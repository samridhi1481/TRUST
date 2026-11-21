
from member2_graph.src.graph_connection import Neo4jConnection


class GraphService:
    """Read-only graph intelligence operations for TRUSTRAIL AI."""

    def __init__(self, connection=None):
        self.connection = connection or Neo4jConnection()
        self._owns_connection = connection is None

    def close(self):
        if self._owns_connection:
            self.connection.close()

    def _run(self, query, **params):
        with self.connection.driver.session(
            database=self.connection.database
        ) as session:
            return list(session.run(query, **params))

    
    @staticmethod
    def _node(node):
        labels = list(node.labels)

        if "SecurityEvent" in labels:
            node_type = "SecurityEvent"
        elif "Evidence" in labels:
            node_type = "Evidence"
        else:
            node_type = node.get("type", "Entity")

        return {
            "id": node.get("id"),
            "type": node_type,
            "properties": dict(node)
        }

    @staticmethod
    def _edge(rel):
        return {
            "id": rel.get("relationship_id"),
            "source": rel.start_node.get("id"),
            "target": rel.end_node.get("id"),
            "type": type(rel).__name__,
            "properties": dict(rel)
        }

    def get_entity(self, entity_id):
        query = """
        MATCH (n:GraphNode {id: $entity_id})
        RETURN n
        """
        records = self._run(query, entity_id=entity_id)
        return self._node(records[0]["n"]) if records else None

    def get_neighbors(self, entity_id, depth=1):
        if not 1 <= depth <= 3:
            raise ValueError("Depth must be between 1 and 3.")

        query = """
        MATCH (start:GraphNode {id: $entity_id})
        MATCH p = (start)-[*1..3]-(neighbor:GraphNode)
        WHERE length(p) <= $depth
        RETURN DISTINCT neighbor
        """
        records = self._run(query, entity_id=entity_id, depth=depth)
        return [self._node(r["neighbor"]) for r in records]

    def get_subgraph(self, entity_id, depth=2):
        if not 1 <= depth <= 3:
            raise ValueError("Depth must be between 1 and 3.")

        query = """
        MATCH (start:GraphNode {id: $entity_id})
        MATCH p = (start)-[*1..3]-(neighbor:GraphNode)
        WHERE length(p) <= $depth
        UNWIND nodes(p) AS node
        WITH collect(DISTINCT node) AS graph_nodes
        UNWIND graph_nodes AS source
        OPTIONAL MATCH (source)-[rel]-(target:GraphNode)
        WHERE target IN graph_nodes
        RETURN graph_nodes, collect(DISTINCT rel) AS graph_edges
        """
        records = self._run(query, entity_id=entity_id, depth=depth)

        if not records:
            entity = self.get_entity(entity_id)
            return {
                "nodes": [entity] if entity else [],
                "edges": [],
                "metadata": {
                    "traversal_depth": depth,
                    "total_nodes": 1 if entity else 0,
                    "total_edges": 0
                }
            }

        nodes = {
            node["id"]: self._node(node)
            for node in records[0]["graph_nodes"]
        }
        edges = {
            rel.get("relationship_id"): self._edge(rel)
            for rel in records[0]["graph_edges"]
            if rel.get("relationship_id") is not None
        }

        return {
            "nodes": list(nodes.values()),
            "edges": list(edges.values()),
            "metadata": {
                "traversal_depth": depth,
                "total_nodes": len(nodes),
                "total_edges": len(edges)
            }
        }

    def find_attack_paths(self, source_id, target_id, max_depth=3):
        if not 1 <= max_depth <= 5:
            raise ValueError("Maximum depth must be between 1 and 5.")

        query = """
        MATCH (source:GraphNode {id: $source_id}),
              (target:GraphNode {id: $target_id})
        MATCH p = (source)-[*1..5]->(target)
        WHERE length(p) <= $max_depth
        RETURN p
        LIMIT 20
        """
        records = self._run(
            query,
            source_id=source_id,
            target_id=target_id,
            max_depth=max_depth
        )

        paths = []
        for record in records:
            path = record["p"]
            paths.append({
                "nodes": [self._node(n) for n in path.nodes],
                "edges": [self._edge(r) for r in path.relationships],
                "interpretation": "Potential graph path; not proof of compromise."
            })

        return paths

    def get_blast_radius(self, entity_id, max_depth=3):
        if not 1 <= max_depth <= 3:
            raise ValueError("Maximum depth must be between 1 and 3.")

        query = """
        MATCH (start:GraphNode {id: $entity_id})
        MATCH p = (start)-[*1..3]->(affected:GraphNode)
        WHERE length(p) <= $max_depth
        RETURN DISTINCT affected
        """
        records = self._run(
            query, entity_id=entity_id, max_depth=max_depth
        )

        return {
            "source_id": entity_id,
            "potentially_reachable": [
                self._node(r["affected"]) for r in records
            ],
            "interpretation": (
                "Graph reachability indicates potential exposure, "
                "not confirmed compromise."
            )
        }

    def get_entity_evidence(self, entity_id):
        query = """
        MATCH (event:GraphNode:SecurityEvent)-[:OBSERVED_ON]-
              (entity:GraphNode {id: $entity_id})
        MATCH (event)-[:SUPPORTED_BY]->(evidence:GraphNode:Evidence)
        RETURN DISTINCT event, evidence
        ORDER BY evidence.observed_at
        """
        records = self._run(query, entity_id=entity_id)

        return [
            {
                "event": self._node(r["event"]),
                "evidence": self._node(r["evidence"])
            }
            for r in records
        ]

    def get_incident_evidence(self, incident_id):
        query = """
        MATCH (incident:GraphNode {id: $incident_id})
              -[:INVOLVES]-(entity:GraphNode)
        MATCH (event:GraphNode:SecurityEvent)-[:OBSERVED_ON]-(entity)
        MATCH (event)-[:SUPPORTED_BY]->(evidence:GraphNode:Evidence)
        RETURN DISTINCT event, evidence
        ORDER BY evidence.observed_at
        """
        records = self._run(query, incident_id=incident_id)

        return [
            {
                "event": self._node(r["event"]),
                "evidence": self._node(r["evidence"])
            }
            for r in records
        ]
    
    def simulate_containment(self, entity_id, excluded_relationship_ids):
        """Simulate containment without modifying the actual Neo4j database."""
        query = """
        MATCH (start:GraphNode {id: $entity_id})
        OPTIONAL MATCH p = (start)-[*0..3]-(neighbor:GraphNode)
        WHERE ALL(rel IN relationships(p)
                  WHERE rel.relationship_category = 'original_entity'
                    AND NOT rel.relationship_id IN $excluded_ids)
        WITH start, collect(DISTINCT neighbor) AS reachable_nodes
        WITH [node IN reachable_nodes WHERE node IS NOT NULL] + [start]
             AS graph_nodes
        UNWIND graph_nodes AS source
        OPTIONAL MATCH (source)-[rel]-(target:GraphNode)
        WHERE target IN graph_nodes
          AND NOT rel.relationship_id IN $excluded_ids
        RETURN collect(DISTINCT source) AS graph_nodes,
               collect(DISTINCT rel) AS graph_edges
        """

        records = self._run(
            query,
            entity_id=entity_id,
            excluded_ids=excluded_relationship_ids
        )

        if not records:
            entity = self.get_entity(entity_id)
            return {
                "nodes": [entity] if entity else [],
                "edges": [],
                "simulation_only": True,
                "excluded_relationship_ids": excluded_relationship_ids
            }

        nodes = {
            node["id"]: self._node(node)
            for node in records[0]["graph_nodes"]
        }

        edges = {
            rel.get("relationship_id"): self._edge(rel)
            for rel in records[0]["graph_edges"]
            if rel is not None and rel.get("relationship_id") is not None
        }

        return {
            "nodes": list(nodes.values()),
            "edges": list(edges.values()),
            "simulation_only": True,
            "excluded_relationship_ids": excluded_relationship_ids
        }


    
    
def simulate_containment(self, entity_id, excluded_relationship_ids):
    """Simulate containment without modifying the actual Neo4j database.

    Only reachable infrastructure nodes and their connecting
    relationships are included in the simulated graph.
    """
    query = """
    MATCH (start:GraphNode {id: $entity_id})
    OPTIONAL MATCH p = (start)-[*0..3]-(neighbor:GraphNode)
    WHERE ALL(rel IN relationships(p)
              WHERE rel.relationship_category = 'original_entity'
                AND NOT rel.relationship_id IN $excluded_ids)
    WITH start, collect(DISTINCT neighbor) AS reachable_nodes
    WITH [node IN reachable_nodes WHERE node IS NOT NULL] + [start]
         AS graph_nodes
    UNWIND graph_nodes AS source
    OPTIONAL MATCH (source)-[rel]-(target:GraphNode)
    WHERE target IN graph_nodes
      AND NOT rel.relationship_id IN $excluded_ids
    RETURN collect(DISTINCT source) AS graph_nodes,
           collect(DISTINCT rel) AS graph_edges
    """

    records = self._run(
        query,
        entity_id=entity_id,
        excluded_ids=excluded_relationship_ids
    )

    if not records:
        entity = self.get_entity(entity_id)
        return {
            "nodes": [entity] if entity else [],
            "edges": [],
            "simulation_only": True,
            "excluded_relationship_ids": excluded_relationship_ids
        }

    nodes = {
        node["id"]: self._node(node)
        for node in records[0]["graph_nodes"]
    }

    edges = {
        rel.get("relationship_id"): self._edge(rel)
        for rel in records[0]["graph_edges"]
        if rel is not None and rel.get("relationship_id") is not None
    }

    return {
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "simulation_only": True,
        "excluded_relationship_ids": excluded_relationship_ids
    }

