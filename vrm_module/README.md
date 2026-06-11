# 虚拟形象模块

包含两种虚拟形象模式：**Live2D 桌面宠物**（默认）和 **VRM 3D 面板**（可选）。

---

## Live2D 桌面宠物

常驻桌面的交互式 Live2D 萌宠，支持情绪感知联动、模型切换、一键导入。

### 启用

自动启用，无需额外安装依赖。Live2D 渲染在 QWebEngineView 中运行，使用 pixi-live2d-display 框架。

### 添加新模型

```bash
python import_model.py 模型文件夹路径
```

脚本会自动复制文件夹、找到 `.model3.json` 并注册到模型列表。

### 操作

| 操作 | 说明 |
|------|------|
| **鼠标拖拽顶部方块** | 拖动宠物窗口 |
| **右键点击顶部方块** | 弹出菜单（切换模型 / 隐藏 / 关闭）|
| **点击模型本体** | 触发随机互动文案 |
| **鼠标移动** | 模型眼睛跟随 |
| **键盘 S** | 快速切换模型 |

### 模型列表

模型定义在 `static/live2d_pet.html` 的 `MODELS` 数组中。默认 8 个模型：

| 名称 | 来源 |
|------|------|
| Haru | pixi-live2d-display |
| Shizuku | pixi-live2d-display |
| Mao | Live2D CubismWebSamples |
| Hiyori | Live2D CubismWebSamples |
| Natori | Live2D CubismWebSamples |
| Ren | Live2D CubismWebSamples |
| Rice | Live2D CubismWebSamples |
| Epsilon | 本地导入 |

### 情绪联动

AI 回复时通过 `emotion_bridge.py` 将 AGI 情绪映射为 Live2D 表情参数：

| AGI 情绪 | Live2D 表情 |
|----------|------------|
| happy / excited / love | happy |
| sad / anxious / nostalgic | sad |
| angry | angry |
| surprised / curious | surprised |
| neutral / calm / thinking | neutral |

### 浏览器测试

```bash
python vrm_module/test_server.py
# 打开 http://localhost:8899/live2d_pet.html
# 点右下角 ↻ 切换模型 | F12 看日志
```

---

## VRM 3D 面板

对话界面右侧的 3D 虚拟角色面板。

### 安装依赖

```bash
pip install PyQt6-WebEngine
```

### 放置模型

将 `.vrm` 模型文件放入 `static/` 文件夹，重命名为 `model.vrm`。

推荐获取方式：
- [VRoid Studio](https://vroid.com/studio)（免费捏脸工具）
- [VRoid Hub](https://hub.vroid.com)（免费可商用模型）

### 配置

在 `config.json` 中控制：

```json
{
  "vrm_enabled": true,
  "vrm_width": 220,
  "vrm_height": 220
}
```

### 优雅降级

以下情况自动跳过，不影响主程序：
- PyQt6-WebEngine 未安装
- VRM 模型文件缺失
- Three.js 加载失败
- WebGL 不支持
- config 中 `vrm_enabled: false`

---

## 架构

```
vrm_module/
├── __init__.py           # 安全加载入口（异常全拦截）
├── desktop_pet.py        # 桌面萌宠窗口（Live2D 常驻桌面）
├── vrm_widget.py         # PyQt6 QWebEngineView 组件
├── emotion_bridge.py     # 情绪映射（AGI → Live2D / VRM）
├── import_model.py        # 一键导入脚本（位于项目根目录）
├── test_server.py        # 测试服务（导航页 + 静态文件）
└── static/
    ├── live2d_pet.html   # Live2D 桌面萌宠渲染页（默认）
    ├── vrm_viewer.html   # VRM 3D 渲染页
    ├── lib/              # Live2D 运行时库（pixi.min.js 等）
    ├── Epsilon/          # 本地 Live2D 模型目录
    └── model.vrm         # VRM 模型文件（用户自行放置）
```