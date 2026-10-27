#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 大事记 · 抓取脚本

数据来源：AIHOT（https://aihot.news）公开 API v1
  官方文档 https://aihot.news/api/v1/agent 明确说明：程序化定时同步、维护本地副本
  应当用 JSON 接口而不是 Agent 的 Markdown 端点，User-Agent 需为 aihot-api/2.0.0。

接口：
  GET /api/v1/dailies?limit=N     日报列表（date / leadTitle / leadParagraph / links）
  GET /api/v1/dailies/{date}      单期详情（lead + sections[].items[]，带来源与原文链接）

产出 data/daily.json，供 daily.html 渲染。

注意：只取标题、摘要与链接，并为每条内容保留 AIHOT 署名与原文地址；
页面必须回链 AIHOT，不得当作自有内容分发。

用法:
  python3 scripts/fetch_daily.py                # 默认抓最近 30 天
  python3 scripts/fetch_daily.py --days 90      # 抓 90 天
  python3 scripts/fetch_daily.py --date 2026-10-27   # 只补某一天
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "daily.json"

BASE = "https://aihot.news"
# 官方要求：程序化同步走 JSON 接口并带这个 UA
HEADERS = {
    "User-Agent": "aihot-api/2.0.0",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",       # 日报详情 10KB 级，压缩后传输更快
}
TIMEOUT = 25
MAX_RETRY = 3
MIN_GAP = 1.2          # 秒；官方限流 60 次/分钟，留足余量
TZ_CN = timezone(timedelta(hours=8))

_last_call = 0.0


def log(msg: str) -> None:
    print(msg, flush=True)


def api(path: str) -> dict | None:
    """
    带节流与重试的 GET（仅标准库，避免服务器装包）。
    429 按 Retry-After 等待，5xx 退避重试。
    """
    global _last_call
    url = BASE + path
    for attempt in range(1, MAX_RETRY + 1):
        gap = time.time() - _last_call
        if gap < MIN_GAP:
            time.sleep(MIN_GAP - gap)
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read()
                _last_call = time.time()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            _last_call = time.time()
            if e.code == 429:
                wait = int(e.headers.get("Retry-After") or 10)
                log(f"  触发限流，等待 {wait}s")
                time.sleep(wait)
                continue
            if 500 <= e.code < 600 and attempt < MAX_RETRY:
                time.sleep(3 * attempt)
                continue
            log(f"  HTTP {e.code}：{path}")
            return None
        except Exception as e:
            _last_call = time.time()
            if attempt == MAX_RETRY:
                log(f"  请求异常 {type(e).__name__}: {path}")
                return None
            time.sleep(2 * attempt)
    return None


def norm_day(report: dict) -> dict:
    """把单期日报压成前端直接能用的结构。"""
    lead = report.get("lead") or {}
    sections = []
    for sec in (report.get("sections") or []):
        items = []
        for it in (sec.get("items") or []):
            links = it.get("links") or {}
            items.append({
                "title": (it.get("title") or "").strip(),
                "summary": (it.get("summary") or "").strip(),
                "source": ((it.get("source") or {}).get("name") or "").strip(),
                "url": links.get("aihot") or "",
                "original": links.get("original") or "",
            })
        if items:
            sections.append({"label": (sec.get("label") or "其他").strip(), "items": items})
    return {
        "date": report.get("date") or "",
        "generated_at": report.get("generatedAt") or "",
        "window_start": report.get("windowStart") or "",
        "window_end": report.get("windowEnd") or "",
        "lead": {
            "title": (lead.get("title") or "").strip(),
            "paragraph": (lead.get("leadParagraph") or "").strip(),
        },
        "url": ((report.get("links") or {}).get("aihot")
                or f"{BASE}/daily/{report.get('date', '')}"),
        "sections": sections,
        "event_count": sum(len(s["items"]) for s in sections),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="抓最近多少天（默认 30）")
    ap.add_argument("--date", default=None, help="只补某一天，格式 2026-10-27")
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    prev = {}
    if OUT.exists():
        try:
            prev = {d["date"]: d for d in json.loads(OUT.read_text(encoding="utf-8")).get("days", [])}
        except Exception:
            prev = {}

    # ---------- 1. 取日期清单 ----------
    if args.date:
        dates = [args.date]
    else:
        listing = api(f"/api/v1/dailies?limit={max(1, min(args.days, 200))}")
        if not listing:
            log("日报列表获取失败，保留上一版数据")
            return 1
        dates = [x["date"] for x in (listing.get("items") or []) if x.get("date")]
        log(f"列表返回 {len(dates)} 期（{dates[-1] if dates else '—'} ~ {dates[0] if dates else '—'}）")

    # ---------- 2. 逐日取详情 ----------
    days, fetched, reused, failed = {}, 0, 0, []
    for i, d in enumerate(dates, 1):
        if d in prev and not args.date:
            days[d] = prev[d]        # 历史日报不会变，直接复用省请求
            reused += 1
            continue
        got = api(f"/api/v1/dailies/{d}")
        if not got or not got.get("report"):
            failed.append(d)
            log(f"[{i}/{len(dates)}] ✗ {d}")
            continue
        days[d] = norm_day(got["report"])
        fetched += 1
        log(f"[{i}/{len(dates)}] ✓ {d}  {days[d]['event_count']} 条事件 · {days[d]['lead']['title'][:30]}")

    if not days:
        log("没有拿到任何一期，保留上一版数据")
        return 1

    ordered = [days[k] for k in sorted(days, reverse=True)]
    total_events = sum(d["event_count"] for d in ordered)
    OUT.write_text(json.dumps({
        "source": "AIHOT",
        "source_url": f"{BASE}/daily",
        "source_note": "标题、摘要与链接版权归 AIHOT 及各原始信源所有，此处仅作索引与引用，"
                       "详情请前往原文。",
        "api_doc": f"{BASE}/api/v1/agent",
        "fetched_at": datetime.now(TZ_CN).strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(ordered),
        "event_total": total_events,
        "earliest": ordered[-1]["date"],
        "latest": ordered[0]["date"],
        "days": ordered,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    size = OUT.stat().st_size / 1024
    log("\n" + "─" * 56)
    log(f"共 {len(ordered)} 期｜{total_events} 条事件｜新抓 {fetched}、复用 {reused}")
    log(f"时间范围 {ordered[-1]['date']} ~ {ordered[0]['date']}")
    log(f"已写入 {OUT.relative_to(ROOT)}（{size:.0f} KB）")
    if failed:
        log(f"失败 {len(failed)} 期：{', '.join(failed[:8])}")
    log("─" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
