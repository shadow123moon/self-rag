import logging
from typing import Sequence

from openai import OpenAI

from config import settings


logger = logging.getLogger(__name__)


class EmbeddingProvider:
    """统一的 embedding provider，供写入向量和查询检索复用。"""

    def __init__(self, batch_size: int = 20):
        self.client = OpenAI(
            base_url=settings.EMBEDDING_URL,
            api_key=settings.EMBEDDING_KEY,
        )
        self.model = settings.EMBEDDING_MODEL
        self.batch_size = batch_size

    def embed_texts(
        self,
        texts: Sequence[str],
        batch_size: int | None = None,
    ) -> list[list[float]]:
        if not texts:
            return []

        effective_batch_size = batch_size or self.batch_size
        if effective_batch_size <= 0:
            raise ValueError("batch_size 必须大于 0")

        all_embeddings: list[list[float]] = []
        total = len(texts)
        for i in range(0, total, effective_batch_size):
            batch = list(texts[i:i + effective_batch_size])
            logger.info(
                "正在生成 embedding，批次 %s，数量 %s",
                i // effective_batch_size + 1,
                len(batch),
            )
            response = self.client.embeddings.create(
                model=self.model,
                input=batch,
            )
            batch_embeddings = sorted(response.data, key=lambda item: item.index)
            all_embeddings.extend([item.embedding for item in batch_embeddings])

        if len(all_embeddings) != total:
            raise RuntimeError("embedding 返回数量和输入文本数量不一致")

        return all_embeddings

    def embed_query(self, query: str) -> list[float]:
        if not query or not query.strip():
            raise ValueError("查询文本不能为空")
        return self.embed_texts([query])[0]


embedding_provider = EmbeddingProvider()
