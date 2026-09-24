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

有兩個獨立的 Windows 編碼風險：

1. Windows `cmd.exe` 解析批次檔時，LF-only 換行可能造成包含引號、`for`、括號與長 PowerShell 命令的行被錯誤切分。
2. Windows 終端機若使用非 UTF-8 code page，批次檔中的中文會被錯誤解碼；`start` 的視窗標題因此可能顯示成亂碼。這不是 Streamlit、虛擬環境或瀏覽器本身的問題。

### 永久修正

- `scripts/start_streamlit.bat` 使用 UTF-8、CRLF 換行。
- 批次檔的 `echo` 與 `start` 視窗標題使用 ASCII `Taiwan Fire Law RAG`，避免受終端機 code page 影響；中文產品名稱仍由 Streamlit 前端與文件顯示。
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

修改 `.bat` 後，提交前確認工作樹中的檔案仍含 `0D 0A` 換行，且不要把中文放回 `echo` 或 `start` 的標題參數；可用 PowerShell `Format-Hex` 檢查。若使用會將文字檔統一成 LF 的編輯器，儲存後必須重新套用 CRLF 並重跑上述啟動驗證。

## 2026-09-16：終端機分頁標題中文亂碼

截圖曾顯示啟動器分頁標題中的中文變成問號與亂碼，但同一畫面的 Streamlit URL 與英文啟動訊息正常。排查後確認是 Windows 終端機 code page 與 UTF-8 批次檔內容不一致；修正為 ASCII console/title 字串後即可避免此類顯示問題。瀏覽器中的 Streamlit 頁面仍應以 UTF-8 顯示繁體中文，若頁面本身亂碼，才另行檢查 Python/HTML response encoding。

## 2026-09-16：全庫文字編碼檢查結果

- 已檢查 58 個受版本控制的文字檔（Python、批次檔、Markdown、JSON、TOML、YAML、HTML 等），均可用 UTF-8 解碼，沒有 BOM 或 Unicode replacement character。
- repository 既有部分文字檔混用 LF/CRLF；除 Windows `.bat` 外，不要因單一終端機問題任意重整全庫換行，以免產生無關 diff。
- 前端中文應由 UTF-8 的 Python/Markdown 與產生器輸出；批次檔只在終端機輸出 ASCII，中文品牌顯示責任交給瀏覽器與文件。

## 2026-09-16：bundled runtime 無法直接轉圖 DOCX

文件技能的 `render_docx.py` 需要 bundled LibreOffice `soffice.exe`，但目前 workspace dependencies 未提供 LibreOffice，且工具會回報 `LibreOffice soffice.exe was not found on PATH`。依專案規則，不應改用使用者自行安裝的桌面 LibreOffice，也不要為例行驗證安裝系統軟體。

目前的可重現替代驗證為：使用 bundled Python 執行 `scripts\build_frontend_user_guide.py --format all`，以同一份 Markdown 與產生器建立 DOCX/PDF；對 PDF 的每一頁使用 bundled Poppler 轉成 PNG 並逐頁目視檢查，同時以 `python-docx` 與 ZIP 測試檢查 DOCX 段落、表格、內嵌圖片及 OOXML 壓縮檔完整性。若未來 workspace dependencies 提供 bundled LibreOffice，再恢復 `render_docx.py` 的直接 DOCX 視覺驗證，不要每次重新搜尋或嘗試使用系統版 `soffice.exe`。

## 2026-09-24：新增跨模組符號後必須重啟 Streamlit

Streamlit 的「Rerun」可重載主頁程式，但已載入的專案模組可能仍保留在 Python process 的 module cache。若 `app/streamlit_app.py` 改為匯入 `app/rerank.py`、`app/search.py` 等模組中新加入的函式，僅按畫面上的 Rerun 可能出現 `ImportError: cannot import name ...`，即使離線 pytest 與新的 Python process 已通過。

遇到此情況，應先確認 8501 port 的擁有者確實是本 repository 的 Python／Streamlit 開發程序，再精確終止該 PID，使用 repository-local `.venv\Scripts\python.exe` 重新啟動 Streamlit，並檢查 `http://127.0.0.1:8501/_stcore/health` 回傳 `200 ok`。不要終止名稱相同但未監聽本專案 port 的其他 Python process，也不要把模組快取造成的首次 ImportError誤判成新程式碼不存在。

## 2026-09-24：venv 的監聽子程序可能顯示為系統 Python

### 症狀與根因

重新雙擊 `scripts/start_streamlit.bat` 時，畫面顯示 8501 被「不相關程序」占用後立即結束，但 `/_stcore/health` 實際仍回傳 `200 ok`。Windows venv 啟動 Streamlit 時，父程序的 executable/command line 會指向 repository-local `.venv\Scripts\python.exe`，實際監聽 8501 的子程序卻可能顯示為系統 Python，且命令列只保留相對路徑 `app/streamlit_app.py`。只檢查監聽 PID 本身，便無法看見 repository 絕對路徑而誤判。

### 修正與安全邊界

啟動器會從監聽 PID 向上檢查最多四層父程序；只有某一層命令列同時包含本 repository 絕對路徑與 `streamlit` 時，才以該匹配祖先 PID 為目標終止整棵程序樹。若有限父鏈中找不到安全匹配，仍視為其他應用程式占用並拒絕終止。驗證時應確認輸出含 `Stopped old NFA Streamlit process tree PID ...`、launcher exit code 為 0，且 health endpoint 回傳 `200 ok`。

## 2026-09-24：受限代理造成 Ollama Cloud 假性斷線

### 症狀與根因

若從 Codex／測試工具的受限 shell 啟動 Streamlit，程序可能繼承僅供隔離網路使用的 `HTTP_PROXY`、`HTTPS_PROXY` 或 `ALL_PROXY`；目前觀察到的阻擋值為 `http://127.0.0.1:9`。此時本機 `http://127.0.0.1:11434` 仍正常，但 `gemma4:31b-cloud` 對 `https://ollama.com/api/chat` 的請求會回報 `ConnectError`。這不是 token 上限、模型不存在或 API key 驗證失敗。

### 正確驗證方式

- 不要在受限 shell 內清除代理變數以繞過隔離；應使用已核准的一般主機環境執行 `scripts\start_streamlit.bat`，或由使用者直接雙擊啟動。
- 重啟後先確認 `/_stcore/health` 回傳 `200 ok`，再以極小的 Ollama Cloud 請求驗證實際模型端點；不要只用首頁可開啟來推論外網正常。
- 診斷時只記錄代理是否存在、端點與例外類型，不得輸出 `OLLAMA_API_KEY`。若一般主機環境仍失敗，再依序檢查 DNS、TLS、防火牆、代理設定與 key 權限。
