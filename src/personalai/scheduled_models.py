"""Independent schedule/report entities; existing event payloads stay unchanged."""
import re
from typing import Literal

from pydantic import Field, model_validator

from .models import StrictModel

# Frozen event scope, including retired historical input; active requests use ActiveScheduleOptions.
Scope = Literal['records', 'goals', 'tasks', 'logs', 'checkins', 'states']
SCOPE_NAMES = {'records': '日常原文', 'goals': '目标及完成标准', 'tasks': '任务及追踪',
               'logs': '活动日志', 'checkins': '早中晚回应', 'states': '当前状态'}
SECTION_NAMES = {'facts': '记录中的事实', 'reflection': '进展分析', 'issues': '问题与阻碍',
                 'suggestions': '改善建议', 'next_steps': '下一步参考', 'long_term': '与长期目标的关系'}


class ScheduleOptions(StrictModel):
    enabled: bool = False
    times: list[str] = Field(default_factory=list, max_length=24)
    scopes: list[Scope] = Field(default_factory=list)

    @model_validator(mode='after')
    def valid(self):
        if any(not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', t) for t in self.times):
            raise ValueError('时间必须为 HH:MM')
        if len(set(self.times)) != len(self.times) or len(set(self.scopes)) != len(self.scopes):
            raise ValueError('时刻与资料类型不能重复')
        if self.enabled and (not self.times or not self.scopes):
            raise ValueError('启用前请选择时刻与数据范围')
        self.times = sorted(self.times)
        return self


class Schedule(ScheduleOptions):
    model_fingerprint: str = ''
    effective_from: str = ''


class CitedText(StrictModel):
    text: str = Field(min_length=1, max_length=3000)
    source_ids: list[str] = Field(min_length=1, max_length=100)


class DailyAssessment(StrictModel):
    facts: list[CitedText] = Field(max_length=20)
    reflection: list[CitedText] = Field(max_length=10)
    issues: list[CitedText] = Field(max_length=10)
    suggestions: list[CitedText] = Field(max_length=10)
    next_steps: list[CitedText] = Field(max_length=10)
    long_term: list[CitedText] = Field(max_length=10)
    missing: list[str] = Field(max_length=30)


class ScheduledRun(StrictModel):
    scheduled_at: str
    started_at: str
    finished_at: str | None = None
    schedule_version: int
    trigger: Literal['scheduled', 'manual']
    status: Literal['running', 'succeeded', 'failed', 'skipped', 'interrupted']
    message: str = ''
    window_start: str
    window_end: str
    sampled_at: str
    model: str
    base_url: str
    sources: dict[str, int]
    source_labels: dict[str, str]
    source_kinds: dict[str, str]
    input_hash: str
    assessment: DailyAssessment | None = None


def report_markdown(identifier, data):
    lines = [f'# 定时综合分析 · {data["window_end"]}', '',
             f'- 报告编号：{identifier}', f'- 状态：{data["status"]}',
             f'- 计划时刻：{data["scheduled_at"]}', f'- 实际开始：{data["started_at"]}',
             f'- 完成时间：{data["finished_at"] or "尚未完成"}',
             f'- 资料范围：{data["window_start"]} 至 {data["window_end"]}（含首尾，Asia/Shanghai）',
             f'- 模型：{data["model"]}', '',
             '当天为主，近七个自然日作背景。目标与任务是取样时快照；AI 建议不自动改变正式计划。', '', data['message'], '']
    if data['assessment']:
        for key, label in SECTION_NAMES.items():
            lines += ['## ' + label, '']
            lines += [f'- {x["text"]}\n  - 依据：' + '、'.join(x['source_ids']) for x in data['assessment'][key]] or ['证据不足，未给出结论。']
            lines += ['']
        lines += ['## 缺失信息', '', *['- ' + x for x in data['assessment']['missing']], '']
    lines += ['## 依据版本', '', *[f'- {data["source_labels"].get(k, k)} · {k} · v{v}' for k, v in data['sources'].items()], '']
    return '\n'.join(lines)
