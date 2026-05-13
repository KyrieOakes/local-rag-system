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

Copy `.env.example` to `.env` before starting. The backend reads configuration from `.env` via pydantic-settings.

```bash
# Evaluation (offline retrieval quality assessment)
python evaluation/run_retrieval_eval.py --dataset evaluation/datasets/golden_retrieval.example.jsonl --top-k 5 --experiment-name my-experiment
jupyter notebook evaluation/retrieval_eval_pipeline.ipynb   # full pipeline + visualizations

# Unit tests
python -m unittest discover tests/
```

## Architecture

**Backend** (`app/`) — FastAPI application with three route modules and a layered RAG pipeline:

- `app/main.py` — App factory, CORS middleware (allows `:5173`), route registration
- `app/api/` — Route handlers: `health.py` (`GET /health`), `documents.py` (`POST /upload`, `POST /upload-batch`, `GET /`, `DELETE /{source}`), `rag.py` (`POST /rag/query`)
- `app/services/` — Business logic orchestration. `ingestion_service.py` delegates to the unified `ingest_file_paths` pipeline; `rag_service.py` wires query_processor → retriever → chain; `document_service.py` handles list/delete by querying Qdrant directly
- `ingest.py` — Standalone CLI script at repo root. `python ingest.py --input_dir <dir> --batch_size <n> [--collection_name <name>]`
- `app/rag/` — The RAG pipeline primitives:
  - `loader.py` — Loads PDF (PyPDF), TXT/MD (TextLoader), DOCX (Docx2txtLoader) via LangChain document loaders
  - `splitter.py` — MarkdownHeaderTextSplitter (preserves H1/H2/H3 hierarchy) for .md/.markdown; RecursiveCharacterTextSplitter for all other types
  - `embeddings.py` — Wraps OpenAIEmbeddings pointed at a local embedding server (LM Studio / Ollama)
  - `query_processor.py` — Pre-retrieval LLM call: intent detection and query rewriting. Falls back to original query on failure.
  - `vectorstore.py` — QdrantVectorStore singleton; also contains `list_all_documents()` and `delete_document_by_source()`
  - `retriever.py` — `similarity_search_with_score` against the vectorstore
  - `chain.py` — Builds a LangChain chain: `rag_prompt | llm | StrOutputParser`
  - `prompt.py` — System prompt template; instructs LLM to write natural flowing prose, grounded in context
  - `query_logger.py` — Writes full query trace to `logs/history/rag_queries.jsonl` + brief terminal summary
  - `ingestion/` — Unified batch-ingestion pipeline:
    - `checksum_store.py` — SQLite-based MD5 checksum database for incremental updates
    - `batch_embedder.py` — Batch embedding via OpenAI-compatible `/v1/embeddings` (configurable batch_size)
    - `bulk_writer.py` — Bulk Qdrant `upsert` (all points in one call) + delete by `metadata.file_path`
    - `ingest_pipeline.py` — Orchestration: scan → checksum classify → load → split → batch embed → bulk upsert
- `app/llm/local_llm.py` — `get_llm()` returns a `ChatOpenAI` instance. **Known bug:** `"local"`/`"cloud"` branches are swapped.
- `app/core/config.py` — `Settings` class loaded from `.env` via pydantic-settings
- `app/schemas/` — Pydantic models: `QueryRequest`/`QueryResponse`/`SourceChunk`
- `app/utils/file_utils.py` — Validates file extension (`.pdf`, `.txt`, `.md`, `.markdown`, `.docx`), saves to `data/raw/` with UUID filenames

**Frontend** (`frontend/`) — React 19 + Vite, single-page chat UI with "Editorial Ink" dark theme:

- `src/App.jsx` — Entire application in one component (sidebar, chat messages, upload modal, document manager modal). No router — all UI state managed via `useState`. Health check on mount, scroll-to-bottom on new messages, click-outside/Escape to close panels. Uses SVG icons for file types and welcome hints; emoji avatars for message roles.
- `src/App.css` — Complete design system with CSS custom properties (design tokens for colors, shadows, radii, transitions). Smoked-glass panels, refined typography, subtle ambient light bleeds. ~800 lines (down from ~2000).
- `src/index.css` — Base reset, grain texture overlay, imports Plus Jakarta Sans (Google Fonts) with weight range 300–800.
- `src/api.js` — Axios instance pointing at `http://127.0.0.1:8000`, exports `healthCheck`, `uploadDocument`, `uploadDocuments`, `queryRag`, `listDocuments`, `deleteDocument`
- Frontend dependencies include `react-markdown` for rendering LLM Markdown responses

**Evaluation** (`evaluation/`) — Offline retrieval quality assessment:

- `run_retrieval_eval.py` — CLI runner: loads golden JSONL dataset, calls production retriever, outputs `retrieval-eval-v1` JSON report
- `retrieval_eval_pipeline.ipynb` — Jupyter notebook: full test pipeline with 7 visualization charts (per-question bar charts, aggregate dashboard, radar chart, top-K sensitivity, correlation heatmap, recall-vs-precision scatter). Supports live and demo modes.
- `retrieval_metrics/metrics.py` — Core retrieval metrics: Recall@K, Precision@K, MRR, NDCG@K, context_redundancy@K
- `retrieval_metrics/matching.py` — Maps golden source/snippet labels to concrete chunk IDs (file_path, source, text-snippet matching)
- `retrieval_metrics/evaluator.py` — Unified `evaluate_retrieval_case()` producing grouped `core_metrics` + `context_quality`
- `datasets/golden_retrieval.example.jsonl` — 22 annotated question→relevant_sources examples covering 8 topic areas
- Visualization dependencies: `matplotlib`, `seaborn`, `pandas`, `jupyter`, `nbconvert`

**Infrastructure:**
- Qdrant runs via Docker Compose, data persisted to `qdrant_storage/`
- All LLM/embedding calls use the OpenAI-compatible API format (works with LM Studio, Ollama, or cloud providers)
- Uploaded files stored in `data/raw/`, referenced by UUID filename; the original name goes into Qdrant point metadata

## Dev log habit

After every completed coding task (bug fix, feature, refactor), generate a structured dev log file in `logs/`. Name format: `DevLog-YYYY-MM-DD-简短描述.md`. Reference `logs/DevLog-2025-04-30-文档管理API.md` for the exact format — it includes: date, tags, overview, file change list (表格), API design, implementation details, new dependencies, test verification steps, edge cases, and impact analysis. The `.continue/rules/dev-log.md` rule also enforces this.

## CLAUDE.md maintenance

After every code change (except log files in `logs/`), update CLAUDE.md to reflect the current project state: new/removed endpoints, new/removed dependencies, changed file responsibilities, new architectural patterns, etc. Keep it accurate and current — stale CLAUDE.md is worse than none.
