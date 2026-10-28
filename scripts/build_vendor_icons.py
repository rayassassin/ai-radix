#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成厂商图标映射 data/vendor_icons.json —— 复用工具集已抓好的 favicon。

为什么要一张手工映射表：
  models.json 的厂商 key 是 OpenRouter 的 slug（openai / moonshotai / x-ai），
  favicons.json 的 key 是工具集的 id（chatgpt / kimi / grok），两套命名毫无对应关系，
  也没有共同的外键。硬做模糊匹配只会把厂商配错图标，比没有图标更糟。
  所以：手工列出能对上的，剩下的降级成原来的色点。

复用而不是重新抓：
  assets/icons/ 里已经有 217 个 64×64 透明 PNG，都是 fetch_favicons.py 四路降级抓下来的。
  同一家公司的 C 端产品图标就是它最易认的 logo，没必要为了「厂商图」再抓一遍。

用法:
  python3 scripts/build_vendor_icons.py            # 生成并打印覆盖率
  python3 scripts/build_vendor_icons.py --dry-run  # 只看不写
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "data" / "models.json"
FAVICONS = ROOT / "data" / "favicons.json"
VENDOR_FAVICONS = ROOT / "data" / "vendor_favicons.json"   # fetch_vendor_icons.py 的产出
ICON_DIR = ROOT / "assets" / "icons"
OUT = ROOT / "data" / "vendor_icons.json"

# 厂商 slug → 工具集 id。
# 选取原则：优先用该厂商最具辨识度的 C 端产品（OpenAI→ChatGPT、月之暗面→Kimi），
# 其次用官方开发者站点（腾讯混元、阶跃星辰）。
# 没有对应工具的厂商不列在这里，前端会自动降级成色点。
VENDOR_TO_TOOL: dict[str, str] = {
    "openai": "chatgpt",
    "anthropic": "claude",
    "google": "gemini",
    "deepseek": "deepseek-chat",
    "qwen": "qwen-chat",
    "moonshotai": "kimi",
    "bytedance": "doubao",
    "bytedance-seed": "doubao",
    "z-ai": "智谱清言",
    "minimax": "海螺ai",
    "x-ai": "grok",
    "mistralai": "le-chat",
    "microsoft": "microsoft-365-copilot",
    "amazon": "amazon-q-developer",
    "tencent": "hunyuan",
    "stepfun": "stepfun",
    "perplexity": "perplexity",
    "openrouter": "openrouter",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印结果，不写文件")
    args = ap.parse_args()

    if not MODELS.is_file():
        print(f"❌ 缺少 {MODELS}", file=sys.stderr)
        return 1
    models = json.loads(MODELS.read_text(encoding="utf-8"))
    if not isinstance(models, list):
        print("❌ models.json 不是数组", file=sys.stderr)
        return 1

    favicons: dict = {}
    if FAVICONS.is_file():
        favicons = json.loads(FAVICONS.read_text(encoding="utf-8")) or {}

    # 厂商 → 模型数，用来算覆盖率（按模型加权比按厂商数更有意义：
    # 59 个厂商里 40 个只有 1-2 个模型，覆盖它们对页面观感几乎没影响）
    per_vendor = Counter(m.get("vendor") for m in models if m.get("vendor"))
    total_models = sum(per_vendor.values())

    icons: dict[str, dict] = {}
    missing_tool: list[str] = []
    n_own = n_reuse = 0

    # 优先级：厂商官网自抓（data/vendor_favicons.json）> 工具集复用。
    # 官网图标更贴厂商本身；同一个厂商两边都有时以自抓为准。
    own: dict = {}
    if VENDOR_FAVICONS.is_file():
        try:
            own = (json.loads(VENDOR_FAVICONS.read_text(encoding="utf-8")) or {}).get("icons", {})
        except json.JSONDecodeError:
            own = {}

    for vendor in sorted(per_vendor):
        vf = own.get(vendor)
        if vf and vf.get("f") and (ICON_DIR / vf["f"]).is_file():
            icons[vendor] = {"f": vf["f"], "t": vf.get("t", "normal"), "from": "官网自抓"}
            n_own += 1
            continue

        tool_id = VENDOR_TO_TOOL.get(vendor)
        if not tool_id:
            continue
        fav = favicons.get(tool_id)
        if not fav or not fav.get("f"):
            missing_tool.append(f"{vendor}({tool_id})")
            continue
        icons[vendor] = {
            "f": fav["f"],
            "t": fav.get("t", "normal"),
            "from": tool_id,
        }
        n_reuse += 1

    covered = sum(per_vendor[v] for v in icons)
    uncovered = [(v, n) for v, n in per_vendor.most_common() if v not in icons]

    payload = {
        "meta": {
            "generated_at": (datetime.now(timezone(timedelta(hours=8)))).strftime("%Y-%m-%d %H:%M:%S"),
            "vendors_total": len(per_vendor),
            "vendors_with_icon": len(icons),
            "models_total": total_models,
            "models_with_icon": covered,
        },
        "icons": icons,
    }

    print(f"厂商 {len(per_vendor)} 个，{len(icons)} 个有图标"
          f"（官网自抓 {n_own} + 工具集复用 {n_reuse}）")
    print(f"模型覆盖 {covered}/{total_models}（{covered / total_models * 100:.0f}%）")
    if missing_tool:
        print(f"\n⚠️ 映射了但工具图标缺失：{', '.join(missing_tool)}")
    if uncovered:
        print("\n未覆盖的厂商（前端降级为色点）：")
        for v, n in uncovered[:15]:
            print(f"  {v:22s} {n} 个模型")
        if len(uncovered) > 15:
            print(f"  …… 另有 {len(uncovered) - 15} 个")

    if args.dry_run:
        print("\n(--dry-run，未写入)")
        return 0

    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\n✅ 已写入 {OUT.relative_to(ROOT)}（{OUT.stat().st_size / 1024:.1f} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
