import json
import unittest

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


class InvestigationDatabase:
    def __init__(self):
        self.investigations = {}
        self.event_ids = {"EVT-001"}
        self.entity_ids = {"HOST-001"}
        self.evidence = {
            "EVD-001": {"evidence_id": "EVD-001", "event_id": "EVT-001"},
        }

    async def execute_read(self, query, parameters=None):
        parameters = parameters or {}
        investigation_id = parameters.get("investigation_id")
        if "investigation.status AS status" in query:
            investigation = self.investigations.get(investigation_id)
            return [{"status": investigation["status"]}] if investigation else []
        if "properties(evidence) AS evidence" in query:
            investigation = self.investigations.get(investigation_id)
            if not investigation:
                return []
            return [
                {"evidence": self.evidence[evidence_id]}
                for evidence_id in investigation["evidence_ids"]
            ]
        if "properties(investigation)" in query:
            if "SKIP $skip" in query:
                return [
                    {"investigation": investigation}
                    for investigation in self.investigations.values()
                ]
            investigation = self.investigations.get(investigation_id)
            return [{"investigation": investigation}] if investigation else []
        return []

    async def execute_write(self, query, parameters=None):
        if "CREATE (investigation:GraphNode:Entity)" in query:
            if parameters["alert_id"] not in (None, *self.event_ids):
                return []
            if any(entity_id not in self.entity_ids for entity_id in parameters["entity_ids"]):
                return []
            investigation = dict(parameters["properties"])
            self.investigations[investigation["id"]] = investigation
            return [{"investigation": investigation}]

        investigation = self.investigations.get(parameters["investigation_id"])
        if investigation is None:
            return []
        if "investigation.notes =" in query:
            investigation["notes"].append(parameters["note_entry"])
            investigation["audit_history"].append(parameters["audit_entry"])
            investigation["updated_at"] = parameters["updated_at"]
        elif "investigation.evidence_ids =" in query:
            evidence_id = parameters["evidence_id"]
            if evidence_id not in self.evidence:
                return []
            already_attached = evidence_id in investigation["evidence_ids"]
            if not already_attached:
                investigation["evidence_ids"].append(evidence_id)
                investigation["audit_history"].append(parameters["audit_entry"])
                investigation["updated_at"] = parameters["updated_at"]
            return [{
                "investigation": investigation,
                "already_attached": already_attached,
            }]
        elif "investigation.status = $new_status" in query:
            if investigation["status"] != parameters["expected_status"]:
                return []
            investigation["status"] = parameters["new_status"]
            investigation["audit_history"].append(parameters["audit_entry"])
            investigation["updated_at"] = parameters["updated_at"]
        return [{"investigation": investigation}]

    async def health(self):
        return {"status": "healthy"}

    async def close(self):
        pass


def make_settings():
    return Settings(
        neo4j_uri="",
        neo4j_username="",
        neo4j_password="",
        neo4j_database="neo4j",
        cors_origins=(),
        max_graph_depth=4,
    )


class InvestigationRouteTests(unittest.TestCase):
    def setUp(self):
        self.database = InvestigationDatabase()
        self.client_context = TestClient(create_app(make_settings(), self.database))
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)

    def create_investigation(self):
        return self.client.post("/api/investigations", json={
            "title": "Investigate suspicious activity",
            "alert_id": "EVT-001",
            "entity_ids": ["HOST-001"],
        })

    def test_create_add_notes_attach_evidence_and_read_timeline(self):
        created = self.create_investigation()

        self.assertEqual(created.status_code, 201)
        investigation = created.json()["data"]
        investigation_id = investigation["id"]
        self.assertEqual(investigation["status"], "OPEN")

        note_response = self.client.post(
            f"/api/investigations/{investigation_id}/notes",
            json={"content": "Reviewed source event."},
        )
        self.assertEqual(note_response.status_code, 200)

        evidence_response = self.client.post(
            f"/api/investigations/{investigation_id}/evidence",
            json={"evidence_id": "EVD-001"},
        )
        self.assertEqual(evidence_response.status_code, 200)

        evidence = self.client.get(
            f"/api/investigations/{investigation_id}/evidence"
        )
        self.assertEqual(evidence.json()["data"]["evidence"][0]["evidence_id"], "EVD-001")

        status_response = self.client.patch(
            f"/api/investigations/{investigation_id}/status",
            json={"status": "IN_PROGRESS", "note": "Triage started."},
        )
        self.assertEqual(status_response.status_code, 200)

        detail = self.client.get(f"/api/investigations/{investigation_id}")
        data = detail.json()["data"]
        self.assertEqual(data["notes"][0]["content"], "Reviewed source event.")
        self.assertEqual(data["status"], "IN_PROGRESS")
        self.assertEqual(len(data["audit_history"]), 4)

        timeline = self.client.get(
            f"/api/investigations/{investigation_id}/timeline"
        )
        self.assertEqual(len(timeline.json()["data"]["timeline"]), 4)
        persisted_history = self.database.investigations[investigation_id]["audit_history"]
        self.assertTrue(all(isinstance(json.loads(entry), dict) for entry in persisted_history))

    def test_missing_references_and_invalid_status_transitions_are_rejected(self):
        missing_reference = self.client.post("/api/investigations", json={
            "title": "Missing alert",
            "alert_id": "EVT-MISSING",
        })
        created = self.create_investigation()
        investigation_id = created.json()["data"]["id"]
        invalid_transition = self.client.patch(
            f"/api/investigations/{investigation_id}/status",
            json={"status": "OPEN"},
        )

        self.assertEqual(missing_reference.status_code, 404)
        self.assertEqual(invalid_transition.status_code, 409)

    def test_duplicate_evidence_attachment_is_idempotent(self):
        created = self.create_investigation()
        investigation_id = created.json()["data"]["id"]
        endpoint = f"/api/investigations/{investigation_id}/evidence"

        first = self.client.post(endpoint, json={"evidence_id": "EVD-001"})
        history_count = len(first.json()["data"]["audit_history"])
        second = self.client.post(endpoint, json={"evidence_id": "EVD-001"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(second.json()["data"]["audit_history"]), history_count)
