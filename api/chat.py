import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from services.rag_service import RagService

rag_service = RagService()   # 应用启动时创建一次
router=APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/stream")
async def chat_stream(
        message: str,
        user_id: str = "default_user",
        session_id: str = "default",
        top_k: int = 5,
):
    def event_generator():
        for event in rag_service.stream_answer(
            query=message,
            user_id=user_id,
            session_id=session_id,
            top_k=top_k,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
