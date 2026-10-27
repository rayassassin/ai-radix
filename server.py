#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI · Radix · 本地预览服务

为什么需要它：浏览器直接双击 file:// 打开会因 CORS 策略拿不到 data/*.json，
所以必须走一个本地 HTTP 服务。零依赖，仅标准库。

用法:
  python3 server.py              # 默认 http://127.0.0.1:8899
  python3 server.py -p 9000      # 指定端口
  python3 server.py --no-open    # 不自动开浏览器
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import socket
import socketserver
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"


class Handler(http.server.SimpleHTTPRequestHandler):
    """静态服务 + 根路径跳转 + 禁用缓存（方便边改边看）。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        # 开发场景：永远拿最新数据，避免改了脚本页面不更新
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def do_GET(self):
        # 旧地址兼容：以前页面在 /web/ 下，现在提到根目录
        if self.path.startswith("/web/"):
            self.send_response(301)
            self.send_header("Location", "/" + self.path[5:])
            self.end_headers()
            return
        super().do_GET()

    def log_message(self, fmt, *args):
        # 静音常规访问日志，只报错误，别刷屏
        if args and str(args[0]).startswith(("4", "5")):
            sys.stderr.write(f"[http] {self.address_string()} {fmt % args}\n")


class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def pick_port(preferred: int) -> int:
    """端口被占用时自动往上找，避免每次手动改。"""
    for p in range(preferred, preferred + 40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError(f"{preferred}–{preferred + 40} 端口段均被占用")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--port", type=int, default=8899)
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    if not INDEX.exists():
        print(f"缺少前端文件：{INDEX}")
        return 1

    models = ROOT / "data" / "models.json"
    if not models.exists():
        print("未找到 data/models.json，先执行抓取：")
        print("  python3 scripts/fetch_models.py")
        return 1
    try:
        n = len(json.loads(models.read_text(encoding="utf-8")))
    except Exception:
        n = -1

    port = pick_port(args.port)
    url = f"http://{args.host}:{port}/"
    with ThreadedServer((args.host, port), Handler) as httpd:
        print("─" * 52)
        print("  AI · Radix · 大模型全景看板")
        print("─" * 52)
        print(f"  地址   {url}")
        print(f"  数据   {n} 个模型")
        print(f"  根目录 {ROOT}")
        print("  Ctrl+C 停止")
        print("─" * 52, flush=True)
        if not args.no_open:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
