from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from services.search_service import  search_similar_with_score

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("/")
async def search(query: str, top_k: int = 3):
    # 获取带分数的检索结果
    docs_with_scores = search_similar_with_score(query, top_k)

    results = []
    for doc, score in docs_with_scores:
        # doc 是 LangChain 的 Document 对象，包含 page_content 和 metadata
        metadata = doc.metadata
        results.append({
            "chunk_id": metadata.get("chunk_id"),  # 需要你在 store_to_chroma 时存入
            "document_id": metadata.get("document_id"),
            "score": round(score, 4),  # 保留四位小数
            "content": doc.page_content,  # 文本内容
            "metadata": {
                "source": metadata.get("source"),  # 如 "公司制度.pdf"
                "page": metadata.get("page_number")  # 如 3
            }
        })

    return {
        "code": 0,
        "message": "success",
        "data": {
            "query": query,
            "results": results
        }
    }