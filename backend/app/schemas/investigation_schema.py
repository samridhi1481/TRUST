from enum import Enum

from pydantic import BaseModel, Field


class InvestigationStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"


class CreateInvestigationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    alert_id: str | None = Field(default=None, min_length=1, max_length=200)
    entity_ids: list[str] = Field(default_factory=list, max_length=50)


class AddInvestigationNoteRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)


class AddInvestigationEvidenceRequest(BaseModel):
    evidence_id: str = Field(min_length=1, max_length=200)


class UpdateInvestigationStatusRequest(BaseModel):
    status: InvestigationStatus
    note: str | None = Field(default=None, max_length=2_000)
