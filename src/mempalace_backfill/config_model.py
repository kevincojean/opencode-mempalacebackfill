from typing import TypedDict
from typing_extensions import NotRequired


class MempalaceConfig(TypedDict):
    database_path: str
    wing: str
    command: NotRequired[str]


class BackfillConfig(TypedDict):
    mempalace: MempalaceConfig
    source_dir: str
    patterns: list[str]
    state_file: str


class Config(TypedDict):
    backfill: BackfillConfig
