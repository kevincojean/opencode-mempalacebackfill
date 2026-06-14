import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import final
import inject
from pymonad.either import Either, Left, Right
from pymonad.maybe import Just

from mempalace_backfill.alias import Error
from mempalace_backfill.config_load_service import ConfigLoadService


@dataclass(frozen=True)
class SyncState:
    last_session_time: str = ""
    last_session_id: str = ""
    exported_session_ids: list[str] = field(default_factory=list)
    total_sessions_exported: int = 0

    def is_exported(self, session_id: str) -> bool:
        return session_id in self.exported_session_ids

    def mark_exported(self, session_id: str) -> 'SyncState':
        if self.is_exported(session_id):
            return self
        new_ids = self.exported_session_ids + [session_id]
        return SyncState(
            last_session_time=self.last_session_time,
            last_session_id=session_id,
            exported_session_ids=new_ids,
            total_sessions_exported=len(new_ids)
        )


@final
class StateFileRepository:
    @inject.autoparams()
    def __init__(self, config_service: ConfigLoadService):
        self._config_service = config_service

    def load(self) -> Either[Error, SyncState]:
        try:
            config = self._config_service.load_config()
            path = config["backfill"]["state_file"]
            
            if not Path(path).exists():
                return Right(SyncState())

            with open(path, "r") as f:
                data = json.load(f)
                return Right(SyncState(**data))
        except Exception as e:
            return Left(Error(f"Failed to load state: {str(e)}", Just(e)))

    def save(self, state: SyncState) -> Either[Error, bool]:
        try:
            config = self._config_service.load_config()
            path = config["backfill"]["state_file"]
            
            Path(path).parent.mkdir(parents=True, exist_ok=True)

            fd, temp_path = tempfile.mkstemp(dir=str(Path(path).parent))
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(asdict(state), f, indent=4)
                Path(temp_path).replace(path)
            except Exception:
                if Path(temp_path).exists():
                    Path(temp_path).unlink()
                raise

            return Right(True)
        except Exception as e:
            return Left(Error(f"Failed to save state: {str(e)}", Just(e)))
