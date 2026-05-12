# 🧠 Local RAG System

> 本地 RAG 知识问答系统 — 上传文档、批量摄入、智能检索、LLM 问答，全程本地运行。

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue?style=flat-square" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.136-informational?style=flat-square" alt="FastAPI">
  <img src="https://img.shields.io/badge/LangChain-1.2-green?style=flat-square" alt="LangChain">
  <img src="https://img.shields.io/badge/Qdrant-latest-red?style=flat-square" alt="Qdrant">
  <img src="https://img.shields.io/badge/React-19-61dafb?style=flat-square" alt="React">
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=flat-square" alt="License">
</p>

---

## ✨ 功能亮点

- **📥 文档上传** — 支持 PDF、TXT、Markdown、DOCX，上传后自动分块、向量化、入库
- **📂 批量摄入** — `python ingest.py --input_dir data/engineering --batch_size 64`，递归扫描、批量 embedding、增量更新
- **🔍 智能问答** — 意图识别 + 查询改写 + 向量检索 + LLM 生成，答案附带来源引用和相似度打分
- **⚡ 批量 Embedding** — 一次 API 调用处理最多 64 条文本，比逐条调用快数倍
- **♻️ 增量更新** — SQLite checksum 数据库，文件未改则跳过，改过的文件自动删旧换新
- **📋 查询日志** — 每次问答完整记录到 `logs/history/rag_queries.jsonl`，方便评估和调试
- **🎨 Editorial Ink 主题** — 深色设计系统，Plus Jakarta Sans 字体，烟熏玻璃面板
- **🔌 本地/云端双模式** — LLM 和 Embedding 均支持 LM Studio / Ollama / DeepSeek 等 OpenAI 兼容 API

---

## 🏗️ 架构

```
Browser (:5173)
    │
    ▼
FastAPI (:8000)
    ├── /health                  健康检查
    ├── /documents/upload        上传文档
    ├── /documents               文档列表
    ├── /documents/{source}      删除文档
    └── /rag/query               RAG 问答 (top_k=5)
    │
    ▼
RAG Pipeline
    摄入: loader → splitter → batch_embedder → bulk_writer → Qdrant
    问答: query_processor → retriever → prompt → LLM → answer + sources
    日志: query_logger → terminal + logs/history/rag_queries.jsonl
    │
    ▼
Qdrant (Docker, :6333)          LM Studio (:1234)
  向量存储 + 语义检索             LLM + Embedding
```

---

## 🚀 快速开始

### 前置条件

- Python 3.10+ &nbsp;·&nbsp; Node.js 18+ &nbsp;·&nbsp; Docker
- LM Studio（或 Ollama），加载 LLM 和 Embedding 模型

### 1. 安装依赖

```bash
git clone <repo-url> && cd local-rag-system
pip install -r requirements.txt
```

### 2. 启动 Qdrant

```bash
docker compose up -d
```

### 3. 配置环境

```bash
cp .env.example .env
# 按需编辑 .env：LLM_BASE_URL、EMBEDDING_MODEL 等
```

### 4. 启动后端

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. 启动前端

```bash
cd frontend && npm install && npm run dev
```

打开 `http://localhost:5173`。

### 6. 批量摄入文档（可选）

```bash
# 首次全量摄入
python ingest.py --input_dir data/engineering --batch_size 64

# 再次运行仅处理变更文件（秒级完成）
python ingest.py --input_dir data/engineering --batch_size 64
```

---

## 📡 API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `GET` | `/documents` | 列出已索引文档 |
| `POST` | `/documents/upload` | 上传单个文件 |
| `POST` | `/documents/upload-batch` | 批量上传文件 |
| `DELETE` | `/documents/{source}` | 删除文档及所有分块 |
| `POST` | `/rag/query` | RAG 问答 |

**问答示例：**

```json
// Request
{ "question": "What is the Guild project about?" }

// Response
{
  "question": "What is the Guild project about?",
  "answer": "The Guild project is a cross-functional initiative...",
  "sources": [
    {
      "content": "...",
      "source": "guild_project.md",
      "file_name": "guild_project.md",
      "file_path": "data/engineering/projects/guild_project.md",
      "chunk_index": 3,
      "score": 0.86
    }
  ]
}
```

---

## 📂 项目结构

```
local-rag-system/
├── app/
│   ├── api/                          FastAPI 路由
│   ├── services/                     业务编排
│   ├── rag/                          RAG 核心
│   │   ├── loader.py                 文档加载 (PDF/TXT/MD/DOCX)
│   │   ├── splitter.py               Markdown 标题切分 + 递归切分
│   │   ├── embeddings.py             Embedding 模型
│   │   ├── query_processor.py        意图识别 + 查询改写
│   │   ├── query_logger.py           查询日志 (JSONL + terminal)
│   │   ├── vectorstore.py            Qdrant 操作
│   │   ├── retriever.py              向量检索
│   │   ├── prompt.py                 System Prompt
│   │   ├── chain.py                  答案生成链
│   │   └── ingestion/                批量摄入 pipeline
│   │       ├── checksum_store.py     SQLite MD5 校验
│   │       ├── batch_embedder.py     批量 Embedding
│   │       ├── bulk_writer.py        批量 Qdrant 写入
│   │       └── ingest_pipeline.py    摄入编排
│   ├── llm/                          LLM 工厂 (本地/云端)
│   ├── core/                         配置 (pydantic-settings)
│   ├── schemas/                      Pydantic 模型
│   └── utils/                        工具函数
├── frontend/                         React 19 + Vite
├── ingest.py                         CLI 批量摄入脚本
├── data/
│   ├── raw/                          上传文件
│   └── ingestion_state.db            Checksum 数据库
├── logs/
│   └── history/rag_queries.jsonl     查询历史
├── docker-compose.yml                Qdrant 容器
├── requirements.txt
└── .env.example
```

---

## 🛠️ 技术栈

| 层 | 技术 |
|----|------|
| 后端 | FastAPI + Uvicorn + LangChain |
| 向量库 | Qdrant (Docker) |
| LLM | qwen3-8b-mlx / DeepSeek（OpenAI 兼容 API） |
| Embedding | text-embedding-qwen3-embedding-4b |
| 文本处理 | PyPDF + Docx2txtLoader + MarkdownHeaderTextSplitter |
| 前端 | React 19 + Vite + react-markdown + Axios |
| 摄入 | `ingest.py` CLI + `app/rag/ingestion/` 模块 |

---

## 📝 查询日志格式

每次问答自动追加到 `logs/history/rag_queries.jsonl`：

```json
{
  "timestamp": "2026-05-12 15:25:47",
  "question": "what is it guild project about?",
  "rewritten_query": "What is the Guild project mainly about?",
  "intent": "question_answering",
  "top_k": 5,
  "retrieved_chunks": [
    {
      "rank": 1,
      "content_preview": "...",
      "file_name": "guild_project.md",
      "file_path": "data/engineering/projects/guild_project.md",
      "chunk_index": 3,
      "score": 0.86
    }
  ],
  "answer": "The Guild project is ..."
}
```
