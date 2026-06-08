"""
desktop_pet.py — 桌面悬浮宠物窗口

无边框、透明背景、始终置顶、可拖动、可缩放。
像 Codex 桌面宠物一样直接浮在桌面上，不嵌在主窗口内。
"""

import os
import sys as _sys
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import Qt, QUrl, QTimer, QPoint
from PyQt6.QtGui import QCursor


def _is_webengine_available():
    _m = _sys.modules.get("main")
    return getattr(_m, "WEBENGINE_AVAILABLE", False) if _m else False


class DesktopPet(QWidget):
    """
    桌面悬浮宠物 — 无边框透明窗口，浮在所有窗口之上。

    特性：
    - 无边框 + 透明背景（只看到角色本身）
    - 始终置顶（WindowStaysOnTopHint）
    - 鼠标拖动移动位置
    - 双击切换模型
    - 右键菜单：切换模型 / 最小化 / 关闭
    - 位置记忆（保存到配置）
    """

    DEFAULT_WIDTH  = 260
    DEFAULT_HEIGHT = 380

    def __init__(self, parent=None, width=None, height=None):
        # ★ 关键：不传 parent，否则会被主窗口约束
        super().__init__(None)

        self._pet_w = width or self.DEFAULT_WIDTH
        self._pet_h = height or self.DEFAULT_HEIGHT

        # ── 窗口属性 ──
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint      # 无边框
            | Qt.WindowType.WindowStaysOnTopHint   # 始终置顶
            | Qt.WindowType.Tool                   # 不在任务栏显示
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)  # 透明背景
        self.setFixedSize(self._pet_w, self._pet_h)

        # ── 布局 ──
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._web = None
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.timeout.connect(self._try_load_webengine)
        self._load_timer.start(800)

        # ── 拖动状态 ──
        self._drag_pos = None

        # ── 恢复上次位置 ──
        self._restore_position()

        print("[DesktopPet] 桌面宠物已创建")

    # ────────────────── WebEngine 加载 ──────────────────

    def _try_load_webengine(self):
        if not _is_webengine_available():
            print("[DesktopPet] WebEngine 未安装，pip install PyQt6-WebEngine")
            return
        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView

            self._web = QWebEngineView(self)
            self._web.setStyleSheet(
                "QWebEngineView{background:transparent;border:none;}"
            )

            # 允许访问远程资源（CDN 模型）
            _settings = self._web.settings()
            try:
                from PyQt6.QtWebEngineCore import QWebEngineSettings
                _settings.setAttribute(
                    QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
                )
                _settings.setAttribute(
                    QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
                )
                # 允许透明背景
                _settings.setAttribute(
                    QWebEngineSettings.WebAttribute.BackgroundColor, 0
                )
            except Exception:
                pass

            self._web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

            # 加载 Live2D 页面
            html_path = os.path.join(
                os.path.dirname(__file__), "static", "live2d_pet.html"
            )
            if os.path.isfile(html_path):
                self._web.load(QUrl.fromLocalFile(
                    html_path.replace("\\", "/")
                ))
            else:
                print(f"[DesktopPet] 页面不存在: {html_path}")
                return

            self.layout().addWidget(self._web)
            print("[DesktopPet] WebEngine 加载成功")

        except Exception as e:
            print(f"[DesktopPet] WebEngine 加载失败: {e}")

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
        """双击切换模型"""
        if self._web:
            self._web.page().runJavaScript("switchModel()")

    # ────────────────── 右键菜单 ──────────────────

    def contextMenuEvent(self, event):
        menu = self._web  # 不用 web 的菜单
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
