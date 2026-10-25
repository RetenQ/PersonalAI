from datetime import date, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

TZ = ZoneInfo("Asia/Shanghai")
CATEGORIES = {
    "uncategorized": "未分类", "exercise": "运动", "plan": "计划任务",
    "effort": "工作学习投入", "progress": "具体工作进展", "rest": "娱乐与休息",
    "sleep": "睡眠与精神", "body": "身体指标", "mood": "疲劳与情绪",
    "skill": "技能实践", "diet": "饮食",
}
Category = Literal["uncategorized", "exercise", "plan", "effort", "progress", "rest", "sleep", "body", "mood", "skill", "diet"]


def now() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecordFields(StrictModel):
    text: str = Field(min_length=1, max_length=10000)
    date: date
    category: Category = "uncategorized"
    status: Literal["open", "partial", "done"] = "open"

    @field_validator("text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("内容不能为空")
        return value


class CreateRecord(RecordFields):
    request_id: UUID
    kind: Literal["note", "task", "idea"] = "note"


class Record(RecordFields):
    id: UUID
    kind: Literal["note", "task", "idea"]
    version: int = Field(ge=1)
    created_at: str
    updated_at: str
    source: Literal["user_input", "confirmed_suggestion"] = "user_input"
    processing: Literal["not_analyzed"] = "not_analyzed"
    previous_version: int | None = None


class ProposeRevision(RecordFields):
    request_id: UUID
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class Proposal(StrictModel):
    id: UUID
    action: Literal["revise", "create_task", "create_idea"]
    status: Literal["pending", "accepted", "rejected"] = "pending"
    target_id: UUID | None = None
    expected_version: int | None = None
    before: Record | None = None
    after: RecordFields
    reason: str
    created_at: str
    decided_at: str | None = None
    result_id: UUID | None = None


class Decision(StrictModel):
    request_id: UUID
    decision: Literal["accept", "reject"]


class Event(StrictModel):
    schema_version: Literal[1] = 1
    sequence: int = Field(ge=1)
    request_id: UUID
    fingerprint: str
    timestamp: str
    previous_hash: str | None
    records: list[Record] = Field(default_factory=list)
    proposals: list[Proposal] = Field(default_factory=list)
    result: dict

