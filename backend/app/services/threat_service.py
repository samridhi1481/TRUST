from __future__ import annotations

from typing import Any

from ..database import queries
from ..database.neo4j_connection import Neo4jConnection
from ..utils.serialization import serialize_neo4j_value
from .member4_detection import Member4DetectionEngine, is_suspicious_prediction


class ThreatService:
    def __init__(
        self,
        database: Neo4jConnection,
        detection_engine: Member4DetectionEngine,
    ):
        self.database = database
        self.detection_engine = detection_engine

    async def list_threats(
        self,
        skip: int,
        limit: int,
        high_risk_only: bool = False,
    ) -> dict[str, Any]:
        rows = await self.database.execute_read(
            queries.THREAT_EVENTS,
            parameters={"skip": skip, "limit": limit},
        )
        events = [
            serialize_neo4j_value(row["event"])
            for row in rows
            if row.get("event") is not None
        ]
        predictions = await self.detection_engine.predict_events(events)
        threats = [
            self._format_threat(event, prediction)
            for event, prediction in zip(events, predictions)
            if is_suspicious_prediction(prediction.get("prediction"))
            and (
                not high_risk_only
                or prediction.get("risk_level") in {"high", "critical"}
            )
        ]
        return {
            "threats": threats,
            "returned": len(threats),
            "pagination": {"skip": skip, "limit": limit},
            "source": "member4_on_demand_inference",
        }

    async def get_threat(self, threat_id: str) -> dict[str, Any] | None:
        rows = await self.database.execute_read(
            queries.THREAT_EVENT,
            parameters={"threat_id": threat_id},
        )
        if not rows or rows[0].get("event") is None:
            return None

        event = serialize_neo4j_value(rows[0]["event"])
        predictions = await self.detection_engine.predict_events([event])
        prediction = predictions[0]
        if not is_suspicious_prediction(prediction.get("prediction")):
            return None
        return self._format_threat(event, prediction)

    async def get_associated_entities(
        self,
        threat_id: str,
    ) -> list[dict[str, Any]] | None:
        threat = await self.get_threat(threat_id)
        if threat is None:
            return None
        rows = await self.database.execute_read(
            queries.THREAT_ASSOCIATED_ENTITIES,
            parameters={"threat_id": threat_id},
        )
        return [
            serialize_neo4j_value({"labels": row["labels"], "properties": row["properties"]})
            for row in rows
            if row.get("properties") is not None
        ]

    async def get_evidence(self, threat_id: str) -> list[dict[str, Any]] | None:
        threat = await self.get_threat(threat_id)
        if threat is None:
            return None
        rows = await self.database.execute_read(
            queries.THREAT_EVIDENCE,
            parameters={"threat_id": threat_id},
        )
        return [
            serialize_neo4j_value(row["evidence"])
            for row in rows
            if row.get("evidence") is not None
        ]

    @staticmethod
    def _format_threat(
        event: dict[str, Any],
        prediction: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "threat_id": event["event_id"],
            "event_id": event["event_id"],
            "entity_id": prediction.get("entity_id"),
            "event_type": event.get("event_type"),
            "event_time": event.get("event_time"),
            "severity": event.get("severity"),
            "description": event.get("description"),
            "evidence_id": event.get("evidence_id"),
            "attack_category": prediction.get("attack_category"),
            "prediction": prediction.get("prediction"),
            "model_name": prediction.get("model_name"),
            "model_version": prediction.get("model_version"),
            "risk_score": prediction.get("risk_score"),
            "risk_level": prediction.get("risk_level"),
            "confidence": prediction.get("confidence"),
            "model_confidence_percent": prediction.get("model_confidence_percent"),
            "explanation": prediction.get("explanation"),
            "top_features": prediction.get("top_features"),
            "recommended_investigation_steps": prediction.get(
                "recommended_investigation_steps"
            ),
            "investigation_priority": prediction.get("investigation_priority"),
            "evidence_status": prediction.get("evidence_status"),
            "is_synthetic": event.get("is_synthetic", False),
            "limitations": prediction.get("limitations", []),
        }
