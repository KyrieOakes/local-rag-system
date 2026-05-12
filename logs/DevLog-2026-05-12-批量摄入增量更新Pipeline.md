# Dev Log — 批量摄入与增量更新 Pipeline

> **日期**: 2026-05-12
> **标签**: feature, ingestion, batch-embedding, incremental-update, cli

---

## 一、概述

实现完整的本地文档批量摄入系统，支持递归扫描目录、MD5 增量更新、Markdown 标题层级保留、批量 embedding、批量 Qdrant 写入。新增 `ingest.py` CLI 脚本和 `app/rag/ingestion/` 模块，同时重构现有上传流程以复用统一 pipeline。

---

## 二、新增/修改的文件清单

### 新增

| 文件 | 说明 |
|------|------|
| `app/rag/ingestion/__init__.py` | 模块导出 |
| `app/rag/ingestion/checksum_store.py` | SQLite-based MD5 checksum 状态数据库 |
| `app/rag/ingestion/batch_embedder.py` | 批量 embedding 函数（OpenAI-compatible API） |
| `app/rag/ingestion/bulk_writer.py` | 批量 Qdrant upsert + 按 file_path 删除 |
| `app/rag/ingestion/ingest_pipeline.py` | 摄入编排：扫描→分类→加载→分割→批量嵌入→批量写入 |
| `ingest.py` | CLI 入口脚本（argparse：--input_dir, --batch_size, --collection_name） |

### 修改

| 文件 | 操作 | 说明 |
|------|------|------|
| `app/rag/loader.py` | 修改 | 新增 `.docx` (Docx2txtLoader) 和 `.markdown` 支持 |
| `app/rag/splitter.py` | 重写 | MarkdownHeaderTextSplitter (保留 H1/H2/H3) + RecursiveCharacterTextSplitter |
| `app/services/ingestion_service.py` | 重写 | 委托给统一的 `ingest_file_paths()` pipeline |
| `app/utils/file_utils.py` | 修改 | ALLOWED_EXTENSIONS 新增 `.markdown`, `.docx` |
| `requirements.txt` | 修改 | 新增 `docx2txt` 依赖 |
| `.gitignore` | 修改 | 忽略 `data/ingestion_state.db` |

---

## 三、CLI 设计

```bash
python ingest.py --input_dir data/engineering --batch_size 64
python ingest.py --input_dir data/engineering --batch_size 32 --collection_name my_collection
```

参数：
- `--input_dir` (必需)：文档目录路径
- `--batch_size` (可选，默认 64)：每批次 embedding 的 chunk 数
- `--collection_name` (可选，默认从 settings 读取)：Qdrant collection 名称

---

## 四、实现细节

### 4.1 增量更新机制

- **Checksum 存储**: SQLite (`data/ingestion_state.db`)，表 `file_checksums` 记录 `file_path, md5, last_ingested_at, chunk_count, collection_name`
- **变更检测**: 每次运行前计算所有文件的 MD5，与数据库比对：
  - 新文件 → 处理
  - MD5 变化 → 先删旧 chunks，再重新处理
  - MD5 未变 → 跳过
- **删除旧数据**: 对变更文件，按 `metadata.file_path` 在 Qdrant 中精确删除旧 chunks

### 4.2 Markdown Header 分割

- 使用 `MarkdownHeaderTextSplitter(headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")], strip_headers=False)`
- 分割后每段 metadata 保留 `h1`/`h2`/`h3` 标题上下文
- 再用 `RecursiveCharacterTextSplitter` 对大段进一步分割

### 4.3 批量 Embedding

- 直接调用 OpenAI Python SDK 的 `client.embeddings.create(model=..., input=[text1, text2, ...])` 
- 按 `batch_size` 分批发送
- 按 `response.data[].index` 排序确保顺序一致

### 4.4 批量 Qdrant Upsert

- 使用 `QdrantClient.upsert(points=[PointStruct(...), ...])` 写入
- 稳定 Point ID: `uuid.uuid5(NAMESPACE_DNS, f"{file_path}:{md5}:{chunk_index}")`
- Payload 结构: `{page_content, metadata: {source, file_path, file_name, file_type, chunk_index, md5, h1, h2, h3, ...}}`
- **Qdrant 32MB 限制**: 单次 upsert payload 不能超过 32MB（约 600-700 个带向量的 point）。`bulk_upsert_chunks` 内部以 `UPSERT_BATCH_SIZE=500` 分批发送，每批独立调用 `client.upsert`

### 4.5 上传 API 统一

- `ingestion_service.ingest_document()` 改为调用 `ingest_file_paths(file_paths=[...], source_map={path: original_filename})`
- `source_map` 确保上传文件的 `source` metadata 保留原始文件名（而非 UUID 文件名）

---

## 五、测试验证

1. **小规模首次摄入**: `/tmp/rag-test` 2 文件 → 72 chunks, 16.6s, 正常
2. **增量跳过**: 二次运行 → 2 文件全跳过, 0.0s
3. **变更检测**: 修改 1 个文件 → 检测 1 changed, 删除 15 旧 chunks, 写入 16 新 chunks, 3.5s
4. **上传 API**: `POST /documents/upload` → 正常索引, `source` 为原始文件名
5. **文档列表**: `GET /documents` → 包含所有摄入和上传的文档
6. **Qdrant 32MB 限制**: 809 points 单次 upsert 触发 400 Bad Request (44.8MB > 32MB)。修复后以 500 points/batch 分批写入

---

## 六、影响分析

- **不破坏现有 API**: 上传、查询、列表、删除端点全部正常
- **性能提升**: 批量 embedding 替代逐条调用，每批次 64 条文本共用一个 HTTP 请求
- **幂等性**: 多次运行同一目录不会重复写入（checksum 去重）
- **可扩展**: `SUPPORTED_EXTENSIONS` 可轻松扩展新文件类型
- **Qdrant 兼容**: upsert 自动拆分为 500 points/batch，避开 32MB payload 限制
