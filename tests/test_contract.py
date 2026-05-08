from __future__ import annotations

from datetime import datetime, timezone


def _turn_payload(session_id: str, user_id: str | None, text: str):
    return {
        "session_id": session_id,
        "user_id": user_id,
        "messages": [
            {"role": "user", "content": text},
            {"role": "assistant", "content": "ack"},
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": {},
    }


def test_contract_roundtrip(client):
    r = client.get("/health")
    assert r.status_code == 200
    w = client.post("/turns", json=_turn_payload("s1", "u1", "I moved to Berlin from NYC."))
    assert w.status_code == 201
    rid = w.json()["id"]
    assert isinstance(rid, str)
    recall = client.post(
        "/recall",
        json={"query": "Where does user live?", "session_id": "s1", "user_id": "u1", "max_tokens": 256},
    )
    assert recall.status_code == 200
    body = recall.json()
    assert "context" in body
    assert "citations" in body


def test_concurrent_sessions_do_not_bleed(client):
    client.post("/turns", json=_turn_payload("s-a", "u-a", "I live in Tokyo."))
    client.post("/turns", json=_turn_payload("s-b", "u-b", "I live in Paris."))
    ra = client.post("/recall", json={"query": "where live", "session_id": "s-a", "user_id": "u-a", "max_tokens": 256}).json()
    rb = client.post("/recall", json={"query": "where live", "session_id": "s-b", "user_id": "u-b", "max_tokens": 256}).json()
    assert "Tokyo" in ra["context"]
    assert "Paris" not in ra["context"]
    assert "Paris" in rb["context"]


def test_malformed_and_unicode_input(client):
    bad = client.post("/turns", content="{broken", headers={"Content-Type": "application/json"})
    assert bad.status_code in (400, 422)
    missing = client.post("/turns", json={"session_id": "x"})
    assert missing.status_code == 422
    uni = client.post("/turns", json=_turn_payload("s-u", "u-u", "I love ramen 🍜 and 東京 life."))
    assert uni.status_code == 201


def test_delete_contract(client):
    client.post("/turns", json=_turn_payload("s-del", "u-del", "I work at Acme Corp."))
    d1 = client.delete("/sessions/s-del")
    assert d1.status_code == 204
    d2 = client.delete("/users/u-del")
    assert d2.status_code == 204


def test_search_contract_shape(client):
    client.post("/turns", json=_turn_payload("s-search", "u-search", "I live in Berlin and prefer concise replies."))
    r = client.post("/search", json={"query": "where live", "session_id": "s-search", "user_id": "u-search", "limit": 5})
    assert r.status_code == 200
    data = r.json()
    assert "results" in data and isinstance(data["results"], list)
    if data["results"]:
        row = data["results"][0]
        for key in ("content", "score", "session_id", "timestamp", "metadata"):
            assert key in row


def test_recall_validation_bounds(client):
    bad = client.post("/recall", json={"query": "", "session_id": "s1", "user_id": "u1", "max_tokens": 12})
    assert bad.status_code == 422

