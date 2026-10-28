#!/usr/bin/env bash
# AIRadix · LLM Radar 一键启动：先抓数据，再起本地服务
# 用法: ./run.sh            抓取 + 启动
#       ./run.sh --no-fetch 直接用现有数据启动

set -euo pipefail

cd "$(dirname "$0")"

PY="${PYTHON_BIN:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "找不到 $PY，请先安装 Python 3.9+"
  exit 1
fi

if [[ "${1:-}" != "--no-fetch" ]]; then
  echo "→ 拉取模型数据…"
  if ! "$PY" scripts/fetch_models.py; then
    echo "⚠️  抓取失败，尝试用现有数据继续启动"
  fi
fi

echo "→ 启动本地服务…"
exec "$PY" server.py
