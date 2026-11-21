from __future__ import annotations

from typing import Any

from ..database import queries
from ..database.neo4j_connection import Neo4jConnection
from ..utils.serialization import serialize_neo4j_value


class BlastRadiusService:
    MAX_PATHS = 300

    def __init__(self, database: Neo4jConnection, max_depth: int):
        if not 1 <= max_depth <= 6:
            raise ValueError("Maximum graph depth must be between 1 and 6.")
        self.database = database
        self.max_depth = max_depth

    async def analyze(
        self,
        entity_id: str,
        depth: int,
        excluded_entity_ids: list[str] | None = None,
    ) -> dict[str, Any] | None:
        if depth > self.max_depth:
            raise ValueError(f"Depth cannot exceed the configured maximum of {self.max_depth}.")
        query = queries.blast_radius_paths_query(depth)
        rows = await self.database.execute_read(
            query,
            parameters={
                "entity_id": entity_id,
                "excluded_entity_ids": excluded_entity_ids or [],
                "limit": self.MAX_PATHS,
            },
        )
        if not rows:
            return None

        source = {
            "labels": rows[0]["source_labels"],
            "properties": rows[0]["source_properties"],
        }
        source_id = source["properties"]["id"]
        reachable: dict[str, dict[str, Any]] = {}
        shortest_hops: dict[str, int] = {}
        relationships: dict[str, dict[str, Any]] = {}
        paths = []
        for row in rows:
            path_nodes = row["nodes"] or []
            path_relationships = row["relationships"] or []
            paths.append({
                "nodes": path_nodes,
                "relationships": path_relationships,
            })
            for hop, node in enumerate(path_nodes):
                node_id = node["id"]
                if node_id == source_id:
                    continue
                reachable.setdefault(node_id, node)
                shortest_hops[node_id] = min(
                    shortest_hops.get(node_id, hop),
                    hop,
                )
            for index, relationship in enumerate(path_relationships):
                key = relationship.get("id") or (
                    relationship.get("type"),
                    relationship.get("source_id"),
                    relationship.get("target_id"),
                    index,
                )
                relationships.setdefault(str(key), relationship)

        exposed_entities = [
            {
                **entity,
                "exposure_status": "potential",
                "hops_from_source": shortest_hops[entity_id],
            }
            for entity_id, entity in reachable.items()
        ]
        by_type: dict[str, int] = {}
        for entity in exposed_entities:
            entity_type = str(entity["properties"].get("type") or "unknown").lower()
            by_type[entity_type] = by_type.get(entity_type, 0) + 1

        critical_entities = [
            entity
            for entity in exposed_entities
            if str(entity["properties"].get("criticality", "")).lower() == "critical"
        ]
        direct_count = sum(1 for hops in shortest_hops.values() if hops == 1)
        indirect_count = len(shortest_hops) - direct_count

        return serialize_neo4j_value({
            "source_entity": source,
            "exposure_classification": "potential_exposure",
            "confirmed_compromise": {
                "available": False,
                "message": (
                    "The current entity contract has no confirmed-compromise field; "
                    "graph reachability is not evidence of compromise."
                ),
            },
            "depth": depth,
            "reachable_entity_count": len(exposed_entities),
            "directly_connected_count": direct_count,
            "indirectly_connected_count": indirect_count,
            "entities_by_type": by_type,
            "potentially_affected_users": by_type.get("user", 0),
            "potentially_affected_devices": by_type.get("host", 0),
            "potentially_affected_servers": by_type.get("server", 0),
            "applications_and_resources_at_risk": by_type.get("application", 0),
            "critical_infrastructure_exposure": len(critical_entities),
            "entities": exposed_entities,
            "relationships": list(relationships.values()),
            "paths": paths,
            "paths_truncated": len(rows) == self.MAX_PATHS,
        })
