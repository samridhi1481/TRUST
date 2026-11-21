from fastapi import APIRouter, HTTPException, Query, Request, status

from ..schemas.incident_schema import (
    CreateIncidentRequest,
    IncidentPriority,
    IncidentStatus,
    UpdateIncidentPriorityRequest,
    UpdateIncidentStatusRequest,
)
from ..services.incident_service import IncidentService
from ..utils.response import success

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


def incident_service(request: Request) -> IncidentService:
    return IncidentService(request.app.state.neo4j)


@router.get("")
async def list_incidents(
    request: Request,
    incident_status: IncidentStatus | None = Query(default=None, alias="status"),
    priority: IncidentPriority | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    data = await incident_service(request).list_incidents(
        status=incident_status.value if incident_status else None,
        priority=priority.value if priority else None,
        skip=skip,
        limit=limit,
    )
    return success(data)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_incident(
    body: CreateIncidentRequest,
    request: Request,
) -> dict:
    incident = await incident_service(request).create_incident(
        title=body.title,
        description=body.description,
        event_id=body.event_id,
        priority=body.priority.value,
    )
    return success(incident, "Incident created")


@router.get("/{incident_id}/timeline")
async def incident_timeline(incident_id: str, request: Request) -> dict:
    timeline = await incident_service(request).get_timeline(incident_id)
    return success({"incident_id": incident_id, "timeline": timeline})


@router.patch("/{incident_id}/status")
async def update_incident_status(
    incident_id: str,
    body: UpdateIncidentStatusRequest,
    request: Request,
) -> dict:
    raise HTTPException(
        status_code=503,
        detail="Incident status updates are disabled until authentication and authorization are configured.",
    )


@router.patch("/{incident_id}/priority")
async def update_incident_priority(
    incident_id: str,
    body: UpdateIncidentPriorityRequest,
    request: Request,
) -> dict:
    incident = await incident_service(request).update_priority(
        incident_id=incident_id,
        priority=body.priority.value,
        note=body.note,
    )
    return success(incident, "Incident priority updated")


@router.get("/{incident_id}")
async def get_incident(incident_id: str, request: Request) -> dict:
    incident = await incident_service(request).get_incident(incident_id)
    return success(incident)
