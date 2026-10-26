#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM Radar · 企业微信群机器人推送

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
CONFIG_EXTERNAL = Path.home() / ".llm-radar" / "config.json"


def resolve_config_path() -> Path:
    """与外置配置保持同一套查找规则，避免线上密钥泄漏到站点目录。"""
    env = os.environ.get("LLM_RADAR_CONFIG")
    if env:
        return Path(env).expanduser()
    if CONFIG_EXTERNAL.exists():
        return CONFIG_EXTERNAL
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


def build_price_blocks(changes: list[dict], rate: float, threshold_pct: float,
                       max_items: int = 12) -> tuple[list[str], int]:
    """
    价格变动块。只保留幅度达阈值的条目 —— 价格每小时都在微调，
    全量推送会变成噪音，只报显著调整。

    返回 (消息块列表, 实际列出的调价条数)。
    """
    picked = []
    for c in changes:
        old, new = c.get("old") or {}, c.get("new") or {}
        # 以输入价为主判断幅度；输入缺失时退到输出价
        p = pct_change(old.get("in"), new.get("in"))
        if p is None:
            p = pct_change(old.get("out"), new.get("out"))
        if p is None or abs(p) < threshold_pct:
            continue
        picked.append((abs(p), p, c))

    if not picked:
        return [], 0

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
            text = "**价格调整**\n\n" + text
        blocks.append(text)

    if truncated:
        blocks.append(f"> 另有 {total_picked - max_items} 条调整未列出")
    return blocks, total_picked


def build_header(meta: dict, new_count: int, price_count: int) -> str:
    """消息头。结构对齐「GitHub 订阅 · 通道自检」：加粗标题 + 若干 `标签：值` 行。"""
    total = meta.get("total", "?")
    vendors = meta.get("vendors", "?")
    title = "大模型全景 · 上新速报" if new_count else "大模型全景 · 价格调整"
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


def build_footer(meta: dict, site_url: str, omitted: int = 0) -> str:
    lines = []
    if omitted > 0:
        lines.append(f"> 另有 {omitted} 个模型未展开，完整列表见看板。")
    lines.append("> 数据源 OpenRouter ｜ 每小时自动同步")
    lines.append(f"> [打开全景看板]({site_url})")
    return "\n".join(lines)


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
DEFAULT_ENV_FILE = os.path.expanduser("~/.llm-radar/wecom.env")


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
    site_url = cfg.get("site", {}).get("url") or "https://rayassassin.github.io/llm-radar/"

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
            "**大模型全景 · 任务异常** 🌶️",
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
            "**大模型全景 · 通道自检** 🌶️",
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
    threshold = float(wcfg.get("price_change_threshold", 10))  # 百分比，低于此值不报

    # 别名路由不是独立模型，价格跟着目标模型走，报出来就是同一条变动的复读
    alias_new = [m for m in new_models if is_alias(m.get("id"))]
    alias_chg = [c for c in price_changes if is_alias(c.get("id"))]
    if alias_new or alias_chg:
        log(f"跳过 {len(alias_new)} 个新增别名、{len(alias_chg)} 条别名调价（非独立模型）")
    new_models = [m for m in new_models if not is_alias(m.get("id"))]
    price_changes = [c for c in price_changes if not is_alias(c.get("id"))]

    price_blocks, price_count = build_price_blocks(price_changes, rate, threshold)

    if not new_models and not price_blocks:
        if price_changes:
            log(f"本次无新增；{len(price_changes)} 条价格变动均未达 {threshold:g}% 阈值，不推送")
        else:
            log("本次无新增模型、无价格变动，不推送")
        return 0

    # 单条消息最多列 20 个，避免刷屏
    MAX_LIST = 20
    listed = new_models[:MAX_LIST]
    omitted = max(0, len(new_models) - MAX_LIST)

    header = build_header(meta, len(new_models), price_count)
    blocks = build_blocks(listed, meta, rate, site_url) + price_blocks
    footer = build_footer(meta, site_url, omitted)
    messages = pack_messages(header, blocks, footer, max_bytes)

    log(f"准备推送：新增 {len(new_models)} 个、显著调价 {price_count} 个，共 {len(messages)} 条消息")

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

    log("全部推送成功")
    return 0


if __name__ == "__main__":
    sys.exit(main())
