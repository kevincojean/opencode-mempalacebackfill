import hashlib
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import final
import inject
from pymonad.either import Either, Left, Right
from pymonad.maybe import Just

from mempalace_backfill.alias import Error
from mempalace_backfill.config_load_service import ConfigLoadService


@dataclass(frozen=True)
class ExportState:
    last_session_time: str = ""
    last_session_id: str = ""
    exported_session_ids: list[str] = field(default_factory=list)
    total_sessions_exported: int = 0

    def is_exported(self, session_id: str) -> bool:
        return session_id in self.exported_session_ids

    def mark_exported(self, session_id: str) -> 'ExportState':
        if self.is_exported(session_id):
            return self
        new_ids = self.exported_session_ids + [session_id]
        return ExportState(
            last_session_time=self.last_session_time,
            last_session_id=session_id,
            exported_session_ids=new_ids,
            total_sessions_exported=len(new_ids)
        )


@final
class ExportStateFileRepository:
    @inject.autoparams()
    def __init__(self, config_service: ConfigLoadService):
        self._config_service = config_service

    def load(self) -> Either[Error, ExportState]:
        try:
            config = self._config_service.load_config()
            path = config["backfill"]["export_state_file"]

            if not Path(path).exists():
                old_path = str(Path(path).parent / "state.json")
                if Path(old_path).exists():
                    logging.warning(
                        "DEPRECATION: found old state file at %s — migrating to %s",
                        old_path, path,
                    )
                    with open(old_path, "r") as f:
                        data = json.load(f)
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    fd, temp_path = tempfile.mkstemp(dir=str(Path(path).parent))
                    try:
                        with os.fdopen(fd, 'w') as f:
                            json.dump(data, f, indent=4)
                        Path(temp_path).replace(path)
                    except Exception:
                        if Path(temp_path).exists():
                            Path(temp_path).unlink()
                        raise
                    Path(old_path).unlink()
                    logging.info("Migrated state file: %s → %s", old_path, path)
                    return Right(ExportState(**data))

                return Right(ExportState())

            with open(path, "r") as f:
                data = json.load(f)
                return Right(ExportState(**data))
        except Exception as e:
            return Left(Error(f"Failed to load state: {str(e)}", Just(e)))

    def save(self, state: ExportState) -> Either[Error, bool]:
        try:
            config = self._config_service.load_config()
            path = config["backfill"]["export_state_file"]

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


@final
@dataclass(frozen=True)
class MineState:
    mined_files: dict[str, str] = field(default_factory=dict)
    last_mined_at: str = ""
    backend: str = ""
    palace_path_hash: str = ""

    def is_mined(self, file_path: str, content_hash: str) -> bool:
        return self.mined_files.get(file_path) == content_hash

    def mark_mined(self, file_path: str, content_hash: str) -> 'MineState':
        if self.is_mined(file_path, content_hash):
            return self
        new_files = {**self.mined_files, file_path: content_hash}
        return MineState(
            mined_files=new_files,
            last_mined_at=datetime.now().isoformat(),
            backend=self.backend,
            palace_path_hash=self.palace_path_hash,
        )


@final
class MineStateFileRepository:
    @inject.autoparams()
    def __init__(
        self,
        config_service: ConfigLoadService,
        wing: str,
        source_dir: str = "",
        backend: str = "",
        palace_path: str = "",
    ):
        self._config_service = config_service
        self._wing = wing
        self._source_dir = source_dir
        self._backend = backend
        self._palace_path = palace_path

    def _sanitize_wing(self) -> str:
        return re.sub(r'[^a-zA-Z0-9_-]', '_', self._wing)

    def _sanitize_backend(self) -> str:
        return re.sub(r'[^a-zA-Z0-9_-]', '_', self._backend)

    def _source_dir_hash(self) -> str:
        if not self._source_dir:
            return ""
        return hashlib.sha256(self._source_dir.encode()).hexdigest()[:16]

    def _palace_path_hash(self) -> str:
        if not self._palace_path:
            return ""
        return hashlib.sha256(self._palace_path.encode()).hexdigest()[:16]

    def _state_path(self) -> Path:
        config = self._config_service.load_config()
        sync_dir = config["backfill"]["sync_state_dir"]
        sd_hash = self._source_dir_hash()
        pp_hash = self._palace_path_hash()
        sanitized_backend = self._sanitize_backend()
        sanitized_wing = self._sanitize_wing()
        parts = ["sync_state"]
        if sanitized_backend:
            parts.append(sanitized_backend)
        if pp_hash:
            parts.append(pp_hash)
        parts.append(sanitized_wing)
        if sd_hash:
            parts.append(sd_hash)
        return Path(sync_dir) / ("_".join(parts) + ".json")

    def load(self) -> Either[Error, 'MineState']:
        try:
            path = self._state_path()
            if not path.exists():
                return Right(MineState(
                    backend=self._backend,
                    palace_path_hash=self._palace_path_hash(),
                ))
            with open(path, "r") as f:
                data = json.load(f)
            state = MineState(**data)
            if state.backend != self._backend or state.palace_path_hash != self._palace_path_hash():
                logging.info(
                    "Mine state namespace mismatch (stored=%s/%s, current=%s/%s) - treating as fresh mine",
                    state.backend, state.palace_path_hash,
                    self._backend, self._palace_path_hash(),
                )
                return Right(MineState(
                    backend=self._backend,
                    palace_path_hash=self._palace_path_hash(),
                ))
            return Right(state)
        except Exception as e:
            return Left(Error(f"Failed to load mine state: {str(e)}", Just(e)))

    def save(self, state: MineState) -> Either[Error, bool]:
        try:
            path = self._state_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_path = tempfile.mkstemp(dir=str(path.parent))
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
            return Left(Error(f"Failed to save mine state: {str(e)}", Just(e)))
