"""Document upload, listing, and lifecycle API."""

from __future__ import annotations

import asyncio
import logging
from typing import List

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.services.document_service import delete_document, list_documents
from app.services.ingestion_service import ingest_document
from app.utils.file_utils import (
    UploadTooLargeError,
    remove_upload_file,
    save_upload_file,
)

router = APIRouter(prefix="/documents", tags=["Documents"])
logger = logging.getLogger(__name__)


async def _cleanup_failed_upload(file_path: str | None) -> None:
    if not file_path:
        return
    try:
        await asyncio.to_thread(remove_upload_file, file_path)
    except Exception:
        logger.exception("Failed to clean up upload file %s", file_path)


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    try:
        file_path = await save_upload_file(file)
    except UploadTooLargeError as error:
        raise HTTPException(status_code=413, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception:
        logger.exception("Failed to save uploaded file %s", file.filename)
        raise HTTPException(status_code=500, detail="Document upload failed")

    try:
        return await asyncio.to_thread(
            ingest_document,
            file_path=file_path,
            original_filename=file.filename,
        )
    except Exception:
        logger.exception("Document ingestion failed for %s", file.filename)
        await _cleanup_failed_upload(file_path)
        raise HTTPException(status_code=500, detail="Document ingestion failed")


@router.post("/upload-batch")
async def upload_documents_batch(files: List[UploadFile] = File(...)):
    results = []
    for file in files:
        file_path: str | None = None
        try:
            file_path = await save_upload_file(file)
        except UploadTooLargeError as error:
            results.append(
                {
                    "filename": file.filename,
                    "status": "error",
                    "error": str(error),
                }
            )
            continue
        except ValueError as error:
            results.append(
                {
                    "filename": file.filename,
                    "status": "error",
                    "error": str(error),
                }
            )
            continue
        except Exception:
            logger.exception("Failed to save batch upload %s", file.filename)
            results.append(
                {
                    "filename": file.filename,
                    "status": "error",
                    "error": "Document upload failed",
                }
            )
            continue

        try:
            result = await asyncio.to_thread(
                ingest_document,
                file_path=file_path,
                original_filename=file.filename,
            )
            results.append(result)
        except Exception:
            logger.exception("Document ingestion failed for %s", file.filename)
            await _cleanup_failed_upload(file_path)
            results.append(
                {
                    "filename": file.filename,
                    "status": "error",
                    "error": "Document ingestion failed",
                }
            )
    return {"results": results}


@router.get("")
def get_documents():
    try:
        return list_documents()
    except Exception:
        logger.exception("Failed to list documents")
        raise HTTPException(status_code=500, detail="Failed to list documents")


@router.delete("/{source:path}")
def remove_document(source: str):
    """Delete by document_id or an unambiguous legacy source name."""
    try:
        result = delete_document(source)
        if result["status"] == "not_found":
            raise HTTPException(
                status_code=404,
                detail=f"Document not found: {source}",
            )
        if result["status"] == "ambiguous":
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Multiple documents share this source; delete by document_id",
                    "candidates": result.get("candidates", []),
                },
            )
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to delete document %s", source)
        raise HTTPException(status_code=500, detail="Failed to delete document")
