# AGENTS.md

This file provides guidance to Codex when working in this repository.

## Development commands

Conda environment: `localrag` at `/Users/chris/miniconda3/envs/localrag`. Always activate it before Python commands:

```bash
conda activate localrag
```

```bash
# Backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Qdrant only
docker compose up -d

# Qdrant + backend + frontend
docker compose --profile full up --build -d

# Directory ingestion
python ingest.py --input_dir data/engineering --batch_size 64
python ingest.py --input_dir data/engineering --batch_size 32 --collection_name my_collection

# Evaluation
pip install -r requirements-eval.txt
python evaluation/run_retrieval_eval.py \
  --dataset evaluation/datasets/golden_retrieval.example.jsonl \
  --top-k 5 \
  --experiment-name my-experiment
jupyter notebook evaluation/retrieval_eval_pipeline.ipynb

# Backend verification
python -m compileall app evaluation
python -m unittest discover tests/

# Frontend
cd frontend && npm ci
cd frontend && npm run dev
cd frontend && npm test
cd frontend && npm run lint
cd frontend && npm run build

# Repository checks
docker compose config
git diff --check
```

Copy `.env.example` to `.env` before starting. Configuration is loaded by pydantic-settings; `.env` overrides `app/core/config.py`. Frontend variables are documented in `frontend/.env.example`.

Never commit real API keys, tokens, passwords, or other credentials. Cloud secrets must come only from the ignored `.env` file or process environment. Source defaults and example files must remain safe. If a secret was committed, revoke it and rewrite Git history; deleting it in a later commit is insufficient.

### Reindex rules

The ingestion pipeline fingerprint includes collection, embedding endpoint/model/revision, chunk size/overlap, and splitter version.

- Content or fingerprint change triggers versioned reingestion automatically.
- A different embedding dimension cannot share an existing collection; use a new collection or clear the old one first.
- If only Qdrant was manually cleared while content and fingerprint stayed identical, also remove `data/ingestion_state.db`, otherwise the authoritative registry correctly reports the version as current.

```bash
python scripts/clear_qdrant.py
rm -f data/ingestion_state.db
```

## Architecture

### Backend

- `app/main.py` — FastAPI app, configurable CORS, request IDs, optional `X-API-Key`, route registration and conversation-memory worker lifecycle.
- `app/api/health.py` — `GET /health` liveness and `GET /health/ready` dependency readiness.
- `app/api/documents.py` — streamed single/batch uploads, optional folder `relative_paths` manifest, duplicate-path rejection, bounded parallel batch ingestion, per-file failure isolation, list, delete-by-ID/source compatibility and safe error mapping.
- `app/api/rag.py` — synchronous JSON query and SSE stream; `TOP_K` comes from settings and SSE status payloads expose factual phase state/timing/metadata.
- `app/api/conversations.py` — list/detail/delete conversation APIs with generic 500 responses.
- `app/services/rag_service.py` — full orchestration: server memory, interactive-inference priority, routing, configured dense/BM25/hybrid retrieval, optional rerank, context planning, sync/stream generation, factual running/completed/skipped/warning SSE events, synchronous completed-exchange persistence and best-effort trace scheduling.
- `app/services/ingestion_service.py` — single/batch upload adapter for the unified ingestion pipeline; validates/preserves logical relative paths, applies configured batch/concurrency limits and returns stable identity/status without exposing the server storage path.
- `app/services/document_service.py` — stable-ID document lifecycle; ambiguous source deletion returns 409.

### RAG primitives

- `app/rag/loader.py` — PDF, TXT/MD/Markdown, DOCX loaders.
- `app/rag/splitter.py` — Markdown H1/H2/H3-aware split followed by recursive character splitting; recursive splitting for other formats.
- `app/rag/embeddings.py` — cached `OpenAIEmbeddings`; true thread-safe 256-entry LRU keyed by endpoint/model/revision/text SHA-256; client reuse.
- `app/rag/query_processor.py` — Layer 0 regex quick replies; Layer 1 JSON route/intent/rewrite/direct answer with legacy parser; malformed output and exceptions fail open to RAG.
- `app/rag/context_manager.py` — authoritative server memory, client-tail reconciliation, separate pending-compaction complete-turn buffer and recent Sliding Window, count/token-triggered strict schema-v1 rolling summaries with typed outcomes, deterministic prompt budgeting and pair-preserving truncation.
- `app/rag/conversation_store.py` — SQLite WAL store; full messages plus structured summary cursor/schema/revision/token metrics and coalesced durable `conversation_memory_jobs`; exchange/job atomic commit, leases/retries, legacy half-turn cursor repair, schema migration, busy timeout, striped locks and `turn_id` idempotency. Read/delete failures propagate so APIs can distinguish storage errors from empty/404 results.
- `app/rag/memory_worker.py` — process-local single worker for durable rolling-summary jobs; startup backfill, lease recovery, exponential retry/dead state, graceful stop and user-query-aware admission.
- `app/rag/bm25.py` — shared Qdrant `qdrant/bm25` document/query construction; multilingual tokenizer and language configuration must remain identical at ingest and query time.
- `app/rag/vectorstore.py` / `retriever.py` — cached Qdrant access plus backward-compatible dense, BM25-only and dense+BM25 RRF/DBSF retrieval; Hybrid collections use named dense/sparse vectors while legacy collections keep unnamed dense vectors.
- `app/rag/reranker.py` — explicit `RerankCandidate(document, retrieval_score)` contract with a backward `vector_score` alias; NoOp, Cross-Encoder and legacy keyword Fusion; safe first-stage fallback.
- `app/rag/prompt.py` / `chain.py` — untrusted-memory/context boundaries and LCEL sync/async generation.
- `app/rag/query_logger.py` — thread-safe JSONL query traces with conversation/turn/routing/stage timings.
- `app/core/background_tasks.py` — bounded fixed worker executor, queue backpressure and graceful shutdown.
- `app/core/inference_coordinator.py` — tracks active interactive requests and admits new background summary inference only while the user path is idle.

### Ingestion

- `app/rag/ingestion/checksum_store.py` — authoritative SQLite `document_registry`, atomic version activation, durable predecessor-cleanup queue, stable collection-scoped IDs and legacy migration.
- `app/rag/ingestion/batch_embedder.py` — OpenAI-compatible embedding requests through a process-wide bounded executor; validates response indexes and restores original batch/chunk order.
- `app/rag/ingestion/bulk_writer.py` — metadata/count/dense-sparse schema validation, deterministic versioned point IDs, synchronous batched upsert, optional same-point named dense + BM25 sparse vectors, exact version/ID deletes, document listing.
- `app/rag/ingestion/ingest_pipeline.py` — scan → identity/version → load/split → embed → new Qdrant version → atomic registry activation/cleanup enqueue → idempotent predecessor cleanup; explicit upload batches can use bounded independent-document workers while the outer lifecycle lock remains held; exact rollback, pending-cleanup retry, legacy upload adoption and safe removed-file reconciliation.
- `app/utils/file_utils.py` — async-offloaded bounded upload writes/content checks, UUID storage, extension/content/relative-path validation and deletion restricted to `data/raw`.

Standalone upload identity is the normalized original filename. Folder upload identity is the normalized browser relative path, so `backend/README.md` and `frontend/README.md` remain distinct while reuploading the same relative path replaces that logical document. Relative paths are metadata/identity only; bytes remain under UUID names in `data/raw`. Directory CLI identity is the canonical path. Qdrant and SQLite do not share a transaction; the code writes the new Qdrant version first, atomically activates it with a durable SQLite cleanup record, then retries predecessor cleanup. This is a local saga, not distributed ACID.

### Frontend

- `frontend/src/App.jsx` — single-page chat/upload/document/conversation UI; recursive folder drop/picker with accepted/ignored previews; cancellable SSE rendering with a live factual pipeline timeline and nonfatal persistence warning state; document-level Source tags instead of visible score piles; accurate indexed/up-to-date upload states; client history tail; `@rag`; stable-ID deletion.
- `frontend/src/folderUpload.js` — asynchronous File System Access/WebKit directory traversal, extension/system-file filtering and relative-path duplicate detection.
- `frontend/src/streamPresentation.js` — stable phase updates including warnings, failed-stage marking, elapsed-time extraction and chunk-to-document Source tag grouping.
- `frontend/src/api.js` — configurable `VITE_API_BASE_URL`, optional API key, sequential 20-file multipart upload batches with relative-path manifests, Axios JSON calls and abortable fetch/SSE reader.
- `frontend/src/App.css` — Editorial Ink component styles and CJK/Markdown rendering; assistant Markdown uses normal whitespace flow while user text and code blocks preserve intentional formatting.
- `frontend/src/index.css` — reset, texture and local system font stack; no runtime Google Fonts dependency.
- `frontend/.dockerignore` — excludes local Vite env files, dependencies and build output from the frontend image context.
- `frontend/Dockerfile` / `frontend/nginx.conf` — multi-stage production build and SPA serving.

The frontend remains a large single component. Do not claim it has already been componentized.

### Evaluation

- `evaluation/run_retrieval_eval.py` — production retriever runner; compares dense/BM25/hybrid modes and records index schema, fusion/prefetch and BM25 configuration in the `retrieval-eval-v1` provenance alongside `metric_semantics_version=evidence-label-v2`, dataset hash and Git state.
- `evaluation/retrieval_metrics/matching.py` — stable evidence labels; unmatched gold remains in the denominator.
- `evaluation/retrieval_metrics/evaluator.py` — evidence-level Recall/Precision/MRR/NDCG while preserving original ranks; chunk-level context quality.
- `evaluation/retrieval_eval_pipeline.ipynb` — deterministic demo/live analysis and multi-experiment comparison; LIVE Rerank records attempted/applied/fallback, DEMO disables Rerank, primary metrics use only top K, and comparison rejects incompatible provenance.
- `evaluation/datasets/golden_retrieval.example.jsonl` — 22 annotated examples.
- Notebook runtime packages (`pandas`, `matplotlib`, `seaborn`, `jupyter`, `nbconvert`) are pinned in optional `requirements-eval.txt`; the backend image installs only `requirements.txt`.

Historical reports without `metric_semantics_version=evidence-label-v2` are not comparable to current results. Do not cite their scores as current evidence.

### Infrastructure and tests

- Qdrant is pinned to `qdrant/qdrant:v1.18.2` in Compose. Hybrid rollout must use a new collection with `RETRIEVAL_INDEX_SCHEMA=hybrid`; do not point that schema at the legacy unnamed-vector collection.
- The full Compose profile uses `host.docker.internal` for host-local LLM/embedding services.
- Root and frontend-specific `.dockerignore` files keep local env files and tool configuration out of Docker build contexts.
- Python runtime/evaluation packages in `requirements.txt` / `requirements-eval.txt` and frontend packages in `package-lock.json` are version-pinned inputs.
- `.github/workflows/ci.yml` runs Python 3.11 tests plus Node 22 frontend logic tests, lint and build.
- Current offline suite: 206 Python unittest cases plus 10 Node frontend tests. They mock external boundaries and do not prove real model/Qdrant/browser/load behavior.

## Dev log habit

After every completed coding task (bug fix, feature, refactor), generate a structured DevLog in `logs/` named `DevLog-YYYY-MM-DD-简短描述.md`.

Use `logs/DevLog-2025-04-30-文档管理API.md` as the structural reference. Include date, tags, overview, changed files, API design, implementation details, dependencies, verification, edge cases and impact analysis. The `.continue/rules/dev-log.md` rule also applies.

## AGENTS.md maintenance

After every code change except log-only changes, update this file to reflect endpoints, dependencies, responsibilities, architecture and test count. Stale architecture guidance is worse than none.

## 校招准备文档维护

`校招准备.md` is the user's on-demand campus-recruiting study guide. Do not update it as routine maintenance.

Only update or rebuild it when the user explicitly asks to update, refresh, rewrite or regenerate the “校招准备” file. When triggered:

1. Read all `logs/DevLog-*.md` files and `logs/项目说明与进度.md`.
2. Inspect current code and configuration; clearly distinguish superseded history from current behavior.
3. Keep it detailed, beginner-friendly, interview-oriented and easy to memorize.
4. Cover purpose, architecture, data flows, module responsibilities, iteration timeline, decisions, tradeoffs, failures/fallbacks, evaluation semantics/results, limitations, roadmap, high-frequency questions, oral versions and revision checklists.
5. Never present aspirations, historical bugs or old evaluation numbers as current capability.
