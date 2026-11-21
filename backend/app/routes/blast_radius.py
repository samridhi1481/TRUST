from fastapi import APIRouter, HTTPException, Query, Request

from ..schemas.blast_radius_schema import BlastRadiusRequest
from ..services.blast_radius_service import BlastRadiusService
from ..utils.response import success

router = APIRouter(prefix="/api/blast-radius", tags=["blast-radius"])


def blast_radius_service(request: Request) -> BlastRadiusService:
    return BlastRadiusService(
        request.app.state.neo4j,
        request.app.state.settings.max_graph_depth,
    )


@router.get("/{entity_id}")
async def get_blast_radius(
    entity_id: str,
    request: Request,
    depth: int = Query(default=2, ge=1, le=6),
) -> dict:
    service = blast_radius_service(request)
    if depth > service.max_depth:
        raise HTTPException(
            status_code=422,
            detail=f"Depth cannot exceed the configured maximum of {service.max_depth}.",
        )
    result = await service.analyze(entity_id, depth)
    if result is None:
        raise HTTPException(status_code=404, detail="Graph entity not found.")
    return success(result)


@router.post("/analyze")
async def analyze_blast_radius(
    body: BlastRadiusRequest,
    request: Request,
) -> dict:
    service = blast_radius_service(request)
    if body.depth > service.max_depth:
        raise HTTPException(
            status_code=422,
            detail=f"Depth cannot exceed the configured maximum of {service.max_depth}.",
        )
    result = await service.analyze(body.entity_id, body.depth)
    if result is None:
        raise HTTPException(status_code=404, detail="Graph entity not found.")
    return success(result)
