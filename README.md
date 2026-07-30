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
- **🔍 智能问答** — 两层路由门控（关键词预过滤 + LLM 路由）+ 意图识别 + 查询改写 + 向量检索 + Rerank 精排 + LLM 生成
- **⚡ SSE 流式输出** — `/rag/query/stream` 端点逐 token 推送，状态事件实时显示管道进度
- **🎯 Rerank 精排** — 可选 Cross-Encoder / Hybrid Fusion 重排序，提升检索精度
- **⚡ 批量 Embedding** — 一次 API 调用处理最多 64 条文本，比逐条调用快数倍
- **♻️ 增量更新** — SQLite checksum 数据库，文件未改则跳过，改过的文件自动删旧换新
- **🧠 服务端长期记忆** — `conversation_id` 自动恢复 SQLite 历史，滚动摘要保留早期决策，近期消息保留原文；客户端尾部仅用于异步落库竞态对账
- **📐 统一上下文预算** — 路由与生成共享 token 预算策略，统一计算系统提示、问题、历史、检索文档、安全余量和预留输出，超限时确定性裁剪或返回 413
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
    ├── /health                     健康检查
    ├── /documents/upload           上传文档
    ├── /documents                  文档列表
    ├── /documents/{source}         删除文档
    ├── /rag/query                  RAG 问答 (同步)
    ├── /rag/query/stream           RAG 问答 (SSE 流式)
    └── /conversations              对话历史管理
    │
    ▼
RAG Pipeline
    摄入: loader → splitter → batch_embedder → bulk_writer → Qdrant
    问答: context_manager → query_processor → retriever → reranker(可选) → prompt → LLM → SSE
    记忆: conversation_store(SQLite 原文 + rolling summary) → token-budgeted context
    日志: query_logger → terminal + logs/history/rag_queries.jsonl
    │
    ▼
Qdrant (Docker, :6333)          LM Studio (:1234)
  向量存储 + 语义检索             LLM + Embedding + Reranker
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

上下文窗口需要与当前模型服务保持一致，核心配置如下：

```dotenv
LLM_CONTEXT_WINDOW=32768
LLM_RESERVED_OUTPUT_TOKENS=2048
CONTEXT_SAFETY_MARGIN_TOKENS=512
CONTEXT_HISTORY_MAX_TOKENS=8192
CONTEXT_SUMMARY_ENABLED=true
```

默认 `CONTEXT_TOKENIZER_ENCODING=offline_multilingual` 可完全离线运行，并对中文做保守计数；如果目标供应商对应的 tiktoken 编码已缓存在本地，可改为 `cl100k_base` 等编码。

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
| `POST` | `/rag/query` | RAG 问答（同步） |
| `POST` | `/rag/query/stream` | RAG 问答（SSE 流式） |
| `GET` | `/conversations` | 对话历史列表 |
| `GET` | `/conversations/{id}` | 对话详情（含全部消息） |
| `DELETE` | `/conversations/{id}` | 删除对话 |

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

**流式问答 SSE 事件：**

```
event: routing
data: {"routing":"rag","conversation_id":"a1b2c3d4"}

event: status
data: {"phase":"searching","message":"Searching documents..."}

event: status
data: {"phase":"generating","message":"Generating answer..."}

event: token
data: "The Guild project is a cross-functional..."

event: sources
data: [{"content":"...","source":"guild_project.md","score":0.86}]

event: done
data: {}
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
│   │   ├── reranker.py               Rerank 精排 (Cross-Encoder/Hybrid)
│   │   ├── conversation_store.py     对话持久化 (SQLite)
│   │   ├── context_manager.py        服务端记忆恢复/摘要/统一 token 预算
│   │   ├── prompt.py                 System Prompt
│   │   ├── chain.py                  答案生成链 (同步 + 流式)
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
│   ├── ingestion_state.db            Checksum 数据库
│   └── conversations.db              对话历史数据库
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
| Rerank | sentence-transformers (BAAI/bge-reranker-base / Hybrid Fusion) |
| 文本处理 | PyPDF + Docx2txtLoader + MarkdownHeaderTextSplitter |
| 流式传输 | SSE (Server-Sent Events) via FastAPI StreamingResponse + LangChain astream |
| 上下文管理 | SQLite rolling summary + recent-message window + configurable token budget |
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
