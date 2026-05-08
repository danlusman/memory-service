"""Load JSON fixtures from fixtures/ and validate recall, search, and delete behavior."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "fixtures"


def _ingest(client: TestClient, data: dict) -> None:
    for convo in data["conversations"]:
        for t in convo["turns"]:
            payload = {
                "session_id": convo["session_id"],
                "user_id": convo["user_id"],
                "messages": t["messages"],
                "timestamp": t["timestamp"],
                "metadata": {},
            }
            r = client.post("/turns", json=payload)
            assert r.status_code == 201, r.text


def _recall_probe_score(client: TestClient, probes: list[dict], *, max_tokens: int = 512) -> float:
    hits = 0
    total = 0
    for p in probes:
        r = client.post("/recall", json={**p, "max_tokens": max_tokens})
        assert r.status_code == 200, r.text
        ctx = r.json().get("context", "").lower()
        for exp in p["expects"]:
            total += 1
            if exp.lower() in ctx:
                hits += 1
    return hits / max(1, total)


def test_recall_fixture_quality_regression(client: TestClient):
    data = json.loads((FIXTURE_DIR / "recall_fixture.json").read_text(encoding="utf-8"))
    _ingest(client, data)
    score = _recall_probe_score(client, data["probes"])
    assert score >= 0.6, f"recall_fixture score {score:.2f}"


def test_multi_hop_fixture_recall(client: TestClient):
    data = json.loads((FIXTURE_DIR / "multi_hop_fixture.json").read_text(encoding="utf-8"))
    _ingest(client, data)
    score = _recall_probe_score(client, data["probes"])
    assert score >= 0.66, f"multi_hop_fixture score {score:.2f}"


def test_cleanup_search_fixture_and_session_delete(client: TestClient):
    data = json.loads((FIXTURE_DIR / "cleanup_search_fixture.json").read_text(encoding="utf-8"))
    _ingest(client, data)
    sar = data["search_after_turns"]
    sr = client.post(
        "/search",
        json={
            "query": sar["query"],
            "session_id": sar["session_id"],
            "user_id": sar["user_id"],
            "limit": sar["limit"],
        },
    )
    assert sr.status_code == 200
    results = sr.json().get("results", [])
    assert results, "search should return allergy memory"
    need = sar["expect_substrings_in_any_result_content"]
    combined = " ".join(r.get("content", "").lower() for r in results)
    assert any(n.lower() in combined for n in need), combined

    d = client.delete(f"/sessions/{sar['session_id']}")
    assert d.status_code == 204

    sr2 = client.post(
        "/search",
        json={
            "query": sar["query"],
            "session_id": sar["session_id"],
            "user_id": sar["user_id"],
            "limit": sar["limit"],
        },
    )
    assert sr2.status_code == 200
    assert sr2.json().get("results") == []

    client.delete(f"/users/{sar['user_id']}")
