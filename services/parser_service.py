# services/parser_service.py
from sqlalchemy.orm import Session
from database import SessionLocal
from models.document import Document
from services.bm25_service import mark_bm25_dirty
from services.splitter_service import process_and_save_chunks, split_text_into_chunks
import pymupdf
import logging
from services.vector_service import vectorize_chunks

import re


def _join_spaced_alnum(match: re.Match) -> str:
    return re.sub(r"\s+", "", match.group(0))


def _join_common_short_terms(match: re.Match) -> str:
    left, right = match.group(1), match.group(2)
    joined = f"{left}{right}"
    common_terms = {
        "ai",
        "io",
        "ip",
        "id",
        "db",
        "os",
        "fd",
        "ui",
        "ux",
        "cv",
        "nl",
        "qa",
    }
    return joined if joined.lower() in common_terms else match.group(0)


def clean_text(text: str) -> str:
    """
    1. 修复英文/数字被空格拆开的情况（如 "R e d i s"、"A O F"）
    2. 统一换行符
    3. 压缩多余空格
    4. 去掉过多空行（连续多个空行 → 保留1个）
    """
    # ===== 2. 统一换行符 =====
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # 修复 PDF 行尾英文断词，如 "fea-\ntures" -> "features"。
    text = re.sub(r"([A-Za-z])-\n\s*([A-Za-z])", r"\1\2", text)

    # 清理 LaTeX/PDF 解析残留的引用标记，保留公式主体文本。
    text = re.sub(
        r"\\\s*(?:l\s*a\s*b\s*e\s*l|r\s*e\s*f|c\s*i\s*t\s*e)\s*\{[^{}]*\}",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    # ===== 1. 修复英文/数字被拆开 =====
    # 只合并 3 个及以上单字符英文/数字序列，避免把 "Redis is fast" 误伤成 "Redisisfast"。
    text = re.sub(
        r"(?<![a-zA-Z0-9])(?:[a-zA-Z0-9]\s+){2,}[a-zA-Z0-9](?![a-zA-Z0-9])",
        _join_spaced_alnum,
        text,
    )
    # 额外处理常见两字符技术词，如 "I O"、"f d"、"A I"。
    text = re.sub(
        r"(?<![a-zA-Z0-9])([a-zA-Z])\s+([a-zA-Z])(?![a-zA-Z0-9])",
        _join_common_short_terms,
        text,
    )

    # ===== 3. 去掉每行首尾空格 + 连续空格 =====
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        # 把连续空格压缩成一个
        line = re.sub(r'[ \t\f\v\u00a0]+', ' ', line)
        # 去掉首尾空格
        line = line.strip()
        cleaned_lines.append(line)

    # ===== 4. 去掉过多空行（连续空行保留1个） =====
    result_lines = []
    prev_empty = False
    for line in cleaned_lines:
        is_empty = (line == '')
        if is_empty and prev_empty:
            continue  # 跳过连续空行
        result_lines.append(line)
        prev_empty = is_empty

    return '\n'.join(result_lines)

def parse_document(doc_id: str, file_path: str, ext: str):
    logger=logging.getLogger(__name__)
    db = SessionLocal()
    try:
        content = ""
        chunks = []

        if ext == ".txt":
            logger.info(f"处理 TXT 文档: {file_path}")
            with open(file_path, "r", encoding="utf-8") as f:
                content = clean_text(f.read())
            # 直接保存 chunks（无页码）
            chunks = process_and_save_chunks(db, doc_id, content)

        elif ext == ".pdf":
            logger.info(f"处理 PDF 文档: {file_path}")
            with pymupdf.open(file_path) as doc:
                page_texts = [clean_text(page.get_text()) for page in doc]
                for i, t in enumerate(page_texts, 1):
                    logger.info(f"第{i}页文本样本: {t[:200]}")
                page_nums = list(range(1, len(page_texts) + 1))
                # 保存 chunks，并传递页码信息
                chunks = process_and_save_chunks(db, doc_id, page_texts, page_nums)

                logger.info(f"PDF的页码总数为：{page_nums}")


        else:
            # 可选的错误处理
            raise ValueError(f"不支持的文件类型: {ext}")
        db.flush()  # 关键：确保 chunk 记录能被后面查询到
        doc_record = db.query(Document).filter(Document.document_id == doc_id).first()
        if not doc_record:
            raise ValueError(f"文档记录不存在: {doc_id}")
        chunk_count = vectorize_chunks(chunks, doc_record.filename)
        # 更新文档状态
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
