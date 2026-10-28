#!/usr/bin/env bash
# AIRadix · LLM Radar · 从服务器拉回运行时数据（反向同步）
#
# 为什么需要这个：
#   服务器是**数据源头** —— 每小时 cron 抓取 → 写 data/ → 自己发布到 Pages。
#   本地 data/ 因此永远落后于服务器（本地只有你最后一次手动抓的那一版）。
#   而 `push_to_github.py` 推的是「本地 HEAD 全量文件」，数据文件也在里面。
#   所以本地发版前不先跑这个，一推就把线上数据**倒退**到几小时甚至几天前 ——
#   看板看起来「莫名其妙少了一堆模型」，其实是自己盖回去的。
#
# 注意方向：sync_server.sh 是 本地 → 服务器（且强制排除 data/）；
#          本脚本是      服务器 → 本地（只拿 data/）。
#          两者互为补充，不能互相替代。
#
# 用法：./scripts/pull_data.sh
#       ./scripts/pull_data.sh --check    # 只比对 md5，不下载

set -euo pipefail
cd "$(dirname "$0")/.."

REMOTE_HOST="${AI_RADIX_HOST:-59.110.138.163}"
REMOTE_PORT="${AI_RADIX_PORT:-2525}"
REMOTE_DIR="${AI_RADIX_REMOTE_DIR:-/opt/ai-radix}"
KEY="${AI_RADIX_KEY:-$HOME/.ssh/zrfan_calendar_deploy}"

# raw_api.json 是原始 API 快照（体积大、可重抓、已被 .gitignore 排除），不拉
FILES="models.json new_models.json meta.json daily.json price_samples.json vendor_icons.json"

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

# macOS 只有 md5 -q，Linux 才有 md5sum；别写成 `md5sum ... | cut ... || md5 -q ...`，
# 管道会让失败被 cut 的 0 退出码吃掉，mac 上永远算出空值 → 全部误判「落后」。
if command -v md5sum >/dev/null 2>&1; then
  hash_of() { md5sum "$1" 2>/dev/null | cut -d' ' -f1; }
else
  hash_of() { md5 -q "$1" 2>/dev/null; }
fi

echo "① 读取服务器端文件指纹"
REMOTE_LIST=$(ssh -p "$REMOTE_PORT" -i "$KEY" -o StrictHostKeyChecking=no \
  "root@$REMOTE_HOST" \
  "cd '$REMOTE_DIR/data' && md5sum $FILES 2>/dev/null" )
[ -z "$REMOTE_LIST" ] && { echo "❌ 没读到服务器数据文件，检查路径 $REMOTE_DIR/data"; exit 1; }

printf "%-22s %-34s %s\n" "文件" "服务器 md5" "本地状态"
needs_pull=0
while read -r rmd5 rfile; do
  [ -z "${rfile:-}" ] && continue
  if [ -f "data/$rfile" ]; then
    lmd5=$(hash_of "data/$rfile")
    if [ "$lmd5" = "$rmd5" ]; then
      state="✅ 一致"
    else
      state="⬇️  落后"
      needs_pull=1
    fi
  else
    state="⬇️  缺失"
    needs_pull=1
  fi
  printf "%-22s %-34s %s\n" "$rfile" "$rmd5" "$state"
done <<< "$REMOTE_LIST"

if [ "$CHECK_ONLY" = "1" ]; then
  [ "$needs_pull" = "1" ] && echo "⚠️  本地数据落后于服务器 —— 发版前请先跑 ./scripts/pull_data.sh"
  exit 0
fi

if [ "$needs_pull" = "0" ]; then
  echo "② 本地已是最新，无需拉取"
  exit 0
fi

echo "② 拉取到本地 data/"
# shellcheck disable=SC2086
scp -P "$REMOTE_PORT" -i "$KEY" -o StrictHostKeyChecking=no \
  $(for f in $FILES; do echo "root@$REMOTE_HOST:$REMOTE_DIR/data/$f"; done) \
  data/ 2>&1 | tail -2

echo "③ 复核"
ok=1
while read -r rmd5 rfile; do
  [ -z "${rfile:-}" ] && continue
  lmd5=$(hash_of "data/$rfile")
  if [ "$lmd5" = "$rmd5" ]; then
    printf "  ✅ %-20s %s\n" "$rfile" "$lmd5"
  else
    printf "  ❌ %-20s 本地 %s ≠ 服务器 %s\n" "$rfile" "$lmd5" "$rmd5"
    ok=0
  fi
done <<< "$REMOTE_LIST"

[ "$ok" = "1" ] && echo "✅ 完成，本地数据已对齐服务器最新一轮抓取" \
                || { echo "❌ 有文件未对齐，请重跑"; exit 1; }
