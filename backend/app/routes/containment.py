from fastapi import APIRouter, HTTPException, Request

from ..schemas.containment_schema import (
    ContainmentCompareRequest,
    ContainmentSimulationRequest,
)
from ..services.containment_service import ContainmentService
from ..utils.response import success

router = APIRouter(prefix="/api/containment", tags=["containment"])


def containment_service(request: Request) -> ContainmentService:
    return ContainmentService(
        request.app.state.neo4j,
        request.app.state.settings.max_graph_depth,
    )


@router.post("/simulate")
async def simulate_containment(
    body: ContainmentSimulationRequest,
    request: Request,
) -> dict:
    service = containment_service(request)
    if body.depth > service.blast_radius.max_depth:
        raise HTTPException(
            status_code=422,
            detail=(
                "Depth cannot exceed the configured maximum of "
                f"{service.blast_radius.max_depth}."
            ),
        )
    result = await service.simulate(
        source_entity_id=body.source_entity_id,
        depth=body.depth,
        actions=body.actions,
    )
    return success(result)


@router.post("/compare")
async def compare_containment(
    body: ContainmentCompareRequest,
    request: Request,
) -> dict:
    service = containment_service(request)
    if any(scenario.depth > service.blast_radius.max_depth for scenario in body.scenarios):
        raise HTTPException(
            status_code=422,
            detail=(
                "Scenario depth cannot exceed the configured maximum of "
                f"{service.blast_radius.max_depth}."
            ),
        )
    scenarios = [
        {
            "name": scenario.name,
            "source_entity_id": scenario.source_entity_id,
            "depth": scenario.depth,
            "actions": scenario.actions,
        }
        for scenario in body.scenarios
    ]
    return success(await service.compare(scenarios))


@router.get("/recommendations/{incident_id}")
async def containment_recommendations(
    incident_id: str,
    request: Request,
) -> dict:
    recommendations = await containment_service(request).recommendations_for_incident(
        incident_id
    )
    if recommendations is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return success(recommendations)
