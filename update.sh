#!/usr/bin/env bash
# LLM Radar · 定时任务入口
# 抓取最新模型数据 → diff 出新上线/调价模型 → 推送企微
# 适合挂 cron：0 8,12,16,20 * * * /path/to/update.sh >> /path/to/logs/cron.log 2>&1
#
# 失败必须告警：任何异常都会回调 push_wecom.py --alert，
# 绝不静默失败（宇神红线）。

set -uo pipefail
cd "$(dirname "$0")"

PY="${PYTHON_BIN:-python3}"
START=$(date +%s)

echo "════════════════════════════════════════"
echo "LLM Radar 更新开始  $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════"

# 告警回调：参数为失败原因。告警自身失败也不能影响主流程退出码。
alert() {
  local reason="$1"
  echo "🔔 触发失败告警：$reason"
  "$PY" scripts/push_wecom.py --alert "$reason" 2>&1 | sed 's/^/    /'
  local rc=$?
  [ "$rc" -ne 0 ] && echo "⚠️  告警未能送达（退出码 $rc）—— 请检查收件人配置"
  return 0
}

# ---------- 1. 抓取 ----------
if ! FETCH_OUT=$("$PY" scripts/fetch_models.py 2>&1); then
  echo "$FETCH_OUT"
  echo "❌ 抓取失败 —— 已有数据保持不变，本次不推送"
  # 取最后一行错误摘要，避免把整段堆栈塞进企微消息
  REASON=$(echo "$FETCH_OUT" | grep -viE '^\s*$' | tail -1 | cut -c1-180)
  alert "数据抓取失败：${REASON:-未知错误}"
  exit 1
fi
echo "$FETCH_OUT"

# ---------- 2. 推送 ----------
"$PY" scripts/push_wecom.py
PUSH_RC=$?

# 退出码 2 = 推送通道未配置，属于「功能未启用」，不算任务失败
if [ "$PUSH_RC" -eq 2 ]; then
  echo "⚠️  推送未启用（通道未配置），数据已更新完成"
  PUSH_RC=0
elif [ "$PUSH_RC" -eq 3 ]; then
  echo "❌ 推送失败且告警未送达（退出码 3）"
elif [ "$PUSH_RC" -ne 0 ]; then
  echo "❌ 推送失败（退出码 $PUSH_RC）"
  alert "消息推送失败（退出码 $PUSH_RC），请检查企微通道与凭证"
fi

# ---------- 3. AI 大事记 ----------
# 只抓 AIHOT 最新一期（历史日报不变，脚本会自动复用本地已有日期）。
# 属于增量补充功能：失败重试 3 次仍不成就记警告，不打断主流程，
# 但也绝不静默 —— cron.log 里会留下明确的 WARN 行。
if DAILY_OUT=$("$PY" scripts/fetch_daily.py --days 30 2>&1); then
  echo "$DAILY_OUT" | tail -3
else
  echo "⚠️  AI 大事记抓取失败（不影响模型数据），详情："
  echo "$DAILY_OUT" | tail -5
  DAILY_FAIL=1
fi

ELAPSED=$(( $(date +%s) - START ))
echo "════════════════════════════════════════"
echo "完成，耗时 ${ELAPSED}s"
if [ "${DAILY_FAIL:-0}" = "1" ]; then
  echo "⚠️  本次 AI 大事记未更新，页面沿用上一版数据"
fi
echo "════════════════════════════════════════"
exit "$PUSH_RC"
