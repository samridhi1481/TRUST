from enum import Enum

from pydantic import BaseModel, Field


class IncidentStatus(str, Enum):
    NEW = "NEW"
    INVESTIGATING = "INVESTIGATING"
    CONFIRMED = "CONFIRMED"
    CONTAINMENT_RECOMMENDED = "CONTAINMENT_RECOMMENDED"
    CONTAINED = "CONTAINED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class IncidentPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CreateIncidentRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    event_id: str | None = Field(default=None, min_length=1, max_length=200)
    priority: IncidentPriority


class UpdateIncidentStatusRequest(BaseModel):
    status: IncidentStatus
    note: str | None = Field(default=None, max_length=2_000)


class UpdateIncidentPriorityRequest(BaseModel):
    priority: IncidentPriority
    note: str | None = Field(default=None, max_length=2_000)
