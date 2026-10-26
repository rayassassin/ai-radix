# LLM Radar · 大模型全景看板

仿 [hvoyai.com/models](https://www.hvoyai.com/models/) 做的大模型目录站，支持多维筛选、排序、横向对比，
并在**新模型上线时自动推送企业微信**。

**线上地址**：https://rayassassin.github.io/llm-radar/
**仓库**：https://github.com/rayassassin/llm-radar

---

## 整体架构

| 层 | 位置 | 职责 |
| --- | --- | --- |
| 展示 | GitHub Pages（静态） | 页面本身，无需构建 |
| 数据 | 浏览器直连 OpenRouter | 每次打开实时拉取，站点永不过期 |
| 定时检测 | 自建服务器 + cron | 每日 12:00 抓取并 diff 新模型，推送订阅成员 |
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
├── index.html / app.js / style.css   # 前端（原生 JS，无构建、无 CDN）
├── build.sh                 # 生成纯静态发布目录 dist/
├── run.sh                   # 本地：抓数据 + 起服务
├── update.sh                # 定时入口：抓数据 + 推企微（cron 调这个）
├── server.py                # 零依赖本地服务（仅标准库）
├── scripts/
│   ├── fetch_models.py      # 抓取 OpenRouter → 标准化 → diff 新模型
│   ├── push_wecom.py        # 推送（支持三种通道，见下）
│   └── push_to_github.py    # 走 Data API 推仓库（git 传输受阻时用）
├── data/
│   ├── models.json          # 标准化缓存（前端兜底用）
│   ├── meta.json            # 统计快照
│   ├── new_models.json      # 本次 diff 出的新模型 + 价格变动
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

| 字段 | 说明 |
| --- | --- |
| `enabled` | 总开关 |
| `push_on_first_run` | 首次建基线是否也推。默认 false，否则开局刷 467 条 |
| `only_push_new` | 只推新模型，不推价格变动 |

### 验证

```bash
python3 scripts/push_wecom.py --test       # 发一条连通性测试
python3 scripts/push_wecom.py --dry-run    # 只打印消息，不发
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
0 12 * * * cd /opt/llm-radar && ./update.sh >> /opt/llm-radar/logs/cron.log 2>&1
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

> 数据源 OpenRouter ｜ 每日 12:00 自动同步
> [打开全景看板](https://rayassassin.github.io/llm-radar/)
```

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
