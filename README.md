# AIRadix · LLM Radar · 大模型全景看板

两个页面，共用一套视觉与导航：

| 页面 | 仿照 | 内容 |
| --- | --- | --- |
| **AI 大模型** `index.html` | [hvoyai.com/models](https://www.hvoyai.com/models/) | 466+ 模型的实时价格、上下文、能力，多维筛选 / 排序 / 分页 / 横向对比 |
| **AI 工具集** `tools.html` | [ai-bot.cn](https://ai-bot.cn/) · [hvoyai.com/ai-tools](https://www.hvoyai.com/ai-tools/) | 218 款按 12 个场景归类的 AI 工具，人工精选 |

模型页在**新模型上线时自动推送企业微信**（每天 8/12/16/20 点检测）。

**线上地址**：https://rayassassin.github.io/ai-radix/
**仓库**：https://github.com/rayassassin/ai-radix

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
ai-radix/
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
│   ├── publish_pages.py     # 服务器端：只发 data/*.json 到 Pages（零依赖）
│   ├── sync_server.sh       # 本地 → 服务器：同步代码（强制排除 data/）
│   ├── pull_data.sh         # 服务器 → 本地：拉回 data/（发版前必跑）
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

查找顺序：`AI_RADIX_CONFIG` 环境变量 → `~/.ai-radix/config.json` → 项目内 `config.json`。

外置是为了避免密钥随站点目录被公开部署。

```bash
mkdir -p ~/.ai-radix
cp config.example.json ~/.ai-radix/config.json
chmod 600 ~/.ai-radix/config.json
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
| `price_digest_hours` | `[8,12,16,20]` | 每天哪几个整点**抓取并推送新增模型**（数组，24 制）。需与 crontab 一致 |
| `price_summary_hour` | 20 | 每天几点出**调价汇总**（24 制）。不填则取 `price_digest_hours` 的最后一项 |
| `price_summary_mode` | `daily` | 汇总节奏。`daily` = 每天只在 `price_summary_hour` 汇总一次；`hourly` = 每轮抓取都汇总（测试期用，靠指纹去重 + 冷却防复读） |
| `notify_when_empty` | false | 空轮也发一条「巡检回执」。测试期打开，能一眼看出通道还在跑；正式放开前关掉 |
| `price_model_cooldown_days` | 7 | 同一个模型播报后多少天内不再重复播报（0 = 关闭）。兜底用，防厂商错峰折扣反复刷屏 |
| `price_cooldown_breakout` | 2.0 | 冷却期内的例外：本次幅度达到上次播报幅度的该倍数时，视为新一轮真实调价，照常播报 |
| `price_promo_push` | false | 是否把「限时优惠」也推到群里。默认关闭：折扣只刷新看板，群里只收**上新**和**真实调价**两类消息 |
| `max_bytes_per_message` | 1800 | 单条正文上限，按通道自动适配 |

> ⚠️ **两个时刻必须分开，不能配成一样。**
> 抓取点同时是汇总点时，台账刚记账就被消费掉，净变化去抖的窗口为 0，
> 相邻两次推送会把同一次摆动一涨一跌各报一次（表现为「重复推送」）。
> 新增模型仍按抓取点及时推，只有调价攒到汇总点出一次。

### 为什么调价要双门槛 + 按批次汇总

OpenRouter 的 `models` 接口返回的价格是**几十个路由里的最低价**。实测 `moonshotai/kimi-k3`
背后有 29 个中转站，报价从 $0.20 到 $4.50（相差 22.5 倍），接口给的就是最低那个。

最低价是所有数字里最不稳定的：哪家做促销、哪家下架，这个数就跳。$0.20 → $0.17 看着跌 15%，
实际每百万 tokens 只差 ¥0.21。所以：

- **百分比 + 绝对金额双门槛**：低价模型的微小抖动过滤掉，高价模型的真实调价照报
- **按批次汇总而非逐小时推**：中间过程记进台账（`logs/.price_ledger.json`），
  只保留每个模型的**最早起点 + 最新终点**，来回摆动自然抵消，只报净变化

台账的关键约束：**跨抓取点累积，每天只在汇总点消费一次**。抓取时刻（8/12/16/20）
照常跑，但只有汇总点（默认 20 点）才播报调价；播报出去的条目从台账移除，
被截断或没达标的留着继续累积。这样既不会漏报，也不会把同一次摆动报两遍。

### 比价的锚点是「基准价」，不是「上一次抓取值」

这是踩过的坑，也是当前口径的核心。

实测轨迹（`z-ai/glm-5.3-flash`，2026-10-28）：

```
09–10 点  ¥0.15      ← 常态价
11–14 点  ¥0.0453    ← 4 小时促销
15 点起   ¥0.15      ← 回到常态价
```

牌价一动没动，只是做了 4 小时促销。但用「上一次抓取值」做锚点，15 点那条变动就是
`0.0453 → 0.15`，被算成 **涨 578%** 发进了群 —— 用户看到的是「GLM 5.3 Flash 暴涨」，
实际是优惠结束。这就是「按小时级波动调推送内容」的典型坏结果。

现在改为以**基准价**（近 3 天采样序列的众数，`models.json` 的 `ref` 字段）为锚点，
把每轮 diff 分成四类：

| 分类 | 判定 | 处理 |
|---|---|---|
| **回到基准价** | 现价与基准价差 ≤ 2% | **静默**。促销结束不播报 |
| **限时优惠** | 现价低于基准价 | 发「限时优惠（非调价）」，注明基准价与折扣，明确写了恢复原价不再通知 |
| **高于基准价** | 现价高于基准价 | 不抢跑，交给「基准价迁移」判定 |
| **基准价迁移** | `ref` 本身变了，且新价已连续挂 ≥ 3 个采样点 | **这才是真实调价**，正常播报涨/跌 |

为什么这样能免疫短期波动：**促销不改变众数**。4 小时的低价在 3 天窗口里只占少数，
基准价仍然压在原价那档，所以「进出促销」在产品层面只是两个 `ref` 相同的价，不构成任何调价事件。

代价是真实调价会**慢半天到一天**（要等新价成为众数、并且挂稳 3 个采样点才认账）。
这是有意的取舍：宁可晚报，也不要按小时级抖动报错。

补充两点：
- 优惠**不进台账**（恢复原价时无需冲销），但同样写播报档案，受指纹去重与 7 天冷却约束
- 已被识别为周期性错峰的模型（`off_peak`），降价一律静默 —— 夜间折扣天天有，天天播就是噪音
- 台账里**净变化归零**的条目会被当场清掉（涨了又跌回原处），否则它会一直挂着把 `since` 拖老


### 折扣展示：周期 + 时段

看板上的折扣不是只标「打折」，而是把**什么时候便宜**说清楚（参照同类产品的写法）：

```
DeepSeek-V4.1-Flash  [☾ 夜间折扣] 0.50x
deepseek/deepseek-v4.1-flash-1017
5 折 ｜ 每日 20:00–次日 08:00 低谷
```

- 徽章只放**类型名 + 图标**：`夜间折扣`（月亮，时段型）/ `限时折扣`（标签，非时段型），
  系数 `0.50x` 单独跟在后面弱化显示，不抢主信息
- 名字下面一行写周期：`5 折 ｜ 每日 20:00–次日 08:00 低谷`
- 详情抽屉按「标签—值」行排：折扣周期 / 低谷时段 / 高峰原价 / 基准价→现价 / 判断依据
- 时段以**连续区间**给出（`off_ranges` / `on_ranges`），跨零点合并成
  `20:00–次日 08:00`，不拆成两段

数据来源（`detect_off_peak`）：把采样按小时聚合后，低价档的小时合并成区间；
周期由采样日期推断，`scope` 取 `daily / weekday / partial / unknown`。

**样本不足 1 天时不会写「每日」**——那是承诺，我们只知道「观察到」。
此时文案退化成「近 1 天 13:00–15:00 出现低谷（待确认）」，详情里也标明
「样本不足，规律待确认」。宁可说得保守，也不给一个没根据的规律。

折扣**只更新看板、不推送**。云服务器照样每小时抓，页面上的徽章和时段会跟着变；
企微只在「上新」和「基准价迁移（真实调价）」时发消息。

回归测试（改判定或文案前后都该跑一遍）：

```bash
python3 scripts/selftest_price.py     # 价格判定：18 项，含 GLM 那次误报的完整轨迹
node scripts/selftest_discount.js     # 折扣文案：21 项，含「折数不能打架」「样本不足不写每日」
```

### 厂商错峰折扣：为什么 DeepSeek 会天天「调价」

实测 20:00 抓到的 DeepSeek 变动：`v4.1-flash-1017` 0.3→0.15、`v4-pro-0813` 1.32→0.66，
**精确到 50%** —— 这是 DeepSeek 官方的错峰折扣（16:30–00:30 半价），不是调价。
抓取点跨过折扣边界就会报一次「降 50%」，次日跨回去再报一次「涨 100%」，周而复始。

两条防线：

1. **24 小时台账窗口**：窗口只要覆盖完整的一天，起点与终点都落在折扣时段内，
   净变化为 0，自然不报。这也是汇总点必须固定、且不能与抓取点重合的深层原因。
2. **同模型冷却（兜底）**：万一窗口被截断（首次部署、汇总失败重试、临时改点），
   同一个模型 `price_model_cooldown_days` 天内也不再重复播报，
   除非幅度达到上次播报幅度的 `price_cooldown_breakout` 倍。

### 错峰折扣：把「麻烦」变成看板信息

既然厂商的错峰折扣会持续制造调价噪声，不如把它识别出来当作选型信息展示。
看板上带 `错峰 5 折` 徽章的模型，就是被识别出「固定时段打折」的。

识别逻辑（`scripts/fetch_models.py`）：

- 每次抓取把价格记进 `data/price_samples.json`，按 `天 → 小时 → 模型` 累积，保留 3 天
- 判据是三条同时成立：
  1. 高低价落差 ≥ 20%
  2. **价格会回到原价**（切换 ≥ 2 次）—— 真实调价只切一次、一去不回，靠这条区分
  3. 同一小时跨天价位一致（极差 ≤ 10%）—— 排除随机抖动
- 结果写进 `models.json` 每条的 `off_peak` 字段，浏览器侧直连时按 id 回填

**冷启动要 2 天**：单日采样最多只能观察到一次切换，无法区分「错峰」和「一次性调价」，
所以第一天不判定。跨天拿到回归证据后自动出现。

### ⚠️ 部署红线：绝不能用本地 data/ 覆盖服务器

`data/models.json` 是**调价基线**——服务器每次抓取后自己写入当次抓取值，
下一轮的 diff 就是拿它来比。本地那份是几天前的快照，一旦被同步覆盖（基线倒退），
同一条真实调价会在之后每一轮被反复 diff 出来、反复推送。

实测踩过：一次不留神的 `tar | ssh tar -x` 把本地旧基线推到服务器，
结果 `qwen/qwen3.8-27b`（0.039→0.2）在 16 点、20 点连报两次同样的「涨 413%」。

**必须走 `scripts/sync_server.sh`**，它排除 `data/` 下的运行时产物
（`models.json` / `new_models.json` / `meta.json` / `raw_api.json` / `daily.json`），
并在同步前自动备份一份到服务器。

新增模型仍按抓取时刻走 —— 每天 4 次，够及时，又不会把群里刷成流水账。

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
tar czf - --exclude=logs --exclude=dist --exclude=.git --exclude='._*' -C ai-radix . \
  | ssh -p <ssh-端口> root@<服务器> 'mkdir -p /opt/ai-radix && tar xzf - -C /opt/ai-radix'

# 配置（服务器上，放项目目录之外，避免随站点一起被公开）
mkdir -p ~/.ai-radix && cp /opt/ai-radix/config.example.json ~/.ai-radix/config.json
chmod 600 ~/.ai-radix/config.json
# 填 env_file 与 touser 后测试
cd /opt/ai-radix && python3 scripts/push_wecom.py --test

# 定时（服务器时区为 Asia/Shanghai，直接写北京时间）
# 每天 4 次：0 8,12,16,20 * * *
# 每小时 1 次（测试期）：5 * * * *     —— 错开整点，避开限流与整点拥堵
0 8,12,16,20 * * * cd /opt/ai-radix && ./update.sh >> /opt/ai-radix/logs/cron.log 2>&1
```

### 测试期：只推给自己、每小时一次

正式放开前先小范围验证，三处要一起改：

```jsonc
// ~/.ai-radix/config.json（本地是 ~/.llm-radar/config.json）
"wecom": {
  "wxapp": { "touser": "<你的 userid>" },   // 显式写单人，压过部署机 env 里的 @all
  "price_digest_hours": [0,1,2,...23],      // 铺满全天（与 crontab 对齐）
  "price_summary_mode": "hourly",           // 每轮都出调价汇总
  "notify_when_empty": true                 // 空轮也发一条巡检回执
}
```

```bash
5 * * * * cd /opt/ai-radix && ./update.sh >> /opt/ai-radix/logs/cron.log 2>&1
```

`touser` 的优先级是 **配置文件 > 环境变量 > env 文件默认值**，所以只要在 config 里显式写了
userid，就一定能压过部署机 `WX_TOUSER` 里的 `@all`——不用改共享 env 文件，也不会影响
同一台机器上其它项目。

放开时把 `touser` 改回 `@all`、`price_summary_mode` 回 `daily`、
`notify_when_empty` 回 `false`，crontab 改回 `0 8,12,16,20 * * *` 即可。

上面这套用一条命令就够：

```bash
./scripts/switch_push_mode.sh me hourly <userid>   # 灰度
./scripts/switch_push_mode.sh all daily            # 放开
```

### 自动发布到 GitHub Pages

服务器抓到的数据得自己发上去，否则线上看板永远停在最后一次手动推送的版本。
`update.sh` 第 4 步调用 `scripts/publish_pages.py`，**只发前端会读的三个文件**：

```
data/models.json   data/meta.json   data/daily.json
```

`tools.json` / `providers.json` / `favicons.json` 是本地生成的静态资产，服务器不产出，
所以远端这些文件原样保留（脚本按远端 tree 的 sha 平铺重建，不会丢）。

和 `push_to_github.py` 的分工：那个依赖 `git ls-files` + `gh` CLI，用于开发机整仓发布；
服务器上 `/opt/ai-radix` 是 tar 解出来的，**没有 .git 也没装 gh**，所以发布走纯 REST + urllib。

**开自动发布只需要一个 token**，三处任选其一：

```bash
# 推荐：env 文件，600 权限，不随代码流转
# read -s 交互输入：既不会把 token 留在 shell 历史里，也不会误把示例当值抄进去
read -rsp "粘贴你的 fine-grained PAT（约 93 字符）: " T && \
  echo "GITHUB_TOKEN=$T" > ~/.ai-radix/github.env && unset T
chmod 600 ~/.ai-radix/github.env
```

> ⚠️ 别把示例里的占位符当值抄。`github_pat_xxx` 只有 14 个字符，GitHub 对它会返回
> `401 Bad credentials`——报错看不出根因，最容易卡在这里。脚本会提前拦：长度 < 30
> 直接判定为占位符并给出正确做法。

或者写进 `~/.ai-radix/config.json` 的 `github.token`，或者给进程环境变量 `GITHUB_TOKEN`。

用 **fine-grained PAT**，范围只勾 `ai-radix` 这一个仓库的 **Contents: Read and write**，
别用 classic token（权限过大）。没配 token 时这一步只记 WARN 不判失败——抓取和企微推送
已经成功，不该因为发布环节回滚整轮。

**数据没变就不提交。** 脚本先算本地 git blob sha 与远端同路径比对，三者一致直接退出，
不造空提交——否则每小时一次 cron 会把提交历史刷成垃圾。

```bash
python3 scripts/publish_pages.py --dry-run    # 只看会改哪些文件
python3 scripts/publish_pages.py --force      # 内容无变化也提交（调试）
```

`update.sh` 退出码约定：`0` 成功或无新增，`1` 抓取失败，`2` 通道未配置（视为未启用），
`3` 推送失败且告警未送达。发布失败不改变退出码，只在日志里留 WARN。

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
> [打开全景看板](https://rayassassin.github.io/ai-radix/)
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

### 日历（统计卡最右侧）

统计区第五格是月历：左半是当前聚焦日（期号 / 大日期 / 年月 / 星期），右半点阵。

- **点某天** → 时间线只留那一天并自动展开，滚到卡片顶部；再点同一天或点结果栏的日期胶囊即可取消
- 点阵三态：有事件 = 深色实心；「今日安静」= 浅圆（仍可点开看当期主线）；数据未覆盖 = 淡数字不可点
- 翻月范围锁在有数据的月份内（当前是 2026-09 ~ 2026-10），出界的箭头置灰
- 翻月**不改变**当前筛选，只是换视图；左半大日期跟着切到该月最后一期，筛选状态始终以结果栏的日期胶囊为准
- 「第 N 期」是本地收录序号（最早一期为第 1 期），不是 AIHOT 官方期号

两个实现上的坑：

1. `.stats` 是全局类，模型页也在用。日历要更宽，所以五列定义写在 `.page-daily .stats` 里；
   同理 1080 断点的两列覆盖也必须写成 `.page-daily .stats`，否则优先级不够、窄屏仍是五列被挤扁。
2. 滚动定位没用 `requestAnimationFrame` —— 页面在后台时 rAF 会被暂停，反而漏掉滚动。
   `render()` 同步写完 DOM 后直接量位置即可。

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

**cron 报 `UnboundLocalError: cannot access local variable 'xxx'`**
`main()` 里变量先被读取、后被赋值，整轮推送崩掉，还会顺带发一条假的「推送失败」告警。
2026-10-28 真踩过一次（`promo_push` 的定义被放在引用点之后，只在「本轮恰好有限时优惠」时才炸）。
现在 `selftest_price.py` 第 ⑤ 项会用 AST 静态扫 `main()`：任何局部变量首次读取早于首次赋值、
或全函数从未赋值，直接判失败。改完推送逻辑先跑一遍：`python3 scripts/selftest_price.py`。

**发布后线上数据「倒退」了**
本地 `data/` 落后于服务器。`push_to_github.py` 推的是本地 HEAD 全量文件，数据文件也在里面，
一推就把线上盖回旧版。发版前先 `./scripts/pull_data.sh`（`--check` 只比对不下载）。

**服务器抓完没自动发布**
服务器缺 GitHub token。放在 `/root/.ai-radix/github.env`，内容 `GITHUB_TOKEN=<fine-grained PAT>`，
权限 `600`，PAT 只需 `ai-radix` 仓库的 Contents: Read and write。
服务器 `git`/`ssh` 通道未必可用，`publish_pages.py` 走 REST API 直传 blob，不依赖 git 和 gh。
