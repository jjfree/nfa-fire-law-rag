# 台灣消防法規 RAG

可執行的「台灣消防法規」知識庫（目前 Phase 2 / v0.2）：

完整的系統架構、爬取設計與安裝啟動，請參閱 [`docs/SYSTEM_MANUAL.md`](docs/SYSTEM_MANUAL.md)與 [`output/pdf/nfa-fire-law-rag-system-manual.pdf`](output/pdf/nfa-fire-law-rag-system-manual.pdf)。前端使用者可直接查閱含畫面的 [`docs/FRONTEND_USER_GUIDE.md`](docs/FRONTEND_USER_GUIDE.md)、[`output/docx/nfa-fire-law-rag-frontend-user-guide.docx`](output/docx/nfa-fire-law-rag-frontend-user-guide.docx) 或 [`output/pdf/nfa-fire-law-rag-frontend-user-guide.pdf`](output/pdf/nfa-fire-law-rag-frontend-user-guide.pdf)。文件對齊規範見 [`AGENTS.md`](AGENTS.md)；本 README 保留快速啟動與開發者入口。

`crawler → 法規條文解析 → SQLite + FTS5 + NumPy → Hybrid Search → Ollama/Gemma answer layer → FastAPI → MCP`

預設來源：

- `https://law.nfa.gov.tw/MOBILE/category.aspx?typecode=A002`
- 可用多分類增量同步：`A001` 通用法令、`A002` 預防調查、`A003` 危險物品管理

> 注意：Phase 2 開發環境仍無法直接解析 `law.nfa.gov.tw` DNS。此版已依目前公開索引可確認的舊版 URL/列印頁格式校正 `LSID` identity、print view 與 parser，並新增不需 DB 的 live probe。第一次在可連線環境執行時，先跑 `python -m app.cli probe --max-laws 3`，再進行完整 ingest。

## 特色

- A001/A002/A003 分類頁自動探索法規連結，不預先寫死法規清單。
- Phase 2：以 `LSID` 作為穩定法規 identity，忽略 `LSID/lsid` 大小寫與不同 `ldate`，避免同一法規重複入庫。
- Phase 2：對有 `LSID` 的法規優先抓 `GNFA/FLAW/PrintFLAWDAT02.aspx` 完整列印版，失敗再 fallback 原始 detail URL。
- 尊重網站：單執行緒、預設 2 秒節流、timeout/retry、固定 User-Agent。
- 依 `第X條` / `一、二、...` 法規結構切 chunk，不用一般固定 token 粗切。
- Semantic `SHA-256` 內容指紋：只雜湊穩定法規內容，排除「列印時間／頁尾」等動態 chrome；未變更法規不重做 embedding，變更時保留舊版本。
- 法規 detail page 的同網域 PDF/下載附件會嘗試抽取文字，包含 A003 常見的「附件清單頁 → 實際 PDF」一層連結，作為 `附件：檔名` chunks 一併存入與查詢；掃描型或失敗附件會記錄在 version metadata，不中斷整批 crawl。
- SQLite default：單一 `data/nfa_fire_law.db` 檔案，不需要 Docker、WSL、資料庫服務或管理員權限。
- FTS5 lexical retrieval + NumPy cosine vector retrieval；候選集合會加入查詢中明確提到的法規，並以法規名稱、條號與通用定義句型 rerank。
- PostgreSQL + `pgvector` + `pg_trgm` 保留為可選 backend，不影響 SQLite 預設流程。
- 無 API key 也能跑：預設 deterministic character n-gram hash embedding (384 維)。
- 可切換 OpenAI `text-embedding-3-small` 並要求 384 維，資料表不用修改。
- FastAPI 查詢 API。
- MCP stdio server，供 ChatGPT/Codex/MCP client 使用。
- 可選本機 Ollama/Gemma 生成層：只使用現行檢索片段回答，並驗證引用編號。

## 1. 快速啟動

需求：Python 3.11+。預設不需要 Docker、WSL、PostgreSQL 或管理員權限。Crawler 單執行緒，預設每次 request 間隔 2 秒。

```bash
# PowerShell（Windows 10/11）
Copy-Item .env.example .env
.venv\Scripts\python.exe -m pip install -e '.[dev]'
.venv\Scripts\python.exe -m app.cli init-db
```

若尚未建立虛擬環境，先執行 `python -m venv .venv`；macOS/Linux 可改用
`cp .env.example .env` 與 `python -m ...`。

確認 API：

```bash
curl http://localhost:8000/health
```

Swagger：`http://localhost:8000/docs`

## 2. Phase 2 live probe 與第一次爬取

先做不需要資料庫的真實站台 probe：

```bash
python -m app.cli probe --max-laws 3
```

probe 會回報 `LSID / retrieved_url / chunks / first_article / last_article / metadata / content_hash`，適合先確認 A002 與 detail parser。

確認 probe 正常後，再小量 ingest：

```bash
python -m app.cli crawl --max-laws 3
```

確認結果正常後完整執行：

```bash
python -m app.cli crawl
```

要一次增量同步 A001、A002 與 A003：

```powershell
.venv\Scripts\python.exe -m app.cli crawl --categories A001,A002,A003
```

此命令仍依 `LSID`、版本與 content hash 判斷 unchanged；不變更既有版本，變更才新增 current version、chunks、FTS5 索引與 embedding。專案內的 `.codex/skills/nfa-incremental-crawl/SKILL.md` 也已將「請增量爬取A001/A002/A003」對應到此流程。

完整 crawl 遇到 HTTP 403/429 會立即停止，不會持續重試；若網路政策更嚴格，可在 `.env` 增加 `CRAWL_DELAY_SECONDS`，例如 `5.0`。附件採串流下載，預設受 `MAX_ATTACHMENT_BYTES=25000000`（25 MB）與 `MAX_ATTACHMENT_PAGES=200` 限制；超過大小、頁數、沒有可搜尋文字或非 PDF 的檔案會記錄在回報的 `metadata.attachments.skipped`（含 URL 與原因），不會耗盡本機記憶體。不要用併發方式加速，也不要關閉 TLS 憑證驗證。

也可經 API：

```bash
curl -X POST 'http://localhost:8000/v1/admin/crawl?max_laws=3'
```

### 若 A002 頁面 selector 與 heuristic 不合

先查看 HTML，再在 `.env` 指定：

```dotenv
CATEGORY_LINK_SELECTOR=.your-law-list a
DETAIL_CONTENT_SELECTOR=#your-content
```

重啟 API 後再試。這兩項預設留白，代表自動偵測。

## 3. 查詢

語意 + 文字 hybrid：

```bash
curl --get 'http://localhost:8000/v1/search' \
  --data-urlencode 'q=防火管理人有哪些責任' \
  --data-urlencode 'top_k=8'
```

精確條號：

```bash
curl --get 'http://localhost:8000/v1/article' \
  --data-urlencode 'law_title=消防法' \
  --data-urlencode 'article=第13條'
```

所有法規：

```bash
curl http://localhost:8000/v1/laws
```

版本紀錄：

```bash
curl http://localhost:8000/v1/laws/1/versions
```

每一筆搜尋結果都保留 `law_title / article_label / source_url / version_no`，方便 LLM 引用法源，而不是無來源回答。

## 4. Embedding 模式

### 零金鑰模式（預設）

```dotenv
EMBEDDING_PROVIDER=hash
EMBEDDING_DIM=384
```

這是 character n-gram feature hashing，目的是讓 PoC 完整可執行；品質不等同真正的 multilingual embedding model。
因此 SQLite 預設以 `HASH_VECTOR_WEIGHT=0.30` 限制 hash cosine 的影響，讓可解釋的
法規名稱、中文詞彙與 `本法所稱 X` 等定義訊號主導排序。切換到訓練過的 embedding
provider 時，則使用 `HYBRID_VECTOR_WEIGHT`。`LAW_TITLE_MATCH_BOOST` 可調整明確法規
名稱的 routing 加權。

### OpenAI Embedding

```dotenv
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=384
```

切換 embedding provider 後，請重建/重新 embedding 全部 chunk，避免向量空間混用。
請先備份現有 SQLite 檔，並使用新的 `DATABASE_URL` 或經審核的 re-embedding
流程；本專案的例行操作不刪除既有 `data/` 資料。若使用 Docker/PG，則仍屬選配開發路徑：

```powershell
$env:DATABASE_URL = "sqlite:///./data/nfa_fire_law_openai.db"
.venv\Scripts\python.exe -m app.cli init-db
.venv\Scripts\python.exe -m app.cli crawl --max-laws 3
```

### 本機 Gemma 問答

預設回答模型為 `gemma4:31b-cloud`。請先在 `.env` 設定 `OLLAMA_API_KEY`；Ollama
cloud model 不需要下載 31B 權重，並需有 Ollama 帳號登入。若要使用本機模型，仍可：

```powershell
ollama pull gemma4:e2b
ollama run gemma4:e4b
```

接著使用回答接口；`/v1/search` 仍保留為原始檢索／除錯接口：

```powershell
curl --get 'http://localhost:8000/v1/ask' `
  --data-urlencode 'q=請說明消防設備人員包含哪些?' `
  --data-urlencode 'top_k=8'
```

回答層只把本機檢索找到的現行法規片段交給模型，要求以 `[1]`、`[2]`
等證據編號引用；若 Ollama 不可用或模型輸出沒有有效引用，系統會保留原文證據，
不會把未驗證的生成文字當成答案。可在 `.env` 調整 `LLM_BASE_URL`、`LLM_MODEL`、
`LLM_TIMEOUT_SECONDS`、`LLM_TEMPERATURE`、`LLM_THINK` 與 `LLM_MAX_OUTPUT_TOKENS`。
遇到角色比較或權限／業務範圍問題時，回答入口會先取較大的 hybrid 候選集，再由
固定的 `gemma4:31b-cloud` 只重新排列候選條文，避免真正分配職務的條文被大量「僅提到
角色名稱」的條文擠出前 8 筆。原始 `/v1/search` 不使用此步驟，仍可用來檢查原始
檢索分數。此功能可用 `RERANKER_ENABLED` 關閉，並可調整 `RERANKER_MODEL`、
`RERANKER_CANDIDATE_LIMIT`、`RERANKER_TIMEOUT_SECONDS` 與輸出限制；失敗時會安全回退
到原始排序，不會阻斷回答。

對「包含哪些？是否包含 X？」這類複合問題，回答入口會辨識明確查詢對象，保留不同
法規來源及候選集中最相關的母法條文，避免精確命中的少見場所名稱被長問題的通用詞
稀釋。`top_k` 控制本機
RAG 證據數；若另有 Web 補充，其編號會接續在本機結果之後，不計入 `top_k`。
回答證據會先列直接涵蓋明確對象的條文，再列相關母法；這只調整回答證據順序，卡片
顯示的 hybrid/vector/lexical 仍是原始檢索分數，不代表法律位階。

Streamlit 前端會將已驗證的 `[N]` 引用轉成頁內連結，點擊後跳到並展開對應的本機
RAG 條文或 Web 補充證據。證據卡依本機後 Web 的順序排列並顯示相同的 `[N]` 編號與
編號範圍；模型仍只需輸出原本的編號格式。
Streamlit 側邊欄也可在每次查詢時選擇 `gemma4:e2b`（速度優先）或
`gemma4:e4b`（品質優先），或 `gemma4:31b-cloud`（雲端品質優先）；此選擇不會改寫
全域設定。選擇 `gemma4:31b-cloud` 時，不論本機 RAG 是否命中，都會使用該模型；
無命中時會先嘗試取得 web 補充資料。

當本機 RAG 沒有結果或最高 hybrid 分數低於 `WEB_SEARCH_MIN_HYBRID_SCORE`（預設 `0.35`）時，
系統可使用 Ollama hosted web search 作為補充，再由本機 Gemma 彙整回答。搜尋結果
只接受 `.env` 中 `WEB_SEARCH_ALLOWED_DOMAINS` 指定的 HTTPS 官方網域，並排除未包含
問題明確查詢對象的結果；回答 API 會在
`web_results` 回傳標題、來源連結、擷取時間與內容摘要。啟用此功能前，請在本機
`.env` 設定 `OLLAMA_API_KEY`；此 key 同時用於 `gemma4:31b-cloud` 與 web fallback。
未設定時仍可正常使用本機 RAG/LLM，但 cloud/web 功能
會回報 `web_search_status=unavailable`。`/v1/ask` 的 `web_search_status` 也會明確標示
本次是否使用、停用或無法使用 web fallback。

## 5. 本機瀏覽器問答介面（Streamlit）

安裝 UI 選配依賴：

```powershell
.venv\Scripts\python.exe -m pip install -e ".[ui]"
```

啟動本機瀏覽器介面（只綁定 `127.0.0.1`，不直接暴露到區域網路）：

```powershell
.venv\Scripts\python.exe -m streamlit run app/streamlit_app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
```

也可以直接雙擊 `scripts\start_streamlit.bat`。啟動器會檢查專案 `.venv` 與
Streamlit 是否可用，啟動本機服務後自動開啟 `http://127.0.0.1:8501`；首次使用前
仍須先完成上面的 UI 選配依賴安裝。啟動器不會執行爬取或自動安裝套件。

開啟 `http://127.0.0.1:8501` 後，可輸入自然語言問題、選擇法規篩選與結果數。
介面顯示現行版本的條文內容、條號、版本、檢索分數與原始來源 URL；預設不需要
OpenAI API key，也不會把檢索不到的內容編造成法律結論。若已設定 `OLLAMA_API_KEY`，
證據不足時也會顯示允許清單內的官方 web 補充來源。這是本機只讀查詢介面，
尚未加入登入驗證或遠端部署能力。

## 6. MCP

MCP server 使用 stdio transport：

```bash
python -m app.mcp_server
```

提供工具：

- `search_fire_law(query, top_k=8, law_title=None)`
- `ask_fire_law(query, top_k=8, law_title=None)`
- `get_fire_law_article(law_title, article)`
- `list_fire_laws()`
- `list_law_versions(law_id)`

SQLite 預設直接使用專案內的資料檔。若選擇 PostgreSQL，請安裝選配依賴並將 `.env` 改為：

```dotenv
STORAGE_BACKEND=postgres
DATABASE_URL=postgresql+psycopg://nfa:nfa@localhost:5432/nfa_law
```

接著安裝 PostgreSQL backend：

```bash
python -m pip install -e '.[postgres]'
```

`docker-compose.yml` 仍可作為 PostgreSQL/pgvector 的選配開發環境，但不是新 PC 的必要依賴。

一個通用 MCP client 設定概念：

```json
{
  "mcpServers": {
    "nfa-fire-law": {
      "command": "python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "C:/path/to/nfa-fire-law-rag"
    }
  }
}
```

## 7. 資料模型

- `laws`：法規 identity、名稱、來源 URL。
- `law_versions`：每次內容變更的完整版本、hash、抓取時間、是否現行。
- `law_chunks`：以條文/行政規則點次切分，SQLite 保存 float32 embedding BLOB；PostgreSQL 保存 pgvector。
- `law_chunks_fts`：SQLite FTS5 現行版本索引，另以 CJK character n-grams 提升中文查詢命中。

版本策略：同一 `source_key` 若 hash 不變 → `unchanged`；hash 變更 → 舊版 `is_current=false`、新增新版並重新 embedding。

## 8. API 安全提醒

`/v1/admin/crawl` 在 PoC 沒加認證；若部署到公開網路，應先加 API key / reverse proxy auth，或只允許內網。PostgreSQL 預設帳密 `nfa/nfa` 也只適合本機 PoC。

## 9. Phase 2 retrieval evaluation

完整 ingest 後可跑第一批檢索驗證案例：

```bash
python -m app.cli eval --path eval/phase2_queries.json --top-k 8
```

輸出 `law_hit_rate` 與有指定條號案例的 `article_hit_rate`，並列出每題前 5 筆命中。這組案例是 smoke/evaluation seed，後續應依實際消防業務題庫持續擴充。

## 10. 測試

```bash
# Windows PowerShell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
python -m pytest -q

# macOS/Linux: source .venv/bin/activate
```

測試 fixture 覆蓋：分類連結探索、`LSID`/`ldate` 去重、來源站 print URL、真實舊版列印頁格式、章節/條號切分、metadata 擷取、列印時間不影響 semantic hash、hash embedding deterministic，以及 SQLite schema/FTS5/hybrid search；定義檢索另以多個 `本法所稱 X` 案例驗證，不依賴特定名詞硬編碼。

## 11. 下一版建議

1. 在可直接連線 `law.nfa.gov.tw` 的環境執行 live probe，保存真正 A002 HTML fixture，再把 selector regression test 鎖定。
2. 支援 PDF/ODT/DOCX 附件抽取與附件法規關聯。
3. 增加法規版本 diff API / MCP tool。
4. 加 reranker（例如 multilingual cross-encoder）。
5. 擴充回答品質評估：建立 RAG-only、web fallback、法規版本衝突與引用完整性的離線案例集。
6. GitHub Actions 定期 crawl 可改為「在有資料庫與站台可達性的 self-hosted runner」執行，避免公開 runner 對政府網站造成不必要流量。

## 法規與資料使用

本專案只保存公開法規內容與原始來源 URL。實際部署前仍應依來源網站使用條款與政府資料開放授權規範確認利用方式；回答法律問題時應顯示原始法源與版本日期，重大個案仍以主管機關正式解釋為準。
