# 開發環境筆記

這份筆記記錄容易因 Windows、Git 或本機環境差異反覆發生的問題。修改啟動器、文件產生器或本機執行流程前，先查閱本文件。

## Windows 批次檔必須保留 CRLF

### 症狀

在 Windows 重新點擊 `scripts/start_streamlit.bat` 後，沒有正常啟動頁面，命令列可能出現以下類似錯誤：

```text
'...\\scripts\\.."' is not recognized as an internal or external command
'streamlit_app.py"' is not recognized as an internal or external command
'http:' is not recognized as an internal or external command
```

### 根因

Windows `cmd.exe` 解析批次檔時，LF-only 換行可能造成包含引號、`for`、括號與長 PowerShell 命令的行被錯誤切分。這不是 Streamlit、虛擬環境或瀏覽器本身的問題。

### 永久修正

- `scripts/start_streamlit.bat` 使用 UTF-8、CRLF 換行。
- `.gitattributes` 已設定 `*.bat text eol=crlf`，避免 Git checkout 或工具改寫成 LF。
- 啟動器仍以 repository-local `.venv\\Scripts\\python.exe` 執行，並等待 `/_stcore/health` 成功後才開啟瀏覽器。

### 修改後驗證

在 repository 根目錄執行：

```powershell
git check-attr -a -- scripts/start_streamlit.bat
cmd.exe /d /c scripts\\start_streamlit.bat
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8501/_stcore/health
```

預期結果：`git check-attr` 顯示 `eol: crlf`，批次檔正常結束，health endpoint 回傳 HTTP 200 且內容為 `ok`。若失敗，先保留命令列錯誤輸出，再檢查 `.venv\\Scripts\\python.exe`、`app/streamlit_app.py` 與 8501 port；不要直接終止不屬於本 repository 的程序。

### 維護注意事項

修改 `.bat` 後，提交前確認工作樹中的檔案仍含 `0D 0A` 換行；可用 PowerShell `Format-Hex` 檢查。若使用會將文字檔統一成 LF 的編輯器，儲存後必須重新套用 CRLF 並重跑上述啟動驗證。
