import logging

from database import SessionLocal
from models.document import Document
from services.bm25_service import mark_bm25_dirty
from services.parsers import (
    PARSERS,
    DocxParser,
    ParsedContent,
    PdfParser,
    PdfTextBlock,
    PyMuPdfOcrProvider,
    TxtParser,
    clean_text,
    parse_file_content,
)
from services.splitter_service import process_and_save_chunks
from services.vector_service import vectorize_chunks


def parse_document(doc_id: str, file_path: str, ext: str):
    logger = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        logger.info(f"处理 {ext} 文档: {file_path}")
        parsed = parse_file_content(file_path, ext)
        if parsed.page_numbers:
            for page_number, text in zip(parsed.page_numbers, parsed.texts):
                logger.info(f"第{page_number}页文本样本: {text[:200]}")
            chunks = process_and_save_chunks(db, doc_id, parsed.texts, parsed.page_numbers)
            logger.info(f"PDF的页码总数为：{parsed.page_numbers}")
        else:
            chunks = process_and_save_chunks(db, doc_id, "\n\n".join(parsed.texts))

        db.flush()  # 关键：确保 chunk 记录能被后面查询到
        doc_record = db.query(Document).filter(Document.document_id == doc_id).first()
        if not doc_record:
            raise ValueError(f"文档记录不存在: {doc_id}")
        chunk_count = vectorize_chunks(chunks, doc_record.filename)
        doc_record.status = "completed"
        doc_record.chunk_count = chunk_count
        doc_record.error_message = None
        db.commit()
        mark_bm25_dirty()
        logger.info(f"文档 {doc_id} 解析完成，chunks 数量: {chunk_count}")

    except Exception as e:
        db.rollback()
        doc_record = db.query(Document).filter(Document.document_id == doc_id).first()
        if doc_record:
            doc_record.status = "failed"
            doc_record.error_message = str(e)
        db.commit()
    finally:
        db.close()
