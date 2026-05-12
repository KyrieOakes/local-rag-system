#!/usr/bin/env python3
"""Batch ingestion script for the local RAG system.

Recursively scans an input directory, computes file checksums for incremental
updates, loads/splits documents, batch-embeds chunks, and bulk-upserts into
Qdrant.

Usage:
    python ingest.py --input_dir data/engineering --batch_size 64
    python ingest.py --input_dir data/engineering --batch_size 32 --collection_name my_collection
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
