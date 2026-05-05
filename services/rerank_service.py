import time

import requests
from langchain_core.documents import Document
import logging

from config import settings
from services.search_service import hybrid_search
logger = logging.getLogger(__name__)

class RerankService:
    def __init__(self):
        # 硅基流动的 rerank 接口不是标准 OpenAI endpoint，需要手动拼接 path
        self.rerank_url = settings.RERANK_URL  # 完整 URL: https://api.siliconflow.cn/v1/rerank
        self.rerank_model = settings.RERANK_MODEL
        self.rerank_key=settings.RERANK_KEY
    def rerank_documents(self,query, docs, top_k):
        start = time.perf_counter()
        headers = {
            "Authorization": f"Bearer {self.rerank_key}",
            "Content-Type": "application/json"
        }
        TRUNCATE_CHARS = 1500
        payload = {
            "model": self.rerank_model,
            "query": query,
            "documents": [doc.page_content[:TRUNCATE_CHARS] for doc in docs],
            "top_n": top_k
        }
        response = requests.post(
            self.rerank_url,
            json=payload,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        results=[]
        data= response.json()
        for item in data.get("results", []):
            doc=docs[item['index']]
            score=item["relevance_score"]
            results.append((doc,score))

        elapsed = time.perf_counter() - start
        logger.info(
            "Reranker 完成 query=%r docs=%d top_k=%d elapsed=%.2fs",
            query[:50], len(docs), top_k, elapsed
        )
        return results

    def hybrid_search_with_rerank(self,query, top_k=5):
        candidates = hybrid_search(
            query,
            top_k=20,
            vector_top_k=20,  # ← 必须扩
            bm25_top_k=20,  # ← 必须扩
        )
        if not candidates:
            return []
        try:
            docs = [doc for doc, _ in candidates]

            return self.rerank_documents(query, docs, top_k=top_k)
        except Exception as e:
            logger.warning("Reranker 调用失败，降级到 hybrid 原始结果: %s", e)
            return candidates[:top_k]  # ← 至少不挂


rerank_service = RerankService()