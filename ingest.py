#!/usr/bin/env python3
"""
批量文档摄取 CLI 脚本。

独立的命令行工具，用于将整个目录的文档递归摄取到 RAG 向量数据库。
调用 app.rag.ingestion.ingest_pipeline.ingest_directory() 流水线。

用法：
    python ingest.py --input_dir data/engineering --batch_size 64
    python ingest.py --input_dir data/engineering --batch_size 32 --collection_name my_collection

参数：
    --input_dir      要摄取的文档目录（必填）
    --batch_size     每次嵌入 API 调用的文本条数（默认 64）
    --collection_name Qdrant 集合名（默认从 .env 读取）

支持增量更新：通过 MD5 校验和自动跳过未变更文件，仅处理新增和变更文件。
完成后打印摘要：文件总数、新增/变更/跳过数、分块数、耗时。
"""

import argparse
import logging
import sys
import time

from app.rag.ingestion import ingest_directory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("ingest")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch-ingest a directory of documents into the RAG vector store",
    )
    parser.add_argument(
        "--input_dir",
        required=True,
        help="Path to the directory containing documents to ingest",
    )
    parser.add_argument(
        "--batch_size",
        type=int,
        default=64,
        help="Number of chunks per embedding API call (default: 64)",
    )
    parser.add_argument(
        "--collection_name",
        default=None,
        help="Qdrant collection name (default: from .env / settings)",
    )
    args = parser.parse_args()

    t_start = time.perf_counter()
    try:
        result = ingest_directory(
            input_dir=args.input_dir,
            collection_name=args.collection_name,
            batch_size=args.batch_size,
        )
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(130)

    total_elapsed = time.perf_counter() - t_start

    # Summary
    print()
    print("=" * 60)
    print("  INGEST SUMMARY")
    print("=" * 60)
    print(f"  Input directory:    {args.input_dir}")
    print(f"  Status:             {result['status']}")
    print(f"  Total files found:  {result.get('total_files', 0)}")
    print(f"  New files:          {result.get('new_files', 0)}")
    print(f"  Changed files:      {result.get('changed_files', 0)}")
    print(f"  Skipped (unchanged):{result.get('skipped_files', 0)}")
    print(f"  Total chunks:       {result.get('total_chunks', 0)}")
    print(f"  Points upserted:    {result.get('points_upserted', 0)}")
    print(f"  Pipeline time:      {result.get('elapsed_seconds', 0)}s")
    print(f"  Total wall time:    {total_elapsed:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
