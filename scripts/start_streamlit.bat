@echo off
setlocal

set "REPO_DIR=%~dp0.."
for %%I in ("%REPO_DIR%") do set "REPO_DIR=%%~fI"
set "PYTHON=%REPO_DIR%\.venv\Scripts\python.exe"
set "APP=%REPO_DIR%\app\streamlit_app.py"
set "URL=http://127.0.0.1:8501"

if not exist "%PYTHON%" (
    echo [ERROR] Repository virtual environment not found:
    echo         %PYTHON%
    echo Run: python -m venv "%REPO_DIR%\.venv"
    exit /b 1
)

if not exist "%APP%" (
    echo [ERROR] Streamlit app not found:
    echo         %APP%
    exit /b 1
)

"%PYTHON%" -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Streamlit is not installed in the repository virtual environment.
    echo Run: "%PYTHON%" -m pip install -e ".[ui]"
    exit /b 1
)

echo Starting NFA Fire Law RAG at %URL% ...
start "NFA Fire Law RAG" /D "%REPO_DIR%" "%PYTHON%" -m streamlit run "%APP%" --server.headless true --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
timeout /t 2 /nobreak >nul
start "" "%URL%"
exit /b 0
