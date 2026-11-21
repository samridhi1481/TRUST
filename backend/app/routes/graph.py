from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from ..services.graph_service import GraphService
from ..utils.response import success

router = APIRouter(prefix="/api/graph", tags=["graph"])


def graph_service(request: Request) -> GraphService:
    return GraphService(
        request.app.state.neo4j,
        request.app.state.settings.max_graph_depth,
    )


@router.get("/overview")
async def graph_overview(request: Request) -> dict:
    return success(await graph_service(request).get_overview())


@router.get("/entities")
async def graph_entities(
    request: Request,
    entity_type: str | None = Query(default=None, max_length=64),
    risk_level: Literal["low", "medium", "high", "critical"] | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    data = await graph_service(request).get_entities(
        entity_type=entity_type,
        risk_level=risk_level,
        skip=skip,
        limit=limit,
    )
    return success(data)


@router.get("/entity/{entity_id}")
async def graph_entity(entity_id: str, request: Request) -> dict:
    entity = await graph_service(request).get_entity(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Graph entity not found.")
    return success(entity)


@router.get("/neighbors/{entity_id}")
async def graph_neighbors(entity_id: str, request: Request) -> dict:
    neighbors = await graph_service(request).get_neighbors(entity_id)
    if neighbors is None:
        raise HTTPException(status_code=404, detail="Graph entity not found.")
    return success(neighbors)


@router.get("/relationships/{entity_id}")
async def graph_relationships(entity_id: str, request: Request) -> dict:
    relationships = await graph_service(request).get_relationships(entity_id)
    if relationships is None:
        raise HTTPException(status_code=404, detail="Graph entity not found.")
    return success(relationships)


@router.get("/subgraph/{entity_id}")
async def graph_subgraph(
    entity_id: str,
    request: Request,
    depth: int = Query(default=2, ge=1, le=6),
    limit: int = Query(default=100, ge=1, le=200),
) -> dict:
    service = graph_service(request)
    if depth > service.max_depth:
        raise HTTPException(
            status_code=422,
            detail=f"Depth cannot exceed the configured maximum of {service.max_depth}.",
        )
    subgraph = await service.get_subgraph(entity_id, depth, limit)
    if subgraph is None:
        raise HTTPException(status_code=404, detail="Graph entity not found.")
    return success(subgraph)
