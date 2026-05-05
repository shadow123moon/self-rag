from fastapi import HTTPException

from fastapi import APIRouter, UploadFile, File, Depends, BackgroundTasks
from sqlalchemy.orm import Session

import logging
from database import get_db
from models.document import Document, DocumentChunk
from services.document_service import upload_document, delete_document, rebuild_document, reindex_document_vectors

router=APIRouter(prefix="/api/documents", tags=["documents"])
@router.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),

):
    logger = logging.getLogger(__name__)  # 通常为 "services.document_service"
    logger.info("开始上传文档")
    result = await upload_document(file, db, background_tasks)

    return {"code": 0, "data": result}
@router.get("/")
async def read_document(db: Session = Depends(get_db)):
    # 查询所有文档，并按创建时间倒序（可选）
    docs = db.query(Document).order_by(Document.created_at.desc()).all()

    # 手动构建返回的 JSON 数据
    result = []
    for doc in docs:
        result.append({
            "document_id": doc.document_id,
            "filename": doc.filename,
            "file_type": doc.file_type,
            "status": doc.status,
            "chunk_count": doc.chunk_count,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        })

    return {"code": 0, "data": result}


@router.get("/{document_id}")
async def read_document_by_id(document_id: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.document_id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    return {
        "code": 0,
        "data": {
            "document_id": doc.document_id,
            "filename": doc.filename,
            "file_type": doc.file_type,
            "file_path": doc.file_path,
            "file_md5": doc.file_md5,
            "file_size": doc.file_size,
            "status": doc.status,
            "chunk_count": doc.chunk_count,
            "error_message": doc.error_message,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        }
    }


@router.get("/{document_id}/chunks")
async def read_document_chunks(document_id: str, db: Session = Depends(get_db)):
    # 查询该文档的所有 chunks，按 chunk_index 顺序排列
    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
        .all()
    )
    if not chunks:
        raise HTTPException(status_code=404, detail="文档不存在或无内容")

    # 构造返回列表
    result = []
    for c in chunks:
        result.append({
            "chunk_id": c.chunk_id,
            "chunk_index": c.chunk_index,
            "content": c.content,
            "page_number": c.page_number,
            "vector_id": c.vector_id,
        })

    return {"code": 0, "data": result}

@router.delete("/{document_id}")
async def delete(document_id: str, db: Session =Depends(get_db)):
   result=delete_document(document_id,db)
   return {
       "code": 0,
       "message": "文档已删除",
       "data": result
   }

@router.post("/{document_id}/rebuild")
async def rebuild(
    document_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    result = rebuild_document( db, document_id,background_tasks)
    return {
        "code": 0,
        "message": "文档开始重建",
        "data": result,
    }
@router.post("/{document_id}/reindex")
async def reindex(document_id: str, db: Session = Depends(get_db)):
    result = reindex_document_vectors(db, document_id)
    return {
        "code": 0,
        "message": "文档重新向量化成功",
        "data": result,
    }
