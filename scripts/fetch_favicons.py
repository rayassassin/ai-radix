#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抓取工具官网的 Favicon，落地成本地图标，供 tools.html 卡片使用。

为什么不用 `https://{域名}/favicon.ico` 直接挂到页面上：
  大量站点（尤其 SPA）对该路径返回的是 index.html 而非图片，
  浏览器 <img> 里就是一个碎图标。所以必须下载 + 校验文件头。

抓取优先级（前一级失败才降级）：
  1. 官网首页 <link rel="...icon..."> 声明的图标（最准，含 apple-touch-icon）
  2. /favicon.ico
  3. /apple-touch-icon.png · /apple-touch-icon-precomposed.png · /favicon.png
  4. DuckDuckGo 图标镜像（缓存来源仍是官网，官网拒连时兜底）
  全部落空 → 不产出文件，前端回落首字母图标。

产出：
  assets/icons/<hash>.png|svg   统一 64x64 PNG（透明底、等比居中）
  data/favicons.json            {tool_id: 文件名}
  data/favicons_meta.json       逐个来源与失败原因，便于排查

用法:
  python3 scripts/fetch_favicons.py                # 全量抓取
  python3 scripts/fetch_favicons.py --limit 20     # 只跑前 20 个（调试）
  python3 scripts/fetch_favicons.py --only chatgpt kimi
  python3 scripts/fetch_favicons.py --workers 12 --force
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ICON_DIR = ROOT / "assets" / "icons"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,image/avif,image/webp,image/*,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
TIMEOUT = 7
SIZE = 64                 # 存储尺寸，页面显示 22px，2x/3x 屏不糊
MIN_ACCEPT = 16           # 小于此尺寸的图放大必糊，宁可回落首字母
MAX_BYTES = 600 * 1024    # 单张图标上限，防把大图拉下来

# 图片文件头 → 格式名。用来识别「返回 200 但其实是 HTML」的坑
MAGIC = [
    (b"\x00\x00\x01\x00", "ico"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"\xff\xd8\xff", "jpg"),
    (b"BM", "bmp"),
    (b"RIFF", "webp"),
]


def sniff(data: bytes) -> str | None:
    """按文件头判断真实格式，识别不出来就当无效（HTML/JSON/错误页都走这里）。"""
    for magic, fmt in MAGIC:
        if data.startswith(magic):
            if fmt == "webp" and data[8:12] != b"WEBP":
                continue
            return fmt
    head = data[:512].lstrip().lower()
    if head.startswith(b"<?xml") or head.startswith(b"<svg") or b"<svg" in head[:300]:
        return "svg"
    return None


def icon_name(tool_id: str) -> str:
    """文件名用 id 的哈希，规避中文/大写/超长 id 带来的编码问题。"""
    return hashlib.md5(tool_id.encode("utf-8")).hexdigest()[:10]


def fetch(url: str, insecure: bool = False) -> bytes | None:
    """下载并做体积/类型闸门，非图片内容尽早丢弃。"""
    try:
        with requests.get(url, headers=HEADERS, timeout=TIMEOUT, verify=not insecure,
                          allow_redirects=True, stream=True) as r:
            if r.status_code != 200:
                return None
            ctype = (r.headers.get("content-type") or "").lower()
            # 明确是网页的，连下载都省了
            if ctype.startswith("text/html") and "/favicon" not in url and not url.endswith(".ico"):
                return None
            buf = bytearray()
            for chunk in r.iter_content(8192):
                buf.extend(chunk)
                if len(buf) > MAX_BYTES:
                    return None
            return bytes(buf) if buf else None
    except requests.exceptions.SSLError:
        # 部分站点证书链不全（如自签中间证书），图标属于低风险静态资源，降级重试一次
        return None if insecure else fetch(url, insecure=True)
    except Exception:
        return None


LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
REL_RE = re.compile(r"""rel\s*=\s*["']([^"']+)["']""", re.I)
SIZE_RE = re.compile(r"""sizes\s*=\s*["']([^"']+)["']""", re.I)


def declared_icons(page_url: str) -> list[str]:
    """解析首页声明的图标地址，按声明的 sizes 从大到小排，没有 sizes 的靠后。"""
    try:
        r = requests.get(page_url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code != 200:
            return []
        html = r.text[:400000]
    except Exception:
        return []

    found: list[tuple[int, str]] = []
    for tag in LINK_RE.findall(html):
        rel = (REL_RE.search(tag) or [None, ""])[1].lower()
        if "icon" not in rel:
            continue
        href = HREF_RE.search(tag)
        if not href:
            continue
        # 相对路径按重定向后的真实地址补全
        url = urljoin(r.url, href.group(1).strip())
        if url.startswith("data:"):
            continue
        best = 0
        sizes = SIZE_RE.search(tag)
        if sizes:
            for part in sizes.group(1).split():
                m = re.match(r"(\d+)x(\d+)", part.strip(), re.I)
                if m:
                    best = max(best, int(m.group(1)))
        if "apple-touch-icon" in rel:
            best = max(best, 180)
        found.append((best, url))
    # 去重但保持顺序
    seen, out = set(), []
    for _, u in sorted(found, key=lambda x: -x[0]):
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def tone_of(im: Image.Image) -> str:
    """
    判断图标是否需要深色背板。

    只认「白笔画 + 透明底」这一种情况（grok 是纯白笔画，放白卡片上直接隐形）。
    白底黑图案的图标（chatgpt 的白圆底）不需要换背板——白色边在白卡片上本来就看不见，
    换成深色反而多出一个白圆，更难看。两者的区别在于不透明面积占比：
      · 白笔画透明底 → 主体亮，但不透明像素少
      · 白底深图案   → 主体亮，且几乎铺满
    """
    px = im.convert("RGBA").resize((40, 40), Image.LANCZOS).getdata()
    total = len(px)
    opaque = bright = 0
    for r, g, b, a in px:
        if a < 24:                       # 近透明像素不计
            continue
        opaque += 1
        if 0.299 * r + 0.587 * g + 0.114 * b >= 200:
            bright += 1
    if opaque == 0:
        return "normal"
    bright_ratio = bright / opaque
    opaque_ratio = opaque / total
    return "light" if bright_ratio >= 0.85 and opaque_ratio < 0.62 else "normal"


def to_png(raw: bytes, fmt: str) -> tuple[bytes, str] | None:
    """统一成 SIZE×SIZE 透明底 PNG，同时给出明暗档。svg 由上层单独处理。"""
    if fmt == "svg":
        return None
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except Exception:
        return None
    if min(im.size) < MIN_ACCEPT:
        return None

    im = im.convert("RGBA")
    # 纯色/全透明图（占位符、纯白方块）没有信息量，判定无效
    colors = im.getcolors(maxcolors=8)
    if colors and len(colors) == 1:
        return None
    if im.getextrema()[3][1] == 0:
        return None

    tone = tone_of(im)
    w, h = im.size
    scale = SIZE / max(w, h)
    im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    canvas.paste(im, ((SIZE - im.width) // 2, (SIZE - im.height) // 2), im)
    out = io.BytesIO()
    canvas.save(out, "PNG", optimize=True)
    return out.getvalue(), tone


def svg_tone(raw: bytes) -> str:
    """
    svg 没法用 PIL 采样，只能看源码里的填充色粗判（判不出就当 normal）。
    只有「纯白笔画、再无其它颜色」才认为需要深背板；
    白底 + 彩色图案的（dify 是白圆底 + 蓝字母）在白卡片上本来就正常。
    仅用于决定背板深浅，猜错也只是观感问题，不影响功能。
    """
    s = raw.decode("utf-8", "ignore").lower()
    fills = re.findall(r'(?:fill|stroke)\s*[:=]\s*["\']?([^"\';>]+)', s)
    colors = {c.strip() for c in fills}
    colors.discard("none")
    colors.discard("currentcolor")
    colors.discard("transparent")
    if not colors:
        return "normal"
    white = {c for c in colors if c in ("#fff", "#ffffff", "white")}
    others = colors - white
    return "light" if white and not others else "normal"


def grab(tool: dict) -> dict:
    """单个工具的多路探测。返回 {id, file, src, fmt, note}。"""
    tid = tool["id"]
    page = tool["url"]
    host = urlparse(page).netloc
    if not host:
        return {"id": tid, "file": None, "note": "url 无 host"}

    candidates: list[str] = []
    candidates += declared_icons(page)
    base = f"https://{host}"
    candidates += [
        f"{base}/favicon.ico",
        f"{base}/apple-touch-icon.png",
        f"{base}/apple-touch-icon-precomposed.png",
        f"{base}/favicon.png",
    ]

    tried = 0
    for url in candidates:
        tried += 1
        raw = fetch(url) or fetch(url)          # 并发下偶发超时，同一路再试一次
        if not raw:
            continue
        fmt = sniff(raw)
        if not fmt:
            continue
        if fmt == "svg":
            return {"id": tid, "file": f"{icon_name(tid)}.svg", "src": url,
                    "fmt": "svg", "tone": svg_tone(raw), "note": f"第 {tried} 路 svg",
                    "blob": raw}
        got = to_png(raw, fmt)
        if got:
            png, tone = got
            return {"id": tid, "file": f"{icon_name(tid)}.png", "src": url,
                    "fmt": fmt, "tone": tone, "note": f"第 {tried} 路 {fmt}", "blob": png}

    # 官网全拒（Cloudflare 403 / 反爬脚本 / 域名证书异常）时走镜像。
    # 两家镜像缓存的源都是官网 favicon；只认 200，404 时返回的是默认地球占位图，必须丢弃。
    for mirror in (f"https://icons.duckduckgo.com/ip3/{host}.ico",
                   f"https://www.google.com/s2/favicons?domain={host}&sz=64"):
        raw = fetch(mirror)
        if not raw:
            continue
        fmt = sniff(raw)
        if not fmt:
            continue
        got = to_png(raw, fmt)
        if got:
            png, tone = got
            kind = "ddg" if "duckduckgo" in mirror else "google"
            return {"id": tid, "file": f"{icon_name(tid)}.png", "src": f"{kind}-mirror",
                    "fmt": fmt, "tone": tone, "note": f"{kind} 镜像兜底", "blob": png}

    return {"id": tid, "file": None, "note": f"官网 {tried} 路 + 双镜像均无可用图标"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个（调试用）")
    ap.add_argument("--only", nargs="*", default=None, help="只处理指定 id")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--force", action="store_true", help="已存在也重抓")
    args = ap.parse_args()

    payload = json.loads((DATA / "tools.json").read_text(encoding="utf-8"))
    tools = payload["tools"] if isinstance(payload, dict) else payload

    if args.only:
        tools = [t for t in tools if t["id"] in set(args.only)]
    if args.limit:
        tools = tools[: args.limit]

    ICON_DIR.mkdir(parents=True, exist_ok=True)

    # 增量：已有文件的直接复用，除非 --force
    prev: dict[str, dict] = {}
    meta_path = DATA / "favicons_meta.json"
    if not args.force and meta_path.exists():
        try:
            old = json.loads(meta_path.read_text(encoding="utf-8"))
            prev = {k: v for k, v in old.get("items", {}).items() if v.get("file")}
        except Exception:
            prev = {}

    todo, reused = [], 0
    for t in tools:
        f = prev.get(t["id"], {}).get("file")
        if f and (ICON_DIR / f).exists():
            reused += 1
            continue
        todo.append(t)

    print(f"共 {len(tools)} 个工具｜复用 {reused}｜待抓 {len(todo)}｜并发 {args.workers}")
    if not todo:
        return summarize(tools, {k: {"f": v["file"], "t": v.get("tone", "normal")}
                                 for k, v in prev.items()}, ICON_DIR, DATA)

    results: dict[str, dict] = {}
    for tid, v in prev.items():
        if (ICON_DIR / v["file"]).exists():
            results[tid] = {**v, "id": tid, "note": "复用"}

    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(grab, t): t for t in todo}
        for fut in as_completed(futs):
            t = futs[fut]
            try:
                r = fut.result()
            except Exception as e:                     # 单点异常不拖垮整批
                r = {"id": t["id"], "file": None, "note": f"异常 {type(e).__name__}"}
            blob = r.pop("blob", None)
            if blob and r["file"]:
                (ICON_DIR / r["file"]).write_bytes(blob)
            results[t["id"]] = r
            done += 1
            mark = "✓" if r.get("file") else "·"
            print(f"[{done}/{len(todo)}] {mark} {t['id']:<24} {r.get('note','')}", flush=True)

    all_ids = [t["id"] for t in json.loads((DATA / "tools.json").read_text(encoding="utf-8"))["tools"]]

    # 以已有映射为基底再叠加本次结果：--only/--limit 只跑部分工具时，
    # 不能把其它工具的图标记录一起清掉。本次跑完仍失败的才删。
    mapping: dict[str, dict] = {}
    fmap_path = DATA / "favicons.json"
    if fmap_path.exists():
        try:
            old_map = json.loads(fmap_path.read_text(encoding="utf-8"))
            mapping = {i: old_map[i] for i in all_ids if i in old_map}
        except Exception:
            mapping = {}
    for tid, r in results.items():
        if r.get("file"):
            # 值带 tone：前端据此给白色图标换深色背板，否则白 logo 在浅色卡片上看不见
            mapping[tid] = {"f": r["file"], "t": r.get("tone") or "normal"}
        else:
            mapping.pop(tid, None)

    fmap_path.write_text(json.dumps(
        {i: mapping[i] for i in all_ids if i in mapping},
        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    # 排查用的逐条来源记录，同样以 prev 为基底合并，别被局部运行清空
    meta_items = {k: v for k, v in prev.items()}
    meta_items.update({k: v for k, v in results.items()})
    (meta_path).write_text(json.dumps({
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "size": SIZE,
        "total": len(all_ids),
        "ok": len(mapping),
        "items": {i: meta_items[i] for i in all_ids if i in meta_items},
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    return summarize([{"id": i} for i in all_ids], mapping, ICON_DIR, DATA)


def summarize(tools, mapping, icon_dir: Path, data_dir: Path) -> int:
    total = len(tools)
    ok = len(mapping)
    files = [v["f"] if isinstance(v, dict) else v for v in mapping.values()]
    size = sum((icon_dir / f).stat().st_size for f in files if (icon_dir / f).exists())
    light = sum(1 for v in mapping.values() if isinstance(v, dict) and v.get("t") == "light")
    print("\n" + "─" * 56)
    print(f"命中 {ok}/{total}（{ok / total * 100:.1f}%），回落首字母 {total - ok} 个")
    print(f"图标文件 {len(files)} 个，合计 {size / 1024:.0f} KB（均 {size / max(len(files), 1) / 1024:.1f} KB）")
    print(f"其中白色系图标 {light} 个（前端自动换深色背板）")
    print(f"映射表 {data_dir / 'favicons.json'}")
    print("─" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
