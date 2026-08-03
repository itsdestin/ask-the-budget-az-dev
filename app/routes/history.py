"""HTTP surface over the local chat-history store (spec H1, H4).

Every route here reads and writes ONLY the analyst's own machine. Nothing in
this module touches the corpus or the shared drive.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from harness import history

router = APIRouter()


class RenameBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title cannot be blank")
        return v.strip()


def _row(t: history.Transcript) -> dict:
    return {
        "id": t.id, "title": t.title, "corpus": t.corpus,
        "created_at": t.created_at, "updated_at": t.updated_at,
        "title_is_manual": t.title_is_manual,
        "message_count": t.message_count,
    }


def _load_or_404(conversation_id: str) -> history.Transcript:
    # ValueError is the store refusing a non-bare id (traversal); surface it
    # as 400 rather than letting it become a 500.
    try:
        t = history.load(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="bad conversation id")
    if t is None:
        raise HTTPException(status_code=404, detail="no such conversation")
    return t


@router.get("/api/history")
def list_history() -> dict:
    # One read per file: `list_all` records message_count while stripping the
    # bodies, so the count never costs a second pass over the directory.
    return {"conversations": [_row(t) for t in history.list_all()]}


@router.get("/api/history/{conversation_id}")
def get_history(conversation_id: str) -> dict:
    t = _load_or_404(conversation_id)
    row = _row(t)
    row["messages"] = t.messages
    return row


@router.patch("/api/history/{conversation_id}")
def rename_history(conversation_id: str, body: RenameBody) -> dict:
    _load_or_404(conversation_id)
    history.rename(conversation_id, body.title)
    return _row(_load_or_404(conversation_id))


@router.delete("/api/history/{conversation_id}")
def delete_history(conversation_id: str) -> dict:
    _load_or_404(conversation_id)
    history.delete(conversation_id)
    return {"deleted": conversation_id}
