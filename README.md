# Memory Service

Docker-deployable memory service implementing the required HTTP contract:

- `GET /health`
- `POST /turns`
- `POST /recall`
- `POST /search`
- `GET /users/{user_id}/memories`
- `DELETE /sessions/{session_id}`
- `DELETE /users/{user_id}`

Default base URL: `http://localhost:8080`.

## Architecture

ASCII overview (renders everywhere):

```
                    +------------------+
                    |   HTTP client    |
                    +--------+---------+
                             |
         +-------------------+-------------------+
         |                                       |
         v                                       v
+----------------+                    +-------------------------+
| POST /turns    |                    | POST /recall, /search    |
+-------+--------+                    +-----------+-------------+
        |                                        |
        | 1. persist raw turn (SQLite)           | 1. hybrid retrieve
        | 2. extract structured memories         |    (FTS5 + embedding
        | 3. supersede mutable facts             |     + lexical)
        | 4. index FTS + store embedding         |
        v                                        v
+-------+----------------------------------------+-------------+
|                     SQLite (/data/memory.db)                 |
|  turns | memories (active/supersedes) | memories_fts       |
+------------------------------------------------------------+
        ^
        | named volume memory_data -> survives docker restarts
        +----------------------------------------------------+
```

Mermaid equivalent (GitHub / many Markdown viewers):

```mermaid
flowchart TD
    A[POST /turns] --> B[Turn Store (SQLite)]
    A --> C[Extraction Engine]
    C --> D[Memory Table + Supersession]
    D --> E[FTS5 Index]
    F[POST /recall] --> G[Hybrid Retrieval]
    G --> E
    G --> D
    G --> H[Recent Turns]
    H --> I[Budgeted Context Assembler]
    D --> I
    I --> J[Context + Citations]
```

This service is a single FastAPI process with synchronous ingestion. `POST /turns` writes the raw turn, runs extraction on user messages, applies fact evolution logic (supersession), updates FTS indices, and only then returns `201`. That guarantees immediate consistency for `/recall` and `/users/{user_id}/memories`.

Persistence is provided by a SQLite DB file at `/data/memory.db`, mounted from a named Docker volume (`memory_data`), so data survives `docker compose down` and subsequent `docker compose up`.

## Backing Store Choice

**SQLite + FTS5**.

Why:
- zero external dependency; one container, no manual setup;
- ACID transactions for synchronous write-then-read correctness;
- built-in FTS5 gives keyword recall (BM25-like ranking) without another service;
- easy Docker volume persistence.

Tradeoff: no ANN vector index. Instead, each memory stores an embedding vector and recall uses direct cosine scoring over a bounded candidate set.

## Extraction Pipeline

Raw turn messages are persisted first, then user messages go through rule/regex extraction:

- Personal facts: employment, location, pets, allergies, relationships/family mentions.
- Preferences: diet, answer-style preferences.
- Opinions: topic-scoped stance statements (`I love X`, `X generics are annoying`, `X is fine but Y for scripts`).
- Corrections/events: statements beginning with correction cues (`actually`, `sorry`).
- Implicit fact handling: e.g. `"walking Biscuit this morning"` becomes a structured pet fact.

Each extracted memory stores:
- `type`, `category`, derived `key`,
- `value`, `confidence`,
- source pointers (`source_session`, `source_turn`),
- timeline fields and supersession linkage.

What it misses:
- nuanced coreference (pronouns across many turns),
- deeply implicit world knowledge,
- nuanced stance decomposition without explicit lexical cues.

## Recall Strategy

`POST /recall` pipeline:
1. Candidate retrieval using hybrid search over active memories:
   - FTS query (keyword precision),
   - embedding cosine similarity (semantic recall),
   - lexical overlap similarity + recency tie-break.
2. Stable memory fetch (`fact` + `preference`, active only) for the user.
3. Recent turn fetch for conversational grounding.
4. Budgeted context assembly under `max_tokens` (approx token estimator):
   - Priority 1: stable user facts/preferences.
   - Priority 2: query-relevant memories.
   - Priority 3: recent conversations.

Noise resistance rule: if neither stable nor relevant memories pass query relevance gating, `/recall` returns empty context with HTTP 200.

## Fact Evolution

Mutable keys (`fact/preference` categories like employment/location/style/diet/pet/allergy/relationship/family) are upserted with supersession:

- when a new memory arrives with the same key but different value,
- previously active row is marked `active=false`,
- new row is inserted as `active=true` and points to prior memory via `supersedes`.

This preserves history while ensuring recall prefers current facts.

Opinion evolution is partially handled but topic-aware:
- opinions are keyed by topic (e.g. `topic:typescript`) and treated as mutable;
- a newer conflicting stance supersedes the prior active stance for that topic;
- history remains inspectable via inactive rows.
For richer arcs (mixed/nuanced views over time), this keeps sequential snapshots rather than collapsing into one abstract summary.

## Tradeoffs

- Optimized for evaluator correctness and operability over maximal model sophistication.
- SQLite + FTS + stored embeddings keeps deployment simple (single container) but does not provide ANN-scale vector search.
- Rule-based extraction gives deterministic behavior and strong inspectability, but misses subtle paraphrases that LLM extraction could capture.
- Synchronous `/turns` ensures immediate read-after-write correctness, with the tradeoff of higher write latency under heavy load.

## Session Scoping

- Cross-session memory sharing is **enabled for the same `user_id`** by design.
- Session-only recall is used when `user_id` is null.
- Different users do not bleed, even with concurrent sessions.

## Failure Modes

- **No data / cold start:** `/recall` returns `{ "context": "", "citations": [] }`.
- **Missing auth token env:** service runs unauthenticated (contract-compatible optional auth).
- **Malformed JSON / missing fields:** 4xx validation errors (no crash).
- **Oversized payload:** `413 Payload too large`.
- **Slow disk / SQLite lock pressure:** requests may slow, but WAL mode improves write/read concurrency.
- **Missing embedding API key:** service falls back to local hash embeddings, preserving deterministic behavior and compatibility.

## Running

```bash
docker compose up -d
curl -sf http://localhost:8080/health
```

Evaluator-compatible setup (exact shell form):

```bash
git clone <your-repo> memory-service
cd memory-service
docker compose up -d
until curl -sf http://localhost:8080/health; do sleep 1; done
```

If Docker says `no configuration file provided: not found`, you are in the wrong directory.
Use either:

```bash
cd memory-service
docker compose up -d
```

or an explicit file path:

```bash
docker compose -f /absolute/path/to/memory-service/docker-compose.yml up -d
```

## How to Run the Tests

Run tests locally:

```bash
pip install -r requirements.txt
pytest -q
```

Container-first verification (no local Python required):

```bash
chmod +x scripts/verify.sh
./scripts/verify.sh
```

Test coverage includes:
- contract roundtrip,
- malformed input/unicode handling,
- concurrent session scoping,
- fact supersession behavior,
- restart persistence simulation,
- fixture-based recall-quality scoring in `fixtures/recall_fixture.json`.

## Embeddings

- Default mode: local hash-based embeddings (no external dependency).
- Optional higher-quality mode: OpenAI embeddings via `OPENAI_API_KEY`.
- Retrieval always uses hybrid fusion (FTS + embedding cosine + lexical overlap), never vanilla cosine top-k.
