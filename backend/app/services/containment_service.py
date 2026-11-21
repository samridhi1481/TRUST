from __future__ import annotations

from typing import Any

from ..database import queries
from ..database.neo4j_connection import Neo4jConnection
from ..schemas.containment_schema import ContainmentAction
from .blast_radius_service import BlastRadiusService


EXPECTED_ENTITY_TYPES = {
    "isolate_entity": "host",
    "disable_account": "user",
    "block_ip": "ipaddress",
    "restrict_server": "server",
}


class ContainmentTargetNotFound(LookupError):
    pass


class InvalidContainmentAction(ValueError):
    pass


class ContainmentService:
    def __init__(
        self,
        database: Neo4jConnection,
        max_depth: int,
    ):
        self.database = database
        self.blast_radius = BlastRadiusService(database, max_depth)

    async def simulate(
        self,
        source_entity_id: str,
        depth: int,
        actions: list[ContainmentAction],
    ) -> dict[str, Any]:
        action_records = [
            {"action": action.action.value, "target_entity_id": action.target_entity_id}
            for action in actions
        ]
        target_ids = [action["target_entity_id"] for action in action_records]
        if len(set(target_ids)) != len(target_ids):
            raise InvalidContainmentAction(
                "Each containment target may appear only once per simulation."
            )

        target_rows = await self.database.execute_read(
            queries.ENTITY_TYPES_BY_IDS,
            parameters={"entity_ids": target_ids},
        )
        entity_types = {row["id"]: str(row["type"]).lower() for row in target_rows}
        missing_ids = sorted(set(target_ids) - set(entity_types))
        if missing_ids:
            raise ContainmentTargetNotFound(missing_ids[0])

        excluded_entity_ids = []
        for action in action_records:
            expected_type = EXPECTED_ENTITY_TYPES[action["action"]]
            actual_type = entity_types[action["target_entity_id"]]
            if actual_type != expected_type:
                raise InvalidContainmentAction(
                    f"{action['action']} requires a {expected_type} entity; "
                    f"{action['target_entity_id']} is {actual_type}."
                )
            excluded_entity_ids.append(action["target_entity_id"])

        before = await self.blast_radius.analyze(source_entity_id, depth)
        if before is None:
            raise ContainmentTargetNotFound(source_entity_id)
        after = await self.blast_radius.analyze(
            source_entity_id,
            depth,
            excluded_entity_ids=excluded_entity_ids,
        )
        if after is None:
            raise ContainmentTargetNotFound(source_entity_id)

        before_entities = {
            entity["properties"]["id"]: entity
            for entity in before["entities"]
        }
        after_entities = {
            entity["properties"]["id"]: entity
            for entity in after["entities"]
        }
        removed_entities = [
            before_entities[entity_id]
            for entity_id in sorted(before_entities.keys() - after_entities.keys())
        ]
        before_relationship_ids = {
            relationship.get("id")
            for relationship in before["relationships"]
            if relationship.get("id") is not None
        }
        after_relationship_ids = {
            relationship.get("id")
            for relationship in after["relationships"]
            if relationship.get("id") is not None
        }

        baseline_count = len(before_entities)
        remaining_count = len(after_entities)
        residual_percentage = (
            round(remaining_count / baseline_count * 100, 2)
            if baseline_count
            else 0.0
        )
        return {
            "mode": "SIMULATION_ONLY",
            "source_entity_id": source_entity_id,
            "depth": depth,
            "actions": action_records,
            "before": {
                "potentially_affected_entities": baseline_count,
                "critical_assets_reachable": before["critical_infrastructure_exposure"],
                "users_potentially_affected": before["potentially_affected_users"],
                "business_services_reachable": before["applications_and_resources_at_risk"],
                "reachable_entity_ids": sorted(before_entities),
            },
            "after": {
                "remaining_exposed_entities": remaining_count,
                "critical_assets_still_reachable": after["critical_infrastructure_exposure"],
                "users_still_potentially_affected": after["potentially_affected_users"],
                "business_services_still_reachable": after["applications_and_resources_at_risk"],
                "reachable_entity_ids": sorted(after_entities),
            },
            "connectivity_removed": len(before_relationship_ids - after_relationship_ids),
            "entities_no_longer_reachable": [
                entity["properties"]["id"] for entity in removed_entities
            ],
            "users_potentially_impacted": sum(
                1 for entity in removed_entities
                if str(entity["properties"].get("type", "")).lower() == "user"
            ),
            "business_services_potentially_disrupted": sum(
                1 for entity in removed_entities
                if str(entity["properties"].get("type", "")).lower() == "application"
            ),
            "residual_exposure_percent": residual_percentage,
            "may_be_truncated": (
                before["paths_truncated"] or after["paths_truncated"]
            ),
            "recommendation": (
                "Review this graph-only simulation with an analyst. "
                "No account, network, firewall, or production control was changed."
            ),
        }

    async def compare(
        self,
        scenarios: list[dict[str, Any]],
    ) -> dict[str, Any]:
        results = []
        for scenario in scenarios:
            result = await self.simulate(
                source_entity_id=scenario["source_entity_id"],
                depth=scenario["depth"],
                actions=scenario["actions"],
            )
            results.append({
                "name": scenario["name"],
                **result,
            })
        return {"mode": "SIMULATION_ONLY", "scenarios": results}

    async def recommendations_for_incident(
        self,
        incident_id: str,
    ) -> dict[str, Any] | None:
        rows = await self.database.execute_read(
            queries.INCIDENT_SOURCE_EVENT,
            parameters={"incident_id": incident_id},
        )
        if not rows:
            return None

        incident = rows[0].get("incident") or {}
        event = rows[0].get("event") or {}
        entity_id = event.get("source_entity_id") or event.get("target_entity_id")
        if entity_id is None:
            return {
                "incident_id": incident_id,
                "available": False,
                "recommendations": [],
                "message": "The incident has no related event endpoint to analyze.",
            }

        entity_rows = await self.database.execute_read(
            queries.ENTITY_TYPE_BY_ID,
            parameters={"entity_id": entity_id},
        )
        if not entity_rows:
            return {
                "incident_id": incident_id,
                "available": False,
                "recommendations": [],
                "message": "The related event endpoint is not a persisted graph entity.",
            }

        entity_type = str(entity_rows[0].get("type") or "").lower()
        action = {
            "host": "isolate_entity",
            "user": "disable_account",
            "ipaddress": "block_ip",
            "server": "restrict_server",
        }.get(entity_type)
        recommendations = []
        if action is not None:
            recommendations.append({
                "action": action,
                "target_entity_id": entity_id,
                "reason": (
                    "This action targets the related event endpoint; simulate it "
                    "and review its operational impact before any authorized response."
                ),
                "mode": "SIMULATION_ONLY",
            })

        blast_radius = await self.blast_radius.analyze(
            entity_id,
            depth=min(2, self.blast_radius.max_depth),
        )
        return {
            "incident_id": incident_id,
            "available": True,
            "source_entity_id": entity_id,
            "recommendations": recommendations,
            "blast_radius": blast_radius,
            "mode": "SIMULATION_ONLY",
        }
