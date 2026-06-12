from dataclasses import dataclass
from datetime import datetime
from typing import final

@final
@dataclass(frozen=True)
class Session:
    id: str
    subject: str
    created_at: datetime
    message_count: int

@final
@dataclass(frozen=True)
class Message:
    session_id: str
    role: str
    content: str
    timestamp: datetime
