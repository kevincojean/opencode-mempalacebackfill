from typing import TypedDict
from typing_extensions import NotRequired


class OpenCodeConfig(TypedDict):
    database_path: str


class MempalaceConfig(TypedDict):
    palace_path: NotRequired[str]
    wing: str
    command: NotRequired[str]


class BackfillConfig(TypedDict):
    opencode: OpenCodeConfig
    mempalace: MempalaceConfig
    source_dir: str
    patterns: list[str]
    state_file: str
    output_dir: NotRequired[str]


class Config(TypedDict):
    backfill: BackfillConfig
