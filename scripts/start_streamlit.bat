@echo off
setlocal

set "REPO_DIR=%~dp0.."
for %%I in ("%REPO_DIR%") do set "REPO_DIR=%%~fI"
set "PYTHON=%REPO_DIR%\.venv\Scripts\python.exe"
set "APP=%REPO_DIR%\app\streamlit_app.py"
set "PORT=8501"
set "URL=http://127.0.0.1:%PORT%"

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

echo Starting Taiwan Fire Law RAG at %URL% ...
set "NFA_REPO_DIR=%REPO_DIR%"
set "NFA_PORT=%PORT%"

rem Stop only an existing Streamlit process that belongs to this repository.
rem If another application owns the port, fail closed instead of terminating it.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "$repo = [IO.Path]::GetFullPath($env:NFA_REPO_DIR); $blocked = $false; $owners = @(); foreach ($line in @(netstat -ano)) { if ([string]$line -match (':' + $env:NFA_PORT + '.*LISTENING\s+(\d+)')) { $owners += [int]$Matches[1] } }; foreach ($owner in $owners) { $process = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $owner) -ErrorAction SilentlyContinue; $commandLine = [string]$process.CommandLine; if ($commandLine -and ($commandLine -like ('*' + $repo + '*') -and $commandLine -like '*streamlit*')) { Start-Process -FilePath 'taskkill.exe' -ArgumentList @('/PID', [string]$owner, '/T', '/F') -Wait -NoNewWindow; Write-Output ('Stopped old NFA Streamlit process tree PID ' + $owner) } elseif ($owner) { Write-Output ('Port is owned by an unrelated process PID ' + $owner); $blocked = $true } }; if ($blocked) { exit 2 }"
if errorlevel 2 (
    echo [ERROR] Port %PORT% is used by another application; no process was stopped.
    echo Close that application or change PORT in this launcher.
    exit /b 2
)

start "Taiwan Fire Law RAG" /D "%REPO_DIR%" "%PYTHON%" -m streamlit run "%APP%" --server.headless true --server.address 127.0.0.1 --server.port %PORT% --browser.gatherUsageStats false

rem Wait for Streamlit's local health endpoint instead of opening a stale page.
set "READY="
for /l %%N in (1,1,20) do (
    "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri '%URL%/_stcore/health' -TimeoutSec 1 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
    if not errorlevel 1 (
        set "READY=1"
        goto :ready
    )
    ping 127.0.0.1 -n 2 >nul
)

if not defined READY (
    echo [ERROR] Streamlit did not become ready at %URL%.
    exit /b 1
)

:ready
start "" "%URL%"
exit /b 0
