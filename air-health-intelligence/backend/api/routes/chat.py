"""
api/routes/chat.py
AI assistant chat endpoints.
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Query

from backend.agents.health_ai_agent import health_ai_agent
from backend.db.mongodb import col_chat_history
from backend.models.alert import ChatMessage, ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["AI Chat"])


# ── POST /chat/message ────────────────────────────────────────────────────────

@router.post("/message", response_model=ChatResponse)
async def send_message(body: ChatRequest):
    """
    Send a message to the AI health assistant.
    The agent retrieves live air quality context automatically.
    """
    if not body.session_id:
        body.session_id = str(uuid.uuid4())
    return await health_ai_agent.chat(body)


# ── GET /chat/history ─────────────────────────────────────────────────────────

@router.get("/history", response_model=List[ChatMessage])
async def get_history(
    session_id: str = Query(..., description="Session UUID"),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Retrieve conversation history for a session."""
    cursor = col_chat_history().find(
        {"session_id": session_id},
        sort=[("timestamp", 1)],
    ).limit(limit)
    docs = await cursor.to_list(length=limit)
    return [ChatMessage(role=d["role"], content=d["content"], timestamp=d["timestamp"]) for d in docs]


# ── POST /chat/new-session ────────────────────────────────────────────────────

@router.post("/new-session")
async def new_session():
    """Generate a fresh session ID."""
    return {"session_id": str(uuid.uuid4())}
