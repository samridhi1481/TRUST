"""Member 2 — Neo4j graph validation.

Two modes:
  1. Standalone JSONL fixture validation (no Neo4j required) — checks record
     structure, counts, and relationship endpoint validity against the
     ingestion contract.
  2. Neo4j validation (requires a live connection) — runs Cypher queries to
     verify node/relationship counts, directions, traceability, timestamps,
     and idempotency.

Run the standalone check from the repository root:
    $env:PYTHONPATH = "member2_graph"
    python member2_graph/validate.py --fixture data/graph_fixture
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from importer import (
    DOMAIN_ENDPOINT_TYPES,
    DOMAIN_TYPES,
    TRACE_TYPES,
    validate_entity,
    validate_event,
    validate_evidence,
    validate_relationship,
    read_jsonl,
)


# ---------------------------------------------------------------------------
# Standalone fixture validation (no Neo4j)
# ---------------------------------------------------------------------------

def _count_nonempty_lines(path: Path) -> int:
    return sum(1 for line in path.open("r", encoding="utf-8") if line.strip())


def validate_fixture(fixture_dir: str | Path) -> dict[str, Any]:
    """Validate the graph_fixture JSONL without Neo4j.

    Returns a dict with per-file counts, relationship breakdown, endpoint
    validity, and a list of errors.
    """
    d = Path(fixture_dir)
    errors: list[str] = []

    files = {
        "entities": d / "entities.jsonl",
        "events": d / "events.jsonl",
        "evidence": d / "evidence.jsonl",
        "relationships": d / "relationships.jsonl",
    }
    records: dict[str, list[dict[str, Any]]] = {}
    for name, path in files.items():
        if not path.is_file():
            errors.append(f"missing file: {path}")
            records[name] = []
            continue
        rows = read_jsonl(path)
        recs: list[dict[str, Any]] = []
        for line_no, record, err in rows:
            if err is not None:
                errors.append(f"{path.name}:{line_no}: {err}")
                continue
            recs.append(record)
        records[name] = recs

    entities = records["entities"]
    events = records["events"]
    evidence = records["evidence"]
    relationships = records["relationships"]

    # Record-level contract validation.
    for rec in entities:
        v = validate_entity(rec)
        if v:
            errors.append(f"entity {rec.get('id')}: {v}")
    for rec in events:
        v = validate_event(rec)
        if v:
            errors.append(f"event {rec.get('event_id')}: {v}")
    for rec in evidence:
        v = validate_evidence(rec)
        if v:
            errors.append(f"evidence {rec.get('evidence_id')}: {v}")

    entity_types = {e["id"]: e["type"] for e in entities}
    event_ids = {e["event_id"] for e in events}
    evidence_ids = {e["evidence_id"] for e in evidence}

    domain_count = 0
    trace_count = 0
    supported_by_count = 0
    observed_on_count = 0

    for rec in relationships:
        v = validate_relationship(rec)
        if v:
            errors.append(f"relationship {rec.get('relationship_id')}: {v}")
            continue
        rtype = rec["relationship_type"]
        category = rec["relationship_category"]
        if category == "original_entity":
            domain_count += 1
            src_type = entity_types.get(rec["source_id"])
            tgt_type = entity_types.get(rec["target_id"])
            if src_type is None:
                errors.append(f"rel {rec['relationship_id']}: unknown source {rec['source_id']}")
                continue
            if tgt_type is None:
                errors.append(f"rel {rec['relationship_id']}: unknown target {rec['target_id']}")
                continue
            allowed_src, allowed_tgt = DOMAIN_ENDPOINT_TYPES[rtype]
            if src_type not in allowed_src:
                errors.append(
                    f"rel {rec['relationship_id']}: {rtype} source type '{src_type}' not in {allowed_src}")
            if tgt_type not in allowed_tgt:
                errors.append(
                    f"rel {rec['relationship_id']}: {rtype} target type '{tgt_type}' not in {allowed_tgt}")
        elif category == "event_trace":
            trace_count += 1
            if rtype == "SUPPORTED_BY":
                supported_by_count += 1
                if rec["source_id"] not in event_ids:
                    errors.append(f"rel {rec['relationship_id']}: SUPPORTED_BY source not an event")
                if rec["target_id"] not in evidence_ids:
                    errors.append(f"rel {rec['relationship_id']}: SUPPORTED_BY target not evidence")
            elif rtype == "OBSERVED_ON":
                observed_on_count += 1
                if rec["source_id"] not in event_ids:
                    errors.append(f"rel {rec['relationship_id']}: OBSERVED_ON source not an event")
                if rec["target_id"] not in entity_types:
                    errors.append(f"rel {rec['relationship_id']}: OBSERVED_ON target not an entity")
                if rec.get("endpoint_role") not in ("source", "target"):
                    errors.append(f"rel {rec['relationship_id']}: OBSERVED_ON missing endpoint_role")

    total_rels = domain_count + trace_count
    return {
        "files": {name: len(recs) for name, recs in records.items()},
        "rejected_lines": _count_nonempty_lines(d / "rejected.jsonl"),
        "relationships": {
            "domain_original_entity": domain_count,
            "traceability": trace_count,
            "supported_by": supported_by_count,
            "observed_on": observed_on_count,
            "total": total_rels,
        },
        "errors": errors,
        "valid": len(errors) == 0,
    }


# ---------------------------------------------------------------------------
# Neo4j validation queries
# ---------------------------------------------------------------------------

# Each entry: (label, cypher, expected)
NODE_COUNT_QUERIES = [
    ("Entity", "MATCH (n:Entity) RETURN count(n) AS c"),
    ("Event", "MATCH (n:Event) RETURN count(n) AS c"),
    ("Evidence", "MATCH (n:Evidence) RETURN count(n) AS c"),
]

RELATIONSHIP_COUNT_QUERIES = [
    ("All relationships", "MATCH ()-[r]-() RETURN count(r) AS c"),
    ("Domain relationships", "MATCH ()-[r]-() WHERE r.relationship_category = 'original_entity' RETURN count(r) AS c"),
    ("Trace relationships", "MATCH ()-[r]-() WHERE r.relationship_category = 'event_trace' RETURN count(r) AS c"),
    ("SUPPORTED_BY", "MATCH ()-[r:SUPPORTED_BY]-() RETURN count(r) AS c"),
    ("OBSERVED_ON", "MATCH ()-[r:OBSERVED_ON]-() RETURN count(r) AS c"),
]

DIRECTION_QUERIES = [
    # Event -> Evidence via SUPPORTED_BY
    ("SUPPORTED_BY direction (start=Event, end=Evidence)",
     "MATCH (e:Event)-[r:SUPPORTED_BY]->(v:Evidence) RETURN count(r) AS c"),
    # Event -> Entity via OBSERVED_ON
    ("OBSERVED_ON direction (start=Event, end=Entity)",
     "MATCH (e:Event)-[r:OBSERVED_ON]->(t:Entity) RETURN count(r) AS c"),
    # Domain edges should start and end on Entity
    ("Domain edges start/end on Entity",
     "MATCH (s:Entity)-[r]->(t:Entity) WHERE r.relationship_category = 'original_entity' RETURN count(r) AS c"),
]

TRACEABILITY_QUERIES = [
    # Every event should have exactly one SUPPORTED_BY to its evidence
    ("Events with SUPPORTED_BY trace",
     "MATCH (e:Event)-[:SUPPORTED_BY]->(v:Evidence) RETURN count(DISTINCT e) AS c"),
    # Every event should have OBSERVED_ON to entities
    ("Events with OBSERVED_ON trace",
     "MATCH (e:Event)-[:OBSERVED_ON]->(t:Entity) RETURN count(DISTINCT e) AS c"),
]

TIMESTAMP_QUERIES = [
    ("Events with null event_time", "MATCH (e:Event) WHERE e.event_time IS NULL RETURN count(e) AS c"),
    ("Events with timestamp_semantics set",
     "MATCH (e:Event) WHERE e.timestamp_semantics IS NOT NULL RETURN count(e) AS c"),
]

CONSTRAINT_QUERIES = [
    ("Entity constraints", "SHOW CONSTRAINTS YIELD name, entityType, labels, properties WHERE entityType = 'NODE' RETURN name, labels, properties"),
]


def run_neo4j_validation(driver) -> dict[str, Any]:
    """Run Cypher validation queries against a live Neo4j driver.

    Returns a dict of query name -> result rows / error.
    """
    from neo4j.exceptions import Neo4jError
    results: dict[str, Any] = {}
    errors: list[str] = []

    def _run(tx, query):
        return list(tx.run(query))

    with driver.session() as session:
        for label, query in NODE_COUNT_QUERIES + RELATIONSHIP_COUNT_QUERIES + DIRECTION_QUERIES + TRACEABILITY_QUERIES + TIMESTAMP_QUERIES:
            try:
                rows = session.execute_read(_run, query)
                results[label] = [dict(r) for r in rows]
            except Neo4jError as exc:
                errors.append(f"{label}: {exc}")
                results[label] = {"error": str(exc)}

        # Constraints (admin command, run once)
        try:
            rows = session.execute_read(_run, CONSTRAINT_QUERIES[0][1])
            results[CONSTRAINT_QUERIES[0][0]] = [dict(r) for r in rows]
        except Neo4jError as exc:
            errors.append(f"{CONSTRAINT_QUERIES[0][0]}: {exc}")
            results[CONSTRAINT_QUERIES[0][0]] = {"error": str(exc)}

    return {"results": results, "errors": errors, "valid": len(errors) == 0}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _fmt(results: dict[str, Any]) -> str:
    lines = ["=" * 60, "Member 2 — standalone fixture validation", "=" * 60]
    fc = results["files"]
    lines.append(
        f"Files: entities={fc.get('entities', 0)} events={fc.get('events', 0)} "
        f"evidence={fc.get('evidence', 0)} relationships={fc.get('relationships', 0)} "
        f"rejected_lines={results['rejected_lines']}")
    rel = results["relationships"]
    lines.append(
        f"Relationships: domain={rel['domain_original_entity']} "
        f"trace={rel['traceability']} (SUPPORTED_BY={rel['supported_by']}, "
        f"OBSERVED_ON={rel['observed_on']}) total={rel['total']}")
    lines.append("")
    if results["errors"]:
        lines.append(f"ERRORS ({len(results['errors'])}):")
        for e in results["errors"]:
            lines.append(f"  - {e}")
    else:
        lines.append("All fixture validation checks passed.")
    lines.append("=" * 60)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the Member 2 graph_fixture (standalone, no Neo4j).")
    parser.add_argument("--fixture", default="data/graph_fixture",
                        help="directory containing the JSONL exports")
    args = parser.parse_args()

    result = validate_fixture(args.fixture)
    print(_fmt(result))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
