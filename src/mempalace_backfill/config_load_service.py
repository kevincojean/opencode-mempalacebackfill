import os
from pathlib import Path
from typing import final, Any
from mempalace_backfill.config_model import Config

_DEFAULT_OUTPUT_DIR = str(Path.home() / ".local" / "share" / "com.kevincojean.opencode-mempalacebackfill" / "exports")
_DEFAULT_EXPORT_STATE_FILE = str(Path.home() / ".local" / "share" / "com.kevincojean.opencode-mempalacebackfill" / "export_state.json")
_DEFAULT_SYNC_STATE_DIR = str(Path.home() / ".local" / "share" / "com.kevincojean.opencode-mempalacebackfill" / "sync_state")


@final
class ConfigLoadService:
    def __init__(self):
        self._overrides = {}

    def load_config(self, overrides: dict[str, Any] | None = None) -> Config:
        if overrides:
            self._overrides = self._deep_merge(self._overrides, overrides)
        
        file_config = {}
        config_path = Path.home() / ".config" / "com.kevincojean.opencode-mempalacebackfill" / "config.json"
        if config_path.exists():
            import json
            try:
                with open(config_path, "r") as f:
                    file_config = json.load(f)
            except Exception:
                pass

        default_config: Config = {
            "backfill": {
                "opencode": {
                    "database_path": "~/.local/share/opencode/opencode.db",
                },
                "mempalace": {
                    "wing": "backfill"
                },
                "preclassification": {
                    "enabled": True,
                    "mode": "regex",
                    "markers": ["decision", "milestone", "architecture", "preference", "problem", "emotional"],
                },
                "source_dir": ".",
                "patterns": ["*.log", "*.md"],
                "export_state_file": _DEFAULT_EXPORT_STATE_FILE,
                "sync_state_dir": _DEFAULT_SYNC_STATE_DIR,
                "output_dir": _DEFAULT_OUTPUT_DIR,
            }
        }
        
        config = self._deep_merge(default_config, file_config)
        config = self._deep_merge(config, self._overrides)
        return self._expand_paths(config)

    def _deep_merge(self, base: Any, overrides: dict[str, Any]) -> dict[str, Any]:
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
            if not expanded.startswith(("http://", "https://")):
                expanded = str(Path(expanded).expanduser())
            return expanded
        return config
