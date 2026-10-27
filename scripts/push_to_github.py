#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通过 GitHub Data API 推送本地仓库内容（绕过 git 传输层）

适用场景：所在网络只允许访问 api.github.com，github.com 的 git/ssh 通道不通，
`git push` 必然失败。此时改用 REST API 直接构造 blob → tree → commit → ref。

用法:
  python3 scripts/push_to_github.py                 # 推送当前 HEAD 的全部文件
  python3 scripts/push_to_github.py --repo o/r      # 指定仓库
  python3 scripts/push_to_github.py --dry-run       # 只列出将上传的文件

前提：本机已 `gh auth login`（脚本通过 gh 转发请求，自动带凭证）。
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO = "rayassassin/ai-radix"
BRANCH = "main"


def gh_api(endpoint: str, method: str = "GET", body: dict | None = None,
           retries: int = 4) -> dict:
    """调 gh api。失败重试：慢链路下 TLS 握手偶发超时，一次就放弃等于白推一遍。"""
    cmd = ["gh", "api", endpoint, "-X", method]
    if body is not None:
        cmd += ["--input", "-"]
        payload = json.dumps(body).encode("utf-8")
    else:
        payload = None

    last = ""
    for attempt in range(1, retries + 1):
        proc = subprocess.run(
            cmd, input=payload,
            capture_output=True, cwd=str(ROOT),
        )
        if proc.returncode == 0:
            out = proc.stdout.decode("utf-8", "replace").strip()
            return json.loads(out) if out else {}
        last = proc.stderr.decode("utf-8", "replace").strip()
        if attempt < retries:
            wait = 3 * attempt
            print(f"  ↻ {method} {endpoint} 失败（{last[:60]}），{wait}s 后重试 {attempt}/{retries - 1}")
            time.sleep(wait)
    raise RuntimeError(f"{method} {endpoint} 失败：{last}")


def tracked_files() -> list[Path]:
    """以 git 索引为准，确保 .gitignore 规则生效（不会上传 dist/ logs/ 等）。"""
    proc = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, cwd=str(ROOT), check=True,
    )
    files = []
    for raw in proc.stdout.split(b"\0"):
        if not raw:
            continue
        p = ROOT / raw.decode("utf-8")
        if p.is_file():
            files.append(p)
    return files


def local_blob_sha(path: Path) -> str:
    """算 Git blob sha。同一内容的 blob sha 与 GitHub 上完全一致，可直接比对。"""
    proc = subprocess.run(
        ["git", "hash-object", str(path)], capture_output=True, cwd=str(ROOT), check=True,
    )
    return proc.stdout.decode().strip()


def remote_blobs(repo: str, branch: str) -> dict[str, dict]:
    """远端分支当前的 path → {sha, mode}。取不到就返回空表，退化为全量上传。"""
    try:
        ref = gh_api(f"repos/{repo}/git/ref/heads/{branch}")
        commit = gh_api(f"repos/{repo}/git/commits/{ref['object']['sha']}")
        tree = gh_api(f"repos/{repo}/git/trees/{commit['tree']['sha']}?recursive=1")
    except Exception as e:                        # 空仓库 / 网络问题都不该阻断推送
        print(f"  取远端 tree 失败，本次走全量：{e}")
        return {}
    return {e["path"]: e for e in tree.get("tree", []) if e.get("type") == "blob"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--message", default="")
    ap.add_argument("--branch", default=BRANCH)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = tracked_files()
    if not files:
        print("git 索引为空，先 git add")
        return 1

    print(f"准备上传 {len(files)} 个文件到 {args.repo}（分支 {args.branch}）")
    total = sum(f.stat().st_size for f in files)
    print(f"总体积 {total / 1024:.0f} KB")
    for f in files:
        print(f"  {f.relative_to(ROOT)}  ({f.stat().st_size / 1024:.0f} KB)")

    if args.dry_run:
        return 0

    # ---- 1. 逐个文件建 blob（内容没变且模式一致的复用远端 sha，不重传）----
    remote = remote_blobs(args.repo, args.branch)
    tree = []
    uploaded = reused = 0
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        # 可执行位要带上，否则 Actions 里 ./update.sh 会报 Permission denied
        mode = "100755" if (f.suffix in (".sh", ".py") or rel.startswith("scripts/")) else "100644"
        sha = local_blob_sha(f)
        old = remote.get(rel)
        if old and old.get("sha") == sha and old.get("mode") == mode:
            tree.append({"path": rel, "mode": mode, "type": "blob", "sha": sha})
            reused += 1
            continue
        content = base64.b64encode(f.read_bytes()).decode("ascii")
        res = gh_api(f"repos/{args.repo}/git/blobs", "POST",
                     {"content": content, "encoding": "base64"})
        tree.append({"path": rel, "mode": mode, "type": "blob", "sha": res["sha"]})
        uploaded += 1
        print(f"  ↑ blob {rel}")

    print(f"✓ blob 完成：新传 {uploaded} 个，复用 {reused} 个（内容未变）")

    # ---- 2. 建 tree ----
    tree_res = gh_api(f"repos/{args.repo}/git/trees", "POST", {"tree": tree})
    tree_sha = tree_res["sha"]
    print(f"✓ tree {tree_sha}")

    # ---- 3. 建 commit ----
    message = args.message or "chore: 同步站点内容"
    commit_body = {"message": message, "tree": tree_sha}
    # 已有分支时接上前一个 commit，保证历史连续
    try:
        ref = gh_api(f"repos/{args.repo}/git/ref/heads/{args.branch}")
        parent = ref["object"]["sha"]
        commit_body["parents"] = [parent]
        print(f"  父提交 {parent[:8]}")
    except RuntimeError:
        print("  分支尚不存在，创建首个提交")

    commit_res = gh_api(f"repos/{args.repo}/git/commits", "POST", commit_body)
    commit_sha = commit_res["sha"]
    print(f"✓ commit {commit_sha}")

    # ---- 4. 更新（或创建）分支引用 ----
    try:
        gh_api(f"repos/{args.repo}/git/refs/heads/{args.branch}", "PATCH",
               {"sha": commit_sha, "force": True})
        print(f"✓ 已更新 {args.branch} → {commit_sha[:8]}")
    except RuntimeError:
        gh_api(f"repos/{args.repo}/git/refs", "POST",
               {"ref": f"refs/heads/{args.branch}", "sha": commit_sha})
        print(f"✓ 已创建 {args.branch} → {commit_sha[:8]}")

    print(f"\n完成：https://github.com/{args.repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
