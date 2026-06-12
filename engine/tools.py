"""
工具集定义
B 层可以调用的所有工具函数

每个工具都有：
  - 函数实现
  - schema（告诉 LLM 这个工具的作用和参数）
  - 风险等级（low/medium/high）- 高风险操作需要 A 层向用户确认
"""

import os
import sys
import json
import subprocess
import shutil
import glob
import base64
import urllib.request
import urllib.parse
import threading
from pathlib import Path
from engine.db_guard import guarded_connect
from datetime import datetime
from typing import Any, Dict, List, Optional


def _get_app_dir() -> Path:
    """Get project directory (cross-platform)"""
    p = Path(__file__).resolve().parent  # engine/
    app = p.parent  # project root
    if (app / "main.py").exists():
        return app
    return Path.cwd()


def _get_desktop() -> Path:
    """Get user Desktop folder (cross-platform)"""
    import sys
    p = Path.home() / "Desktop"
    if p.exists():
        return p
    # Linux: try xdg-user-dir
    if sys.platform == "linux":
        try:
            result = subprocess.run(
                ["xdg-user-dir", "DESKTOP"],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and result.stdout.strip():
                alt = Path(result.stdout.strip())
                if alt.exists():
                    return alt
        except Exception:
            pass
    return Path.home()


# ═══════════════════════════════════════════════════
# 工具注册表
# ═══════════════════════════════════════════════════

TOOL_REGISTRY: Dict[str, Dict] = {}


def register_tool(name: str, description: str, parameters: dict, risk: str = "low"):
    """装饰器：注册工具到注册表"""
    def decorator(func):
        # required 必须在顶层，不能在 properties 里（DeepSeek/OpenAI 规范）
        required_keys = [k for k, v in parameters.items() if v.get("required", False)]
        clean_props = {
            k: {pk: pv for pk, pv in v.items() if pk != "required"}
            for k, v in parameters.items()
        }
        TOOL_REGISTRY[name] = {
            "function": func,
            "schema": {
                "name": name,
                "description": description,
                "input_schema": {
                    "type": "object",
                    "properties": clean_props,
                    "required": required_keys
                }
            },
            "risk": risk
        }
        return func
    return decorator


# ═══════════════════════════════════════════════════
# 文件系统工具
# ═══════════════════════════════════════════════════

@register_tool(
    name="read_file",
    description="读取本地文件内容。支持文本文件（txt/md/py/json/csv等）",
    parameters={
        "path": {"type": "string", "description": "文件路径（绝对路径或相对路径）", "required": True},
        "encoding": {"type": "string", "description": "编码格式，默认 utf-8"}
    },
    risk="low"
)
def read_file(path: str, encoding: str = "utf-8") -> Dict:
    try:
        path = os.path.expanduser(path)
        with open(path, "r", encoding=encoding, errors="replace") as f:
            content = f.read()
        size = len(content)
        # 超过 50k 字符只返回前 50k
        if size > 50000:
            content = content[:50000] + f"\n\n[文件过大，已截断。总大小: {size} 字符]"
        return {"ok": True, "content": content, "path": path, "size": size}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@register_tool(
    name="search_in_file",
    description=(
        "在指定文件中搜索关键词，返回匹配的行及其上下文。"
        "适用于在已读文件中查找特定人物、事件、段落等细节。"
    ),
    parameters={
        "path": {"type": "string", "description": "文件路径（绝对路径或相对路径）", "required": True},
        "keyword": {"type": "string", "description": "要搜索的关键词", "required": True},
        "encoding": {"type": "string", "description": "编码格式，默认 utf-8"},
        "context_lines": {"type": "integer", "description": "返回匹配行前后各几行上下文，默认 3"}
    },
    risk="low"
)
def search_in_file(path: str, keyword: str, encoding: str = "utf-8",
                   context_lines: int = 3) -> Dict:
    try:
        path = os.path.expanduser(path)
        with open(path, "r", encoding=encoding, errors="replace") as f:
            lines = f.readlines()

        matches = []
        for i, line in enumerate(lines):
            if keyword in line:
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                context = "".join(lines[start:end]).rstrip()
                matches.append({
                    "line_number": i + 1,
                    "line": line.rstrip(),
                    "context": context
                })

        total_chars = sum(len(m["context"]) for m in matches)
        # 截断过长的结果
        if total_chars > 8000:
            for m in matches:
                m["context"] = m["context"][:500]
            matches = matches[:20]

        return {
            "ok": True,
            "path": path,
            "keyword": keyword,
            "total_lines": len(lines),
            "match_count": len(matches),
            "matches": matches
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@register_tool(
    name="write_file",
    description="写入内容到文件。路径不填则默认保存到桌面。支持相对路径和绝对路径",
    parameters={
        "path": {"type": "string",
                 "description": "目标文件路径。可以是文件名（自动保存到桌面）、相对路径或绝对路径",
                 "required": True},
        "content": {"type": "string", "description": "要写入的内容", "required": True},
        "append": {"type": "boolean", "description": "是否追加（而非覆盖），默认 false"}
    },
    risk="medium"
)
def write_file(path: str, content: str, append: bool = False) -> Dict:
    try:
        path = path.strip()
        # 如果只是文件名（没有路径分隔符），自动放到桌面
        if not any(c in path for c in ["/", "\\", ":"]):
            desktop = _get_desktop()
            path = str(desktop / path)
        path = os.path.expanduser(path)
        abs_path = os.path.abspath(path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        mode = "a" if append else "w"
        with open(abs_path, mode, encoding="utf-8") as f:
            f.write(content)
        return {
            "ok": True,
            "path": abs_path,          # 返回绝对路径，让用户知道文件在哪
            "bytes_written": len(content.encode()),
            "tip": f"文件已保存到: {abs_path}"
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@register_tool(
    name="list_directory",
    description="列出目录内容，包括文件和子目录",
    parameters={
        "path": {"type": "string", "description": "目录路径，默认当前目录"},
        "pattern": {"type": "string", "description": "过滤模式，如 *.py、*.txt"}
    },
    risk="low"
)
def list_directory(path: str = ".", pattern: str = "*") -> Dict:
    try:
        path = os.path.expanduser(path)
        # "." should resolve to the project directory, not CWD
        if path in (".", "./"):
            path = str(_get_app_dir())
        entries = []
        for item in sorted(Path(path).glob(pattern)):
            stat = item.stat()
            entries.append({
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            })
        return {"ok": True, "path": str(Path(path).absolute()), "entries": entries}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@register_tool(
    name="search_files",
    description="在目录中搜索包含指定内容的文件（仅搜索一层子目录，最多返回20个结果）",
    parameters={
        "directory": {"type": "string", "description": "搜索目录（默认项目根目录）", "required": False},
        "keyword": {"type": "string", "description": "搜索关键词", "required": True},
        "file_pattern": {"type": "string", "description": "文件类型过滤，如 *.py"}
    },
    risk="low"
)
def search_files(keyword: str, directory: str = ".", file_pattern: str = "*") -> Dict:
    try:
        directory = os.path.expanduser(directory)
        if directory in (".", "./"):
            directory = str(_get_app_dir())
        # Safety: prevent searching system directories
        abs_dir = Path(directory).resolve()
        blocked = {"C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
                    "/usr", "/etc", "/bin", "/System", "/Library"}
        if any(abs_dir.is_relative_to(Path(b)) for b in blocked):
            return {"ok": False, "error": f"不允许搜索系统目录：{directory}"}
        results = []
        max_depth = 3  # limit recursion depth
        for filepath in abs_dir.rglob(file_pattern):
            # depth check
            try:
                rel = filepath.relative_to(abs_dir)
                if len(rel.parts) > max_depth:
                    continue
            except ValueError:
                continue
            if filepath.is_file():
                try:
                    content = filepath.read_text(encoding="utf-8", errors="ignore")
                    if keyword.lower() in content.lower():
                        lines = content.split("\n")
                        matched = [(i+1, l.strip()) for i, l in enumerate(lines)
                                   if keyword.lower() in l.lower()][:3]
                        results.append({
                            "file": str(filepath),
                            "matches": matched
                        })
                        if len(results) >= 20:
                            break
                except Exception:
                    pass
        return {"ok": True, "keyword": keyword, "found": len(results), "results": results[:20]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@register_tool(
    name="delete_file",
    description="删除文件或空目录",
    parameters={
        "path": {"type": "string", "description": "要删除的文件路径", "required": True}
    },
    risk="high"
)
def delete_file(path: str) -> Dict:
    try:
        path = os.path.expanduser(path)
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
        else:
            return {"ok": False, "error": "路径不存在"}
        return {"ok": True, "deleted": path}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@register_tool(
    name="export_guest_photos",
    description="导出游客会话的人脸照片到桌面。可指定会话ID导出单张，不指定则导出全部",
    parameters={
        "session_id": {"type": "string",
                       "description": "要导出的游客会话ID（可选，不填则导出全部有照片的记录）"}
    },
    risk="low"
)
def export_guest_photos(session_id: str = "") -> Dict:
    try:
        import sqlite3
        # 获取数据库路径
        try:
            from desktop.config import DB_FILE
            db_path = DB_FILE
        except Exception:
            db_path = str(Path.home() / "Desktop" / ".agi-desktop" / "memory.db")
            if sys.platform == "win32":
                db_path = str(Path(os.environ.get("APPDATA", str(Path.home())))
                              / "AGI-Desktop" / "memory.db")

        desktop = _get_desktop()
        export_dir = desktop / "AGI游客照片"
        export_dir.mkdir(parents=True, exist_ok=True)

        with guarded_connect(db_path) as conn:
            if session_id:
                rows = conn.execute(
                    "SELECT session_id, started_at, photo_b64 FROM guest_sessions "
                    "WHERE session_id=? AND photo_b64 IS NOT NULL AND photo_b64 != ''",
                    (session_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT session_id, started_at, photo_b64 FROM guest_sessions "
                    "WHERE photo_b64 IS NOT NULL AND photo_b64 != '' "
                    "ORDER BY started_at DESC"
                ).fetchall()

        if not rows:
            return {"ok": False, "error": "没有找到含照片的游客记录"}

        saved = []
        for row in rows:
            sid, started_at, photo_b64 = row
            try:
                img_data = base64.b64decode(photo_b64)
                time_str = started_at.replace(":", "-").replace(".", "-")[:19] if started_at else "unknown"
                filename = f"guest_{sid}_{time_str}.jpg"
                filepath = export_dir / filename
                filepath.write_bytes(img_data)
                saved.append(filename)
            except Exception as e:
                saved.append(f"{sid}: 导出失败({e})")

        return {
            "ok": True,
            "export_dir": str(export_dir),
            "total": len(rows),
            "saved": saved,
            "tip": f"已导出 {len(rows)} 张照片到: {export_dir}"
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════
# 终端命令工具
# ═══════════════════════════════════════════════════

@register_tool(
    name="run_command",
    description="在终端执行 shell 命令。适合：安装包、运行脚本、git操作、文件处理等",
    parameters={
        "command": {"type": "string", "description": "要执行的命令", "required": True},
        "cwd": {"type": "string", "description": "工作目录，默认当前目录"},
        "timeout": {"type": "integer", "description": "超时秒数，默认 30"}
    },
    risk="high"
)
def run_command(command: str, cwd: str = None, timeout: int = 30) -> Dict:
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            cwd=cwd,
            timeout=timeout,
        )
        def _safe_decode(data: bytes) -> str:
            try:
                return data.decode("utf-8", errors="replace")
            except Exception:
                return data.decode("utf-8", errors="replace")

        return {
            "ok": True,
            "returncode": result.returncode,
            "stdout": _safe_decode(result.stdout)[-5000:] if result.stdout else "",
            "stderr": _safe_decode(result.stderr)[-2000:] if result.stderr else "",
            "command": command
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"命令超时（{timeout}秒）"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@register_tool(
    name="run_python",
    description="执行 Python 代码片段，返回输出结果",
    parameters={
        "code": {"type": "string", "description": "Python 代码", "required": True},
        "cwd": {"type": "string", "description": "工作目录"}
    },
    risk="high"
)
def run_python(code: str, cwd: str = None) -> Dict:
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py',
                                         delete=False, encoding='utf-8') as f:
            f.write(code)
        tmp_path = f.name
        # Windows 兼容：优先 python3，回退 python
        python_cmd = "python3" if shutil.which("python3") else "python"
        result = subprocess.run(
            [python_cmd, tmp_path],
            capture_output=True,
            cwd=cwd, timeout=30,
        )
        os.unlink(tmp_path)
        # 手动解码：优先 utf-8，失败则按系统默认编码（Windows GBK）
        def _safe_decode(data: bytes) -> str:
            try:
                return data.decode("utf-8", errors="replace")
            except Exception:
                return data.decode("utf-8", errors="replace")

        success = result.returncode == 0
        return {
            "ok": success,
            "returncode": result.returncode,
            "stdout": _safe_decode(result.stdout)[-5000:] if result.stdout else "",
            "stderr": _safe_decode(result.stderr)[-2000:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return {"ok": False, "error": "脚本执行超时（30秒）"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════
# 网络工具
# ═══════════════════════════════════════════════════

@register_tool(
    name="web_search",
    description="搜索网络信息。优先使用 DuckDuckGo，失败时自动切换到 Bing 搜索",
    parameters={
        "query": {"type": "string", "description": "搜索关键词", "required": True},
        "max_results": {"type": "integer", "description": "最大结果数，默认 5"}
    },
    risk="low"
)
def web_search(query: str, max_results: int = 5) -> Dict:
    """搜索网络，多引擎备用"""

    # ── 方式1：DuckDuckGo Instant Answer API ──
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())

        results = []
        if data.get("AbstractText"):
            results.append({
                "title":   data.get("Heading", "摘要"),
                "snippet": data["AbstractText"][:500],
                "url":     data.get("AbstractURL", "")
            })
        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "title":   topic.get("FirstURL", "").split("/")[-1].replace("_", " "),
                    "snippet": topic["Text"][:300],
                    "url":     topic.get("FirstURL", "")
                })
        if results:
            return {"ok": True, "engine": "DuckDuckGo",
                    "query": query, "results": results[:max_results]}
    except Exception:
        pass   # 静默失败，尝试备用

    # ── 方式2：Bing 搜索（抓取结果页）──────────
    try:
        import re
        encoded = urllib.parse.quote(query)
        url = f"https://www.bing.com/search?q={encoded}&count={max_results}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9"
            }
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        # 提取搜索结果
        results = []
        # 匹配 Bing 结果标题和链接
        titles   = re.findall(r'<h2[^>]*><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html)
        snippets = re.findall(r'<p[^>]*class="[^"]*b_lineclamp[^"]*"[^>]*>(.*?)</p>', html)

        for i, (href, title) in enumerate(titles[:max_results]):
            title_clean   = re.sub(r'<[^>]+>', '', title).strip()
            snippet_clean = re.sub(r'<[^>]+>', '', snippets[i]).strip() if i < len(snippets) else ""
            if title_clean and not href.startswith("javascript"):
                results.append({
                    "title":   title_clean,
                    "snippet": snippet_clean[:300],
                    "url":     href
                })

        if results:
            return {"ok": True, "engine": "Bing",
                    "query": query, "results": results}
        else:
            return {"ok": True, "engine": "Bing", "query": query,
                    "results": [], "note": "未解析到结果，建议用 fetch_url 直接访问"}

    except Exception as e:
        return {"ok": False,
                "error": f"搜索失败（DuckDuckGo 和 Bing 均不可用）: {e}",
                "tip": "建议使用 fetch_url 工具直接访问目标网页"}


@register_tool(
    name="fetch_url",
    description="获取指定 URL 的网页内容（纯文本）。结果直接返回在 content 字段中，不会写入任何文件，请直接使用返回的数据",
    parameters={
        "url": {"type": "string", "description": "目标 URL", "required": True},
        "max_chars": {"type": "integer", "description": "最大字符数，默认 8000"}
    },
    risk="low"
)
def fetch_url(url: str, max_chars: int = 8000) -> Dict:
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; AGI-System/1.0)",
                "Accept": "text/html,application/xhtml+xml"
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            html = raw.decode(charset, errors="replace")

        # 简单去除 HTML 标签
        import re
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        return {
            "ok": True,
            "url": url,
            "content": text[:max_chars],
            "total_length": len(text)
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@register_tool(
    name="read_article",
    description="从新闻/文章 URL 中提取正文内容、标题、作者、发布时间等元信息。比 fetch_url 更智能，能自动去除广告和导航栏，只保留文章正文",
    parameters={
        "url": {"type": "string", "description": "文章 URL", "required": True},
        "max_chars": {"type": "integer", "description": "正文最大字符数，默认 5000"}
    },
    risk="low"
)
def read_article(url: str, max_chars: int = 5000) -> Dict:
    try:
        import sys
        import concurrent.futures
        from newspaper import Article

        def _download_with_timeout(article, timeout=10):
            if sys.platform != "win32":
                import signal
                def _handler(signum, frame):
                    raise TimeoutError("下载超时")
                signal.signal(signal.SIGALRM, _handler)
                signal.alarm(timeout)
                try:
                    article.download()
                    article.parse()
                finally:
                    signal.alarm(0)
            else:
                def _do():
                    article.download()
                    article.parse()
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(_do)
                    future.result(timeout=timeout)

        # 确保 NLTK 分词资源可用（首次使用时自动下载）
        try:
            import nltk
            nltk.data.find('tokenizers/punkt_tab')
        except (ImportError, LookupError):
            try:
                import nltk
                nltk.download('punkt_tab', quiet=True)
                nltk.download('punkt', quiet=True)
            except Exception:
                pass

        article = Article(url, language="zh")
        try:
            _download_with_timeout(article, timeout=10)
        except (TimeoutError, concurrent.futures.TimeoutError):
            return {"ok": False, "error": "页面下载超时（10秒）"}

        try:
            article.nlp()
        except Exception:
            pass  # NLP 失败不影响正文提取

        result = {
            "ok": True,
            "url": url,
            "title": article.title or "",
            "authors": article.authors or [],
            "publish_date": str(article.publish_date) if article.publish_date else "",
            "top_image": article.top_image or "",
            "keywords": article.keywords or [],
            "summary": article.summary or "",
            "text": (article.text or "")[:max_chars],
            "text_length": len(article.text or ""),
        }
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════
# 系统控制工具（需要安装额外依赖）
# ═══════════════════════════════════════════════════

@register_tool(
    name="screenshot",
    description="截取当前屏幕截图，返回图片的 base64 编码。需要 pyautogui",
    parameters={
        "region": {"type": "string", "description": "截图区域 'x,y,w,h'，不填则全屏"}
    },
    risk="low"
)
def screenshot(region: str = None) -> Dict:
    try:
        import pyautogui
        from PIL import Image
        import io

        if region:
            x, y, w, h = map(int, region.split(","))
            img = pyautogui.screenshot(region=(x, y, w, h))
        else:
            img = pyautogui.screenshot()

        # 压缩后转 base64
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return {"ok": True, "image_base64": b64,
                "size": f"{img.width}x{img.height}"}
    except ImportError:
        return {"ok": False, "error": "需要安装：pip install pyautogui pillow"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@register_tool(
    name="mouse_click",
    description="点击屏幕指定位置。需要 pyautogui",
    parameters={
        "x": {"type": "integer", "description": "X 坐标", "required": True},
        "y": {"type": "integer", "description": "Y 坐标", "required": True},
        "button": {"type": "string", "description": "left/right/middle，默认 left"},
        "clicks": {"type": "integer", "description": "点击次数，默认 1"}
    },
    risk="high"
)
def mouse_click(x: int, y: int, button: str = "left", clicks: int = 1) -> Dict:
    try:
        import pyautogui
        pyautogui.click(x, y, button=button, clicks=clicks)
        return {"ok": True, "action": f"点击 ({x},{y}) {button} {clicks}次"}
    except ImportError:
        return {"ok": False, "error": "需要安装：pip install pyautogui"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@register_tool(
    name="keyboard_type",
    description="模拟键盘输入文字或按键。需要 pyautogui",
    parameters={
        "text": {"type": "string", "description": "要输入的文字"},
        "hotkey": {"type": "string", "description": "组合键，如 'ctrl,c' 或 'alt,tab'"}
    },
    risk="high"
)
def keyboard_type(text: str = None, hotkey: str = None) -> Dict:
    try:
        import pyautogui
        import time
        if hotkey:
            keys = [k.strip() for k in hotkey.split(",")]
            pyautogui.hotkey(*keys)
            return {"ok": True, "action": f"按键 {hotkey}"}
        elif text:
            pyautogui.typewrite(text, interval=0.03)
            return {"ok": True, "action": f"输入文字 ({len(text)} 字符)"}
        else:
            return {"ok": False, "error": "必须提供 text 或 hotkey"}
    except ImportError:
        return {"ok": False, "error": "需要安装：pip install pyautogui"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@register_tool(
    name="open_application",
    description="打开应用程序或文件",
    parameters={
        "target": {"type": "string", "description": "应用名称或文件路径", "required": True}
    },
    risk="medium"
)
def open_application(target: str) -> Dict:
    try:
        import platform
        system = platform.system()
        if system == "Darwin":      # macOS
            subprocess.Popen(["open", target])
        elif system == "Windows":
            os.startfile(target)
        else:                        # Linux
            subprocess.Popen(["xdg-open", target])
        return {"ok": True, "opened": target}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@register_tool(
    name="browser_action",
    description="控制浏览器：打开URL、获取页面内容、点击元素。需要 playwright",
    parameters={
        "action": {"type": "string",
                   "description": "操作类型：open_url / get_text / click_text / fill_input / get_screenshot",
                   "required": True},
        "url": {"type": "string", "description": "目标 URL（open_url 时必填）"},
        "selector": {"type": "string", "description": "CSS 选择器或文字内容"},
        "value": {"type": "string", "description": "填写的内容（fill_input 时）"}
    },
    risk="medium"
)
def browser_action(action: str, url: str = None,
                   selector: str = None, value: str = None) -> Dict:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            if action == "open_url" and url:
                page.goto(url, timeout=15000)
                title = page.title()
                browser.close()
                return {"ok": True, "title": title, "url": url}

            elif action == "get_text" and url:
                page.goto(url, timeout=15000)
                text = page.inner_text("body")[:8000]
                browser.close()
                return {"ok": True, "text": text}

            elif action == "click_text" and selector:
                page.get_by_text(selector).first.click()
                page.wait_for_load_state()
                browser.close()
                return {"ok": True, "clicked": selector}

            elif action == "fill_input" and selector and value:
                page.fill(selector, value)
                browser.close()
                return {"ok": True, "filled": selector}

            elif action == "get_screenshot":
                img_bytes = page.screenshot()
                b64 = base64.b64encode(img_bytes).decode()
                browser.close()
                return {"ok": True, "image_base64": b64}

            browser.close()
            return {"ok": False, "error": f"未知操作: {action}"}

    except ImportError:
        return {"ok": False,
                "error": "需要安装：pip install playwright && playwright install chromium"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════
# 系统信息工具
# ═══════════════════════════════════════════════════

@register_tool(
    name="get_system_info",
    description="获取系统信息：OS、磁盘、内存、运行进程等",
    parameters={
        "info_type": {"type": "string",
                      "description": "os / disk / memory / processes / all，默认 all"}
    },
    risk="low"
)
def get_system_info(info_type: str = "all") -> Dict:
    import platform
    result = {}
    try:
        if info_type in ("os", "all"):
            result["os"] = {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version()
            }
        if info_type in ("disk", "all"):
            usage = shutil.disk_usage(".")
            result["disk"] = {
                "total_gb": round(usage.total / 1e9, 1),
                "used_gb":  round(usage.used  / 1e9, 1),
                "free_gb":  round(usage.free  / 1e9, 1)
            }
        if info_type in ("processes", "all"):
            ps = subprocess.run(["ps", "aux", "--no-header"],
                                capture_output=True, text=True, timeout=5)
            procs = [l.split()[10] for l in ps.stdout.strip().split("\n")
                     if l.strip()][:20]
            result["processes"] = procs
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@register_tool(
    name="read_clipboard",
    description="读取剪贴板内容",
    parameters={},
    risk="low"
)
def read_clipboard() -> Dict:
    try:
        result = subprocess.run(
            ["pbpaste"] if os.uname().sysname == "Darwin" else ["xclip", "-o"],
            capture_output=True, text=True, timeout=5
        )
        return {"ok": True, "content": result.stdout}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@register_tool(
    name="write_clipboard",
    description="写入内容到剪贴板",
    parameters={
        "content": {"type": "string", "description": "要写入剪贴板的内容", "required": True}
    },
    risk="low"
)
def write_clipboard(content: str) -> Dict:
    try:
        import platform
        if platform.system() == "Darwin":
            proc = subprocess.run(["pbcopy"], input=content.encode(), timeout=5)
        else:
            proc = subprocess.run(["xclip", "-selection", "clipboard"],
                                  input=content.encode(), timeout=5)
        return {"ok": True, "written": len(content)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════
# 金融数据工具
# ═══════════════════════════════════════════════════

@register_tool(
    name="get_stock_info",
    description="获取股票/基金实时行情和基本信息，支持 A股、美股、港股等全球市场",
    parameters={
        "symbol": {"type": "string", "description": "股票代码，如 600519.SS（茅台）、AAPL（苹果）、00700.HK（腾讯）", "required": True},
        "period": {"type": "string", "description": "查询内容类型：info（基本信息）、quote（实时报价）、history（历史K线）", "required": False},
        "range": {"type": "string", "description": "历史K线范围（仅 period=history 时有效）：1d/5d/1mo/3mo/6mo/1y/2y/5y/max，默认 1mo"}
    },
    risk="low"
)
def get_stock_info(symbol: str, period: str = "info", range: str = "1mo") -> Dict:
    try:
        import yfinance as yf

        period = period.lower() if period else "info"
        ticker = yf.Ticker(symbol)

        if period == "quote":
            info = ticker.fast_info
            result = {
                "ok": True,
                "symbol": symbol,
                "market_price": getattr(info, "last_price", None),
                "currency": getattr(info, "currency", ""),
                "previous_close": getattr(info, "previous_close", None),
                "open": getattr(info, "open", None),
                "day_high": getattr(info, "day_high", None),
                "day_low": getattr(info, "day_low", None),
                "volume": getattr(info, "last_volume", None),
            }
            # 过滤 None 值
            result = {k: v for k, v in result.items() if v is not None}

        elif period == "history":
            hist = ticker.history(period=range)
            if hist.empty:
                return {"ok": False, "error": f"未获取到 {symbol} 的历史数据"}
            records = []
            for idx, row in hist.iterrows():
                records.append({
                    "date": idx.strftime("%Y-%m-%d"),
                    "open": round(row.get("Open", 0), 2),
                    "high": round(row.get("High", 0), 2),
                    "low": round(row.get("Low", 0), 2),
                    "close": round(row.get("Close", 0), 2),
                    "volume": int(row.get("Volume", 0)),
                })
            result = {
                "ok": True,
                "symbol": symbol,
                "range": range,
                "count": len(records),
                "records": records,
                "latest": records[-1] if records else None,
            }

        else:
            # 基本信息
            info = ticker.info
            result = {
                "ok": True,
                "symbol": symbol,
                "name": info.get("shortName") or info.get("longName", ""),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "market": info.get("market", ""),
                "currency": info.get("currency", ""),
                "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "previous_close": info.get("previousClose"),
                "open": info.get("regularMarketOpen"),
                "day_high": info.get("dayHigh") or info.get("regularMarketDayHigh"),
                "day_low": info.get("dayLow") or info.get("regularMarketDayLow"),
                "volume": info.get("volume") or info.get("regularMarketVolume"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "dividend_yield": info.get("dividendYield"),
                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                "summary": info.get("longBusinessSummary", "")[:500] if info.get("longBusinessSummary") else "",
            }
            result = {k: v for k, v in result.items() if v is not None}

        return result

    except ImportError:
        return {"ok": False, "error": "需要安装 yfinance：pip install yfinance"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@register_tool(
    name="search_stock",
    description="搜索股票代码，根据关键词模糊匹配股票名称或代码",
    parameters={
        "keyword": {"type": "string", "description": "搜索关键词，如 茅台、苹果、腾讯、TSLA", "required": True},
        "max_results": {"type": "integer", "description": "最大返回数量，默认 5"}
    },
    risk="low"
)
def search_stock(keyword: str, max_results: int = 5) -> Dict:
    try:
        import yfinance as yf

        results = yf.Search(keyword, max_results=max_results)
        quotes = []
        for q in getattr(results, "quotes", [])[:max_results]:
            quotes.append({
                "symbol": q.get("symbol", ""),
                "name": q.get("shortname") or q.get("longname", ""),
                "type": q.get("quoteType", ""),
                "exchange": q.get("exchange", ""),
                "market": q.get("market", ""),
            })
        news = []
        for n in getattr(results, "news", [])[:5]:
            news.append({
                "title": n.get("title", ""),
                "publisher": n.get("publisher", ""),
                "link": n.get("link", ""),
            })

        return {
            "ok": True,
            "keyword": keyword,
            "quotes": quotes,
            "news": news,
            "tip": f"找到 {len(quotes)} 个结果，使用 get_stock_info 获取详细信息"
        }

    except ImportError:
        return {"ok": False, "error": "需要安装 yfinance：pip install yfinance"}
    except Exception as e:
        # 旧版本 yfinance 没有 Search，给出手动提示
        return {
            "ok": False,
            "error": str(e),
            "tip": "请确保 yfinance 版本 >= 0.2.31：pip install --upgrade yfinance"
        }


# ═══════════════════════════════════════════════════
# 新闻资讯工具
# ═══════════════════════════════════════════════════

def _get_newsapi_key(api_key: str = "") -> str:
    """获取 NewsAPI key，优先用传入的，回退到系统配置和环境变量"""
    if api_key:
        return api_key
    try:
        from desktop.config import load_config
        cfg = load_config()
        key = cfg.get("newsapi_key", "")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("NEWSAPI_KEY", "")


@register_tool(
    name="get_news",
    description="获取最新新闻资讯，支持按关键词、来源、国家、分类搜索。需要 NewsAPI Key（在设置中配置 newsapi_key）",
    parameters={
        "keyword":     {"type": "string", "description": "搜索关键词，如 AI、苹果、科技"},
        "category":    {"type": "string", "description": "新闻分类：general/business/entertainment/health/science/sports/technology"},
        "country":     {"type": "string", "description": "国家代码，如 us（美国）、jp（日本），默认 us（免费版不支持 cn）"},
        "page_size":   {"type": "integer", "description": "返回条数，默认 5，最大 100"},
        "api_key":     {"type": "string", "description": "NewsAPI Key（可选，不填则用系统配置）"}
    },
    risk="low"
)
def get_news(keyword: str = "", category: str = "", country: str = "us",
             page_size: int = 5, api_key: str = "") -> Dict:
    try:
        from newsapi import NewsApiClient

        key = _get_newsapi_key(api_key)
        if not key:
            return {
                "ok": False,
                "error": "未配置 NewsAPI Key",
                "tip": "请在设置中填写 newsapi_key，或设置环境变量 NEWSAPI_KEY。"
                      "免费申请：https://newsapi.org/register"
            }

        client = NewsApiClient(api_key=key)

        if keyword:
            # get_everything 按关键词全文搜索，不支持 category 参数
            articles = client.get_everything(
                q=keyword,
                language="zh" if country in ("cn", "tw", "hk") else "en",
                page_size=min(page_size, 100),
                sort_by="publishedAt"
            )
        else:
            # get_top_headlines 支持按 category + country 获取头条
            articles = client.get_top_headlines(
                category=category or None,
                country=country,
                page_size=min(page_size, 100)
            )

        if articles.get("status") != "ok":
            return {"ok": False, "error": articles.get("message", "请求失败")}

        total = articles.get("totalResults", 0)
        items = []
        for a in articles.get("articles", [])[:page_size]:
            items.append({
                "title":       a.get("title", ""),
                "source":      a.get("source", {}).get("name", ""),
                "author":      a.get("author", ""),
                "published_at": a.get("publishedAt", ""),
                "description": (a.get("description", "") or "")[:200],
                "url":         a.get("url", ""),
                "url_to_image": a.get("urlToImage", ""),
            })

        return {
            "ok": True,
            "total": total,
            "count": len(items),
            "keyword": keyword,
            "category": category,
            "country": country,
            "articles": items,
        }

    except ImportError:
        return {"ok": False, "error": "需要安装 newsapi-python：pip install newsapi-python"}
    except Exception as e:
        err_msg = str(e)
        # 常见错误友好提示
        if "apiKey" in err_msg or "API key" in err_msg:
            return {"ok": False, "error": "NewsAPI Key 无效或未配置",
                    "tip": "请在设置中检查 newsapi_key。免费申请：https://newsapi.org/register"}
        return {"ok": False, "error": err_msg}


@register_tool(
    name="get_news_sources",
    description="获取 NewsAPI 支持的新闻来源列表，可按国家、语言、分类过滤",
    parameters={
        "country":   {"type": "string", "description": "国家代码，如 cn、us"},
        "language":  {"type": "string", "description": "语言代码，如 zh、en"},
        "category":  {"type": "string", "description": "分类：general/business/entertainment/health/science/sports/technology"}
    },
    risk="low"
)
def get_news_sources(country: str = "", language: str = "", category: str = "") -> Dict:
    try:
        from newsapi import NewsApiClient

        key = _get_newsapi_key()
        if not key:
            return {
                "ok": False,
                "error": "未配置 NewsAPI Key",
                "tip": "请在设置中填写 newsapi_key。免费申请：https://newsapi.org/register"
            }

        client = NewsApiClient(api_key=key)

        kwargs = {}
        if country:
            kwargs["country"] = country
        if language:
            kwargs["language"] = language
        if category:
            kwargs["category"] = category

        result = client.get_sources(**kwargs)

        if result.get("status") != "ok":
            return {"ok": False, "error": result.get("message", "请求失败")}

        sources = []
        for s in result.get("sources", [])[:50]:
            sources.append({
                "id":       s.get("id", ""),
                "name":     s.get("name", ""),
                "category": s.get("category", ""),
                "language": s.get("language", ""),
                "country":  s.get("country", ""),
                "url":      s.get("url", ""),
                "description": (s.get("description", "") or "")[:100],
            })

        return {
            "ok": True,
            "total": len(sources),
            "sources": sources,
        }

    except ImportError:
        return {"ok": False, "error": "需要安装 newsapi-python：pip install newsapi-python"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════
# 图片生成工具（pollinations.ai，免费无需 API Key）
# ═══════════════════════════════════════════════════

@register_tool(
    name="generate_image",
    description=(
        "在线生成图片（pollinations.ai），质量一般、速度慢（10-30秒）。"
        "仅在 generate_image_comfy 不可用时作为备选。优先使用 generate_image_comfy。"
    ),
    parameters={
        "prompt": {"type": "string", "description": "英文画面描述，如 'a cat sitting on a rainbow, digital art'", "required": True},
        "width": {"type": "integer", "description": "图片宽度（像素），默认 1024"},
        "height": {"type": "integer", "description": "图片高度（像素），默认 1024"},
        "use_simlife_scene": {"type": "boolean", "description": "是否使用 SimLife 当前场景作为背景（拍照/自拍时设为 true），默认 false"},
    },
    risk="low"
)
def generate_image(prompt: str, width: int = 1024, height: int = 1024, use_simlife_scene: bool = False) -> Dict:
    try:
        from engine.image_gen import download_image, get_image_dir
        from pathlib import Path
        from datetime import datetime
        import uuid

        # 如果请求使用 SimLife 场景，尝试获取当前状态并融入 prompt
        if use_simlife_scene:
            try:
                from engine.simlife_client import SimLifeClient
                _sl = SimLifeClient()
                sl_ctx = _sl.format_for_prompt()
                if sl_ctx:
                    prompt = f"{prompt}, based on current life scene context"
            except Exception:
                pass

        filename = f"tool_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
        save_path = str(get_image_dir() / filename)

        image_path = download_image(prompt, width=width, height=height, save_path=save_path)
        if image_path:
            return {
                "ok": True,
                "image_path": image_path,
                "prompt": prompt,
                "size": f"{width}x{height}",
                "message": f"图片已生成并保存到: {image_path}"
            }
        else:
            return {"ok": False, "error": "图片生成或下载失败"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════
# 图片生成工具（ComfyUI 本地后端，高质量 SDXL）
# ═══════════════════════════════════════════════════

_WORKFLOW_JSON = str(Path(__file__).parent.parent / "workflow_api.json")


def _load_comfyui_config() -> dict:
    """从 config.json 读取 ComfyUI 配置，未配置时使用默认值"""
    try:
        from desktop.config import load_config
        cfg = load_config()
    except Exception:
        cfg = {}
    return {
        "url": cfg.get("comfyui_url", "http://127.0.0.1:8188"),
        "output_dir": cfg.get("comfyui_output", ""),
        "style": cfg.get("comfyui_style", ""),
    }


# 风格关键词预设（追加到 prompt 最前面，保证权重最高）
_STYLE_PREFIX = {
    "anime": "pixiv",
    "realistic": "photorealistic, 8k uhd, dslr, soft lighting, high quality",
}

# 风格冲突词表：当 config 设定某风格时，从 prompt 中移除对立风格词
_STYLE_CONFLICTS = {
    "anime": [
        "real", "realistic", "real_photo", "real photo", "photorealistic", "photograph",
        "photo", "dslr", "8k uhd", "camera", "raw photo", "hyperrealistic",
    ],
    "realistic": [
        "anime", "illustration", "pixiv", "manga", "cartoon", "2d", "cel shading",
        "anime style", "ukiyo", "visual novel",
    ],
}


def _clean_style_conflicts(prompt: str, style: str) -> str:
    """移除 prompt 中与当前设定风格冲突的词汇"""
    import re as _re
    conflicts = _STYLE_CONFLICTS.get(style, [])
    removed = []
    for word in conflicts:
        pattern = rf'\b{_re.escape(word)}\b[_\s]?,?\s*'
        new_prompt = _re.sub(pattern, '', prompt, flags=_re.IGNORECASE)
        if new_prompt != prompt:
            removed.append(word)
            prompt = new_prompt
    if removed:
        print(f"[ComfyUI] 已移除与 {style} 风格冲突的词: {', '.join(removed)}")
    return prompt


def _get_style_prefix() -> str:
    """根据 config.json 的 comfyui_style 返回风格前缀"""
    style = _load_comfyui_config()["style"]
    return _STYLE_PREFIX.get(style, "")


def _comfyui_url() -> str:
    return _load_comfyui_config()["url"]


def _comfyui_output_dir() -> str:
    cfg = _load_comfyui_config()
    if cfg["output_dir"]:
        return cfg["output_dir"]
    # 兜底：尝试常见路径
    import sys
    if sys.platform == "win32":
        candidates = [r"D:\ComfyUI_windows_portable\ComfyUI\output",
                       r"C:\ComfyUI_windows_portable\ComfyUI\output"]
    else:
        candidates = [str(Path.home() / "ComfyUI" / "output")]
    for c in candidates:
        if Path(c).is_dir():
            return c
    return candidates[0]


def _parse_comfy_workflow() -> Optional[Dict]:
    """
    加载并解析 workflow_api.json，自动定位关键节点。
    返回 dict: {positive_node_id, negative_node_id, sampler_node_id, seed_node_id, output_node_id, workflow}
    """
    try:
        with open(_WORKFLOW_JSON, "r", encoding="utf-8") as f:
            workflow = json.load(f)
    except Exception as e:
        print(f"[ComfyUI] 无法加载 workflow: {e}")
        return None

    # 自动定位 KSampler 节点
    sampler_id = None
    for nid, node in workflow.items():
        if isinstance(node, dict) and node.get("class_type") in ("KSampler", "KSamplerAdvanced"):
            sampler_id = nid
            break

    if not sampler_id:
        print("[ComfyUI] workflow 中未找到 KSampler 节点")
        return None

    sampler_inputs = workflow[sampler_id].get("inputs", {})
    positive_id = str(sampler_inputs.get("positive", [None])[0])
    negative_id = str(sampler_inputs.get("negative", [None])[0])

    # 找 SaveImage 节点（输出）
    output_id = None
    for nid, node in workflow.items():
        if isinstance(node, dict) and node.get("class_type") == "SaveImage":
            output_id = nid
            break

    return {
        "positive_id": str(positive_id),
        "negative_id": str(negative_id),
        "sampler_id": sampler_id,
        "output_id": output_id,
        "workflow": workflow,
    }


def _check_comfyui_alive() -> bool:
    """检查 ComfyUI 是否在线"""
    try:
        import requests
        resp = requests.get(f"{_comfyui_url()}/system_stats", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def _wait_for_comfyui(prompt_id: str, timeout: int = 120) -> Optional[str]:
    """
    轮询 ComfyUI 等待生成完成。
    返回输出图片的文件名（如 ComfyUI_00001_.png），超时返回 None。
    """
    import requests, time

    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{_comfyui_url()}/history/{prompt_id}", timeout=5)
            if resp.status_code == 200:
                history = resp.json()
                if prompt_id in history:
                    outputs = history[prompt_id].get("outputs", {})
                    for node_id, node_out in outputs.items():
                        if "images" in node_out and node_out["images"]:
                            return node_out["images"][0].get("filename")
        except Exception:
            pass
        time.sleep(2)

    return None


@register_tool(
    name="generate_image_comfy",
    description=(
        "首选图片生成工具。使用本地 ComfyUI 生成图片，"
        "适用于生成自拍、场景分享、各种风格画面。"
        "当用户想看你的样子、环境、周围场景时优先使用此工具。"
        "注意：如果用户要求看风景、场景、环境，不要在 prompt 中添加人物，"
        "同时将 no_human 参数设为 true。"
        "当用户明确点击工具面板画图（对话中包含工具名），系统会自动跳过角色特征注入。"
        "当是你自己要拍照或拍风景时（如'让我看看你''拍张照'），直接生成 prompt 即可，系统会自动注入你的角色特征。"
    ),
    parameters={
        "prompt": {
            "type": "string",
            "description": "英文画面描述，使用逗号分隔的标签/关键词格式。人数用 1girl/1boy/2girls 等，构图用 solo/full body/upper body 等，服装外貌用具体描述如 white_shirt/black_dress/long_hair。示例: '1girl, solo, full body, long_hair, white_shirt, standing, indoors, cafe, warm_lighting'",
            "required": True,
        },
        "negative_prompt": {
            "type": "string",
            "description": "负向提示词（排除内容），不填则使用 workflow 默认值",
            "required": False,
        },
        "no_human": {
            "type": "boolean",
            "description": "是否生成纯风景/静物图（不包含人物）。当用户要求看风景、景色、场景、环境、食物、物品时设为 true，此时不要在 prompt 中添加 1girl/1boy/solo 等人物标签",
            "required": False,
        },
        "width": {
            "type": "integer",
            "description": "图片宽度（像素），如 512/768/1024。不填则自动根据 prompt 推断（人像768/风景1024/默认832）",
            "required": False,
        },
        "height": {
            "type": "integer",
            "description": "图片高度（像素），如 512/768/1024。不填则自动根据 prompt 推断（人像1024/风景768/默认832）",
            "required": False,
        },
    },
    risk="medium",
)
def generate_image_comfy(prompt: str, negative_prompt: str = "", no_human: bool = False,
                         width: int = 0, height: int = 0) -> Dict:
    try:
        import requests
        import random
        import shutil
        from datetime import datetime
        from engine.image_gen import get_image_dir

        # 0.0 判断是否跳过角色特征注入
        # 策略：用户原始消息包含"generate_image_comfy"（点击工具面板）→ 跳过注入
        #       其他情况（系统自主调用、自然对话触发）→ 注入角色特征
        _raw_input = getattr(generate_image_comfy, '_user_raw_input', '') or ''
        no_inject = 'generate_image_comfy' in _raw_input
        # 兼容：LLM 也可能加 [NO_INJECT]，仅当用户消息也匹配时才生效
        if not no_inject and prompt.strip().startswith("[NO_INJECT]"):
            prompt = prompt.strip().replace("[NO_INJECT]", "").strip().lstrip(",").strip()
            # LLM 单方面加的 [NO_INJECT]，用户消息没有工具名，忽略
        if no_inject:
            prompt = prompt.strip().replace("[NO_INJECT]", "").strip().lstrip(",").strip()
            print(f"[ComfyUI] 用户主动指定画图，跳过角色特征注入")
        else:
            print(f"[ComfyUI] 系统自主调用，将注入角色特征")

        # 0.0.1 风格冲突清理（anime ↔ realistic，两个模式都需要）
        _current_style = _load_comfyui_config()["style"]
        if _current_style in _STYLE_CONFLICTS:
            prompt = _clean_style_conflicts(prompt, _current_style)

        if no_inject:
            # 用户指定画图：仅注入风格前缀，跳过所有角色特征注入
            style_prefix = _get_style_prefix()
            if style_prefix:
                prompt = f"{style_prefix}, {prompt}"
                print(f"[ComfyUI] 用户指定模式，仅注入风格前缀: {style_prefix}")
            else:
                print(f"[ComfyUI] 用户指定模式，无风格前缀，使用原始 prompt")
            prompt_lower = prompt.lower()
        else:
            # 0. 注入风格前缀（anime/realistic，权重最高放最前）
            style_prefix = _get_style_prefix()
            if style_prefix:
                prompt = f"{style_prefix}, {prompt}"
                print(f"[ComfyUI] 已注入风格前缀: {style_prefix}")

            # 0.1 判断是否包含人物主体（纯风景/静物时不注入 avatar 和穿着）
            prompt_lower = prompt.lower()
            # no_human 参数优先（工具描述已引导 LLM 拍风景时设为 true）
            if no_human:
                has_person = False
                # 从 prompt 中移除常见人物标签
                import re as _re
                _human_tags_remove = ("1girl", "1boy", "2girls", "2boys", "3girls", "3boys",
                                      "solo", "girl", "boy", "woman", "man",
                                      "selfie", "portrait", "looking at viewer")
                for tag in _human_tags_remove:
                    prompt = _re.sub(rf'\b{_re.escape(tag)}\b\s*,?\s*', '', prompt, flags=_re.IGNORECASE)
                prompt_lower = prompt.lower()
                print(f"[ComfyUI] no_human=true，已清除人物标签")
            else:
                _person_indicators = (
                    # 人称
                    "1girl", "1boy", "2girls", "2boys", "3girls", "3boys",
                    "solo", "duo", "trio",
                    "girl", "boy", "woman", "man", "person", "people",
                    "child", "kid", "teen", "elder", "lady", "gentleman",
                    # 身体部位
                    "hair", "eye", "eyes", "face", "skin", "hand", "hands",
                    "smile", "expression", "lips", "mouth", "body",
                    # 动作/姿态
                    "sitting", "standing", "walking", "lying", "looking",
                    "selfie", "portrait", "upper body", "full body",
                    # 明确无人
                    "no humans",
                )
                has_person = any(tag in prompt_lower for tag in _person_indicators)
                if "no humans" in prompt_lower:
                    has_person = False

            # 0.5 注入角色外貌特征（国籍/发色/眼睛颜色/身材，仅有人物时注入）
            # 从角色卡（CharacterCard）读取结构化字段，而非 personality.json 的自由文本
            if has_person:
                try:
                    from engine.simlife_client import SimLifeClient
                    _sl = SimLifeClient()
                    character = _sl._read_character()
                    if character:
                        basic = character.get("basic", {})
                        parts = []
                        nationality = basic.get("nationality", "").strip()
                        hair = basic.get("hair_color", "").strip()
                        eyes = basic.get("eye_color", "").strip()
                        body = basic.get("body_type", "").strip()
                        if nationality:
                            parts.append(f"{nationality} girl")
                        if hair:
                            parts.append(f"{hair} hair")
                        if eyes:
                            parts.append(f"{eyes} eyes")
                        if body:
                            parts.append(body)
                        if parts:
                            avatar_desc = ", ".join(parts)
                            if avatar_desc.lower() not in prompt_lower:
                                prompt = f"{avatar_desc}, {prompt}"
                                print(f"[ComfyUI] 已注入角色外貌: {avatar_desc}")
                            else:
                                print(f"[ComfyUI] 角色外貌已存在于 prompt 中，跳过注入")
                        else:
                            print(f"[ComfyUI] 角色卡中无外貌字段（nationality/hair_color/eye_color/body_type）")
                    else:
                        # 兜底：从 personality.json 读取 avatar_prompt
                        from desktop.config import PERSONALITY_FILE
                        import json
                        if Path(PERSONALITY_FILE).exists():
                            personality = json.loads(Path(PERSONALITY_FILE).read_text(encoding="utf-8"))
                            avatar = personality.get("avatar_prompt", "").strip()
                            if avatar and avatar.lower() not in prompt_lower:
                                prompt = f"{avatar}, {prompt}"
                                print(f"[ComfyUI] 兜底：已注入 avatar_prompt: {avatar[:60]}...")
                except Exception as e:
                    print(f"[ComfyUI] 注入角色外貌失败: {e}")
            else:
                print(f"[ComfyUI] 检测为风景/静物图，跳过外貌注入")

            # 0.6 穿着由 A层 LLM 自行决定写入 prompt，后端不再注入 SimLife 穿着

            # 0.7 随机姿势/拍摄角度（避免画面呆板，人物和风景各用不同的池）
            _pose_angles_person = [
                "hand on hip", "leaning forward", "arms crossed", "head tilt", "looking away",
                "stretching", "adjusting hair", "hand resting on chin", "turning back",
                "dynamic pose", "looking up", "looking down", "side glance",
                "from side", "from above", "dutch angle", "over shoulder shot",
                "cowboy shot", "headshot", "close-up on face",
            ]
            _pose_angles_scene = [
                "wide angle", "bird eye view", "low angle shot", "aerial view",
                "golden hour lighting", "rule of thirds", "dramatic sky",
                "leading lines", "depth of field", "long shot", "panoramic",
                "vibrant colors", "soft focus", "sunrise", "sunset glow",
            ]
            _pool = _pose_angles_person if has_person else _pose_angles_scene
            _angle_blacklist = ("from above", "from below", "wide angle", "close-up", "low angle")
            _has_angle = any(a in prompt_lower for a in _angle_blacklist)
            if not _has_angle:
                import random
                _chosen = random.sample(_pool, min(2, len(_pool)))
                _angle_str = ", ".join(_chosen)
                prompt = f"{prompt}, {_angle_str}"
                print(f"[ComfyUI] 已追加姿势/角度: {_angle_str}")

            # 0.6 注入旅行目的地信息（旅行博主模式下，添加当前所在城市的场景描述）
            try:
                from engine.simlife_client import SimLifeClient
                _sl = SimLifeClient()
                character = _sl._read_character()
                if character:
                    ws = character.get("basic", {}).get("work_style", "")
                    if ws == "travel":
                        from datetime import date
                        plan = character.get("travel_plan", {})
                        if plan and plan.get("enabled"):
                            today = date.today()
                            for dest in plan.get("destinations", []):
                                start = dest.get("start_date", "")
                                end = dest.get("end_date", "")
                                if start and end:
                                    try:
                                        if date.fromisoformat(start) <= today <= date.fromisoformat(end):
                                            city_en = dest.get("city_en", dest.get("city", ""))
                                            country = dest.get("country", "")
                                            location_hint = f"in {city_en}"
                                            if country:
                                                location_hint = f"in {city_en}, {country}"
                                            if location_hint.lower() not in prompt.lower():
                                                prompt = f"{prompt}, {location_hint}"
                                                print(f"[ComfyUI] 已注入旅行目的地: {location_hint}")
                                            break
                                    except (ValueError, TypeError):
                                        continue
            except Exception as e:
                print(f"[ComfyUI] 注入旅行目的地失败: {e}")

        # 1. 解析 workflow
        parsed = _parse_comfy_workflow()
        if not parsed:
            return {"ok": False, "error": "无法加载 workflow_api.json，请确认文件存在于项目根目录"}

        workflow = parsed["workflow"]

        # 1.1 分辨率：用户指定优先，否则自动推断（人物竖屏 / 风景横屏 / 默认正方形）
        if width > 0 and height > 0:
            _w, _h = width, height
            print(f"[ComfyUI] 用户指定分辨率: {_w}x{_h}")
        else:
            _portrait_tags = (
                "selfie", "portrait", "full body", "upper body", "headshot",
                "cowboy shot", "bust shot", "standing",
            )
            _landscape_tags = (
                "landscape", "scenery", "cityscape", "panorama", "panoramic",
                "aerial view", "bird eye", "skyline", "horizon",
                "mountain", "ocean", "sea", "river", "field", "forest",
                "view from window", "sunset", "sunrise",
            )
            is_portrait = any(t in prompt_lower for t in _portrait_tags)
            is_landscape = any(t in prompt_lower for t in _landscape_tags)
            if is_portrait and not is_landscape:
                _w, _h = 768, 1024
            elif is_landscape and not is_portrait:
                _w, _h = 1024, 768
            else:
                _w, _h = 832, 832
        # 找 EmptyLatentImage 节点并修改分辨率
        for nid, node in workflow.items():
            if isinstance(node, dict) and node.get("class_type") == "EmptyLatentImage":
                node["inputs"]["width"] = _w
                node["inputs"]["height"] = _h
                print(f"[ComfyUI] 分辨率: {_w}x{_h}")
                break

        # 2. 替换正向提示词
        workflow[parsed["positive_id"]]["inputs"]["text"] = prompt

        # 3. 替换负向提示词（如果提供了的话）
        if negative_prompt.strip():
            workflow[parsed["negative_id"]]["inputs"]["text"] = negative_prompt

        # 4. 随机种子
        workflow[parsed["sampler_id"]]["inputs"]["seed"] = random.randint(1, 10**12)

        # 5. 发送任务到 ComfyUI
        resp = requests.post(
            f"{_comfyui_url()}/prompt",
            json={"prompt": workflow},
            timeout=10,
        )
        result = resp.json()

        if "error" in result:
            return {"ok": False, "error": f"ComfyUI 返回错误: {result['error'].get('message', result['error'])}"}

        prompt_id = result.get("prompt_id")
        if not prompt_id:
            return {"ok": False, "error": "ComfyUI 未返回 prompt_id"}

        # 6. 轮询等待生成完成（最多 120 秒）
        output_filename = _wait_for_comfyui(prompt_id, timeout=120)
        if not output_filename:
            return {"ok": False, "error": "图片生成超时（120秒），ComfyUI 可能卡住了"}

        # 7. 从 ComfyUI output 目录复制到 AGI 的 images 目录
        comfy_output = Path(_comfyui_output_dir()) / output_filename
        if not comfy_output.exists():
            return {"ok": False, "error": f"生成完成但找不到图片: {comfy_output}"}

        dest_dir = get_image_dir()
        dest_path = dest_dir / f"comfy_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{output_filename}"
        shutil.copy2(str(comfy_output), str(dest_path))

        size_kb = dest_path.stat().st_size // 1024
        print(f"[ComfyUI] 图片已保存: {dest_path} ({size_kb}KB)")
        return {
            "ok": True,
            "image_path": str(dest_path),
            "prompt": prompt,
            "size": f"{size_kb}KB",
            "message": f"ComfyUI 图片已生成并保存到: {dest_path} ({size_kb}KB)",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════
# Everything 全盘搜索工具（Windows）
# ═══════════════════════════════════════════════════

_ES_PATHS = [
    r"C:\Program Files\Everything\es.exe",
    r"C:\Program Files (x86)\Everything\es.exe",
    str(Path(__file__).parent / "es.exe"),
]
_es_exe_cache: Optional[str] = None


def _find_es_exe() -> Optional[str]:
    """查找 es.exe 路径（结果缓存，失败时缓存空字符串）"""
    global _es_exe_cache
    if _es_exe_cache is not None:
        return _es_exe_cache

    # 1. 在 PATH 里找
    es_in_path = shutil.which("es")
    if es_in_path:
        _es_exe_cache = es_in_path
        return _es_exe_cache

    # 2. 检查固定路径
    for p in _ES_PATHS:
        if os.path.isfile(p):
            _es_exe_cache = p
            return _es_exe_cache

    # 3. 缓存失败结果
    _es_exe_cache = ""
    return ""


def _reset_es_cache():
    """重置 es.exe 查找缓存（安装 es.exe 后调用）"""
    global _es_exe_cache
    _es_exe_cache = None


@register_tool(
    name="everything_search",
    description=(
        "使用 Everything 进行毫秒级全盘文件搜索（比系统搜索快百倍）。"
        "需要安装 Everything 并将 es.exe 放到 PATH 或 Everything 安装目录。"
        "支持通配符，如 *.py、report*.docx"
    ),
    parameters={
        "query":       {"type": "string", "description": "搜索关键词或通配符，如 *.py、report*.docx", "required": True},
        "max_results": {"type": "integer", "description": "最多返回条数，默认 20"},
        "search_path": {"type": "string", "description": "限定搜索目录（如 D:\\Projects），留空表示全盘"},
    },
    risk="low"
)
def everything_search(query: str, max_results: int = 20, search_path: str = "") -> Dict:
    try:
        es = _find_es_exe()
        # 如果之前缓存了失败，重新查找（es.exe 可能是后来安装的）
        if not es:
            _reset_es_cache()
            es = _find_es_exe()
        if not es:
            return {
                "ok": False,
                "error": (
                    "未找到 es.exe。请安装 Everything (https://www.voidtools.com) "
                    "并下载 es.exe (https://www.voidtools.com/es.zip) "
                    "放到 Everything 安装目录或 PATH 中。"
                    "\n\nes.exe not found. Install Everything and put es.exe "
                    "in the Everything directory or PATH."
                ),
            }

        cmd = [es, "-n", str(max_results), "-full-path-and-name"]
        if search_path:
            cmd.append("-path")
            cmd.append(search_path)
        cmd.append(query)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            return {"ok": False, "error": stderr or "es.exe 执行失败"}

        lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
        return {
            "ok": True,
            "results": lines,
            "count": len(lines),
            "query": query,
            "search_path": search_path or "(全盘)",
        }

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "搜索超时（5秒）/ Search timed out (5s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════
# 热点趋势工具
# ═══════════════════════════════════════════════════

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _fetch_baidu_trending() -> list:
    """百度热搜"""
    import httpx
    url = "https://top.baidu.com/api/board?tab=realtime"
    with httpx.Client(headers=_HEADERS, timeout=10, verify=False) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
    cards = data.get("data", {}).get("cards", [])
    if not cards:
        return []
    content = cards[0].get("content", [])
    result = []
    for i, item in enumerate(content):
        word = item.get("word", "")
        hot = item.get("hotScore", "")
        if word:
            result.append({"rank": i + 1, "title": word, "hot": str(hot)})
    return result[:30]


def _fetch_sspai_feed() -> list:
    """少数派 RSS"""
    import feedparser
    feed = feedparser.parse("https://sspai.com/feed")
    result = []
    for entry in feed.entries[:10]:
        result.append({
            "title": entry.get("title", ""),
            "url": entry.get("link", ""),
        })
    return result


def _fetch_github_trending() -> list:
    """GitHub Trending (Python)"""
    import httpx
    from bs4 import BeautifulSoup

    url = "https://github.com/trending/python?since=daily"
    headers = {**_HEADERS, "Accept": "text/html"}
    with httpx.Client(headers=headers, timeout=10, verify=False) as client:
        resp = client.get(url)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    articles = soup.select("article.Box-row")
    result = []
    for art in articles[:10]:
        # 仓库名在 h2 > a
        h2 = art.select_one("h2 a")
        if not h2:
            continue
        repo = "/".join(h2.get_text(strip=True).split())
        # 描述在 p
        p = art.select_one("p")
        desc = p.get_text(strip=True) if p else ""
        result.append({"repo": repo, "desc": desc})
    return result


@register_tool(
    name="get_trending",
    description="获取百度热搜、少数派最新文章、GitHub今日热门Python项目",
    parameters={},
    risk="low"
)
def get_trending() -> Dict:
    """抓取三个平台的热点数据并返回结构化结果"""
    baidu, sspai, github = [], [], []
    errors = []

    # 百度热搜
    try:
        baidu = _fetch_baidu_trending()
    except Exception as e:
        errors.append(f"百度热搜失败: {e}")

    # 少数派
    try:
        sspai = _fetch_sspai_feed()
    except Exception as e:
        errors.append(f"少数派失败: {e}")

    # GitHub Trending
    try:
        github = _fetch_github_trending()
    except Exception as e:
        errors.append(f"GitHub Trending失败: {e}")

    summary_parts = []
    if baidu:
        summary_parts.append(f"百度热搜 {len(baidu)} 条")
    if sspai:
        summary_parts.append(f"少数派 {len(sspai)} 条")
    if github:
        summary_parts.append(f"GitHub {len(github)} 条")

    result = {
        "ok": True,
        "baidu": baidu,
        "sspai": sspai,
        "github": github,
    }
    if errors:
        result["partial_errors"] = errors
        result["summary"] = "，".join(summary_parts) + f"（部分失败：{len(errors)}/3）"
    else:
        result["summary"] = "，".join(summary_parts) + "，全部获取成功"

    return result


# ═══════════════════════════════════════════════════
# 记忆查询工具（B 层按需调用，记忆回想的兜底手段）
# ═══════════════════════════════════════════════════

def _get_memory_store():
    """获取全局 MemoryStore 实例"""
    try:
        from engine.tools import _memory_store_ref
        if _memory_store_ref:
            return _memory_store_ref
    except Exception:
        pass
    return None


@register_tool(
    name="search_memories_by_date",
    description=(
        "按日期范围搜索历史记忆。当你根据已有的记忆上下文无法回忆起"
        "用户所问的某个时间段的对话时才使用此工具。"
        "如果已有上下文中已经包含相关信息，不要重复查询。"
        "日期格式：YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SS"
    ),
    parameters={
        "start_date": {"type": "string",
                       "description": "开始日期，格式 YYYY-MM-DD", "required": True},
        "end_date":   {"type": "string",
                       "description": "结束日期，格式 YYYY-MM-DD", "required": True},
        "level":      {"type": "string",
                       "description": "记忆层级：summary(大纲)/outline(细纲)/detail(细节)，默认 summary"},
        "top_k":      {"type": "integer",
                       "description": "最大返回条数，默认 30"},
    },
    risk="low"
)
def search_memories_by_date(
    start_date: str, end_date: str, level: str = "summary", top_k: int = 30
) -> Dict:
    try:
        from engine.models import MemoryLevel
        from engine.memory import MemoryStore

        store = _get_memory_store()
        if not store:
            # 尝试通过 db_path 直接创建
            try:
                from desktop.config import DB_FILE
                db_path = DB_FILE
            except Exception:
                import os
                db_path = os.path.join(
                    os.environ.get("APPDATA", str(Path.home())),
                    "AGI-Desktop", "memory.db"
                ) if os.name == "nt" else str(
                    Path.home() / "Desktop" / ".agi-desktop" / "memory.db"
                )
            store = MemoryStore(db_path)

        level_map = {
            "summary": MemoryLevel.SUMMARY,
            "outline": MemoryLevel.OUTLINE,
            "detail":  MemoryLevel.DETAIL,
        }
        mem_level = level_map.get(level, MemoryLevel.SUMMARY)

        # 补全时间：纯日期自动补 00:00:00 / 23:59:59
        if len(start_date) == 10:
            start_date += "T00:00:00"
        if len(end_date) == 10:
            end_date += "T23:59:59"

        nodes = store.get_by_date_range(
            start_date=start_date,
            end_date=end_date,
            level=mem_level,
            top_k=top_k,
        )

        if not nodes:
            return {"ok": True, "count": 0, "memories": [],
                    "hint": f"在 {start_date[:10]} ~ {end_date[:10]} 之间没有找到记忆记录"}

        items = []
        for n in nodes:
            items.append({
                "date": n.created_at[:16] if n.created_at else "",
                "content": n.content[:300],
                "importance": n.importance,
                "emotion": n.emotion.primary.value if n.emotion else "",
            })

        return {
            "ok": True,
            "count": len(items),
            "date_range": f"{start_date[:10]} ~ {end_date[:10]}",
            "memories": items,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# 全局引用：外部注入 MemoryStore 实例
_memory_store_ref = None


def set_memory_store(store):
    """由 agent 启动时调用，注入 MemoryStore 实例"""
    global _memory_store_ref
    _memory_store_ref = store


# ═══════════════════════════════════════════════════
# SimLife 行程管理工具
# ═══════════════════════════════════════════════════

@register_tool(
    "add_schedule",
    "将用户或系统提到的未来计划添加到 SimLife 日程中。当对话中出现未来要做的事情时调用。",
    {
        "content": {"type": "string", "description": "计划内容描述", "required": True},
        "date": {"type": "string", "description": "计划日期，格式 YYYY-MM-DD。支持相对日期如'明天'、'后天'、'下周一'", "required": True},
        "category": {"type": "string", "description": "分类：entertainment(娱乐)/work(工作)/personal(个人)/health(健康)/social(社交)/other(其他)", "required": False},
        "source": {"type": "string", "description": "来源：user(用户提出) / system(系统提议)", "required": False},
    },
    risk="low",
)
def add_schedule(content: str, date: str, category: str = "personal", source: str = "user") -> Dict:
    """将计划添加到 SimLife 行程（仅记录，不触发定时执行）"""
    try:
        from datetime import timedelta

        date_lower = date.strip().lower()
        if date_lower in ("明天", "tmr", "tomorrow"):
            target = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        elif date_lower in ("后天", "day after tomorrow"):
            target = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        elif date_lower in ("大后天",):
            target = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        elif date_lower.startswith("下周"):
            weekdays = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6,
                        "1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6,
                        "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
            today = datetime.now()
            target_dow = weekdays.get(date_lower.replace("下周", ""), 0)
            current_dow = today.weekday()
            days_ahead = (target_dow - current_dow + 7) % 7
            if days_ahead == 0:
                days_ahead = 7
            target = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        elif "-" in str(date) and len(str(date)) >= 8:
            target = str(date)[:10]
        else:
            return {"ok": False, "error": f"无法解析日期: {date}"}

        schedule_path = Path(__file__).resolve().parent.parent / "simlife" / "data" / "scheduled_events.json"
        schedule_path.parent.mkdir(parents=True, exist_ok=True)

        events = []
        if schedule_path.exists():
            with open(schedule_path, "r", encoding="utf-8") as f:
                try:
                    events = json.load(f)
                except json.JSONDecodeError:
                    events = []

        event = {
            "id": f"sch_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(events)}",
            "content": content,
            "scheduled_date": target,
            "scheduled_time_range": "09:00-21:00",
            "category": category,
            "source": source,
            "created_at": datetime.now().isoformat(),
        }
        events.append(event)

        with open(schedule_path, "w", encoding="utf-8") as f:
            json.dump(events, f, ensure_ascii=False, indent=2)

        return {"ok": True, "message": f"已添加行程：{content}（{target}）", "event": event}

    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════
# 定时任务（TaskScheduler 后台线程调度）
# ═══════════════════════════════════════════════════

@register_tool(
    "create_timed_task",
    description=(
        "创建定时任务，到指定时间后主动说话或执行工具。"
        "支持多种时间格式："
        "1) ISO格式 '2026-05-21T15:00:00' "
        "2) 简单时间 '15:00'（今天或明天） "
        "3) 相对时间 '+30m' '+2h' '+1d'（从现在起30分钟/2小时/1天后）"
        "repeat 可选：daily（每天）/ weekly（每周）/ interval:N（每N分钟）/ 留空表示一次性"
    ),
    parameters={
        "content": {"type": "string", "description": "任务描述，如'提醒用户喝水'", "required": True},
        "trigger_time": {"type": "string", "description": "触发时间，如 '+30m' 或 '15:00' 或 '2026-05-19T15:00:00'", "required": True},
        "action": {"type": "string", "description": "执行动作：speak（主动说话）/ tool（调用工具）", "required": True},
        "message": {"type": "string", "description": "action=speak 时要说的话", "required": False},
        "tool_name": {"type": "string", "description": "action=tool 时要调用的工具名", "required": False},
        "tool_params": {"type": "object", "description": "action=tool 时传给工具的参数", "required": False},
        "repeat": {"type": "string", "description": "重复模式：daily/weekly/interval:N，留空为一次性", "required": False},
    },
    risk="medium"
)
def create_timed_task(
    content: str,
    trigger_time: str,
    action: str = "speak",
    message: str = "",
    tool_name: str = "",
    tool_params: dict = None,
    repeat: str = "",
) -> Dict:
    try:
        from engine.task_scheduler import get_scheduler
        scheduler = get_scheduler()

        action_params = {}
        if action == "speak":
            action_params = {"message": message or content}
        elif action == "tool":
            action_params = {"tool_name": tool_name, "tool_params": tool_params or {}}

        result = scheduler.create_task(
            content=content,
            trigger_time=trigger_time,
            action=action,
            action_params=action_params,
            repeat=repeat or None,
            source="system",
        )
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


@register_tool(
    "cancel_timed_task",
    "取消一个待执行的定时任务。传入任务ID即可取消。",
    {
        "task_id": {"type": "string", "description": "要取消的任务ID", "required": True},
    },
    risk="low"
)
def cancel_timed_task(task_id: str) -> Dict:
    try:
        from engine.task_scheduler import get_scheduler
        scheduler = get_scheduler()
        return scheduler.cancel_task(task_id)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@register_tool(
    "list_timed_tasks",
    "列出当前所有待执行的定时任务。",
    {
        "status": {"type": "string", "description": "筛选状态：pending（待执行）/ done（已完成）/ all（全部）", "required": False},
    },
    risk="low"
)
def list_timed_tasks(status: str = "pending") -> Dict:
    try:
        from engine.task_scheduler import get_scheduler
        scheduler = get_scheduler()
        if status == "all":
            tasks = scheduler._tasks
        else:
            tasks = scheduler.list_tasks(status)
        if not tasks:
            return {"ok": True, "tasks": [], "message": "当前没有定时任务"}
        summaries = []
        for t in tasks:
            s = f"[{t['id']}] {t['content']} \u2192 {t['trigger_time'][:16]} ({t['action']})"
            if t.get("repeat"):
                s += f" 重复:{t['repeat']}"
            summaries.append(s)
        return {"ok": True, "tasks": tasks, "summary": "\n".join(summaries)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════
# 工具执行入口
# ═══════════════════════════════════════════════════

def execute_tool(name: str, params: dict, user_input: str = "") -> Dict:
    """执行指定工具，返回结果。user_input 用于传递用户原始消息（供工具内部判断上下文）"""
    if name not in TOOL_REGISTRY:
        return {"ok": False, "error": f"工具 '{name}' 不存在"}
    try:
        func = TOOL_REGISTRY[name]["function"]
        # 注入用户原始消息到函数属性，供 generate_image_comfy 等工具使用
        if user_input and hasattr(func, '_user_raw_input') is not False:
            func._user_raw_input = user_input
        result = func(**params)
        return result
    except TypeError as e:
        return {"ok": False, "error": f"参数错误: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"执行异常: {e}"}


def get_tool_risk(name: str) -> str:
    return TOOL_REGISTRY.get(name, {}).get("risk", "low")


def get_all_schemas() -> List[Dict]:
    """获取所有工具的 schema，用于传给 LLM"""
    return [info["schema"] for info in TOOL_REGISTRY.values()]


def get_schemas_by_risk(max_risk: str = "high") -> List[Dict]:
    """按风险等级过滤工具"""
    risk_order = {"low": 0, "medium": 1, "high": 2}
    max_level = risk_order.get(max_risk, 2)
    return [
        info["schema"] for info in TOOL_REGISTRY.values()
        if risk_order.get(info["risk"], 0) <= max_level
    ]

# ═══════════════════════════════════════════════════
# 工具自检（检测依赖库是否安装）
# ═══════════════════════════════════════════════════

# 工具依赖清单
TOOL_DEPS = {
    "screenshot":      ["pyautogui", "PIL"],
    "mouse_click":     ["pyautogui"],
    "keyboard_type":   ["pyautogui"],
    "browser_action":  ["playwright"],
    "read_clipboard":  [],   # Linux 需要 xclip，Windows/Mac 内置
    "write_clipboard": [],
    "get_stock_info":  ["yfinance"],
    "search_stock":    ["yfinance"],
    "get_news":        ["newsapi"],
    "get_news_sources":["newsapi"],
    "read_article":    ["newspaper"],
    "get_trending":    ["httpx", "feedparser", "bs4"],
    "everything_search": [],   # 依赖 es.exe 外部程序，非 Python 包
}

def check_tool_deps(tool_name: str) -> Dict:
    """
    检测某个工具的依赖库是否已安装
    返回 {ok, missing, installable}
    """
    deps = TOOL_DEPS.get(tool_name, [])
    missing = []
    for dep in deps:
        try:
            __import__(dep)
        except ImportError:
            missing.append(dep)

    install_cmds = {
        "pyautogui":  "pip install pyautogui",
        "PIL":        "pip install Pillow",
        "playwright": "pip install playwright && playwright install chromium",
        "newspaper":  "pip install newspaper3k",
    }
    cmds = [install_cmds.get(m, f"pip install {m}") for m in missing]

    return {
        "ok":      len(missing) == 0,
        "tool":    tool_name,
        "missing": missing,
        "install": cmds,
        "tip":     ("所有依赖已安装" if not missing
                    else f"缺少依赖: {', '.join(missing)}\n安装命令:\n" + "\n".join(cmds))
    }


def check_all_deps() -> Dict[str, Dict]:
    """检测所有有依赖的工具"""
    results = {}
    for tool_name in TOOL_DEPS:
        results[tool_name] = check_tool_deps(tool_name)
    return results


def self_test(tool_name: str = None) -> List[Dict]:
    """
    工具自测：每个工具用安全参数测一遍，返回测试结果
    tool_name=None 时测试所有安全工具
    """
    safe_tests = {
        "list_directory":  {"path": ".", "pattern": "*.py"},
        "get_system_info": {"info_type": "os"},
        "read_file":       {"path": __file__},          # 读自身
        "write_file":      {"path": "agi_self_test.txt",
                            "content": "AGI工具自测成功"},
        "web_search":      {"query": "python", "max_results": 1},
        "fetch_url":       {"url": "http://httpbin.org/get", "max_chars": 200},
        "run_command":     {"command": "echo AGI_TOOL_TEST_OK", "timeout": 5},
        "run_python":      {"code": "print('AGI Python工具测试OK')"},
        "search_files":    {"keyword": "def", "directory": ".",
                            "file_pattern": "*.py"},
        "search_stock":    {"keyword": "AAPL", "max_results": 1},
    }

    # 高危工具和需要依赖的工具跳过自动测试
    skip = {
        "delete_file", "mouse_click", "keyboard_type",
        "screenshot", "browser_action",
        "read_clipboard", "write_clipboard",
        "open_application", "get_stock_info",
        "get_news", "get_news_sources",   # 需要 API Key
        "read_article",                    # 需要网络请求文章
        "everything_search",               # 需要外部 es.exe
    }

    targets = [tool_name] if tool_name else list(safe_tests.keys())
    results = []

    for name in targets:
        if name in skip:
            results.append({"tool": name, "status": "skipped",
                             "reason": "高危/需依赖，跳过自动测试"})
            continue
        if name not in safe_tests:
            results.append({"tool": name, "status": "no_test_case"})
            continue

        params = safe_tests[name]
        try:
            result = execute_tool(name, params)
            ok = result.get("ok", True)
            results.append({
                "tool":   name,
                "status": "pass" if ok else "fail",
                "result": result
            })
        except Exception as e:
            results.append({
                "tool":   name,
                "status": "error",
                "error":  str(e)
            })

    return results


# ══════════════════════════════════════════
# Office 文件工具（读写 docx/xlsx/pptx/pdf）
# ══════════════════════════════════════════

@register_tool(
    name="read_office",
    description="读取 Office 文件或 PDF 内容。支持 .docx .xlsx .pptx .pdf .csv .txt",
    parameters={
        "path": {"type": "string",
                 "description": "文件路径（绝对路径或相对路径）",
                 "required": True}
    },
    risk="low"
)
def read_office(path: str) -> Dict:
    from engine.office_tools import read_office_file
    result = read_office_file(path)
    if result.get("ok"):
        text = result.get("text", "")
        if len(text) > 8000:
            text = text[:8000] + f"\n\n[内容已截断，共 {len(text)} 字符]"
        return {"ok": True, "type": result.get("type"), "text": text,
                "summary": f"成功读取 {result.get('type','').upper()} 文件，{len(text)} 字符"}
    return result


@register_tool(
    name="create_word",
    description="创建 Word 文档（.docx）。内容支持 Markdown 格式：# 标题，**粗体**，- 列表，| 表格",
    parameters={
        "path":    {"type": "string", "description": "保存路径或文件名（如 报告.docx）", "required": True},
        "content": {"type": "string", "description": "文档内容，支持 Markdown", "required": True},
        "title":   {"type": "string", "description": "文档标题（可选）"}
    },
    risk="medium"
)
def create_word(path: str, content: str, title: str = "") -> Dict:
    from engine.office_tools import create_docx
    return create_docx(path, content, title)


@register_tool(
    name="create_excel",
    description="创建 Excel 表格（.xlsx）。传入二维数组，第一行自动设为标题行",
    parameters={
        "path":       {"type": "string", "description": "保存路径或文件名", "required": True},
        "data":       {"type": "string", "description": "JSON格式的二维数组，如 [[\"姓名\",\"分数\"],[\"张三\",90]]", "required": True},
        "sheet_name": {"type": "string", "description": "Sheet名称，默认 Sheet1"}
    },
    risk="medium"
)
def create_excel(path: str, data: str, sheet_name: str = "Sheet1") -> Dict:
    from engine.office_tools import create_xlsx
    try:
        parsed = json.loads(data)
    except Exception:
        return {"ok": False, "error": "data 必须是有效的 JSON 二维数组"}
    return create_xlsx(path, parsed, sheet_name)


@register_tool(
    name="create_ppt",
    description="创建 PowerPoint 演示文稿（.pptx）",
    parameters={
        "path":        {"type": "string", "description": "保存路径或文件名", "required": True},
        "slides_json": {"type": "string",
                       "description": 'JSON数组，每项含 title/content/bullets，如 [{"title":"介绍","bullets":["要点1","要点2"]}]',
                       "required": True}
    },
    risk="medium"
)
def create_ppt(path: str, slides_json: str) -> Dict:
    from engine.office_tools import create_pptx
    try:
        slides = json.loads(slides_json)
    except Exception:
        return {"ok": False, "error": "slides_json 必须是有效的 JSON 数组"}
    return create_pptx(path, slides)


@register_tool(
    name="create_pdf",
    description="创建 PDF 文档。内容支持 Markdown 标题格式",
    parameters={
        "path":    {"type": "string", "description": "保存路径或文件名（如 文档.pdf）", "required": True},
        "content": {"type": "string", "description": "文档内容，支持 # ## 标题", "required": True},
        "title":   {"type": "string", "description": "PDF标题（可选）"}
    },
    risk="medium"
)
def create_pdf_file(path: str, content: str, title: str = "") -> Dict:
    from engine.office_tools import create_pdf
    return create_pdf(path, content, title)


@register_tool(
    name="analyze_image",
    description="分析图片内容。使用独立的多模态模型（非文本LLM），支持 OCR、图表解读、场景描述等。支持 OpenAI GPT-4o / Claude / Gemini / Qwen-VL / GLM-4V / Ollama(llava)",
    parameters={
        "image_path": {"type": "string", "description": "图片文件路径（jpg/png/gif/webp等）", "required": True},
        "question":   {"type": "string", "description": "关于图片的问题，不填则自动描述图片内容"}
    },
    risk="low"
)
def analyze_image_tool(image_path: str, question: str = "") -> Dict:
    from engine.vision_client import create_vision_client
    client = create_vision_client()
    if not client:
        return {"ok": False,
                "error": "未配置多模态模型",
                "tip": "请在设置中配置多模态模型（Vision），或在设置页面点击\"多模态配置\"进行设置"}
    result = client.analyze(image_path, question or "请详细描述这张图片的内容，包括主要对象、场景、文字等关键信息。")
    return result


@register_tool(
    name="analyze_video",
    description="分析视频内容。使用多模态模型理解视频，描述画面、动作、场景等。需要 Gemini 等支持视频的模型",
    parameters={
        "video_path": {"type": "string", "description": "视频文件路径（mp4/webm/mov等，建议不超过30秒）", "required": True},
        "question":   {"type": "string", "description": "关于视频的问题，不填则自动描述视频内容"}
    },
    risk="low"
)
def analyze_video_tool(video_path: str, question: str = "") -> Dict:
    from engine.vision_client import create_vision_client
    client = create_vision_client()
    if not client:
        return {"ok": False,
                "error": "未配置多模态模型",
                "tip": "视频分析需要 Gemini 等支持视频的模型，请在设置中配置多模态模型"}
    result = client.analyze(video_path, question or "请详细描述这个视频的内容，包括场景、人物动作、关键事件等。")
    return result


@register_tool(
    name="analyze_audio",
    description="分析音频内容。使用多模态模型理解音频，可进行语音识别、音乐分析、情感判断等。需要 Gemini 等支持音频的模型",
    parameters={
        "audio_path": {"type": "string", "description": "音频文件路径（mp3/wav/ogg/m4a等）", "required": True},
        "question":   {"type": "string", "description": "关于音频的问题，不填则自动转录和描述音频内容"}
    },
    risk="low"
)
def analyze_audio_tool(audio_path: str, question: str = "") -> Dict:
    from engine.vision_client import create_vision_client
    client = create_vision_client()
    if not client:
        return {"ok": False,
                "error": "未配置多模态模型",
                "tip": "音频分析需要 Gemini 等支持音频的模型，请在设置中配置多模态模型"}
    result = client.analyze(audio_path, question or "请转录并描述这个音频的内容。")
    return result


# ═══════════════════════════════════════════════════
# 语音识别工具（STT）
# ═══════════════════════════════════════════════════

@register_tool(
    name="stt_tool",
    description=(
        "语音识别工具。将音频文件转成文字。"
        "支持讯飞在线、DeepSeek Whisper、本地 Whisper 三种后端。"
        "当用户发送语音消息或需要转录音频时使用。"
    ),
    parameters={
        "audio_path": {"type": "string",
                       "description": "音频文件路径（wav/mp3/m4a/ogg等），支持绝对路径和相对路径",
                       "required": True},
        "language":   {"type": "string",
                       "description": "语言代码，默认 zh（中文）。支持 en、ja、ko 等"},
    },
    risk="low"
)
def stt_tool(audio_path: str, language: str = "zh") -> Dict:
    """
    语音识别：音频文件 → 文字
    以工具插件形式运行，不修改 agent.py 主逻辑
    """
    try:
        from engine.stt_engine import STTEngine
        from desktop.config import load_config

        cfg = load_config()
        engine = STTEngine(cfg)
        engine.language = language

        if not engine.is_available():
            return {
                "ok": False,
                "error": "语音识别不可用",
                "tip": STTEngine.install_guide()
            }

        result = engine.recognize_file(audio_path)
        return result

    except Exception as e:
        return {"ok": False, "error": f"语音识别异常: {e}"}


@register_tool(
    name="stt_record",
    description=(
        "录制一段语音并识别为文字。"
        "会打开麦克风录制指定时长的音频，然后转成文字。"
        "需要安装 sounddevice 或 pyaudio。"
    ),
    parameters={
        "duration": {"type": "integer",
                     "description": "录制时长（秒），默认 5 秒，最大 30 秒"},
    },
    risk="low"
)
def stt_record(duration: int = 5) -> Dict:
    """
    录音 + 语音识别
    """
    try:
        duration = max(1, min(30, duration))

        from engine.stt_engine import STTEngine, record_audio
        from desktop.config import load_config

        cfg = load_config()
        engine = STTEngine(cfg)

        if not engine.is_available():
            return {
                "ok": False,
                "error": "语音识别不可用",
                "tip": STTEngine.install_guide()
            }

        # 录制音频
        audio_path = record_audio(duration=duration)
        if not audio_path:
            return {"ok": False, "error": "录音失败，请检查麦克风或安装 sounddevice: pip install sounddevice"}

        # 识别
        result = engine.recognize_file(audio_path)

        # 清理临时文件
        try:
            os.unlink(audio_path)
        except Exception:
            pass

        return result

    except Exception as e:
        return {"ok": False, "error": f"录音识别异常: {e}"}


# ═══════════════════════════════════════════════════
# 语音合成工具（TTS）
# ═══════════════════════════════════════════════════

@register_tool(
    name="tts_tool",
    description=(
        "语音合成工具。将文字转成语音并播放。"
        "使用微软 Edge TTS（高质量在线合成）或 pyttsx3（离线兜底）。"
        "当需要将回复朗读出来时使用。"
    ),
    parameters={
        "text":    {"type": "string", "description": "要朗读的文字", "required": True},
        "voice":   {"type": "string", "description": "声音ID，如 zh-CN-XiaoxiaoNeural（默认），zh-CN-YunjianNeural（男声）"},
        "save_to": {"type": "string", "description": "保存到文件路径（可选，不填则直接播放）"},
    },
    risk="low"
)
def tts_tool(text: str, voice: str = "", save_to: str = "") -> Dict:
    """
    语音合成：文字 → 语音播放/保存
    复用现有 TTSEngine（edge-tts / pyttsx3）
    """
    try:
        from engine.tts_engine import get_tts
        import tempfile

        tts = get_tts()

        if not tts.is_available():
            return {
                "ok": False,
                "error": "语音合成不可用",
                "tip": tts.install_guide()
            }

        if voice:
            tts.set_voice(voice)

        if save_to:
            # 保存到文件
            import asyncio
            try:
                import edge_tts

                async def _save():
                    communicate = edge_tts.Communicate(text=text, voice=tts.voice)
                    await communicate.save(save_to)

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(_save())
                finally:
                    loop.close()

                size = os.path.getsize(save_to) if os.path.exists(save_to) else 0
                return {"ok": True, "saved_to": save_to, "size_bytes": size}
            except Exception as e:
                return {"ok": False, "error": f"保存失败: {e}"}
        else:
            # 异步播放（不阻塞工具调用）
            result_holder = {"done": False, "ok": False, "error": ""}
            done_event = threading.Event()

            def _on_done():
                result_holder["done"] = True
                result_holder["ok"] = True
                done_event.set()

            def _on_error(err):
                result_holder["error"] = err
                done_event.set()

            tts.speak(text, on_done=_on_done, on_error=_on_error)

            # 等待播放开始（最多等 2 秒）
            done_event.wait(timeout=2)

            return {
                "ok": True,
                "message": f"语音合成已开始播放（{tts.get_backend_name()}）",
                "text_preview": text[:100],
                "backend": tts.get_backend_name()
            }

    except Exception as e:
        return {"ok": False, "error": f"语音合成异常: {e}"}


# ═══════════════════════════════════════════════════
# 传感器数据工具（Sensor Agent）
# ═══════════════════════════════════════════════════

@register_tool(
    name="sensor_status",
    description=(
        "查询机器人/机器狗的传感器状态。"
        "返回电量、温度、姿态、速度、障碍物距离等数据的自然语言描述。"
        "当需要了解机器人当前物理状态时使用。"
        "无硬件时使用模拟数据。"
    ),
    parameters={
        "detailed": {"type": "boolean",
                     "description": "是否返回详细数据（JSON），默认 false 返回文字摘要"},
    },
    risk="low"
)
def sensor_status(detailed: bool = False) -> Dict:
    """
    查询传感器状态
    以工具插件形式运行，不修改 agent.py 主逻辑
    """
    try:
        from engine.sensor_agent import get_sensor_agent
        from desktop.config import load_config

        cfg = load_config()
        agent = get_sensor_agent(cfg)

        if not agent.is_available():
            return {"ok": False, "error": "传感器模块未启用"}

        if detailed:
            data = agent.get_all_sensors()
            # 截断过大的数据
            data_str = json.dumps(data, ensure_ascii=False, default=str)
            if len(data_str) > 5000:
                data_str = data_str[:5000] + "...(已截断)"
            return {
                "ok": True,
                "data": json.loads(data_str),
                "formatted": agent.get_status_text()
            }
        else:
            return {
                "ok": True,
                "status_text": agent.get_status_text(),
                "source": "模拟" if agent.mock_mode else "硬件"
            }

    except Exception as e:
        return {"ok": False, "error": f"传感器查询异常: {e}"}


@register_tool(
    name="sensor_command",
    description=(
        "向机器人/机器狗发送控制指令。"
        "支持行走、坐下、站立、停止、转向等基本动作。"
    ),
    parameters={
        "command": {"type": "string",
                    "description": "控制指令：walk/sit/stand/stop/turn_left/turn_right/speed_up/speed_down",
                    "required": True},
        "params":  {"type": "string",
                    "description": "附加参数（JSON 格式），如 {\"speed\": 0.5, \"duration\": 3}"},
    },
    risk="medium"
)
def sensor_command(command: str, params: str = "") -> Dict:
    """
    发送控制指令到机器人
    """
    try:
        from engine.sensor_agent import get_sensor_agent
        from desktop.config import load_config

        cfg = load_config()
        agent = get_sensor_agent(cfg)

        if not agent.is_available():
            return {"ok": False, "error": "传感器模块未启用"}

        param_dict = {}
        if params:
            try:
                param_dict = json.loads(params)
            except Exception:
                return {"ok": False, "error": "params 必须是有效的 JSON 格式"}

        result = agent.send_command(command, param_dict)
        return result

    except Exception as e:
        return {"ok": False, "error": f"指令发送异常: {e}"}


# 更新工具依赖清单
TOOL_DEPS.update({
    "stt_tool":     ["websocket-client"],     # 讯飞
    "stt_record":   ["sounddevice"],           # 录音
    "tts_tool":     ["edge_tts", "pyttsx3"],   # 已在 requirements.txt
    "sensor_status": ["paho.mqtt"],            # MQTT
    "sensor_command": ["paho.mqtt"],           # MQTT
})
