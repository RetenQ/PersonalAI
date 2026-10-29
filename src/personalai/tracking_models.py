"""Version 2 types. Version 1 models remain frozen for byte-exact replay."""
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from .models import StrictModel, Event
from .scheduled_models import Schedule, ScheduledRun

MODULES = ['profile', 'state', 'year', 'goals', 'logs', 'other', 'checkins', 'pending']


class Milestone(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    weight: float = Field(default=1, gt=0, allow_inf_nan=False)
    progress: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)


class Goal(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    criteria: str = Field(min_length=1, max_length=3000)
    due: date | None = None
    mode: Literal['metric', 'milestones'] = 'metric'
    unit: str = Field(default='', max_length=50)
    baseline: float | None = Field(default=None, allow_inf_nan=False)
    target: float | None = Field(default=None, allow_inf_nan=False)
    current: float | None = Field(default=None, allow_inf_nan=False)
    milestones: list[Milestone] = Field(default_factory=list, max_length=50)

    @model_validator(mode='after')
    def valid(self):
        if self.mode == 'metric' and self.target is not None and self.baseline == self.target:
            raise ValueError('起点与目标值不能相同')
        if self.mode == 'milestones' and not self.milestones:
            raise ValueError('请添加里程碑')
        return self


class Tracking(StrictModel):
    task_id: UUID
    goal_id: UUID | None = None
    tags: list[str] = Field(default_factory=list, max_length=30)
    progress: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)


class Activity(StrictModel):
    date: date
    slot: Literal['morning', 'noon', 'evening'] | None = None
    task_id: UUID | None = None
    goal_id: UUID | None = None
    text: str = Field(min_length=1, max_length=10000)
    result: str = Field(default='', max_length=3000)
    obstacle: str = Field(default='', max_length=3000)
    completed: bool = False


class CheckIn(StrictModel):
    date: date
    slot: Literal['morning', 'noon', 'evening']
    goal_id: UUID | None = None
    response: str = Field(min_length=1, max_length=10000)
    obstacle: str = Field(default='', max_length=3000)


class CurrentState(StrictModel):
    """Historical v2 replay only. Active current-state writes are retired."""
    date: date
    energy: str = Field(default='', max_length=200)
    mood: str = Field(default='', max_length=200)
    obstacle: str = Field(default='', max_length=3000)
    note: str = Field(default='', max_length=3000)


class TaskType(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=80)
    active: bool = True


class Profile(StrictModel):
    """Explicit self-description, independent of settings and inferred analyses."""
    personality: str = Field(default='', max_length=6000)
    values: str = Field(default='', max_length=6000)
    preferences: str = Field(default='', max_length=6000)
    boundaries: str = Field(default='', max_length=6000)


class ModelConfig(StrictModel):
    enabled: bool = False
    base_url: str = ''
    model: str = Field(default='', max_length=200)
    response_format: Literal['json_schema', 'json_object'] = 'json_schema'

    @model_validator(mode='after')
    def safe_endpoint(self):
        if self.base_url:
            url = urlsplit(self.base_url)
            _ = url.port  # Validate malformed and out-of-range port numbers before saving.
            if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or any(c.isspace() for c in self.base_url):
                raise ValueError('云端接口必须使用不含凭据或查询参数的 HTTPS 地址')
        if self.enabled and (not self.base_url or not self.model.strip()):
            raise ValueError('启用前请填写模型和服务地址')
        return self


class Settings(StrictModel):
    name: str = Field(default='', max_length=100)
    bio: str = Field(default='', max_length=3000)
    focus: str = Field(default='', max_length=3000)
    order: list[str] = Field(default_factory=lambda: MODULES.copy())
    hidden: list[str] = Field(default_factory=list)
    task_types: list[TaskType] = Field(default_factory=list, max_length=100)
    model: ModelConfig = Field(default_factory=ModelConfig)

    @model_validator(mode='after')
    def unique_modules(self):
        if len(self.order) != len(MODULES) or set(self.order) != set(MODULES):
            raise ValueError('模块顺序必须包含每个模块一次')
        if not set(self.hidden) <= set(MODULES):
            raise ValueError('未知模块')
        if len({t.id for t in self.task_types}) != len(self.task_types):
            raise ValueError('类型编号重复')
        return self


class Contribution(StrictModel):
    task_id: str
    relevance: Literal['direct', 'supporting', 'insufficient']
    reason: str = Field(min_length=1, max_length=3000)
    source_ids: list[str]


class Assessment(StrictModel):
    low: float | None = Field(ge=0, le=100, allow_inf_nan=False)
    high: float | None = Field(ge=0, le=100, allow_inf_nan=False)
    confidence: Literal['low', 'medium', 'high', 'insufficient']
    explanation: str = Field(min_length=1, max_length=6000)
    source_ids: list[str]
    contributions: list[Contribution]
    missing: list[str]
    suggestions: list[str]

    @model_validator(mode='after')
    def interval(self):
        if (self.low is None) != (self.high is None):
            raise ValueError('估计区间不完整')
        if self.low is not None and (self.low > self.high or not self.source_ids or self.confidence == 'insufficient'):
            raise ValueError('无依据或无效的估计')
        return self


class Analysis(StrictModel):
    goal_id: UUID
    model: str
    base_url: str
    sources: dict[str, int]
    assessment: Assessment


class Suggestion(StrictModel):
    analysis_id: UUID
    goal_id: UUID
    text: str = Field(min_length=1, max_length=3000)
    status: Literal['pending', 'accepted', 'rejected'] = 'pending'


class Change(StrictModel):
    target_id: str
    target_kind: Literal['goal', 'tracking', 'log', 'checkin', 'state', 'settings', 'profile']
    expected_version: int = Field(ge=0)
    before: dict | None
    after: dict
    reason: str = Field(min_length=1, max_length=1000)
    status: Literal['pending', 'accepted', 'rejected'] = 'pending'


KINDS = {'goal': Goal, 'tracking': Tracking, 'log': Activity, 'checkin': CheckIn, 'profile': Profile,
         'schedule': Schedule, 'scheduled_run': ScheduledRun,
         'state': CurrentState, 'settings': Settings, 'analysis': Analysis, 'change': Change, 'suggestion': Suggestion}


class Entity(StrictModel):
    id: str
    kind: Literal['goal', 'tracking', 'log', 'checkin', 'state', 'settings', 'profile', 'analysis', 'change', 'suggestion', 'schedule', 'scheduled_run']
    version: int = Field(ge=1)
    created_at: str
    updated_at: str
    data: dict

    @model_validator(mode='after')
    def validate_data(self):
        self.data = KINDS[self.kind].model_validate(self.data).model_dump(mode='json')
        return self


class EventV2(Event):
    schema_version: Literal[2] = 2
    entities: list[Entity] = Field(default_factory=list)


class WriteEntity(StrictModel):
    request_id: UUID
    data: dict
    expected_version: int = Field(default=0, ge=0)
    reason: str = Field(default='更新记录', min_length=1, max_length=1000)
    progress_update: Tracking | None = None
    tracking_expected_version: int = Field(default=0, ge=0)


def goal_progress(data: dict) -> float | None:
    goal = Goal.model_validate(data)
    if goal.mode == 'metric':
        if any(v is None for v in [goal.baseline, goal.target, goal.current]):
            return None
        baseline, target, current = (Decimal(str(v)) for v in (goal.baseline, goal.target, goal.current))
        return round(float(max(Decimal(0), min(Decimal(100), (current - baseline) / (target - baseline) * 100))), 1)
    if any(m.progress is None for m in goal.milestones):
        return None
    weighted = sum(Decimal(str(m.weight)) * Decimal(str(m.progress)) for m in goal.milestones)
    return round(float(weighted / sum(Decimal(str(m.weight)) for m in goal.milestones)), 1)


def year_time(day: date):
    start, end = date(day.year, 1, 1), date(day.year + 1, 1, 1)
    return {'year': day.year, 'remaining_days': (end - day).days,
            'elapsed_percent': round((day - start).days / (end - start).days * 100, 1), 'includes_today': True}
