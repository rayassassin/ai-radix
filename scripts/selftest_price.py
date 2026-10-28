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


def test_entry_order():
    """⑤ 入口函数变量定义顺序（静态检查）

    2026-10-28 线上事故：main() 里 promo_push 在第 1182 行被读、第 1220 行才赋值。
    逻辑测试全绿 —— 因为只有「本轮恰好有限时优惠」才会走到那行，平时根本触发不到；
    真触发时就是 UnboundLocalError 崩掉整轮推送，顺带发一条假的「推送失败」告警。

    这类「先读后写」用 AST 就能静态抓出来：扫 main() 的局部变量，
    任何变量首次读取行号早于首次赋值行号即判失败。通用防同类回归。
    """
    print("⑤ 入口变量定义顺序")
    import ast
    import builtins

    src = Path(pw.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    check("找到 main() 函数", fn is not None)
    if fn is None:
        return

    params = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}

    def scan(node: ast.AST, stores: dict[str, int], loads: dict[str, int],
             nested: bool = False) -> None:
        """收集 Name 的读写位置。nested=True 时遇到函数/Lambda 就停（独立作用域）。"""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                if nested:
                    continue
                scan_body(child)
                continue
            if isinstance(child, ast.Name):
                ln = child.lineno
                if isinstance(child.ctx, ast.Store):
                    stores[child.id] = min(stores.get(child.id, ln), ln)
                elif isinstance(child.ctx, ast.Load):
                    loads[child.id] = min(loads.get(child.id, ln), ln)
            scan(child, stores, loads, nested=True)

    def scan_body(fnnode: ast.AST) -> None:
        # main() 自己的函数体要扫，但它内部的内嵌函数不扫
        for child in ast.iter_child_nodes(fnnode):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            scan(child, stores, loads, nested=True)

    stores: dict[str, int] = {}
    loads: dict[str, int] = {}
    scan_body(fn)

    # 模块级的名字（导入、顶层常量、函数类名）在 main 里读是合法的，不进检查
    top_stores: dict[str, int] = {}
    top_loads: dict[str, int] = {}
    for child in ast.iter_child_nodes(tree):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            top_stores[child.name] = child.lineno
            continue
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            for a in child.names:
                top_stores[(a.asname or a.name).split(".")[0]] = child.lineno
            continue
        scan(child, top_stores, top_loads)

    bad = []
    for name, load_ln in sorted(loads.items(), key=lambda kv: kv[1]):
        if name in params or hasattr(builtins, name) or name in top_stores:
            continue
        store_ln = stores.get(name)
        if store_ln is None:
            bad.append(f"{name}（{load_ln} 行读，全函数无赋值）")
        elif load_ln < store_ln:
            bad.append(f"{name}（{load_ln} 行读 / {store_ln} 行赋值）")
    check("main() 内无「先读后写 / 从未赋值」的局部变量", not bad, "; ".join(bad))


def main() -> int:
    for fn in (test_split, test_ref_shift, test_ledger, test_wording, test_entry_order):
        fn()
    print()
    if _failed:
        print(f"❌ {_failed} 项失败")
        return 1
    print("✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
