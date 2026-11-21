from __future__ import annotations

from collections import Counter
from typing import Any

from ..database import queries
from ..database.neo4j_connection import Neo4jConnection
from ..utils.serialization import serialize_neo4j_value
from .member4_detection import Member4DetectionEngine, is_suspicious_prediction


ACTIVE_INCIDENT_STATUSES = [
    "NEW",
    "INVESTIGATING",
    "CONFIRMED",
    "CONTAINMENT_RECOMMENDED",
    "CONTAINED",
]


class DashboardService:
    THREAT_DISTRIBUTION_LIMIT = 20

    def __init__(
        self,
        database: Neo4jConnection,
        detection_engine: Member4DetectionEngine,
    ):
        self.database = database
        self.detection_engine = detection_engine

    async def get_overview(self) -> dict[str, Any]:
        rows = await self.database.execute_read(
            queries.DASHBOARD_OVERVIEW,
            parameters={
                "device_types": ["host", "server"],
                "active_incident_statuses": ACTIVE_INCIDENT_STATUSES,
            },
        )
        if len(rows) != 1:
            raise RuntimeError("Dashboard overview query did not return its aggregate row.")

        row = rows[0]
        unavailable = {
            "suspicious_ip_addresses": (
                "The entity contract has no confirmed suspicious-IP indicator."
            ),
            "detected_threats": (
                "Predictions are computed on demand; complete counts require persisted detections."
            ),
            "critical_alerts": (
                "No persisted alert record contract is available."
            ),
            "high_risk_entities": (
                "No confirmed entity risk-score field is available."
            ),
            "current_investigation_count": (
                "Investigation records are not currently persisted in Neo4j."
            ),
        }
        counts = {
            "total_monitored_entities": row["total_monitored_entities"],
            "devices": row["devices"],
            "users": row["users"],
            "servers": row["servers"],
            "suspicious_ip_addresses": None,
            "detected_threats": None,
            "active_incidents": row["active_incidents"],
            "critical_alerts": None,
            "high_risk_entities": None,
            "current_investigation_count": None,
        }
        return {
            "counts": counts,
            "unavailable_metrics": unavailable,
        }

    async def get_threat_distribution(self) -> dict[str, Any]:
        rows = await self.database.execute_read(
            queries.THREAT_EVENTS,
            parameters={"skip": 0, "limit": self.THREAT_DISTRIBUTION_LIMIT},
        )
        events = [serialize_neo4j_value(row["event"]) for row in rows]
        predictions = await self.detection_engine.predict_events(events)
        distribution = Counter(
            (
                str(event.get("severity") or "unknown"),
                str(prediction.get("attack_category") or "unknown"),
            )
            for event, prediction in zip(events, predictions)
            if is_suspicious_prediction(prediction.get("prediction"))
        )
        return {
            "available": True,
            "source": "member4_on_demand_inference",
            "distribution": [
                {"severity": severity, "category": category, "count": count}
                for (severity, category), count in sorted(distribution.items())
            ],
            "events_evaluated": len(events),
            "evaluation_limit": self.THREAT_DISTRIBUTION_LIMIT,
            "may_be_truncated": len(events) == self.THREAT_DISTRIBUTION_LIMIT,
            "limitations": [
                "Only the first 20 events in the selected page are evaluated.",
                "The bundled model was evaluated on a small synthetic dataset.",
            ],
        }

    async def get_recent_activity(self, limit: int) -> dict[str, Any]:
        rows = await self.database.execute_read(
            queries.DASHBOARD_RECENT_EVENTS,
            parameters={"limit": limit},
        )
        events = [serialize_neo4j_value(row) for row in rows]
        investigation_rows = await self.database.execute_read(
            queries.INVESTIGATION_RECENT_ACTIVITY,
            parameters={"limit": limit},
        )
        investigations = [
            serialize_neo4j_value(row)
            for row in investigation_rows
        ]
        return {
            "events": events,
            "investigations": investigations,
            "investigation_activity_available": True,
        }
