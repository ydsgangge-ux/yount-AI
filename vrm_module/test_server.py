"""
VRM 模型测试服务
在浏览器中预览 VRM 模型效果。

使用方法：
  python vrm_module/test_server.py

然后在浏览器打开显示的地址。
注意：不要直接双击打开 static/vrm_viewer.html，
      浏览器会因安全策略阻止 ES 模块加载，必须通过 HTTP 服务访问。
"""
import http.server
import webbrowser
import os
import sys

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

if not os.path.isdir(STATIC_DIR):
    print(f"[VRM] static 目录不存在: {STATIC_DIR}")
    sys.exit(1)

# 切换到 static 目录
os.chdir(STATIC_DIR)

# 尝试端口 8899，被占用则自动 +1
PORT = 8899
httpd = None
for attempt in range(10):
    try:
        httpd = http.server.HTTPServer(("127.0.0.1", PORT), http.server.SimpleHTTPRequestHandler)
        break
    except OSError:
        print(f"[VRM] 端口 {PORT} 被占用，尝试 {PORT + 1}...")
        PORT += 1

if httpd is None:
    print("[VRM] 无法找到可用端口，请检查网络配置后重试")
    input("按回车退出…")
    sys.exit(1)

url = f"http://localhost:{PORT}/vrm_viewer.html"

print("=" * 55, flush=True)
print("  VRM 模型测试服务已启动", flush=True)
print("=" * 55, flush=True)
print("", flush=True)
print(f"  浏览器打开:  {url}", flush=True)
print("", flush=True)
print("  提示：不要直接双击打开 HTML 文件", flush=True)
print("        必须通过此 HTTP 服务访问，否则模型无法加载", flush=True)
print("", flush=True)
print("  按 Ctrl+C 停止服务", flush=True)
print("", flush=True)

# 自动打开浏览器
try:
    webbrowser.open(url)
except Exception:
    pass

try:
    httpd.serve_forever()
except KeyboardInterrupt:
    print("\n[VRM] 服务已停止")
    httpd.server_close()