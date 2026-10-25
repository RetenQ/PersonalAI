"""Model contracts only: no provider SDK, key loading or network calls."""
from typing import Literal, Protocol

from pydantic import Field

from .models import RecordFields, StrictModel


class ExtractedItem(RecordFields):
    intent: Literal["fact", "possible_task", "possible_idea"]
    evidence: str = Field(min_length=1)


class Understanding(StrictModel):
    items: list[ExtractedItem]
    uncertainties: list[str] = Field(default_factory=list)


class GeneratedReport(StrictModel):
    facts: list[str]
    evaluation: str
    issues: list[str]
    suggestions: list[str]
    next_day_reference: str
    long_term_relation: str
    source_ids: list[str]


class ModelUnavailable(Exception):
    pass


class ModelGateway(Protocol):
    def understand(self, text: str) -> Understanding: ...
    def generate_report(self, approved_records: list[dict]) -> GeneratedReport: ...


class UnconfiguredModel:
    def understand(self, text: str) -> Understanding:
        raise ModelUnavailable("模型尚未配置；原文可本地保存，尚未进行 AI 理解。")

    def generate_report(self, approved_records: list[dict]) -> GeneratedReport:
        raise ModelUnavailable("模型尚未配置；仅支持本地事实汇总。")
