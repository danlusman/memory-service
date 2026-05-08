from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .embeddings import cosine_similarity, embed_text
from .memory_logic import ExtractedMemory, classify_scope, make_key, similarity_score, tokenize


class MemoryStore:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS turns (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_id TEXT,
                timestamp TEXT NOT NULL,
                messages_json TEXT NOT NULL,
                combined_text TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                session_id TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                type TEXT NOT NULL,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL NOT NULL,
                embedding_json TEXT NOT NULL DEFAULT '[]',
                scope TEXT NOT NULL,
                supersedes TEXT,
                active INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
            USING fts5(memory_id UNINDEXED, user_id, session_id, type, category, value, content='');
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_turns_session_user ON turns(session_id, user_id);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memories_user_active ON memories(user_id, active, key);
            """
        )
        columns = [r["name"] for r in cur.execute("PRAGMA table_info(memories)").fetchall()]
        if "embedding_json" not in columns:
            cur.execute("ALTER TABLE memories ADD COLUMN embedding_json TEXT NOT NULL DEFAULT '[]';")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def insert_turn(self, session_id: str, user_id: str | None, timestamp: datetime, messages: list[dict[str, Any]], metadata: dict[str, Any]) -> str:
        turn_id = str(uuid.uuid4())
        combined_text = "\n".join([f"{m.get('role','unknown')}: {m.get('content','')}" for m in messages])
        self.conn.execute(
            """
            INSERT INTO turns(id, session_id, user_id, timestamp, messages_json, combined_text, metadata_json)
            VALUES(?,?,?,?,?,?,?)
            """,
            (turn_id, session_id, user_id, timestamp.isoformat(), json.dumps(messages), combined_text, json.dumps(metadata)),
        )
        self.conn.commit()
        return turn_id

    def upsert_memories(self, session_id: str, user_id: str | None, turn_id: str, extracted: list[ExtractedMemory], created_at_iso: str) -> None:
        cur = self.conn.cursor()
        for mem in extracted:
            mem_id = str(uuid.uuid4())
            key = make_key(mem.mem_type, mem.category)
            scope = classify_scope(mem.mem_type, mem.category)
            emb = embed_text(mem.value)
            supersedes = None
            if user_id and scope == "mutable":
                prev = cur.execute(
                    """
                    SELECT id, value FROM memories
                    WHERE user_id = ? AND key = ? AND active = 1
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (user_id, key),
                ).fetchone()
                if prev and prev["value"].lower() == mem.value.lower():
                    # Avoid duplicate active rows when the same fact arrives repeatedly.
                    continue
                if prev and prev["value"].lower() != mem.value.lower():
                    supersedes = prev["id"]
                    cur.execute("UPDATE memories SET active = 0, updated_at = ? WHERE id = ?", (created_at_iso, prev["id"]))
            cur.execute(
                """
                INSERT INTO memories(
                    id, user_id, session_id, turn_id, type, category, key, value, confidence, embedding_json, scope,
                    supersedes, active, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    mem_id,
                    user_id,
                    session_id,
                    turn_id,
                    mem.mem_type,
                    mem.category,
                    key,
                    mem.value,
                    mem.confidence,
                    json.dumps(emb),
                    scope,
                    supersedes,
                    1,
                    created_at_iso,
                    created_at_iso,
                ),
            )
            cur.execute(
                """
                INSERT INTO memories_fts(memory_id, user_id, session_id, type, category, value)
                VALUES(?,?,?,?,?,?)
                """,
                (mem_id, user_id or "", session_id, mem.mem_type, mem.category, mem.value),
            )
        self.conn.commit()

    def search_memories(self, query: str, session_id: str | None, user_id: str | None, limit: int) -> list[dict[str, Any]]:
        q_tokens = tokenize(query)
        q_emb = embed_text(query)
        query_for_fts = " ".join(q_tokens[:8]) if q_tokens else query
        clauses = ["m.active = 1"]
        params: list[Any] = []
        if user_id:
            clauses.append("m.user_id = ?")
            params.append(user_id)
        elif session_id:
            clauses.append("m.session_id = ?")
            params.append(session_id)
        where_clause = " AND ".join(clauses)
        try:
            bm25_rows = self.conn.execute(
                f"""
                SELECT m.*, bm25(memories_fts) AS rank
                FROM memories_fts
                JOIN memories m ON m.id = memories_fts.memory_id
                WHERE memories_fts MATCH ? AND {where_clause}
                ORDER BY rank
                LIMIT ?
                """,
                [query_for_fts, *params, max(limit * 3, 10)],
            ).fetchall()
        except sqlite3.OperationalError:
            bm25_rows = []
        results: dict[str, dict[str, Any]] = {}
        for idx, r in enumerate(bm25_rows):
            bm25_score = 1.0 / (1.0 + max(float(r["rank"]), 0.0))
            sim = similarity_score(query, r["value"])
            emb = json.loads(r["embedding_json"] or "[]")
            sem = max(0.0, cosine_similarity(q_emb, emb))
            fuse = 0.45 * bm25_score + 0.20 * sim + 0.35 * sem
            results[r["id"]] = {
                "id": r["id"],
                "content": r["value"],
                "score": fuse + (1.0 / (60 + idx)),
                "session_id": r["session_id"],
                "timestamp": r["updated_at"],
                "metadata": {"type": r["type"], "category": r["category"], "turn_id": r["turn_id"]},
                "turn_id": r["turn_id"],
            }
        for r in self.conn.execute(f"SELECT * FROM memories m WHERE {where_clause} ORDER BY m.updated_at DESC LIMIT ?", [*params, max(limit * 5, 20)]):
            sim = similarity_score(query, r["value"])
            emb = json.loads(r["embedding_json"] or "[]")
            sem = max(0.0, cosine_similarity(q_emb, emb))
            if sim <= 0 and sem < 0.2:
                continue
            base = 0.20 * sim + 0.35 * sem
            if r["id"] in results:
                results[r["id"]]["score"] += base
            else:
                results[r["id"]] = {
                    "id": r["id"],
                    "content": r["value"],
                    "score": base,
                    "session_id": r["session_id"],
                    "timestamp": r["updated_at"],
                    "metadata": {"type": r["type"], "category": r["category"], "turn_id": r["turn_id"]},
                    "turn_id": r["turn_id"],
                }
        ranked = sorted(results.values(), key=lambda x: x["score"], reverse=True)
        return ranked[:limit]

    def get_user_memories(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM memories
            WHERE user_id = ?
            ORDER BY key, updated_at DESC
            """,
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_turns(self, session_id: str, user_id: str | None, limit: int = 5) -> list[dict[str, Any]]:
        if user_id:
            rows = self.conn.execute(
                "SELECT * FROM turns WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM turns WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, session_id: str) -> None:
        self.conn.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))
        self.conn.execute("DELETE FROM memories WHERE session_id = ?", (session_id,))
        self.conn.execute("DELETE FROM memories_fts WHERE session_id = ?", (session_id,))
        self.conn.commit()

    def delete_user(self, user_id: str) -> None:
        self.conn.execute("DELETE FROM turns WHERE user_id = ?", (user_id,))
        self.conn.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
        self.conn.execute("DELETE FROM memories_fts WHERE user_id = ?", (user_id,))
        self.conn.commit()

    def health(self) -> bool:
        try:
            self.conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.DatabaseError:
            return False

