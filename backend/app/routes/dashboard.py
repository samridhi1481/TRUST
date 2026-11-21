from fastapi import APIRouter, Query, Request

from ..services.dashboard_service import DashboardService
from ..utils.response import success

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/overview")
async def dashboard_overview(request: Request) -> dict:
    data = await DashboardService(
        request.app.state.neo4j,
        request.app.state.detection_engine,
    ).get_overview()
    return success(data)


@router.get("/threat-distribution")
async def threat_distribution(request: Request) -> dict:
    data = await DashboardService(
        request.app.state.neo4j,
        request.app.state.detection_engine,
    ).get_threat_distribution()
    return success(data)


@router.get("/recent-activity")
async def recent_activity(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    data = await DashboardService(
        request.app.state.neo4j,
        request.app.state.detection_engine,
    ).get_recent_activity(limit)
    return success(data)
