#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回查 GitHub Pages 构建结果 —— 部署失败主动告警（只告警，不自动重建）。

为什么需要这个脚本（2026-11-06 的真实事故）：
  publish_pages.py 把 commit 推上去就收工了，完全不知道后续 Pages 构建成功没有。
  11-06 03:05 那轮 GitHub 侧 deploy 卡在 `updating_pages` 状态轮询 10 分钟，
  最后 `Timeout reached, aborting!` 取消部署，而服务器毫无感知 —— 线上数据停更，
  属于典型的「静默失败」。本脚本补上结果回查，让主流程能主动告警。

⚠️ 2026-11-07 的教训：绝不能自动 POST /pages/builds 重建。
  本项目每小时推一个新 commit，GitHub 自己就会触发构建、天然具备自愈能力。
  手动 POST 会和自动构建抢并发：GitHub 取消先到的那次，把它记成 errored/cancelled，
  后到的成功记为 built —— 于是同一 commit 3 秒内「先 errored 后 built」成对出现。
  下一轮回查又看到这个新 errored，再 POST，再造一个 errored …… 自激循环，
  每小时稳定产生一条「部署异常」误报告警。真凶是重试动作本身，不是 GitHub。

检查口径：
  拉取最近 N 次 builds，只看过去 WINDOW_HOURS 小时内 status=errored 的，
  且该失败之后**没有任何一次成功构建**（有 = 已自愈，跳过）。
  用状态文件按 created_at 去重，同一个失败只告警一次。
  正在 queued/building 属正常（本轮刚推上去，构建还没跑完），不告警。

退出码（llm-api-pricing.sh 据此决定是否告警）：
  0  正常（含 built / building / queued，以及已被后续成功覆盖的历史 errored）
  1  发现尚未恢复的部署失败 → 主流程推企微告警
  2  检查本身失败（网络/凭证），只记 WARN 不发告警，避免网络抖动造成噪音

用法:
  python3 scripts/check_pages_status.py
  python3 scripts/check_pages_status.py --dry-run    # 只打印，不写状态文件
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

    # API 返回倒序，这里统一按时间正序处理，方便判断「之后有没有成功」。
    stamped: list[tuple[datetime, dict]] = []
    for b in builds:
        if not isinstance(b, dict):
            continue
        ts = parse_ts(b.get("created_at") or "")
        if ts is not None:
            stamped.append((ts, b))
    stamped.sort(key=lambda x: x[0])
    success_times = [ts for ts, b in stamped if b.get("status") == "built"]

    fresh_failures = []
    recovered = 0
    for ts, b in stamped:
        if b.get("status") != "errored" or ts < cutoff:
            continue
        # 关键闸门：之后只要有过一次成功构建，就说明服务已自愈。
        # GitHub 并发构建被取消产生的 errored，紧接着 2-3 秒就有同 commit 的 built，
        # 全都会在这里被滤掉 —— 2026-11-07 每小时误报就是漏了这一层。
        if any(s > ts for s in success_times):
            recovered += 1
            continue
        key = b.get("created_at") or "unknown"
        if key in alerted:
            continue
        fresh_failures.append((key, b))

    latest = builds[0] if builds else {}
    log(f"Pages 最近构建 {len(builds)} 次，最新状态：{latest.get('status', '未知')}"
        f"（{(latest.get('commit') or '')[:7]}）｜近 {window:g}h 未恢复失败 "
        f"{len(fresh_failures)} 次 / 已自愈 {recovered} 次｜凭证来自 {source}")

    if not fresh_failures:
        return 0

    # 刻意不自动 POST /pages/builds：每小时的新 commit 本身就是重建触发器，
    # 手动重建只会和 GitHub 自动构建撞车，反过来制造新的 errored（详见文件头注释）。
    # 这里只负责如实告警，自愈交给下一轮正常发布。
    for key, b in fresh_failures:
        err = ((b.get("error") or {}).get("message") or "").strip()
        log(f"  ❌ 部署失败 {key}  commit={(b.get('commit') or '')[:7]}"
            f"  {err[:120] or '状态 errored（常见于 GitHub 侧 deploy 超时）'}")
        alerted.add(key)

    if not args.dry_run:
        # 只保留最近 3 天的记录，状态文件别无限长
        keep = [k for k in alerted if (parse_ts(k) or now) > now - timedelta(days=3)]
        save_state({"alerted": sorted(keep), "updated_at": now.isoformat()})

    print(f"GitHub Pages 部署失败 {len(fresh_failures)} 次（近 {window:g}h）且尚未恢复；"
          f"下一轮新 commit 会自动触发重建，请留意是否恢复")
    return 1


if __name__ == "__main__":
    sys.exit(main())
