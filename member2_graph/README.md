# Member 2 — Neo4j Graph Database & Ingestion

TRUSTRAIL AI Member 2 owns the Neo4j graph database and the JSONL importer that
loads Member 3's graph-ready exports into it. This module is limited to
database setup, Python driver integration, and data ingestion — no attack-path
exploration, blast-radius analysis, or frontend work here.

## Repository layout

```
member2_graph/
  db.py             # Neo4j driver connection module (singleton, error handling)
  importer.py       # JSONL importer: entities, events, evidence, relationships
  validate.py       # Standalone fixture validation + Neo4j validation queries
  README.md         # this file
  .env.example      # credential template (no passwords) — copy to .env
  .env              # local credentials — GITIGNORED, never commit
  requirements.txt  # neo4j, python-dotenv

data/graph_fixture/  # synthetic Member 3 export used for import testing
```

## Prerequisites

- Python 3.10+
- A Neo4j Aura instance (URI, username, password)

Install dependencies:

```powershell
$env:PYTHONPATH = "member2_graph"
pip install -r member2_graph/requirements.txt
```

## Environment configuration

1. Copy `member2_graph/.env.example` to `member2_graph/.env`.
2. Fill in your Neo4j Aura credentials:

```
NEO4J_URI=neo4j+s://<your-instance>.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<your-aura-password>
IMPORT_BATCH_SIZE=500
```

3. **Never commit `.env`.** It is excluded from Git via the root `.gitignore`
   (`.env` pattern matches any directory). `.env.example` contains no
   passwords and is safe to commit.

Credentials are read from the environment (`.env` loaded by
`python-dotenv`, without overwriting existing variables) and are never
logged or written to reports.

## Connection module (`db.py`)

`get_driver()` returns a lazily-initialized, singleton Neo4j driver.
`verify_connectivity()` checks reachability and reports failures without
exposing credentials. `session()` is a context manager that guarantees
session cleanup.

Self-check (shows configured URI only; reports connection failure cleanly
when Aura is unreachable):

```powershell
$env:PYTHONPATH = "member2_graph"
python member2_graph/db.py
```

## Database schema

Constraints/uniqueness (create once, e.g. via Neo4j Browser or the setup
step below):

```cypher
CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT event_id IF NOT EXISTS FOR (e:Event) REQUIRE e.event_id IS UNIQUE;
CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (e:Evidence) REQUIRE e.evidence_id IS UNIQUE;
CREATE CONSTRAINT relationship_id IF NOT EXISTS FOR ()-[r]-() REQUIRE r.relationship_id IS UNIQUE;
```

Node labels: `Entity`, `Event`, `Evidence`.

Relationships (all directed, source → target), keyed by `relationship_id`:
- Domain (`relationship_category = 'original_entity'`): `AUTHENTICATED_TO`,
  `COMMUNICATES_WITH`, `RUNS`, `DEPENDS_ON`, `HAS_VULNERABILITY`, `INVOLVES`
  between `(:Entity)-[]->(:Entity)`, endpoint types validated against
  `docs/ingestion_contract.md`.
- Trace (`relationship_category = 'event_trace'`):
  - `(:Event)-[:SUPPORTED_BY]->(:Evidence)`
  - `(:Event)-[:OBSERVED_ON]->(:Entity)` with `endpoint_role` (`source`/`target`).

Original IDs, relationship directions, `evidence_status`, and `is_synthetic`
flags are preserved. Optional properties absent from a record are not invented.

## Import commands

Generate/refresh the synthetic fixture (Member 3 export) — already present:

```powershell
# data/graph_fixture/ contains entities.jsonl, events.jsonl, evidence.jsonl,
# relationships.jsonl, rejected.jsonl, metadata.json
```

Run the importer:

```powershell
$env:PYTHONPATH = "member2_graph"
python member2_graph/importer.py --input-dir data/graph_fixture --batch-size 500
```

Sample output:

```
============================================================
Member 2 — JSONL import report
============================================================
Entities:      18 imported / 18 read
Events:        17 imported / 17 read
Evidence:      17 imported / 17 read
Relationships: 68 imported / 68 read
Errors:        0
Failed batches:0
============================================================
```

## Database reset

To wipe the graph before a re-import (Neo4j Browser or `cypher-shell`):

```cypher
MATCH (n) DETACH DELETE n;
```

Then re-run the importer. Because the importer uses `MERGE` keyed on the
supplied IDs, re-importing the same dataset is idempotent: node and
relationship counts remain unchanged on a second pass.

## Validation

Standalone fixture validation (no Neo4j required — checks record structure,
counts, and endpoint validity against the ingestion contract):

```powershell
$env:PYTHONPATH = "member2_graph"
python member2_graph/validate.py --fixture data/graph_fixture
```

Expected synthetic totals (validated above):

| Item | Count |
|---|---|
| Entities | 18 |
| Events | 17 |
| Evidence records | 17 |
| Domain relationships (`original_entity`) | 17 |
| Trace `SUPPORTED_BY` | 17 |
| Trace `OBSERVED_ON` | 34 |
| Total relationships | 68 |
| Rejected records | 0 |

Neo4j validation queries (run against a live connection via
`validate.py.run_neo4j_validation(driver)` or Neo4j Browser):

```cypher
-- Node counts
MATCH (n:Entity) RETURN count(n) AS entities;          -- expect 18
MATCH (n:Event) RETURN count(n) AS events;             -- expect 17
MATCH (n:Evidence) RETURN count(n) AS evidence;        -- expect 17

-- Relationship counts
MATCH ()-[r]-() RETURN count(r) AS total;              -- expect 68
MATCH ()-[r]-() WHERE r.relationship_category = 'original_entity' RETURN count(r);  -- 17
MATCH ()-[r]-() WHERE r.relationship_category = 'event_trace' RETURN count(r);      -- 51
MATCH ()-[r:SUPPORTED_BY]->() RETURN count(r);         -- 17
MATCH ()-[r:OBSERVED_ON]->() RETURN count(r);          -- 34

-- Directions
MATCH (e:Event)-[r:SUPPORTED_BY]->(v:Evidence) RETURN count(r);   -- 17
MATCH (e:Event)-[r:OBSERVED_ON]->(t:Entity) RETURN count(r);      -- 34

-- Idempotency: re-run the importer, counts must be unchanged
```

## Idempotency / duplicate prevention

Every node is `MERGE`d on its ID (`Entity.id`, `Event.event_id`,
`Evidence.evidence_id`). Every relationship is `MERGE`d on
`relationship_id` between its endpoints. Importing the same fixture twice
produces identical counts with no duplicates; the importer reports
`duplicates_skipped` naturally through MERGE semantics and never silently
discards invalid records — record-level validation errors are collected and
reported, and failed batches are rolled back.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Missing Neo4j credentials` | `.env` absent or incomplete | Copy `.env.example` to `.env` and fill URI/username/password |
| `Cannot resolve address ...` | Wrong `NEO4J_URI` | Use your Aura instance hostname, port 7687 (`neo4j+s://`) |
| `AuthError` / `Neo4jError` | Bad username/password | Verify `NEO4J_USERNAME`/`NEO4J_PASSWORD` in `.env` |
| Relationship import fails | Endpoint type mismatch | Ensure source/target entity types satisfy the contract table |
| Duplicate nodes after re-import | Missing uniqueness constraint | Create the `entity_id`, `event_id`, `evidence_id` constraints |

## Notes

- No real Neo4j Aura endpoint was reachable in this environment, so the
  end-to-end import against Aura could not be executed here. The connection
  module, importer, and fixture validation are implemented and tested; when
  credentials are configured, run the import command above and the Neo4j
  validation queries to confirm the expected totals.
- `.env` is never committed and contains no credentials in `.env.example`.
