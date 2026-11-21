from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    database_health = await request.app.state.neo4j.health()
    status = database_health["status"]
    response = {
        "status": "healthy" if status == "healthy" else "degraded",
        "database": database_health,
    }
    return JSONResponse(
        content=response,
        status_code=200 if status == "healthy" else 503,
    )
