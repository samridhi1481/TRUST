
import unittest

from member2_graph.src.graph_service import GraphService


class FakeNode(dict):
    def __init__(self, node_id, node_type="Entity", labels=None):
        super().__init__(id=node_id, type=node_type)
        self.labels = labels or ["GraphNode"]


class FakeRelationship(dict):
    def __init__(self, relationship_id, source, target):
        super().__init__(
            relationship_id=relationship_id,
            relationship_category="original_entity"
        )
        self.start_node = source
        self.end_node = target


class FakePath:
    def __init__(self, nodes, relationships):
        self.nodes = nodes
        self.relationships = relationships


class FakeConnection:
    def close(self):
        pass


class GraphServiceTests(unittest.TestCase):

    def setUp(self):
        self.service = GraphService(connection=FakeConnection())
        self.user = FakeNode("USR-001", "User", ["GraphNode", "Entity"])
        self.host = FakeNode("HOST-001", "Host", ["GraphNode", "Entity"])
        self.ip = FakeNode("IP-001", "IPAddress", ["GraphNode", "Entity"])
        self.event = FakeNode(
            "EVT-001", labels=["GraphNode", "SecurityEvent"]
        )
        self.evidence = FakeNode(
            "EVD-001", labels=["GraphNode", "Evidence"]
        )
        self.rel = FakeRelationship("REL-001", self.user, self.host)

    def tearDown(self):
        self.service.close()

    def test_get_entity(self):
        self.service._run = lambda *a, **k: [{"n": self.user}]
        result = self.service.get_entity("USR-001")
        self.assertEqual(result["id"], "USR-001")
        self.assertEqual(result["type"], "User")

    def test_get_entity_not_found(self):
        self.service._run = lambda *a, **k: []
        self.assertIsNone(self.service.get_entity("UNKNOWN"))

    def test_get_neighbors(self):
        self.service._run = lambda *a, **k: [
            {"neighbor": self.host}
        ]
        result = self.service.get_neighbors("USR-001", depth=1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "HOST-001")

    def test_neighbors_reject_invalid_depth(self):
        with self.assertRaises(ValueError):
            self.service.get_neighbors("USR-001", depth=4)

    def test_get_subgraph(self):
        self.service._run = lambda *a, **k: [{
            "graph_nodes": [self.user, self.host],
            "graph_edges": [self.rel]
        }]
        result = self.service.get_subgraph("USR-001", depth=2)
        self.assertEqual(result["metadata"]["total_nodes"], 2)
        self.assertEqual(result["metadata"]["total_edges"], 1)
        self.assertEqual(result["edges"][0]["source"], "USR-001")
        self.assertEqual(result["edges"][0]["target"], "HOST-001")

    def test_find_attack_paths(self):
        path = FakePath([self.user, self.host], [self.rel])
        self.service._run = lambda *a, **k: [{"p": path}]
        result = self.service.find_attack_paths(
            "USR-001", "HOST-001", max_depth=2
        )
        self.assertEqual(len(result), 1)
        self.assertIn("not proof of compromise", result[0]["interpretation"])

    def test_attack_path_rejects_invalid_depth(self):
        with self.assertRaises(ValueError):
            self.service.find_attack_paths("USR-001", "HOST-001", 6)

    def test_get_blast_radius(self):
        self.service._run = lambda *a, **k: [
            {"affected": self.host},
            {"affected": self.ip}
        ]
        result = self.service.get_blast_radius("USR-001", max_depth=2)
        self.assertEqual(len(result["potentially_reachable"]), 2)
        self.assertIn("not confirmed compromise", result["interpretation"])

    def test_get_entity_evidence(self):
        self.service._run = lambda *a, **k: [{
            "event": self.event,
            "evidence": self.evidence
        }]
        result = self.service.get_entity_evidence("HOST-001")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["event"]["id"], "EVT-001")
        self.assertEqual(result[0]["evidence"]["id"], "EVD-001")

    def test_get_incident_evidence(self):
        self.service._run = lambda *a, **k: [{
            "event": self.event,
            "evidence": self.evidence
        }]
        result = self.service.get_incident_evidence("INC-001")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["evidence"]["type"], "Evidence")

    def test_simulate_containment_excludes_relationship(self):
        remaining_rel = FakeRelationship("REL-002", self.user, self.host)
        self.service._run = lambda *a, **k: [{
            "graph_nodes": [self.user, self.host],
            "graph_edges": [remaining_rel]
        }]
        result = self.service.simulate_containment(
            "USR-001", ["REL-001"]
        )
        edge_ids = [edge["id"] for edge in result["edges"]]
        self.assertTrue(result["simulation_only"])
        self.assertIn("REL-001", result["excluded_relationship_ids"])
        self.assertNotIn("REL-001", edge_ids)
        self.assertIn("REL-002", edge_ids)

    def test_node_type_detection(self):
        self.assertEqual(
            GraphService._node(self.event)["type"], "SecurityEvent"
        )
        self.assertEqual(
            GraphService._node(self.evidence)["type"], "Evidence"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
