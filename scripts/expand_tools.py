# -*- coding: utf-8 -*-
"""扩充 AI 工具清单：把新增条目合并进 data/tools.json。

格式：cat|name|url|desc|tags|hot
tags 用逗号分隔；hot 用 1 表示进推荐位。
只做合并，不删除已有条目；已存在的同名工具跳过。
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
P = ROOT / "data" / "tools.json"

# 新增分类（插到合适位置）
NEW_CATS = [
    {"id": "search", "name": "搜索与研究", "color": "#0d7ea8"},
]

RAW = """
chat|腾讯元宝|https://yuanbao.tencent.com/|混元与 DeepSeek 双模型，深度接入微信生态|免费|
chat|智谱清言|https://chatglm.cn/|GLM 系列对话入口，支持智能体与长文档解读|免费试用,付费|
chat|文心一言|https://yiyan.baidu.com/|百度文心大模型的对话入口，中文问答与创作|免费|
chat|讯飞星火|https://xinghuo.xfyun.cn/|科大讯飞对话助手，语音与多语种见长|免费试用|
chat|Le Chat|https://chat.mistral.ai/|Mistral 官方助手，响应快、代码能力强|免费试用|
chat|Poe|https://poe.com/|一个入口聚合多家模型与自定义 Bot|免费试用,付费|
chat|Character.AI|https://character.ai/|角色扮演式对话，虚拟角色社区|免费,付费|
chat|Manus|https://manus.im/|通用 Agent，自己拆解任务并交付结果|免费试用,付费|1
chat|Monica|https://monica.im/|浏览器侧边栏助手，划词问答与网页摘要|免费,免费试用,付费|
chat|Chatbox|https://chatboxai.app/|本地桌面客户端，填自己的 Key 用任意模型|免费,开源|
chat|LobeChat|https://lobehub.com/|开源多模型聊天框架，插件与知识库齐全|免费,开源|
chat|百川智能|https://www.baichuan-ai.com/|百川大模型对话与医疗垂类应用|免费|
chat|海螺AI|https://hailuoai.com/|MiniMax 的对话与语音助手|免费|
chat|Qwen Chat|https://chat.qwen.ai/|通义千问国际版，支持图像与视频理解|免费|
chat|跃问|https://yuewen.cn/|阶跃星辰多模态助手，长图与文档理解强|免费|

search|Perplexity|https://www.perplexity.ai/|带引用的 AI 搜索引擎，回答附来源|免费,付费|1
search|NotebookLM|https://notebooklm.google.com/|喂资料做问答与播客式摘要，来源可溯源|免费|1
search|Genspark|https://www.genspark.ai/|生成式搜索，直接产出结构化报告|免费试用,付费|
search|Consensus|https://consensus.app/|从论文里找结论，适合循证类问题|免费,付费|
search|Elicit|https://elicit.com/|文献综述助手，批量提取论文要点|免费,付费|
search|SciSpace|https://typeset.io/|论文阅读助手，逐段解释公式与术语|免费,付费|
search|Semantic Scholar|https://www.semanticscholar.org/|AI 驱动的学术搜索，引用关系清晰|免费|
search|Connected Papers|https://www.connectedpapers.com/|按引用关系画论文图谱，看领域脉络|免费,付费|
search|Devv|https://devv.ai/|面向开发者的技术搜索，答案带代码|免费|
search|Phind|https://www.phind.com/|技术问题搜索，长答案附来源|免费,付费|
search|Kagi|https://kagi.com/|付费无广告搜索，可调结果权重|付费|
search|Exa|https://exa.ai/|面向 AI 的语义搜索 API，按意思找网页|免费试用,付费|
search|纳米AI搜索|https://www.n.cn/|360 的 AI 搜索，聚合多模型回答|免费|

writing|DeepL Write|https://www.deepl.com/write|英文润色与改写，语气可选|免费,付费|
writing|Wordtune|https://www.wordtune.com/|句子级改写与语气调整|免费,付费|
writing|Rytr|https://rytr.me/|低成本批量文案生成，模板多|免费试用,付费|
writing|Sudowrite|https://www.sudowrite.com/|小说创作助手，续写与情节头脑风暴|免费试用,付费|
writing|NovelAI|https://novelai.net/|AI 小说与配图创作，注重隐私|付费|
writing|ProWritingAid|https://prowritingaid.com/|长文语法与风格检查，报告细|免费,付费|
writing|Hemingway Editor|https://hemingwayapp.com/|标出冗长句与被动语态，逼你写短句|免费|
writing|火龙果写作|https://www.mypitaya.com/|中文学术与公文写作，纠错改写|免费试用,付费|

image|Ideogram|https://ideogram.ai/|擅长在图里排文字，海报与 Logo 首选|免费试用,付费|1
image|FLUX|https://blackforestlabs.ai/|开源图像模型天花板，细节与手部稳定|免费,开源|
image|Leonardo.Ai|https://leonardo.ai/|游戏美术与概念设计，风格模型多|免费试用,付费|
image|Recraft|https://www.recraft.ai/|矢量图与品牌套件生成，可导出 SVG|免费试用,付费|
image|Krea|https://www.krea.ai/|实时画板，边画边出图|免费试用,付费|
image|Civitai|https://civitai.com/|开源模型与 LoRA 最大集散地|免费,开源|
image|Photoroom|https://www.photoroom.com/|商品图去背与场景合成，电商常用|免费试用,付费|
image|remove.bg|https://www.remove.bg/|一键去背景，API 也常用|免费,付费|
image|通义万相|https://tongyi.aliyun.com/wanxiang/|阿里图像与视频生成，中文提示理解好|免费|
image|文心一格|https://yige.baidu.com/|百度 AI 作画，国风与插画风格多|免费试用|
image|无界AI|https://www.wujieai.com/|国内 AI 绘画社区，模型与工作流齐全|免费试用,付费|
image|佐糖|https://picwish.cn/|抠图、去水印、画质修复工具箱|免费试用,付费|
image|Upscayl|https://upscayl.org/|开源本地图片放大，可批量处理|免费,开源|
image|Playground|https://playground.com/|画布式图像创作，改局部很方便|免费试用,付费|

video|PixVerse|https://app.pixverse.ai/|免费额度大的视频生成，模板丰富|免费,付费|
video|智谱清影|https://chatglm.cn/video|智谱视频生成，中文提示友好|免费|
video|腾讯智影|https://zenvideo.qq.com/|数字人播报与视频剪辑一体|免费试用,付费|
video|一帧秒创|https://aigc.yizhentv.com/|图文一键转视频，适合口播号|免费试用|
video|Synthesia|https://www.synthesia.io/|企业级数字人视频，多语种口型准|付费|
video|D-ID|https://www.d-id.com/|照片驱动数字人，API 集成方便|免费试用,付费|
video|Captions|https://www.captions.ai/|AI 剪辑与自动字幕，短视频常用|免费试用,付费|
video|Descript|https://www.descript.com/|像编辑文档一样剪音视频|免费,付费|
video|OpusClip|https://www.opus.pro/|长视频自动切成短视频片段|免费试用,付费|
video|CapCut|https://www.capcut.com/|剪映国际版，AI 字幕与特效齐全|免费,付费|
video|InVideo|https://invideo.io/|模板化视频生成，脚本到成片一条龙|免费试用,付费|
video|VEED|https://www.veed.io/|在线剪辑 + 自动字幕 + 翻译|免费试用,付费|
video|Veo|https://deepmind.google/models/veo/|Google 视频生成模型，物理与运镜自然|免费试用|

audio|Fish Audio|https://fish.audio/|开源 TTS，音色克隆门槛低|免费,开源|
audio|TTSMaker|https://ttsmaker.cn/|免费在线配音，多语种多音色|免费|
audio|魔音工坊|https://www.moyin.com/|中文配音与声音克隆，短视频常用|免费试用,付费|
audio|讯飞配音|https://peiyin.xunfei.cn/|讯飞音色库，播音腔自然|免费试用,付费|
audio|LALAL.AI|https://www.lalal.ai/|人声与伴奏分离，音质干净|免费试用,付费|
audio|Moises|https://moises.ai/|分轨与节拍检测，练琴与混音用|免费试用,付费|
audio|AIVA|https://www.aiva.ai/|AI 作曲，可指定情绪与风格|免费试用,付费|
audio|Mubert|https://mubert.com/|按场景生成免版税背景音乐|免费试用,付费|
audio|网易天音|https://tianyin.163.com/|网易 AI 音乐创作，中文歌友好|免费|
audio|Speechify|https://speechify.com/|网页与文档朗读，听书场景|免费试用,付费|
audio|Krisp|https://krisp.ai/|实时降噪，会议与录音去背景音|免费,付费|

office|Microsoft 365 Copilot|https://www.microsoft.com/microsoft-365/copilot|Word / Excel / PPT 里的 AI 助手|付费|
office|讯飞智文|https://zhiwen.xfyun.cn/|一句话生成 PPT 与文档|免费试用,付费|
office|boardmix 博思白板|https://boardmix.cn/|AI 生成思维导图与白板协作|免费试用,付费|
office|Napkin AI|https://www.napkin.ai/|把文字自动变成信息图|免费,付费|
office|ChatPDF|https://www.chatpdf.com/|上传 PDF 直接问答|免费,付费|
office|Humata|https://www.humata.ai/|长文档问答与摘要，适合合同与论文|免费试用,付费|
office|Otter.ai|https://otter.ai/|会议录音转写与摘要，英文最佳|免费,付费|
office|Fireflies|https://fireflies.ai/|会议记录机器人，自动出纪要与待办|免费,付费|
office|Beautiful.ai|https://www.beautiful.ai/|排版自动对齐的 PPT 工具|付费|
office|钉钉 AI|https://www.dingtalk.com/|钉钉内的 AI 助理与流程自动化|免费|
office|腾讯文档|https://docs.qq.com/|在线协作文档，内置 AI 写作与总结|免费|

coding|Tabnine|https://www.tabnine.com/|企业级代码补全，可私有部署|免费试用,付费|
coding|Amazon Q Developer|https://aws.amazon.com/q/developer/|AWS 官方 AI 编程助手|免费试用,付费|
coding|Continue|https://www.continue.dev/|开源 IDE 插件，可接任意模型|免费,开源|
coding|Cline|https://cline.bot/|VS Code 里的自主编码 Agent|免费,开源|
coding|Aider|https://aider.chat/|命令行配对编程，自动改仓库并提交|免费,开源|
coding|Bolt.new|https://bolt.new/|一句话生成可运行的全栈应用|免费,付费|
coding|v0|https://v0.dev/|Vercel 的 UI 生成器，直接出 React 代码|免费,付费|
coding|Lovable|https://lovable.dev/|自然语言出全栈应用，可接数据库|免费,付费|
coding|Zed|https://zed.dev/|高性能编辑器，内置 AI 补全|免费,开源|
coding|JetBrains AI|https://www.jetbrains.com/ai/|JetBrains 全家桶的 AI 助手|免费试用,付费|
coding|CodeGeeX|https://codegeex.cn/|智谱开源代码模型，国产 IDE 适配广|免费|
coding|aiXcoder|https://www.aixcoder.com/|国产代码补全，支持私有化|免费试用,付费|
coding|Cody|https://sourcegraph.com/cody|基于代码库检索的问答与补全|免费,付费|
coding|Warp|https://www.warp.dev/|AI 终端，自然语言转命令|免费,付费|

design|Framer|https://www.framer.com/|AI 生成站点并一键发布|免费,付费|
design|Uizard|https://uizard.io/|草图转可编辑 UI 原型|免费试用,付费|
design|Visily|https://www.visily.ai/|截图或文字转线框图|免费试用,付费|
design|Relume|https://www.relume.io/|AI 生成网站结构图与线框|免费试用,付费|
design|Khroma|https://www.khroma.co/|按偏好生成配色方案|免费|
design|Coolors|https://coolors.co/|快速配色与调色板管理|免费,付费|
design|Pacdora|https://www.pacdora.com/|包装与刀版图 3D 预览|免费试用,付费|
design|Durable|https://durable.co/|几十秒生成小企业官网|免费试用,付费|
design|Webflow|https://webflow.com/|可视化建站，AI 生成布局|免费,付费|

model|Artificial Analysis|https://artificialanalysis.ai/|模型质量、速度、价格的权威横向榜单|免费|1
model|LMArena|https://lmarena.ai/|盲测投票的模型竞技场，看真实偏好|免费|1
model|Google AI Studio|https://aistudio.google.com/|Gemini 官方调试台，免费额度大|免费|
model|Groq|https://groq.com/|LPU 推理，速度极快|免费,付费|
model|Together AI|https://www.together.ai/|开源模型托管与微调|免费试用,付费|
model|Fireworks AI|https://fireworks.ai/|高吞吐推理与模型部署|免费试用,付费|
model|Replicate|https://replicate.com/|一个 API 跑上千个开源模型|免费试用,付费|
model|硅基流动|https://siliconflow.cn/|国内开源模型 API，价格低|免费,付费|
model|阿里云百炼|https://bailian.console.aliyun.com/|通义系列模型的一站式平台|免费试用,付费|
model|arXiv|https://arxiv.org/|论文预印本原始出处|免费|
model|Papers with Code|https://paperswithcode.com/|论文配代码与榜单|免费|
model|Kaggle|https://www.kaggle.com/|数据集、竞赛与免费 GPU|免费|
model|LlamaIndex|https://www.llamaindex.ai/|RAG 与 Agent 的数据框架|免费,开源|
model|n8n|https://n8n.io/|开源自动化工作流，可接大模型|免费,开源|

business|影刀 RPA|https://www.yingdao.com/|国产 RPA，拼装式流程自动化|免费试用,付费|
business|腾讯云 AI|https://cloud.tencent.com/product/ai|OCR、语音、翻译等能力集合|免费试用,付费|
business|网易七鱼|https://qiyukf.com/|智能客服与工单，电商常用|免费试用,付费|
business|讯飞开放平台|https://www.xfyun.cn/|语音识别与合成的能力市场|免费试用,付费|
business|探迹|https://www.tungee.com/|AI 销售线索挖掘与客户触达|付费|

safety|Sapling|https://sapling.ai/ai-content-detector|AI 文本检测，面向企业场景|免费,付费|
safety|Winston AI|https://gowinston.ai/|AI 内容检测，主打高准确率|免费试用,付费|
safety|网易易盾|https://dun.163.com/|内容安全检测，覆盖文本图片音频|免费试用,付费|
safety|数美科技|https://www.ishumei.com/|风控与内容审核 SaaS|付费|
safety|阿里云内容安全|https://www.aliyun.com/product/lvwang|文本图像审核 API|免费试用,付费|
safety|腾讯云天御|https://cloud.tencent.com/product/tms|内容安全与文本审核|免费试用,付费|
safety|瑞莱智慧|https://www.realai.ai/|AI 安全与深度伪造检测|付费|
safety|Hive Moderation|https://hivemoderation.com/|多模态内容审核 API|付费|
"""


def slug(name: str) -> str:
    s = name.lower()
    out = []
    for ch in s:
        if ch.isalnum():
            out.append(ch)
        elif ch in " .-_/":
            out.append("-")
    r = "".join(out)
    while "--" in r:
        r = r.replace("--", "-")
    return r.strip("-") or "tool"


def main():
    data = json.loads(P.read_text(encoding="utf-8"))
    cats = data["categories"]
    have_cat = {c["id"] for c in cats}
    for c in NEW_CATS:
        if c["id"] not in have_cat:
            cats.append(c)
    valid = {c["id"] for c in cats}

    existing = {t["name"].strip().lower() for t in data["tools"]}
    existing_url = {t["url"].rstrip("/").lower() for t in data["tools"]}
    ids = {t["id"] for t in data["tools"]}

    added, skipped = [], []
    for line in RAW.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cat, name, url, desc, tags, hot = [x.strip() for x in line.split("|")]
        if cat not in valid:
            raise SystemExit(f"未知分类 {cat}: {name}")
        if name.lower() in existing or url.rstrip("/").lower() in existing_url:
            skipped.append(name)
            continue
        tid = slug(name)
        base, n = tid, 2
        while tid in ids:
            tid = f"{base}-{n}"
            n += 1
        ids.add(tid)
        data["tools"].append({
            "id": tid,
            "name": name,
            "cat": cat,
            "desc": desc,
            "url": url,
            "tags": [x for x in tags.split(",") if x] or ["免费试用"],
            "hot": hot == "1",
        })
        existing.add(name.lower())
        existing_url.add(url.rstrip("/").lower())
        added.append(name)

    data["updated_at"] = "2026-10-27"
    P.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    from collections import Counter
    print(f"新增 {len(added)} 个，跳过重复 {len(skipped)} 个，当前共 {len(data['tools'])} 个")
    if skipped:
        print("跳过:", "、".join(skipped))
    cnt = Counter(t["cat"] for t in data["tools"])
    for c in cats:
        print(f"  {c['name']:12s} {cnt.get(c['id'], 0)}")


if __name__ == "__main__":
    main()
