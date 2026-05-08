from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str = Field(min_length=1)
    name: str | None = None


class TurnIn(BaseModel):
    session_id: str = Field(min_length=1)
    user_id: str | None = None
    messages: list[Message] = Field(min_length=1)
    timestamp: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class TurnCreated(BaseModel):
    id: str


class RecallIn(BaseModel):
    query: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    user_id: str | None = None
    max_tokens: int = Field(default=1024, ge=64, le=8192)


class Citation(BaseModel):
    turn_id: str
    score: float
    snippet: str


class RecallOut(BaseModel):
    context: str
    citations: list[Citation]


class SearchIn(BaseModel):
    query: str = Field(min_length=1)
    session_id: str | None = None
    user_id: str | None = None
    limit: int = Field(default=10, ge=1, le=100)


class SearchResult(BaseModel):
    content: str
    score: float
    session_id: str
    timestamp: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchOut(BaseModel):
    results: list[SearchResult]

