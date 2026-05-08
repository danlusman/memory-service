# Design Log

This changelog tracks only significant design iterations.  
Each entry records what was attempted, what was observed, and why direction changed.

Entries are newest first.

---

## v7 — Docker/runtime reproducibility and deterministic test DB isolation

**Tried:** Running local edits with plain `docker compose up -d` and relying on fixture-level env changes without reloading `src.main`.

**Observed:** App code is image-baked (`COPY src`) and not bind-mounted, so `up -d` reused stale images after source changes. In tests, module-level `DB_PATH` could stay pinned across runs, causing confusing cross-test DB behavior.

**Direction change:** Standardized docs around `docker compose up -d --build` for edited code paths, added optional `docker compose watch`, and reloaded `src.main` in the pytest fixture after setting `MEMORY_DB_PATH`.

**Result:** Reproducible local/dev flow and deterministic test isolation.

---

## v6 — Implicit pet extraction and noise resistance hardening

**Tried:** A simple lowercase-only implicit pattern, then broad case-insensitive matching.

**Observed:** Natural phrasing like `Walking Biscuit...` intermittently failed in Docker runs, and broad patterns risked false positives (e.g., non-name tokens after verbs).

**Direction change:** Switched to scoped case-insensitive verb matching with proper-noun-first capture, then guarded lowercase fallback with a small stoplist; added dedicated unit + integration coverage.

**Result:** Reliable implicit pet extraction with better noise resistance.

---

## v5 — Recall quality loop driven by scripted fixtures

**Tried:** Manual curl checks and ad-hoc reasoning about recall quality.

**Observed:** Manual checks under-detected regressions, especially multi-hop and noise scenarios.

**Direction change:** Added fixture-driven quality tests (`fixtures/*.json` + `tests/test_fixtures_extended.py`) with threshold assertions, and tightened recall gating/context clipping.

**Result:** Repeatable quality regression loop and stronger confidence in `/recall`.

---

## v4 — Hybrid retrieval instead of single-signal search

**Tried:** Keyword-dominant retrieval and simple lexical ranking.

**Observed:** Exact-match paths missed paraphrased memory queries; semantic-only ranking risked spurious matches.

**Direction change:** Introduced fused ranking across FTS5, embedding cosine similarity, and lexical overlap; kept deterministic local embedding fallback with optional OpenAI embeddings.

**Result:** Better balance between precision and semantic recall without external hard dependency.

---

## v3 — Fact evolution via supersession chains

**Tried:** Append-only memory records and overwrite-like behavior.

**Observed:** Contradictions (e.g., employment/location changes) need both current truth for recall and historical traceability for inspection.

**Direction change:** Implemented mutable-key supersession (`active` + `supersedes`) so new facts deactivate prior active rows while preserving history.

**Result:** Recall favors current state; `/users/{user_id}/memories` still exposes full evolution.

---

## v2 — Structured extraction instead of raw message storage

**Tried:** Persisting turns with minimal derivation.

**Observed:** Raw logs alone are weak for targeted recall and do not satisfy memory-inspection expectations.

**Direction change:** Added deterministic extraction pipeline for facts, preferences, opinions, corrections, and implicit cues into normalized memory rows.

**Result:** Inspectable structured memory store and higher-quality retrieval inputs.

---

## v1 — Contract-first, single-container foundation

**Tried:** Started from an empty repository and contract requirements.

**Observed:** Needed strict synchronous correctness (`/turns` write-to-read), simple ops, and restart persistence.

**Direction change:** Built FastAPI + SQLite (WAL) monolith with named Docker volume and required endpoints before optimization work.

**Result:** Stable baseline for subsequent extraction/retrieval iterations.

