# NFA Fire Law RAG

可執行的「內政部消防署消防預防調查法令」知識庫（目前 Phase 2 / v0.2）：

`crawler → 法規條文解析 → SQLite + FTS5 + NumPy → Hybrid Search → FastAPI → MCP`

預設來源：

- `https://law.nfa.gov.tw/MOBILE/category.aspx?typecode=A002`

> 注意：Phase 2 開發環境仍無法直接解析 `law.nfa.gov.tw` DNS。此版已依目前公開索引可確認的 NFA legacy URL/列印頁格式校正 `LSID` identity、print view 與 parser，並新增不需 DB 的 live probe。第一次在可連線環境執行時，先跑 `python -m app.cli probe --max-laws 3`，再進行完整 ingest。

## 特色

- A002 分類頁自動探索法規連結，不預先寫死法規清單。
- Phase 2：以 `LSID` 作為穩定法規 identity，忽略 `LSID/lsid` 大小寫與不同 `ldate`，避免同一法規重複入庫。
- Phase 2：對有 `LSID` 的法規優先抓 `GNFA/FLAW/PrintFLAWDAT02.aspx` 完整列印版，失敗再 fallback 原始 detail URL。
- 尊重網站：單執行緒、預設 1.2 秒節流、timeout/retry、固定 User-Agent。
- 依 `第X條` / `一、二、...` 法規結構切 chunk，不用一般固定 token 粗切。
- Semantic `SHA-256` 內容指紋：只雜湊穩定法規內容，排除「列印時間／頁尾」等動態 chrome；未變更法規不重做 embedding，變更時保留舊版本。
- SQLite default：單一 `data/nfa_fire_law.db` 檔案，不需要 Docker、WSL、資料庫服務或管理員權限。
- FTS5 lexical retrieval + NumPy cosine vector retrieval，先以 FTS5 篩選候選，再融合 hybrid score。
- PostgreSQL + `pgvector` + `pg_trgm` 保留為可選 backend，不影響 SQLite 預設流程。
- 無 API key 也能跑：預設 deterministic character n-gram hash embedding (384 維)。
- 可切換 OpenAI `text-embedding-3-small` 並要求 384 維，資料表不用修改。
- FastAPI 查詢 API。
- MCP stdio server，供 ChatGPT/Codex/MCP client 使用。

## 1. 快速啟動

需求：Python 3.11+。預設不需要 Docker、WSL、PostgreSQL 或管理員權限。

```bash
cp .env.example .env
python -m pip install -e '.[dev]'
python -m app.cli init-db
```

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

### OpenAI Embedding

```dotenv
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=384
```

切換 embedding provider 後，請重建/重新 embedding 全部 chunk，避免向量空間混用。SQLite 可刪除資料檔後重新初始化；若使用 Docker/PG，則可用：

```bash
Remove-Item -Recurse -Force data
python -m app.cli init-db
python -m app.cli crawl
```

## 5. MCP

MCP server 使用 stdio transport：

```bash
python -m app.mcp_server
```

提供工具：

- `search_fire_law(query, top_k=8, law_title=None)`
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

## 6. 資料模型

- `laws`：法規 identity、名稱、來源 URL。
- `law_versions`：每次內容變更的完整版本、hash、抓取時間、是否現行。
- `law_chunks`：以條文/行政規則點次切分，SQLite 保存 float32 embedding BLOB；PostgreSQL 保存 pgvector。
- `law_chunks_fts`：SQLite FTS5 現行版本索引，另以 CJK character n-grams 提升中文查詢命中。

版本策略：同一 `source_key` 若 hash 不變 → `unchanged`；hash 變更 → 舊版 `is_current=false`、新增新版並重新 embedding。

## 7. API 安全提醒

`/v1/admin/crawl` 在 PoC 沒加認證；若部署到公開網路，應先加 API key / reverse proxy auth，或只允許內網。PostgreSQL 預設帳密 `nfa/nfa` 也只適合本機 PoC。

## 8. Phase 2 retrieval evaluation

完整 ingest 後可跑第一批檢索驗證案例：

```bash
python -m app.cli eval --path eval/phase2_queries.json --top-k 8
```

輸出 `law_hit_rate` 與有指定條號案例的 `article_hit_rate`，並列出每題前 5 筆命中。這組案例是 smoke/evaluation seed，後續應依實際消防業務題庫持續擴充。

## 9. 測試

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

測試 fixture 覆蓋：分類連結探索、`LSID`/`ldate` 去重、NFA print URL、真實舊版列印頁格式、章節/條號切分、metadata 擷取、列印時間不影響 semantic hash、hash embedding deterministic，以及 SQLite schema/FTS5/hybrid search。

## 10. 下一版建議

1. 在可直接連線 `law.nfa.gov.tw` 的環境執行 live probe，保存真正 A002 HTML fixture，再把 selector regression test 鎖定。
2. 支援 PDF/ODT/DOCX 附件抽取與附件法規關聯。
3. 增加法規版本 diff API / MCP tool。
4. 加 reranker（例如 multilingual cross-encoder）。
5. 增加回答層：強制逐條引用 `法規名稱 + 條號 + source_url`。
6. GitHub Actions 定期 crawl 可改為「在有資料庫與站台可達性的 self-hosted runner」執行，避免公開 runner 對政府網站造成不必要流量。

## 法規與資料使用

本專案只保存公開法規內容與原始來源 URL。實際部署前仍應依消防署網站使用條款/政府資料開放授權規範確認利用方式；回答法律問題時應顯示原始法源與版本日期，重大個案仍以主管機關正式解釋為準。
