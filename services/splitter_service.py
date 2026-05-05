
from langchain_text_splitters import RecursiveCharacterTextSplitter
from typing import List, Union, Optional
import uuid
from config import settings
from sqlalchemy.orm import Session
from models.document import DocumentChunk
import logging
logger = logging.getLogger(__name__)
# 全局单例，可复用
_splitter = RecursiveCharacterTextSplitter(
    chunk_size=settings.chunk_size,
    chunk_overlap=settings.chunk_overlap,
    separators=settings.separators,  # 中英文混合分隔符
    length_function=len,
)


def split_text_into_chunks(text: str) -> List[str]:
    """切分文本，带兜底机制，保证至少返回一个 chunk"""
    if not text.strip():
        return []

    # 用递归分割器尝试
    chunks = _splitter.split_text(text)

    # 兜底：如果分割器返回空，手动按固定长度切分
    if not chunks:
        chunk_size = settings.chunk_size
        overlap = settings.chunk_overlap
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start = end - overlap
            if start >= len(text):
                break
    return chunks
def save_chunks(
    db: Session,
    document_id: str,
    text_chunks: List[str],
    page_numbers: Optional[List[int]] = None,
) -> List[DocumentChunk]:
    chunk_objs = []
    for idx, content in enumerate(text_chunks):
        chunk = DocumentChunk(
            chunk_id=uuid.uuid4().hex,
            document_id=document_id,
            chunk_index=idx,
            content=content,
            page_number=page_numbers[idx] if page_numbers else None,
            source="document",
        )
        db.add(chunk)
        chunk_objs.append(chunk)
    return chunk_objs

def process_and_save_chunks(
    db: Session,
    document_id: str,
    text: Union[str, List[str]],
    page_numbers: Optional[List[int]] = None,
) -> List[DocumentChunk]:
    """兼容两种输入：整个文本字符串，或已经按页拆分好的文本列表"""
    if isinstance(text, str):
        chunks_text = split_text_into_chunks(text)
    else:
        # 如果传入的是列表，对每页分别切分，并保留页码
        all_chunks = []
        all_page_nums = []
        for pg_num, page_text in zip(page_numbers or [], text):
            page_chunks = split_text_into_chunks(page_text)
            logger.info(f"第{pg_num}页文本长度 {len(page_text)}，切分成 {len(page_chunks)} 个片段")
            all_chunks.extend(page_chunks)
            all_page_nums.extend([pg_num] * len(page_chunks))
        return save_chunks(db, document_id, all_chunks, all_page_nums)
    return save_chunks(db, document_id, chunks_text, page_numbers)