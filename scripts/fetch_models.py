#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI · Radix · 数据抓取与标准化

从 OpenRouter 公开 API 拉取全量模型清单，标准化为前端可直接消费的 JSON，
并与上一版快照做 diff，识别「新上线模型」供推送使用。

设计原则：
  - 零第三方依赖（仅标准库），避免环境踩坑
  - 抓取失败不覆盖旧数据（宁可旧，不可空）
  - diff 基线首次运行不推送，避免开号即刷屏

用法:
  python3 scripts/fetch_models.py            # 抓取并更新 data/
  python3 scripts/fetch_models.py --offline  # 仅用 data/raw_api.json 本地重算
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG_EXTERNAL = Path.home() / ".ai-radix" / "config.json"
# 迁移期兼容：改名前的 ~/.llm-radar 若还在也认，旧目录清掉后这段连同下面一起删
CONFIG_LEGACY = Path.home() / ".llm-radar" / "config.json"


def resolve_config_path() -> Path:
    """配置查找顺序：环境变量 → ~/.ai-radix/config.json → ~/.llm-radar/config.json → 项目内 config.json。
    外置是为了避免 webhook 密钥随站点目录一起被公开部署。"""
    env = os.environ.get("AI_RADIX_CONFIG") or os.environ.get("LLM_RADAR_CONFIG")
    if env:
        return Path(env).expanduser()
    for p in (CONFIG_EXTERNAL, CONFIG_LEGACY):
        if p.exists():
            return p
    return ROOT / "config.json"
PROVIDERS_PATH = DATA_DIR / "providers.json"
RAW_PATH = DATA_DIR / "raw_api.json"
MODELS_PATH = DATA_DIR / "models.json"
META_PATH = DATA_DIR / "meta.json"
NEW_PATH = DATA_DIR / "new_models.json"
SAMPLES_PATH = DATA_DIR / "price_samples.json"

TZ_CN = timezone(timedelta(hours=8))

# 主流厂商中文名 + 品牌色。未收录的厂商走哈希调色板兜底。
DEFAULT_PROVIDERS = {
    "openai":        {"name": "OpenAI",           "cn": "OpenAI",       "color": "#10a37f"},
    "qwen":          {"name": "Qwen",             "cn": "通义千问",      "color": "#615ced"},
    "google":        {"name": "Google",           "cn": "Google",       "color": "#4285f4"},
    "anthropic":     {"name": "Anthropic",        "cn": "Anthropic",    "color": "#d97757"},
    "mistralai":     {"name": "Mistral AI",       "cn": "Mistral",      "color": "#fa520f"},
    "z-ai":          {"name": "Z.AI",             "cn": "智谱 AI",       "color": "#3859ff"},
    "deepseek":      {"name": "DeepSeek",         "cn": "深度求索",      "color": "#4d6bfe"},
    "nvidia":        {"name": "NVIDIA",           "cn": "英伟达",        "color": "#76b900"},
    "moonshotai":    {"name": "Moonshot AI",      "cn": "月之暗面",      "color": "#1f1f1f"},
    "minimax":       {"name": "MiniMax",          "cn": "MiniMax",      "color": "#ee2b5b"},
    "meta":          {"name": "Meta",             "cn": "Meta",         "color": "#0866ff"},
    "meta-llama":    {"name": "Meta Llama",       "cn": "Meta",         "color": "#0866ff"},
    "x-ai":          {"name": "xAI",              "cn": "xAI",          "color": "#1a1a1a"},
    "tencent":       {"name": "Tencent",          "cn": "腾讯混元",      "color": "#0052d9"},
    "bytedance":     {"name": "ByteDance",        "cn": "字节跳动",      "color": "#325ab4"},
    "bytedance-seed":{"name": "ByteDance Seed",   "cn": "字节 Seed",     "color": "#325ab4"},
    "xiaomi":        {"name": "Xiaomi",           "cn": "小米",          "color": "#ff6900"},
    "meituan":       {"name": "Meituan",          "cn": "美团",          "color": "#ffd100"},
    "stepfun":       {"name": "StepFun",          "cn": "阶跃星辰",      "color": "#0e5cff"},
    "inclusionai":   {"name": "InclusionAI",      "cn": "蚂蚁百灵",      "color": "#1677ff"},
    "openrouter":    {"name": "OpenRouter",       "cn": "OpenRouter",   "color": "#6467f2"},
    "amazon":        {"name": "Amazon",           "cn": "亚马逊",        "color": "#ff9900"},
    "cohere":        {"name": "Cohere",           "cn": "Cohere",       "color": "#39594d"},
    "perplexity":    {"name": "Perplexity",       "cn": "Perplexity",   "color": "#20808d"},
    "microsoft":     {"name": "Microsoft",        "cn": "微软",          "color": "#0078d4"},
    "sakana":        {"name": "Sakana AI",        "cn": "Sakana AI",    "color": "#e8467c"},
    "thinkingmachines": {"name": "Thinking Machines", "cn": "Thinking Machines", "color": "#0f0f0f"},
    "poolside":      {"name": "Poolside",         "cn": "Poolside",     "color": "#16a34a"},
    "inception":     {"name": "Inception",        "cn": "Inception",    "color": "#7c3aed"},
    "liquid":        {"name": "Liquid AI",        "cn": "Liquid AI",    "color": "#2dd4bf"},
    "upstage":       {"name": "Upstage",          "cn": "Upstage",      "color": "#f97316"},
    "nousresearch":  {"name": "Nous Research",    "cn": "Nous",         "color": "#8b5cf6"},
    "ibm-granite":   {"name": "IBM Granite",      "cn": "IBM",          "color": "#0062ff"},
    "writer":        {"name": "Writer",           "cn": "Writer",       "color": "#0b0b0b"},
    "arcee-ai":      {"name": "Arcee AI",         "cn": "Arcee AI",     "color": "#ef4444"},
    "rekaai":        {"name": "Reka AI",          "cn": "Reka AI",      "color": "#06b6d4"},
    "cognitivecomputations": {"name": "Cognitive Computations", "cn": "Cognitive", "color": "#78716c"},
    "aion-labs":     {"name": "Aion Labs",        "cn": "Aion Labs",    "color": "#a855f7"},
    "moondream":     {"name": "Moondream",        "cn": "Moondream",    "color": "#fbbf24"},
    "nex-agi":       {"name": "Nex AGI",          "cn": "Nex AGI",      "color": "#ec4899"},
    "inference-net": {"name": "Inference.net",    "cn": "Inference.net","color": "#64748b"},
    "reflection":    {"name": "Reflection",       "cn": "Reflection",   "color": "#111827"},
    "recursive":     {"name": "Recursive",        "cn": "Recursive",    "color": "#0891b2"},
}

PALETTE = ["#5b5bd6", "#0ea5e9", "#14b8a6", "#f59e0b", "#ef4444",
           "#8b5cf6", "#ec4899", "#22c55e", "#f97316", "#6366f1"]


def now_cn() -> datetime:
    return datetime.now(TZ_CN)


def log(msg: str) -> None:
    print(f"[{now_cn():%H:%M:%S}] {msg}", flush=True)


def load_json(path: Path, default=None):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(path)


def ensure_providers() -> dict:
    """厂商映射：文件存在则文件优先（可手工改），缺失项由内置表补齐。"""
    merged = dict(DEFAULT_PROVIDERS)
    file_cfg = load_json(PROVIDERS_PATH)
    if isinstance(file_cfg, dict):
        merged.update({k: v for k, v in file_cfg.items() if isinstance(v, dict)})
    else:
        save_json(PROVIDERS_PATH, DEFAULT_PROVIDERS)
        log(f"已生成厂商映射模板 {PROVIDERS_PATH.relative_to(ROOT)}（可手工补充）")
    return merged


def vendor_info(vendor: str, providers: dict) -> dict:
    base = vendor.lstrip("~")
    info = providers.get(base)
    if info:
        return {"name": info.get("name", base), "cn": info.get("cn", base),
                "color": info.get("color", PALETTE[0])}
    # 未收录厂商：稳定哈希分配颜色，保证同一厂商每次同色
    color = PALETTE[sum(ord(c) for c in base) % len(PALETTE)]
    return {"name": base, "cn": base, "color": color}


def to_float(v, default=None):
    try:
        f = float(v)
        # OpenRouter 用 -1 表示动态定价，视为未知
        return default if f < 0 else f
    except (TypeError, ValueError):
        return default


def per_million(v):
    """美元/token → 美元/1M tokens"""
    f = to_float(v)
    return None if f is None else round(f * 1_000_000, 4)


def classify(m: dict) -> str:
    """
    模型主类型判定 —— 只看「产出什么」，输入多模态属于附加能力，不改主类型。

    踩坑记录：早期按输入模态分类，会把 Kimi K3.1 Pro 这种「输入含视频」的
    对话模型误判成「视频理解」。行业惯例（含参考站点）主类型只有文本/图像/语音几大类，
    多模态输入应体现在能力标签而非类型上。
    """
    arch = m.get("architecture") or {}
    outs = set(arch.get("output_modalities") or [])
    mid = (m.get("id") or "").lower()
    name = (m.get("name") or "").lower()
    blob = f"{mid} {name}"

    if "embed" in blob:
        return "嵌入"
    if "rerank" in blob or "reranker" in blob:
        return "重排序"
    if "moderation" in blob:
        return "审核"
    # 生成类模型通常是双模态输出（如 ["image","text"]），只要能产出即归入对应大类
    if "video" in outs:
        return "视频生成"
    if "image" in outs:
        return "图像生成"
    if "audio" in outs:
        return "语音合成"
    return "文本"


def capabilities(m: dict) -> dict:
    sp = set(m.get("supported_parameters") or [])
    arch = m.get("architecture") or {}
    ins = set(arch.get("input_modalities") or [])
    outs = set(arch.get("output_modalities") or [])
    pricing = m.get("pricing") or {}
    reasoning_cfg = m.get("reasoning") or {}
    return {
        "reasoning": bool("reasoning" in sp or "include_reasoning" in sp or reasoning_cfg),
        "tools": "tools" in sp,
        "structured": "structured_outputs" in sp,
        "json": bool("response_format" in sp or "structured_outputs" in sp),
        "temperature": "temperature" in sp,
        "open_weights": bool(m.get("hugging_face_id")),
        "vision": "image" in ins,
        "audio_in": "audio" in ins,
        "video_in": "video" in ins,
        "file_in": "file" in ins,
        "image_out": "image" in outs,
        "audio_out": "audio" in outs,
        "cache": bool(to_float(pricing.get("input_cache_read"))),
        "seed": "seed" in sp,
        "logprobs": "logprobs" in sp,
    }


def normalize(m: dict, providers: dict, new_days: int, today: datetime) -> dict | None:
    mid = m.get("id")
    if not mid or "/" not in mid:
        return None

    vendor_raw, slug_raw = mid.split("/", 1)
    is_alias = vendor_raw.startswith("~")
    vendor = vendor_raw.lstrip("~")
    vinfo = vendor_info(vendor_raw, providers)

    full_name = (m.get("name") or mid).strip()
    # "MoonshotAI: Kimi K3.1 Pro" → "Kimi K3.1 Pro"
    name = full_name.split(": ", 1)[1] if ": " in full_name else full_name

    created_ts = int(m.get("created") or 0)
    created_dt = datetime.fromtimestamp(created_ts, TZ_CN) if created_ts else None
    age_days = (today - created_dt).days if created_dt else None

    bench = m.get("benchmarks") or {}
    aa = bench.get("artificial_analysis") or {}
    arena = []
    for item in (bench.get("design_arena") or []):
        if isinstance(item, dict):
            arena.append({
                "category": item.get("category"),
                "elo": item.get("elo"),
                "rank": item.get("rank"),
                "win_rate": item.get("win_rate"),
            })

    pricing = m.get("pricing") or {}
    price = {
        "in": per_million(pricing.get("prompt")),
        "out": per_million(pricing.get("completion")),
        "cache_read": per_million(pricing.get("input_cache_read")),
        "cache_write": per_million(pricing.get("input_cache_write")),
        "image": per_million(pricing.get("image")),
        "audio": per_million(pricing.get("audio")),
        "audio_out": per_million(pricing.get("audio_output")),
        "web_search": per_million(pricing.get("web_search")),
        "internal_reasoning": per_million(pricing.get("internal_reasoning")),
    }

    top = m.get("top_provider") or {}
    arch = m.get("architecture") or {}
    ctx = m.get("context_length") or 0
    max_out = top.get("max_completion_tokens")

    return {
        "id": mid,
        "slug": slug_raw,
        "name": name,
        "full_name": full_name,
        "vendor": vendor,
        "vendor_alias": is_alias,
        "vendor_name": vinfo["name"],
        "vendor_cn": vinfo["cn"],
        "vendor_color": vinfo["color"],
        "type": classify(m),
        "context": ctx,
        "max_output": max_out,
        "input_modalities": arch.get("input_modalities") or [],
        "output_modalities": arch.get("output_modalities") or [],
        "modality": arch.get("modality"),
        "tokenizer": arch.get("tokenizer"),
        "caps": capabilities(m),
        "iq": aa.get("intelligence_index"),
        "iq_coding": aa.get("coding_index"),
        "iq_agentic": aa.get("agentic_index"),
        "arena": arena,
        "price": price,
        "created": created_dt.strftime("%Y-%m-%d") if created_dt else None,
        "created_ts": created_ts,
        "age_days": age_days,
        "is_new": bool(age_days is not None and 0 <= age_days <= new_days),
        "knowledge_cutoff": m.get("knowledge_cutoff"),
        "expiration": m.get("expiration_date"),
        "hf_id": m.get("hugging_face_id"),
        "moderated": top.get("is_moderated"),
        "provider_ctx": top.get("context_length"),
        "description": (m.get("description") or "").strip(),
        "supported_parameters": sorted(m.get("supported_parameters") or []),
        "per_request_limits": m.get("per_request_limits"),
    }


def http_get(url: str, timeout: int, retries: int = 3) -> dict:
    headers = {
        "User-Agent": "LLM-Radar/1.0 (+local dashboard)",
        "Accept": "application/json",
    }
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            log(f"抓取失败（第 {attempt}/{retries} 次）：{e}")
            if attempt < retries:
                time.sleep(2 * attempt)
    raise RuntimeError(f"OpenRouter 接口不可用：{last_err}")


def build_meta(models: list[dict], prev_meta: dict, new_ids: list[str], cfg: dict) -> dict:
    # 厂商数按「展示名」去重（meta / meta-llama 都归 Meta），与前端下拉口径保持一致
    vendors = {}
    for m in models:
        key = m["vendor_cn"] or m["vendor"]
        vendors[key] = vendors.get(key, 0) + 1
    types = {}
    for m in models:
        types[m["type"]] = types.get(m["type"], 0) + 1

    return {
        "updated_at": now_cn().strftime("%Y-%m-%d %H:%M:%S"),
        "updated_ts": int(time.time()),
        "total": len(models),
        "vendors": len(vendors),
        "recent_new": sum(1 for m in models if m["is_new"]),
        "detected_new": len(new_ids),
        "open_weights": sum(1 for m in models if m["caps"]["open_weights"]),
        "with_iq": sum(1 for m in models if m["iq"] is not None),
        "vendor_stats": dict(sorted(vendors.items(), key=lambda x: -x[1])),
        "type_stats": dict(sorted(types.items(), key=lambda x: -x[1])),
        "prev_total": prev_meta.get("total"),
        "usd_to_cny": cfg["data"]["usd_to_cny"],
        "new_model_days": cfg["data"]["new_model_days"],
        "source": cfg["data"]["source"],
    }


# ---------------- 错峰折扣识别 ----------------
# OpenRouter 给的是「几十个路由里的最低价」，而部分厂商有明确的错峰折扣
# （DeepSeek 是典型：16:30–00:30 半价）。这会让同一模型在一天内不同时刻报价差一倍，
# 既污染调价推送，本身也是选型时值得知道的信息 —— 干脆识别出来摆到看板上。
#
# 判据不是「价格变过」，而是「价格按**时刻**稳定地分档」：同一个小时在不同日期
# 采到的价位一致，而不同小时之间有稳定落差。真实调价不会每天同一时刻反复横跳。
SAMPLE_KEEP_DAYS = 3      # 采样保留天数，够跨天比对即可，再长只是占体积
OFF_PEAK_MIN_DROP = 0.2   # 低谷至少比高峰便宜 20% 才算折扣（排除噪声抖动）


def load_samples() -> dict:
    d = load_json(SAMPLES_PATH, {}) or {}
    if not isinstance(d, dict) or not isinstance(d.get("days"), dict):
        return {"days": {}}
    return d


def record_samples(samples: dict, models: list[dict], day: str, hour: int) -> None:
    """按 天 → 小时 → 模型 记一份输入/输出价。"""
    slot = samples["days"].setdefault(day, {}).setdefault(str(hour), {})
    for m in models:
        p = m.get("price") or {}
        pin, pout = p.get("in"), p.get("out")
        if pin is None and pout is None:
            continue
        slot[m["id"]] = [pin, pout]


def prune_samples(samples: dict, keep_days: int = SAMPLE_KEEP_DAYS) -> None:
    """只留最近 keep_days 天，采样表不然会长成几百 KB 的垃圾。"""
    days = sorted(samples.get("days", {}))
    for day in days[:-keep_days]:
        samples["days"].pop(day, None)


def _median(xs) -> float | None:
    vals = sorted(x for x in xs if isinstance(x, (int, float)))
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def detect_off_peak(samples: dict, min_drop: float = OFF_PEAK_MIN_DROP) -> dict:
    """
    从采样表里找出「按时刻稳定分档、并且会回到原价」的模型。

    关键是区分**错峰折扣**和**真实调价**，两者都会让价格出现高低两档：

    - 错峰折扣：每天都在切换。序列里必然出现 high→low **又回到** high（反之亦然），
      切换次数 >= 2；且同一个小时在不同日期采到的价位一致。
    - 真实调价：只切换一次，之后一直停在新价，不会回到旧价。

    所以判据是三条同时成立：落差 >= min_drop、切换 >= 2 次、同一小时跨天稳定。
    单日数据最多只能观察到一次切换，天然不会被误判 —— 想识别错峰，至少要跨天。

    返回 {模型id: {low, high, discount, off_hours, on_hours, samples, days, confidence}}
    """
    days = samples.get("days") or {}
    if not days:
        return {}

    # 按时间顺序铺开：一天的 8/12/16/20 点，接着第二天的 8/12/16/20 点……
    timeline = []
    for day in sorted(days):
        hours = days[day] or {}
        for hour in sorted(hours, key=lambda x: int(x)):
            timeline.append((day, int(hour), hours[hour]))
    if len(timeline) < 3:
        return {}

    mids: set[str] = set()
    for _, _, slot in timeline:
        mids.update(slot or {})

    out = {}
    for mid in mids:
        seq = []      # [(hour, 价格)]，保持时间顺序
        for day, hour, slot in timeline:
            vals = (slot or {}).get(mid)
            if isinstance(vals, list) and isinstance(vals[0], (int, float)):
                seq.append((hour, vals[0]))
        if len(seq) < 3:
            continue

        prices = [p for _, p in seq]
        high, low = max(prices), min(prices)
        if high <= 0 or low / high > (1 - min_drop):
            continue

        # 二值化成 H/L，数「切换」次数：真实调价只切一次，错峰来回切
        marks = []
        for _, p in seq:
            if p <= low * 1.05:
                marks.append("L")
            elif p >= high * 0.95:
                marks.append("H")
        switches = sum(1 for i in range(1, len(marks)) if marks[i] != marks[i - 1])
        if switches < 2:
            continue      # 没有回归 -> 一次性调价，不是错峰

        # 同一小时跨天必须稳定，否则是随机抖动不是「时段规律」
        by_hour: dict[int, list] = {}
        for hour, p in seq:
            by_hour.setdefault(hour, []).append(p)
        stable = all(
            max(v) <= min(v) * 1.1
            for v in by_hour.values() if len(v) >= 2
        )
        if not stable:
            continue

        hour_price = {h: _median(v) for h, v in by_hour.items()}
        out[mid] = {
            "low": low,
            "high": high,
            "discount": round(low / high, 3),   # 0.5 = 半价
            "off_hours": sorted(h for h, p in hour_price.items() if p and p <= low * 1.05),
            "on_hours": sorted(h for h, p in hour_price.items() if p and p >= high * 0.95),
            "samples": len(seq),
            "days": len(days),
            "confidence": "high" if len(days) >= 2 else "low",
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="不联网，用本地 raw_api.json 重算")
    args = ap.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg = load_json(resolve_config_path())
    if not cfg:
        log(f"配置缺失或损坏：{resolve_config_path()}")
        return 1

    providers = ensure_providers()
    new_days = int(cfg["data"].get("new_model_days", 30))
    today = now_cn()

    # ---------- 1. 取原始数据 ----------
    if args.offline:
        raw = load_json(RAW_PATH)
        if not raw:
            log("离线模式但缺少 data/raw_api.json")
            return 1
        log("离线模式：读本地原始快照")
    else:
        try:
            raw = http_get(cfg["data"]["source"], int(cfg["data"].get("timeout", 30)))
            save_json(RAW_PATH, raw)
            log(f"抓取成功，原始条目 {len(raw.get('data') or [])}")
        except Exception as e:
            # 铁律：抓取失败绝不覆盖旧数据
            log(f"抓取异常：{e}")
            if MODELS_PATH.exists():
                log("保留上一版数据，本次不更新")
                return 2
            log("无历史数据可回退，任务终止")
            return 1

    # ---------- 2. 标准化 ----------
    models, skipped = [], 0
    for m in (raw.get("data") or []):
        item = normalize(m, providers, new_days, today)
        if item is None:
            skipped += 1
        else:
            models.append(item)

    models.sort(key=lambda x: (-(x["created_ts"] or 0), x["id"]))
    log(f"标准化完成：{len(models)} 个模型（跳过 {skipped}）")

    # ---------- 3. diff 出新增模型 ----------
    prev = load_json(MODELS_PATH) or []
    prev_ids = {m.get("id") for m in prev if isinstance(m, dict)}
    has_baseline = bool(prev_ids)
    new_ids = [m["id"] for m in models if m["id"] not in prev_ids]
    new_models = [m for m in models if m["id"] not in prev_ids]
    changed_price = []
    if has_baseline:
        prev_map = {m["id"]: m for m in prev if isinstance(m, dict)}
        for m in models:
            p = prev_map.get(m["id"])
            if not p:
                continue
            a, b = (p.get("price") or {}), (m.get("price") or {})
            if a.get("in") != b.get("in") or a.get("out") != b.get("out"):
                changed_price.append({
                    "id": m["id"], "name": m["name"], "vendor_cn": m["vendor_cn"],
                    "old": {"in": a.get("in"), "out": a.get("out")},
                    "new": {"in": b.get("in"), "out": b.get("out")},
                })
    log(f"新增 {len(new_ids)} 个｜涨价/降价 {len(changed_price)} 个｜基线：{'有' if has_baseline else '无（首次）'}")

    # ---------- 4. 价格采样 + 错峰折扣识别 ----------
    # 采样必须在写入 models.json 之前做：models.json 是下次 diff 的基线，
    # 而采样表是独立累积的时序数据，两者不能互相干扰。
    samples = load_samples()
    record_samples(samples, models, f"{now_cn():%Y-%m-%d}", now_cn().hour)
    prune_samples(samples)
    save_json(SAMPLES_PATH, samples)
    off_peak = detect_off_peak(samples)
    for m in models:
        op = off_peak.get(m["id"])
        if op:
            m["off_peak"] = op
    if off_peak:
        log(f"错峰折扣：识别到 {len(off_peak)} 个模型（采样覆盖 "
            f"{len(samples.get('days', {}))} 天）")

    # ---------- 5. 落盘 ----------
    prev_meta = load_json(META_PATH) or {}
    meta = build_meta(models, prev_meta, new_ids, cfg)
    meta["has_baseline"] = has_baseline
    save_json(MODELS_PATH, models)
    save_json(META_PATH, meta)
    save_json(NEW_PATH, {
        "generated_at": meta["updated_at"],
        "has_baseline": has_baseline,
        "new_count": len(new_ids),
        "models": new_models,
        "price_changes": changed_price,
    })

    log(f"已写入 data/models.json（{len(models)} 条）｜data/meta.json｜data/new_models.json")
    if new_ids:
        preview = "、".join(f"{m['vendor_cn']}·{m['name']}" for m in new_models[:8])
        log(f"新模型预览：{preview}{' 等' if len(new_models) > 8 else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
