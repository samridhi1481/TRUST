import unittest

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


class StubDetectionEngine:
    async def predict_events(self, events):
        predictions = []
        for event in events:
            suspicious = event["event_id"] == "EVT-001"
            predictions.append({
                "event_id": event["event_id"],
                "entity_id": event.get("source_entity_id"),
                "prediction": "1" if suspicious else "0",
                "attack_category": "1" if suspicious else "0",
                "risk_score": 82.5 if suspicious else 8.0,
                "risk_level": "high" if suspicious else "low",
                "confidence": 0.91 if suspicious else 0.96,
                "model_confidence_percent": 91 if suspicious else 96,
                "explanation": ["Synthetic test model signal."],
                "top_features": [],
                "recommended_investigation_steps": "Review with an analyst.",
                "investigation_priority": {
                    "score": 82.5 if suspicious else 8.0,
                    "level": "high" if suspicious else "low",
                },
                "evidence_status": "model_generated_signal",
                "limitations": ["Synthetic model test."],
            })
        return predictions


class ThreatDatabase:
    def __init__(self):
        self.calls = []
        self.events = {
            "EVT-001": {
                "event_id": "EVT-001",
                "event_type": "network_connection",
                "event_time": "2026-11-20T10:00:00Z",
                "severity": "high",
                "source_entity_id": "HOST-001",
                "is_synthetic": True,
            },
            "EVT-002": {
                "event_id": "EVT-002",
                "event_type": "authentication",
                "event_time": "2026-11-20T11:00:00Z",
                "severity": "low",
                "source_entity_id": "HOST-002",
                "is_synthetic": True,
            },
        }

    async def execute_read(self, query, parameters=None):
        self.calls.append((query, parameters))
        if "SKIP $skip" in query:
            return [{"event": event} for event in self.events.values()]
        if "OBSERVED_ON" in query:
            return [{
                "labels": ["GraphNode", "Entity"],
                "properties": {"id": "HOST-001", "type": "Host"},
            }]
        if "SUPPORTED_BY" in query:
            return [{
                "evidence": {"evidence_id": "EVD-001", "event_id": "EVT-001"},
            }]
        threat_id = parameters["threat_id"]
        event = self.events.get(threat_id)
        return [{"event": event}] if event else []

    async def health(self):
        return {"status": "healthy"}

    async def close(self):
        pass


def make_settings() -> Settings:
    return Settings(
        neo4j_uri="",
        neo4j_username="",
        neo4j_password="",
        neo4j_database="neo4j",
        cors_origins=(),
        max_graph_depth=4,
    )


class ThreatRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = ThreatDatabase()
        self.client_context = TestClient(create_app(
            make_settings(),
            self.database,
            StubDetectionEngine(),
        ))
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)

    def test_threat_list_uses_member4_inference_and_separates_scores(self) -> None:
        response = self.client.get("/api/threats")

        self.assertEqual(response.status_code, 200)
        threat = response.json()["data"]["threats"][0]
        self.assertEqual(threat["event_id"], "EVT-001")
        self.assertEqual(threat["risk_score"], 82.5)
        self.assertEqual(threat["model_confidence_percent"], 91)
        self.assertNotEqual(threat["risk_score"], threat["model_confidence_percent"])
        self.assertTrue(threat["is_synthetic"])

    def test_high_risk_list_filters_using_investigation_priority(self) -> None:
        response = self.client.get("/api/threats/high-risk")

        self.assertEqual(response.status_code, 200)
        threats = response.json()["data"]["threats"]
        self.assertEqual([threat["event_id"] for threat in threats], ["EVT-001"])

    def test_threat_details_and_evidence_use_graph_trace_links(self) -> None:
        details = self.client.get("/api/threats/EVT-001")
        evidence = self.client.get("/api/threats/evidence/EVT-001")
        entities = self.client.get("/api/threats/associated-entities/EVT-001")

        self.assertEqual(details.status_code, 200)
        self.assertEqual(evidence.json()["data"]["evidence"][0]["evidence_id"], "EVD-001")
        self.assertEqual(
            entities.json()["data"]["entities"][0]["properties"]["id"],
            "HOST-001",
        )

    def test_non_suspicious_event_is_not_returned_as_threat(self) -> None:
        response = self.client.get("/api/threats/EVT-002")

        self.assertEqual(response.status_code, 404)
