from pathlib import Path

LAUNCHER = Path(__file__).parents[1] / "scripts" / "start_streamlit.bat"


def test_windows_launcher_uses_repository_venv_and_loopback_url() -> None:
    text = LAUNCHER.read_text(encoding="utf-8")

    assert 'set "REPO_DIR=%~dp0.."' in text
    assert 'set "PYTHON=%REPO_DIR%\\.venv\\Scripts\\python.exe"' in text
    assert "--server.address 127.0.0.1" in text
    assert "--server.headless true" in text
    assert 'start "" "%URL%"' in text
    assert "netstat -ano" in text
    assert "Get-CimInstance Win32_Process" in text
    assert "$current.ParentProcessId" in text
    assert "$depth -lt 4" in text
    assert "taskkill.exe" in text
    assert "@('/PID', [string]$matchedPid, '/T', '/F')" in text
    assert "/_stcore/health" in text


def test_windows_launcher_does_not_install_or_crawl() -> None:
    text = LAUNCHER.read_text(encoding="utf-8").lower()

    assert "pip install" in text
    assert "streamlit run" in text
    assert "crawl" not in text
