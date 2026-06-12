from typing import TypedDict, Optional
from datetime import datetime

class SessionFilters(TypedDict, total=False):
    project_id: Optional[str]
    since: Optional[datetime]
    until: Optional[datetime]
    max_sessions: Optional[int]
    exclude_title: Optional[str]
    min_messages: Optional[int]
    limit: int
    offset: int
    db_path: Optional[str]
