# Design Changelog

Significant iterations only. Entries are newest first.

---

## v7 — Fixture-driven recall quality loop (pytest + JSON fixtures)

**What changed:** Added recall-quality fixtures (`fixtures/recall_fixture.json`, `fixtures/multi_hop_fixture.json`) and an integration harness (`tests/test_fixtures_extended.py`) that ingests turns through `POST /turns` and scores `POST /recall` by expected-substring hits. Added a third fixture (`fixtures/cleanup_search_fixture.json`) to assert `/search` works and `DELETE /sessions/{id}` actually clears session data.

**Why:** Manual curls don’t catch regressions, especially multi-hop (“city + dog name”) and cleanup behavior. The project needed a repeatable loop to tune extraction and retrieval against something concrete.

**Result:** `/recall` quality is asserted with explicit numeric thresholds:
- `fixtures/recall_fixture.json`: **7 total checks** (5 probes; expects sizes = 1,1,1,2,2) with threshold **≥ 0.60**, i.e. must hit at least **5/7** expected substrings.
- `fixtures/multi_hop_fixture.json`: **3 total checks** (3 probes; expects sizes = 1,1,1) with threshold **≥ 0.66**, i.e. must hit at least **2/3** expected substrings.

Cleanup/search behavior is also asserted end-to-end: `/search` must return at least one result containing the expected substring before `DELETE /sessions/{id}`, and must return an empty result list after deletion.

**Next:** Add per-probe diagnostics (hit/miss breakdown) so improvements are attributable at the individual query level.

---

## v6 — Budgeted context assembly + “return nothing when irrelevant”

**What changed:** Implemented budgeted context assembly for `/recall` with an explicit priority order: stable user facts/preferences first, then query-relevant memories, then recent turns. Added a strict gate that returns `{"context": "", "citations": []}` when nothing is relevant.

**Why:** The eval includes noise prompts (e.g. unrelated networking questions) where *any* context is harmful. Token budgets force tradeoffs; without a policy, the service tends to include verbose or recent-but-irrelevant content.

**Result:** `/recall` respects a hard “no signal → empty context” rule. This is asserted by `tests/test_persistence_and_quality.py::test_implicit_pet_extraction_and_noise_resistance`, which posts an unrelated query (“Explain TCP congestion control algorithms”) and requires `context == ""`.

**Next:** Prefer higher-confidence stable facts when budgets are extremely small and enforce a tighter snippet length cap.

---

## v5 — Hybrid retrieval fusion (FTS5 + cosine + lexical overlap)

**What changed:** Added hybrid retrieval to `/search` and `/recall`: FTS5 (BM25-style), cosine similarity over stored embeddings, and lexical overlap, fused into a single ranking with light recency tie-breaking.

**Why:** Keyword-heavy queries (“dog’s name”, “where do they live”) are often better served by exact token matches, while paraphrases need semantic signal. Single-signal ranking was brittle in fixtures.

**Result:** `/search` and `/recall` are not a single-signal shortcut:
- FTS5 is exercised via the cleanup/search fixture (expects keyword hit on “peanut”).
- Cosine similarity is exercised by `tests/test_embeddings.py` (related text must score ≥ unrelated text).

**Next:** Consider explicit reciprocal-rank-fusion and a lightweight reranker for long-tail edge cases.

---

## v4 — Optional OpenAI embeddings with deterministic local fallback

**What changed:** Made embeddings optional: if `OPENAI_API_KEY` is set, use OpenAI embeddings; otherwise generate deterministic local hash embeddings. Stored the vector per memory row so retrieval can use cosine similarity as one signal in the hybrid scorer.

**Why:** Evaluator setup must work with `docker compose up` and no external keys. But semantic signal materially helps recall when the query doesn’t share exact tokens with stored values.

**Result:** Semantic ranking signal exists even with zero external dependencies. When `OPENAI_API_KEY` is unset, embeddings remain deterministic (hash-based) so tests and fixtures are stable across environments; when set, quality can be upgraded without changing API surface.

**Next:** Add simple vector caching/compaction if memory volume grows, and consider embedding the `combined_text` for turn-level retrieval.

---

## v3 — Mutable facts via supersession chains (`active` + `supersedes`)

**What changed:** Implemented mutable-key evolution with `active` flags and `supersedes` links (`fact:employment`, `fact:location`, `fact:pet`, topic opinions, etc.), deactivating prior active rows on contradiction.

**Why:** Append-only storage returned stale facts in recall and failed contradiction handling requirements (e.g., previous employer/location persisting as current truth).

**Result:** `/recall` prefers the current fact while `/users/{user_id}/memories` preserves history for inspection (covered by `tests/test_persistence_and_quality.py::test_fact_supersession_chain` and `test_opinion_evolution_supersession`).

**Next:** Expand contradiction rules for softer opinion arcs (not only direct overwrite patterns).

---

## v2 — Structured extraction (facts/preferences/opinions/events), not raw logs

**What changed:** Built a deterministic extractor that turns user messages into typed memories (employment, location/relocation, pets, allergies, diet/style preferences, topic opinions, corrections). Normalized values are stored as memory rows with keys and confidence, designed to be inspectable via `/users/{user_id}/memories`.

**Why:** Review explicitly inspects `/users/{user_id}/memories`. If it contains raw message blobs instead of structured memories, it reads as “message log” rather than a memory system.

**Result:** The memory table contains normalized facts (e.g. `Lives in Berlin`, `Moved from NYC to Berlin`, `Has a dog named Biscuit`) rather than raw turn text (covered by contract/integration tests).

**Next:** Expand normalization for correction phrasing to reduce any remaining raw-sentence-shaped event values.

---

## v1 — Contract-first, single-container baseline (FastAPI + SQLite/FTS5)

**What changed:** Shipped the contract endpoints with a synchronous `/turns` path (persist → extract → index → return 201), backed by SQLite (WAL) persisted on a named Docker volume.

**Why:** Needed a stable baseline satisfying endpoint contract, immediate read-after-write correctness, and restart persistence before recall quality optimization.

**Result:** End-to-end service became deployable via Docker Compose with inspectable health, write, recall, search, and cleanup paths.

**Next:** Iteratively improve extraction fidelity and retrieval quality under fixed contract constraints.

