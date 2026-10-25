"""Version 3 envelopes preserve unknown plugin data without executing plugin code."""
from typing import Literal
from uuid import uuid4
from pydantic import Field
from .models import Event, StrictModel, now
from .tracking_models import Entity

class PluginEntity(StrictModel):
    id: str
    kind: str = Field(pattern=r"^[a-z][a-z0-9_-]*/[a-z][a-z0-9_.-]*$")
    version: int = Field(ge=1)
    created_at: str
    updated_at: str
    data: dict
    readable: str = ''

class EventV3(Event):
    schema_version: Literal[3] = 3
    entities: list[Entity | PluginEntity] = Field(default_factory=list)

def extension(kind, data, identifier=None, before=None, readable=''):
    return PluginEntity(id=identifier or str(uuid4()), kind=kind, data=data,
        version=before.version + 1 if before else 1,
        created_at=before.created_at if before else now(), updated_at=now(), readable=readable)
