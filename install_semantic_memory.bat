@echo off
rem ============================================================
rem  Install Semantic Vector Memory
rem  (sentence-transformers library + MiniLM model weights)
rem  Uses China mirror endpoints for faster/successful download.
rem
rem  安装语义向量记忆
rem  - library: Tsinghua PyPI mirror
rem  - model:   hf-mirror.com (HuggingFace China mirror)
rem ============================================================
title Install Semantic Vector Memory

setlocal enabledelayedexpansion

:: ---- 1. Find Python ----
set "PYTHON_CMD="
where python >nul 2>&1 && set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
    where python3 >nul 2>&1 && set "PYTHON_CMD=python3"
)
if not defined PYTHON_CMD (
    where py >nul 2>&1 && set "PYTHON_CMD=py"
)
if not defined PYTHON_CMD (
    echo.
    echo [ERROR] Python was not found in PATH.
    echo         Install Python from https://www.python.org/downloads/
    echo         and check "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Python found: %PYTHON_CMD%
echo ============================================================

:: ---- 2. Install sentence-transformers from Tsinghua mirror ----
echo.
echo [1/3] Installing sentence-transformers (Tsinghua mirror)...
echo       This pulls in torch (~2GB), please be patient...
%PYTHON_CMD% -m pip install sentence-transformers numpy -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install sentence-transformers.
    echo         Check your network, then run this script again.
    echo         Alternative mirror: -i https://mirrors.aliyun.com/pypi/simple/
    echo.
    pause
    exit /b 1
)
echo [OK] Library installed.

:: ---- 3. Download model weights via hf-mirror.com ----
echo.
echo [2/3] Downloading model weights from hf-mirror.com (~500MB)...
echo       URL: https://hf-mirror.com/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
echo       Please wait for the download progress bar to finish...
set "HF_ENDPOINT=https://hf-mirror.com"
%PYTHON_CMD% -c "from sentence_transformers import SentenceTransformer; m=SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2'); print('  Model loaded | vector dim:', len(m.encode('hello test')))"
if errorlevel 1 (
    echo.
    echo [WARN] Model download may have failed.
    echo       - Mirror unreachable? Try again later.
    echo       - If it hangs, press Ctrl+C, then re-run.
    echo       - Manual test:  HF_ENDPOINT=https://hf-mirror.com python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"
    echo.
    pause
    exit /b 1
)
echo [OK] Model weights downloaded.

:: ---- 4. Verify offline (pure local) loading ----
echo.
echo [3/3] Verifying offline loading (local_files_only)...
%PYTHON_CMD% -c "from sentence_transformers import SentenceTransformer; m=SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2', local_files_only=True); print('  Offline OK | dim:', len(m.encode('test')))"
if errorlevel 1 (
    echo [WARN] Offline verification failed, but model files may still be valid.
) else (
    echo [OK] Offline loading verified.
)

echo.
echo ============================================================
echo   Done! Semantic vector memory is fully ready.
echo   The app will now use real semantic search (dim=384).
echo ============================================================
echo.
pause