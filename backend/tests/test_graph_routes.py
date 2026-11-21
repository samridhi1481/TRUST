import unittest

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


class GraphDatabase:
    def __init__(self):
        self.calls = []
        self.entity_exists = True
        self.risk_labeled_count = 0
        self.closed = False

    async def execute_read(self, query, parameters=None):
        self.calls.append((query, parameters))
        if "total_nodes" in query:
            return [{
                "total_nodes": 3,
                "total_entities": 1,
                "total_events": 1,
                "total_evidence": 1,
                "total_relationships": 2,
            }]
        if "labeled_entities" in query:
            return [{"labeled_entities": self.risk_labeled_count}]
        if "SKIP $skip" in query:
            return [{
                "labels": ["GraphNode", "Entity"],
                "properties": {"id": "HOST-001", "type": "Host"},
            }]
        if "OPTIONAL MATCH path" in query:
            if not self.entity_exists:
                return []
            return [{
                "source_labels": ["GraphNode", "Entity"],
                "source_properties": {"id": "HOST-001", "type": "Host"},
                "nodes": [{
                    "id": "HOST-001",
                    "labels": ["GraphNode", "Entity"],
                    "properties": {"id": "HOST-001", "type": "Host"},
                }],
                "relationships": [],
            }]
        if "OPTIONAL MATCH (entity)-[relationship]-(neighbor" in query:
            if not self.entity_exists:
                return []
            return [{
                "entity_labels": ["GraphNode", "Entity"],
                "entity_properties": {"id": "HOST-001", "type": "Host"},
                "neighbor_labels": None,
                "neighbor_properties": None,
                "relationship_type": None,
                "relationship_properties": None,
                "source_id": None,
                "target_id": None,
            }]
        if "RETURN labels(entity)" in query:
            if not self.entity_exists:
                return []
            return [{
                "labels": ["GraphNode", "Entity"],
                "properties": {"id": "HOST-001", "type": "Host"},
            }]
        return []

    async def health(self):
        return {"status": "healthy"}

    async def close(self):
        self.closed = True


def make_settings(max_graph_depth: int = 4) -> Settings:
    return Settings(
        neo4j_uri="",
        neo4j_username="",
        neo4j_password="",
        neo4j_database="neo4j",
        cors_origins=(),
        max_graph_depth=max_graph_depth,
    )


class GraphRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = GraphDatabase()
        self.client_context = TestClient(create_app(make_settings(), self.database))
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)

    def test_graph_overview_returns_actual_aggregate_counts(self) -> None:
        response = self.client.get("/api/graph/overview")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["total_relationships"], 2)

    def test_entities_apply_parameterized_type_and_pagination_filters(self) -> None:
        response = self.client.get(
            "/api/graph/entities?entity_type=Host&skip=5&limit=10"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["entities"][0]["properties"]["id"], "HOST-001")
        query, parameters = self.database.calls[-1]
        self.assertIn("$entity_type", query)
        self.assertEqual(parameters, {
            "entity_type": "Host",
            "risk_level": None,
            "skip": 5,
            "limit": 10,
        })

    def test_missing_risk_data_is_reported_instead_of_fabricating_results(self) -> None:
        response = self.client.get("/api/graph/entities?risk_level=high")

        self.assertEqual(response.status_code, 200)
        risk_filter = response.json()["data"]["risk_filter"]
        self.assertFalse(risk_filter["available"])
        self.assertEqual(response.json()["data"]["entities"], [])

    def test_missing_entity_returns_404(self) -> None:
        self.database.entity_exists = False
        response = self.client.get("/api/graph/entity/UNKNOWN")

        self.assertEqual(response.status_code, 404)

    def test_subgraph_depth_is_limited_by_configuration(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.database = GraphDatabase()
        self.client_context = TestClient(create_app(make_settings(max_graph_depth=2), self.database))
        self.client = self.client_context.__enter__()

        response = self.client.get("/api/graph/subgraph/HOST-001?depth=3")

        self.assertEqual(response.status_code, 422)
        self.assertFalse(any("OPTIONAL MATCH path" in query for query, _ in self.database.calls))

    def test_subgraph_returns_root_even_when_it_has_no_paths(self) -> None:
        response = self.client.get("/api/graph/subgraph/HOST-001?depth=2")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["root"]["properties"]["id"], "HOST-001")
        self.assertEqual(data["nodes"], [{"id": "HOST-001", "labels": ["GraphNode", "Entity"], "properties": {"id": "HOST-001", "type": "Host"}}])
