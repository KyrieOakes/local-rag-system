# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development commands

Conda environment: `localrag` at `/Users/chris/miniconda3/envs/localrag`. Always activate it before running Python commands:

```bash
conda activate localrag
```

```bash
# Backend (from repo root, with conda env activated)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Batch ingest local directories
python ingest.py --input_dir data/engineering --batch_size 64
python ingest.py --input_dir data/engineering --batch_size 32 --collection_name my_collection

# Qdrant vector database
docker compose up -d

# Frontend (from frontend/)
cd frontend && npm run dev       # Vite dev server on :5173
cd frontend && npm run build     # production build
cd frontend && npm run lint      # ESLint

# Python dependencies (if adding new ones)
pip install -r requirements.txt
```

Copy `.env.example` to `.env` before starting. The backend reads configuration from `.env` via pydantic-settings — `.env` values override defaults in `app/core/config.py`. All modules import the global `settings` singleton.

```bash
# Reset vector DB + checksum store (required when changing embedding/chunking config)
python scripts/clear_qdrant.py && rm -f data/ingestion_state.db

# Evaluation (offline retrieval quality assessment)
python evaluation/run_retrieval_eval.py --dataset evaluation/datasets/golden_retrieval.example.jsonl --top-k 5 --experiment-name my-experiment
python evaluation/run_retrieval_eval.py --dataset ... --top-k 5 --use-reranker --reranker-type cross_encoder --rerank-top-n 20 --experiment-name rerank-test
jupyter notebook evaluation/retrieval_eval_pipeline.ipynb   # full pipeline + strategy comparison

# Unit tests
python -m unittest discover tests/
```

## Architecture

**Backend** (`app/`) — FastAPI application with three route modules and a layered RAG pipeline:

- `app/main.py` — App factory, CORS middleware (allows `:5173`), route registration
- `app/api/` — Route handlers: `health.py` (`GET /health`), `documents.py` (`POST /upload`, `POST /upload-batch`, `GET /`, `DELETE /{source}`), `rag.py` (`POST /rag/query` + `POST /rag/query/stream` SSE streaming)
- `app/services/` — Business logic orchestration. `ingestion_service.py` delegates to the unified `ingest_file_paths` pipeline; `rag_service.py` orchestrates the full RAG pipeline with RAG routing gate, conversation context, rerank step (STEP 3.5, conditional on `RERANKER_TYPE`), async logging, and SSE streaming (`query_rag` + `query_rag_stream`); `document_service.py` handles list/delete by querying Qdrant directly
- `ingest.py` — Standalone CLI script at repo root. `python ingest.py --input_dir <dir> --batch_size <n> [--collection_name <name>]`
- `app/rag/` — The RAG pipeline primitives:
  - `loader.py` — Loads PDF (PyPDF), TXT/MD (TextLoader), DOCX (Docx2txtLoader) via LangChain document loaders
  - `splitter.py` — MarkdownHeaderTextSplitter (preserves H1/H2/H3 hierarchy) for .md/.markdown; RecursiveCharacterTextSplitter for all other types
  - `embeddings.py` — `CachedOpenAIEmbeddings` with thread-safe LRU cache (256 entries, MD5-keyed) for repeated query embeddings. Wraps OpenAIEmbeddings pointed at local/cloud embedding server.
  - `query_processor.py` — Two-layer RAG routing gate: **Layer 0** keyword pre-filter (regex-based, catches greetings/thanks/goodbyes/meta-questions with zero LLM cost); **Layer 1** unified LLM call that simultaneously decides `needs_rag`, detects intent, and either rewrites the query for retrieval or generates a direct answer. Accepts conversation history for pronoun resolution.
  - `vectorstore.py` — QdrantVectorStore singleton; also contains `list_all_documents()` and `delete_document_by_source()`
  - `retriever.py` — `similarity_search_with_score` against the vectorstore
  - `reranker.py` — Pluggable reranking module for post-retrieval precision. Abstract `BaseReranker` interface with three implementations: `NoOpReranker` (pass-through), `CrossEncoderReranker` (local sentence-transformers cross-encoder, lazy-loaded), `HybridFusionReranker` (vector + keyword score fusion, no extra model). Factory: `get_reranker()` returns singleton based on `RERANKER_TYPE` config. Workflow: vector search retrieves `RERANKER_CANDIDATE_TOP_N` (e.g. 20), reranker narrows to `RERANKER_FINAL_TOP_K` (e.g. 5). Preserves `vector_score` and `rerank_score` in document metadata. Falls back to vector-only results on model load failure.
  - `chain.py` — Builds a LangChain chain: `rag_prompt | llm | StrOutputParser`. `generate_answer()` for sync; `generate_answer_stream()` async generator for SSE token streaming. Formats conversation history with ~2048 token budget.
  - `prompt.py` — System prompt template with `{history}` and `{context}` placeholders; instructs LLM to write natural flowing prose grounded in context + conversation
  - `query_logger.py` — Writes full query trace to `logs/history/rag_queries.jsonl` + brief terminal summary. Called from background thread (non-blocking).
  - `ingestion/` — Unified batch-ingestion pipeline:
    - `checksum_store.py` — SQLite-based MD5 checksum database for incremental updates
    - `batch_embedder.py` — Batch embedding via OpenAI-compatible `/v1/embeddings` (configurable batch_size)
    - `bulk_writer.py` — Bulk Qdrant `upsert` + auto-create collection if missing (infers vector_size from first embedding) + delete by `metadata.file_path`
    - `ingest_pipeline.py` — Orchestration: scan → checksum classify → load → split → batch embed → bulk upsert
- `app/llm/local_llm.py` — `get_llm()` returns a `ChatOpenAI` instance. `"local"` → local LM Studio/Ollama config; `"cloud"` → cloud API config.
- `app/core/config.py` — `Settings` class loaded from `.env` via pydantic-settings
- `app/schemas/` — Pydantic models: `Message` (role+content for conversation history), `QueryRequest` (question, conversation_id, history, force_rag), `QueryResponse` (question, answer, sources, conversation_id, routing), `SourceChunk`
- `app/utils/file_utils.py` — Validates file extension (`.pdf`, `.txt`, `.md`, `.markdown`, `.docx`), saves to `data/raw/` with UUID filenames

**Frontend** (`frontend/`) — React 19 + Vite, single-page chat UI with "Editorial Ink" dark theme:

- `src/App.jsx` — Entire application in one component (sidebar, chat messages, upload modal, document manager modal). Manages `conversationId` state for multi-turn conversations; builds recent history (last 10 messages) for each request; handles `@rag` prefix to force retrieval mode; renders SSE-streamed tokens in real-time; shows routing badge ("Searched documents" / "Direct response" / "Quick reply") on each assistant message. No router — all UI state managed via `useState`.
- `src/App.css` — Complete design system with CSS custom properties (design tokens for colors, shadows, radii, transitions). Smoked-glass panels, refined typography, subtle ambient light bleeds. Includes `.routing-badge` styles for rag/direct/greeting indicators.
- `src/index.css` — Base reset, grain texture overlay, imports Plus Jakarta Sans (Google Fonts) with weight range 300–800.
- `src/api.js` — Axios instance pointing at `http://127.0.0.1:8000`, exports `healthCheck`, `uploadDocument`, `uploadDocuments`, `queryRag` (with conversationId/history/forceRag params), `queryRagStream` (fetch-based SSE reader with event callbacks), `listDocuments`, `deleteDocument`
- Frontend dependencies include `react-markdown` for rendering LLM Markdown responses

**Evaluation** (`evaluation/`) — Offline retrieval quality assessment:

- `run_retrieval_eval.py` — CLI runner: loads golden JSONL dataset, calls production retriever, outputs `retrieval-eval-v1` JSON report with `settings_snapshot` (chunk_size, embedding_model, etc.)
- `retrieval_eval_pipeline.ipynb` — Jupyter notebook: full test pipeline with 16 visualization charts across two sections:
  - Sections 1–15: Single-experiment pipeline (per-question bar charts, aggregate dashboard, radar chart, top-K sensitivity, correlation heatmap, recall-vs-precision scatter, auto-diagnosis)
  - Section 16: **Multi-experiment strategy comparison** (comparison table with config metadata, core metrics bar chart, context quality chart, radar overlay, recall-vs-precision trade-off, per-question sensitivity heatmap). Auto-loads all reports from `evaluation/results/` and displays `chunk_size`/`embedding_model` from each report's `settings_snapshot`.
  - Supports live mode (real Qdrant + embedding) and demo mode (synthetic data for offline visualization testing)
- `retrieval_metrics/metrics.py` — Core retrieval metrics: Recall@K, Precision@K, MRR, NDCG@K, context_redundancy@K
- `retrieval_metrics/matching.py` — Maps golden source/snippet labels to concrete chunk IDs (file_path, source, text-snippet matching)
- `retrieval_metrics/evaluator.py` — Unified `evaluate_retrieval_case()` producing grouped `core_metrics` + `context_quality`
- `datasets/golden_retrieval.example.jsonl` — 22 annotated question→relevant_sources examples covering 8 topic areas
- Visualization dependencies: `matplotlib`, `seaborn`, `pandas`, `jupyter`, `nbconvert`

**Strategy comparison workflow** (for embedding/chunking/top-k/rerank experiments):
1. Modify `.env` (embedding_model, chunk_size, reranker_type, etc.)
2. For embedding/chunking changes: `python scripts/clear_qdrant.py && rm -f data/ingestion_state.db` — full reset
3. `python ingest.py --input_dir data/engineering --batch_size 64` — re-ingest (skip for rerank-only experiments)
4. `python evaluation/run_retrieval_eval.py --dataset ... --experiment-name <strategy-name> [--use-reranker --reranker-type ...]` — evaluate
5. Repeat 1-4 with different configs, then open notebook → Restart & Run All → scroll to §16

**Rerank experiment matrix** (no re-ingestion needed, just vary CLI args):
```bash
# Baseline (no rerank)
python evaluation/run_retrieval_eval.py --dataset ... --top-k 5 --experiment-name baseline-vector-only

# Cross-Encoder with top-20 candidates
python evaluation/run_retrieval_eval.py --dataset ... --top-k 5 --use-reranker --reranker-type cross_encoder --rerank-top-n 20 --experiment-name rerank-bge-base-top20

# Hybrid fusion (lightweight, no extra model)
python evaluation/run_retrieval_eval.py --dataset ... --top-k 5 --use-reranker --reranker-type hybrid --rerank-top-n 20 --experiment-name rerank-hybrid-top20
```

**Infrastructure:**
- Qdrant runs via Docker Compose, data persisted to `qdrant_storage/`
- All LLM/embedding calls use the OpenAI-compatible API format (works with LM Studio, Ollama, or cloud providers)
- Uploaded files stored in `data/raw/`, referenced by UUID filename; the original name goes into Qdrant point metadata

## Dev log habit

After every completed coding task (bug fix, feature, refactor), generate a structured dev log file in `logs/`. Name format: `DevLog-YYYY-MM-DD-简短描述.md`. Reference `logs/DevLog-2025-04-30-文档管理API.md` for the exact format — it includes: date, tags, overview, file change list (表格), API design, implementation details, new dependencies, test verification steps, edge cases, and impact analysis. The `.continue/rules/dev-log.md` rule also enforces this.

## CLAUDE.md maintenance

After every code change (except log files in `logs/`), update CLAUDE.md to reflect the current project state: new/removed endpoints, new/removed dependencies, changed file responsibilities, new architectural patterns, etc. Keep it accurate and current — stale CLAUDE.md is worse than none.
