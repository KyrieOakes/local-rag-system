from typing import List

from fastapi import APIRouter, File, HTTPException, UploadFile, Body

from app.services.ingestion_service import ingest_document
from app.services.document_service import list_documents, delete_document
from app.utils.file_utils import save_upload_file

# 定义一个APIRouter实例，设置路由的前缀为"/documents"和标签为"Documents"，用于处理与文档相关的API请求
router = APIRouter(prefix="/documents", tags=["Documents"])

# 定义一个POST请求的路由处理函数，路径为"/upload"，用于处理文档上传的请求，
# 接受一个名为file的UploadFile类型的参数，表示上传的文件
@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    try:
        file_path = await save_upload_file(file)

        result = ingest_document(
            file_path=file_path,
            original_filename=file.filename,
        )

        return result

    except ValueError as error:
        # 如果在文件验证过程中发生ValueError异常，说明上传的文件类型不受支持，返回一个400 Bad Request的HTTP响应，并包含错误信息
        raise HTTPException(status_code=400, detail=str(error))

    except Exception as error:
        # 如果在文档摄取过程中发生任何其他异常，返回一个500 Internal Server Error的HTTP响应，并包含错误信息，提示文档摄取失败
        raise HTTPException(status_code=500, detail=f"Document ingestion failed: {error}")


@router.post("/upload-batch")
async def upload_documents_batch(files: List[UploadFile] = File(...)):
    results = []
    for file in files:
        try:
            file_path = await save_upload_file(file)
            result = ingest_document(
                file_path=file_path,
                original_filename=file.filename,
            )
            results.append(result)
        except ValueError as error:
            results.append({
                "filename": file.filename,
                "status": "error",
                "error": str(error),
            })
        except Exception as error:
            results.append({
                "filename": file.filename,
                "status": "error",
                "error": f"Document ingestion failed: {error}",
            })
    return {"results": results}


@router.get("")
def get_documents():
    """列出所有已索引的文档，按文件类型分组"""
    try:
        return list_documents()
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Failed to list documents: {error}")


@router.delete("/{source:path}")
def remove_document(source: str):
    """按文件名删除文档及其所有分块"""
    try:
        result = delete_document(source)
        if result["status"] == "not_found":
            raise HTTPException(status_code=404, detail=f"Document not found: {source}")
        return result
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {error}")
