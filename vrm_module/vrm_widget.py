"""
vrm_widget.py — PyQt6 QWebEngineView 嵌入组件

在右侧工具面板上方显示 VRM 虚拟形象，尺寸固定，不影响下方工具列表。
"""

import os
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import QUrl, QTimer
from PyQt6.QtGui import QColor

# WebEngine 是否可用，延迟从 main 模块读取（避免模块级循环导入）
import sys as _sys

def _is_webengine_available():
    return getattr(_sys.modules.get("main", type("M", (), {})()), "WEBENGINE_AVAILABLE", False)


class VRMWidget(QWidget):
    """
    VRM 渲染面板，嵌入 QWebEngineView 加载 Three.js 页面。
    尺寸通过 config 配置，默认 220x220。
    """

    WIDTH  = 220
    HEIGHT = 220

    def __init__(self, parent=None, width=220, height=220):
        super().__init__(parent)
        self.WIDTH = width
        self.HEIGHT = height
        self.setFixedWidth(self.WIDTH)
        self.setFixedHeight(self.HEIGHT)
        self.setStyleSheet("background:#0d1117;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 占位标签（WebEngine 加载前显示）
        self._placeholder = QLabel("")
        self._placeholder.setStyleSheet(
            "background:#0d1117;border:1px dashed #30363d;"
            "color:#484f58;font-size:11px;"
        )
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._placeholder)

        self._web = None
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.timeout.connect(self._try_load_webengine)

        # 延迟 500ms 尝试加载，避免阻塞启动
        self._load_timer.start(500)

    def _try_load_webengine(self):
        """延迟加载 WebEngine，避免影响启动性能"""
        if not _is_webengine_available():
            self._placeholder.setText("VRM: WebEngine\n未安装")
            print("[VRM] PyQt6-WebEngine 未安装，pip install PyQt6-WebEngine")
            return
        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView

            layout = self.layout()
            layout.removeWidget(self._placeholder)
            self._placeholder.deleteLater()

            self._web = QWebEngineView()
            self._web.setStyleSheet(
                "QWebEngineView{background:transparent;border:none;}"
            )

            # 禁用右键菜单
            self._web.setContextMenuPolicy(
                Qt.ContextMenuPolicy.NoContextMenu
            )

            html_path = os.path.join(
                os.path.dirname(__file__), "static", "vrm_viewer.html"
            )
            if os.path.isfile(html_path):
                self._web.load(QUrl.fromLocalFile(
                    html_path.replace("\\", "/")
                ))
            else:
                print(f"[VRM] 渲染页面不存在: {html_path}")

            layout.addWidget(self._web)

        except Exception as e:
            self._placeholder.setText("VRM: 加载失败")
            print(f"[VRM] WebEngine 加载失败: {e}")

    def set_emotion(self, emotion: str, intensity: float = 1.0):
        """驱动 VRM 表情（由 emotion_bridge.translate 生成参数后调用）"""
        if not self._web:
            return
        js = f"setEmotion('{emotion}', {intensity:.2f})"
        self._web.page().runJavaScript(js)

    def set_speaking(self, is_speaking: bool):
        """触发/停止说话动画"""
        if not self._web:
            return
        js = f"setSpeaking({str(is_speaking).lower()})"
        self._web.page().runJavaScript(js)
