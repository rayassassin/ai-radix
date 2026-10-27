#!/usr/bin/env bash
# 生成纯静态发布目录 dist/
# 只带前端运行必需的文件，避免把脚本、日志、原始 API 备份一起公开出去

set -euo pipefail
cd "$(dirname "$0")"

rm -rf dist
mkdir -p dist/data dist/assets

cp index.html app.js style.css dist/
cp tools.html tools.js dist/
cp daily.html daily.js dist/
cp data/models.json data/meta.json data/providers.json data/tools.json dist/data/ 2>/dev/null || true
# 工具图标：官网 favicon 的本地副本（脚本 scripts/fetch_favicons.py 生成）
cp data/favicons.json dist/data/ 2>/dev/null || true
# AI 大事记：AIHOT 日报索引（脚本 scripts/fetch_daily.py 生成）
cp data/daily.json dist/data/ 2>/dev/null || true
[ -d assets/icons ] && cp -R assets/icons dist/assets/

# 数据缓存里的站点地址改写成线上地址（若有配置）
python3 - <<'PY'
import json, pathlib
p = pathlib.Path('dist/data/meta.json')
if p.exists():
    m = json.loads(p.read_text(encoding='utf-8'))
    m['build_at'] = __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    p.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding='utf-8')
PY

echo "dist/ 已生成："
find dist -type f -exec du -h {} + | sort -k2
