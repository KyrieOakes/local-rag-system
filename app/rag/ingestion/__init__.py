"""
ingestion 子包 — 批量文档摄取流水线。

公开接口：
- ChecksumStore — 基于 SQLite 的文件 MD5 校验和存储（增量更新核心）
- embed_texts — 批量文本嵌入（调用 OpenAI 兼容的 /v1/embeddings API）
- bulk_upsert_chunks — 批量写入 Qdrant（分批 upsert，避免 32MB 载荷限制）
- delete_chunks_by_filepath — 按文件路径删除 Qdrant 中的已有分块
- ingest_directory — CLI 入口：递归扫描目录 → 分类（新增/变更/未变）→ 摄取
- ingest_file_paths — API 入口：摄取指定的文件路径列表（用于上传接口）
"""

from app.rag.ingestion.checksum_store import ChecksumStore
from app.rag.ingestion.batch_embedder import embed_texts
from app.rag.ingestion.bulk_writer import bulk_upsert_chunks, delete_chunks_by_filepath
from app.rag.ingestion.ingest_pipeline import ingest_directory, ingest_file_paths

__all__ = [
    "ChecksumStore",
    "embed_texts",
    "bulk_upsert_chunks",
    "delete_chunks_by_filepath",
    "ingest_directory",
    "ingest_file_paths",
]
