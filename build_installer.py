"""
一键打包安装程序
- 下载嵌入式 Python 3.13 (amd64)
- 安装全部依赖到嵌入式 Python
- 收集项目文件
- 调用 NSIS 生成安装程序

用法：python build_installer.py
产物：dist/AGI-Assistant-Setup.exe
"""

import os
import sys
import shutil
import subprocess
import urllib.request
import zipfile
import json
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────
APP_NAME = "AGI-Assistant"
APP_VERSION = "1.0.0.1"
APP_PUBLISHER = "Yount-AI"

PYTHON_VERSION = "3.13.7"          # 嵌入式 Python 版本
PYTHON_EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"

# 项目根目录
BASE = Path(__file__).parent
BUILD_DIR = BASE / "build_installer"
DIST_DIR = BASE / "dist"
# 持久缓存目录（存放已下载的 Python 与已安装依赖，避免每次打包重复下载）
CACHE_DIR = BASE / ".build_cache"

# NSIS 路径（自动探测）
NSIS_CANDIDATES = [
    "C:\\Program Files (x86)\\NSIS\\makensis.exe",
    "C:\\Program Files\\NSIS\\makensis.exe",
]

# ── 工具函数 ──────────────────────────────────────────
def _find_nsis() -> str:
    """查找 makensis.exe"""
    # 优先 PATH
    from shutil import which
    p = which("makensis")
    if p:
        return p
    for c in NSIS_CANDIDATES:
        if Path(c).exists():
            return c
    return ""


def _download(url: str, dest: Path):
    """下载文件（带进度）"""
    print(f"  下载: {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as f:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                bar = "█" * (pct // 2) + "·" * (50 - pct // 2)
                print(f"\r  [{bar}] {pct:3d}% ({done//1024}KB/{total//1024}KB)", end="")
        print()
    print(f"  保存到: {dest}")


def _extract_zip(zip_path: Path, dest: Path):
    """解压 zip"""
    print(f"  解压到: {dest}")
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest)


# ── 打包步骤 ──────────────────────────────────────────
def step1_prepare_dirs():
    """1. 准备打包目录（保留持久缓存）"""
    print("\n[1/6] 准备打包目录...")
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    if CACHE_DIR.exists():
        print(f"  复用缓存目录: {CACHE_DIR}（Python 与依赖无需重新下载）")
    if DIST_DIR.exists():
        # 不删 dist，避免误删其他构建产物
        pass
    BUILD_DIR.mkdir(parents=True)
    print(f"  打包工作目录: {BUILD_DIR}")


def step2_download_python():
    """2. 下载并解压嵌入式 Python（命中缓存则直接复用）"""
    py_dir = BUILD_DIR / "python"
    py_exe = py_dir / "python.exe"

    # 命中完整缓存：直接复用已装好依赖的 Python 环境
    if _cache_valid():
        print("\n[2/6] 命中缓存 Python 环境...")
        cache_py = CACHE_DIR / "python"
        shutil.copytree(cache_py, py_dir)
        print(f"  已从缓存复制 Python 环境（跳过下载与依赖安装）")
        return py_dir, py_exe, True

    print("\n[2/6] 下载嵌入式 Python...")
    py_zip = CACHE_DIR / f"python-{PYTHON_VERSION}-embed-amd64.zip"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if py_zip.exists():
        print(f"  已存在缓存: {py_zip}")
    else:
        _download(PYTHON_EMBED_URL, py_zip)
    _extract_zip(py_zip, py_dir)

    # 启用 pip：取消 ._pth 中的 import site 注释
    pth_files = list(py_dir.glob("python*._pth"))
    for pth in pth_files:
        text = pth.read_text(encoding="utf-8")
        if "import site" in text and "#import site" in text:
            text = text.replace("#import site", "import site")
            pth.write_text(text, encoding="utf-8")
            print(f"  启用 site 模块: {pth.name}")

    # 安装 pip
    print("  安装 pip...")
    get_pip = BUILD_DIR / "get-pip.py"
    _download("https://bootstrap.pypa.io/get-pip.py", get_pip)
    subprocess.run(
        [str(py_exe), str(get_pip), "--no-warn-script-location"],
        cwd=str(py_dir),
        check=True,
        capture_output=True,
    )
    print("  pip 安装完成")
    return py_dir, py_exe, False


# 全部依赖（分批安装，避免单次失败；同时用于缓存校验）
DEPS = [
    # 核心 UI 框架
    "PyQt6>=6.6.0",
    "Pillow>=10.0.0",
    "pyautogui>=0.9.54",
    "pytesseract>=0.3.10",
    "keyboard>=0.13.5",
    "requests>=2.31.0",
    # Office 工具
    "python-docx>=1.1.0",
    "openpyxl>=3.1.0",
    "python-pptx>=0.6.23",
    "reportlab>=4.1.0",
    "pdfplumber>=0.10.0",
    # 金融
    "yfinance>=0.2.31",
    # TTS 语音
    "edge-tts>=6.1.0",
    "pyttsx3>=2.90",
    # 新闻
    "newspaper3k>=0.2.8",
    "lxml_html_clean>=0.1.0",
    # HTTP / 抓取
    "httpx>=0.27.0",
    "feedparser>=6.0.11",
    "beautifulsoup4>=4.12.3",
    # FastAPI 服务（SimLife + 手机端）
    "fastapi>=0.110.0",
    "uvicorn>=0.27.0",
    "PyJWT>=2.8.0",
    # Flask 网页版
    "Flask>=3.0.0",
    "Flask-SocketIO>=5.3.0",
    # 语音 STT
    "websocket-client>=1.6.0",
    "sounddevice>=0.4.6",
    "SoundFile>=0.10.3",
    # 传感器
    "paho-mqtt>=2.0.0",
    # pydantic（SimLife）
    "pydantic>=2.0.0",
]


def _deps_hash() -> str:
    """依赖清单的哈希，用于缓存有效性校验"""
    import hashlib
    return hashlib.md5("\n".join(DEPS).encode("utf-8")).hexdigest()


def _cache_valid() -> bool:
    """已缓存的完整 Python 环境是否可用（存在且依赖清单匹配）"""
    py = CACHE_DIR / "python" / "python.exe"
    deps_file = CACHE_DIR / "deps.txt"
    if not py.exists() or not deps_file.exists():
        return False
    return deps_file.read_text(encoding="utf-8").strip() == _deps_hash()


def step3_install_deps(py_exe: Path, py_dir: Path, from_cache: bool = False):
    """3. 安装全部依赖到嵌入式 Python（若 from_cache，直接复用缓存环境）"""
    print("\n[3/6] 安装全部依赖...")

    if from_cache:
        print(f"  ✓ 命中缓存，跳过依赖安装（{len(DEPS)} 个依赖已就绪）")
        total = sum(f.stat().st_size for f in py_dir.rglob("*") if f.is_file())
        print(f"  Python 环境总大小: {total/1024/1024:.1f} MB")
        return

    # 分批安装，避免单次安装失败
    deps = DEPS

    print(f"  安装 {len(deps)} 个依赖包...")
    for i, dep in enumerate(deps, 1):
        print(f"  [{i}/{len(deps)}] {dep.split('>')[0].split('=')[0]}...")
        result = subprocess.run(
            [str(py_exe), "-m", "pip", "install", dep, "--no-warn-script-location",
             "--no-cache-dir", "--quiet"],
            cwd=str(py_dir),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"    [WARN] {dep} 安装失败: {result.stderr[:200]}")

    # 单独安装 PyQt6-WebEngine（体积大，可能失败）
    print("  [可选] PyQt6-WebEngine...")
    result = subprocess.run(
        [str(py_exe), "-m", "pip", "install", "PyQt6-WebEngine",
         "--no-warn-script-location", "--no-cache-dir", "--quiet"],
        cwd=str(py_dir),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"    [WARN] PyQt6-WebEngine 安装失败（VRM 模块将不可用）: {result.stderr[:200]}")
    else:
        print("    [OK] PyQt6-WebEngine 安装成功")

    # 清理 pip 缓存和临时文件
    cache_dir = py_dir / "pip"
    if cache_dir.exists():
        shutil.rmtree(cache_dir, ignore_errors=True)

    # 统计体积
    total_size = sum(f.stat().st_size for f in py_dir.rglob("*") if f.is_file())
    print(f"  Python 环境总大小: {total_size/1024/1024:.1f} MB")

    # 写入持久缓存，下次打包直接复用
    print("  保存环境到缓存（下次打包可直接复用，无需重新下载）...")
    cache_py = CACHE_DIR / "python"
    if cache_py.exists():
        shutil.rmtree(cache_py, ignore_errors=True)
    cache_py.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(py_dir, cache_py)
    (CACHE_DIR / "deps.txt").write_text(_deps_hash(), encoding="utf-8")


def step4_collect_project(app_root: Path):
    """4. 收集项目文件"""
    print("\n[4/6] 收集项目文件...")

    # 排除规则
    EXCLUDE_DIRS = {
        "__pycache__", ".git", ".idea", ".vscode", "venv", ".venv",
        "dist", "build", "build_installer", ".workbuddy", ".codebuddy",
        "node_modules", "screenshot_*.png",
    }
    EXCLUDE_FILES = {
        ".gitignore", ".gitattributes", "build.py", "build_installer.py",
        "main_patch.txt", "PROJECT_HANDOFF.md",
    }
    EXCLUDE_PATTERNS = [
        "*.pyc", "*.pyo", "*.pyd.bak", "*.log", "*.db",
        "screenshot_*.png", "*.whl", "*.egg-info",
    ]
    EXCLUDE_PATHS = {
        # SimLife 运行时数据（用户首次启动生成）
        "simlife/data/world_state.json",
        "simlife/data/character_card.json",
        "simlife/data/npc_cards.json",
        "simlife/data/event_history.json",
        "simlife/data/scheduled_events.json",
        "simlife/data/weather_cache.json",
        "simlife/data/last_online.json",
        "simlife/data/death_mode_state.json",
        "simlife/data/user_profile.json",
        "simlife/data/simlife_config.json",
        "simlife/data/story_influence.json",
        "simlife/data/story_cast.json",
        # 外部二进制（用户单独下载）
        "engine/es.exe",
    }
    EXCLUDE_DIRS_BY_PART = {
        "story_archive", "dungeons", "worlds",  # SimLife 子目录
    }

    import fnmatch

    def should_skip(path: Path, rel_parts: tuple) -> bool:
        # 排除目录
        if any(part in EXCLUDE_DIRS for part in rel_parts):
            return True
        # 排除特定子目录（按目录名匹配）
        if any(part in EXCLUDE_DIRS_BY_PART for part in rel_parts):
            return True
        # 排除 VRM 大模型文件
        if path.suffix == ".vrm":
            return True
        # 排除特定文件
        if path.name in EXCLUDE_FILES:
            return True
        # 排除模式
        for pat in EXCLUDE_PATTERNS:
            if fnmatch.fnmatch(path.name, pat):
                return True
        # 排除特定相对路径
        rel_path = "/".join(rel_parts)
        if rel_path in EXCLUDE_PATHS:
            return True
        return False

    copied = 0
    total_size = 0

    for root, dirs, files in os.walk(BASE):
        root_path = Path(root)
        rel_parts = tuple(root_path.relative_to(BASE).parts)

        # 跳过顶层排除目录
        if rel_parts and rel_parts[0] in EXCLUDE_DIRS:
            continue

        # 计算相对路径
        rel_dir = root_path.relative_to(BASE)
        target_dir = app_root / rel_dir if str(rel_dir) != "." else app_root
        target_dir.mkdir(parents=True, exist_ok=True)

        for fname in files:
            src = root_path / fname
            # 完整相对路径用于判断
            full_parts = rel_parts + (fname,)
            if should_skip(src, full_parts):
                continue
            dst = target_dir / fname
            try:
                shutil.copy2(src, dst)
                copied += 1
                total_size += src.stat().st_size
            except Exception as e:
                print(f"    [WARN] 跳过 {src}: {e}")

    print(f"  复制 {copied} 个文件, 共 {total_size/1024/1024:.1f} MB")


def step5_create_launcher(app_root: Path):
    """5. 创建启动器脚本"""
    print("\n[5/6] 创建启动器...")

    # 启动器：用嵌入式 Python 启动 main.py
    launcher = app_root / "launch_portable.bat"
    launcher.write_text(
        '@echo off\r\n'
        'chcp 65001 >nul 2>&1\r\n'
        f'title {APP_NAME}\r\n'
        'cd /d "%~dp0"\r\n'
        '"python\\python.exe" main.py %*\r\n'
        'if errorlevel 1 (\r\n'
        '  echo.\r\n'
        '  echo [ERROR] Application exited with errors.\r\n'
        '  pause\r\n'
        ')\r\n',
        encoding="utf-8",
    )
    print(f"  创建: {launcher.name}")

    # SimLife 后端启动器
    simlife_launcher = app_root / "launch_simlife.bat"
    simlife_launcher.write_text(
        '@echo off\r\n'
        'chcp 65001 >nul 2>&1\r\n'
        'title SimLife Backend\r\n'
        'cd /d "%~dp0"\r\n'
        '"python\\python.exe" -m simlife.backend.main %*\r\n'
        'if errorlevel 1 pause\r\n',
        encoding="utf-8",
    )
    print(f"  创建: {simlife_launcher.name}")

    # 首次安装后安装可选依赖的脚本
    install_optional = app_root / "install_optional.bat"
    install_optional.write_text(
        '@echo off\r\n'
        'chcp 65001 >nul 2>&1\r\n'
        'title 安装可选依赖\r\n'
        'cd /d "%~dp0"\r\n'
        'echo ========================================\r\n'
        'echo   安装可选扩展依赖\r\n'
        'echo ========================================\r\n'
        'echo.\r\n'
        'echo 如果你的网络较好，可以运行原始 install.bat 联网安装。\r\n'
        'echo 此脚本用于在便携版中重新安装失败的依赖。\r\n'
        'echo.\r\n'
        'python\\python.exe -m pip install --upgrade pip\r\n'
        'python\\python.exe -m pip install -r requirements.txt\r\n'
        'echo.\r\n'
        'echo 完成！\r\n'
        'pause\r\n',
        encoding="utf-8",
    )
    print(f"  创建: {install_optional.name}")


def step6_build_nsis(app_root: Path, py_dir: Path):
    """6. 生成 NSIS 安装程序"""
    print("\n[6/6] 生成 NSIS 安装程序...")

    nsis_exe = _find_nsis()
    if not nsis_exe:
        print("  [ERROR] 未找到 makensis.exe")
        print("          请安装 NSIS: https://nsis.sourceforge.io/Download")
        print("          默认路径: C:\\Program Files (x86)\\NSIS")
        return False

    print(f"  NSIS: {nsis_exe}")

    # 把 python 目录复制到 app_root/python
    print("  复制 Python 环境到打包目录...")
    py_target = app_root / "python"
    if py_target.exists():
        shutil.rmtree(py_target)
    shutil.copytree(py_dir, py_target)

    # 生成 NSIS 脚本
    nsi_path = BUILD_DIR / "installer.nsi"
    _write_nsis_script(nsi_path, app_root)
    print(f"  NSIS 脚本: {nsi_path}")

    # 调用 makensis
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    print("  调用 makensis 编译...")
    result = subprocess.run(
        [nsis_exe, str(nsi_path)],
        cwd=str(BUILD_DIR),
        capture_output=True,
        text=True,
        encoding="gbk",
        errors="replace",
    )
    if result.returncode != 0:
        print(f"  [ERROR] makensis 失败:")
        print(result.stdout[-2000:])
        print(result.stderr[-1000:])
        return False

    # 输出文件
    out = DIST_DIR / f"{APP_NAME}-Setup.exe"
    if out.exists():
        size = out.stat().st_size / 1024 / 1024
        print(f"\n[OK] 打包成功！")
        print(f"  安装包: {out}")
        print(f"  大小: {size:.1f} MB")
        return True
    else:
        print(f"  [ERROR] 输出文件未找到: {out}")
        print(result.stdout[-2000:])
        return False


def _write_nsis_script(nsi_path: Path, app_root: Path):
    """生成 NSIS 脚本"""
    # 计算相对路径收集的所有文件
    files指令 = []

    # 递归收集文件
    def collect(dir_path: Path, prefix: str = ""):
        for item in sorted(dir_path.iterdir()):
            if item.is_file():
                rel = str(item.relative_to(app_root))
                files指令.append(f'  File "${{SOURCE_DIR}}\\{rel}"')
            elif item.is_dir():
                collect(item, prefix)

    # 用通配符更简单
    nsi_content = f"""; NSIS 安装脚本 - 自动生成
; 由 build_installer.py 生成

!define APP_NAME "{APP_NAME}"
!define APP_VERSION "{APP_VERSION}"
!define APP_PUBLISHER "{APP_PUBLISHER}"
!define SOURCE_DIR "{app_root}"

; ── 基本配置 ──
Name "${{APP_NAME}}"
OutFile "{DIST_DIR}\\${{APP_NAME}}-Setup.exe"
InstallDir "$LOCALAPPDATA\\${{APP_NAME}}"
InstallDirRegKey HKCU "Software\\${{APP_NAME}}" "InstallDir"
RequestExecutionLevel user
ShowInstDetails show
ShowUnInstDetails show
SetCompressor /SOLID lzma
Unicode True

; ── 现代界面 ──
!include "MUI2.nsh"
!include "LogicLib.nsh"

!define MUI_ABORTWARNING
!define MUI_ICON "${{NSISDIR}}\\Contrib\\Graphics\\Icons\\modern-install.ico"
!define MUI_UNICON "${{NSISDIR}}\\Contrib\\Graphics\\Icons\\modern-uninstall.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "${{NSISDIR}}\\Contrib\\Graphics\\Wizard\\win.bmp"

; 页面
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; 卸载页面
!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

; 语言
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

; ── 版本信息 ──
VIProductVersion "{APP_VERSION}"
VIAddVersionKey "ProductName" "${{APP_NAME}}"
VIAddVersionKey "CompanyName" "${{APP_PUBLISHER}}"
VIAddVersionKey "FileVersion" "${{APP_VERSION}}"
VIAddVersionKey "ProductVersion" "${{APP_VERSION}}"

; ── 安装段 ──
Section "MainSection" SecMain
  SetOutPath "$INSTDIR"
  
  ; 复制所有文件
  File /r "${{SOURCE_DIR}}\\*.*"
  
  ; 创建启动器
  SetOutPath "$INSTDIR"
  
  ; 写注册表
  WriteRegStr HKCU "Software\\${{APP_NAME}}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\\${{APP_NAME}}" "Version" "${{APP_VERSION}}"
  
  ; 卸载信息
  WriteUninstaller "$INSTDIR\\Uninstall.exe"
  
  ; 开始菜单快捷方式
  CreateDirectory "$SMPROGRAMS\\${{APP_NAME}}"
  CreateShortCut "$SMPROGRAMS\\${{APP_NAME}}\\${{APP_NAME}}.lnk" "$INSTDIR\\launch_portable.bat" "" "$INSTDIR\\launch_portable.bat" 0
  CreateShortCut "$SMPROGRAMS\\${{APP_NAME}}\\SimLife后端.lnk" "$INSTDIR\\launch_simlife.bat" "" "$INSTDIR\\launch_simlife.bat" 0
  CreateShortCut "$SMPROGRAMS\\${{APP_NAME}}\\卸载.lnk" "$INSTDIR\\Uninstall.exe" "" "$INSTDIR\\Uninstall.exe" 0
  
  ; 桌面快捷方式
  CreateShortCut "$DESKTOP\\${{APP_NAME}}.lnk" "$INSTDIR\\launch_portable.bat" "" "$INSTDIR\\launch_portable.bat" 0
  
  ; 详细信息
  DetailPrint "安装完成！"
  DetailPrint "安装位置: $INSTDIR"
  DetailPrint "启动: 双击桌面快捷方式或开始菜单中的 ${{APP_NAME}}"
SectionEnd

; ── 卸载段 ──
Section "Uninstall"
  ; 删除安装目录（保留用户数据）
  RMDir /r "$INSTDIR\\engine"
  RMDir /r "$INSTDIR\\ui"
  RMDir /r "$INSTDIR\\desktop"
  RMDir /r "$INSTDIR\\simlife"
  RMDir /r "$INSTDIR\\vrm_module"
  RMDir /r "$INSTDIR\\web"
  RMDir /r "$INSTDIR\\data"
  RMDir /r "$INSTDIR\\python"
  Delete "$INSTDIR\\*.py"
  Delete "$INSTDIR\\*.bat"
  Delete "$INSTDIR\\*.txt"
  Delete "$INSTDIR\\*.md"
  Delete "$INSTDIR\\*.json"
  Delete "$INSTDIR\\Uninstall.exe"
  
  ; 删除快捷方式
  Delete "$DESKTOP\\${{APP_NAME}}.lnk"
  RMDir /r "$SMPROGRAMS\\${{APP_NAME}}"
  
  ; 删除注册表
  DeleteRegKey HKCU "Software\\${{APP_NAME}}"
  
  DetailPrint "卸载完成"
SectionEnd
"""
    nsi_path.write_text(nsi_content, encoding="gbk")


# ── 主流程 ────────────────────────────────────────────
def main():
    print("=" * 60)
    print(f"  {APP_NAME} v{APP_VERSION} 安装包打包工具")
    print(f"  嵌入式 Python {PYTHON_VERSION} (amd64)")
    print("=" * 60)

    # 检查 NSIS
    if not _find_nsis():
        print("\n[ERROR] 未找到 NSIS (makensis.exe)")
        print("        请安装: https://nsis.sourceforge.io/Download")
        print("        默认路径: C:\\Program Files (x86)\\NSIS")
        return 1

    try:
        step1_prepare_dirs()
        py_dir, py_exe, from_cache = step2_download_python()
        step3_install_deps(py_exe, py_dir, from_cache)

        # 准备应用根目录
        app_root = BUILD_DIR / "app"
        app_root.mkdir(parents=True, exist_ok=True)
        step4_collect_project(app_root)
        step5_create_launcher(app_root)
        ok = step6_build_nsis(app_root, py_dir)

        if ok:
            print("\n" + "=" * 60)
            print("  打包完成！")
            print(f"  安装包位于: {DIST_DIR}\\{APP_NAME}-Setup.exe")
            print("=" * 60)
            return 0
        else:
            print("\n[X] 打包失败")
            return 1
    except Exception as e:
        import traceback
        print(f"\n[X] 异常: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
