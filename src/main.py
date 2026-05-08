from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from .memory_logic import approx_tokens, extract_memories, now_iso, tokenize
from .models import Citation, RecallIn, RecallOut, SearchIn, SearchOut, SearchResult, TurnCreated, TurnIn
from .store import MemoryStore

DB_PATH = os.getenv("MEMORY_DB_PATH", "/data/memory.db")
AUTH_TOKEN = os.getenv("MEMORY_AUTH_TOKEN", "")
MAX_PAYLOAD_BYTES = int(os.getenv("MAX_PAYLOAD_BYTES", "1048576"))


def _authorized(request: Request) -> bool:
    if not AUTH_TOKEN:
        return True
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {AUTH_TOKEN}"


@asynccontextmanager
async def lifespan(_: FastAPI):
    app.state.store = MemoryStore(DB_PATH)
    try:
        yield
    finally:
        app.state.store.close()


app = FastAPI(title="memory-service", lifespan=lifespan)


@app.middleware("http")
async def guard_payload_and_auth(request: Request, call_next):
    if request.url.path != "/health" and not _authorized(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    body = await request.body()
    if len(body) > MAX_PAYLOAD_BYTES:
        return JSONResponse({"detail": "Payload too large"}, status_code=413)
    request._body = body
    return await call_next(request)


@app.exception_handler(ValidationError)
async def validation_exception_handler(_: Request, exc: ValidationError):
    return JSONResponse({"detail": exc.errors()}, status_code=422)


@app.exception_handler(json.JSONDecodeError)
async def json_decode_exception_handler(_: Request, __: json.JSONDecodeError):
    return JSONResponse({"detail": "Malformed JSON"}, status_code=400)


@app.exception_handler(Exception)
async def generic_exception_handler(_: Request, __: Exception):
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


@app.get("/health")
def health():
    if app.state.store.health():
        return {"status": "ok"}
    raise HTTPException(status_code=503, detail="store unavailable")


@app.post("/turns", response_model=TurnCreated, status_code=status.HTTP_201_CREATED)
async def post_turn(turn: TurnIn):
    store: MemoryStore = app.state.store
    turn_id = store.insert_turn(
        session_id=turn.session_id,
        user_id=turn.user_id,
        timestamp=turn.timestamp,
        messages=[m.model_dump() for m in turn.messages],
        metadata=turn.metadata,
    )
    extracted = []
    for msg in turn.messages:
        if msg.role != "user":
            continue
        extracted.extend(extract_memories(msg.content))
    if extracted:
        store.upsert_memories(
            session_id=turn.session_id,
            user_id=turn.user_id,
            turn_id=turn_id,
            extracted=extracted,
            created_at_iso=now_iso(),
        )
    return TurnCreated(id=turn_id)


@app.post("/search", response_model=SearchOut)
async def post_search(payload: SearchIn):
    store: MemoryStore = app.state.store
    rows = store.search_memories(payload.query, payload.session_id, payload.user_id, payload.limit)
    results = [
        SearchResult(
            content=r["content"],
            score=round(float(r["score"]), 6),
            session_id=r["session_id"],
            timestamp=r["timestamp"],
            metadata=r["metadata"],
        )
        for r in rows
    ]
    return SearchOut(results=results)


def _fits(lines: list[str], remaining: int) -> list[str]:
    while len(lines) > 1 and approx_tokens("\n".join(lines)) > remaining:
        lines.pop()
    return lines if len(lines) > 1 else []


def _assemble_context(stable: list[dict], relevant: list[dict], recent_turns: list[dict], max_tokens: int) -> tuple[str, list[Citation]]:
    parts: list[str] = []
    citations: list[Citation] = []
    remaining = max_tokens
    if stable:
        lines = ["## Known facts about this user"]
        for m in stable:
            lines.append(f"- {m['value']} (updated {m['updated_at'][:10]})")
        lines = _fits(lines, remaining)
        if lines:
            block = "\n".join(lines)
            t = approx_tokens(block)
            parts.append(block)
            remaining -= t
    if relevant:
        lines = ["## Query-relevant memories"]
        for r in relevant:
            lines.append(f"- {r['content']}")
            citations.append(Citation(turn_id=r["turn_id"], score=round(float(r["score"]), 6), snippet=r["content"][:220]))
        lines = _fits(lines, remaining)
        if lines:
            block = "\n".join(lines)
            t = approx_tokens(block)
            parts.append(block)
            remaining -= t
    if remaining > 64 and recent_turns:
        lines = ["## Relevant from recent conversations"]
        for trow in recent_turns:
            lines.append(f"- [{trow['timestamp'][:10]}] {trow['combined_text'][:180]}")
        lines = _fits(lines, remaining)
        if lines:
            parts.append("\n".join(lines))
    return ("\n\n".join(parts), citations[:20])


def _dedupe_rows(rows: list[dict], key_fields: tuple[str, ...]) -> list[dict]:
    seen: set[tuple] = set()
    out: list[dict] = []
    for row in rows:
        sig = tuple((row.get(k) or "").lower() if isinstance(row.get(k), str) else row.get(k) for k in key_fields)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(row)
    return out


@app.post("/recall", response_model=RecallOut)
async def post_recall(payload: RecallIn):
    store: MemoryStore = app.state.store
    relevant = store.search_memories(payload.query, payload.session_id, payload.user_id, 10)
    relevant = _dedupe_rows(relevant, ("content", "turn_id"))
    query_terms = set(tokenize(payload.query))
    profile_cues = {"user", "they", "their", "them", "live", "lives", "work", "works", "preference", "prefer", "allergy", "dog", "cat"}
    personal_query = bool(query_terms.intersection(profile_cues))
    if payload.user_id:
        all_user = store.get_user_memories(payload.user_id)
        stable = [m for m in all_user if int(m["active"]) == 1 and m["type"] in {"fact", "preference"}]
        # Noise resistance: only include stable facts likely relevant to the query.
        if personal_query:
            stable = stable[:12]
        else:
            stable = [m for m in stable if query_terms.intersection(set(tokenize(m["value"])))][:12]
        stable = _dedupe_rows(stable, ("key", "value"))
    else:
        stable = []
    recent = store.get_recent_turns(payload.session_id, payload.user_id, limit=4) if relevant else []
    if not relevant and not stable:
        return RecallOut(context="", citations=[])
    context, citations = _assemble_context(stable, relevant, recent, max(64, payload.max_tokens))
    return RecallOut(context=context, citations=citations)


@app.get("/users/{user_id}/memories")
async def get_user_memories(user_id: str):
    store: MemoryStore = app.state.store
    rows = store.get_user_memories(user_id)
    out = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "type": r["type"],
                "key": r["key"],
                "value": r["value"],
                "confidence": r["confidence"],
                "source_session": r["session_id"],
                "source_turn": r["turn_id"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "supersedes": r["supersedes"],
                "active": bool(r["active"]),
                "category": r["category"],
            }
        )
    return {"memories": out}


@app.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str):
    app.state.store.delete_session(session_id)
    return Response(status_code=204)


@app.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: str):
    app.state.store.delete_user(user_id)
    return Response(status_code=204)

