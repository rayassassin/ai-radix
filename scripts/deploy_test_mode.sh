#!/usr/bin/env bash
# AI · Radix · 一键部署「灰度测试模式」到服务器
#
# 做四件事，幂等，可反复执行：
#   ① 同步代码（走 sync_server.sh，排除运行时数据，先备份基线）
#   ② 服务器配置切成「只推给自己 + 每小时 + 空轮回执」
#   ③ 立即发一条测试消息，确认收件人和通道
#   ④ 检查 GitHub token 是否就位（自动发布 Pages 的前提）
#
# 用法：
#   ./scripts/deploy_test_mode.sh <你的企微 userid>
#   ./scripts/deploy_test_mode.sh <userid> --no-test     # 跳过测试消息
#
# 放开（回到全员 + 每天 4 次）：
#   ssh -p 2525 -i ~/.ssh/zrfan_calendar_deploy root@59.110.138.163 \
#     'cd /opt/ai-radix && ./scripts/switch_push_mode.sh all daily'

set -uo pipefail
cd "$(dirname "$0")/.."

USERID="${1:-${AI_RADIX_TOUSER:-}}"
SKIP_TEST="${2:-}"

# 没显式给 userid 时，从本地配置里读（config 优先，其次老路径）。
# 这样部署时不用把 userid 敲在命令行里，也不会出现在 shell 历史。
if [ -z "$USERID" ]; then
  for cfg in "${AI_RADIX_CONFIG:-}" "$HOME/.ai-radix/config.json" "$HOME/.llm-radar/config.json"; do
    [ -n "$cfg" ] && [ -f "$cfg" ] || continue
    USERID=$(python3 -c "
import json,sys
try:
    c=json.load(open('$cfg'))
    t=((c.get('wecom') or {}).get('wxapp') or {}).get('touser') or ''
    print('' if t.strip()=='@all' else t.strip())
except Exception:
    print('')
")
    [ -n "$USERID" ] && break
  done
fi

if [ -z "$USERID" ]; then
  echo "用法: $0 [企微 userid] [--no-test]"
  echo "  不传 userid 时会自动从 ~/.ai-radix/config.json 或 ~/.llm-radar/config.json 读取"
  echo "  两处都没有时就手工传：$0 <你的 userid>"
  exit 1
fi

REMOTE_HOST="${AI_RADIX_HOST:-59.110.138.163}"
REMOTE_PORT="${AI_RADIX_PORT:-2525}"
REMOTE_DIR="${AI_RADIX_DIR:-/opt/ai-radix}"
KEY="${AI_RADIX_KEY:-$HOME/.ssh/zrfan_calendar_deploy}"

SSH=(ssh -p "$REMOTE_PORT" -i "$KEY" -o StrictHostKeyChecking=no "root@$REMOTE_HOST")

echo "===== ① 同步代码 ====="
./scripts/sync_server.sh "$REMOTE_DIR" || { echo "❌ 同步失败，后续步骤已跳过"; exit 1; }

echo
echo "===== ② 切成「只推自己 + 每小时」 ====="
"${SSH[@]}" "cd '$REMOTE_DIR' && ./scripts/switch_push_mode.sh me hourly '$USERID'"
RC=$?
if [ "$RC" -ne 0 ]; then
  echo "❌ 配置切换失败（退出码 $RC），未继续"
  exit "$RC"
fi

if [ "$SKIP_TEST" != "--no-test" ]; then
  echo
  echo "===== ③ 发一条测试消息 ====="
  "${SSH[@]}" "cd '$REMOTE_DIR' && python3 scripts/push_wecom.py --test 2>&1 | tail -6"
fi

echo
echo "===== ④ 自动发布前置检查（GitHub token）====="
"${SSH[@]}" "if [ -s /root/.ai-radix/github.env ] || grep -q '\"token\": *\"[^\"]' /root/.ai-radix/config.json 2>/dev/null; then \
   echo '✅ token 已配置，update.sh 会自动发布 data/ 到 Pages'; \
 else \
   echo '⚠️  未配置 GitHub token —— 抓取和企微推送正常，但数据不会自动上 Pages。'; \
   echo \"    在服务器上执行（read -s 交互输入，不落 shell 历史）：\" ; \
   echo \"      read -rsp '粘贴 fine-grained PAT: ' T && echo \\\"GITHUB_TOKEN=\\\$T\\\" > /root/.ai-radix/github.env && unset T && chmod 600 /root/.ai-radix/github.env\" ; \
   echo '    注意：占位符 github_pat_xxx 只有 14 字符，GitHub 会回 401，别原样抄'; \
   echo '    权限只需 ai-radix 仓库的 Contents: Read and write（fine-grained PAT，约 93 字符）'; \
 fi"

echo
echo "✅ 部署完成。下一轮 cron（每小时第 5 分）起生效。"
echo "   看日志：ssh -p $REMOTE_PORT -i $KEY root@$REMOTE_HOST 'tail -40 $REMOTE_DIR/logs/cron.log'"
