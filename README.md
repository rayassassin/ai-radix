# LLM Radar · 大模型全景看板

两个页面，共用一套视觉与导航：

| 页面 | 仿照 | 内容 |
| --- | --- | --- |
| **AI 大模型** `index.html` | [hvoyai.com/models](https://www.hvoyai.com/models/) | 466+ 模型的实时价格、上下文、能力，多维筛选 / 排序 / 分页 / 横向对比 |
| **AI 工具集** `tools.html` | [ai-bot.cn](https://ai-bot.cn/) · [hvoyai.com/ai-tools](https://www.hvoyai.com/ai-tools/) | 218 款按 12 个场景归类的 AI 工具，人工精选 |

模型页在**新模型上线时自动推送企业微信**（每天 8/12/16/20 点检测）。

**线上地址**：https://rayassassin.github.io/llm-radar/
**仓库**：https://github.com/rayassassin/llm-radar

---

## 整体架构

| 层 | 位置 | 职责 |
| --- | --- | --- |
| 展示 | GitHub Pages（静态） | 页面本身，无需构建 |
| 数据 | 浏览器直连 OpenRouter | 每次打开实时拉取，站点永不过期 |
| 定时检测 | 自建服务器 + cron | 每天 8/12/16/20 点抓取并 diff，有变化才推送订阅成员 |
| 推送 | 企微自建应用消息 | 以应用身份发消息给成员 |

**为什么数据在浏览器拉而不是定时写入仓库**：OpenRouter 接口的 CORS 全开
（`access-control-allow-origin: *`），前端可以直接取。所以站点不需要每天重新发布，
静态 JSON 只作断网兜底。定时任务只负责「发现新模型并推送」。

**为什么推送跑在服务器而不是 GitHub Actions**：企微自建应用要求请求来源 IP 在
「企业可信IP」白名单内（只白名单了自建服务器），Actions 的出口 IP 不在白名单，发出去必然
报 `60020`。所以推送必须在白名单内的机器上跑。

---

## 快速开始（本地开发）

```bash
./run.sh              # 抓一次数据做缓存 + 启动本地服务
./run.sh --no-fetch   # 直接用现有缓存启动
```

访问 <http://127.0.0.1:8899/>。

> ⚠️ 不要直接双击 `index.html`。`file://` 协议下浏览器会拦截脚本和 fetch。

---

## 目录结构

```
llm-radar/
├── index.html / app.js / style.css   # AI 大模型（原生 JS，无构建、无 CDN）
├── tools.html / tools.js             # AI 工具集（共用 style.css）
├── daily.html / daily.js             # AI 大事记（共用 style.css）
├── build.sh                 # 生成纯静态发布目录 dist/
├── run.sh                   # 本地：抓数据 + 起服务
├── update.sh                # 定时入口：抓数据 + 推企微（cron 调这个）
├── server.py                # 零依赖本地服务（仅标准库）
├── scripts/
│   ├── fetch_models.py      # 抓取 OpenRouter → 标准化 → diff 新模型
│   ├── push_wecom.py        # 推送（支持三种通道，见下）
│   ├── fetch_favicons.py    # 抓各工具官网 favicon → assets/icons/
│   ├── fetch_daily.py       # 抓 AIHOT 日报 → data/daily.json
│   ├── score_tools.py       # 工具流行度指数
│   ├── expand_tools.py      # 工具批量补录
│   └── push_to_github.py    # 走 Data API 推仓库（git 传输受阻时用）
├── assets/icons/            # 工具官网图标（64×64 PNG/SVG，217 个）
├── data/
│   ├── models.json          # 标准化缓存（前端兜底用）
│   ├── meta.json            # 统计快照
│   ├── new_models.json      # 本次 diff 出的新模型 + 价格变动
│   ├── tools.json           # AI 工具清单（人工维护）
│   ├── favicons.json        # 工具 id → 图标文件名 + 明暗档
│   ├── favicons_meta.json   # 图标逐个来源与失败原因（排查用）
│   ├── daily.json           # AI 大事记：AIHOT 日报索引
│   ├── raw_api.json         # API 原始响应（--offline 重算用，不入库）
│   └── providers.json       # 厂商中文名 / 品牌色
├── config.example.json      # 配置模板
└── logs/push.log            # 推送日志
```

---

## 配置（已外置，不在项目目录）

查找顺序：`LLM_RADAR_CONFIG` 环境变量 → `~/.llm-radar/config.json` → 项目内 `config.json`。

外置是为了避免密钥随站点目录被公开部署。

```bash
mkdir -p ~/.llm-radar
cp config.example.json ~/.llm-radar/config.json
chmod 600 ~/.llm-radar/config.json
```

---

## 推送通道（三种，用 `wecom.transport` 切换）

### `wxapp` — 企微自建应用（**当前使用**）

以自建应用身份发消息。**必须跑在「企业可信IP」白名单内的机器上**。

```json
"wecom": {
  "transport": "wxapp",
  "wxapp": {
    "env_file": "<凭据文件路径，见下>",
    "touser": "<成员 userid，多人用 | 分隔；@all 表示应用可见范围全员>"
  },
  "max_bytes_per_message": 1800
}
```

凭据统一放 env 文件，**不写进配置文件、不写进仓库**。需要一个包含以下变量的文件：

| 变量 | 含义 |
| --- | --- |
| `WX_CORPID` | 企业 ID |
| `WX_SECRET` | 应用 Secret |
| `WX_AGENTID` | 应用 AgentId |
| `WX_TOUSER`（可选） | 默认收件人，配置里的 `touser` 优先 |

`env_file` 支持给数组，按顺序合并多个来源。文件权限建议 `600`。

**限制**：应用消息只能发成员（`touser`）、部门（`toparty`）或应用自己创建的群，
发不进普通企微群。markdown 正文按 1800 字节分批。

### `aibot` — 智能机器人（本机 wecom-cli）

```json
"wecom": { "transport": "aibot", "aibot": { "chat_name": "群名" } }
```

每次发送前重新拉会话列表，按群名精确匹配。只能在本机跑（CLI 授权绑定本机）。
markdown 上限 20480 字节，基本不用分批；不支持 @所有人。

### `webhook` — 群机器人

```json
"wecom": { "transport": "webhook", "webhook": "<key 或完整 URL>" }
```

最通用，任何环境都能跑，支持 @所有人。key 也可用环境变量 `WECOM_WEBHOOK_KEY`。

### 其它配置项

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `enabled` | true | 总开关 |
| `push_on_first_run` | false | 首次建基线是否也推，否则开局刷 467 条 |
| `price_change_threshold` | 10 | 调价的**百分比**门槛（%） |
| `price_change_min_abs_cny` | 1.0 | 调价的**绝对金额**门槛（¥/百万 tokens）。百分比和金额要同时达标 |
| `price_digest_hours` | `[8,12,16,20]` | 每天哪几个整点推送（数组，24 制）。新增模型与调价汇总都按这个时刻走 |
| `max_bytes_per_message` | 1800 | 单条正文上限，按通道自动适配 |

### 为什么调价要双门槛 + 按批次汇总

OpenRouter 的 `models` 接口返回的价格是**几十个路由里的最低价**。实测 `moonshotai/kimi-k3`
背后有 29 个中转站，报价从 $0.20 到 $4.50（相差 22.5 倍），接口给的就是最低那个。

最低价是所有数字里最不稳定的：哪家做促销、哪家下架，这个数就跳。$0.20 → $0.17 看着跌 15%，
实际每百万 tokens 只差 ¥0.21。所以：

- **百分比 + 绝对金额双门槛**：低价模型的微小抖动过滤掉，高价模型的真实调价照报
- **按批次汇总而非逐小时推**：中间过程记进台账（`logs/.price_ledger.json`），
  只保留每个模型的**最早起点 + 最新终点**，来回摆动自然抵消，只报净变化

新增模型也走同一批次的时刻 —— 每天 4 次，够及时，又不会把群里刷成流水账。

### 验证

```bash
python3 scripts/push_wecom.py --test         # 发一条连通性自检
python3 scripts/push_wecom.py --dry-run      # 只打印消息，不发（不写台账）
python3 scripts/push_wecom.py --dry-run --digest   # 提前预演调价汇总
```

---

## 部署

### 站点（GitHub Pages）

```bash
./build.sh        # 生成 dist/，只含前端必需文件
```

仓库推上去后 Pages 自动发布。改动前端后重新 build + 推送即可，链接不变。

**这台机器上 `git push` 不通**（代理只放通 `api.github.com`，`github.com` 与
`ssh.github.com` 均被拦），所以用：

```bash
python3 scripts/push_to_github.py
```

它走 Git Data API（blob → tree → commit → ref），全程只碰 api.github.com。
注意：`.github/workflows/` 下的文件需要 token 有 `workflow` scope，否则建 tree 会返回
404（GitHub 用 404 掩盖权限不足）。

### 定时推送（自建服务器）

```bash
# 部署（把 <ssh-端口> <服务器> 换成自己的）
tar czf - --exclude=logs --exclude=dist --exclude=.git --exclude='._*' -C llm-radar . \
  | ssh -p <ssh-端口> root@<服务器> 'mkdir -p /opt/llm-radar && tar xzf - -C /opt/llm-radar'

# 配置（服务器上，放项目目录之外，避免随站点一起被公开）
mkdir -p ~/.llm-radar && cp /opt/llm-radar/config.example.json ~/.llm-radar/config.json
chmod 600 ~/.llm-radar/config.json
# 填 env_file 与 touser 后测试
cd /opt/llm-radar && python3 scripts/push_wecom.py --test

# 定时（服务器时区为 Asia/Shanghai，直接写北京时间）
0 8,12,16,20 * * * cd /opt/llm-radar && ./update.sh >> /opt/llm-radar/logs/cron.log 2>&1
```

`update.sh` 退出码约定：`0` 成功或无新增，`1` 抓取失败，`2` 通道未配置（视为未启用），
`3` 推送失败且告警未送达。

**失败必告警**：抓取或推送任一环节失败，`update.sh` 会回调 `push_wecom.py --alert` 主动推一条
异常消息，不会静默失败。

---

## 推送原理

每次抓取后，与上一版 `data/models.json` 的模型 ID 集合做差集，差出来的就是新上线模型。
同时比对输入/输出价格，涨降价记录在 `new_models.json` 的 `price_changes` 里。

已处理的坑：

- **消息长度限制**：webhook 4096 字节 / 应用消息 1800 字节 / 智能机器人 20480 字节，脚本按通道自动分批，单条最多列 20 个模型
- **首跑刷屏**：第一次只建基线不推送
- **抓取失败**：绝不覆盖旧数据，非零退出，写 `logs/push.log`
- **token 缓存**：应用 access_token 缓存到 `logs/.wx_token.json`（600 权限），避免每次冷启动都取
- **别名噪音**：`~vendor/model-latest` 是浮动别名路由，价格跟着目标模型走，推送时整体跳过
- **页脚孤条**：打包时先预留 footer 字节，否则正文填满上限会把「看板链接」挤成一条独立消息

### 消息版式（与 `github-atom-watch` 的「通道自检」统一）

企微 Markdown 里不用 `<font>` 着色 —— 字体深浅在客户端不可控，截图/转发会失真。统一口径：

- 标题一行加粗，形如 `**大模型全景 · 上新速报** 🌶️`
- 元信息用 `标签：值 ｜ 标签：值` 纯文本行（全角冒号与竖线）
- 明细块整体用 `> ` 引用块包住，标识放反引号；每条明细空一行隔开
- 结尾用 `> ` 说明收尾，最后一行是 `[打开全景看板](url)`

```
**大模型全景 · 上新速报** 🌶️
时间：2026-10-26 12:00:00
新增：1 个 ｜ 全网：467 个 / 59 家厂商

**新模型上线**

> **1. 月之暗面 · Kimi K3.1 Pro**
> 标识：`moonshotai/kimi-k3.1-pro`
> 上下文：1M ｜ 输出：944K ｜ 智力：55.1
> 价格：¥14.3 / ¥71.5（每百万 tokens）
> 模态：文字 / 图片 / 视频 → 文字
> 能力：推理 · 工具 · JSON

> 数据源 OpenRouter ｜ 每天 08/12/16/20 点同步
> [打开全景看板](https://rayassassin.github.io/llm-radar/)
```

---

## AI 工具集（`tools.html`）

仿 [ai-bot.cn](https://ai-bot.cn/) 与 [hvoyai.com/ai-tools](https://www.hvoyai.com/ai-tools/) 做的工具清单页，
和 AI 大模型页共用同一套视觉与顶栏导航（`AI 大模型` / `AI 工具集`），两个页面顶部可直接互跳。

### 为什么这份数据是人工维护

工具没有公开的聚合 API，抓别人的导航站既不稳定也不合适（版权 + 随时改版）。
所以走**人工精选 + 版本化维护**：`data/tools.json` 就是唯一数据源，改完提交即可。
这与模型页的「浏览器实时拉取」是两种不同的取舍，各取所长。

### 字段

`data/tools.json` 结构：

```json
{
  "updated_at": "2026-10-27",
  "categories": [
    { "id": "image", "name": "图像与视觉", "color": "#d94f8a" }
  ],
  "tools": [
    {
      "id": "comfyui",
      "name": "ComfyUI",
      "cat": "image",
      "desc": "节点式扩散模型工作流，本地跑图与视频，插件生态最全",
      "url": "https://www.comfy.org/",
      "tags": ["免费", "开源"],
      "hot": false
    }
  ]
}
```

| 字段 | 说明 |
| --- | --- |
| `id` | 唯一标识，小写无空格 |
| `cat` | 必须对上 `categories[].id`，否则页面显示原始 id |
| `desc` | 一句话说清「适合干什么」，卡片里最多显示 2 行 |
| `tags` | 取值只有 `免费` / `开源` / `免费试用` / `付费` 四种，决定标签底色 |
| `hot` | 为 true 时进「热门推荐」区，并带「推荐」角标 |
| `pop` | 流行度指数 0–100（见下节，由脚本算出，不要手改） |
| `pop_tier` | 量级档位 S/A/B/C/D，指数的分档依据 |
| `pop_dims` | 四维明细 `users` / `trend` / `commercial` / `eco` |

### 流行度指数

光有一句简介，读者没法判断「哪个是主流、哪个是小众」。所以给每个工具算一个
**0–100 的流行度指数**，卡片右下角显示为「🔥 95」——火焰颜色按下表分档，鼠标悬停可看四维明细，
排序里也能选「流行度优先」。

#### 颜色分档

火焰图标按分数由热到冷变色，分页条右侧有常驻图例：

| 火焰 | 区间 | 含义 | 当前数量 |
| --- | --- | --- | --- |
| 红 | ≥ 90 | 现象级，几乎人人都在用 | 20 |
| 橙 | 80–89 | 主流，行业标配 | 69 |
| 黄 | 70–79 | 常用，特定场景优先选它 | 65 |
| 绿 | 60–69 | 圈内知名，垂直领域够用 | 50 |
| 灰 | < 60 | 小众或垂类工具 | 14 |

配色只做视觉引导，不改变分数本身。红黄绿这套顺序是「热度」语义，
和股票涨跌的红绿含义无关，别混。

#### 四维与权重

| 维度 | 字段 | 权重 | 看什么 |
| --- | --- | --- | --- |
| 用户规模 | `users` | 35% | 覆盖广度、月活量级、是否大众产品 |
| 热度趋势 | `trend` | 25% | 近半年讨论度与采用增速 |
| 商业表现 | `commercial` | 20% | 融资、营收、付费转化 |
| 技术生态 | `eco` | 20% | 开放 API、插件与社区、被第三方集成程度 |

#### 怎么算的

1. 每个工具先归一个**量级档位**：S / A / B / C / D → 基准分 93 / 82 / 70 / 55 / 38
2. 再按**分类系数**把基准分拆成四维 —— 不同品类的强弱项本来就不一样：
   - 模型类：生态 ×1.16、商业 ×0.92（开发者生态强，变现弱）
   - 办公类：商业 ×1.08、生态 ×0.93
   - 编程类：生态 ×1.12、商业 ×1.05
   - 搜索类：趋势 ×1.07（赛道还在快速变化）
3. 四维按权重加权，得到总分
4. 进「推荐位」的工具，趋势再 ×1.03

这样做的好处是四维不会退化成同一个数字 —— 中位极差 6 分，最大差 20 分，
雷达图形状才有信息量。当前分布：最高 96、中位 71、最低 36。

#### 这是判断，不是测量

**指数是编辑部判断，不是抓来的客观数据。** 依据是公开可见的规模与声量，
不接任何付费位，也不做「谁给钱谁分高」这种操作。它回答的是「值不值得先试」，
不是「谁技术更先进」。

权重、档位基准、分类系数全部集中在 `scripts/score_tools.py` 顶部：
改一处，跑一次脚本，218 个工具的分数整体重算。

```bash
python3 scripts/score_tools.py
```

脚本会做三件事：按档位表打分、校验有没有工具漏归档（漏了默认 C 并告警）、
回写 `pop` / `pop_tier` / `pop_dims`。档位表里写错的 id 也会被点名。

**分工**：`expand_tools.py` 负责把工具补进清单，`score_tools.py` 负责打分。
补录完记得跑第二个，否则新工具没有指数。

### 加一个工具

1. 在 `data/tools.json` 的 `tools` 数组里加一条，`cat` 用已有分类 id
2. 改 `updated_at` 为当天日期（顶栏会显示）
3. 跑 `python3 scripts/score_tools.py` 给它算流行度指数（不加进去就会显示为空）
4. 跑 `python3 scripts/fetch_favicons.py` 补抓官网图标（不跑就显示分类色首字母，页面不会报错）
5. 刷新页面即可，无构建步骤

分类下没有工具时，该分类按钮**自动隐藏**，不会点出空列表。

批量补录可以用 `scripts/expand_tools.py`：它按 `分类|名称|地址|简介|标签|是否推荐`
一行一条的格式合并进 JSON，已存在的同名或同址工具自动跳过。**新增后务必跑一遍
链接验证**（见下节），人工写的地址里总有失效的。

### 分类

| 分类 | 数量 | 分类 | 数量 |
| --- | --- | --- | --- |
| 对话与智能体 | 27 | 编程与开发 | 22 |
| 图像与视觉 | 23 | 模型与学习资源 | 22 |
| 视频与动画 | 21 | 办公与效率 | 19 |
| 写作与内容 | 16 | 音频与语音 | 16 |
| 设计与创意 | 15 | 搜索与研究 | 13 |
| 内容检测与安全 | 13 | 行业与商业场景 | 11 |

### 交互

| 操作 | 效果 |
| --- | --- |
| 搜索 | 匹配名称 / 简介 / 分类名 / 标签 |
| 分类按钮 | 单选，写进 URL hash（`#cat=image` 可直接分享） |
| 标签按钮 | 多选，取「或」（选免费+开源 = 两者都看） |
| 排序 | 推荐优先 / 流行度优先 / 名称（中文按拼音）/ 按分类 |
| 分页 | 默认 48 个/页，可切 24 / 96；改筛选或排序自动回第 1 页 |
| 有筛选时 | 自动隐藏「热门推荐」区，避免和结果重复占屏 |

### 链接校验

清单里的 218 个 URL 做过并发可达性验证：**202 个直连可达，16 个返回 403**。
403 全部来自 Cloudflare / Vercel 反爬（ChatGPT、Claude、Perplexity、Midjourney、Ideogram 等），
链接本身有效 —— 浏览器打开正常，只是脚本抓不了。

验证时揪出并换掉了 3 条真死链：腾讯智影（`zenvideo.qq.com` 已停）、跃问（`yuewen.cn` 无解析）、
腾讯云 AI（原路径 404），分别替换为剪映、阶跃星辰、腾讯混元。

### 卡片图标

卡片左上角显示工具官网的 favicon，抓不到就回落成「分类色淡底 + 首字母」。
图标由 `scripts/fetch_favicons.py` 预先落地到 `assets/icons/`（64×64，平均 3.6 KB），
页面只引用本地文件 —— 不在运行时挂外链，避免官网防盗链、慢响应、防盗链 404 造成的空洞。

抓取按优先级降级，任一级通过校验即停：

| 级别 | 来源 | 说明 |
| --- | --- | --- |
| 1 | 官网首页 `<link rel="...icon...">` | 最准，含 apple-touch-icon，按声明尺寸从大到小试 |
| 2 | `/favicon.ico` | 兜底常规路径 |
| 3 | `/apple-touch-icon.png` 等 | 高清但常被漏声明 |
| 4 | DDG / Google 图标镜像 | 官网 403、反爬脚本、证书异常时兜底，缓存源仍是官网 |

三个坑：

- **返回 200 不等于拿到图标。** 大量 SPA 对 `/favicon.ico` 返回的是 `index.html`（豆包 192 KB、
  grok 89 KB）。脚本按文件头 magic bytes 判定真实格式，认不出就丢弃，否则 `<img>` 里就是个碎图标。
- **白色图标会隐形。** grok 这类纯白笔画放浅色卡片上等于没有。脚本按「亮像素占比 + 不透明面积」
  判出这一档，前端给它换深色背板（`data/favicons.json` 里的 `t` 字段）。
  注意只认白笔画透明底，白底黑图案的（ChatGPT 白圆底）不换 —— 换成深色反而多出一个白圆。
- **图标自带底色。** 很多是 app icon 样式的不透明方块，容器再染分类色会露出「方块套方块」的脏边，
  所以有图标时容器背景透明。

当前命中 **217/218**，唯一失败的「一帧秒创」站点已失效（证书异常 + 全路径 404），按设计回落首字母。

```bash
python3 scripts/fetch_favicons.py              # 全量（已有文件默认复用）
python3 scripts/fetch_favicons.py --force      # 强制重抓
python3 scripts/fetch_favicons.py --only kimi  # 只补某个
python3 scripts/fetch_favicons.py --limit 20   # 先跑一批看效果
```

图标不需要天天刷新（官网 logo 很少改），换 logo 或新增工具时手动跑一次即可。

---

## AI 大事记（`daily.html`）

把每天的 AI 动态压成一条时间线：模型发布、产品更新、行业动态、论文研究。
数据来自 **AIHOT**（[aihot.news](https://aihot.news/daily)）的公开 API。

### 为什么走 API 而不是解析网页

AIHOT 在 `https://aihot.news/api/v1/agent` 里明确给了接入方式，并且专门要求：

> 要写程序做定时同步、推送或维护本地副本，不用这些地址，改用 JSON 接口：
> `https://aihot.news/openapi-v1.json`（User-Agent 用 `aihot-api/2.0.0`）

所以脚本用官方 JSON 接口 + 指定 UA，不猜 HTML 结构、不模拟浏览器：

| 接口 | 用途 |
| --- | --- |
| `GET /api/v1/dailies?limit=N` | 日报列表（日期、当日主线标题与摘要） |
| `GET /api/v1/dailies/{date}` | 单期详情（lead + 分类事件，含来源与原文链接） |

限流约 60 次/分钟，脚本按 1.2 秒间隔节流，遇到 429 读 `Retry-After` 等待。

### 合规边界（重要）

AIHOT 的使用规则写明：匿名免 Key **只是技术访问方式，不代表所有用途都获许可**。
个人非商业、公益非商业、组织内部使用免费；而**面向外部的商业产品、公开镜像、
批量公开再分发**等须事先取得书面授权，仅标注「数据来源：AIHOT」不算授权。

本站目前的做法与风险：

- 只存**索引**——标题、摘要、来源、原文链接，不存全文、不重排改写
- 每条事件都带「AIHOT」与「原文」两个出口，读者核对信息回原站
- 页脚与详情区都标明内容来自 AIHOT，版权归原信源

若本站定位转为对外公开产品，应联系 `wzglyay@virxact.com` 取得授权，
或把 `daily.html` 限制在内网访问。规则全文见 <https://aihot.news/terms>。

### 数据结构

`data/daily.json` 按日期倒序，每期保留当日主线（lead）与分类事件（sections）：

```json
{
  "date": "2026-10-27",
  "lead": { "title": "…", "paragraph": "…" },
  "sections": [
    { "label": "模型发布/更新",
      "items": [{ "title": "…", "summary": "…", "source": "X：Tibo",
                  "url": "…/items/xxx", "original": "…" }] }
  ],
  "event_count": 12
}
```

### 更新与交互

```bash
python3 scripts/fetch_daily.py              # 默认最近 30 天
python3 scripts/fetch_daily.py --days 90    # 更深的历史
python3 scripts/fetch_daily.py --date 2026-10-27   # 只补某一天
```

历史日报内容不会再变，脚本复用本地已有日期，每次只抓新的一期，通常 1–2 个请求。
`update.sh` 已把它挂在每日例行任务末尾，失败不影响模型数据，但会在 cron.log 里留 WARN。

页面支持搜索（标题/摘要/来源）、按五类事件筛选、按日期或事件数排序、逐日展开与「全部展开」。
「今日无大事」的安静日会保留在时间线上（虚线圆点、无展开按钮），否则日期会出现断档。

---

## 数据字段

数据源：`https://openrouter.ai/api/v1/models`（公开接口，无需 token）。

| 前端字段 | 数据来源 |
| --- | --- |
| 模型名 / ID | `name` / `id` |
| 上下文、最大输出 | `context_length` / `top_provider.max_completion_tokens` |
| 输入输出模态 | `architecture.input_modalities` / `output_modalities` |
| 智力指数 | `benchmarks.artificial_analysis.intelligence_index` |
| 编码 / Agent 指数 | 同上的 `coding_index` / `agentic_index` |
| 竞技场 Elo | `benchmarks.design_arena` |
| 价格 | `pricing.*`（美元/token，×1e6 换算每百万 tokens） |
| 能力 | `supported_parameters` + `hugging_face_id` |
| 发布日期 | `created`（Unix 时间戳，按 UTC+8 出日期） |

口径说明：

- **智力指数**直接取 Artificial Analysis 官方值，不是自研评分。没有该字段的模型（多数图像生成类）显示 `—`。
- **模型类型**只看产出：能产图=图像生成，能产语音=语音合成，其余=文本。多模态输入体现在「输入」列图标。
- **价格币种**默认人民币，汇率在配置 `data.usd_to_cny`（默认 7.15）。切美元只影响展示，筛选阈值固定按人民币。
- **`~` 前缀**是浮动别名路由（自动指向最新版），表格里标「路由」。

厂商中文名和品牌色在 `data/providers.json`，可手工补充。

---

## 交互

| 操作 | 效果 |
| --- | --- |
| `/` | 聚焦搜索 |
| `Esc` | 关闭详情/弹窗/清空搜索 |
| 点表头 | 按该列排序 |
| 点行 | 打开详情抽屉 |
| 勾选方框 | 加入对比（最多 4 个） |
| 点「已选条件」的 × | 移除单条筛选 |

---

## 常见问题

**顶栏显示「本地缓存」而不是「实时同步」**
浏览器拉 OpenRouter 失败（网络问题或临时故障），已自动回落缓存。刷新重试。

**推送报 `errcode=60020`**
请求 IP 不在企业可信IP 白名单。只能在服务器上跑，或去企微后台把当前出口 IP 加进去。

**推送报 `errcode=93000` / `45009`**
前者是 webhook key 无效；后者是频率限制（20 条/分钟），脚本已内置间隔。

**抓取失败**
「失败不覆盖」原则：保留上一版数据并返回非零退出码，站点不会变空。

**页面空白 / CORS 报错**
用了 `file://` 打开。走 `./run.sh` 后访问 `http://127.0.0.1:8899/`。
