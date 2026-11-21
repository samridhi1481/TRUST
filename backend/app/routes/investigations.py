from fastapi import APIRouter, HTTPException, Query, Request, status

from ..schemas.investigation_schema import (
    AddInvestigationEvidenceRequest,
    AddInvestigationNoteRequest,
    CreateInvestigationRequest,
    InvestigationStatus,
    UpdateInvestigationStatusRequest,
)
from ..services.investigation_service import InvestigationService
from ..utils.response import success

router = APIRouter(prefix="/api/investigations", tags=["investigations"])


def investigation_service(request: Request) -> InvestigationService:
    return InvestigationService(request.app.state.neo4j)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_investigation(
    body: CreateInvestigationRequest,
    request: Request,
) -> dict:
    investigation = await investigation_service(request).create_investigation(
        title=body.title,
        alert_id=body.alert_id,
        entity_ids=body.entity_ids,
    )
    return success(investigation, "Investigation created")


@router.get("")
async def list_investigations(
    request: Request,
    investigation_status: InvestigationStatus | None = Query(default=None, alias="status"),
    alert_id: str | None = Query(default=None, max_length=200),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    data = await investigation_service(request).list_investigations(
        status=investigation_status.value if investigation_status else None,
        alert_id=alert_id,
        skip=skip,
        limit=limit,
    )
    return success(data)


@router.post("/{investigation_id}/notes")
async def add_investigation_note(
    investigation_id: str,
    body: AddInvestigationNoteRequest,
    request: Request,
) -> dict:
    investigation = await investigation_service(request).add_note(
        investigation_id,
        body.content,
    )
    return success(investigation, "Investigation note added")


@router.post("/{investigation_id}/evidence")
async def attach_investigation_evidence(
    investigation_id: str,
    body: AddInvestigationEvidenceRequest,
    request: Request,
) -> dict:
    investigation = await investigation_service(request).add_evidence(
        investigation_id,
        body.evidence_id,
    )
    return success(investigation, "Evidence attached to investigation")


@router.get("/{investigation_id}/evidence")
async def get_investigation_evidence(
    investigation_id: str,
    request: Request,
) -> dict:
    evidence = await investigation_service(request).get_evidence(investigation_id)
    return success({"evidence": evidence})


@router.patch("/{investigation_id}/status")
async def update_investigation_status(
    investigation_id: str,
    body: UpdateInvestigationStatusRequest,
    request: Request,
) -> dict:
    investigation = await investigation_service(request).update_status(
        investigation_id,
        body.status.value,
        body.note,
    )
    return success(investigation, "Investigation status updated")


@router.get("/{investigation_id}/timeline")
async def get_investigation_timeline(
    investigation_id: str,
    request: Request,
) -> dict:
    timeline = await investigation_service(request).get_timeline(investigation_id)
    return success({"investigation_id": investigation_id, "timeline": timeline})


@router.get("/{investigation_id}")
async def get_investigation(investigation_id: str, request: Request) -> dict:
    investigation = await investigation_service(request).get_investigation(investigation_id)
    return success(investigation)
