from typing import Literal
from uuid import UUID, uuid4
from .models import CreateRecord, Record, now
from .tracking import TrackingService, entity


class CreateTask(CreateRecord):
    kind: Literal['task'] = 'task'
    goal_id: UUID | None = None


def register_tasks(app, store):
    @app.post('/api/tasks')
    def create_task(request: CreateTask):
        return create_task_with_tracking(store, request)


def create_task_with_tracking(store, request: CreateTask):
    def prepare():
        goal_id = str(request.goal_id) if request.goal_id else None
        if goal_id:
            TrackingService(store).get(goal_id, 'goal')
        record = Record(**request.model_dump(exclude={'request_id', 'goal_id'}), id=uuid4(),
                        version=1, created_at=now(), updated_at=now())
        tracking = entity('tracking', {'task_id': str(record.id), 'goal_id': goal_id,
                                      'tags': [], 'progress': None}, 'tracking:' + str(record.id))
        return [record], [], {'record': record.model_dump(mode='json')}, [tracking]
    return store.transaction(request.request_id, 'create-task', request.model_dump(mode='json'), prepare, extension=True)
