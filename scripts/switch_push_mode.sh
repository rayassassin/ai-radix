#!/usr/bin/env bash
# AIRadix · LLM Radar · 推送投放范围 / 频率一键切换
#
# 用法：
#   ./scripts/switch_push_mode.sh me hourly <userid>   # 只推给我 + 每小时（灰度测试）
#   ./scripts/switch_push_mode.sh all daily            # 全员 + 每天 4 次（正式放开）
#
# 改三处，保证配置一致，不会出现「cron 每小时却没配 hourly」这种半套状态：
#   1. config.json 的 wecom.wxapp.touser  收件人
#   2. config.json 的 price_summary_mode / price_digest_hours / notify_when_empty
#   3. crontab 的执行频率
#
# 收件人优先级：config > 环境变量 > env 文件默认值。
# 所以在 config 里显式写 userid 就能压过部署机 WX_TOUSER 里的 @all，
# 不必改共享 env 文件，也不会影响同机其它项目。

set -uo pipefail
cd "$(dirname "$0")/.."

CONFIG="${AI_RADIX_CONFIG:-$HOME/.ai-radix/config.json}"

# 只取位置参数，跳过 --no-cron，避免标志位错位被当成 userid。
# 不用数组：服务器上可能是 bash 3.2，空数组在 set -u 下会炸。
SCOPE=""
CADENCE=""
USERID=""
NO_CRON=0
for a in "$@"; do
  case "$a" in
    --no-cron) NO_CRON=1 ;;
    *)
      if [ -z "$SCOPE" ]; then SCOPE="$a"
      elif [ -z "$CADENCE" ]; then CADENCE="$a"
      elif [ -z "$USERID" ]; then USERID="$a"
      fi
      ;;
  esac
done

# 覆盖了配置路径 = 演练场景，一律不动 crontab。
# 参数写错就能改掉开发机定时任务，这条兜底比任何参数都可靠。
[ -n "${AI_RADIX_CONFIG:-}" ] && NO_CRON=1

usage() {
  cat <<'EOF'
用法: switch_push_mode.sh <me|all> <hourly|daily> [userid]

  me   只推给指定成员（需带 userid，或沿用 config 里已有的值）
  all  推给应用可见范围内全部成员（touser=@all）

  hourly  每小时跑一次，每轮都出调价汇总，空轮也发巡检回执（测试期）
  daily   每天 4 次（8/12/16/20），每天 20 点汇总一次，空轮不发（正式）
EOF
  exit 1
}

case "$SCOPE" in me|all) ;; *) usage ;; esac
case "$CADENCE" in hourly|daily) ;; *) usage ;; esac
[ -f "$CONFIG" ] || { echo "❌ 找不到配置：$CONFIG"; exit 1; }

python3 - "$CONFIG" "$SCOPE" "$CADENCE" "$USERID" <<'PY'
import json, sys, pathlib

path, scope, cadence, userid = sys.argv[1:5]
p = pathlib.Path(path)
cfg = json.loads(p.read_text(encoding="utf-8"))
w = cfg.setdefault("wecom", {})
wx = w.setdefault("wxapp", {})

if scope == "all":
    wx["touser"] = "@all"
    w["mention_all"] = True
else:
    if userid:
        wx["touser"] = userid
    if not wx.get("touser") or wx["touser"] == "@all":
        sys.exit("❌ scope=me 但没给 userid，且配置里也没有可用的单人收件人")
    w["mention_all"] = False

if cadence == "hourly":
    w["price_digest_hours"] = list(range(24))
    w["price_summary_mode"] = "hourly"
    w["notify_when_empty"] = True
else:
    w["price_digest_hours"] = [8, 12, 16, 20]
    w["price_summary_mode"] = "daily"
    w["price_summary_hour"] = 20
    w["notify_when_empty"] = False

p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
p.chmod(0o600)

target = wx["touser"]
shown = "全部成员(@all)" if target == "@all" else f"{len(target.split('|'))} 个成员"
print(f"✅ 收件人：{shown}")
print(f"✅ 汇总节奏：{w['price_summary_mode']}，抓取点 {len(w['price_digest_hours'])} 个"
      f"，空轮回执 {'开' if w['notify_when_empty'] else '关'}")
PY
RC=$?
[ "$RC" -ne 0 ] && exit "$RC"

# ---- crontab ----
CRON_LINE_HOURLY='5 * * * * cd /opt/ai-radix && ./update.sh >> /opt/ai-radix/logs/cron.log 2>&1'
CRON_LINE_DAILY='0 8,12,16,20 * * * cd /opt/ai-radix && ./update.sh >> /opt/ai-radix/logs/cron.log 2>&1'

if [ "$CADENCE" = "hourly" ]; then
  NEW_CRON="$CRON_LINE_HOURLY"
else
  NEW_CRON="$CRON_LINE_DAILY"
fi

# --no-cron 或演练模式：只改配置不动定时任务（别把开发机的 crontab 改了）
if [ "$NO_CRON" = "1" ]; then
  echo "（跳过 crontab，目标行应为）"
  echo "$NEW_CRON"
  exit 0
fi

TMP=$(mktemp)
crontab -l 2>/dev/null | grep -v 'ai-radix.*update.sh' > "$TMP"
echo "$NEW_CRON" >> "$TMP"
crontab "$TMP"
rm -f "$TMP"

echo "✅ crontab 已更新："
crontab -l | grep 'update.sh'
