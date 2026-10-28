#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIRadix · LLM Radar · 价格判定回归测试

跑法：python3 scripts/selftest_price.py

为什么留这个文件：2026-10-28 出过一次真实误报 ——
`z-ai/glm-5.3-flash` 做了 4 小时促销（0.15 → 0.0453 → 0.15），
旧口径拿「上一次抓取值」做锚点，把「促销结束」算成了「涨 578%」推进群，
用户看到的是「暴涨」，而牌价从头到尾没动。这类问题改一次代码就可能复发，
所以把当时那几条轨迹固化成用例。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import push_wecom as pw  # noqa: E402

RATE, TH, MIN_ABS = 7.15, 10, 1.0
_failed = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global _failed
    if not cond:
        _failed += 1
    print(("  ✅ " if cond else "  ❌ ") + name + ("" if cond else f"   {extra}"))


def chg(mid, oi, oo, ni, no):
    return {"id": mid, "name": mid, "old": {"in": oi, "out": oo}, "new": {"in": ni, "out": no}}


GLM = "z-ai/glm-5.3-flash"
REF = {
    GLM: {"in": 0.15, "out": 0.5, "stable": 2, "name": "GLM 5.3 Flash",
          "vendor": "z-ai", "vendor_cn": "智谱 AI", "off_peak": False},
    "deepseek/v4": {"in": 0.3, "out": 1.2, "stable": 1, "name": "DS V4",
                    "vendor": "deepseek", "vendor_cn": "深度求索", "off_peak": True},
}


def test_split():
    print("① 以基准价为锚点分类")
    promo, _, _, _ = pw.split_by_ref([chg(GLM, 0.15, 0.5, 0.0453, 0.0745)], REF)
    check("促销进入 → 限时优惠", len(promo) == 1 and promo[0]["ratio"] == 0.302, promo)
    check("优惠的 old 锚定为基准价", promo and promo[0]["old"]["in"] == 0.15)

    p2, a2, _, back2 = pw.split_by_ref([chg(GLM, 0.0453, 0.0745, 0.15, 0.5)], REF)
    check("促销结束回到原价 → 静默（曾经被误报成涨 578%）",
          len(back2) == 1 and not p2 and not a2, f"promo={p2} above={a2}")

    _, _, _, b3 = pw.split_by_ref([chg(GLM, 0.15, 0.5, 0.151, 0.5)], REF)
    check("±2% 内视为同价", len(b3) == 1)
    _, a4, _, _ = pw.split_by_ref([chg(GLM, 0.15, 0.5, 0.3, 1.0)], REF)
    check("高于基准价 → 不当场报", len(a4) == 1)
    _, _, n5, _ = pw.split_by_ref([chg("no/ref", 1.0, 2.0, 0.5, 1.0)], REF)
    check("无基准价 → 走老口径", len(n5) == 1)
    p6, _, _, b6 = pw.split_by_ref([chg("deepseek/v4", 0.3, 1.2, 0.15, 0.6)], REF)
    check("错峰模型降价 → 静默（夜间优惠天天有）", len(b6) == 1 and not p6, p6)


def test_ref_shift():
    print("② 基准价迁移 = 真实调价")
    c0, st0 = pw.detect_ref_shifts(REF, {}, RATE, TH, MIN_ABS)
    check("首次登记不播报", c0 == [] and len(st0) == 2, c0)

    big = {"big/model": {"in": 5.0, "out": 20.0, "stable": 6, "name": "Big",
                          "vendor": "big", "vendor_cn": "某厂", "off_peak": False}}
    prev = {"big/model": {"in": 10.0, "out": 20.0}}
    c1, _ = pw.detect_ref_shifts(big, prev, RATE, TH, MIN_ABS)
    check("基准价砍半 → 报降 50%",
          len(c1) == 1 and abs(pw.judge_change(c1[0], RATE)[0] + 50) < 0.01, c1)

    shaky = {"big/model": {"in": 5.0, "out": 20.0, "stable": 1, "name": "Big",
                            "vendor": "big", "vendor_cn": "某厂", "off_peak": False}}
    c2, st2 = pw.detect_ref_shifts(shaky, prev, RATE, TH, MIN_ABS)
    check("新价没挂稳 → 不认账", not c2 and st2["big/model"]["in"] == 10.0,
          f"changes={c2} state={st2.get('big/model')}")


def test_ledger():
    print("③ 台账")
    led = {"since": None, "items": {}}
    pw.merge_into_ledger(led, [chg("m/x", 1.0, 4.0, 1.3, 5.2)], RATE, TH, MIN_ABS)
    check("首次记账保留", "m/x" in led["items"])
    pw.merge_into_ledger(led, [chg("m/x", 1.3, 5.2, 1.0, 4.0)], RATE, TH, MIN_ABS)
    check("涨完跌回原处 → 条目清掉（旧的会一直挂着）", "m/x" not in led["items"])
    check("台账空了 since 归零", led["since"] is None)


def test_wording():
    print("④ 优惠文案")
    promo, _, _, _ = pw.split_by_ref([chg(GLM, 0.15, 0.5, 0.0453, 0.0745)], REF)
    blocks, n, listed = pw.build_promo_blocks(promo, RATE)
    txt = "\n".join(blocks)
    check("标题写明「非调价」", "限时优惠（非调价）" in txt)
    check("给出折扣系数 ×0.302", "×0.302" in txt)
    check("声明恢复原价不通知", "恢复原价不再另行通知" in txt)
    check("不出现「涨」字", "涨" not in txt)
    check("返回实际列出的条目", n == 1 and len(listed) == 1)


def main() -> int:
    for fn in (test_split, test_ref_shift, test_ledger, test_wording):
        fn()
    print()
    if _failed:
        print(f"❌ {_failed} 项失败")
        return 1
    print("✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
