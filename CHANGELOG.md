_Format used for each iteration: **What changed**, **Why**, **Result (observed behavior/test outcome)**, **Next**._

## v1 - Contract-first skeleton

**What changed:** Implemented FastAPI service with all required endpoints and SQLite persistence model for turns + memories.

**Why:** Needed a strict baseline that passed the evaluator's HTTP contract before optimizing retrieval quality.

**Result:** Contract endpoints responded with correct status codes and shapes on manual smoke checks.

**Next:** Add real extraction logic; avoid storing raw chunks as memories.

---

## v2 - Structured extraction pass

**What changed:** Added rule-based extraction for employment, location, pets, dietary preferences, allergies, and simple opinions/corrections.

**Why:** A message log alone is not memory. Needed typed, inspectable records for `/users/{user_id}/memories`.

**Result:** Memory table became structured (`type/category/key/value/confidence/provenance`) and inspectable.

**Next:** Improve contradiction handling so stale facts stop surfacing.

---

## v3 - Fact evolution via supersession chain

**What changed:** Added mutable-key upsert logic (`employment`, `location`, `diet`, etc.) with `active` flag and `supersedes` pointer.

**Why:** Evaluations penalize append-only contradictions (e.g., Stripe vs Notion both active).

**Result:** Newest fact is active and old value preserved as inactive history.

**Next:** Retrieval quality still weak for keyword-heavy probes; add hybrid recall.

---

## v4 - Hybrid retrieval and budgeted recall assembly

**What changed:** Added FTS5 ranking + lexical similarity fusion + recency tie-break, plus section-priority context assembly under token budget.

**Why:** Pure nearest-neighbor style retrieval misses exact entity probes ("dog's name", "shellfish allergy").

**Result:** Query recall improved on internal fixture; stable facts now prioritized under tight token budgets.

**Next:** Add fixture-driven regression tests and persistence restart checks.

---

## v5 - Internal quality loop and hardening

**What changed:** Added contract tests, malformed input tests, concurrent-session tests, restart persistence test, and fixture-based recall quality scoring.

**Why:** Needed a repeatable internal eval loop and robustness checks to avoid regressions.

**Result:** Service now ships with automated quality guardrails and restart safety verification.

**Next:** Future iteration could add optional LLM extraction/reranking and opinion-arc summarization.

---

## v6 - Hard-problem alignment pass

**What changed:** Extended extraction to include implicit pet facts ("walking Biscuit"), relationship/family facts, and topic-scoped opinion memories. Added mutable supersession for topic opinions (e.g., TypeScript stance changes). Tightened recall with query-relevance gating to reduce unrelated context spill.

**Why:** The evaluation emphasizes extraction depth, contradiction handling beyond jobs/locations, and noise resistance. Earlier behavior handled facts well but opinion arcs and implicit cues were too shallow.

**Result:** Internal tests now explicitly cover opinion supersession, implicit-fact extraction, and unrelated-query empty-context behavior in addition to prior contract/persistence checks.

**Next:** Add optional LLM-assisted normalization for harder paraphrases and long-horizon opinion summarization while keeping deterministic fallback.

---

## v7 - Post-smoke bugfix and documentation pass

**What changed:** Fixed three issues found during live smoke runs: (1) duplicate active memories when the same mutable fact was ingested repeatedly, (2) overly greedy relocation extraction that produced malformed strings, and (3) repeated lines in recall context/citations. Added dedupe safeguards in storage and recall assembly plus a regression test for duplicate fact ingestion.

**Why:** The service produced noisy `/recall` output (`Lives in Berlin` repeated) and malformed relocation values (`Moved from NYC ... to Berlin`) under realistic repeated-run conditions. These hurt recall readability and reviewer confidence even though endpoint shapes were valid.

**Result:** Re-ingesting identical turns no longer creates duplicate active mutable facts, relocation memory text is normalized, and recall output is deduplicated. Test suite includes a new regression case and remains green.

**Known operational note:** `no configuration file provided: not found` is a CLI invocation/cwd issue, not an API bug. Use `docker compose -f docker-compose.yml ...` (or run from repo root) to avoid this during local verification.

**Next:** Add an end-to-end smoke script that runs compose, health wait, ingest, recall, and assertion checks in one command to reduce operator error.

---

## v8 - Evaluator smoothness hardening

**What changed:** Added a reproducible `scripts/verify.sh` smoke-and-test runner, expanded README with evaluator-compatible setup commands, and added a regression test to enforce normalized relocation extraction (`Moved from NYC to Berlin`).

**Why:** Live runs surfaced operator friction (wrong cwd/compose file) and made it hard to quickly distinguish environment mistakes from service bugs. Also needed explicit guardrails to prevent relocation-format regressions.

**Result:** One-command verification path now exists for clean-machine checks, setup docs are unambiguous, and tests explicitly validate relocation normalization in addition to duplicate-memory safeguards.

**Next:** Optionally add CI to run `scripts/verify.sh` on each push for deployment confidence.

---

## v9 - Embedding-enhanced retrieval

**What changed:** Added memory embeddings with hybrid retrieval fusion: FTS score + embedding cosine + lexical overlap. Added optional OpenAI embedding support (`OPENAI_API_KEY`) with deterministic local fallback embeddings when no key is provided. Persisted embeddings in storage with migration-safe schema upgrade.

**Why:** To meet the "real recall ranking" bar and improve semantic recall beyond keyword overlap while preserving zero-setup Docker startup.

**Result:** Retrieval now includes an explicit semantic signal and remains fully functional offline. System still boots with `docker compose up` and no manual key setup.

**Next:** Add offline reranking over top candidates and benchmark recall/latency deltas per fixture query.

---

## v10 - Contract and reliability polish

**What changed:** Tightened request validation bounds (`max_tokens`, `/search` limit, non-empty queries/messages), added explicit `/search` contract-shape and recall-bound tests, removed redundant session delete logic, and added a generic 500 handler for resilient error responses.

**Why:** Final review criteria emphasize strict contract behavior and graceful degradation under malformed or unexpected traffic.

**Result:** API now rejects out-of-bounds inputs with clear 422 responses, cleanup logic is simpler, and failure paths consistently return JSON errors without crashing the process.

**Next:** Add CI execution for full contract + fixture suite on each change.
