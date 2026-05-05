import json
from datetime import datetime

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from database import SessionLocal
from models.conversation import ConversationMessage, ConversationSession


def _clean_value(value: str, default: str) -> str:
    return (value or default).strip() or default


def build_db_session_id(user_id: str, session_id: str) -> str:
    clean_user_id = _clean_value(user_id, "default_user")
    clean_session_id = _clean_value(session_id, "default")
    return f"{clean_user_id}__{clean_session_id}"


def _guess_title(question: str) -> str:
    title = (question or "").strip()
    return title[:30] if title else "新对话"


def _ensure_session(db, user_id: str, session_id: str, question: str) -> None:
    clean_user_id = _clean_value(user_id, "default_user")
    db_session_id = build_db_session_id(clean_user_id, session_id)

    session = (
        db.query(ConversationSession)
        .filter(ConversationSession.session_id == db_session_id)
        .first()
    )

    now = datetime.utcnow()
    if session:
        session.updated_at = now
        return

    db.add(
        ConversationSession(
            session_id=db_session_id,
            user_id=clean_user_id,
            title=_guess_title(question),
            status="active",
            created_at=now,
            updated_at=now,
        )
    )


def get_history_messages(user_id: str, session_id: str) -> list[BaseMessage]:
    clean_user_id = _clean_value(user_id, "default_user")
    db_session_id = build_db_session_id(clean_user_id, session_id)

    db = SessionLocal()
    try:
        rows = (
            db.query(ConversationMessage)
            .filter(
                ConversationMessage.user_id == clean_user_id,
                ConversationMessage.session_id == db_session_id,
            )
            .order_by(ConversationMessage.created_at.asc())
            .all()
        )

        result: list[BaseMessage] = []

        for row in rows:
            if row.role == "user":
                result.append(HumanMessage(content=row.content))
            elif row.role == "assistant":
                result.append(AIMessage(content=row.content))
            elif row.role == "system":
                result.append(SystemMessage(content=row.content))

        return result

    finally:
        db.close()


def save_chat_turn(user_id: str, session_id: str, question: str, answer: str, references: list[dict]) -> None:
    clean_user_id = _clean_value(user_id, "default_user")
    db_session_id = build_db_session_id(clean_user_id, session_id)

    db = SessionLocal()
    try:
        _ensure_session(db, clean_user_id, session_id, question)

        db.add(
            ConversationMessage(
                user_id=clean_user_id,
                session_id=db_session_id,
                content=question,
                role="user",
            )
        )

        db.add(
            ConversationMessage(
                user_id=clean_user_id,
                session_id=db_session_id,
                content=answer,
                role="assistant",
                references_json=json.dumps(references or [], ensure_ascii=False),
            )
        )

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
