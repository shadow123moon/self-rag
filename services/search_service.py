import logging
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_chroma import Chroma

from config import settings
from services.bm25_service import bm25_search
from services.embedding_service import embedding_provider

logger = logging.getLogger(__name__)


class LangChainEmbeddingAdapter(Embeddings):
    """把统一 embedding provider 适配给 LangChain Chroma。"""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return embedding_provider.embed_texts(texts)

    def embed_query(self, text: str) -> list[float]:
        return embedding_provider.embed_query(text)


class SearchService:
    def __init__(self):
        self.vector_store = Chroma(
            collection_name=settings.CHROMA_COLLECTION_NAME,
            embedding_function=LangChainEmbeddingAdapter(),
            persist_directory=settings.CHROMA_PERSIST_DIR,
        )

    def search_similar(self, query: str, top_k: int = 3) -> list[Any]:
        return self.vector_store.similarity_search(
            self._validate_query(query),
            k=self._normalize_top_k(top_k),
        )

    def search_similar_with_score(
        self,
        query: str,
        top_k: int = 3,
    ) -> list[tuple[Any, float]]:
        return self.vector_store.similarity_search_with_score(
            self._validate_query(query),
            k=self._normalize_top_k(top_k),
        )

    @staticmethod
    def _validate_query(query: str) -> str:
        if not query or not query.strip():
            raise ValueError("查询文本不能为空")
        return query.strip()

    @staticmethod
    def _normalize_top_k(top_k: int) -> int:
        if top_k <= 0:
            raise ValueError("top_k 必须大于 0")
        return top_k


search_service = SearchService()


def search_similar(query: str, top_k: int = 3) -> list[Any]:
    """仅返回文档列表，不带分数。"""
    return search_service.search_similar(query, top_k)


def search_similar_with_score(query: str, top_k: int = 3) -> list[tuple[Any, float]]:
    """返回 (document, score) 列表，score 语义由 Chroma collection 距离配置决定。"""
    return search_service.search_similar_with_score(query, top_k)


def hybrid_search(
    query: str,
    top_k: int = 5,
    vector_top_k: int = 10,
    bm25_top_k: int = 10,
):
    bm25_results=bm25_search(query, bm25_top_k)
    vector_raw = search_similar_with_score(query, vector_top_k)
    vector_results = [
        (doc, distance)
        for doc, distance in vector_raw
        if distance <= settings.RAG_MAX_DISTANCE
    ]
    logger.debug(
        "Hybrid检索 | query=%r max_dist=%.3f vector_raw=%d vector_kept=%d "
        "best_vector=%.4f bm25=%d best_bm25=%.2f",
        query, settings.RAG_MAX_DISTANCE,
        len(vector_raw), len(vector_results),
        vector_raw[0][1] if vector_raw else -1,
        len(bm25_results),
        bm25_results[0][1] if bm25_results else 0,
    )
    best_bm25_score = bm25_results[0][1] if bm25_results else 0

    has_vector_signal = len(vector_results) > 0
    has_strong_bm25_signal =  best_bm25_score >= settings.BM25_STRONG_SCORE
    if not has_vector_signal and not has_strong_bm25_signal:
        return []

    rrf_scores = {}
    doc_map = {}
    rrf_k=60
    # BM25 排名打分
    for rank,  (doc, score)in enumerate(bm25_results):
        chunk_id = doc.metadata["chunk_id"]
        if chunk_id not in rrf_scores:
            rrf_scores[chunk_id] = 0
        rrf_scores[chunk_id] += 1 / (rrf_k + rank+1)
        doc_map[chunk_id] =doc

    # 语义排名打分
    for rank, (doc, score) in enumerate(vector_results):
        chunk_id = doc.metadata["chunk_id"]
        if chunk_id not in rrf_scores:
            rrf_scores[chunk_id] = 0
        rrf_scores[chunk_id] += 1 / (rrf_k + rank+1)
        doc_map[chunk_id] = doc
    sorted_chunk_ids = sorted(
        rrf_scores.keys(),
        key=lambda chunk_id: rrf_scores[chunk_id],
        reverse=True,
    )

    result = [
        (doc_map[chunk_id], rrf_scores[chunk_id])
        for chunk_id in sorted_chunk_ids[:top_k]
    ]
    return result


