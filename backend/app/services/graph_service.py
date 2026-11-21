from __future__ import annotations

from typing import Any

from ..database import queries
from ..database.neo4j_connection import Neo4jConnection
from ..utils.serialization import serialize_neo4j_value


class GraphService:
    def __init__(self, database: Neo4jConnection, max_depth: int):
        if not 1 <= max_depth <= 6:
            raise ValueError("Maximum graph depth must be between 1 and 6.")
        self.database = database
        self.max_depth = max_depth

    async def get_overview(self) -> dict[str, int]:
        rows = await self.database.execute_read(queries.GRAPH_OVERVIEW)
        if len(rows) != 1:
            raise RuntimeError("Graph overview query did not return its aggregate row.")
        return rows[0]

    async def get_entities(
        self,
        entity_type: str | None,
        risk_level: str | None,
        skip: int,
        limit: int,
    ) -> dict[str, Any]:
        risk_filter_available: bool | None = None
        if risk_level is not None:
            coverage = await self.database.execute_read(queries.GRAPH_RISK_LEVEL_COVERAGE)
            risk_filter_available = bool(
                coverage and coverage[0]["labeled_entities"] > 0
            )
            if not risk_filter_available:
                return {
                    "entities": [],
                    "risk_filter": {
                        "requested": risk_level,
                        "available": False,
                        "message": (
                            "No entities currently have a persisted risk_level property."
                        ),
                    },
                }

        rows = await self.database.execute_read(
            queries.GRAPH_ENTITIES,
            parameters={
                "entity_type": entity_type,
                "risk_level": risk_level,
                "skip": skip,
                "limit": limit,
            },
        )
        result = {
            "entities": [serialize_neo4j_value(row) for row in rows],
            "pagination": {"skip": skip, "limit": limit},
        }
        if risk_filter_available is not None:
            result["risk_filter"] = {
                "requested": risk_level,
                "available": risk_filter_available,
                "field": "risk_level",
            }
        return result

    async def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        rows = await self.database.execute_read(
            queries.GRAPH_ENTITY,
            parameters={"entity_id": entity_id},
        )
        return serialize_neo4j_value(rows[0]) if rows else None

    async def get_neighbors(self, entity_id: str) -> dict[str, Any] | None:
        rows = await self.database.execute_read(
            queries.GRAPH_NEIGHBORS,
            parameters={"entity_id": entity_id},
        )
        if not rows:
            return None

        entity = {
            "labels": rows[0]["entity_labels"],
            "properties": rows[0]["entity_properties"],
        }
        neighbors = []
        for row in rows:
            if row["neighbor_properties"] is None:
                continue
            neighbors.append({
                "labels": row["neighbor_labels"],
                "properties": row["neighbor_properties"],
                "relationship": {
                    "type": row["relationship_type"],
                    "properties": row["relationship_properties"],
                    "source_id": row["source_id"],
                    "target_id": row["target_id"],
                },
            })
        return serialize_neo4j_value({"entity": entity, "neighbors": neighbors})

    async def get_relationships(self, entity_id: str) -> dict[str, Any] | None:
        rows = await self.database.execute_read(
            queries.GRAPH_RELATIONSHIPS,
            parameters={"entity_id": entity_id},
        )
        if not rows:
            return None
        relationships = [
            {
                "type": row["type"],
                "properties": row["properties"],
                "source_id": row["source_id"],
                "target_id": row["target_id"],
                "neighbor": {
                    "labels": row["neighbor_labels"],
                    "properties": row["neighbor_properties"],
                },
            }
            for row in rows
            if row["type"] is not None
        ]
        return serialize_neo4j_value({"relationships": relationships})

    async def get_subgraph(
        self,
        entity_id: str,
        depth: int,
        limit: int,
    ) -> dict[str, Any] | None:
        if depth > self.max_depth:
            raise ValueError(f"Depth cannot exceed the configured maximum of {self.max_depth}.")
        query = queries.graph_subgraph_query(depth)
        rows = await self.database.execute_read(
            query,
            parameters={"entity_id": entity_id, "limit": limit},
        )
        if not rows:
            return None

        root = {
            "labels": rows[0]["source_labels"],
            "properties": rows[0]["source_properties"],
        }
        nodes: dict[str, dict[str, Any]] = {}
        relationships: dict[str, dict[str, Any]] = {}
        for row in rows:
            for node in row["nodes"]:
                nodes.setdefault(node["id"], node)
            for relationship in row["relationships"]:
                relationship_id = relationship.get("id")
                if relationship_id is not None:
                    relationships.setdefault(relationship_id, relationship)
        return serialize_neo4j_value({
            "root": root,
            "nodes": list(nodes.values()),
            "relationships": list(relationships.values()),
            "depth": depth,
            "path_limit": limit,
        })
