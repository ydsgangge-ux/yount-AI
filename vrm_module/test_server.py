"""
Desktop Pet 测试服务

在浏览器中预览桌面萌宠效果。

使用方法：
  python vrm_module/test_server.py

然后在浏览器打开显示的地址，选择一个页面预览：
  - live2d_pet.html    → Live2D 桌面萌宠（默认）
  - vrm_viewer.html    → VRM 3D 模型
  - lottie_pet.html    → Lottie 动画萌宠

注意：不要直接双击打开 HTML 文件，
      浏览器会因安全策略阻止模块加载，必须通过此 HTTP 服务访问。
"""

import http.server
import webbrowser
import os
import sys


# ── 路径 ──
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if not os.path.isdir(STATIC_DIR):
    print(f"[错误] static 目录不存在: {STATIC_DIR}")
    sys.exit(1)


def make_index():
    """列出 static/ 下所有可用的 HTML 测试页"""
    html_files = []
    for f in sorted(os.listdir(STATIC_DIR)):
        if f.endswith(".html"):
            html_files.append(f)

    links = "\n".join(
        f'    <li><a href="{f}">{f}</a></li>' for f in html_files
    )
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8"/>
<title>Desktop Pet 测试导航</title>
<style>
  body {{
    font-family: "Microsoft YaHei", sans-serif;
    background: #0d1117; color: #c9d1d9;
    padding: 40px; max-width: 600px; margin: auto;
  }}
  h1 {{ color: #58a6ff; font-size: 22px; }}
  ul {{ list-style: none; padding: 0; }}
  li {{ margin: 10px 0; }}
  a {{
    display: block; padding: 12px 16px;
    background: #161b22; border: 1px solid #30363d;
    border-radius: 8px; color: #58a6ff;
    text-decoration: none; font-size: 15px;
  }}
  a:hover {{ background: #21262d; border-color: #58a6ff; }}
</style>
</head>
<body>
<h1>Desktop Pet 测试服务</h1>
<p>选择一个页面预览：</p>
<ul>
{links}
</ul>
<hr/>
<p><small>按 Ctrl+C 停止服务</small></p>
</body>
</html>"""


# ── 自定义 Handler：导航 + 静态文件 ──
class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(make_index().encode("utf-8"))
            return
        return super().do_GET()

    def log_message(self, fmt, *args):
        print(f"  [{self.log_date_time_string()}] {args[0]} {args[1]}", flush=True)


# ── 自动找可用端口 ──
PORT = 8899
httpd = None
for attempt in range(10):
    try:
        httpd = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
        break
    except OSError:
        PORT += 1

if httpd is None:
    print("[错误] 无法找到可用端口，请检查网络配置后重试")
    input("按回车退出…")
    sys.exit(1)


# ── 启动 ──
os.chdir(STATIC_DIR)

default_page = "live2d_pet.html"
url = f"http://localhost:{PORT}/{default_page}"
nav_url = f"http://localhost:{PORT}/"

print("=" * 55, flush=True)
print("  Desktop Pet 测试服务已启动", flush=True)
print("=" * 55, flush=True)
print("", flush=True)
print(f"  萌宠预览:   {url}", flush=True)
print(f"  导航页:     {nav_url}", flush=True)
print("", flush=True)
print(f"  可用页面（共 {len([f for f in os.listdir('.') if f.endswith('.html')])} 个）：", flush=True)
for f in sorted(os.listdir(".")):
    if f.endswith(".html"):
        print(f"    - {f}", flush=True)
print("", flush=True)
print("  提示：不要直接双击打开 HTML 文件", flush=True)
print("        必须通过此 HTTP 服务访问，否则模型无法加载", flush=True)
print("", flush=True)
print("  按 Ctrl+C 停止服务", flush=True)
print("", flush=True)

try:
    webbrowser.open(url)
except Exception:
    pass

try:
    httpd.serve_forever()
except KeyboardInterrupt:
    print("\n[服务已停止]")
    httpd.server_close()