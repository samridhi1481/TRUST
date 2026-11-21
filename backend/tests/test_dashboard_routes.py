import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


class DashboardDatabase:
    def __init__(self):
        self.overview = {
            "total_monitored_entities": 18,
            "devices": 6,
            "users": 3,
            "servers": 3,
            "active_incidents": 1,
        }
        self.events = [{
            "event_id": "EVT-001",
            "event_type": "authentication",
            "event_time": datetime(2026, 11, 20, tzinfo=timezone.utc),
            "severity": "medium",
            "description": "synthetic event",
            "is_synthetic": True,
        }]
        self.calls = []
        self.closed = False

    async def execute_read(self, query, parameters=None):
        self.calls.append((query, parameters))
        if "active_incident_statuses" in query:
            return [self.overview]
        if "properties(event) AS event" in query:
            return [{
                "event": {
                    "event_id": "EVT-001",
                    "event_type": "network_connection",
                    "event_time": "2026-11-20T10:00:00Z",
                    "severity": "high",
                    "is_synthetic": True,
                },
            }]
        if "investigation_id" in query:
            return []
        return self.events

    async def health(self):
        return {"status": "healthy"}

    async def close(self):
        self.closed = True


class DashboardDetectionEngine:
    async def predict_events(self, events):
        return [
            {
                "prediction": "1",
                "attack_category": "1",
            }
            for _ in events
        ]


def make_settings() -> Settings:
    return Settings(
        neo4j_uri="",
        neo4j_username="",
        neo4j_password="",
        neo4j_database="neo4j",
        cors_origins=("http://localhost:5173",),
        max_graph_depth=4,
    )


class DashboardRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = DashboardDatabase()
        self.client_context = TestClient(create_app(
            make_settings(),
            self.database,
            DashboardDetectionEngine(),
        ))
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)

    def test_overview_uses_graph_counts_and_marks_unknown_metrics(self) -> None:
        response = self.client.get("/api/dashboard/overview")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["counts"]["total_monitored_entities"], 18)
        self.assertIsNone(data["counts"]["detected_threats"])
        self.assertIn("detected_threats", data["unavailable_metrics"])

    def test_threat_distribution_uses_member4_inference(self) -> None:
        response = self.client.get("/api/dashboard/threat-distribution")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertTrue(data["available"])
        self.assertEqual(data["source"], "member4_on_demand_inference")
        self.assertEqual(data["distribution"], [{
            "severity": "high",
            "category": "1",
            "count": 1,
        }])

    def test_recent_activity_serializes_timestamps_and_bounds_limit(self) -> None:
        response = self.client.get("/api/dashboard/recent-activity?limit=1")

        self.assertEqual(response.status_code, 200)
        event = response.json()["data"]["events"][0]
        self.assertEqual(event["event_id"], "EVT-001")
        self.assertEqual(event["event_time"], "2026-11-20T00:00:00+00:00")
        self.assertEqual(response.json()["data"]["investigations"], [])
        self.assertTrue(response.json()["data"]["investigation_activity_available"])
        self.assertEqual(self.database.calls[-1][1], {"limit": 1})

        invalid_limit = self.client.get("/api/dashboard/recent-activity?limit=101")
        self.assertEqual(invalid_limit.status_code, 422)
