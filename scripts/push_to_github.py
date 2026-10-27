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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO = "rayassassin/ai-radix"
BRANCH = "main"


def gh_api(endpoint: str, method: str = "GET", body: dict | None = None) -> dict:
    cmd = ["gh", "api", endpoint, "-X", method]
    if body is not None:
        cmd += ["--input", "-"]
        proc = subprocess.run(
            cmd, input=json.dumps(body).encode("utf-8"),
            capture_output=True, cwd=str(ROOT),
        )
    else:
        proc = subprocess.run(cmd, capture_output=True, cwd=str(ROOT))
    if proc.returncode != 0:
        raise RuntimeError(f"{method} {endpoint} 失败：{proc.stderr.decode('utf-8', 'replace').strip()}")
    out = proc.stdout.decode("utf-8", "replace").strip()
    return json.loads(out) if out else {}


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

    # ---- 1. 逐个文件建 blob ----
    tree = []
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        content = base64.b64encode(f.read_bytes()).decode("ascii")
        # 可执行位要带上，否则 Actions 里 ./update.sh 会报 Permission denied
        mode = "100755" if (f.suffix in (".sh", ".py") or rel.startswith("scripts/")) else "100644"
        res = gh_api(f"repos/{args.repo}/git/blobs", "POST",
                     {"content": content, "encoding": "base64"})
        tree.append({"path": rel, "mode": mode, "type": "blob", "sha": res["sha"]})
        print(f"  ✓ blob {rel}")

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
