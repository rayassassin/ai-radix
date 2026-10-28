#!/usr/bin/env bash
# AIRadix · LLM Radar · 推送链路一键诊断
#
# 用法：./scripts/diagnose_push.sh
#
# 一条命令把「为什么企微没收到」的六种可能一次查完，不需要登服务器翻文件：
#   ① crontab 是不是还在每天 4 次（没改就说明部署命令没跑过）
#   ② 服务器上的配置到底是什么（收件人打码，不打印明文）
#   ③ 新代码有没有到位
#   ④ cron.log 最近发生了什么
#   ⑤ 直接跑一次 --test，看企微返回码
#   ⑥ 自动发布所需的 token 有没有
#
# 只读为主，唯一的写操作是 ⑤ 的 --test（会真发一条企微消息，这正是要验证的）。

set -uo pipefail
cd "$(dirname "$0")/.."

REMOTE_HOST="${AI_RADIX_HOST:-59.110.138.163}"
REMOTE_PORT="${AI_RADIX_PORT:-2525}"
REMOTE_DIR="${AI_RADIX_DIR:-/opt/ai-radix}"
KEY="${AI_RADIX_KEY:-$HOME/.ssh/zrfan_calendar_deploy}"

echo "════════ 诊断 $REMOTE_HOST:$REMOTE_DIR ════════"
echo "本地时间：$(date '+%F %T %Z')"
echo

ssh -p "$REMOTE_PORT" -i "$KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=15 "root@$REMOTE_HOST" bash -s <<REMOTE
set -u
cd '$REMOTE_DIR' 2>/dev/null || { echo "❌ 目录不存在：$REMOTE_DIR"; exit 1; }

echo "───── ① crontab ─────"
crontab -l 2>/dev/null | grep -v '^#' | grep -E 'update.sh|ai-radix' || echo "（没有 ai-radix 的定时任务）"

echo
echo "───── ② 服务器配置（收件人打码）─────"
python3 - <<'PY'
import json, pathlib
for p in (pathlib.Path("/root/.ai-radix/config.json"),):
    if not p.is_file():
        print(f"  ❌ 配置不存在：{p}")
        continue
    c = json.loads(p.read_text(encoding="utf-8"))
    w = c.get("wecom") or {}
    wx = w.get("wxapp") or {}
    t = wx.get("touser") or ""
    if t == "@all":
        shown = "@all（全员）"
    elif t:
        parts = [x for x in t.split("|") if x]
        shown = f"{len(parts)} 个成员：{parts[0][:4]}***{parts[0][-2:]}"
    else:
        shown = "（空，会退回 env 文件的 WX_TOUSER）"
    print(f"  enabled            : {w.get('enabled')}")
    print(f"  transport          : {w.get('transport')}")
    print(f"  touser             : {shown}")
    print(f"  mention_all        : {w.get('mention_all')}")
    print(f"  price_digest_hours : {w.get('price_digest_hours')}")
    print(f"  price_summary_mode : {w.get('price_summary_mode')}")
    print(f"  price_summary_hour : {w.get('price_summary_hour')}")
    print(f"  notify_when_empty  : {w.get('notify_when_empty')}")
PY

echo
echo "───── ③ 代码版本 ─────"
for f in scripts/publish_pages.py scripts/switch_push_mode.sh scripts/push_wecom.py; do
  # 注意：\$() 必须转义，否则会在本地 shell 先展开 —— macOS 的 BSD stat 没有 -c，直接报 illegal option
  if [ -f "\$f" ]; then echo "  ✅ \$f  (\$(date -r "\$f" '+%m-%d %H:%M' 2>/dev/null))"; else echo "  ❌ 缺 \$f"; fi
done
echo -n "  push_wecom 含 hourly 汇总: "; grep -c 'parse_summary_mode' scripts/push_wecom.py 2>/dev/null | head -1
echo -n "  update.sh 含自动发布步骤: "; grep -c 'publish_pages' update.sh 2>/dev/null | head -1

echo
echo "───── ④ cron.log 最近关键行 ─────"
tail -60 logs/cron.log 2>/dev/null | grep -E '更新开始|已记账|准备推送|消息 |推送通道|回执|发布|失败|告警|跳过|Traceback|Error' | tail -25 || echo "  （日志为空或不存在）"

echo
echo "───── ⑤ 实发一条测试消息 ─────"
TEST_RC=0
TEST_OUT=\$(timeout 90 python3 scripts/push_wecom.py --test 2>&1) || TEST_RC=\$?
echo "\$TEST_OUT" | tail -8
echo "  退出码：\$TEST_RC（0=已送达，2=通道未就绪，1=发送失败）"

echo
echo "───── ⑥ 自动发布 token ─────"
if [ -s /root/.ai-radix/github.env ]; then
  echo "  ✅ /root/.ai-radix/github.env 存在（token 行 $(grep -c GITHUB_TOKEN /root/.ai-radix/github.env 2>/dev/null | head -1) 条）"
else
  echo "  ❌ 没有 /root/.ai-radix/github.env —— 数据不会自动上 Pages"
fi
REMOTE

echo
echo "════════ 诊断结束 ════════"
echo "把上面输出整段发给我即可定位。重点看 ①（crontab 是否已是每小时）、⑤（企微返回码）。"
