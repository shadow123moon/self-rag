import logging
from fastapi import UploadFile, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from config import settings
from models.document import Document, DocumentChunk
from services.parser_service import parse_document
from services.vector_service import delete_vectors_by_document_id, vectorize_chunks
from services.bm25_service import mark_bm25_dirty
from services.storage_service import LocalStorageService
from utils.file_utils import (
    validate_file_type,
    generate_document_id,
)
logger = logging.getLogger(__name__)
storage_service = LocalStorageService(settings.UPLOAD_DIR)


async def upload_document(file: UploadFile, db: Session, background_tasks: BackgroundTasks):
    ext = validate_file_type(file)
    doc_id = generate_document_id()
    stored_file = await storage_service.save_upload(file, f"{doc_id}{ext}")

    logger.info(f"文档类型: {ext},文档ID:{doc_id}")
    existing_doc = db.query(Document).filter(Document.file_md5 == stored_file.md5).first()
    if existing_doc:
        logger.info("文件已存在，实现“秒传”，不重复存储")
        try:
            storage_service.delete(stored_file.path)
        except Exception as e:
            logger.warning(f"重复文件临时对象删除失败: {e}")
        return {
            "document_id": existing_doc.document_id,
            "duplicate": True,
            "status": existing_doc.status,
            "filename": existing_doc.filename,
        }

    logger.info(f"新文件上传:文件名：{file.filename}")
    new_doc = Document(
        document_id=doc_id,
        filename=file.filename,
        file_type=ext.lstrip("."),
        file_path=stored_file.path,
        file_md5=stored_file.md5,
        file_size=stored_file.size,
        status="processing",
    )
    try:
        db.add(new_doc)
        db.commit()
        db.refresh(new_doc)
    except Exception:
        db.rollback()
        try:
            storage_service.delete(stored_file.path)
        except Exception as e:
            logger.warning(f"数据库写入失败后文件清理失败: {e}")
        raise

    logger.info(f"后台开始实现文档: {new_doc.filename}的解析")
    background_tasks.add_task(parse_document, doc_id, stored_file.path, ext)
    return {
        "document_id": doc_id,
        "duplicate": False,
        "filename": file.filename,
        "status": "processing",
    }


def delete_document(doc_id: str, db: Session):
    doc = db.query(Document).filter(Document.document_id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).all()
    vector_ids = [chunk.vector_id for chunk in chunks if chunk.vector_id]

    try:
        delete_vectors_by_document_id(doc_id)


    except Exception as e:
        db.rollback()
        logger.error(f"删除向量失败: {e}")
        raise HTTPException(status_code=500, detail="删除向量失败")

    db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).delete(
        synchronize_session=False
    )
    db.delete(doc)
    db.commit()
    mark_bm25_dirty()

    if doc.file_path and storage_service.exists(doc.file_path):
        try:
            storage_service.delete(doc.file_path)
        except Exception as e:
            logger.warning(f"原始文件删除失败: {e}")

    return {
        "document_id": doc_id,
        "deleted_chunks": len(chunks),
        "deleted_vectors": len(vector_ids),
    }

def rebuild_document(db: Session, doc_id: str, background_tasks: BackgroundTasks):
    doc = db.query(Document).filter(Document.document_id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    if not doc.file_path or not storage_service.exists(doc.file_path):
        raise HTTPException(status_code=400, detail="原始文件不存在，无法重建")

    try:
        delete_vectors_by_document_id(doc_id)

        old_chunks_count = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc_id)
            .delete(synchronize_session=False)
        )

        doc.status = "processing"
        doc.chunk_count = 0
        doc.error_message = None
        db.commit()
        mark_bm25_dirty()

        ext = doc.file_type
        if not ext.startswith("."):
            ext = "." + ext

        background_tasks.add_task(parse_document, doc_id, doc.file_path, ext)

        return {
            "document_id": doc_id,
            "status": "processing",
            "deleted_chunks": old_chunks_count,
            "message": "文档正在后台重建",
        }

    except Exception as e:
        db.rollback()
        doc = db.query(Document).filter(Document.document_id == doc_id).first()
        if doc:
            doc.status = "failed"
            doc.error_message = f"重建文档失败: {e}"
            db.commit()
        raise HTTPException(status_code=500, detail=f"重建文档失败: {e}")

def reindex_document_vectors(db: Session, doc_id: str):
    doc = db.query(Document).filter(Document.document_id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == doc_id)
        .order_by(DocumentChunk.chunk_index)
        .all()
    )
    if not chunks:
        raise HTTPException(status_code=400, detail="文档没有 chunks，无法重新向量化")

    try:
        delete_vectors_by_document_id(doc_id)

        doc.status = "processing"
        doc.error_message = None
        db.flush()

        count = vectorize_chunks(chunks, doc.filename)

        doc.status = "completed"
        doc.chunk_count = count
        doc.error_message = None
        db.commit()

        return {
            "document_id": doc_id,
            "status": "completed",
            "chunk_count": count,
            "message": "文档重新向量化完成",
        }

    except Exception as e:
        db.rollback()
        doc = db.query(Document).filter(Document.document_id == doc_id).first()
        if doc:
            doc.status = "failed"
            doc.error_message = f"重新向量化失败: {e}"
            db.commit()
        raise HTTPException(status_code=500, detail=f"重新向量化失败: {e}")

