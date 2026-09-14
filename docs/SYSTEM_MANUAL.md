# NFA Fire Law RAG 系統說明書

本說明書說明 NFA Fire Law RAG 的系統架構、法規爬取與版本化設計、檢索與回答流程、安裝啟動方式，以及 Streamlit 前端操作。預設目標是 Windows 10/11 的本機 SQLite 執行環境；Docker、WSL、PostgreSQL 與 pgvector 仍保留為選配相容路徑，不是一般使用的必要條件。

文件版本：2026-09-14

適用版本：Phase 2 / v0.2.x

主要資料來源：內政部消防署法令查詢系統 `law.nfa.gov.tw`

## 1. 系統定位與使用邊界

本系統將消防相關公開法規抓取、解析、版本保存、索引與檢索整合成可查詢的本機知識庫。回答介面會保留法規名稱、條號或段落標籤、版本號與來源 URL，讓使用者能回到原始法源核對。

系統是法規檢索與證據整理工具，不取代主管機關正式解釋、行政處分或個案法律意見。若檢索證據不足，回答層應顯示資料不足，不應以模型記憶補齊法律結論。

目前支援的 NFA 分類為：

- `A001` 通用法令
- `A002` 預防調查
- `A003` 危險物品管理

## 2. 整體架構

```mermaid
flowchart LR
    NFA[NFA 分類頁與法規頁] --> D[Discovery<br/>同網域連結探索]
    D --> F[Fetcher<br/>TLS 節流 重試 403/429 停止]
    F --> P[Parser<br/>清理 metadata 條文切 chunk]
    F --> A[Attachment<br/>同網域 PDF 一層展開]
    P --> I[Version-aware Ingest<br/>LSID + content hash]
    A --> I
    I --> DB[(SQLite<br/>laws / versions / chunks)]
    DB --> X[FTS5<br/>CJK n-gram lexical index]
    DB --> V[NumPy<br/>float32 embeddings]
    X --> S[Hybrid Search]
    V --> S
    S --> R[Optional reranker]
    R --> Q[Evidence-grounded answer]
    Q --> UI[Streamlit UI]
    Q --> API[FastAPI]
    Q --> MCP[MCP stdio]
```

### 2.1 元件與程式位置

| 元件 | 程式位置 | 職責 |
|---|---|---|
| 設定 | `app/config.py`, `.env.example` | 來源網址、資料庫、embedding、LLM、web fallback 與 API 設定 |
| 分類與連結探索 | `app/crawler/categories.py`, `discovery.py` | 解析 A001/A002/A003 分類頁，篩選同網域法規 detail URL |
| HTTP 抓取 | `app/crawler/fetch.py` | TLS 驗證、User-Agent、節流、timeout、有限重試與封鎖停止 |
| NFA URL 正規化 | `app/crawler/nfa_urls.py` | 擷取 `LSID`、建立穩定法規 identity、組合列印版 URL |
| HTML/PDF 解析 | `app/parser.py`, `app/attachments.py` | 清除頁面雜訊、擷取 metadata、切割條文與附件文字 |
| 入庫與版本 | `app/ingest.py` | unchanged/inserted 判斷、保留歷史版本、寫入 embedding 與 FTS5 |
| 資料庫 | `app/db.py`, `app/models.py` | SQLite schema、交易、foreign key、FTS5、embedding bytes |
| 檢索 | `app/search.py`, `app/embedding.py`, `app/rerank.py` | lexical + vector hybrid、條號與定義訊號、條件式 rerank |
| 回答 | `app/answer.py`, `app/web_search.py` | 只依證據生成、驗證引用、必要時使用官方網域 web fallback |
| API/MCP | `app/api.py`, `app/mcp_server.py` | HTTP API 與 stdio MCP 工具 |
| 前端 | `app/streamlit_app.py`, `app/conversations.py` | 本機問答、對話保存、證據展開與引用定位 |

### 2.2 預設執行模式

預設使用單一 SQLite 檔案 `data/nfa_fire_law.db`，不需要資料庫服務。法規 embedding 預設為 384 維 deterministic character n-gram hash，適合離線 PoC 與無金鑰啟動；它不是訓練好的多語言語意模型。若切換到 OpenAI embedding，必須重新建立所有 chunk 的向量，不能混用不同向量空間。

Ollama/Gemma 是回答層，不是檢索層的必要條件。Ollama 不可用時，仍可使用原始檢索、條文證據與 API；回答層會回報無法產生可驗證引用的狀態。

## 3. 爬取設計重點

### 3.1 探索與來源驗證

1. 從分類頁探索法規連結，不預先寫死法規清單。
2. 只接受與 `NFA_ALLOWED_HOST` 相同的 HTTP/HTTPS host，拒絕外部網址。
3. 排除導覽、列印、新聞、錨點、JavaScript、mailto 與標示為廢止的項目。
4. 以 `LSID` 作為穩定 identity，忽略 `LSID/lsid` 大小寫與歷史 `ldate` 差異。
5. 有 `LSID` 時優先使用 `GNFA/FLAW/PrintFLAWDAT02.aspx` 列印版，失敗才回到原始 detail URL；`Law.source_url` 仍保存人員可辨識的原始法規 URL。

### 3.2 抓取邊界與禮貌策略

- 單執行緒執行，預設 request 間隔 2 秒，可由 `CRAWL_DELAY_SECONDS` 調高。
- 啟用作業系統信任憑證鏈的 TLS 驗證，不應為了抓取方便關閉憑證檢查。
- 網路 timeout 預設 20 秒，網路錯誤最多重試 3 次；HTTP 403 或 429 立即停止整批 crawl，不持續加壓。
- 附件以串流下載，預設上限 25 MB、最多 200 頁；超過大小、頁數、非 PDF 或沒有可搜尋文字的附件會記錄原因並跳過。
- 附件只允許同網域來源，支援「附件清單頁 -> 實際 PDF」一層展開，不把任意頁面變成無限爬蟲圖。

### 3.3 解析、chunk 與 hash

Parser 會清除列印時間、頁尾、導覽與系統提示等動態 chrome，再擷取法規名稱、發布/施行/修正日期、主管機關與法規狀態。正式法規以 `第 X 條` 切割；行政規則或附件則可依 `一、二、...` 或阿拉伯數字項次切割。每個 chunk 保存順序、條號或項次、標題與完整文字。

`content_hash` 只對穩定的法規內容與重要 metadata 計算 SHA-256，刻意排除每次抓取都會變動的列印時間。因此同一法規內容未變更時不會重複新增版本，也不會重做 embedding。

### 3.4 增量版本策略

| 情況 | 入庫結果 |
|---|---|
| 找不到相同 `source_key` | 建立 `Law`、版本 1、chunks、embedding 與 FTS5 |
| 相同 identity 且 `content_hash` 不變 | 回報 `unchanged`，保留原 current version |
| 相同 identity 但內容變更 | 舊版 `is_current=false`，新增 version_no、chunks、embedding，更新 FTS5 |
| 單一附件失敗 | 保存錯誤/跳過原因到 version metadata，不中斷其他法規 |

一般更新先做小量 probe，再做 `--max-laws` 小量 crawl，確認結果後才執行完整增量同步。例行測試不得對真實 local database 做 destructive setup，也不應在未確認網站可達性時直接完整 crawl。

## 4. 資料模型與可追溯性

| 資料表 | 主要內容 |
|---|---|
| `laws` | 穩定 `source_key`、法規名稱、分類、原始來源 URL |
| `law_versions` | 版本號、content hash、完整 raw text、metadata、current 狀態、抓取時間 |
| `law_chunks` | version 關聯、seq、條號、標題、chunk 內容、float32 embedding |
| `law_chunks_fts` | SQLite FTS5 lexical index，只重建現行版本，並保存 chunk/law/version 對照欄位 |
| `conversations` | Streamlit 本機對話標題與時間 |
| `conversation_messages` | 使用者問題、助手輸出與完整 response JSON |

所有回答面向的結果至少應帶出：法規名稱、條號/段落標籤、版本號、原始來源 URL。`version_no` 是系統保留版本的序號；真正法律效力仍應回到來源頁面的發布、施行或修正日期核對。

## 5. 檢索與回答流程

### 5.1 Hybrid search

SQLite 檢索先以 FTS5 取得候選，再以 NumPy 計算 embedding cosine similarity，並融合文字重疊、法規名稱 routing、明確條號與「本法所稱 X」定義句型訊號。中文查詢使用 character n-gram，避免只依賴空格分詞。預設 hash embedding 的 vector weight 為 0.30，讓可解釋的法律詞彙訊號優先。

`/v1/search` 與 MCP `search_fire_law` 提供原始檢索排序；`/v1/ask`、MCP `ask_fire_law` 與 Streamlit 問答可對角色比較、權限或業務範圍問題取得較大候選集，再由設定的 Gemma 進行條件式重排。重排失敗會安全回退原始排序。

### 5.2 證據回答與 web fallback

回答 prompt 只會收到現行本機檢索片段，並要求每個重要法律主張附 `[1]`、`[2]` 等證據編號。系統會拒絕不存在或完全缺少的引用；此時保留原始條文給使用者核對，不把未驗證文字當作可靠法律答案。

當本機無命中、最高 hybrid 分數低於 `WEB_SEARCH_MIN_HYBRID_SCORE`，或模型明確表示證據不足時，可選擇啟用 Ollama hosted web search。web 結果只接受 `.env` 的 HTTPS 官方網域清單，且會標示為「官方網頁補充資料」與擷取時間；不能默默覆蓋或合併本機現行法規。

## 6. 安裝與啟動

以下以 Windows PowerShell 為主。指令應在 repository 根目錄執行。

### 6.1 前置條件

- Windows 10/11
- Python 3.11 以上，建議使用 repository 內的 `.venv`
- 可連線 NFA 網站的環境，只有 probe/crawl 需要外部網路
- 不需要 Docker、WSL、PostgreSQL 或系統管理員權限

### 6.2 建立環境與安裝

```powershell
python --version
python -m venv .venv
Copy-Item .env.example .env
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e ".[dev,ui]"
```

`.env` 是本機設定檔，不可提交 Git。初次使用可先維持預設的 SQLite、hash embedding；若要使用 OpenAI embedding 或 Ollama Cloud，才填入對應金鑰。API 與 UI 預設應綁定 loopback 使用，公開部署前必須先補認證與反向代理控管。

### 6.3 初始化資料庫與確認 API

```powershell
.venv\Scripts\python.exe -m app.cli init-db
.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

另開一個 PowerShell 視窗確認：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Start-Process http://127.0.0.1:8000/docs
```

API 要長駐執行時，請保留該視窗；停止可按 `Ctrl+C`。`/v1/admin/crawl` 目前沒有登入認證，只適合本機或受控內網使用。

### 6.4 首次 probe 與增量爬取

```powershell
.venv\Scripts\python.exe -m app.cli probe --max-laws 3
.venv\Scripts\python.exe -m app.cli crawl --categories A001,A002,A003 --max-laws 3
```

小量結果正常後，再執行：

```powershell
.venv\Scripts\python.exe -m app.cli crawl --categories A001,A002,A003
```

單一分類也可使用：

```powershell
.venv\Scripts\python.exe -m app.cli crawl --max-laws 3
```

`probe` 不需資料庫與 embedding，會回報 `LSID`、retrieved URL、chunk 數、首末條號、metadata、content hash 與附件 URL，適合先確認站台格式。`crawl` 是增量操作，未變更法規不會建立新版本。

### 6.5 啟動 Streamlit 前端

方法一：雙擊 `scripts\start_streamlit.bat`。啟動器會檢查 `.venv` 與 Streamlit，確認 `8501` port，僅停止本 repository 自己留下的舊 Streamlit process，等待 health endpoint 後開啟瀏覽器。

方法二：PowerShell 手動啟動：

```powershell
.venv\Scripts\python.exe -m streamlit run app/streamlit_app.py `
  --server.headless true `
  --server.address 127.0.0.1 `
  --server.port 8501 `
  --browser.gatherUsageStats false
```

開啟 `http://127.0.0.1:8501`。若只使用 UI，仍建議先完成 `init-db` 與至少一次 crawl；UI 啟動時會自動初始化 schema，但不會自動爬取法規。

### 6.6 API、MCP 與評估入口

常用 API：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/v1/laws"
Invoke-RestMethod "http://127.0.0.1:8000/v1/search?q=防火管理人有哪些責任&top_k=8"
Invoke-RestMethod "http://127.0.0.1:8000/v1/article?law_title=消防法&article=第13條"
```

MCP 使用 stdio；在 MCP client 設定中以 repository 內的 Python 啟動：

```json
{
  "mcpServers": {
    "nfa-fire-law": {
      "command": "C:\\path\\to\\nfa-fire-law-rag\\.venv\\Scripts\\python.exe",
      "args": ["-m", "app.mcp_server"],
      "cwd": "C:\\path\\to\\nfa-fire-law-rag"
    }
  }
}
```

提供的 MCP 工具為 `search_fire_law`、`ask_fire_law`、`get_fire_law_article`、`list_fire_laws`、`list_law_versions`。檢索 smoke test：

```powershell
.venv\Scripts\python.exe -m app.cli eval --path eval/phase2_queries.json --top-k 8
```

## 7. Streamlit 前端操作說明

### 7.1 側邊欄

- **對話列表**：選擇既有對話；對話會保存於本機 SQLite，重啟後仍可查看。
- **新增對話**：建立空白對話。
- **... 選單**：修改對話標題或刪除對話。刪除會移除該對話及其訊息，不會刪除法規資料。
- **顯示結果數**：控制顯示 1 至 20 筆檢索證據。
- **法規篩選**：選擇全部法規或限定某一法規名稱。
- **回答模型**：`gemma4:e2b` 偏速度、`gemma4:e4b` 偏完整、`gemma4:31b-cloud` 偏雲端品質；這是當次查詢選擇，不會改寫全域設定。

### 7.2 問答與證據

在底部輸入自然語言問題，例如「消防法第13條對管理權人有什麼要求？」。回答區會依序顯示：模型回答或資料不足提示、本機檢索摘要、現行法規證據卡片，以及必要時的 web 補充來源。

證據卡片標示法規名稱、條號、標題、版本與 hybrid/vector/lexical 分數。點擊卡片可展開原文；點擊回答中的 `[N]` 引用會跳到並展開對應證據。**分數是排序訊號，不是法律效力。**

若看到「RAG 證據不足」提示，應優先改用更具體的法規名稱、條號、角色或動作詞，再檢查原始來源。web fallback 若無金鑰、無結果或連線失敗，介面仍會顯示本機檢索結果與狀態，不會假裝已完成外部查詢。

### 7.3 建議提問方式

- 具體指定法規名稱與條號：`消防法第13條管理權人義務`
- 問定義時指出名詞：`消防法所稱管理權人是什麼`
- 問責任時指出動作：`防火管理人應負哪些責任`
- 比較不同角色時說明比較面向：`管理權人與防火管理人的設置及責任有何不同`

## 8. 設定與故障排除

| 現象 | 優先檢查 |
|---|---|
| `ModuleNotFoundError` | 是否使用 `.venv\Scripts\python.exe`，以及是否已安裝 `-e ".[dev,ui]"` |
| UI 顯示沒有資料 | 確認 `DATABASE_URL`、執行 `init-db`，再做 probe/crawl |
| NFA DNS/連線失敗 | 先只做 `probe --max-laws 3`；確認網路政策與 `NFA_ALLOWED_HOST`，不要直接完整 crawl |
| HTTP 403/429 | 依程式停止，稍後再試並提高 `CRAWL_DELAY_SECONDS`，不要增加併發或重試壓力 |
| Ollama 回答失敗 | 先使用 `/v1/search` 或查看證據；確認 Ollama URL、模型與金鑰。檢索本身不依賴 Ollama |
| Cloud/web fallback 不可用 | 確認 `OLLAMA_API_KEY`、允許網域與 HTTPS；未設定時屬預期的 unavailable 狀態 |
| Streamlit port 被占用 | 關閉占用 `8501` 的應用程式，或修改啟動命令的 port；不要任意終止不相關 process |
| 切換 embedding provider | 使用新的 `DATABASE_URL` 或受控 re-embedding 流程，先備份 SQLite，避免混用向量 |

## 9. 文件維護與變更紀錄

本手冊負責說明系統如何使用；後續程式異動的文件責任、對齊矩陣與交付檢查表，統一依 repository 根目錄的 [`AGENTS.md`](../AGENTS.md) 第 17 節執行。採影響範圍驅動的方式維護文件：只有影響操作、資料契約、來源規則、執行方式、資安邊界或驗證方式的變更，才需要同步受影響文件。PDF 是本手冊的列印與分享版本，由 `scripts/build_system_manual_pdf.py` 產生，不直接手工編輯。

| 日期 | 內容 |
|---|---|
| 2026-09-14 | 建立本系統說明書，納入架構、爬取設計、安裝啟動與 Streamlit 操作 |
| 2026-09-14 | 將文件對齊規範移至 `AGENTS.md` 第 17 節，保留本手冊的維護入口 |
| 2026-09-14 | 建立由 Markdown 產生的易讀 PDF 版本；後續異動須重新產製並檢查 PDF |
