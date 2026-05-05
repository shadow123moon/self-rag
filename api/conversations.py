from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from services.conversation_service import (
    create_conversation,
    delete_conversation,
    get_conversation_messages,
    list_conversations,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("/")
async def conversations(user_id: str = "default_user", db: Session = Depends(get_db)):
    return {
        "code": 0,
        "message": "success",
        "data": list_conversations(db, user_id),
    }


@router.post("/")
async def create(user_id: str = "default_user", title: str | None = None, db: Session = Depends(get_db)):
    return {
        "code": 0,
        "message": "success",
        "data": create_conversation(db, user_id, title),
    }


@router.get("/{session_id}/messages")
async def messages(session_id: str, user_id: str = "default_user", db: Session = Depends(get_db)):
    return {
        "code": 0,
        "message": "success",
        "data": get_conversation_messages(db, user_id, session_id),
    }


@router.delete("/{session_id}")
async def delete(session_id: str, user_id: str = "default_user", db: Session = Depends(get_db)):
    return {
        "code": 0,
        "message": "success",
        "data": delete_conversation(db, user_id, session_id),
    }
