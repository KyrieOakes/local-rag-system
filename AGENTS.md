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

- `app/main.py` — FastAPI app, configurable CORS, request IDs, optional `X-API-Key`, route registration.
- `app/api/health.py` — `GET /health` liveness and `GET /health/ready` dependency readiness.
- `app/api/documents.py` — streamed single/batch uploads, list, delete-by-ID/source compatibility, safe error mapping.
- `app/api/rag.py` — synchronous JSON query and SSE stream; `TOP_K` comes from settings.
- `app/api/conversations.py` — list/detail/delete conversation APIs with generic 500 responses.
- `app/services/rag_service.py` — full orchestration: server memory, routing, retrieval, optional rerank, context planning, sync/stream generation, completed-answer side effects.
- `app/services/ingestion_service.py` — upload adapter for the unified ingestion pipeline; returns stable identity/status without exposing the server storage path.
- `app/services/document_service.py` — stable-ID document lifecycle; ambiguous source deletion returns 409.

### RAG primitives

- `app/rag/loader.py` — PDF, TXT/MD/Markdown, DOCX loaders.
- `app/rag/splitter.py` — Markdown H1/H2/H3-aware split followed by recursive character splitting; recursive splitting for other formats.
- `app/rag/embeddings.py` — cached `OpenAIEmbeddings`; true thread-safe 256-entry LRU keyed by endpoint/model/revision/text SHA-256; client reuse.
- `app/rag/query_processor.py` — Layer 0 regex quick replies; Layer 1 JSON route/intent/rewrite/direct answer with legacy parser; malformed output and exceptions fail open to RAG.
- `app/rag/context_manager.py` — authoritative server memory, client-tail reconciliation, rolling summaries, deterministic token budgeting and truncation.
- `app/rag/conversation_store.py` — SQLite WAL store; full messages plus summary cursor; schema migration, busy timeout, striped locks and `turn_id` idempotency. Read/delete failures propagate so APIs can distinguish storage errors from empty/404 results.
- `app/rag/vectorstore.py` / `retriever.py` — cached Qdrant wrapper and `similarity_search_with_score`.
- `app/rag/reranker.py` — explicit `RerankCandidate(document, vector_score)` contract; NoOp, Cross-Encoder and Hybrid Fusion; safe vector fallback.
- `app/rag/prompt.py` / `chain.py` — untrusted-memory/context boundaries and LCEL sync/async generation.
- `app/rag/query_logger.py` — thread-safe JSONL query traces with conversation/turn/routing/stage timings.
- `app/core/background_tasks.py` — bounded fixed worker executor, queue backpressure and graceful shutdown.

### Ingestion

- `app/rag/ingestion/checksum_store.py` — authoritative SQLite `document_registry`, atomic version activation, durable predecessor-cleanup queue, stable collection-scoped IDs and legacy migration.
- `app/rag/ingestion/batch_embedder.py` — OpenAI-compatible batch embeddings.
- `app/rag/ingestion/bulk_writer.py` — metadata/count/dimension validation, deterministic versioned point IDs, synchronous batched upsert, exact version/ID deletes, document listing.
- `app/rag/ingestion/ingest_pipeline.py` — scan → identity/version → load/split → embed → new Qdrant version → atomic registry activation/cleanup enqueue → idempotent predecessor cleanup; exact rollback, pending-cleanup retry, legacy upload adoption and safe removed-file reconciliation.
- `app/utils/file_utils.py` — streamed bounded uploads, UUID storage, extension/content validation, deletion restricted to `data/raw`.

Upload identity is the normalized original filename, so reuploading the same name replaces that logical upload. Directory identity is the canonical path. Qdrant and SQLite do not share a transaction; the code writes the new Qdrant version first, atomically activates it with a durable SQLite cleanup record, then retries predecessor cleanup. This is a local saga, not distributed ACID.

### Frontend

- `frontend/src/App.jsx` — single-page chat/upload/document/conversation UI; cancellable SSE rendering; accurate indexed/up-to-date upload states; client history tail for persistence reconciliation; `@rag`; stable-ID deletion.
- `frontend/src/api.js` — configurable `VITE_API_BASE_URL`, optional API key, Axios JSON calls and abortable fetch/SSE reader.
- `frontend/src/App.css` — Editorial Ink component styles and CJK/Markdown rendering.
- `frontend/src/index.css` — reset, texture and local system font stack; no runtime Google Fonts dependency.
- `frontend/.dockerignore` — excludes local Vite env files, dependencies and build output from the frontend image context.
- `frontend/Dockerfile` / `frontend/nginx.conf` — multi-stage production build and SPA serving.

The frontend remains a large single component. Do not claim it has already been componentized.

### Evaluation

- `evaluation/run_retrieval_eval.py` — production retriever runner; `retrieval-eval-v1` report shape with `metric_semantics_version=evidence-label-v2`, dataset hash, Git state, settings snapshot and fingerprint.
- `evaluation/retrieval_metrics/matching.py` — stable evidence labels; unmatched gold remains in the denominator.
- `evaluation/retrieval_metrics/evaluator.py` — evidence-level Recall/Precision/MRR/NDCG while preserving original ranks; chunk-level context quality.
- `evaluation/retrieval_eval_pipeline.ipynb` — deterministic demo/live analysis and multi-experiment comparison; LIVE Rerank records attempted/applied/fallback, DEMO disables Rerank, primary metrics use only top K, and comparison rejects incompatible provenance.
- `evaluation/datasets/golden_retrieval.example.jsonl` — 22 annotated examples.
- Notebook runtime packages (`pandas`, `matplotlib`, `seaborn`, `jupyter`, `nbconvert`) are pinned in optional `requirements-eval.txt`; the backend image installs only `requirements.txt`.

Historical reports without `metric_semantics_version=evidence-label-v2` are not comparable to current results. Do not cite their scores as current evidence.

### Infrastructure and tests

- Qdrant is pinned to `qdrant/qdrant:v1.18.2` in Compose.
- The full Compose profile uses `host.docker.internal` for host-local LLM/embedding services.
- Root and frontend-specific `.dockerignore` files keep local env files and tool configuration out of Docker build contexts.
- Python runtime/evaluation packages in `requirements.txt` / `requirements-eval.txt` and frontend packages in `package-lock.json` are version-pinned inputs.
- `.github/workflows/ci.yml` runs Python 3.11 tests plus Node 22 lint/build.
- Current offline suite: 160 unittest cases. They mock external boundaries and do not prove real model/Qdrant/browser/load behavior.

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
