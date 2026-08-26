from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from arbiter.models import utcnow


class SystemEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: str
    resource_type: str
    resource_id: str
    action: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
