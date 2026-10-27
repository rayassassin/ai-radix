#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI · Radix · 企业微信群机器人推送

职责：读取 data/new_models.json 中本次 diff 出的新上线模型，推送到企微群。

设计要点：
  - 首次运行（无基线）默认不推送，避免开号即刷 400+ 条
  - webhook 未配置时安全退出（退出码 2），不算失败，不阻塞抓取
  - 发送失败必须非零退出并打日志 —— 静默失败是不可接受的
  - 企微 markdown 有 4096 字节硬上限，超长自动分批

用法:
  python3 scripts/push_wecom.py --dry-run   # 只打印消息，不发送
  python3 scripts/push_wecom.py             # 正式推送
  python3 scripts/push_wecom.py --test      # 发一条连通性测试
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
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
    """与外置配置保持同一套查找规则，避免线上密钥泄漏到站点目录。"""
    env = os.environ.get("AI_RADIX_CONFIG") or os.environ.get("LLM_RADAR_CONFIG")
    if env:
        return Path(env).expanduser()
    for p in (CONFIG_EXTERNAL, CONFIG_LEGACY):
        if p.exists():
            return p
    return ROOT / "config.json"
NEW_PATH = DATA_DIR / "new_models.json"
META_PATH = DATA_DIR / "meta.json"
LOG_DIR = ROOT / "logs"

TZ_CN = timezone(timedelta(hours=8))
WEBHOOK_BASE = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key="


def now_cn() -> datetime:
    return datetime.now(TZ_CN)


def log(msg: str) -> None:
    line = f"[{now_cn():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with (LOG_DIR / "push.log").open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_json(path: Path, default=None):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def fmt_ctx(n) -> str:
    if not n or n <= 0:
        return "—"
    if n >= 1048576:
        v = f"{n / 1048576:.2f}".rstrip("0").rstrip(".")
        return f"{v}M"
    if n >= 1000:
        return f"{round(n / 1000)}K"
    return str(n)


def fmt_money(v, rate: float) -> str:
    if v is None:
        return "—"
    if v == 0:
        return "免费"
    cny = v * rate
    if cny >= 100:
        s = f"{cny:.0f}"
    elif cny >= 10:
        s = f"{cny:.1f}"
    elif cny >= 1:
        s = f"{cny:.2f}".rstrip("0").rstrip(".")
    elif cny >= 0.01:
        s = f"{cny:.3f}".rstrip("0").rstrip(".")
    else:
        s = f"{cny:.4f}".rstrip("0").rstrip(".")
    return f"¥{s}"


MOD_CN = {"text": "文字", "image": "图片", "audio": "音频", "video": "视频", "file": "文件"}

# 排版口径与「GitHub 订阅 · 通道自检」保持一致：
#   · 标题一行加粗，后面跟 `标签：值 ｜ 标签：值` 的纯文本行
#   · 不使用 <font> 着色标签（企微里字体深浅不可控，截图/转发会失真）
#   · 每条明细用 `> ` 引用块包住，标识用反引号
#   · 结尾用一条 `> ` 说明收尾
QUOTE = "> "


def q(lines: list[str]) -> list[str]:
    """把若干行渲染成一个引用块 —— 每行都要挂前缀，否则企微只认第一行。"""
    return [QUOTE + ln if ln else ">" for ln in lines]


def model_block(idx: int, m: dict, rate: float) -> str:
    """单个模型的明细块。信息密度优先，格式跟通道自检统一。"""
    caps = m.get("caps") or {}
    tags = []
    if caps.get("reasoning"):
        tags.append("推理")
    if caps.get("tools"):
        tags.append("工具")
    if caps.get("json"):
        tags.append("JSON")
    if caps.get("open_weights"):
        tags.append("开放权重")

    ins = " / ".join(MOD_CN.get(x, x) for x in (m.get("input_modalities") or []))
    outs = " / ".join(MOD_CN.get(x, x) for x in (m.get("output_modalities") or []))
    modality = f"{ins} → {outs}" if ins else ""

    pin, pout = m.get("price", {}).get("in"), m.get("price", {}).get("out")
    if pin == 0 and pout == 0:
        price = "**免费**"
    elif pin is None and pout is None:
        price = "暂无公开定价"
    else:
        price = f"{fmt_money(pin, rate)} / {fmt_money(pout, rate)}（每百万 tokens）"

    # 上下文 / 输出 / 智力 挤在「标签：值 ｜ 值」一行，跟自检的 meta 行同构
    metrics = [f"上下文：{fmt_ctx(m.get('context'))}"]
    if m.get("max_output"):
        metrics.append(f"输出：{fmt_ctx(m.get('max_output'))}")
    iq = m.get("iq")
    if isinstance(iq, (int, float)):
        metrics.append(f"智力：{iq:.1f}")

    body = [
        f"**{idx}. {m.get('vendor_cn') or m.get('vendor')} · {m.get('name')}**",
        f"标识：`{m.get('id')}`",
        " ｜ ".join(metrics),
        f"价格：{price}",
    ]
    if modality:
        body.append(f"模态：{modality}")
    if tags:
        body.append(f"能力：{' · '.join(tags)}")
    return "\n".join(q(body))


def build_blocks(models: list[dict], meta: dict, rate: float, site_url: str,
                 titled: bool = True) -> list[str]:
    """把新模型切成消息块。区块标题并入第一块，避免分批时标题被孤立。"""
    blocks = []
    for i, m in enumerate(models, 1):
        text = model_block(i, m, rate)
        if i == 1 and titled:
            text = "**新模型上线**\n\n" + text
        blocks.append(text)
    return blocks


def is_alias(mid: str) -> bool:
    """`~vendor/model-latest` 是 OpenRouter 的浮动别名路由，价格随目标模型浮动。
    它不是独立模型，报新增或调价只会制造重复噪音，推送时一律跳过。"""
    return str(mid or "").lstrip().startswith("~")


def pct_change(old, new) -> float | None:
    """变动百分比。任一值缺失或旧值为 0 时无法计算。"""
    if old is None or new is None:
        return None
    try:
        old_f, new_f = float(old), float(new)
    except (TypeError, ValueError):
        return None
    if old_f <= 0:
        return None
    return (new_f - old_f) / old_f * 100


def judge_change(c: dict, rate: float) -> tuple[float | None, float]:
    """
    判断一条价格变动该不该报，返回 (百分比, 绝对金额 CNY/1M tokens)。

    OpenRouter 的 models 接口给的是**几十个路由里的最低价**，最低价由最便宜的
    中转站决定 —— 谁在做促销、谁上下线，这个数就跳。$0.20 → $0.17 看着跌 15%，
    实际每百万 tokens 只差 ¥0.21。所以必须同时看百分比和绝对金额，
    只看百分比会被低价模型的小抖动刷屏。
    """
    old, new = c.get("old") or {}, c.get("new") or {}
    # 输入/输出两侧都算，取幅度更大的一侧作为这条变动的代表值。
    # 早期写法是「输入价算得出就直接用」，结果输入价没变、只有输出价变的模型
    # 会被判成 0% 直接漏报 —— 缓存/输出侧调价恰恰是最常见的那一类。
    best = None  # (|百分比|, 百分比, 绝对金额)
    for key in ("in", "out"):
        p = pct_change(old.get(key), new.get(key))
        if p is None:
            continue
        try:
            abs_cny = abs(float(new[key]) - float(old[key])) * rate
        except (KeyError, TypeError, ValueError):
            abs_cny = 0.0
        if best is None or abs(p) > abs(best[1]):
            best = (abs(p), p, abs_cny)
    if best is None:
        return None, 0.0
    return best[1], best[2]


def build_price_blocks(changes: list[dict], rate: float, threshold_pct: float,
                       min_abs_cny: float = 0.0,
                       max_items: int = 12,
                       section: str = "价格调整") -> tuple[list[str], int, list[dict]]:
    """
    价格变动块。双重门槛：百分比达标 **且** 绝对金额达标。

    只报绝对金额够大的 —— 低价模型的百分比跳动对用户没有决策价值
    （¥0.21/百万 tokens 的差异不值得一条推送）。

    返回 (文本块, 达标总数, 实际列出的条目)。第三个返回值供「播报即消费」用：
    台账只移除真正发出去的条目，没列出的（超出 max_items 被截断的）留着下次再报。
    """
    picked = []
    for c in changes:
        p, abs_cny = judge_change(c, rate)
        if p is None or abs(p) < threshold_pct:
            continue
        if abs_cny < min_abs_cny:
            continue
        picked.append((abs(p), p, c))

    if not picked:
        return [], 0, []

    picked.sort(key=lambda x: -x[0])
    truncated = len(picked) > max_items
    total_picked = len(picked)
    picked = picked[:max_items]

    blocks = []
    for i, (_, p, c) in enumerate(picked, 1):
        old, new = c.get("old") or {}, c.get("new") or {}
        sign = "降" if p < 0 else "涨"
        head = (f"**{i}. {c.get('vendor_cn') or c.get('vendor', '')} · {c.get('name', '')}**"
                f" {sign} {abs(p):.1f}%")
        old_in, new_in = old.get("in"), new.get("in")
        old_out, new_out = old.get("out"), new.get("out")
        detail = [head, f"标识：`{c.get('id', '')}`"]
        line = f"输入：{fmt_money(old_in, rate)} → **{fmt_money(new_in, rate)}**"
        # 输出侧没变就不显示，避免「¥3.58 → ¥3.58」这种噪声
        if fmt_money(old_out, rate) != fmt_money(new_out, rate):
            line += f" ｜ 输出：{fmt_money(old_out, rate)} → **{fmt_money(new_out, rate)}**"
        detail.append(line + "（每百万 tokens）")
        text = "\n".join(q(detail))
        if i == 1:
            text = f"**{section}**\n\n" + text
        blocks.append(text)

    if truncated:
        blocks.append(f"> 另有 {total_picked - max_items} 条调整未列出")
    return blocks, total_picked, [c for _, _, c in picked]


def build_header(meta: dict, new_count: int, price_count: int, digest: bool = False,
                 site_title: str = "") -> str:
    """消息头。结构对齐「GitHub 订阅 · 通道自检」：加粗标题 + 若干 `标签：值` 行。

    标题前缀取 config.site.title（如「AI · Radix」），缺省回落「大模型全景」。
    """
    total = meta.get("total", "?")
    vendors = meta.get("vendors", "?")
    brand = (site_title or "").strip() or "大模型全景"
    if new_count:
        title = f"{brand} · 上新速报"
    elif digest:
        title = f"{brand} · 价格汇总"
    else:
        title = f"{brand} · 价格调整"
    bits = []
    if new_count:
        bits.append(f"新增：{new_count} 个")
    if price_count:
        bits.append(f"调价：{price_count} 个")
    change = " ｜ ".join(bits) if bits else "本次无变化"
    return "\n".join([
        f"**{title}** 🌶️",
        f"时间：{now_cn():%Y-%m-%d %H:%M:%S}",
        f"{change} ｜ 全网：{total} 个 / {vendors} 家厂商",
    ])


def parse_push_hours(wcfg: dict) -> list[int]:
    """
    推送/汇总时刻（本地时区的小时，24 制）。

    优先读 `price_digest_hours`（数组，如 [8,12,16,20]）；
    兼容旧的单值写法 `price_digest_hour`；都没有则回退 12 点。
    非法值静默丢弃，宁可少推一次也不要因为配置写错整天不推。
    """
    raw = wcfg.get("price_digest_hours")
    if raw is None:
        raw = wcfg.get("price_digest_hour", 12)
    if isinstance(raw, (int, str)):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return [12]

    hours = set()
    for item in raw:
        try:
            h = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= h <= 23:
            hours.add(h)
    return sorted(hours) or [12]


def fmt_hours(hours: list[int]) -> str:
    return " / ".join(f"{h:02d}:00" for h in hours)


def parse_summary_hour(wcfg: dict, push_hours: list[int]) -> int:
    """
    每日价格汇总时刻（24 制）。台账跨所有抓取点累积，只有每天汇总一次，
    「最早起点 + 最新终点」的净变化去抖才有意义。

    优先读 `price_summary_hour`；未配置时取 `price_digest_hours` 的**最后一项**
    （如 [8,12,16,20] → 20 点），这样线上老配置不用改就能自动落到「每日一汇」。
    """
    raw = wcfg.get("price_summary_hour")
    if raw is None:
        raw = push_hours[-1] if push_hours else 20
    try:
        h = int(raw)
    except (TypeError, ValueError):
        h = push_hours[-1] if push_hours else 20
    return h if 0 <= h <= 23 else 20


def build_footer(meta: dict, site_url: str, omitted: int = 0, since: str = "",
                 sync_note: str = "") -> str:
    lines = []
    if since:
        lines.append(f"> 统计区间：{since} 起（来回波动已按净变化合并，不重复报送）")
    if omitted > 0:
        lines.append(f"> 另有 {omitted} 个模型未展开，完整列表见看板。")
    lines.append(f"> 数据源 OpenRouter ｜ {sync_note or '定时同步，调价按批次汇总'}")
    lines.append(f"> [打开全景看板]({site_url})")
    return "\n".join(lines)


# ---------------- 调价台账 ----------------
# 调价不逐小时推，而是先记账、到点汇总。原因见 judge_change 的注释：
# 最低价路由的抖动本身没有决策价值，按净变化看才是真相。
LEDGER_PATH = ROOT / "logs" / ".price_ledger.json"


def load_ledger() -> dict:
    d = load_json(LEDGER_PATH, {}) or {}
    if not isinstance(d, dict) or not isinstance(d.get("items"), dict):
        d = {"since": None, "items": {}}
    return d


def save_ledger(ledger: dict) -> None:
    """原子写：先写临时文件再替换，避免 cron 并发时写出半个 JSON。"""
    try:
        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = LEDGER_PATH.with_name(LEDGER_PATH.name + ".tmp")
        tmp.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(LEDGER_PATH)
    except OSError as e:
        log(f"台账写入失败：{e}")


def merge_into_ledger(ledger: dict, changes: list[dict], rate: float,
                      threshold_pct: float, min_abs_cny: float) -> int:
    """
    把本轮合格的变动并入台账。同一模型只保留**最早起点 + 最新终点**，
    所以涨了又跌回去的模型，净变化自然归零、不会出现在汇总里。
    """
    stamp = f"{now_cn():%Y-%m-%d %H:%M}"
    merged = 0
    for c in changes:
        p, abs_cny = judge_change(c, rate)
        if p is None or abs(p) < threshold_pct or abs_cny < min_abs_cny:
            continue
        mid = c.get("id")
        if not mid:
            continue
        old, new = c.get("old") or {}, c.get("new") or {}
        item = ledger["items"].get(mid)
        if item is None:
            ledger["items"][mid] = {
                "id": mid,
                "name": c.get("name", ""),
                "vendor": c.get("vendor", ""),
                "vendor_cn": c.get("vendor_cn", ""),
                "old": old,
                "new": new,
                "times": 1,
                "first_seen": stamp,
                "last_seen": stamp,
            }
            if not ledger.get("since"):
                ledger["since"] = stamp
        else:
            item["new"] = new          # 起点留最早，终点用最新 → 得到净变化
            item["times"] = int(item.get("times", 1)) + 1
            item["last_seen"] = stamp
        merged += 1
    return merged


def ledger_as_changes(ledger: dict) -> list[dict]:
    return [v for v in ledger["items"].values() if isinstance(v, dict)]


def drop_notified(ledger: dict, changes: list[dict]) -> None:
    """
    只移除本轮**真正播报出去**的条目，然后给台账打上当天的汇总戳。

    早期写法是整本台账一把清空，两个后果：
      1. 超出 max_items 被截断的条目跟着一起没了，等于静默丢信息；
      2. 更重要的是，配合「每 4 小时汇总一次」的配置，台账存活时间为 0 ——
         记账完立刻汇总、汇总完立刻清空，「最早起点 + 最新终点」的净变化去抖
         完全失效，跨窗口的来回摆动就会在相邻两次推送里各报一次（一涨一跌），
         看起来像重复推送。
    现在改成：播报即消费，没播出去的继续累积到下次，跨窗口摆动自动抵消。
    """
    for c in changes or []:
        mid = c.get("id")
        if mid:
            ledger["items"].pop(mid, None)
    if not ledger["items"]:
        ledger["since"] = None      # 台账空了，统计区间跟着归零
    ledger["last_summary_date"] = f"{now_cn():%Y-%m-%d}"


def pack_messages(header: str, blocks: list[str], footer: str, max_bytes: int) -> list[str]:
    """按 UTF-8 字节数打包，避免企微 4096 字节静默截断。

    打包时先扣掉 footer 的字节数再算预算 —— 否则正文正好填满上限时，
    footer 会被挤成一条 100 多字节的孤立消息（「数据源…／看板链接」单独一条），
    看起来像发漏了。预留之后 footer 必定能并入末条。
    """
    footer_reserve = len(footer.encode("utf-8")) + 2  # +2 是 footer 前的空行
    budget = max(400, max_bytes - footer_reserve)

    messages = []
    cur = header
    for b in blocks:
        candidate = cur + "\n\n" + b
        if len(candidate.encode("utf-8")) > budget and cur != header:
            messages.append(cur)
            cur = b
        else:
            cur = candidate
    if cur.strip():
        messages.append(cur)

    # 末条补 footer
    if messages:
        last = messages[-1] + "\n\n" + footer
        if len(last.encode("utf-8")) > max_bytes:
            messages.append(footer)
        else:
            messages[-1] = last
    else:
        messages.append(header + "\n\n" + footer)
    return messages


def post_json(url: str, payload: dict, retries: int = 3) -> tuple[bool, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("errcode") == 0:
                return True, "ok"
            # 45009: 接口调用超过限制；93000: 机器人 webhook 无效
            return False, f"errcode={data.get('errcode')} errmsg={data.get('errmsg')}"
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
            msg = f"第 {attempt}/{retries} 次发送失败：{e}"
            log(msg)
            if attempt < retries:
                time.sleep(2 * attempt)
    return False, "重试耗尽"


def send_text_mention(webhook: str, content: str) -> tuple[bool, str]:
    return post_json(webhook, {
        "msgtype": "text",
        "text": {"content": content, "mentioned_list": ["@all"]},
    })


def send_markdown(webhook: str, content: str) -> tuple[bool, str]:
    return post_json(webhook, {
        "msgtype": "markdown",
        "markdown": {"content": content},
    })


# ---------------- 智能机器人通道 ----------------
# 走本机 wecom-cli，以企微智能机器人身份发消息。
# 与群机器人 webhook 的差异：
#   - markdown 上限 20480 字节（webhook 只有 4096），基本不用分批
#   - 不支持 @所有人
#   - 只能在本机跑（CLI 授权绑定本机），云端 CI 用不了

WECOM_CLI = "wecom-cli"


def aibot_sessions() -> list[dict]:
    """拉取当前可发送的会话列表。CLI 要求 chat_id 必须来自本次调用。"""
    try:
        proc = subprocess.run(
            [WECOM_CLI, "message", "aibot", "sessions", "list"],
            capture_output=True, text=True, timeout=40,
        )
    except FileNotFoundError:
        raise RuntimeError("找不到 wecom-cli，请先安装：npm install -g @wecom/cli")
    except subprocess.TimeoutExpired:
        raise RuntimeError("wecom-cli 调用超时")
    if proc.returncode != 0:
        raise RuntimeError(f"会话列表获取失败：{(proc.stderr or proc.stdout)[:200]}")
    try:
        return json.loads(proc.stdout).get("sessions") or []
    except json.JSONDecodeError:
        raise RuntimeError("会话列表返回格式异常")


def resolve_chat_id(chat_name: str) -> str:
    """按群名精确匹配。chat_id 是内部标识，只在本进程内使用，不落日志不外露。"""
    sessions = aibot_sessions()
    for s in sessions:
        if (s.get("chat_name") or "").strip() == chat_name.strip():
            return s["chat_id"]
    names = "、".join(s.get("chat_name", "?") for s in sessions[:10])
    raise RuntimeError(f"未找到会话「{chat_name}」。当前可发送：{names}")


def send_via_aibot(chat_name: str, content: str) -> tuple[bool, str]:
    try:
        chat_id = resolve_chat_id(chat_name)
    except RuntimeError as e:
        return False, str(e)

    payload = {
        "chat_id": chat_id,
        "msg_type": "markdown",
        "markdown": {"content": content},
    }
    try:
        proc = subprocess.run(
            [WECOM_CLI, "message", "aibot", "send", "--json",
             json.dumps(payload, ensure_ascii=False)],
            capture_output=True, text=True, timeout=40,
        )
    except subprocess.TimeoutExpired:
        return False, "发送超时"
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout)[:200]
    return True, "ok"


# ---------------- 自建应用消息通道 ----------------
# 走企微 message/send，以自建应用身份发给成员。
# 约束：
#   - 只能发 touser（成员）/ toparty（部门）/ 应用自建的群，发不进普通群
#   - 请求 IP 必须在「企业可信IP」白名单里，所以只能在白名单内的机器上跑
#   - markdown 正文按 2048 字节上限处理，这里保守取 1800

# 兜底凭据文件位置（实际路径由 config 的 wecom.wxapp.env_file 指定，
# 不写死任何机器上的具体路径，避免公开仓库暴露部署细节）
DEFAULT_ENV_FILE = os.path.expanduser("~/.ai-radix/wecom.env")


def parse_env_file(path: str) -> dict:
    """解析 KEY=VALUE 环境文件，兼容 systemd 的 `Environment=KEY=VALUE` 写法。
    支持 `~` 展开，方便配置里写家目录下的路径。"""
    try:
        text = Path(os.path.expanduser(str(path))).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("Environment="):
            line = line[len("Environment="):]
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def wxapp_credentials(cfg: dict) -> dict:
    """
    凭据来源：进程环境变量 > 配置指定的 env 文件（可多个，按序合并）。

    设计原则：任何凭证与成员标识都不写进项目配置文件，一律从部署机上已有的
    env 文件读取，避免密钥随代码流转（也避免仓库里出现具体路径）。
    """
    wxcfg = (cfg.get("wecom") or {}).get("wxapp") or {}
    files = wxcfg.get("env_file") or DEFAULT_ENV_FILE
    if isinstance(files, str):
        files = [files]

    merged = {}
    for path in files:
        merged.update(parse_env_file(path))
    merged.update({k: v for k, v in os.environ.items() if k.startswith(("WX_", "WECOM_"))})

    return {
        "corpid": merged.get("WX_CORPID", ""),
        "secret": merged.get("WX_SECRET", ""),
        "agentid": merged.get("WX_AGENTID", ""),
        # 优先级：配置文件显式指定 > 环境变量 > 共享文件里的默认收件人。
        # 显式配在 config 里的收件人必须能压过共享文件的默认值，
        # 否则想改成 @all 之类的目标会被部署机上的旧值悄悄覆盖。
        "touser": (wxcfg.get("touser")
                   or merged.get("WX_TOUSER")
                   or merged.get("PREVIEW_TOUSER")
                   or ""),
    }


_TOKEN_CACHE = ROOT / "logs" / ".wx_token.json"


def wxapp_token(creds: dict) -> str:
    """access_token 缓存到文件，避免 cron 每次冷启动都取一次。"""
    now = time.time()
    try:
        cached = json.loads(_TOKEN_CACHE.read_text(encoding="utf-8"))
        if cached.get("token") and cached.get("exp", 0) - now > 300:
            return cached["token"]
    except (OSError, json.JSONDecodeError):
        pass

    url = (f"https://qyapi.weixin.qq.com/cgi-bin/gettoken"
           f"?corpid={creds['corpid']}&corpsecret={creds['secret']}")
    with urllib.request.urlopen(url, timeout=20) as resp:
        r = json.loads(resp.read().decode("utf-8"))
    if r.get("errcode", 0) != 0:
        raise RuntimeError(f"gettoken 失败 errcode={r.get('errcode')} errmsg={r.get('errmsg')}")

    token = r["access_token"]
    exp = int(now) + int(r.get("expires_in", 7200))
    try:
        _TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_CACHE.write_text(json.dumps({"token": token, "exp": exp}), encoding="utf-8")
        _TOKEN_CACHE.chmod(0o600)
    except OSError:
        pass
    return token


def send_via_wxapp(creds: dict, content: str) -> tuple[bool, str]:
    if not (creds.get("corpid") and creds.get("secret") and creds.get("agentid")):
        return False, "缺少 WX_CORPID / WX_SECRET / WX_AGENTID"
    if not creds.get("touser"):
        return False, "缺少收件人 WX_TOUSER"

    try:
        token = wxapp_token(creds)
    except Exception as e:
        return False, f"取 access_token 失败：{e}"

    try:
        agentid = int(creds["agentid"])
    except (TypeError, ValueError):
        return False, f"agentid 非法：{creds.get('agentid')!r}"

    payload = {
        "touser": creds["touser"],
        "msgtype": "markdown",
        "agentid": agentid,
        "markdown": {"content": content},
    }
    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST",
    )
    for attempt in range(1, 3):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                r = json.loads(resp.read().decode("utf-8"))
            if r.get("errcode", 0) == 0:
                return True, "ok"
            # 60020 = 调用 IP 不在企业可信IP，说明没在服务器上跑
            return False, f"errcode={r.get('errcode')} errmsg={r.get('errmsg')}"
        except Exception as e:
            if attempt == 2:
                return False, str(e)
            time.sleep(2)
    return False, "重试耗尽"


def resolve_webhook(cfg: dict) -> str:
    """环境变量优先，方便 CI / cron 注入；其次读 config.json。"""
    key = (os.environ.get("WECOM_WEBHOOK_KEY") or "").strip()
    if key:
        return WEBHOOK_BASE + key if not key.startswith("http") else key
    raw = (cfg.get("wecom", {}).get("webhook") or "").strip()
    if not raw:
        return ""
    if raw.startswith("http"):
        return raw
    return WEBHOOK_BASE + raw


def make_sender(cfg: dict):
    """
    按配置选择推送通道，返回 (send_fn, 目标描述, 错误信息)。
    transport 可选：
      wxapp  — 自建应用消息，推荐；仅能在可信IP白名单内的机器上跑
      aibot  — 智能机器人（wecom-cli），仅能在本机跑
      webhook— 群机器人，任意环境都能跑，但不能 @ 之外的定制
    """
    wcfg = cfg.get("wecom") or {}
    transport = (wcfg.get("transport") or "wxapp").strip().lower()

    if transport == "wxapp":
        creds = wxapp_credentials(cfg)
        missing = [k for k in ("corpid", "secret", "agentid", "touser") if not creds.get(k)]
        if missing:
            return None, "", f"缺少凭据：{', '.join(missing)}（检查 env 文件与 WX_TOUSER）"
        targets = [x.strip() for x in creds["touser"].split("|") if x.strip()]
        if "@all" in targets or len(targets) == 0:
            desc = "自建应用消息 → 应用可见范围内全部成员"
        else:
            desc = f"自建应用消息 → {len(targets)} 个成员"
        return lambda msg: send_via_wxapp(creds, msg), desc, None

    if transport == "aibot":
        chat_name = ((wcfg.get("aibot") or {}).get("chat_name") or "").strip()
        if not chat_name:
            return None, "", "未配置 wecom.aibot.chat_name"
        return (
            lambda msg: send_via_aibot(chat_name, msg),
            f"智能机器人 → {chat_name}",
            None,
        )

    webhook = resolve_webhook(cfg)
    if not webhook:
        return None, "", "未配置 webhook key"
    return lambda msg: send_markdown(webhook, msg), "企业微信群机器人", None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印消息内容，不实际发送")
    ap.add_argument("--test", action="store_true", help="发送一条测试消息验证连通性")
    ap.add_argument("--force", action="store_true", help="忽略「仅推新模型」限制")
    ap.add_argument("--digest", action="store_true",
                    help="强制出一份调价汇总（不等 price_digest_hours 的整点），用于手动验证")
    ap.add_argument(
        "--alert",
        metavar="原因",
        default="",
        help="发送一条任务失败告警（由 update.sh 在异常时调用），不读新增数据",
    )
    args = ap.parse_args()

    cfg = load_json(resolve_config_path())
    if not cfg:
        log(f"配置缺失：{resolve_config_path()}")
        return 1

    wcfg = cfg.get("wecom", {})
    if not wcfg.get("enabled", True):
        log("企微推送已在 config.json 中关闭（wecom.enabled=false），跳过")
        return 0

    sender, target_desc, send_err = make_sender(cfg)
    transport = (wcfg.get("transport") or "wxapp").strip().lower()
    max_bytes = int(wcfg.get("max_bytes_per_message", 1800))
    rate = float(cfg["data"].get("usd_to_cny", 7.15))
    site_url = cfg.get("site", {}).get("url") or "https://rayassassin.github.io/ai-radix/"
    # 消息头品牌名统一取配置，改一处就全站一致（页面侧的品牌在 HTML 的 .brand-title）
    brand = (cfg.get("site", {}).get("title") or "").strip() or "大模型全景"

    meta = load_json(META_PATH) or {}
    payload = load_json(NEW_PATH) or {}
    new_models = payload.get("models") or []
    has_baseline = payload.get("has_baseline", True)

    # ---------- 失败告警 ----------
    # 由 update.sh 在抓取/推送失败时回调。设计原则：告警本身绝不能再抛异常，
    # 否则失败会变成静默 —— 宁可返回非零码让 cron 邮件兜底。
    if args.alert:
        reason = args.alert.strip()[:300]
        msg = "\n".join([
            f"**{brand} · 任务异常** 🌶️",
            f"时间：{now_cn():%Y-%m-%d %H:%M:%S}",
            f"原因：{reason}",
            f"已收录：{meta.get('total', '?')} 个模型 ｜ 上次更新：{meta.get('updated_at') or '未知'}",
            "",
            "> 已有数据未被覆盖，站点仍可访问，只是本次未刷新。",
            f"> [打开全景看板]({site_url})",
        ])
        if args.dry_run:
            print(msg)
            return 0
        if not sender:
            log(f"告警无法发送（通道未就绪）：{send_err}")
            return 3
        ok, info = sender(msg)
        if ok:
            log("失败告警已推送")
            return 0
        log(f"失败告警发送失败：{info}")
        return 3

    # ---------- 测试模式 ----------
    if args.test:
        transport_cn = {"wxapp": "自建应用消息", "aibot": "智能机器人", "webhook": "群机器人"}
        msg = "\n".join([
            f"**{brand} · 通道自检** 🌶️",
            f"时间：{now_cn():%Y-%m-%d %H:%M:%S}",
            f"通道：{target_desc or transport_cn.get(transport, transport)}",
            f"收录：{meta.get('total', '?')} 个模型 / {meta.get('vendors', '?')} 家厂商",
            f"最近更新：{meta.get('updated_at') or '—'}",
            "",
            "> 收到即说明推送通道正常，可忽略。",
            f"> [打开全景看板]({site_url})",
        ])
        if args.dry_run:
            print(msg)
            return 0
        if not sender:
            log(f"无法发送测试消息：{send_err}")
            return 2
        log(f"目标：{target_desc}")
        ok, info = sender(msg)
        if ok:
            log("测试消息已发送，去企微看看")
            return 0
        log(f"测试消息发送失败：{info}")
        return 1

    # ---------- 是否该推 ----------
    if not has_baseline and not wcfg.get("push_on_first_run", False) and not args.force:
        log(f"首次建立基线（{len(new_models)} 个模型），按配置不推送。下次检测到真正新增时会推。")
        return 0

    price_changes = payload.get("price_changes") or []
    threshold = float(wcfg.get("price_change_threshold", 10))       # 百分比门槛
    min_abs = float(wcfg.get("price_change_min_abs_cny", 1.0))      # 绝对金额门槛（¥/百万 tokens）
    push_hours = parse_push_hours(wcfg)                             # 每天哪几个整点推送

    # 别名路由不是独立模型，价格跟着目标模型走，报出来就是同一条变动的复读
    alias_new = [m for m in new_models if is_alias(m.get("id"))]
    alias_chg = [c for c in price_changes if is_alias(c.get("id"))]
    if alias_new or alias_chg:
        log(f"跳过 {len(alias_new)} 个新增别名、{len(alias_chg)} 条别名调价（非独立模型）")
    new_models = [m for m in new_models if not is_alias(m.get("id"))]
    price_changes = [c for c in price_changes if not is_alias(c.get("id"))]

    # ---------- 调价先记账 ----------
    # 逐小时推调价等于把「最低价路由的抖动」当新闻播。改成记账 + 每日汇总：
    # 只有净变化够大的模型才会出现在汇总里，来回摆动自动抵消。
    ledger = load_ledger()
    merged = merge_into_ledger(ledger, price_changes, rate, threshold, min_abs)
    if merged and not args.dry_run:
        save_ledger(ledger)
    if merged:
        # 预演只改内存不落盘，日志里说清楚，免得排查时误以为台账已被消费
        tail = "（预演，未落盘）" if args.dry_run else ""
        log(f"调价已记账 {merged} 条（台账累计 {len(ledger['items'])} 个模型）{tail}")

    # ---------- 到点才出价格汇总 ----------
    # 抓取点（cron 8/12/16/20）与汇总点必须分开：两者重合时台账刚记账就被消费掉，
    # 净变化去抖零窗口，最低价路由的来回摆动会在相邻两次推送里各报一次（一涨一跌）。
    # 台账跨抓取点累积、每天只在汇总点播报一次，摆动才抵消得掉。
    summary_hour = parse_summary_hour(wcfg, push_hours)
    today = f"{now_cn():%Y-%m-%d}"
    last_summary = ledger.get("last_summary_date")
    # 今天还没汇总过，且（到了汇总点 ｜ 台账里从没汇总过 —— 首次部署不必干等一天）
    due = (last_summary != today) and (now_cn().hour >= summary_hour or last_summary is None)
    is_digest = bool(args.digest) or due

    if is_digest:
        price_blocks, price_count, price_listed = build_price_blocks(
            ledger_as_changes(ledger), rate, threshold, min_abs,
            section="价格变动汇总（净变化）")
    else:
        price_blocks, price_count, price_listed = [], 0, []

    if not new_models and not price_blocks:
        # 下一个汇总点：今天还没到就写今天，过了就写明天的同一时刻
        now_h = now_cn().hour
        day = "" if now_h < summary_hour else "明日 "
        if price_changes:
            log(f"本次无新增；{len(price_changes)} 条变动未达门槛"
                f"（{threshold:g}% 且 ¥{min_abs:g}/百万 tokens），"
                f"台账累计 {len(ledger['items'])} 个模型，{day}{summary_hour:02d}:00 汇总")
        else:
            log(f"本次无新增模型、无价格变动，不推送"
                f"（台账 {len(ledger['items'])} 个模型，{day}{summary_hour:02d}:00 汇总）")
        return 0

    # 单条消息最多列 20 个，避免刷屏
    MAX_LIST = 20
    listed = new_models[:MAX_LIST]
    omitted = max(0, len(new_models) - MAX_LIST)

    header = build_header(meta, len(new_models), price_count, digest=is_digest,
                          site_title=brand)
    blocks = build_blocks(listed, meta, rate, site_url) + price_blocks
    footer = build_footer(meta, site_url, omitted,
                          since=ledger.get("since") if (is_digest and price_count) else "",
                          sync_note=f"每天 {fmt_hours(push_hours)} 同步，"
                                    f"价格每天 {summary_hour:02d}:00 汇总")
    messages = pack_messages(header, blocks, footer, max_bytes)

    log(f"准备推送：新增 {len(new_models)} 个、汇总调价 {price_count} 个，共 {len(messages)} 条消息")

    if args.dry_run:
        for i, msg in enumerate(messages, 1):
            print(f"\n{'=' * 20} 消息 {i}/{len(messages)} · {len(msg.encode('utf-8'))} 字节 {'=' * 20}\n")
            print(msg)
        return 0

    if not sender:
        log(f"无法推送：{send_err}")
        log("→ 检查 config 的 wecom.transport 与对应通道配置")
        return 2

    log(f"推送通道：{target_desc}")

    # @所有人 仅群机器人 webhook 支持；应用消息与 markdown 都做不到
    if transport == "webhook" and wcfg.get("mention_all", False):
        ok, info = send_text_mention(
            resolve_webhook(cfg),
            f"【大模型上新】本次新增 {len(new_models)} 个模型，详情见下条消息。",
        )
        if not ok:
            log(f"@所有人 提醒发送失败：{info}")
        time.sleep(0.5)

    failed = 0
    for i, msg in enumerate(messages, 1):
        ok, info = sender(msg)
        if ok:
            log(f"消息 {i}/{len(messages)} 发送成功（{len(msg.encode('utf-8'))} 字节）")
        else:
            failed += 1
            log(f"消息 {i}/{len(messages)} 发送失败：{info}")
        time.sleep(0.6)  # 企微机器人限 20 条/分钟，留余量

    if failed:
        log(f"推送完成但有 {failed} 条失败 —— 请检查 webhook 是否有效、是否触发频率限制")
        return 1

    # 汇总已成功送达才消费台账；发送失败就整本留着，下次汇总继续带上，不丢信息
    if is_digest and price_count:
        drop_notified(ledger, price_listed)
        save_ledger(ledger)
        left = len(ledger["items"])
        log(f"已播报 {len(price_listed)} 条并移出台账"
            + (f"，{left} 条未列出/未达标，继续累积" if left else "，台账已空"))

    log("全部推送成功")
    return 0


if __name__ == "__main__":
    sys.exit(main())
