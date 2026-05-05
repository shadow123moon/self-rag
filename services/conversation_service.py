import json
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models.conversation import ConversationMessage, ConversationSession
from services.history_service import build_db_session_id


def _clean_value(value: str, default: str) -> str:
    return (value or default).strip() or default


def _raw_session_id(db_session_id: str, user_id: str) -> str:
    prefix = f"{_clean_value(user_id, 'default_user')}__"
    if db_session_id.startswith(prefix):
        return db_session_id[len(prefix):]
    return db_session_id


def _format_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_references(value: str | None) -> list | None:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _format_session(db: Session, session: ConversationSession) -> dict:
    last_message = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.session_id == session.session_id)
        .order_by(ConversationMessage.created_at.desc())
        .first()
    )
    message_count = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.session_id == session.session_id)
        .count()
    )

    return {
        "session_id": _raw_session_id(session.session_id, session.user_id),
        "db_session_id": session.session_id,
        "user_id": session.user_id,
        "title": session.title,
        "status": session.status,
        "message_count": message_count,
        "last_message": last_message.content[:80] if last_message else "",
        "updated_at": _format_datetime(session.updated_at),
        "created_at": _format_datetime(session.created_at),
    }


def list_conversations(db: Session, user_id: str) -> list[dict]:
    clean_user_id = _clean_value(user_id, "default_user")
    sessions = (
        db.query(ConversationSession)
        .filter(ConversationSession.user_id == clean_user_id)
        .order_by(ConversationSession.updated_at.desc())
        .all()
    )
    return [_format_session(db, session) for session in sessions]


def create_conversation(db: Session, user_id: str, title: str | None = None) -> dict:
    clean_user_id = _clean_value(user_id, "default_user")
    raw_session_id = uuid.uuid4().hex
    db_session_id = build_db_session_id(clean_user_id, raw_session_id)
    now = datetime.utcnow()

    session = ConversationSession(
        session_id=db_session_id,
        user_id=clean_user_id,
        title=_clean_value(title or "", "新对话"),
        status="active",
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _format_session(db, session)


def get_conversation_messages(db: Session, user_id: str, session_id: str) -> dict:
    clean_user_id = _clean_value(user_id, "default_user")
    db_session_id = build_db_session_id(clean_user_id, session_id)

    session = (
        db.query(ConversationSession)
        .filter(
            ConversationSession.user_id == clean_user_id,
            ConversationSession.session_id == db_session_id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="对话不存在")

    rows = (
        db.query(ConversationMessage)
        .filter(
            ConversationMessage.user_id == clean_user_id,
            ConversationMessage.session_id == db_session_id,
        )
        .order_by(ConversationMessage.created_at.asc())
        .all()
    )

    messages = []
    for row in rows:
        messages.append({
            "message_id": row.message_id,
            "session_id": _raw_session_id(row.session_id, clean_user_id),
            "user_id": row.user_id,
            "role": row.role,
            "content": row.content,
            "references": _parse_references(row.references_json),
            "created_at": _format_datetime(row.created_at),
        })

    return {
        "session": _format_session(db, session),
        "messages": messages,
    }


def delete_conversation(db: Session, user_id: str, session_id: str) -> dict:
    clean_user_id = _clean_value(user_id, "default_user")
    db_session_id = build_db_session_id(clean_user_id, session_id)

    session = (
        db.query(ConversationSession)
        .filter(
            ConversationSession.user_id == clean_user_id,
            ConversationSession.session_id == db_session_id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="对话不存在")

    deleted_session_id = _raw_session_id(session.session_id, clean_user_id)
    db.delete(session)
    db.commit()
    return {
        "session_id": deleted_session_id,
        "message": "对话已删除",
    }
