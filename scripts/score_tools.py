# -*- coding: utf-8 -*-
"""给 AI 工具集计算「流行度指数」（0-100）。

为什么要有这套东西
------------------
工具清单只有「一句话简介」时，用户没法判断哪个值得先试。流行度指数就是为了
回答「哪个是主流、哪个是小众」这个问题。

口径（四维加权，权重写死在 WEIGHTS 里）
--------------------------------------
  users       用户规模  35%   覆盖广度与月活量级
  trend       热度趋势  25%   近半年的讨论与采用增速
  commercial  商业表现  20%   融资、营收、付费转化
  eco         技术生态  20%   开放 API、插件/社区、被集成程度

评分怎么来的
------------
先给每个工具定一个「量级档位」(S/A/B/C/D)，再由分类系数把档位拆成四个维度
—— 不同品类的强弱项本来就不一样（模型类生态强、商业弱；办公类商业强、生态弱）。
这样四个维度不会退化成同一个数字，雷达才有意义。

**这是编辑部判断，不是测量值。** 依据是公开可见的规模与声量，不接任何付费位。
权重与系数集中在文件顶部，改一处即可整体重算。
"""
import json
import pathlib
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
P = ROOT / "data" / "tools.json"

# ---------------- 权重 ----------------
WEIGHTS = {"users": 0.35, "trend": 0.25, "commercial": 0.20, "eco": 0.20}

# ---------------- 档位 → 基准分 ----------------
TIER_BASE = {"S": 93, "A": 82, "B": 70, "C": 55, "D": 38}

# ---------------- 分类系数（对四个维度的加减） ----------------
CAT_FACTOR = {
    #            用户规模 热度趋势 商业表现 技术生态
    "chat":     (1.03, 1.02, 1.00, 0.97),
    "writing":  (0.98, 0.94, 0.96, 0.92),
    "image":    (1.01, 1.00, 1.02, 1.06),
    "video":    (1.00, 1.05, 0.98, 0.97),
    "audio":    (0.96, 0.99, 0.95, 1.02),
    "office":   (1.02, 1.00, 1.08, 0.93),
    "coding":   (0.97, 1.03, 1.05, 1.12),
    "design":   (0.94, 0.98, 0.97, 0.95),
    "model":    (0.91, 1.01, 0.92, 1.16),
    "business": (0.95, 0.94, 1.10, 0.98),
    "safety":   (0.92, 0.96, 1.04, 0.96),
    "search":   (1.00, 1.07, 0.96, 1.00),
}

# ---------------- 档位归属（按 id） ----------------
TIERS = {
    "S": """
        chatgpt gemini claude deepseek-chat
        grammarly
        midjourney canva
        sora runway jianying kling
        suno elevenlabs
        microsoft-365-copilot feishu
        copilot cursor claude-code
        figma-ai
        huggingface
        turnitin
        perplexity
    """,
    "A": """
        kimi doubao 腾讯元宝 grok tongyi 智谱清言 coze manus
        notion-ai quillbot deepl-write xiezuocat
        stability firefly flux ideogram comfyui jimeng liblib
        pika luma heygen capcut veo veed pixverse vidu hailuo descript opusclip
        udio xunfei-zhizuo fish-audio
        gamma wps-ai 讯飞智文 aippt processon otter-ai boardmix-博思白板 腾讯文档 钉钉-ai
        windsurf trae lingma replit bolt-new v0 lovable cline aider
        framer gaoding jsdesign lovart
        ollama openrouter lmarena artificial-analysis langchain modelscope groq replicate kaggle arxiv
        qianfan volcengine hunyuan 影刀-rpa xiaoduo
        gptzero originality
        notebooklm genspark elicit consensus 纳米ai搜索
    """,
    "B": """
        文心一言 讯飞星火 metaso tiangong poe monica dify qwen-chat 海螺ai 百川智能 character-ai le-chat chatbox lobechat
        jasper copy-ai writesonic ibiling wordtune prowritingaid 火龙果写作 sudowrite
        leonardo-ai recraft krea civitai remove-bg photoroom 通义万相 clipdrop playground 文心一格 无界ai meitu-design
        synthesia d-id captions invideo 智谱清影 一帧秒创
        adobe-podcast lalal-ai 魔音工坊 speechify moises ttsmaker aiva mubert krisp rask 网易天音
        islide tingwu iflyrec napkin-ai chatpdf humata fireflies beautiful-ai
        tabnine amazon-q-developer continue codegeex jetbrains-ai comate zed warp cody
        modao looka coolors webflow uizard relume durable visily
        lmstudio vllm google-ai-studio together-ai fireworks-ai 硅基流动 阿里云百炼 llamaindex n8n papers-with-code
        wondercv 网易七鱼 讯飞开放平台 yanxi 探迹
        copyleaks 网易易盾 阿里云内容安全 腾讯云天御 数美科技 sapling winston-ai zerogpt
        scispace semantic-scholar connected-papers devv phind exa
    """,
    "C": """
        stepfun
        rytr novelai hemingway-editor
        佐糖 upscayl
        deeplearning
        瑞莱智慧 kagi
    """,
    "D": """
        khroma pacdora aixcoder hive-moderation 52cv
    """,
}


def build_tier_map() -> dict:
    m = {}
    for tier, blob in TIERS.items():
        for tid in blob.split():
            if tid in m:
                raise SystemExit(f"重复归档：{tid} 同时在 {m[tid]} 与 {tier}")
            m[tid] = tier
    return m


def clamp(v: int) -> int:
    return max(30, min(99, v))


def main():
    data = json.loads(P.read_text(encoding="utf-8"))
    tools = data["tools"]
    tier_map = build_tier_map()

    missing = [t["id"] for t in tools if t["id"] not in tier_map]
    if missing:
        print(f"⚠️ 有 {len(missing)} 个工具没归档，默认给 C：")
        print("   ", " ".join(missing))
    extra = [k for k in tier_map if k not in {t["id"] for t in tools}]
    if extra:
        print(f"⚠️ 档位表里有 {len(extra)} 个 id 不在清单中（拼写错误？）：")
        print("   ", " ".join(extra))

    for t in tools:
        tier = tier_map.get(t["id"], "C")
        base = TIER_BASE[tier]
        f = CAT_FACTOR.get(t["cat"], (1, 1, 1, 1))
        dims = {
            "users": clamp(round(base * f[0])),
            "trend": clamp(round(base * f[1])),
            "commercial": clamp(round(base * f[2])),
            "eco": clamp(round(base * f[3])),
        }
        # 推荐位说明运营与口碑都在线，趋势上再给一点点倾斜
        if t.get("hot"):
            dims["trend"] = clamp(round(dims["trend"] * 1.03))

        t["pop"] = round(sum(dims[k] * w for k, w in WEIGHTS.items()))
        t["pop_dims"] = dims
        t["pop_tier"] = tier

    # 字段顺序：核心在前，评分为附加信息
    order = ["id", "name", "cat", "desc", "url", "tags", "hot", "pop", "pop_tier", "pop_dims"]
    data["tools"] = [{k: t[k] for k in order} for t in tools]
    data["pop_rubric"] = {
        "weights": WEIGHTS,
        "note": "编辑部判断，非测量值；四维加权后归一化到 0-100",
        "dims": {
            "users": "用户规模",
            "trend": "热度趋势",
            "commercial": "商业表现",
            "eco": "技术生态",
        },
    }

    P.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    pops = [t["pop"] for t in tools]
    print(f"已评分 {len(tools)} 个工具")
    print(f"  分布：最高 {max(pops)} / 中位 {sorted(pops)[len(pops)//2]} / 最低 {min(pops)}")
    print(f"  档位：{dict(Counter(t['pop_tier'] for t in tools))}")
    top = sorted(tools, key=lambda x: -x["pop"])[:10]
    print("  Top10:", "、".join(f"{t['name']}({t['pop']})" for t in top))
    low = sorted(tools, key=lambda x: x["pop"])[:5]
    print("  末5:", "、".join(f"{t['name']}({t['pop']})" for t in low))
    return 1 if (missing or extra) else 0


if __name__ == "__main__":
    raise SystemExit(main())
