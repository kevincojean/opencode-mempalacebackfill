import os
from pathlib import Path
from typing import final, Any
from mempalace_backfill.config_model import Config

_DEFAULT_OUTPUT_DIR = str(Path.home() / ".local" / "share" / "com.kevincojean.opencode-mempalacebackfill" / "exports")
_DEFAULT_STATE_FILE = str(Path.home() / ".local" / "share" / "com.kevincojean.opencode-mempalacebackfill" / "state.json")


@final
class ConfigLoadService:
    def __init__(self):
        self._overrides = {}

    def load_config(self, overrides: dict[str, Any] = None) -> Config:
        if overrides:
            self._overrides = self._deep_merge(self._overrides, overrides)
        
        default_config: Config = {
            "backfill": {
                "opencode": {
                    "database_path": "~/.local/share/opencode/opencode.db",
                },
                "mempalace": {
                    "wing": "backfill"
                },
                "source_dir": ".",
                "patterns": ["*.log", "*.md"],
                "state_file": _DEFAULT_STATE_FILE,
                "output_dir": _DEFAULT_OUTPUT_DIR,
            }
        }
        
        config = self._deep_merge(default_config, self._overrides)
        return self._expand_paths(config)

    def _deep_merge(self, base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
        result = base.copy()
        for key, value in overrides.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def _expand_paths(self, config: Any) -> Any:
        if isinstance(config, dict):
            return {k: self._expand_paths(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [self._expand_paths(v) for v in config]
        elif isinstance(config, str):
            expanded = os.path.expandvars(config)
            expanded = str(Path(expanded).expanduser())
            return expanded
        return config
