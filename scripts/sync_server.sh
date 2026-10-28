#!/usr/bin/env bash
# AI · Radix · 代码同步到服务器
#
# ⚠️ 这个脚本存在的唯一理由：data/ 下的运行时产物绝不能被本地版本覆盖。
#   models.json 是**调价基线**：每次抓取后由服务器自己写成当次抓取值，
#   diff 就是拿它跟下次抓取比。一旦被本地旧文件覆盖（基线倒退），
#   同一条调价会在之后每一轮被反复 diff 出来、反复推送 —— 表现为「重复推送」。
#   new_models.json / meta.json / raw_api.json / daily.json 同理。
#   price_samples.json 是服务器的价格时序采样（错峰折扣识别依据），
#   本地覆盖会直接把攒了几天的采样冲掉，一样得排除。
#
# 用法：./scripts/sync_server.sh [服务器目录]
#   默认 59.110.138.163 的 /opt/ai-radix

set -euo pipefail
cd "$(dirname "$0")/.."

REMOTE_HOST="${AI_RADIX_HOST:-59.110.138.163}"
REMOTE_PORT="${AI_RADIX_PORT:-2525}"
REMOTE_DIR="${1:-/opt/ai-radix}"
KEY="${AI_RADIX_KEY:-$HOME/.ssh/zrfan_calendar_deploy}"

# 同步前先备份服务器上的运行时数据，真出事还能回滚
BACKUP="/opt/ai-radix-backup-$(date +%Y%m%d-%H%M%S)"
echo "① 备份服务器运行时数据 → $BACKUP"
ssh -p "$REMOTE_PORT" -i "$KEY" -o StrictHostKeyChecking=no "root@$REMOTE_HOST" \
  "mkdir -p '$BACKUP' && cp -a '$REMOTE_DIR'/data/models.json '$REMOTE_DIR'/data/new_models.json \
   '$REMOTE_DIR'/data/meta.json '$REMOTE_DIR'/data/daily.json '$BACKUP'/ 2>/dev/null; \
   ls -1 '$BACKUP' | wc -l | xargs echo '   已备份文件数:'"

echo "② 同步代码（排除运行时数据）"
tar -czf - \
  --exclude='.git' \
  --exclude='.workbuddy' \
  --exclude='__pycache__' \
  --exclude='.DS_Store' \
  --exclude='./logs' \
  --exclude='./data/models.json' \
  --exclude='./data/new_models.json' \
  --exclude='./data/meta.json' \
  --exclude='./data/raw_api.json' \
  --exclude='./data/daily.json' \
  --exclude='./data/price_samples.json' \
  --exclude='./data/vendor_icons.json' \
  . | ssh -p "$REMOTE_PORT" -i "$KEY" -o StrictHostKeyChecking=no "root@$REMOTE_HOST" \
      "tar -xzf - -C '$REMOTE_DIR'" 2>/dev/null

echo "③ 校验：服务器基线未被本次同步改动"
ssh -p "$REMOTE_PORT" -i "$KEY" -o StrictHostKeyChecking=no "root@$REMOTE_HOST" \
  "cd '$REMOTE_DIR' && ls -la --time-style=+%m-%d_%H:%M data/models.json \
   && grep -c 'price_model_cooldown_days\|change_fp' scripts/push_wecom.py \
   | xargs echo '   新代码标记命中数:'"

echo "✅ 完成。若基线时间还是上一次 cron 的时刻，说明数据没被覆盖。"
