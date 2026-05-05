import logging
import threading
from pathlib import Path
from typing import Any

import jieba
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi
from sqlalchemy.orm import joinedload

from config import settings
from database import SessionLocal
from models.document import DocumentChunk


logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
STOPWORDS_PATH = BASE_DIR / "resources" / "bm25_stopwords.txt"

_bm25_lock = threading.RLock()
_bm25_index: BM25Okapi | None = None
_bm25_documents: list[Document] = []
_bm25_dirty = True


def load_stopwords() -> set[str]:
    if not STOPWORDS_PATH.exists():
        return set()

    return {
        line.strip().lower()
        for line in STOPWORDS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


BM25_STOPWORDS = load_stopwords()


def tokenize(text: str) -> list[str]:
    tokens = []
    for token in jieba.cut(text):
        token = token.strip()
        if not token:
            continue
        if token.lower() in BM25_STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def _chunk_to_document(chunk: DocumentChunk) -> Document:
    return Document(
        page_content=chunk.content,
        metadata={
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "chunk_index": chunk.chunk_index,
            "page_number": chunk.page_number,
            "source": chunk.source,
            "filename": chunk.document.filename if chunk.document else "",
        },
    )


def load_chunk_documents() -> list[Document]:
    db = SessionLocal()
    try:
        chunks = (
            db.query(DocumentChunk)
            .options(joinedload(DocumentChunk.document))
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
            .all()
        )
        return [_chunk_to_document(chunk) for chunk in chunks]
    finally:
        db.close()


def build_bm25_index() -> None:
    """Rebuild BM25 index from document_chunks table and cache it in memory."""
    global _bm25_index, _bm25_documents, _bm25_dirty

    with _bm25_lock:
        documents = load_chunk_documents()
        tokenized_corpus = [tokenize(doc.page_content) for doc in documents]

        _bm25_documents = documents
        _bm25_index = BM25Okapi(tokenized_corpus) if tokenized_corpus else None
        _bm25_dirty = False

        logger.info("BM25 索引构建完成，chunks=%s", len(_bm25_documents))


def mark_bm25_dirty() -> None:
    """Mark cache stale after document chunks are created, deleted, or rebuilt."""
    global _bm25_dirty
    with _bm25_lock:
        _bm25_dirty = True
        logger.info("BM25 索引已标记为待刷新")


def _ensure_bm25_index() -> tuple[BM25Okapi | None, list[Document]]:
    if _bm25_dirty or _bm25_index is None:
        build_bm25_index()
    return _bm25_index, _bm25_documents


def bm25_search(query: str, top_k: int = 10) -> list[tuple[Any, float]]:
    tokenized_query = tokenize(query)
    if not tokenized_query:
        return []

    bm25, documents = _ensure_bm25_index()
    if bm25 is None or not documents:
        return []

    scores = bm25.get_scores(tokenized_query)
    doc_scores = sorted(zip(documents, scores), key=lambda x: x[1], reverse=True)

    return [
        (doc, float(score))
        for doc, score in doc_scores[:top_k]
        if score >= settings.BM25_MIN_SCORE
    ]
