from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..database import queries
from ..database.neo4j_connection import Neo4jConnection
from ..utils.serialization import serialize_neo4j_value


INVESTIGATION_TRANSITIONS = {
    "OPEN": {"IN_PROGRESS", "CLOSED"},
    "IN_PROGRESS": {"OPEN", "CLOSED"},
    "CLOSED": {"OPEN"},
}


class InvestigationNotFound(LookupError):
    pass


class InvestigationConflict(RuntimeError):
    pass


class InvestigationReferenceNotFound(LookupError):
    pass


class InvestigationService:
    def __init__(self, database: Neo4jConnection):
        self.database = database

    async def list_investigations(
        self,
        status: str | None,
        alert_id: str | None,
        skip: int,
        limit: int,
    ) -> dict[str, Any]:
        rows = await self.database.execute_read(
            queries.INVESTIGATION_LIST,
            parameters={
                "status": status.upper() if status else None,
                "alert_id": alert_id,
                "skip": skip,
                "limit": limit,
            },
        )
        return {
            "investigations": [
                self._format_investigation(row["investigation"], include_history=False)
                for row in rows
                if row.get("investigation") is not None
            ],
            "pagination": {"skip": skip, "limit": limit},
        }

    async def get_investigation(self, investigation_id: str) -> dict[str, Any]:
        rows = await self.database.execute_read(
            queries.INVESTIGATION_GET,
            parameters={"investigation_id": investigation_id},
        )
        if not rows or rows[0].get("investigation") is None:
            raise InvestigationNotFound(investigation_id)
        return self._format_investigation(rows[0]["investigation"], include_history=True)

    async def create_investigation(
        self,
        title: str,
        alert_id: str | None,
        entity_ids: list[str],
    ) -> dict[str, Any]:
        if len(set(entity_ids)) != len(entity_ids):
            raise InvestigationConflict(
                "An entity may only be linked once to an investigation."
            )

        now = self._now()
        investigation_id = f"INV-{uuid4().hex}"
        initial_audit = self._audit_entry(
            action="created",
            previous_value=None,
            new_value="OPEN",
            note=None,
            timestamp=now,
        )
        properties = {
            "id": investigation_id,
            "type": "Investigation",
            "title": title,
            "related_event_id": alert_id,
            "entity_ids": entity_ids,
            "status": "OPEN",
            "created_at": now,
            "updated_at": now,
            "notes": [],
            "evidence_ids": [],
            "audit_history": [self._dump(initial_audit)],
        }
        rows = await self.database.execute_write(
            queries.INVESTIGATION_CREATE,
            parameters={
                "alert_id": alert_id,
                "entity_ids": entity_ids,
                "properties": properties,
            },
        )
        if not rows or rows[0].get("investigation") is None:
            raise InvestigationReferenceNotFound(
                "The linked alert or one of the linked entities does not exist."
            )
        return self._format_investigation(rows[0]["investigation"], include_history=True)

    async def add_note(self, investigation_id: str, content: str) -> dict[str, Any]:
        now = self._now()
        note_entry = {
            "note_id": f"NOTE-{uuid4().hex}",
            "content": content,
            "actor": "backend_api",
            "created_at": now,
        }
        audit_entry = self._audit_entry(
            action="note_added",
            previous_value=None,
            new_value=note_entry["note_id"],
            note=content,
            timestamp=now,
        )
        rows = await self.database.execute_write(
            queries.INVESTIGATION_ADD_NOTE,
            parameters={
                "investigation_id": investigation_id,
                "note_entry": self._dump(note_entry),
                "audit_entry": self._dump(audit_entry),
                "updated_at": now,
            },
        )
        if not rows:
            raise InvestigationNotFound(investigation_id)
        return self._format_investigation(rows[0]["investigation"], include_history=True)

    async def add_evidence(
        self,
        investigation_id: str,
        evidence_id: str,
    ) -> dict[str, Any]:
        now = self._now()
        audit_entry = self._audit_entry(
            action="evidence_attached",
            previous_value=None,
            new_value=evidence_id,
            note=None,
            timestamp=now,
        )
        rows = await self.database.execute_write(
            queries.INVESTIGATION_ADD_EVIDENCE,
            parameters={
                "investigation_id": investigation_id,
                "evidence_id": evidence_id,
                "audit_entry": self._dump(audit_entry),
                "updated_at": now,
            },
        )
        if not rows:
            investigation = await self.database.execute_read(
                queries.INVESTIGATION_GET,
                parameters={"investigation_id": investigation_id},
            )
            if not investigation:
                raise InvestigationNotFound(investigation_id)
            raise InvestigationReferenceNotFound(f"Evidence {evidence_id} not found.")
        return self._format_investigation(rows[0]["investigation"], include_history=True)

    async def get_evidence(self, investigation_id: str) -> list[dict[str, Any]]:
        await self.get_investigation(investigation_id)
        rows = await self.database.execute_read(
            queries.INVESTIGATION_EVIDENCE,
            parameters={"investigation_id": investigation_id},
        )
        return [
            serialize_neo4j_value(row["evidence"])
            for row in rows
            if row.get("evidence") is not None
        ]

    async def update_status(
        self,
        investigation_id: str,
        new_status: str,
        note: str | None,
    ) -> dict[str, Any]:
        status_rows = await self.database.execute_read(
            queries.INVESTIGATION_STATUS,
            parameters={"investigation_id": investigation_id},
        )
        if not status_rows:
            raise InvestigationNotFound(investigation_id)

        current_status = status_rows[0].get("status")
        normalized_status = str(current_status or "").upper()
        if new_status not in INVESTIGATION_TRANSITIONS.get(normalized_status, set()):
            raise InvestigationConflict(
                f"Status transition from {normalized_status or 'unset'} to {new_status} is not allowed."
            )

        now = self._now()
        audit_entry = self._audit_entry(
            action="status_changed",
            previous_value=normalized_status,
            new_value=new_status,
            note=note,
            timestamp=now,
        )
        rows = await self.database.execute_write(
            queries.INVESTIGATION_UPDATE_STATUS,
            parameters={
                "investigation_id": investigation_id,
                "expected_status": current_status,
                "new_status": new_status,
                "audit_entry": self._dump(audit_entry),
                "updated_at": now,
            },
        )
        if not rows:
            raise InvestigationConflict(
                "Investigation status changed concurrently; reload and retry."
            )
        return self._format_investigation(rows[0]["investigation"], include_history=True)

    async def get_timeline(self, investigation_id: str) -> list[dict[str, Any]]:
        investigation = await self.get_investigation(investigation_id)
        return investigation["audit_history"]

    @classmethod
    def _format_investigation(
        cls,
        investigation: dict[str, Any],
        include_history: bool,
    ) -> dict[str, Any]:
        result = dict(investigation)
        notes = result.get("notes", [])
        audit_history = result.pop("audit_history", [])
        if include_history:
            result["notes"] = [json.loads(note) for note in notes]
            result["audit_history"] = [
                json.loads(entry) for entry in audit_history
            ]
        else:
            result["note_count"] = len(notes)
            result["audit_entry_count"] = len(audit_history)
            result.pop("notes", None)
        return result

    @staticmethod
    def _audit_entry(
        action: str,
        previous_value: str | None,
        new_value: str,
        note: str | None,
        timestamp: str,
    ) -> dict[str, Any]:
        return {
            "action": action,
            "previous_value": previous_value,
            "new_value": new_value,
            "note": note,
            "actor": "backend_api",
            "timestamp": timestamp,
        }

    @staticmethod
    def _dump(value: dict[str, Any]) -> str:
        return json.dumps(value, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
