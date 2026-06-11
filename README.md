# AGI 认知助手

<p align="center">
  <b>模拟人类认知架构的桌面 AI 助手</b><br>
  分层记忆 · 情感加权 · 关联检索 · 人格成长
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/PyQt6-桌面应用-green?logo=qt" alt="PyQt6">
  <img src="https://img.shields.io/badge/许可证-MIT-yellow" alt="License">
  <img src="https://img.shields.io/badge/平台-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey" alt="Platform">
</p>

<p align="center">
  <a href="README_EN.md">English</a> | 简体中文
</p>

---

## 功能特性

- **A/B 双层架构** — A 层（意识层）拥有人格、情感、判断力；B 层（执行层）调用 LLM + 工具
- **动态思考模式** — 感知层自动判断问题复杂度，简单问题快速响应（省 token），复杂问题启用深度推理（高质量），三种模式可切换（自动/始终开启/始终关闭），服务器日志可观测决策路径
- **分层记忆系统** — SQLite + 向量检索，三级存储（大纲/细纲/片段）+ 关联网络 + 两阶段检索
- **用户画像** — 逐步积累性格特征，检测异常行为，身份验证
- **28 个内置工具** — 文件操作、系统控制、网页搜索、浏览器自动化、OCR、编程智能体、Office 文件、股票、新闻、**AI 图片生成**
- **AI 图片生成** — 双后端：① pollinations.ai（免费，无需 API Key）自动生成；② **ComfyUI 本地生成**（SDXL/NoobAI 等模型，支持 LoRA，4 步极速出图）。支持动态穿着注入（SimLife 衣柜）、旅行场景注入、风格切换（二次元/写实）。自动配置工具 `setup_comfyui.py` 一键检测路径、端口、模型
- **SimLife 生活模拟** — 虚拟生活系统：实时场景引擎（工作/居家/通勤/外出/旅游）、每日事件、心情系统、NPC 互动、天气集成（Open-Meteo 免费）、节假日日历、行程管理。随主程序自动启动，无需单独开服务器。首次使用通过内置 Web 界面初始化（`http://127.0.0.1:87659`）
- **SimLife 世界观系统** — 支持异世界通讯体验！除了默认现代世界，可导入自定义世界观（奇幻/科幻/异世界），用户通过外部大模型生成设定包（JSON），系统自动注入到角色生成、活动描述和事件系统中，实现异世界角色扮演。内置世界观模板和生成 Prompt，支持一键切换
- **成长引擎** — 人格漂移 + 主动学习 + 体验认知（去重合并 + 活跃度衰减）— AGI 在对话中不断进化
- **手机端 Web 客户端** — 内置 Web 服务（FastAPI），手机浏览器直接聊天，与桌面端共享同一个 Agent 实例和记忆
- **主动对话** — AGI 自主发起话题，用户回复后完整记忆链存储（系统→用户→AI 三方合一），主动消息带身份标识，AI 可正确区分自己发出的内容和用户发送的内容
- **12 个 LLM 供应商** — DeepSeek / OpenAI / Groq / Claude / Gemini / Qwen / 智谱 GLM / 豆包 / Kimi / 文心一言 / 讯飞星火 / Ollama（100% 本地）
- **多语言支持** — 中文 / English / 日本語 / 한국어 / Español / العربية
- **语音合成** — Microsoft Edge TTS，多种语音
- **人脸识别** — 多引擎（InsightFace / face_recognition / OpenCV），多用户身份
- **桌面集成** — 系统托盘、全局热键、悬浮窗、截图 OCR、开机自启
- **桌面宠物（Live2D + VRM）** — 双模式虚拟形象：① **Live2D 桌面宠物**（常驻桌面，8 个模型可选，一键导入新模型，情绪感知联动，眼睛跟踪鼠标，点击互动，小拖动块设计，右键菜单切换/隐藏）② **VRM 3D 面板**（内嵌对话界面，20+ 表情映射，说话动画，呼吸/眨眼）。宠物情绪随 AI 回复实时变化，缺失时优雅降级

---

## 快速开始

### Windows（推荐）

1. **安装 Python 3.10+**：前往 https://www.python.org/downloads/
   - **必须勾选** `Add Python to PATH`
2. **双击 `install.bat`** — 安装所有依赖
3. **双击 `launch.bat`** — 启动应用

安装好 Python 后只需双击两次即可！

### Linux / macOS

```bash
# 1. 确保 Python 3.10+ 和 pip 已安装
# Ubuntu: sudo apt install python3 python3-pip
# macOS:   brew install python3

# 2. 安装依赖
chmod +x install.sh launch.sh
./install.sh

# 3. 启动
./launch.sh
```

---

## 截图预览

| 主对话 | 工具面板 | 设置 |
|:---------:|:----------:|:--------:|
| ![主对话](docs/screenshots/zhuduihua.png) | ![工具面板](docs/screenshots/ceshitai.jpg) | ![设置](docs/screenshots/shezhi.jpg) |

---

## 项目结构

```
agi_app/
├── main.py                  # 入口（PyQt6 桌面应用）
├── server.py                # 手机端 Web 服务（FastAPI，共享 Agent 实例）
├── install.bat / install.sh # 一键安装脚本
├── launch.bat / launch.sh   # 启动脚本
├── setup_comfyui.py         # ComfyUI 自动检测与配置工具
├── import_model.py          # Live2D 模型一键导入脚本
├── workflow_api.json        # ComfyUI workflow（模型/LoRA/采样参数）
├── build.py                 # PyInstaller 打包脚本
├── requirements.txt         # Python 依赖
│
├── engine/                  # AGI 核心引擎
│   ├── models.py            # 数据模型（人格/记忆/情感/模态）
│   ├── memory.py            # SQLite 向量记忆存储（CRUD + 衰减）
│   ├── memory_manager.py    # 分层检索（两阶段检索）
│   ├── association.py       # 记忆关联网络（有向加权图）
│   ├── agent.py             # A 层意识体（感知→记忆→推理→工具→生成）
│   ├── executor.py          # B 层工具执行循环（ReAct，最多 8 步）
│   ├── tools.py             # 28 个工具函数
│   ├── image_gen.py         # AI 图片生成（pollinations.ai，自拍 & 风景）
│   ├── coder.py             # 自主编程智能体（写→运行→修复循环）
│   ├── office_tools.py      # Office 文件工具（docx/xlsx/pptx/pdf）
│   ├── user_profile.py      # 用户画像（特征积累 + 异常检测）
│   ├── learner.py           # 成长引擎（人格漂移 + 主动学习 + 认知去重/衰减）
│   ├── auth.py              # 多用户身份验证
│   ├── face_recognition_engine.py  # 人脸识别（三引擎懒加载）
│   ├── llm_client.py        # LLM 客户端（DeepSeek/OpenAI/Groq/Claude/Gemini/Ollama）
│   ├── tts_engine.py        # 语音合成（Edge TTS / pyttsx3）
│   └── i18n.py              # 国际化（6 种语言）
│
├── desktop/                 # 桌面系统层
│   ├── config.py            # 配置管理、路径、QSS 暗色主题
│   ├── system.py            # 系统托盘、全局热键、开机自启
│   └── screenshot.py        # 截图选择器 + OCR 后台线程
│
├── simlife/                 # SimLife 虚拟生活模拟
│   ├── backend/             # FastAPI 后端（随主程序自动启动）
│   │   ├── main.py          # 服务入口 + API 路由（端口 8769）
│   │   ├── world_engine.py  # 场景引擎（日程 + 天气 + 节假日）
│   │   ├── event_engine.py  # 每日/随机/排期事件系统
│   │   ├── mood_engine.py   # 心情计算（场景 + 事件 + 天气）
│   │   ├── npc_engine.py    # NPC 激活与互动
│   │   ├── weather.py       # Open-Meteo 天气（免费，无需 Key）
│   │   ├── generator.py     # LLM 生成人物卡/NPC 卡（自动注入世界观）
│   │   └── holiday_calendar.py  # 中国节假日 + 节日日历
│   ├── frontend/            # 初始化 Web 界面（首次创建角色）
│   ├── data/                # 运行时数据（人物卡、世界状态、事件库）
│   ├── worlds/              # 世界观系统
│   │   ├── world_manager.py       # 世界观加载/切换/注入管理器
│   │   ├── world_setting_template.json  # 13 维度世界观模板
│   │   └── generate_world_prompt.md     # 用户生成世界观的 Prompt 模板
│   └── setup.py             # 独立启动器
│
├── vrm_module/              # 虚拟形象模块（桌面宠物 + VRM，可选）
│   ├── __init__.py          # 安全加载入口（异常全拦截）
│   ├── desktop_pet.py       # 桌面萌宠窗口（Live2D 常驻桌面）
│   ├── vrm_widget.py        # PyQt6 QWebEngineView 组件
│   ├── emotion_bridge.py    # 情绪映射（AGI 情绪 → VRM BlendShape / Live2D表情）
│   ├── static/              # 前端渲染资源
│   │   ├── live2d_pet.html  # Live2D 桌面萌宠渲染页面（主）
│   │   ├── vrm_viewer.html  # Three.js + three-vrm 渲染页面
│   │   ├── lib/             # Live2D 运行时库
│   │   ├── Epsilon/         # 本地 Live2D 模型（用户可自行添加）
│   │   ├── three.module.js  # Three.js ES Module（离线）
│   │   └── three-vrm.module.js  # three-vrm ES Module（离线）
│   └── test_server.py       # 浏览器测试服务器（导航页 → 所有测试页）
│
└── ui/                      # UI 层（PyQt6）
    ├── main_window.py       # 主窗口（7 个功能标签页）
    └── float_window.py      # 悬浮窗（置顶、可拖拽、动画、主动对话回复）
```

---

## 首次配置

启动后，进入 **设置** 标签页进行配置：

| 设置项 | 说明 |
|--------|------|
| **LLM 供应商** | DeepSeek / OpenAI / Groq / Claude / Gemini / Ollama |
| **API Key** | 前往对应供应商官网获取（Ollama 无需） |
| **快捷键** | 自定义唤醒和截图快捷键 |
| **语言** | 中文 / English / 日本語 / 한국어 / Español / العربية |

### 支持的 LLM 供应商

| 供应商 | API Key 获取地址 | 备注 |
|--------|-----------------|------|
| **DeepSeek** | https://platform.deepseek.com | 推荐，价格实惠 |
| **OpenAI** | https://platform.openai.com | GPT-4o-mini 等 |
| **Groq** | https://console.groq.com | 有免费额度，速度快 |
| **Claude** | https://console.anthropic.com | Anthropic |
| **Gemini** | https://aistudio.google.com | Google |
| **Ollama** | https://ollama.ai | 100% 本地，无需 Key |

> **工具调用**：DeepSeek / OpenAI / Groq / 通义千问 / 智谱 GLM / 豆包 / Kimi / 文心一言 / 讯飞星火使用原生 function calling。Claude / Gemini / Ollama 使用 ReAct 提示词解析（工具描述嵌入提示词，JSON 输出）。所有供应商均支持真实的工具执行。

---

## 架构概览

```
用户输入
    │
    ▼
① 感知（LLM）→ 情绪 / 任务类型 / 话题标签 / 复杂度（simple/complex）
    │
    ▼
② 两阶段记忆检索
   阶段 1：向量搜索大纲 + 关联涟漪扩散
   阶段 2：按大纲方向拉取细节
   + 用户画像（始终注入）
    │
    ▼
③ 推理（LLM）→ 决定工具使用、存储策略
   └ 复杂问题启用深度思考，简单问题快速响应
    │
    ├── 需要工具 ──→ ④ B 层工具循环（ReAct，最多 8 步）
    │
    ▼
⑤ 生成回应（LLM）→ 人格驱动的输出
    │
    ▼
⑥ 存储 → 按重要性/情感分层记忆
    │
    ▼
⑦ 后台 → 用户画像 / 成长引擎 / 体验认知
```

---

## 工具列表（28 个）

| 分类 | 工具 |
|------|------|
| **文件系统** | `read_file` · `write_file` · `list_directory` · `search_files` · `delete_file` |
| **执行** | `run_command` · `run_python` |
| **网络** | `web_search`（DuckDuckGo + Bing）· `fetch_url` · `read_article`（newspaper3k） |
| **系统** | `screenshot` · `mouse_click` · `keyboard_type` · `open_application` · `get_system_info` · `read_clipboard` · `write_clipboard` |
| **浏览器** | `browser_action`（Playwright） |
| **Office** | `create_word` · `create_excel` · `create_pptx` · `create_pdf` · `read_office_file` |
| **金融** | `get_stock_info` · `search_stock` |
| **新闻** | `get_news` · `get_news_sources` |
| **图片** | `generate_image`（pollinations.ai，免费）· `generate_image_comfy`（ComfyUI 本地） |

所有高风险工具（`run_command`、`run_python`）执行前需要用户明确确认。

---

## ComfyUI 本地图片生成

支持通过本地 ComfyUI 生成高质量图片，适用于角色自拍、场景画面等。

### 快速配置

```bash
# 1. 安装并启动 ComfyUI（https://github.com/comfyanonymous/ComfyUI）
# 2. 下载模型到 ComfyUI/models/checkpoints/ 目录
# 3. 双击运行自动配置工具
python setup_comfyui.py
```

`setup_comfyui.py` 会自动检测：ComfyUI 安装路径、运行端口、可用模型、workflow 匹配，并让你选择生成风格（二次元/写实/无）。

### 支持的模型

不限制特定模型，`workflow_api.json` 就是标准 ComfyUI 导出格式。你可以在 ComfyUI 中搭建自己的 workflow 后导出替换。

| 推荐 | 说明 |
|------|------|
| NoobAI + sdxl_lightning LoRA | 二次元动漫，4 步出图 |
| SDXL Turbo | 写实风格，4 步出图 |
| Flux / SD 1.5 / 其他 | 修改 workflow_api.json 即可 |

### 智能注入

出图时自动追加：
1. **风格前缀** — 根据 config 中的 `comfyui_style` 追加（anime: `illustration, anime style, pixiv` / realistic: `photorealistic, 8k uhd`）
2. **外貌特征** — avatar_prompt（五官、发型、体型）
3. **动态穿着** — SimLife 衣柜根据当前场景/时间自动匹配
4. **旅行场景** — 旅游博主模式下自动注入所在城市

---

## SimLife 世界观系统

SimLife 支持自定义世界观，让你体验异世界通讯的感觉 — AGI 可以扮演奇幻/科幻世界中的角色。

### 工作原理

- **现代世界**（默认）：不可删除，使用原有现实主题逻辑
- **自定义世界**：用户通过外部大模型生成世界观设定（JSON），导入后系统自动注入到角色生成、活动描述和事件生成中
- **LLM 配置继承**：SimLife 自动使用主系统的大模型配置，无需单独设置

### 使用步骤

1. 打开 `simlife/worlds/generate_world_prompt.md`，复制 Prompt 模板
2. 粘贴到你喜欢的任意大模型（如 DeepSeek、ChatGPT 等），按需修改定制区域
3. 将生成的 JSON 保存为 `world_setting.json`
4. 通过 SimLife API 导入：`POST http://127.0.0.1:8769/api/worlds/import`
5. 切换世界：`POST http://127.0.0.1:8769/api/worlds/switch`，body: `{"world_id": "你的世界ID"}`

### API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/worlds` | GET | 列出所有可用世界观 |
| `/api/worlds/current` | GET | 获取当前世界观 |
| `/api/worlds/switch` | POST | 切换世界观 |
| `/api/worlds/import` | POST | 导入世界观设定 |
| `/api/worlds/template` | GET | 获取世界观模板 |

### 世界观模板维度

`world_setting_template.json` 包含 13 个维度：世界名称、地理、种族、力量体系、势力、历史、日常生活、危险/副本、物品、通讯装置、时间体系、特殊规则、自定义字段。提供原神风格、刀剑神域风格、原创魔法世界等 Prompt 示例。

---

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Shift+Space` | 显示/隐藏悬浮窗 |
| `Ctrl+Shift+S` | 选区截图 + OCR |

> 两个快捷键均可在设置中自定义。

---

## 可选增强功能

以下组件会在 `install.bat`/`install.sh` 中自动安装（如可能）：

```bash
# 语音合成（Microsoft Edge TTS，免费）
pip install edge-tts

# 手机端 Web 服务（手机浏览器聊天）
pip install fastapi uvicorn PyJWT

# Office 文件读写（Word/Excel/PPT/PDF）
pip install python-docx openpyxl python-pptx reportlab pdfplumber

# 语义向量（提升记忆检索质量，约 500MB）
pip install sentence-transformers

# 人脸识别（InsightFace 引擎，推荐）
pip install insightface onnxruntime opencv-python

# 浏览器自动化
pip install playwright && playwright install chromium

# 文章提取（智能新闻/文章解析器）
pip install newspaper3k

# 金融工具（股票信息与搜索）
pip install yfinance

# 新闻工具（需要 newsapi.org 的 API Key）
pip install newsapi-python

# VRM 虚拟形象（PyQt6 WebEngine，可选，需 Python 3.12/3.13）
pip install PyQt6-WebEngine
```

缺少可选依赖时会优雅降级 — 核心功能不受影响。

---

## 桌面宠物（Live2D）

桌面宠物体现已取代原有 VRM 面板，作为默认虚拟形象。使用 **Live2D** 技术渲染，带交互和情绪感知：

| 功能 | 说明 |
|------|------|
| **桌面显示** | 独立小窗口常驻桌面，顶部小拖动块拖拽/右键菜单 |
| **交互** | 眼睛跟随鼠标、点击出现互动文案 |
| **情绪联动** | AI 回复时自动切换表情（喜/怒/哀/惊/好奇/思考）|
| **模型切换** | 右键菜单 / 快捷键 `S` 切换模型 |
| **一键导入** | `python import_model.py 模型文件夹` |

### 预置模型

| 模型 | 来源 |
|------|------|
| Haru / Shizuku | pixi-live2d-display 测试资源 |
| Mao / Hiyori / Natori / Ren / Rice | Live2D CubismWebSamples 官方示例 |
| Epsilon | 本地模型（已导入） |

### 添加新模型

```bash
python import_model.py 下载的模型文件夹路径
# 刷新浏览器预览，或重启应用
```

### 浏览器测试

```bash
python vrm_module/test_server.py
# 浏览器打开 http://localhost:8899/live2d_pet.html
# 点右下角 ↻ 切换模型 | F12 控制台看日志
```

## VRM 虚拟形象

除 Live2D 桌面宠物外，还保留了 VRM 3D 模型模式（对话界面右侧面板）。

### 启用条件

- Python 3.12 或 3.13（3.14 暂不兼容 PyQt6-WebEngine）
- `pip install PyQt6-WebEngine`
- 将 `.vrm` 模型文件放入 `vrm_module/static/model.vrm`

### 模型来源

- [VRoid Studio](https://vroid.com/studio)（免费捏脸工具）
- [VRoid Hub](https://hub.vroid.com)（免费可商用模型）

### 表情映射

| AGI 情绪 | VRM 表情 | 强度 |
|----------|----------|------|
| happy / love / gratitude | happy | 0.7~1.0 |
| sad / anxious / nostalgic | sad | 0.3~0.7 |
| angry | angry | 0.6 |
| surprised / curious | surprised | 0.4~1.0 |
| neutral / calm / trust | neutral | 0.7~1.0 |

---

## 打包为独立可执行文件

```bash
pip install pyinstaller
python build.py windows   # → dist/AGI-Desktop.exe
python build.py linux     # → dist/AGI-Desktop
```

---

## 数据存储

所有数据存储在用户目录中 — 项目文件夹保持干净：

| 平台 | 数据目录 |
|------|---------|
| Windows | `%APPDATA%\AGI-Desktop\` |
| Linux/macOS | `~/.agi-desktop/` |

核心文件：
- `config.json` — 用户设置（API Key、快捷键、ComfyUI 配置等）
- `personality.json` — 人格配置（含 avatar_prompt 外貌设定）
- `memory.db` — SQLite 数据库（记忆/关联/用户画像/人脸/成长）

---

## 常见问题

### "Python 未安装" 或 "'python' 不是内部或外部命令"

1. 前往 https://www.python.org/downloads/ 下载 Python
2. 安装时**勾选 "Add Python to PATH"**（关键！）
3. 重新打开命令提示符，再次运行 `install.bat`

### "No module named PyQt6"

重新运行 `install.bat`，或手动执行：`pip install -r requirements.txt`

### 控制台乱码

右键控制台标题栏 → 属性 → 字体 → 选择支持你所用语言的字体。

### 记忆检索质量不佳

安装语义向量：`pip install sentence-transformers`

### Ollama 工具调用不工作

Ollama 不原生支持 function calling。建议使用 DeepSeek API 以获得完整工具支持。

### VRM 面板显示 "WebEngine 未安装"

Python 3.14 暂不兼容 PyQt6-WebEngine，需使用 Python 3.12 或 3.13。VRM 模块为可选功能，不影响主程序运行。

---

## 技术栈

- **UI**：PyQt6（暗色主题）
- **LLM**：DeepSeek / OpenAI / Groq / Claude / Gemini / Ollama
- **记忆**：SQLite + sentence-transformers（可选）
- **手机端**：FastAPI + Uvicorn + PyJWT
- **语音**：Edge TTS / pyttsx3
- **人脸**：InsightFace / face_recognition / OpenCV
- **Office**：python-docx / openpyxl / python-pptx / reportlab / pdfplumber
- **浏览器**：Playwright（可选）
- **金融**：yfinance
- **文章**：newspaper3k
- **图片**：pollinations.ai（免费）/ ComfyUI（本地，可选）
- **虚拟形象**：Three.js + three-vrm + PyQt6-WebEngine（可选）

---

## 许可证

[MIT](LICENSE)
