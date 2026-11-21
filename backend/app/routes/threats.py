from fastapi import APIRouter, HTTPException, Query, Request

from ..services.threat_service import ThreatService
from ..utils.response import success

router = APIRouter(prefix="/api/threats", tags=["threats"])


def threat_service(request: Request) -> ThreatService:
    return ThreatService(
        request.app.state.neo4j,
        request.app.state.detection_engine,
    )


@router.get("/high-risk")
async def high_risk_threats(
    request: Request,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=20),
) -> dict:
    data = await threat_service(request).list_threats(
        skip=skip,
        limit=limit,
        high_risk_only=True,
    )
    return success(data)


@router.get("/associated-entities/{threat_id}")
async def threat_associated_entities(threat_id: str, request: Request) -> dict:
    entities = await threat_service(request).get_associated_entities(threat_id)
    if entities is None:
        raise HTTPException(status_code=404, detail="Threat not found.")
    return success({"entities": entities})


@router.get("/evidence/{threat_id}")
async def threat_evidence(threat_id: str, request: Request) -> dict:
    evidence = await threat_service(request).get_evidence(threat_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail="Threat not found.")
    return success({"evidence": evidence})


@router.get("")
async def list_threats(
    request: Request,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=20),
) -> dict:
    data = await threat_service(request).list_threats(skip=skip, limit=limit)
    return success(data)


@router.get("/{threat_id}")
async def threat_detail(threat_id: str, request: Request) -> dict:
    threat = await threat_service(request).get_threat(threat_id)
    if threat is None:
        raise HTTPException(status_code=404, detail="Threat not found.")
    return success(threat)
