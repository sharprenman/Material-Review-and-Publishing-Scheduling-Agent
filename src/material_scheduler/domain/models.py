"""Validated public business contracts; all times normalize to Shanghai."""

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScheduleRequest(Contract):
    request_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    material_id: str = Field(min_length=1, max_length=80)
    channel: str = Field(min_length=1, max_length=80)
    account: str = Field(min_length=1, max_length=80)
    requested_time: datetime

    @field_validator("requested_time")
    @classmethod
    def local_hour(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        value = value.astimezone(ZoneInfo("Asia/Shanghai"))
        if value.minute or value.second or value.microsecond:
            raise ValueError("必须使用整点")
        return value


class Material(Contract):
    material_id: str
    title: str | None = None
    rights: bool | None = None
    tags: list[str] = Field(default_factory=list)


class Rule(Contract):
    rule_id: str
    blocked_tag: str
    reason: str


class ReviewResult(Contract):
    status: Literal["passed", "missing", "blocked"]
    missing: list[str] = Field(default_factory=list)
    risks: list[dict[str, str]] = Field(default_factory=list)


class SlotOption(Contract):
    time: str
    available: bool


class ScheduleProposal(Contract):
    proposal_id: str
    version: int
    time: str
    confirmation: Literal["pending", "accepted", "rejected"] = "pending"


class Confirmation(Contract):
    proposal_id: str
    version: int = Field(ge=1)
    accept: bool


class Draft(Contract):
    draft_id: str
    request_id: str
    material_id: str
    channel: str
    account: str
    time: str


class RunResult(Contract):
    request_id: str
    run_id: str
    thread_id: str
    mode: str
    execution: str
    requested_time: str
    review: dict | None
    proposal: dict | None
    save_status: str
    draft: dict | None
    error: str | None
    model_calls: int
    tool_calls: int
