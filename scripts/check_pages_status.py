#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回查 GitHub Pages 构建结果 —— 部署失败主动告警 + 自动重新构建。

为什么需要这个脚本（2026-11-06 的真实事故）：
  publish_pages.py 把 commit 推上去就收工了，完全不知道后续 Pages 构建成功没有。
  11-06 03:05 那轮 GitHub 侧 deploy 卡在 `updating_pages` 状态轮询 10 分钟，
  最后 `Timeout reached, aborting!` 取消部署，而服务器毫无感知 —— 线上数据停更，
  属于典型的「静默失败」。下一轮恰好成功才自动补上，纯属运气。
  本脚本补上结果回查：发现 errored 就自动请求重新构建，并让主流程发企微告警。

检查口径：
  拉取最近 N 次 builds，只看过去 WINDOW_HOURS 小时内 status=errored 的。
  用状态文件按 created_at 去重，同一个失败只告警一次，避免每小时重复打扰。
  正在 queued/building 属正常（本轮刚推上去，构建还没跑完），不告警。

退出码（llm-api-pricing.sh 据此决定是否告警）：
  0  正常（含 built / building / queued）
  1  发现新的部署失败 → 主流程推企微告警
  2  检查本身失败（网络/凭证），只记 WARN 不发告警，避免网络抖动造成噪音

用法:
  python3 scripts/check_pages_status.py
  python3 scripts/check_pages_status.py --dry-run    # 只打印，不重试、不写状态文件
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from publish_pages import DEFAULT_REPO, find_token, api  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "logs" / ".pages_alerted.json"
# 与 publish_pages.py 的 --config 默认值保持一致，别另搞一套查找规则
CONFIG_PATH = Path(os.path.expanduser("~/.ai-radix/config.json"))

WINDOW_HOURS = 3        # 只看最近 3 小时（覆盖 3 轮 cron，避免漏报）
LOOKBACK = 15           # 拉取最近 15 次（每小时一轮，留足余量，别卡在窗口边界漏掉）


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone(timedelta(hours=8))):%Y-%m-%d %H:%M:%S}] {msg}")


def parse_ts(s: str) -> datetime | None:
    """GitHub 返回的是 '2026-11-05T19:05:20Z' 这类 UTC 时间。"""
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def load_state() -> dict:
    try:
        d = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {"alerted": []}
    except (OSError, json.JSONDecodeError):
        return {"alerted": []}


def save_state(state: dict) -> None:
    """原子写，避免 cron 并发写出半个 JSON。"""
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_name(STATE_PATH.name + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(STATE_PATH)
    except OSError as e:
        log(f"状态文件写入失败（不影响本轮判断）：{e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印，不重试、不记状态")
    ap.add_argument("--window-hours", type=float, default=WINDOW_HOURS,
                    help=f"回查窗口小时数（默认 {WINDOW_HOURS}，排查历史失败可调大）")
    args = ap.parse_args()
    window = args.window_hours

    token, source = find_token(CONFIG_PATH)
    if not token:
        # 凭证缺失由 publish_pages.py 负责告警，这里不重复发
        print(f"⚠️  无法回查 Pages 状态：{source}")
        return 2

    try:
        builds = api(token, f"/repos/{DEFAULT_REPO}/pages/builds?per_page={LOOKBACK}")
    except Exception as e:
        print(f"⚠️  回查 Pages 构建状态失败：{type(e).__name__}: {e}")
        return 2
    if not isinstance(builds, list):
        print("⚠️  Pages 构建状态返回格式异常（不是数组）")
        return 2

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=window)
    state = load_state()
    alerted = set(state.get("alerted") or [])

    fresh_failures = []
    for b in builds:
        if not isinstance(b, dict) or b.get("status") != "errored":
            continue
        ts = parse_ts(b.get("created_at") or "")
        if ts is None or ts < cutoff:
            continue
        key = b.get("created_at") or "unknown"
        if key in alerted:
            continue
        fresh_failures.append((key, b))

    latest = builds[0] if builds else {}
    log(f"Pages 最近构建 {len(builds)} 次，最新状态：{latest.get('status', '未知')}"
        f"（{(latest.get('commit') or '')[:7]}）｜近 {window:g}h 新失败 {len(fresh_failures)} 次"
        f"｜凭证来自 {source}")

    if not fresh_failures:
        return 0

    # 发现失败 → 请求一次新的 Pages 构建（GitHub 官方 API，不依赖新 commit）。
    # 失败也不影响告警：重试是尽力而为，告警才是硬要求。
    retried = False
    if not args.dry_run:
        try:
            api(token, f"/repos/{DEFAULT_REPO}/pages/builds", method="POST", body={})
            retried = True
            log("  ↻ 已请求重新构建 Pages（POST /pages/builds）")
        except Exception as e:
            log(f"  ⚠️ 自动重试构建失败（仍会告警）：{type(e).__name__}: {e}")

    for key, b in fresh_failures:
        err = ((b.get("error") or {}).get("message") or "").strip()
        log(f"  ❌ 部署失败 {key}  commit={(b.get('commit') or '')[:7]}"
            f"  {err[:120] or '状态 errored（常见于 GitHub 侧 deploy 超时）'}")
        alerted.add(key)

    if not args.dry_run:
        # 只保留最近 3 天的记录，状态文件别无限长
        keep = [k for k in alerted if (parse_ts(k) or now) > now - timedelta(days=3)]
        save_state({"alerted": sorted(keep), "updated_at": now.isoformat()})

    suffix = "，已自动请求重新构建" if retried else ""
    print(f"GitHub Pages 部署失败 {len(fresh_failures)} 次（近 {window:g}h）"
          f"{suffix}；线上页面可能停更，请留意下一轮是否恢复")
    return 1


if __name__ == "__main__":
    sys.exit(main())
