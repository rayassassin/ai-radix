#!/usr/bin/env bash
# AI · Radix · 定时任务入口
# 抓取最新模型数据 → diff 出新上线/调价模型 → 推送企微
# 适合挂 cron：0 8,12,16,20 * * * /path/to/update.sh >> /path/to/logs/cron.log 2>&1
#
# 失败必须告警：任何异常都会回调 push_wecom.py --alert，
# 绝不静默失败（宇神红线）。

set -uo pipefail
cd "$(dirname "$0")"

# 并发锁：每小时跑一次时，万一某轮抓取卡住超过 1 小时，下一轮进来会两轮同时写
# models.json（基线互相覆盖 → 伪调价）并重复推送。抢不到锁就静默退出，这不是失败。
LOCK_FILE="${TMPDIR:-/tmp}/ai-radix-update.lock"
if command -v flock >/dev/null 2>&1; then
  exec 200>"$LOCK_FILE"
  if ! flock -n 200; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') 上一轮仍在运行，本轮跳过（锁：$LOCK_FILE）"
    exit 0
  fi
fi

PY="${PYTHON_BIN:-python3}"
START=$(date +%s)

echo "════════════════════════════════════════"
echo "AI · Radix 更新开始  $(date '+%Y-%m-%d %H:%M:%S')"
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

# ---------- 1.5 刷新厂商图标映射 ----------
# 厂商随模型上下架会增减，映射得跟着重算。纯本地计算，几十毫秒。
# 失败不打断主流程：前端拿不到映射会自动降级成原来的色点，不影响可读性。
if VI_OUT=$("$PY" scripts/build_vendor_icons.py 2>&1); then
  echo "$VI_OUT" | head -2
else
  echo "⚠️  厂商图标映射生成失败（页面降级为色点）：$(echo "$VI_OUT" | tail -1)"
fi

# ---------- 2. 推送 ----------
"$PY" scripts/push_wecom.py
PUSH_RC=$?

# 退出码 2 = 推送通道未就绪（token 拿不到 / webhook 为空等），属于**任务失败**。
# 注意：真正「功能未启用」是 push_wecom.py 里 wecom.enabled=false，那种情况返回 0，
# 不会走到这里。以前把 2 当成「未启用」静默置 0，等于制造了一个静默失败黑洞：
# 推送没发出去、台账没消费、还不告警，下一轮带着旧账再推一遍 —— 用户看到的就是重复。
if [ "$PUSH_RC" -eq 2 ]; then
  echo "❌ 推送通道未就绪（退出码 2），本次未送达"
  alert "推送通道未就绪（退出码 2）：消息未发出，调价台账未消费，将于下次汇总时补报。请检查企微凭证与通道配置"
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

# ---------- 4. 发布数据到 GitHub Pages ----------
# 服务器是数据源头：抓完必须自己发上去，否则线上看板永远停在我手动推的那一版。
# 只发 data/ 下前端会读的三个 JSON，其余文件沿用远端原件（见 publish_pages.py）。
# 失败只告警不判失败：抓取与企微推送都已成功，不能因为发布环节回滚整轮。
PUBLISH_RC=0
if PUBLISH_OUT=$("$PY" scripts/publish_pages.py 2>&1); then
  echo "$PUBLISH_OUT" | tail -3
else
  PUBLISH_RC=$?
  echo "⚠️  Pages 发布失败（数据与推送不受影响），详情："
  echo "$PUBLISH_OUT" | tail -6
  if [ "$PUBLISH_RC" -eq 2 ]; then
    echo "    ↑ 未配置 GitHub token —— 按上面提示放好 token 后即可自动发布"
  fi
fi

ELAPSED=$(( $(date +%s) - START ))
echo "════════════════════════════════════════"
echo "完成，耗时 ${ELAPSED}s"
if [ "${DAILY_FAIL:-0}" = "1" ]; then
  echo "⚠️  本次 AI 大事记未更新，页面沿用上一版数据"
fi
if [ "$PUBLISH_RC" -ne 0 ]; then
  echo "⚠️  本次数据未发布到 Pages，线上看板仍是上一版"
fi
echo "════════════════════════════════════════"
exit "$PUSH_RC"
