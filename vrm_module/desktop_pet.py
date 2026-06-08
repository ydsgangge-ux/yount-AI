"""
desktop_pet.py — 桌面悬浮宠物窗口

无边框、透明背景、始终置顶、可拖动。
像 Codex 桌面宠物一样直接浮在桌面上。

关键：必须通过 HTTP 服务加载页面，file:// 协议无法加载远程模型。
"""

import os
import sys as _sys
import threading
import http.server
import functools
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, QUrl, QTimer


def _is_webengine_available():
    _m = _sys.modules.get("main")
    return getattr(_m, "WEBENGINE_AVAILABLE", False) if _m else False


# ── 全局 HTTP 服务（所有 DesktopPet 实例共享） ──
_http_port = None
_http_server = None
_http_lock = threading.Lock()


def _ensure_http_server():
    """启动本地 HTTP 服务，返回端口号。线程安全，只启动一次。"""
    global _http_port, _http_server
    with _http_lock:
        if _http_port is not None:
            return _http_port

        static_dir = os.path.join(os.path.dirname(__file__), "static")
        handler = functools.partial(
            http.server.SimpleHTTPRequestHandler,
            directory=static_dir,
        )

        for port in range(18890, 18900):
            try:
                srv = http.server.HTTPServer(("127.0.0.1", port), handler)
                t = threading.Thread(target=srv.serve_forever, daemon=True)
                t.start()
                _http_server = srv
                _http_port = port
                print(f"[DesktopPet] HTTP 服务已启动: http://127.0.0.1:{port}/", flush=True)
                return _http_port
            except OSError:
                continue

        print("[DesktopPet] HTTP 服务启动失败，所有端口被占用", flush=True)
        return None


class DesktopPet(QWidget):
    """
    桌面悬浮宠物 — 无边框透明窗口，浮在所有窗口之上。
    """

    DEFAULT_WIDTH  = 260
    DEFAULT_HEIGHT = 380

    def __init__(self, parent=None, width=None, height=None):
        super().__init__(None)

        self._pet_w = width or self.DEFAULT_WIDTH
        self._pet_h = height or self.DEFAULT_HEIGHT

        # ── 窗口属性 ──
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self._pet_w, self._pet_h)

        # ── 布局 ──
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 占位标签 ──
        self._placeholder = QLabel("AI Pet\n加载中...")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(
            "background:rgba(13,17,23,0.85);"
            "color:#58a6ff;font-size:13px;"
            "border:1px solid #30363d;border-radius:12px;"
            "padding:20px;"
        )
        layout.addWidget(self._placeholder)

        self._web = None
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.timeout.connect(self._try_load_webengine)
        self._load_timer.start(500)

        # ── 拖动状态 ──
        self._drag_pos = None

        # ── 恢复上次位置 ──
        self._restore_position()

        print("[DesktopPet] 桌面宠物已创建", flush=True)

    # ────────────────── WebEngine 加载 ──────────────────

    def _try_load_webengine(self):
        if not _is_webengine_available():
            self._placeholder.setText("AI Pet\nWebEngine 未安装\npip install PyQt6-WebEngine")
            print("[DesktopPet] WebEngine 未安装", flush=True)
            return

        # 启动 HTTP 服务
        port = _ensure_http_server()
        if port is None:
            self._placeholder.setText("AI Pet\nHTTP 服务启动失败")
            return

        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView

            self._placeholder.setText("AI Pet\n加载 Live2D...")

            self._web = QWebEngineView(self)
            self._web.setStyleSheet(
                "QWebEngineView{background:transparent;border:none;}"
            )

            # 允许访问远程资源
            _settings = self._web.settings()
            try:
                from PyQt6.QtWebEngineCore import QWebEngineSettings
                _settings.setAttribute(
                    QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
                )
                _settings.setAttribute(
                    QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
                )
            except Exception:
                pass

            # ★ 关键：用 page().setBackgroundColor 设置透明背景
            #    settings().setBackgroundColor() 在 PyQt6 中不生效
            try:
                from PyQt6.QtGui import QColor
                self._web.page().setBackgroundColor(QColor(0, 0, 0, 0))
            except Exception as e:
                print(f"[DesktopPet] 透明背景设置失败: {e}", flush=True)

            self._web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

            # ★ 通过 HTTP 服务加载页面（不是 file://）
            url = QUrl(f"http://127.0.0.1:{port}/live2d_pet.html")
            self._web.load(url)
            print(f"[DesktopPet] 加载页面: {url.toString()}", flush=True)

            self._web.loadFinished.connect(self._on_load_finished)

            layout = self.layout()
            layout.removeWidget(self._placeholder)
            self._placeholder.setParent(None)
            layout.addWidget(self._web)

            print("[DesktopPet] WebEngine 加载成功", flush=True)

        except Exception as e:
            self._placeholder.setText(f"AI Pet\n加载失败\n{e}")
            print(f"[DesktopPet] WebEngine 加载失败: {e}", flush=True)

    def _on_load_finished(self, ok):
        if ok:
            print("[DesktopPet] 页面加载完成", flush=True)
        else:
            print("[DesktopPet] 页面加载失败", flush=True)

    # ────────────────── 鼠标拖动 ──────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None
            self._save_position()
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if self._web:
            self._web.page().runJavaScript("switchModel()")

    # ────────────────── 右键菜单 ──────────────────

    def contextMenuEvent(self, event):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#161b22;color:#c9d1d9;border:1px solid #30363d;"
            "padding:4px;}"
            "QMenu::item:selected{background:#21262d;}"
        )

        act_switch = menu.addAction("切换模型")
        act_hide   = menu.addAction("隐藏宠物")
        act_close  = menu.addAction("关闭宠物")

        action = menu.exec(event.globalPos())
        if action == act_switch:
            if self._web:
                self._web.page().runJavaScript("switchModel()")
        elif action == act_hide:
            self.hide()
        elif action == act_close:
            self._save_position()
            self.close()

    # ────────────────── 位置记忆 ──────────────────

    def _save_position(self):
        try:
            from desktop.config import load_config, save_config
            cfg = load_config()
            cfg["pet_pos_x"] = self.pos().x()
            cfg["pet_pos_y"] = self.pos().y()
            save_config(cfg)
        except Exception:
            pass

    def _restore_position(self):
        try:
            from desktop.config import load_config
            cfg = load_config()
            x = cfg.get("pet_pos_x")
            y = cfg.get("pet_pos_y")
            if x is not None and y is not None:
                self.move(int(x), int(y))
                return
        except Exception:
            pass
        # 默认位置：右下角
        screen = self.screen()
        if screen:
            geo = screen.availableGeometry()
            self.move(
                geo.right() - self._pet_w - 40,
                geo.bottom() - self._pet_h - 40,
            )

    # ────────────────── 兼容 VRM 接口 ──────────────────

    def set_emotion(self, emotion: str, intensity: float = 1.0):
        if not self._web:
            return
        js = f"setEmotion('{emotion}', {intensity:.2f})"
        self._web.page().runJavaScript(js)

    def set_speaking(self, is_speaking: bool):
        if not self._web:
            return
        js = f"setSpeaking({str(is_speaking).lower()})"
        self._web.page().runJavaScript(js)
