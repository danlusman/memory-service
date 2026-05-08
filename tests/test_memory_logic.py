"""Deterministic unit checks for extraction helpers (no HTTP)."""
from __future__ import annotations

from src.memory_logic import extract_memories


def test_implicit_pet_sentence_capitalized_walking():
    text = "Walking Biscuit this morning before standup."
    mems = extract_memories(text)
    assert any(m.category == "pet" and "Biscuit" in m.value for m in mems)


def test_implicit_pet_sentence_lowercase_walking():
    text = "walking biscuit before standup"
    mems = extract_memories(text)
    assert any("biscuit" in m.value.lower() for m in mems)
