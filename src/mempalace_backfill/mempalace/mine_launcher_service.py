import json
import logging
import os
import pty
import re
import select
import subprocess
import tempfile
import time
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
    re.compile(r"is held by", re.IGNORECASE),
]

# Retry configuration for lock contention with exponential backoff.
# mempalace uses non-blocking flock (LOCK_EX | LOCK_NB), so the retry
# must live on our side.  Delays: 5s, 15s, 45s (total worst-case ~65s).
_LOCK_MAX_RETRIES = 3
_LOCK_BASE_DELAY = 5  # seconds; multiplied by 3**attempt

# If the mempalace process produces no output for this many seconds,
# assume it is stuck or crashed and kill it. The mine can take several
# minutes on a large export directory, but it should produce periodic
# progress lines. 300s = 5 minutes of silence.
_LINE_TIMEOUT = 300


@final
class MineLauncherService:
    @inject.autoparams()
    def __init__(self, config_service: ConfigLoadService) -> None:
        self._config_service = config_service

    @staticmethod
    def _check_lock_error(output: str) -> bool:
        return any(p.search(output) for p in _LOCK_PATTERNS)

    @staticmethod
    def _extract_holder_pid(output: str) -> int | None:
        m = re.search(r"held by (?:PID\s+)?(\d+)", output, re.IGNORECASE)
        if m:
            return int(m.group(1))
        return None

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return False
        return True

    def _repair_and_retry(
        self, base_cmd: str, palace_path: str | None, mine_cmd: list[str],
        env: dict[str, str] | None = None,
    ) -> Either[Error, int]:
        """Attempt palace repair after SIGSEGV and retry the mine once."""
        repair_cmd = [base_cmd, "repair", "--mode", "from-sqlite", "--yes", "--archive-existing"]
        if palace_path:
            repair_cmd.extend(["--palace", palace_path])

        logging.info("Attempting palace repair after mine SIGSEGV: %s", " ".join(repair_cmd))
        try:
            repair_proc = subprocess.run(repair_cmd, capture_output=True, text=True, timeout=600, env=env)
        except subprocess.TimeoutExpired:
            return Left(Error("Palace repair timed out after 600s"))

        if repair_proc.returncode != 0:
            return Left(Error(
                f"mempalace mine failed with exit code -11 (SIGSEGV) and palace repair also failed "
                f"(exit {repair_proc.returncode}): {repair_proc.stderr or repair_proc.stdout}"
            ))

        logging.info("Palace repair succeeded — retrying mine")
        return self._run_mine(mine_cmd, base_cmd, palace_path, env=env)

    def _run_mine(self, cmd: list[str], base_cmd: str = "mempalace", palace_path: str | None = None, env: dict[str, str] | None = None) -> Either[Error, int]:
        """Run a single mine subprocess and return the result."""
        logging.info("Starting mempalace mine: %s", " ".join(cmd))

        master_fd, slave_fd = pty.openpty()
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            env=env,
        )
        os.close(slave_fd)

        logging.info("Mempalace mine PID %d started", process.pid)

        output_lines: list[str] = []
        buffer = ""

        while True:
            r, _, _ = select.select([master_fd], [], [], _LINE_TIMEOUT)
            if not r:
                process.kill()
                process.wait()
                os.close(master_fd)
                combined = "\n".join(output_lines)
                return Left(Error(
                    f"mempalace mine produced no output for {_LINE_TIMEOUT}s. "
                    f"Partial output: {combined}"
                ))

            try:
                data = os.read(master_fd, 65536)
            except OSError:
                break

            if not data:
                break

            text = data.decode("utf-8", errors="replace")
            buffer += text

            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.rstrip("\r")
                output_lines.append(line)
                if line:
                    logging.info("[mempalace] %s", line)

        if buffer:
            buffer = buffer.rstrip("\r")
            output_lines.append(buffer)
            if buffer:
                logging.info("[mempalace] %s", buffer)

        os.close(master_fd)
        process.wait()
        combined_output = "\n".join(output_lines)

        if process.returncode != 0:
            if process.returncode == -11:
                return self._repair_and_retry(base_cmd, palace_path, cmd, env=env)
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

    def launch(self, export_dir: str, wing: str, dry_run: bool = False, extract_general: bool = False) -> Either[Error, int]:
        if dry_run:
            cmd = self._build_command(export_dir, wing, extract_general)
            print(f"[DRY-RUN] Command: {' '.join(cmd)}")
            return Right(0)

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

        # Feed the backfill's custom regex patterns into mempalace's classifier
        # via the MEMPALACE_CUSTOM_PATTERNS env var.  general_extractor.py reads
        # this at import time and appends the patterns to its built-in marker sets.
        patterns_file: str | None = None
        env: dict[str, str] | None = None
        try:
            custom_patterns = (
                config.get("backfill", {})
                .get("preclassification", {})
                .get("custom_patterns", {})
            )
            if custom_patterns:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", delete=False, prefix="mempalace_custom_patterns_"
                ) as f:
                    json.dump(custom_patterns, f)
                    patterns_file = f.name
                env = os.environ.copy()
                env["MEMPALACE_CUSTOM_PATTERNS"] = patterns_file
        except (AttributeError, KeyError, OSError) as e:
            logging.warning("Could not export custom patterns to mempalace: %s", e)

        try:
            cmd = self._build_command(export_dir, wing, extract_general)
            last_result: Either[Error, int] | None = None
            for attempt in range(_LOCK_MAX_RETRIES + 1):
                result = self._run_mine(cmd, base_cmd, palace_path, env=env)
                if result.is_right():
                    return result
                err_msg = str(result.monoid[0]) if result.is_left() else ""
                if not MineLauncherService._check_lock_error(err_msg):
                    return result
                last_result = result
                if attempt < _LOCK_MAX_RETRIES:
                    delay = _LOCK_BASE_DELAY * (3 ** attempt)
                    holder_pid = MineLauncherService._extract_holder_pid(err_msg)
                    pid_info = ""
                    if holder_pid is not None:
                        status = "still running" if MineLauncherService._is_pid_alive(holder_pid) else "dead, stale lock?"
                        pid_info = f" (holder PID {holder_pid} — {status})"
                    logging.warning(
                        "mempalace locked (attempt %d/%d)%s — retrying in %ds",
                        attempt + 1, _LOCK_MAX_RETRIES + 1, pid_info, delay,
                    )
                    time.sleep(delay)
            return last_result if last_result is not None else Left(Error("mempalace mine failed"))
        except FileNotFoundError:
            return Left(Error("mempalace not found in PATH"))
        except Exception as e:
            return Left(Error(f"Unexpected error during mempalace mine: {str(e)}", Just(e)))
        finally:
            if patterns_file:
                try:
                    os.unlink(patterns_file)
                except OSError:
                    pass

    def _build_command(self, export_dir: str, wing: str, extract_general: bool = False) -> list[str]:
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
        if extract_general:
            cmd.extend(["--extract", "general"])
        if palace_path:
            cmd.extend(["--palace", palace_path])
        cmd.append(export_dir)
        return cmd
