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


def find_token(config_path: Path) -> tuple[str, str]:
    """返回 (token, 来源说明)。找不到就给空串和引导文案。"""
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        v = os.environ.get(name, "").strip()
        if v:
            return v, f"环境变量 {name}"

    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cfg = {}
    v = str(((cfg.get("github") or {}).get("token")) or "").strip()
    if v:
        return v, f"配置 {config_path}"

    env_file = Path(os.path.expanduser("~/.ai-radix/github.env"))
    v = read_env_file(env_file).get(TOKEN_ENV_NAME, "").strip()
    if v:
        return v, f"env 文件 {env_file}"

    return "", (
        f"未找到 GitHub token。三种放法任选其一：\n"
        f"    a) 写进 {config_path} 的 github.token\n"
        f"    b) 写入 ~/.ai-radix/github.env：{TOKEN_ENV_NAME}=github_pat_xxx\n"
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

    log(f"✓ 已发布 {commit_res['sha'][:8]} → {args.branch}（Pages 会自动重建）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
