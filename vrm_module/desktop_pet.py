"""
desktop_pet.py — 桌面悬浮宠物窗口

无边框、透明背景、始终置顶。
顶部中央有 ~1cm 拖动块，鼠标悬停变色提示，按住拖动。
其余区域鼠标事件直通 Live2D（眼睛跟踪 / 点击互动正常）。
"""

import os
import sys as _sys
import threading
import http.server
import functools
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QMenu
from PyQt6.QtCore import Qt, QUrl, QTimer, QEvent, QSize
from PyQt6.QtGui import QColor, QCursor, QPainter, QFont


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


# ────────────────── 拖动块 ──────────────────

class _DragHandle(QWidget):
    """
    桌面宠物顶部中央的小拖动块。
    - 悬停时变亮 + 鼠标变十字箭头
    - 左键按住拖动窗口
    - 右键弹出菜单
    """
    HANDLE_SIZE = 36  # ~1cm（96dpi 下约 0.95cm）

    def __init__(self, pet_widget):
        super().__init__(pet_widget)
        self._pet = pet_widget
        self._hovered = False
        self._drag_pos = None

        hs = self.HANDLE_SIZE
        self.setGeometry((pet_widget.width() - hs) // 2, 4, hs, hs)
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))

        self.setStyleSheet("""
            _DragHandle {
                background: rgba(48,54,61,0.5);
                border: 1px solid rgba(139,148,158,0.4);
                border-radius: 18px;
            }
            _DragHandle:hover {
                background: rgba(88,166,255,0.35);
                border: 1px solid rgba(88,166,255,0.7);
            }
        """)

    # ── 画四条小点装饰 ──
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(139, 148, 158, 180 if self._hovered else 100)
        p.setPen(color)
        hs = self.HANDLE_SIZE
        cx, cy = hs // 2, hs // 2
        for i in range(4):
            x = cx - 6 + i * 4
            p.drawPoint(x, cy)

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        self._drag_pos = None
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # ★ OS 系统级拖动
            win = self._pet.windowHandle()
            if win is not None:
                try:
                    win.startSystemMove()
                    event.accept()
                    return
                except Exception:
                    pass
            # 回退：手动拖动
            self._drag_pos = event.globalPosition().toPoint() - self._pet.pos()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self._pet._show_menu(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None:
            self._pet.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self._drag_pos = None
            self._pet._save_position()


# ────────────────── 主窗口 ──────────────────

class DesktopPet(QWidget):
    """
    桌面悬浮宠物 — 无边框透明窗口，浮在所有窗口之上。
    顶部拖动块控制移动，主体区域鼠标事件透传 Live2D。
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
        self._handle = None
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.timeout.connect(self._try_load_webengine)
        self._load_timer.start(500)

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

            # ★ 透明背景
            try:
                self._web.page().setBackgroundColor(QColor(0, 0, 0, 0))
            except Exception as e:
                print(f"[DesktopPet] 透明背景设置失败: {e}", flush=True)

            # ★ 右键菜单：CustomContextMenu 信号（防 Chrome 默认菜单）
            try:
                self._web.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                self._web.customContextMenuRequested.connect(self._on_web_menu)
            except Exception:
                pass

            # ★ 加载页面
            url = QUrl(f"http://127.0.0.1:{port}/live2d_pet.html?mode=desktop")
            self._web.load(url)
            print(f"[DesktopPet] 加载页面: {url.toString()}", flush=True)

            self._web.loadFinished.connect(self._on_load_finished)

            # 交换占位标签 → QWebEngineView
            layout = self.layout()
            layout.removeWidget(self._placeholder)
            self._placeholder.setParent(None)
            layout.addWidget(self._web)

            # ★ 顶部拖动块（在 QWebEngineView 之上）
            self._handle = _DragHandle(self)
            self._handle.show()
            self._handle.raise_()

            print("[DesktopPet] WebEngine 加载成功", flush=True)

        except Exception as e:
            self._placeholder.setText(f"AI Pet\n加载失败\n{e}")
            print(f"[DesktopPet] WebEngine 加载失败: {e}", flush=True)

    def _on_load_finished(self, ok):
        if ok:
            print("[DesktopPet] 页面加载完成", flush=True)
        else:
            print("[DesktopPet] 页面加载失败", flush=True)

    # ────────────────── 右键菜单 ──────────────────

    def _on_web_menu(self, pos):
        """QWebEngineView 右键信号 → 弹出菜单"""
        global_pos = self._web.mapToGlobal(pos)
        self._show_menu(global_pos)

    def contextMenuEvent(self, event):
        """占位标签阶段的右键菜单"""
        self._show_menu(event.globalPos())

    def _show_menu(self, global_pos):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#161b22;color:#c9d1d9;border:1px solid #30363d;"
            "padding:4px;}"
            "QMenu::item:selected{background:#21262d;}"
        )
        act_switch = menu.addAction("切换模型")
        menu.addSeparator()
        act_hide  = menu.addAction("隐藏宠物")
        act_close = menu.addAction("关闭宠物")

        action = menu.exec(global_pos)

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