from enum import Enum

from pydantic import BaseModel, Field


class ContainmentActionType(str, Enum):
    ISOLATE_ENTITY = "isolate_entity"
    DISABLE_ACCOUNT = "disable_account"
    BLOCK_IP = "block_ip"
    RESTRICT_SERVER = "restrict_server"


class ContainmentAction(BaseModel):
    action: ContainmentActionType
    target_entity_id: str = Field(min_length=1, max_length=200)


class ContainmentSimulationRequest(BaseModel):
    source_entity_id: str = Field(min_length=1, max_length=200)
    depth: int = Field(default=2, ge=1, le=6)
    actions: list[ContainmentAction] = Field(min_length=1, max_length=10)


class ContainmentScenario(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    source_entity_id: str = Field(min_length=1, max_length=200)
    depth: int = Field(default=2, ge=1, le=6)
    actions: list[ContainmentAction] = Field(min_length=1, max_length=10)


class ContainmentCompareRequest(BaseModel):
    scenarios: list[ContainmentScenario] = Field(min_length=1, max_length=5)
