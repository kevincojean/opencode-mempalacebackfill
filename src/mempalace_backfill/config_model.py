from typing import TypedDict, Literal
from typing_extensions import NotRequired


class PreclassificationConfig(TypedDict):
    enabled: bool
    mode: str
    markers: list[str]
    custom_patterns: NotRequired[dict[str, list[str]]]


class OpenCodeConfig(TypedDict):
    database_path: str


class MempalaceConfig(TypedDict):
    palace_path: NotRequired[str]
    wing: str
    command: NotRequired[str]
    backend: NotRequired[Literal["chroma", "qdrant"]]


class BackfillConfig(TypedDict):
    opencode: OpenCodeConfig
    mempalace: MempalaceConfig
    preclassification: PreclassificationConfig
    source_dir: str
    patterns: list[str]
    export_state_file: str
    sync_state_dir: NotRequired[str]
    output_dir: NotRequired[str]


class Config(TypedDict):
    backfill: BackfillConfig
