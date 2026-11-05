#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把抓取产物发布到 GitHub Pages —— 零依赖版（只要 token，不要 git / gh）

为什么单独写一个：
  `push_to_github.py` 依赖 git 索引 + gh CLI，适合开发机整仓发布；
  但服务器上 `/opt/ai-radix` 是 tar 解出来的，**没有 .git**，也没装 gh。
  服务器只需要把每轮抓出来的 data/*.json 更新上去，别的文件一个都不该动。

做法：
  取远端 tree（含全部既有文件）→ 只把目标 JSON 换成新 blob → 建 commit → 移分支。
  data/ 之外的文件原样引用远端 sha，不会重传也不会丢。

增量判断：
  本地算 git blob sha（sha1("blob <len>\\0" + 内容)），与远端 tree 里同路径的 sha 比。
  **全部一致就直接退出，不造空提交** —— 否则每小时一次 cron 会把提交历史刷成垃圾。

用法:
  python3 scripts/publish_pages.py              # 有变化才提交
  python3 scripts/publish_pages.py --dry-run    # 只看会改哪些文件
  python3 scripts/publish_pages.py --force      # 强制提交（调试用）

token 来源（按序，找到就用）:
  1. 环境变量 GITHUB_TOKEN / GH_TOKEN
  2. 本项目 config 的 github.token（默认 ~/.ai-radix/config.json）
  3. env 文件 ~/.ai-radix/github.env 里的 GITHUB_TOKEN=

权限要求：fine-grained PAT，仅需目标仓库的 Contents: Read and write。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO = "rayassassin/ai-radix"
BRANCH = "main"
API = "https://api.github.com"

# 只发布前端真正会读、且由服务器每轮刷新的文件。
# tools.json / providers.json / favicons.json 是本地生成的静态资产，服务器不产出。
PUBLISH_FILES = [
    "data/models.json",
    "data/meta.json",
    "data/daily.json",
    # 厂商图标映射随厂商增减而变，由 build_vendor_icons.py 在抓取后重算
    "data/vendor_icons.json",
]

TOKEN_ENV_NAME = "GITHUB_TOKEN"


def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


# ---------------- token ----------------

def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip("'\"")
    except OSError:
        pass
    return out


def check_token_shape(tok: str) -> str:
    """
    校验 token 形态。返回空串=通过，否则返回人话错误说明。

    为什么要拦：GitHub 对形态不对的 token 只回 401 Bad credentials，
    日志里看就是一句 "Bad credentials"，根本看不出根因。
    而最常见的错法恰恰是把文档示例 github_pat_xxx 整个抄进配置
    —— 这个坑已经真实踩过一次，必须在这里提前拦掉。

    GitHub 凭证的固定形态：
      ghp_/gho_/ghu_/ghs_/ghr_ + 36 位 ≈ 40 字符（classic / OAuth）
      github_pat_ + 82 位         ≈ 93 字符（fine-grained）
    """
    n = len(tok)
    if n < 30 or "xxx" in tok.lower() or tok.endswith("..."):
        return (
            f"token 形态不对：只有 {n} 个字符（真实 token 至少 40）。\n"
            f"   基本可以确定是把文档里的占位符（github_pat_xxx）原样抄进了配置。\n"
            f"   正确做法：GitHub → Settings → Developer settings → Personal access tokens\n"
            f"   → Fine-grained tokens → 新建，仓库只选 ai-radix，权限只勾 Contents: Read and write\n"
            f"   生成后完整复制（约 93 字符），不要带引号、不要带 GITHUB_TOKEN= 前缀。"
        )
    if tok.startswith("github_pat_") and n < 70:
        return (
            f"token 被截断了：github_pat_ 开头但只有 {n} 字符（fine-grained PAT 通常 93 字符）。"
            f"请重新完整复制。"
        )
    return ""


def find_token(config_path: Path) -> tuple[str, str]:
    """返回 (token, 来源说明)；找不到或形态不对时返回 ("", 错误说明)。"""
    found, source = "", ""

    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        v = os.environ.get(name, "").strip()
        if v:
            found, source = v, f"环境变量 {name}"
            break

    if not found:
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cfg = {}
        v = str(((cfg.get("github") or {}).get("token")) or "").strip()
        if v:
            found, source = v, f"配置 {config_path}"

    if not found:
        env_file = Path(os.path.expanduser("~/.ai-radix/github.env"))
        v = read_env_file(env_file).get(TOKEN_ENV_NAME, "").strip()
        if v:
            found, source = v, f"env 文件 {env_file}"

    if found:
        err = check_token_shape(found)
        if err:
            return "", f"{source} 里的 token 用不了（这一轮不会发布）。\n  {err}"
        return found, source

    return "", (
        f"未找到 GitHub token。三种放法任选其一：\n"
        f"    a) 写进 {config_path} 的 github.token\n"
        f"    b) 写入 ~/.ai-radix/github.env：{TOKEN_ENV_NAME}=<你的真实token>\n"
        f"    c) 环境变量 {TOKEN_ENV_NAME}（cron 里不方便）\n"
        f"  权限只需目标仓库的 Contents: Read and write。"
    )


# ---------------- HTTP ----------------

def api(token: str, endpoint: str, method: str = "GET",
        body: dict | None = None, retries: int = 3) -> dict:
    """调 GitHub REST。慢链路下单次 TLS 握手会偶发超时，必须重试。"""
    url = endpoint if endpoint.startswith("http") else f"{API}{endpoint}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    last = ""
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "ai-radix-publisher")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            # 4xx 除限流外重试没意义，直接抛
            if e.code < 500 and e.code != 429:
                raise RuntimeError(f"{method} {endpoint} → HTTP {e.code}：{detail}")
            last = f"HTTP {e.code} {detail}"
        except Exception as e:                       # 超时 / DNS / 连接重置
            last = f"{type(e).__name__}: {e}"
        if attempt < retries:
            wait = 2 ** attempt
            log(f"  ↻ {method} {endpoint} 失败（{last[:70]}），{wait}s 后重试 {attempt}/{retries - 1}")
            time.sleep(wait)
    raise RuntimeError(f"{method} {endpoint} 失败：{last}")


# ---------------- git blob ----------------

def blob_sha(data: bytes) -> str:
    """Git blob sha1。内容一致则 sha 一致，可直接与远端比对，省掉整轮重传。"""
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def remote_tree(token: str, repo: str, branch: str) -> tuple[str, dict[str, str], dict[str, str]]:
    """返回 (父提交 sha, {path: blob sha}, {path: mode})。分支不存在时抛错。"""
    ref = api(token, f"/repos/{repo}/git/ref/heads/{branch}")
    parent = ref["object"]["sha"]
    commit = api(token, f"/repos/{repo}/git/commits/{parent}")
    tree = api(token, f"/repos/{repo}/git/trees/{commit['tree']['sha']}?recursive=1")
    shas, modes = {}, {}
    for e in tree.get("tree", []):
        if e.get("type") != "blob":
            continue
        shas[e["path"]] = e["sha"]
        modes[e["path"]] = e.get("mode", "100644")
    return parent, shas, modes


# ---------------- 部署结果验证 ----------------

def previous_deploy_failed(token: str, repo: str) -> tuple[bool, str]:
    """
    检查**上一轮** Pages 部署是否失败。

    为什么必须有这一步：GitHub 部署端卡住时，要等约 11 分钟才把 build 标成 errored
    （2026-11-05 两次失败都是 19:05 启动、19:16 `Timeout reached`），
    远长于本轮愿意等待的 120 秒窗口。光靠「提交后轮询」会漏掉这类慢失败，
    结果就是失败发生了、脚本却说「Pages 会自动重建」—— 又回到静默。
    所以由下一轮开头兜底巡检一次，发现 errored 就告警 + 强制重建（自愈）。
    """
    try:
        b = api(token, f"/repos/{repo}/pages/builds/latest", retries=1)
    except Exception:
        return False, ""
    if (b.get("status") or "").lower() != "errored":
        return False, ""
    err = ((b.get("error") or {}).get("message")) or "Page build failed"
    return True, f"上一轮 Pages 部署失败（{str(b.get('commit', ''))[:8]}）：{err}"


def verify_deployment(token: str, repo: str, commit_sha: str,
                      wait_sec: int = 120, interval: int = 15) -> tuple[str, str]:
    """
    **commit 推上去 ≠ 页面上线。** Pages 的 build + deploy 是独立一步，
    而 GitHub 部署端会偶发卡在 `updating_pages` 直到超时 ——
    2026-11-05 凌晨真实发生过 2 次（build 成功、deploy `Timeout reached, aborting!`）。

    旧代码只打印「✓ 已发布 …（Pages 会自动重建）」就返回 0，
    部署失败时脚本照样报成功，cron.log 里连一条 WARN 都没有 —— 典型的静默失败。
    这里补上验证：按 commit sha 认领本次构建，轮询到出结果为止。

    返回 (status, message)：
      built    部署成功
      errored  部署失败（调用方应告警，退出码 4）
      pending  仍在构建 / 查询不到，**不判失败**（记 WARN，下轮继续验）
               —— 权限收窄后可能读不到 pages builds，不能让每轮误报。
    """
    deadline = time.time() + wait_sec
    target = commit_sha[:8]
    while True:
        try:
            b = api(token, f"/repos/{repo}/pages/builds/latest", retries=1)
        except Exception as e:
            return "pending", (f"查不到 Pages 部署状态（token 权限或网络：{type(e).__name__}）"
                               f"，不判失败")
        got = (b.get("commit") or "")[:8]
        st = b.get("status") or "unknown"
        if got == target:
            if st == "built":
                return "built", f"Pages 部署成功（{target}）"
            if st in ("errored", "cancelled", "canceled"):
                err = ((b.get("error") or {}).get("message")) or "GitHub 部署端超时/失败"
                return "errored", f"Pages 部署失败（{target}）：{err}"
        last = f"latest={got or '?'} status={st}"
        if time.time() >= deadline:
            return "pending", f"等待 Pages 部署超时，{last}（不判失败，下轮继续验）"
        time.sleep(interval)


# ---------------- 主流程 ----------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--branch", default=BRANCH)
    ap.add_argument("--config", default=os.path.expanduser("~/.ai-radix/config.json"))
    ap.add_argument("--message", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="内容无变化也提交（调试）")
    args = ap.parse_args()

    config_path = Path(args.config)
    dry = args.dry_run

    # ---- 本地产物清单 ----
    local: dict[str, bytes] = {}
    for rel in PUBLISH_FILES:
        p = ROOT / rel
        if not p.is_file():
            log(f"⚠️  跳过缺失文件 {rel}")
            continue
        local[rel] = p.read_bytes()
    if not local:
        log("没有任何可发布的数据文件，退出")
        return 1

    token, source = find_token(config_path)
    if not token:
        log("❌ " + source)
        return 2

    log(f"目标 {args.repo}@{args.branch}，待发布 {len(local)} 个文件，凭证来自{source}")

    prev_failed, prev_msg = previous_deploy_failed(token, args.repo)
    if prev_failed and not dry:
        log(f"⚠️  {prev_msg}")
        log("    → 本轮强制提交一次，触发 Pages 重建（自愈）")
        args.force = True

    parent, rshas, rmodes = remote_tree(token, args.repo, args.branch)

    # ---- 判断哪些内容真的变了 ----
    changed = {rel: body for rel, body in local.items()
               if rshas.get(rel) != blob_sha(body)}
    if not changed and not args.force:
        log("数据无变化，不提交（远端已是这份内容）")
        return 0

    for rel in local:
        mark = "改动" if rel in changed else "未变"
        log(f"  {mark}  {rel}  ({len(local[rel]) / 1024:.0f} KB)")

    if dry:
        log(f"[dry-run] 将更新 {len(changed)} 个文件，父提交 {parent[:8]}")
        return 0

    # ---- 建 blob ----
    tree_entries = []
    uploaded = reused = 0
    for path, sha in rshas.items():
        if path in local:
            continue                                  # 目标文件稍后替换
        tree_entries.append({"path": path, "mode": rmodes.get(path, "100644"),
                             "type": "blob", "sha": sha})
        reused += 1

    for rel, body in local.items():
        if rel not in changed:
            tree_entries.append({"path": rel, "mode": "100644",
                                 "type": "blob", "sha": rshas[rel]})
            continue
        res = api(token, f"/repos/{args.repo}/git/blobs", "POST", {
            "content": base64.b64encode(body).decode("ascii"),
            "encoding": "base64",
        })
        tree_entries.append({"path": rel, "mode": "100644",
                             "type": "blob", "sha": res["sha"]})
        uploaded += 1

    log(f"blob：新传 {uploaded} 个，沿用远端 {reused} 个")

    tree_res = api(token, f"/repos/{args.repo}/git/trees", "POST", {"tree": tree_entries})
    commit_res = api(token, f"/repos/{args.repo}/git/commits", "POST", {
        "message": args.message or f"data: 自动同步 {time.strftime('%Y-%m-%d %H:%M')}",
        "tree": tree_res["sha"],
        "parents": [parent],
    })
    api(token, f"/repos/{args.repo}/git/refs/heads/{args.branch}", "PATCH",
        {"sha": commit_res["sha"], "force": True})

    log(f"✓ 已提交 {commit_res['sha'][:8]} → {args.branch}")

    # 提交只是把 commit 推上去，部署是独立一步 —— 必须验证，
    # 否则 GitHub 部署端超时这类失败会完全静默（宇神红线：失败必须告警）。
    status, msg = verify_deployment(token, args.repo, commit_res["sha"])
    if status == "built":
        log(f"✓ {msg}，页面已更新")
        return 0
    if status == "errored":
        log(f"❌ {msg}（commit 已推送，下一轮构建会自动带上最新数据）")
        return 4           # 让 llm-api-pricing.sh 触发企微告警
    log(f"⚠️  {msg}")
    if prev_failed:
        # 上一轮确实失败了，本轮虽已强制提交但还没确认重建成功 —— 必须告警，不能静默
        log(f"❌ {prev_msg}；本轮重建尚未确认（{status}）")
        return 5
    return 0


if __name__ == "__main__":
    sys.exit(main())
