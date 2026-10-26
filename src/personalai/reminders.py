"""Versioned reminder rules and a deterministic thirty-day occurrence window."""
from datetime import date, datetime, timedelta
from typing import Literal
from uuid import NAMESPACE_URL, uuid5
from pydantic import Field, model_validator
from .models import StrictModel, TZ
from .store import StoreError


class Reminder(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    start_date: date
    time: str = Field(pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    repeat: Literal['once', 'daily', 'weekly'] = 'once'
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    end_date: date | None = None
    timezone: Literal['Asia/Shanghai'] = 'Asia/Shanghai'
    task_id: str | None = None
    checkin_slot: Literal['morning', 'noon', 'evening'] | None = None
    enabled: bool = True

    @model_validator(mode='after')
    def valid(self):
        if any(d not in range(7) for d in self.weekdays) or len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError('Invalid weekdays')
        if self.repeat == 'weekly' and not self.weekdays:
            raise ValueError('Weekly reminders require weekdays')
        if self.end_date and self.end_date < self.start_date:
            raise ValueError('Invalid reminder date range')
        return self


def validate_reminder(store, value):
    rule = Reminder.model_validate(value)
    if rule.task_id and store.get(rule.task_id).kind != 'task':
        raise StoreError('提醒只能关联正式任务。', 422)
    return rule.model_dump(mode='json')


def occurrences(store, at=None):
    at = (at or datetime.now(TZ)).astimezone(TZ)
    result = []
    for entity in store.entities.values():
        if entity.kind != 'core/reminder':
            continue
        rule = Reminder.model_validate(entity.data)
        if not rule.enabled:
            continue
        for offset in range(30):
            day = at.date() + timedelta(days=offset)
            if day < rule.start_date or rule.end_date and day > rule.end_date:
                continue
            if rule.repeat == 'once' and day != rule.start_date or rule.repeat == 'weekly' and day.weekday() not in rule.weekdays:
                continue
            hour, minute = map(int, rule.time.split(':'))
            due = datetime.combine(day, datetime.min.time(), TZ).replace(hour=hour, minute=minute)
            if due < at:
                continue
            identifier = str(uuid5(NAMESPACE_URL, f'{entity.id}:{entity.version}:{due.isoformat()}'))
            result.append({'id': identifier, 'rule_id': entity.id, 'rule_version': entity.version,
                           'title': rule.title, 'due_at': due.isoformat(), 'task_id': rule.task_id,
                           'checkin_slot': rule.checkin_slot})
    return sorted(result, key=lambda e: (e['due_at'], e['id']))
