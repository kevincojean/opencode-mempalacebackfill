import logging
import subprocess
import re
from typing import final
import inject
from pymonad.either import Either, Left, Right
from pymonad.maybe import Just, Nothing

from mempalace_backfill.alias import Error
from mempalace_backfill.config_load_service import ConfigLoadService

_LOCK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"database is locked", re.IGNORECASE),
    re.compile(r"lock", re.IGNORECASE),
    re.compile(r"another process", re.IGNORECASE),
    re.compile(r"already running", re.IGNORECASE),
    re.compile(r"resource temporarily unavailable", re.IGNORECASE),
    re.compile(r"timeout", re.IGNORECASE),
]


@final
class MineLauncherService:
    @inject.autoparams()
    def __init__(self, config_service: ConfigLoadService) -> None:
        self._config_service = config_service

    @staticmethod
    def _check_lock_error(output: str) -> bool:
        return any(p.search(output) for p in _LOCK_PATTERNS)

    def launch(self, export_dir: str, wing: str, dry_run: bool = False) -> Either[Error, int]:
        cmd = self._build_command(export_dir, wing)
        
        if dry_run:
            print(f"[DRY-RUN] Command: {' '.join(cmd)}")
            return Right(0)

        try:
            logging.info("Starting mempalace mine: %s", ' '.join(cmd))
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            assert process.stdout is not None
            output_lines: list[str] = []
            for line in iter(process.stdout.readline, ''):
                line = line.rstrip('\n')
                output_lines.append(line)
                if line:
                    logging.info("[mempalace] %s", line)
            process.stdout.close()

            process.wait(timeout=120)
            combined_output = '\n'.join(output_lines)

            if process.returncode != 0:
                if MineLauncherService._check_lock_error(combined_output):
                    return Left(Error(
                        f"mempalace is locked: {combined_output}"
                    ))
                return Left(Error(
                    f"mempalace mine failed with exit code {process.returncode}: {combined_output}"
                ))

            match = re.search(r"(\d+)\s+drawers?", combined_output)
            if match:
                return Right(int(match.group(1)))

            return Right(0)

        except FileNotFoundError:
            return Left(Error("mempalace not found in PATH"))
        except subprocess.TimeoutExpired:
            return Left(Error("mempalace mine timed out after 120s"))
        except Exception as e:
            return Left(Error(f"Unexpected error during mempalace mine: {str(e)}", Just(e)))

    def _build_command(self, export_dir: str, wing: str) -> list[str]:
        config = self._config_service.load_config()
        
        base_cmd = "mempalace"
        palace_path: str | None = None
        try:
            mempalace_config = config.get("backfill", {}).get("mempalace", {})
            if isinstance(mempalace_config, dict):
                base_cmd = mempalace_config.get("command", "mempalace")
                palace_path = mempalace_config.get("palace_path")
        except (AttributeError, KeyError):
            pass

        cmd = [base_cmd, "mine", "--mode", "convos", "--wing", wing]
        if palace_path:
            cmd.extend(["--palace", palace_path])
        cmd.append(export_dir)
        return cmd
