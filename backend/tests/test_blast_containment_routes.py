import unittest

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


def graph_node(entity_id, entity_type, criticality="low"):
    return {
        "id": entity_id,
        "labels": ["GraphNode", "Entity"],
        "properties": {
            "id": entity_id,
            "type": entity_type,
            "criticality": criticality,
        },
    }


def graph_relationship(relationship_id, source_id, target_id):
    return {
        "id": relationship_id,
        "type": "COMMUNICATES_WITH",
        "source_id": source_id,
        "target_id": target_id,
        "properties": {"relationship_category": "original_entity"},
    }


class BlastContainmentDatabase:
    def __init__(self):
        self.source_exists = True
        self.write_calls = 0

    async def execute_read(self, query, parameters=None):
        parameters = parameters or {}
        if "OPTIONAL MATCH path" in query:
            if not self.source_exists:
                return []
            root = graph_node("HOST-001", "Host")
            paths = []
            excluded = set(parameters["excluded_entity_ids"])
            if "SRV-001" not in excluded and "HOST-001" not in excluded:
                paths.append({
                    "source_labels": root["labels"],
                    "source_properties": root["properties"],
                    "nodes": [
                        root,
                        graph_node("SRV-001", "Server", "high"),
                        graph_node("APP-001", "Application", "critical"),
                    ],
                    "relationships": [
                        graph_relationship("REL-001", "HOST-001", "SRV-001"),
                        graph_relationship("REL-002", "SRV-001", "APP-001"),
                    ],
                })
            if "HOST-001" not in excluded:
                paths.append({
                    "source_labels": root["labels"],
                    "source_properties": root["properties"],
                    "nodes": [root, graph_node("USR-001", "User")],
                    "relationships": [
                        graph_relationship("REL-003", "HOST-001", "USR-001"),
                    ],
                })
            if not paths:
                paths.append({
                    "source_labels": root["labels"],
                    "source_properties": root["properties"],
                    "nodes": [],
                    "relationships": [],
                })
            return paths
        if "entity.id IN $entity_ids" in query:
            types = {
                "HOST-001": "Host",
                "SRV-001": "Server",
                "USR-001": "User",
            }
            return [
                {"id": entity_id, "type": types[entity_id]}
                for entity_id in parameters["entity_ids"]
                if entity_id in types
            ]
        if "entity.type AS type" in query:
            return [{"id": parameters["entity_id"], "type": "Host"}]
        return []

    async def execute_write(self, query, parameters=None):
        self.write_calls += 1
        raise AssertionError("Containment simulation must not write to Neo4j.")

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


class BlastContainmentRouteTests(unittest.TestCase):
    def setUp(self):
        self.database = BlastContainmentDatabase()
        self.client_context = TestClient(create_app(make_settings(), self.database))
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)

    def test_blast_radius_classifies_reachable_entities_as_potential(self):
        response = self.client.get("/api/blast-radius/HOST-001?depth=3")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["reachable_entity_count"], 3)
        self.assertEqual(data["directly_connected_count"], 2)
        self.assertEqual(data["indirectly_connected_count"], 1)
        self.assertEqual(data["critical_infrastructure_exposure"], 1)
        self.assertEqual(data["exposure_classification"], "potential_exposure")
        self.assertFalse(data["confirmed_compromise"]["available"])

    def test_containment_returns_before_after_without_database_writes(self):
        response = self.client.post("/api/containment/simulate", json={
            "source_entity_id": "HOST-001",
            "depth": 3,
            "actions": [{
                "action": "restrict_server",
                "target_entity_id": "SRV-001",
            }],
        })

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["mode"], "SIMULATION_ONLY")
        self.assertEqual(data["before"]["potentially_affected_entities"], 3)
        self.assertEqual(data["after"]["remaining_exposed_entities"], 1)
        self.assertEqual(data["business_services_potentially_disrupted"], 1)
        self.assertEqual(data["connectivity_removed"], 2)
        self.assertEqual(self.database.write_calls, 0)

    def test_invalid_action_target_type_is_rejected(self):
        response = self.client.post("/api/containment/simulate", json={
            "source_entity_id": "HOST-001",
            "actions": [{
                "action": "block_ip",
                "target_entity_id": "HOST-001",
            }],
        })

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.database.write_calls, 0)

    def test_containment_comparison_runs_named_scenarios(self):
        response = self.client.post("/api/containment/compare", json={
            "scenarios": [{
                "name": "Restrict app server",
                "source_entity_id": "HOST-001",
                "depth": 2,
                "actions": [{
                    "action": "restrict_server",
                    "target_entity_id": "SRV-001",
                }],
            }],
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"]["scenarios"][0]["name"],
            "Restrict app server",
        )
