from pydantic import BaseModel, Field


class BlastRadiusRequest(BaseModel):
    entity_id: str = Field(min_length=1, max_length=200)
    depth: int = Field(default=2, ge=1, le=6)
