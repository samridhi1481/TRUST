"""Member 2 — JSONL importer for TRUSTRAIL graph data.

Imports Member 3's graph-ready JSONL exports (entities, relationships, events,
evidence) into Neo4j using parameterised Cypher and MERGE, preserving the
ingestion contract's IDs, relationship directions, evidence_status and
synthetic provenance flags.

Run from the repository root:
    $env:PYTHONPATH = "member2_graph"
    python member2_graph/importer.py --input-dir data/graph_fixture
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from db import get_driver, close_driver, verify_connectivity, session


# ---------------------------------------------------------------------------
# Contract constants (from docs/ingestion_contract.md)
# ---------------------------------------------------------------------------

ENTITY_LABEL = "Entity"
EVENT_LABEL = "Event"
EVIDENCE_LABEL = "Evidence"

# Allowed domain relationship endpoint types (source -> target).
DOMAIN_ENDPOINT_TYPES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "AUTHENTICATED_TO": (("user",), ("host",)),
    "COMMUNICATES_WITH": (("host", "server"), ("ip", "server")),
    "RUNS": (("host",), ("process",)),
    "DEPENDS_ON": (("server",), ("application",)),
    "HAS_VULNERABILITY": (("server",), ("vulnerability",)),
    "INVOLVES": (("incident",), ("host", "user")),
}

DOMAIN_TYPES = set(DOMAIN_ENDPOINT_TYPES.keys())
TRACE_TYPES = {"SUPPORTED_BY", "OBSERVED_ON"}
ALL_RELATIONSHIP_TYPES = DOMAIN_TYPES | TRACE_TYPES

VALID_EVIDENCE_STATUS = {"observed", "derived", "unconfirmed"}

RELATIONSHIP_CATEGORY_ORIGINAL = "original_entity"
RELATIONSHIP_CATEGORY_TRACE = "event_trace"

# Required properties per record type (per the ingestion contract).
REQUIRED_ENTITY = {"id", "type", "synthetic"}
REQUIRED_EVENT = {
    "event_id", "event_type", "event_time", "severity", "description",
    "evidence_id", "is_synthetic",
}
REQUIRED_EVIDENCE = {
    "evidence_id", "event_id", "source_record_id", "source_system",
    "observed_at", "is_synthetic", "evidence_status",
}
REQUIRED_RELATIONSHIP = {
    "relationship_id", "source_id", "target_id", "relationship_type",
    "evidence_status", "event_id", "is_synthetic", "relationship_category",
}

BATCH_SIZE_DEFAULT = 500


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ImportError:
    file: str
    line: int
    record_id: str
    reason: str


@dataclass
class ImportReport:
    entities_read: int = 0
    entities_imported: int = 0
    events_read: int = 0
    events_imported: int = 0
    evidence_read: int = 0
    evidence_imported: int = 0
    relationships_read: int = 0
    relationships_imported: int = 0
    errors: list[ImportError] = field(default_factory=list)
    batches_failed: int = 0

    @property
    def total_errors(self) -> int:
        return len(self.errors)

    @property
    def success(self) -> bool:
        return self.total_errors == 0


# ---------------------------------------------------------------------------
# JSONL reading
# ---------------------------------------------------------------------------

def read_jsonl(path: Path) -> list[tuple[int, dict[str, Any] | None, str | None]]:
    """Read a JSONL file into (line_no, record_or_None, error_or_None) tuples."""
    rows: list[tuple[int, dict[str, Any] | None, str | None]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                rows.append((line_no, None, f"invalid JSON: {exc}"))
                continue
            if not isinstance(record, dict):
                rows.append((line_no, None, "record must be a JSON object"))
                continue
            rows.append((line_no, record, None))
    return rows


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _missing_required(record: dict[str, Any], required: set[str], label: str) -> str | None:
    # Key presence is required; null values are allowed for fields the
    # contract permits to be absent/unresolved (e.g. event_time, observed_at).
    missing = [k for k in sorted(required) if k not in record]
    if missing:
        return f"missing required {label} field(s): {', '.join(missing)}"
    return None


def validate_entity(record: dict[str, Any]) -> str | None:
    err = _missing_required(record, REQUIRED_ENTITY, "entity")
    if err:
        return err
    if not isinstance(record["synthetic"], bool):
        return "entity 'synthetic' must be a boolean"
    return None


def validate_event(record: dict[str, Any]) -> str | None:
    err = _missing_required(record, REQUIRED_EVENT, "event")
    if err:
        return err
    if not isinstance(record["is_synthetic"], bool):
        return "event 'is_synthetic' must be a boolean"
    if record["evidence_status"] not in VALID_EVIDENCE_STATUS:
        return f"event 'evidence_status' must be one of {sorted(VALID_EVIDENCE_STATUS)}"
    return None


def validate_evidence(record: dict[str, Any]) -> str | None:
    err = _missing_required(record, REQUIRED_EVIDENCE, "evidence")
    if err:
        return err
    if not isinstance(record["is_synthetic"], bool):
        return "evidence 'is_synthetic' must be a boolean"
    if record["evidence_status"] not in VALID_EVIDENCE_STATUS:
        return f"evidence 'evidence_status' must be one of {sorted(VALID_EVIDENCE_STATUS)}"
    return None


def validate_relationship(record: dict[str, Any]) -> str | None:
    err = _missing_required(record, REQUIRED_RELATIONSHIP, "relationship")
    if err:
        return err
    rtype = record["relationship_type"]
    if rtype not in ALL_RELATIONSHIP_TYPES:
        return f"unsupported relationship_type: {rtype}"
    if record["evidence_status"] not in VALID_EVIDENCE_STATUS:
        return f"relationship 'evidence_status' must be one of {sorted(VALID_EVIDENCE_STATUS)}"
    if not isinstance(record["is_synthetic"], bool):
        return "relationship 'is_synthetic' must be a boolean"
    category = record["relationship_category"]
    if category not in {RELATIONSHIP_CATEGORY_ORIGINAL, RELATIONSHIP_CATEGORY_TRACE}:
        return f"unsupported relationship_category: {category}"
    if category == RELATIONSHIP_CATEGORY_TRACE and rtype not in TRACE_TYPES:
        return f"event_trace relationship must use {sorted(TRACE_TYPES)}, got {rtype}"
    if category == RELATIONSHIP_CATEGORY_ORIGINAL and rtype not in DOMAIN_TYPES:
        return f"original_entity relationship must use {sorted(DOMAIN_TYPES)}, got {rtype}"
    if rtype == "OBSERVED_ON" and "endpoint_role" not in record:
        return "OBSERVED_ON requires endpoint_role ('source' or 'target')"
    if record.get("endpoint_role") not in (None, "source", "target"):
        return "endpoint_role must be 'source' or 'target'"
    return None


# ---------------------------------------------------------------------------
# Property maps (drop None values so optional fields stay absent)
# ---------------------------------------------------------------------------

def _props(**kwargs: Any) -> dict[str, Any]:
    return {k: v for k, v in kwargs.items() if v is not None}


def entity_props(record: dict[str, Any]) -> dict[str, Any]:
    return _props(
        type=record.get("type"),
        name=record.get("name"),
        criticality=record.get("criticality"),
        synthetic=record.get("synthetic"),
    )


def event_props(record: dict[str, Any]) -> dict[str, Any]:
    return _props(
        event_type=record.get("event_type"),
        event_time=record.get("event_time"),
        event_time_original=record.get("event_time_original"),
        timestamp_semantics=record.get("timestamp_semantics"),
        severity=record.get("severity"),
        description=record.get("description"),
        evidence_id=record.get("evidence_id"),
        is_synthetic=record.get("is_synthetic"),
        source_system=record.get("source_system"),
        source_record_id=record.get("source_record_id"),
        ingested_at=record.get("ingested_at"),
        evidence_status=record.get("evidence_status"),
    )


def evidence_props(record: dict[str, Any]) -> dict[str, Any]:
    return _props(
        event_id=record.get("event_id"),
        source_record_id=record.get("source_record_id"),
        source_system=record.get("source_system"),
        source_dataset_id=record.get("source_dataset_id"),
        source_version=record.get("source_version"),
        source_url=record.get("source_url"),
        license=record.get("license"),
        observed_at=record.get("observed_at"),
        observed_at_original=record.get("observed_at_original"),
        ingested_at=record.get("ingested_at"),
        evidence_type=record.get("evidence_type"),
        description=record.get("description"),
        evidence_status=record.get("evidence_status"),
        is_synthetic=record.get("is_synthetic"),
    )


def relationship_props(record: dict[str, Any]) -> dict[str, Any]:
    return _props(
        evidence_status=record.get("evidence_status"),
        event_id=record.get("event_id"),
        is_synthetic=record.get("is_synthetic"),
        relationship_category=record.get("relationship_category"),
        endpoint_role=record.get("endpoint_role"),
    )


# ---------------------------------------------------------------------------
# Cypher helpers
# ---------------------------------------------------------------------------

def _merge_node_cypher(label: str, key: str, key_param: str, props: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Build a MERGE node query; props values are all non-None."""
    if props:
        set_clause = "SET n += {" + ", ".join(f"{k}: $p_{k}" for k in props) + "} "
    else:
        set_clause = ""
    query = (
        f"MERGE (n:{label} {{{key}: ${key_param}}}) "
        f"{set_clause}"
        "RETURN n"
    )
    params = {key_param: props.get(key)}
    params.update({f"p_{k}": v for k, v in props.items()})
    return query, params


# Relationship templates: relationship type is interpolated (whitelisted),
# everything else is parameterised.
_REL_TEMPLATES = {
    # Domain edges: Entity -> Entity
    "domain": (
        "MERGE (s:Entity {id: $source_id}) "
        "MERGE (t:Entity {id: $target_id}) "
        "MERGE (s)-[r:{rtype} {{relationship_id: $relationship_id}}]->(t) "
        "SET r += $rprops "
        "RETURN r"
    ),
    # SUPPORTED_BY: Event -> Evidence
    "supported_by": (
        "MERGE (s:Event {event_id: $source_id}) "
        "MERGE (t:Evidence {evidence_id: $target_id}) "
        "MERGE (s)-[r:SUPPORTED_BY {{relationship_id: $relationship_id}}]->(t) "
        "SET r += $rprops "
        "RETURN r"
    ),
    # OBSERVED_ON: Event -> Entity
    "observed_on": (
        "MERGE (s:Event {event_id: $source_id}) "
        "MERGE (t:Entity {id: $target_id}) "
        "MERGE (s)-[r:OBSERVED_ON {{relationship_id: $relationship_id}}]->(t) "
        "SET r += $rprops "
        "RETURN r"
    ),
}


# ---------------------------------------------------------------------------
# Importer
# ---------------------------------------------------------------------------

class Importer:
    def __init__(self, input_dir: str | Path, batch_size: int = BATCH_SIZE_DEFAULT):
        self.input_dir = Path(input_dir)
        self.batch_size = batch_size
        self.report = ImportReport()
        # ID -> type lookups built during entity import, used for endpoint validation.
        self.entity_types: dict[str, str] = {}
        self.event_ids: set[str] = set()
        self.evidence_ids: set[str] = set()

    # -- file paths -------------------------------------------------------
    def _path(self, name: str) -> Path:
        return self.input_dir / name

    def _exists(self, name: str) -> bool:
        return self._path(name).is_file()

    # -- per-batch transaction writers ------------------------------------
    def _write_entities_batch(self, tx, rows: list[dict[str, Any]]) -> int:
        count = 0
        for record in rows:
            props = entity_props(record)
            query, params = _merge_node_cypher(ENTITY_LABEL, "id", "eid", props)
            tx.run(query, **params)
            count += 1
        return count

    def _write_events_batch(self, tx, rows: list[dict[str, Any]]) -> int:
        count = 0
        for record in rows:
            props = event_props(record)
            query, params = _merge_node_cypher(EVENT_LABEL, "event_id", "eid", props)
            tx.run(query, **params)
            count += 1
        return count

    def _write_evidence_batch(self, tx, rows: list[dict[str, Any]]) -> int:
        count = 0
        for record in rows:
            props = evidence_props(record)
            query, params = _merge_node_cypher(EVIDENCE_LABEL, "evidence_id", "eid", props)
            tx.run(query, **params)
            count += 1
        return count

    def _write_relationships_batch(self, tx, rows: list[dict[str, Any]]) -> int:
        count = 0
        for record in rows:
            rtype = record["relationship_type"]
            category = record["relationship_category"]
            rprops = relationship_props(record)
            params: dict[str, Any] = {
                "source_id": record["source_id"],
                "target_id": record["target_id"],
                "relationship_id": record["relationship_id"],
                "rprops": rprops,
            }
            if category == RELATIONSHIP_CATEGORY_ORIGINAL:
                query = _REL_TEMPLATES["domain"].format(rtype=rtype)
            elif rtype == "SUPPORTED_BY":
                query = _REL_TEMPLATES["supported_by"]
            elif rtype == "OBSERVED_ON":
                query = _REL_TEMPLATES["observed_on"]
            else:
                raise ValueError(f"unsupported trace relationship type: {rtype}")
            tx.run(query, **params)
            count += 1
        return count

    def _run_batch(self, tx_func, rows: list[dict[str, Any]], label: str) -> int:
        """Run a batch inside a write transaction. Returns records written."""
        with session() as neo_session:
            return neo_session.execute_write(tx_func, rows)

    # -- validation + import ---------------------------------------------
    def _validate_and_partition(self) -> None:
        """Read and validate every JSONL file; populate report and lookups."""
        for name, validator, counter in (
            ("entities.jsonl", validate_entity, "entities_read"),
            ("events.jsonl", validate_event, "events_read"),
            ("evidence.jsonl", validate_evidence, "evidence_read"),
            ("relationships.jsonl", validate_relationship, "relationships_read"),
        ):
            path = self._path(name)
            if not path.is_file():
                self.report.errors.append(ImportError(name, 0, "", f"file not found: {path}"))
                continue
            rows = read_jsonl(path)
            valid_rows: list[dict[str, Any]] = []
            for line_no, record, error in rows:
                setattr(self.report, counter, getattr(self.report, counter) + 1)
                if error is not None:
                    rec_id = record.get("id") or record.get("event_id") or record.get(
                        "evidence_id") or record.get("relationship_id") or f"line:{line_no}"
                    self.report.errors.append(ImportError(name, line_no, str(rec_id), error))
                    continue
                if validator(record) is not None:
                    rec_id = record.get("id") or record.get("event_id") or record.get(
                        "evidence_id") or record.get("relationship_id") or f"line:{line_no}"
                    self.report.errors.append(
                        ImportError(name, line_no, str(rec_id), validator(record)))
                    continue
                valid_rows.append(record)
            setattr(self, f"_{name.split('.')[0]}_valid", valid_rows)

        # Build lookups from valid entities for endpoint validation.
        self.entity_types = {r["id"]: r["type"] for r in self._entities_valid}
        self.event_ids = {r["event_id"] for r in self._events_valid}
        self.evidence_ids = {r["evidence_id"] for r in self._evidence_valid}

        # Validate relationship endpoints now that entity types are known.
        for record in self._relationships_valid:
            self._validate_relationship_endpoints(record)

    def _validate_relationship_endpoints(self, record: dict[str, Any]) -> None:
        rtype = record["relationship_type"]
        source_id = record["source_id"]
        target_id = record["target_id"]
        category = record["relationship_category"]

        if category == RELATIONSHIP_CATEGORY_ORIGINAL:
            src_type = self.entity_types.get(source_id)
            tgt_type = self.entity_types.get(target_id)
            if src_type is None:
                record["_import_error"] = f"source entity not found: {source_id}"
                return
            if tgt_type is None:
                record["_import_error"] = f"target entity not found: {target_id}"
                return
            allowed_src, allowed_tgt = DOMAIN_ENDPOINT_TYPES[rtype]
            if src_type not in allowed_src:
                record["_import_error"] = (
                    f"{rtype} source type '{src_type}' not in {allowed_src}")
                return
            if tgt_type not in allowed_tgt:
                record["_import_error"] = (
                    f"{rtype} target type '{tgt_type}' not in {allowed_tgt}")
                return
        elif rtype == "SUPPORTED_BY":
            if source_id not in self.event_ids:
                record["_import_error"] = f"SUPPORTED_BY source event not found: {source_id}"
                return
            if target_id not in self.evidence_ids:
                record["_import_error"] = f"SUPPORTED_BY target evidence not found: {target_id}"
                return
        elif rtype == "OBSERVED_ON":
            if source_id not in self.event_ids:
                record["_import_error"] = f"OBSERVED_ON source event not found: {source_id}"
                return
            if target_id not in self.entity_types:
                record["_import_error"] = f"OBSERVED_ON target entity not found: {target_id}"
                return

    def import_all(self) -> ImportReport:
        if not verify_connectivity():
            self.report.errors.append(
                ImportError("connection", 0, "", "could not connect to Neo4j"))
            return self.report

        self._validate_and_partition()

        # Import nodes.
        self.report.entities_imported = self._import_in_batches(
            self._write_entities_batch, self._entities_valid, "entities")
        self.report.events_imported = self._import_in_batches(
            self._write_events_batch, self._events_valid, "events")
        self.report.evidence_imported = self._import_in_batches(
            self._write_evidence_batch, self._evidence_valid, "evidence")

        # Import relationships (endpoints now exist as nodes).
        rel_valid = [
            r for r in self._relationships_valid if "_import_error" not in r
        ]
        rel_errors = [
            r for r in self._relationships_valid if "_import_error" in r
        ]
        for r in rel_errors:
            self.report.errors.append(
                ImportError("relationships.jsonl", 0,
                            r.get("relationship_id", "unknown"), r["_import_error"]))
        self.report.relationships_imported = self._import_in_batches(
            self._write_relationships_batch, rel_valid, "relationships")
        self.report.relationships_read = len(self._relationships_valid)

        close_driver()
        return self.report

    def _import_in_batches(self, tx_func, rows: list[dict[str, Any]], label: str) -> int:
        total = 0
        for start in range(0, len(rows), self.batch_size):
            batch = rows[start:start + self.batch_size]
            try:
                written = self._run_batch(tx_func, batch, label)
                total += written
            except Exception as exc:  # roll back failed batch, keep going
                self.report.batches_failed += 1
                msg = type(exc).__name__ + ": " + str(exc)
                for record in batch:
                    rec_id = (
                        record.get("id") or record.get("event_id")
                        or record.get("evidence_id") or record.get("relationship_id")
                        or f"batch-start:{start}")
                    self.report.errors.append(
                        ImportError(f"{label}.jsonl", 0, str(rec_id),
                                    f"batch failed: {msg}"))
        return total


def run_import(input_dir: str | Path = "data/graph_fixture",
               batch_size: int = BATCH_SIZE_DEFAULT) -> ImportReport:
    return Importer(input_dir, batch_size).import_all()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _report_text(report: ImportReport) -> str:
    lines = [
        "=" * 60,
        "Member 2 — JSONL import report",
        "=" * 60,
        f"Entities:      {report.entities_imported} imported / {report.entities_read} read",
        f"Events:        {report.events_imported} imported / {report.events_read} read",
        f"Evidence:      {report.evidence_imported} imported / {report.evidence_read} read",
        f"Relationships: {report.relationships_imported} imported / {report.relationships_read} read",
        f"Errors:        {report.total_errors}",
        f"Failed batches:{report.batches_failed}",
    ]
    if report.errors:
        lines.append("")
        lines.append("Record-level errors:")
        for err in report.errors:
            lines.append(
                f"  [{err.file}:{err.line}] {err.record_id}: {err.reason}")
    lines.append("=" * 60)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import Member 3 JSONL graph exports into Neo4j.")
    parser.add_argument("--input-dir", default="data/graph_fixture",
                        help="directory containing the JSONL exports")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE_DEFAULT,
                        help="records per import transaction")
    args = parser.parse_args()

    report = run_import(args.input_dir, args.batch_size)
    print(_report_text(report))
    return 0 if report.success else 1


if __name__ == "__main__":
    sys.exit(main())
