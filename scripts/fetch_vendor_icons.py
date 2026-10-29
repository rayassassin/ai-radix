#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抓取厂商官网 favicon → assets/icons/，映射写入 data/vendor_favicons.json。

和 build_vendor_icons.py 的分工：
  本脚本负责「抓」，一次性/偶尔跑，结果作为静态资产提交进仓库；
  build_vendor_icons.py 负责「映射」，每轮 llm-api-pricing.sh 都会跑，只做 JSON 合并。
  分开的理由：抓外网要数分钟且依赖网络，绝不能挂在每小时 cron 上。

数据来源优先级（与 build_vendor_icons 一致）：
  data/vendor_favicons.json（本脚本产出）> 工具集 favicons.json 复用

域名表里的空值表示「没有官网」，比如 HuggingFace 上的个人作者（sao10k、undi95）。
这些厂商前端会降级成色点，不强行造图标。

用法:
  python3 scripts/fetch_vendor_icons.py                # 抓全部缺图标的厂商
  python3 scripts/fetch_vendor_icons.py --only nvidia cohere
  python3 scripts/fetch_vendor_icons.py --force        # 已有也重抓
  python3 scripts/fetch_vendor_icons.py --workers 6

需要 requests（本机用 ~/.workbuddy/binaries/python/envs/default/bin/python 跑）。
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_favicons import (  # noqa: E402  探测逻辑只保留一份，见 probe_icon
    ICON_DIR,
    ROOT,
    probe_icon,
)

DATA = ROOT / "data"
OUT = DATA / "vendor_favicons.json"

# 厂商 slug → 官网。空串/缺省 = 没有官网，跳过。
# 只写有把握的域名；写错的域名抓不到东西会自动失败，不会配错图标。
VENDOR_SITES: dict[str, str] = {
    # ---- 大厂 ----
    "nvidia": "https://www.nvidia.com",
    "meta": "https://ai.meta.com",
    "meta-llama": "https://www.llama.com",
    "cohere": "https://cohere.com",
    "xiaomi": "https://www.mi.com",
    "ibm-granite": "https://www.ibm.com/favicon.ico",   # 首页声明的是 CMS 通用图标，必须直取 favicon.ico
    "meituan": "https://www.meituan.com",
    "writer": "https://writer.com",
    "typesafe": "https://www.typesafe.com",
    # ---- 模型公司 ----
    "sakana": "https://sakana.ai",
    "thinkingmachines": "https://thinkingmachines.ai",
    "poolside": "https://poolside.ai",
    "liquid": "https://www.liquid.ai",
    "upstage": "https://www.upstage.ai",
    "rekaai": "https://www.reka.ai",
    "relace": "https://www.relace.ai",
    "morph": "https://morphllm.com",
    "moondream": "https://moondream.ai",
    "nousresearch": "https://nousresearch.com",
    "inference-net": "https://inference.net",
    "inception": "https://www.inceptionai.ai",
    "aion-labs": "https://aionlabs.ai",
    "fireworks": "https://fireworks.ai",
    "mancer": "https://mancer.tech",
    "scaledown": "https://scaledown.ai",
    "perceptron": "https://www.perceptron.inc",
    "nex-agi": "https://nexagi.com",
    "inclusionai": "https://www.inclusionai.cn",
    "xingchen-agi": "https://xingchen.iflytek.com",
    "dots-studio": "https://dots.ai",
    "recursive": "https://recursive.com",
    # ---- 社区作者（无官网，留空表示跳过）----
    "unbiased": "",
    "thedrummer": "",
    "sao10k": "",
    "anthracite-org": "",
    "gryphe": "",
    "undi95": "",
    "prism-ml": "",
    "reflection": "",
    "cognitivecomputations": "",
    "elorian": "",
}

# 永久跳过：有官网，但**抓到的图案本身不适合当品牌图标**。
# 这类即使抓成功也不可用，写进来省得每次重抓一遍。
# 判据只看图案内容（EDA：是否是可辨识的品牌标识），跟网络无关。
SKIP: dict[str, str] = {
    "ibm-granite": "ibm.com/favicon.ico 里装的是一只蜜蜂图案，不是 IBM 品牌标识",
    "nousresearch": "官网 favicon 是作者插画（动漫人物），不适合当品牌图标",
    "thinkingmachines": "apple-touch-icon 是纯色底板，64px 下没有任何可辨图案",
    "typesafe": "typesafe.com 跳转到 Akka，抓到的是别家 logo",
}
# ⚠️ 曾经写在这里、但**属于网络问题**的（meta/meta-llama/inclusionai 连接超时、
#    writer Cloudflare 403、rekaai/recursive/aion-labs 官网 404、mancer 非图片、
#    xingchen-agi 连接失败）已于 2026-10-29 全部移出，交还给探测流程重试。
#    原因：这类失败随网络环境和「有没有镜像兜底」而变，写死等于永久判死刑；
#    而 403/本机连不通恰恰是镜像兜底最擅长救的两类场景。
#    做法原则：**只有「图案不合适」才写进 SKIP，网络失败让它每轮重试。**


def grab_vendor(vendor: str, page: str) -> dict:
    """
    抓一个厂商图标 —— 探测过程**完全复用** fetch_favicons.probe_icon。

    2026-10-29 之前这里自己写了一遍候选列表，漏了「镜像兜底」那一级，
    于是工具集 217 张图标顺利到手、厂商列却大面积缺图。
    现在只剩两件事：拼出加前缀的 key，以及把字段换成 vendor 口径。
    """
    # key 加前缀是为了让文件名哈希和工具集图标错开，避免撞车
    r = probe_icon(f"vendor:{vendor}", page)
    return {"vendor": vendor, "file": r.get("file"), "src": r.get("src", ""),
            "fmt": r.get("fmt"), "tone": r.get("tone", "normal"),
            "note": r.get("note", ""), "blob": r.get("blob")}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    ICON_DIR.mkdir(parents=True, exist_ok=True)

    # 已抓过的直接复用（除非 --force），避免每次全量重来
    prev: dict = {}
    if OUT.is_file():
        try:
            prev = (json.loads(OUT.read_text(encoding="utf-8")) or {}).get("icons", {})
        except json.JSONDecodeError:
            prev = {}
    # 早期抓错的（插画/通用图标/别家 logo）要能从已有结果里剔除
    for v in list(prev):
        if v in SKIP:
            prev.pop(v)

    targets = {v: s for v, s in VENDOR_SITES.items() if s and v not in SKIP}
    if args.only:
        targets = {v: s for v, s in targets.items() if v in set(args.only)}

    if SKIP:
        print(f"按 SKIP 表跳过 {len(SKIP)} 家（有官网但图标不可用）：")
        for v, why in SKIP.items():
            print(f"  - {v:20s} {why}")

    todo = []
    for v, site in targets.items():
        if not args.force and v in prev and (ICON_DIR / prev[v]["f"]).is_file():
            continue
        todo.append((v, site))

    print(f"待抓 {len(todo)} 家（已有 {len(prev)} 家复用），并发 {args.workers}")

    results: dict[str, dict] = dict(prev)
    ok = fail = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(grab_vendor, v, s): v for v, s in todo}
        for fut in as_completed(futs):
            v = futs[fut]
            try:
                r = fut.result()
            except Exception as e:                      # 单家失败不影响整体
                r = {"vendor": v, "file": None, "note": f"异常 {type(e).__name__}"}
            if r.get("file") and r.get("blob"):
                (ICON_DIR / r["file"]).write_bytes(r["blob"])
                results[v] = {"f": r["file"], "t": r.get("tone", "normal"),
                              "src": r.get("src", ""), "note": r.get("note", "")}
                ok += 1
                print(f"  ✅ {v:22s} {r['note']:10s} {r.get('src', '')[:62]}")
            else:
                fail += 1
                print(f"  ❌ {v:22s} {r.get('note', '')}")

    OUT.write_text(json.dumps({"icons": results}, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print(f"\n成功 {ok} 家、失败 {fail} 家，累计 {len(results)} 家")
    print(f"映射已写入 {OUT.relative_to(ROOT)}")
    if fail:
        print("失败的厂商前端会降级为色点；确认域名无误后可重跑。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
