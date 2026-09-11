# NFA Fire Law RAG

第一版可執行的「內政部消防署消防預防調查法令」知識庫：

`crawler → 法規條文解析 → PostgreSQL/pgvector → Hybrid Search → FastAPI → MCP`

預設來源：

- `https://law.nfa.gov.tw/MOBILE/category.aspx?typecode=A002`

> 注意：建立此版本時，開發環境無法解析 `law.nfa.gov.tw` DNS，因此沒有把網站 CSS selector 寫死。Crawler 以同網域連結探索與法規名稱/URL heuristic 為主，並提供 `.env` selector override。第一次在可連線環境執行時，建議先用 `--max-laws 3` 驗證實際站台結構。

## 特色

- A002 分類頁自動探索法規連結，不預先寫死法規清單。
- 尊重網站：單執行緒、預設 1.2 秒節流、timeout/retry、固定 User-Agent。
- 依 `第X條` / `一、二、...` 法規結構切 chunk，不用一般固定 token 粗切。
- `SHA-256` 內容指紋：未變更法規不重做 embedding；變更時保留舊版本。
- PostgreSQL + `pgvector` + `pg_trgm`。
- Hybrid Retrieval：cosine vector score + 中文 trigram lexical score。
- 無 API key 也能跑：預設 deterministic character n-gram hash embedding (384 維)。
- 可切換 OpenAI `text-embedding-3-small` 並要求 384 維，資料表不用修改。
- FastAPI 查詢 API。
- MCP stdio server，供 ChatGPT/Codex/MCP client 使用。

## 1. 快速啟動

需求：Docker Desktop / Docker Compose。

```bash
cp .env.example .env
docker compose up -d --build
```

確認 API：

```bash
curl http://localhost:8000/health
```

Swagger：`http://localhost:8000/docs`

## 2. 第一次爬取

建議先小量驗證：

```bash
docker compose exec api python -m app.cli crawl --max-laws 3
```

確認結果正常後完整執行：

```bash
docker compose exec api python -m app.cli crawl
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

切換 embedding provider 後，請重建/重新 embedding 全部 chunk，避免向量空間混用。PoC 最簡單做法：

```bash
docker compose down -v
docker compose up -d --build
docker compose exec api python -m app.cli crawl
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

若 MCP client 在主機執行，而 PostgreSQL 在 Docker，請將 `.env` 的 DB host 改成 `localhost`：

```dotenv
DATABASE_URL=postgresql+psycopg://nfa:nfa@localhost:5432/nfa_law
```

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
- `law_chunks`：以條文/行政規則點次切分，保存 vector。

版本策略：同一 `source_key` 若 hash 不變 → `unchanged`；hash 變更 → 舊版 `is_current=false`、新增新版並重新 embedding。

## 7. API 安全提醒

`/v1/admin/crawl` 在 PoC 沒加認證；若部署到公開網路，應先加 API key / reverse proxy auth，或只允許內網。PostgreSQL 預設帳密 `nfa/nfa` 也只適合本機 PoC。

## 8. 測試

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

測試 fixture 覆蓋：分類連結探索、法規條號切分、metadata 擷取、hash embedding deterministic。

## 9. 下一版建議

1. 在實際可連線的台灣網路環境保存 A002 HTML fixture，針對真實 DOM 加 selector regression test。
2. 支援 PDF/ODT/DOCX 附件抽取與附件法規關聯。
3. 增加法規版本 diff API / MCP tool。
4. 加 reranker（例如 multilingual cross-encoder）。
5. 增加回答層：強制逐條引用 `法規名稱 + 條號 + source_url`。
6. GitHub Actions 定期 crawl 可改為「在有資料庫與站台可達性的 self-hosted runner」執行，避免公開 runner 對政府網站造成不必要流量。

## 法規與資料使用

本專案只保存公開法規內容與原始來源 URL。實際部署前仍應依消防署網站使用條款/政府資料開放授權規範確認利用方式；回答法律問題時應顯示原始法源與版本日期，重大個案仍以主管機關正式解釋為準。
