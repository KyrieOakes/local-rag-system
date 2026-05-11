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

# Qdrant vector database
docker compose up -d

# Frontend (from frontend/)
cd frontend && npm run dev       # Vite dev server on :5173
cd frontend && npm run build     # production build
cd frontend && npm run lint      # ESLint

# Python dependencies (if adding new ones)
pip install -r requirements.txt
```

Copy `.env.example` to `.env` before starting. The backend reads configuration from `.env` via pydantic-settings. Tests exist in `tests/` but are empty skeleton files.

## Architecture

**Backend** (`app/`) — FastAPI application with three route modules and a layered RAG pipeline:

- `app/main.py` — App factory, CORS middleware (allows `:5173`), route registration
- `app/api/` — Route handlers: `health.py` (`GET /health`), `documents.py` (`POST /upload`, `POST /upload-batch`, `GET /`, `DELETE /{source}`), `rag.py` (`POST /rag/query`)
- `app/services/` — Business logic orchestration. `ingestion_service.py` wires loader → splitter → vectorstore; `rag_service.py` wires query_processor → retriever → chain; `document_service.py` handles list/delete by querying Qdrant directly
- `app/rag/` — The RAG pipeline primitives:
  - `loader.py` — Loads PDF (PyPDF), TXT/MD (TextLoader) via LangChain document loaders
  - `splitter.py` — RecursiveCharacterTextSplitter with separators `["\n\n", "\n", "。", ".", " ", ""]`
  - `embeddings.py` — Wraps OpenAIEmbeddings pointed at a local embedding server (LM Studio / Ollama)
  - `query_processor.py` — Pre-retrieval LLM call: intent detection (question_answering/summarization/comparison/fact_lookup) and query rewriting for better retrieval. Falls back to original query on failure.
  - `vectorstore.py` — QdrantVectorStore singleton; also contains `list_all_documents()` (scrolls all Qdrant points, groups by `metadata.source`) and `delete_document_by_source()` (filtered delete by `metadata.source`)
  - `retriever.py` — `similarity_search_with_score` against the vectorstore
  - `chain.py` — Builds a LangChain chain: `rag_prompt | llm | StrOutputParser`; formats retrieved documents with source/page headers
  - `prompt.py` — System prompt template instructing the LLM to answer only from context
- `app/llm/local_llm.py` — `get_llm()` returns a `ChatOpenAI` instance, switching between local and cloud endpoints based on `LLM_PROVIDER` env var. **Known bug:** the `"local"` branch uses `cloud_llm_*` settings and the default fallback uses `llm_*` settings — the condition appears reversed.
- `app/core/config.py` — `Settings` class loaded from `.env` via pydantic-settings
- `app/schemas/` — Pydantic models: `QueryRequest`/`QueryResponse`/`SourceChunk` for RAG; `document.py` is an empty file
- `app/utils/file_utils.py` — Validates file extension (`.pdf`, `.txt`, `.md`), saves uploads to `data/raw/` with UUID-based filenames (original filename preserved in Qdrant metadata as `source`)

**Frontend** (`frontend/`) — React 19 + Vite, single-page chat UI with "Editorial Ink" dark theme:

- `src/App.jsx` — Entire application in one component (sidebar, chat messages, upload modal, document manager modal). No router — all UI state managed via `useState`. Health check on mount, scroll-to-bottom on new messages, click-outside/Escape to close panels. Uses SVG icons for file types and welcome hints; emoji avatars for message roles.
- `src/App.css` — Complete design system with CSS custom properties (design tokens for colors, shadows, radii, transitions). Smoked-glass panels, refined typography, subtle ambient light bleeds. ~800 lines (down from ~2000).
- `src/index.css` — Base reset, grain texture overlay, imports Plus Jakarta Sans (Google Fonts) with weight range 300–800.
- `src/api.js` — Axios instance pointing at `http://127.0.0.1:8000`, exports `healthCheck`, `uploadDocument`, `uploadDocuments`, `queryRag`, `listDocuments`, `deleteDocument`
- Frontend dependencies include `react-markdown` for rendering LLM Markdown responses

**Infrastructure:**
- Qdrant runs via Docker Compose, data persisted to `qdrant_storage/`
- All LLM/embedding calls use the OpenAI-compatible API format (works with LM Studio, Ollama, or cloud providers)
- Uploaded files stored in `data/raw/`, referenced by UUID filename; the original name goes into Qdrant point metadata

## Dev log habit

After every completed coding task (bug fix, feature, refactor), generate a structured dev log file in `logs/`. Name format: `DevLog-YYYY-MM-DD-简短描述.md`. Reference `logs/DevLog-2025-04-30-文档管理API.md` for the exact format — it includes: date, tags, overview, file change list (表格), API design, implementation details, new dependencies, test verification steps, edge cases, and impact analysis. The `.continue/rules/dev-log.md` rule also enforces this.

## CLAUDE.md maintenance

After every code change (except log files in `logs/`), update CLAUDE.md to reflect the current project state: new/removed endpoints, new/removed dependencies, changed file responsibilities, new architectural patterns, etc. Keep it accurate and current — stale CLAUDE.md is worse than none.
