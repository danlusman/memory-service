from __future__ import annotations

import importlib
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient


def _turn(session_id: str, user_id: str, text: str):
    return {
        "session_id": session_id,
        "user_id": user_id,
        "messages": [{"role": "user", "content": text}, {"role": "assistant", "content": "ok"}],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": {},
    }


def test_restart_persistence(tmp_path: Path):
    db = tmp_path / "persist.db"
    os.environ["MEMORY_DB_PATH"] = str(db)
    import src.main as main_mod

    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c1:
        w = c1.post("/turns", json=_turn("s1", "u1", "I just joined Notion."))
        assert w.status_code == 201
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c2:
        rec = c2.post("/recall", json={"query": "where work", "session_id": "s2", "user_id": "u1", "max_tokens": 128})
        assert rec.status_code == 200
        assert "Notion" in rec.json()["context"]


def test_fact_supersession_chain(client):
    client.post("/turns", json=_turn("s-old", "u-emp", "I work at Stripe as an engineer."))
    client.post("/turns", json=_turn("s-new", "u-emp", "I just joined Notion as a PM."))
    mems = client.get("/users/u-emp/memories").json()["memories"]
    active_jobs = [m for m in mems if m["key"] == "fact:employment" and m["active"]]
    assert len(active_jobs) == 1
    assert "Notion" in active_jobs[0]["value"]
    assert any((not m["active"]) and ("Stripe" in m["value"]) for m in mems)


def test_opinion_evolution_supersession(client):
    client.post("/turns", json=_turn("s-op1", "u-op", "I love TypeScript."))
    client.post("/turns", json=_turn("s-op2", "u-op", "TypeScript generics are getting annoying."))
    mems = client.get("/users/u-op/memories").json()["memories"]
    ts_opinions = [m for m in mems if m["type"] == "opinion" and m["category"] == "topic:typescript"]
    active = [m for m in ts_opinions if m["active"]]
    assert len(active) == 1
    assert "frustrated" in active[0]["value"].lower()
    assert any(not m["active"] for m in ts_opinions)


def test_implicit_pet_extraction_and_noise_resistance(client):
    client.post("/turns", json=_turn("s-pet", "u-pet", "Walking Biscuit this morning before standup."))
    mems = client.get("/users/u-pet/memories").json()["memories"]
    assert any("Biscuit" in m["value"] for m in mems)
    unrelated = client.post(
        "/recall",
        json={"query": "Explain TCP congestion control algorithms", "session_id": "s-pet", "user_id": "u-pet", "max_tokens": 200},
    )
    assert unrelated.status_code == 200
    assert unrelated.json()["context"] == ""


def test_duplicate_fact_ingestion_does_not_create_active_duplicates(client):
    text = "I just moved to Berlin from NYC last month."
    client.post("/turns", json=_turn("s-dedup-1", "u-dedup", text))
    client.post("/turns", json=_turn("s-dedup-2", "u-dedup", text))
    mems = client.get("/users/u-dedup/memories").json()["memories"]
    active_locations = [m for m in mems if m["key"] == "fact:location" and m["active"]]
    assert len(active_locations) == 1
    assert active_locations[0]["value"] == "Lives in Berlin"


def test_relocation_extraction_is_normalized(client):
    client.post(
        "/turns",
        json=_turn(
            "s-reloc",
            "u-reloc",
            "I just moved to Berlin from NYC last month. My dog named Biscuit is loving the parks.",
        ),
    )
    mems = client.get("/users/u-reloc/memories").json()["memories"]
    reloc = [m for m in mems if m["key"] == "event:relocation"]
    assert len(reloc) == 1
    assert reloc[0]["value"] == "Moved from NYC to Berlin"


