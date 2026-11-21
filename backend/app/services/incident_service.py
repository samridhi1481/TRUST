from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..database import queries
from ..database.neo4j_connection import Neo4jConnection


STATUS_TRANSITIONS = {
    "UNSET": {"NEW"},
    "NEW": {"INVESTIGATING", "CONFIRMED", "CLOSED"},
    "INVESTIGATING": {
        "CONFIRMED",
        "CONTAINMENT_RECOMMENDED",
        "RESOLVED",
        "CLOSED",
    },
    "CONFIRMED": {
        "CONTAINMENT_RECOMMENDED",
        "CONTAINED",
        "RESOLVED",
        "CLOSED",
    },
    "CONTAINMENT_RECOMMENDED": {
        "INVESTIGATING",
        "CONTAINED",
        "RESOLVED",
        "CLOSED",
    },
    "CONTAINED": {"INVESTIGATING", "RESOLVED", "CLOSED"},
    "RESOLVED": {"INVESTIGATING", "CLOSED"},
    "CLOSED": set(),
}


class IncidentNotFound(LookupError):
    pass


class IncidentConflict(RuntimeError):
    pass


class IncidentService:
    def __init__(self, database: Neo4jConnection):
        self.database = database

    async def list_incidents(
        self,
        status: str | None,
        priority: str | None,
        skip: int,
        limit: int,
    ) -> dict[str, Any]:
        rows = await self.database.execute_read(
            queries.INCIDENT_LIST,
            parameters={
                "status": status.upper() if status else None,
                "priority": priority.lower() if priority else None,
                "skip": skip,
                "limit": limit,
            },
        )
        incidents = [
            self._format_incident(row["incident"], include_history=False)
            for row in rows
            if row.get("incident") is not None
        ]
        return {
            "incidents": incidents,
            "pagination": {"skip": skip, "limit": limit},
        }

    async def get_incident(self, incident_id: str) -> dict[str, Any]:
        rows = await self.database.execute_read(
            queries.INCIDENT_GET,
            parameters={"incident_id": incident_id},
        )
        if not rows or rows[0].get("incident") is None:
            raise IncidentNotFound(incident_id)
        return self._format_incident(rows[0]["incident"], include_history=True)

    async def create_incident(
        self,
        title: str,
        description: str | None,
        event_id: str | None,
        priority: str,
    ) -> dict[str, Any]:
        now = self._now()
        incident_id = f"INC-{uuid4().hex}"
        initial_status = "NEW"
        audit_entry = self._audit_entry(
            action="created",
            previous_value=None,
            new_value=initial_status,
            note=None,
            timestamp=now,
        )
        properties = {
            "id": incident_id,
            "type": "Incident",
            "title": title,
            "description": description,
            "related_event_id": event_id,
            "priority": priority.lower(),
            "status": initial_status,
            "created_at": now,
            "updated_at": now,
            "status_history": [self._serialize_audit(audit_entry)],
        }
        rows = await self.database.execute_write(
            queries.INCIDENT_CREATE,
            parameters={
                "event_id": event_id,
                "properties": properties,
            },
        )
        if not rows or rows[0].get("incident") is None:
            raise IncidentNotFound(event_id or "")
        return self._format_incident(rows[0]["incident"], include_history=True)

    async def update_status(
        self,
        incident_id: str,
        new_status: str,
        note: str | None,
    ) -> dict[str, Any]:
        status_rows = await self.database.execute_read(
            queries.INCIDENT_STATUS,
            parameters={"incident_id": incident_id},
        )
        if not status_rows:
            raise IncidentNotFound(incident_id)

        current_status = status_rows[0].get("status")
        normalized_status = str(current_status or "UNSET").upper()
        if new_status not in STATUS_TRANSITIONS.get(normalized_status, set()):
            raise IncidentConflict(
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
            queries.INCIDENT_UPDATE_STATUS,
            parameters={
                "incident_id": incident_id,
                "expected_status": current_status or "UNSET",
                "new_status": new_status,
                "updated_at": now,
                "audit_entry": self._serialize_audit(audit_entry),
            },
        )
        if not rows:
            raise IncidentConflict(
                "Incident status changed concurrently; reload and retry."
            )
        return self._format_incident(rows[0]["incident"], include_history=True)

    async def update_priority(
        self,
        incident_id: str,
        priority: str,
        note: str | None,
    ) -> dict[str, Any]:
        existing = await self.database.execute_read(
            queries.INCIDENT_GET,
            parameters={"incident_id": incident_id},
        )
        if not existing:
            raise IncidentNotFound(incident_id)

        current_priority = existing[0]["incident"].get("priority")
        now = self._now()
        audit_entry = self._audit_entry(
            action="priority_changed",
            previous_value=current_priority,
            new_value=priority.lower(),
            note=note,
            timestamp=now,
        )
        rows = await self.database.execute_write(
            queries.INCIDENT_UPDATE_PRIORITY,
            parameters={
                "incident_id": incident_id,
                "priority": priority.lower(),
                "updated_at": now,
                "audit_entry": self._serialize_audit(audit_entry),
            },
        )
        if not rows:
            raise IncidentNotFound(incident_id)
        return self._format_incident(rows[0]["incident"], include_history=True)

    async def get_timeline(self, incident_id: str) -> list[dict[str, Any]]:
        incident = await self.get_incident(incident_id)
        return incident["status_history"]

    @classmethod
    def _format_incident(
        cls,
        incident: dict[str, Any],
        include_history: bool,
    ) -> dict[str, Any]:
        result = dict(incident)
        history = result.pop("status_history", [])
        if include_history:
            result["status_history"] = [json.loads(entry) for entry in history]
        else:
            result["audit_entry_count"] = len(history)
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
    def _serialize_audit(entry: dict[str, Any]) -> str:
        return json.dumps(entry, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
