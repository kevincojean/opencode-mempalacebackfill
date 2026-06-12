import logging
import os
import pty
import re
import select
import subprocess
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

    def launch(self, export_dir: str, wing: str, dry_run: bool = False) -> Either[Error, int]:
        cmd = self._build_command(export_dir, wing)
        
        if dry_run:
            print(f"[DRY-RUN] Command: {' '.join(cmd)}")
            return Right(0)

        try:
            logging.info("Starting mempalace mine: %s", ' '.join(cmd))

            # ── Pseudo-terminal for reliable real-time output ────────────
            #
            # We spawn mempalace through a PTY (pseudo-terminal) instead of a
            # regular pipe.  A PTY is a kernel device pair:
            #
            #   master_fd  ← we read from this (the "terminal" side)
            #   slave_fd   → child writes to this (the "program" side)
            #
            # The child process thinks stdout/stderr are a real terminal, so
            # the C runtime picks line-buffered mode automatically.  Each
            # print() that ends with \n flushes immediately — no buffering
            # delay on the pipe.
            #
            # Why not stdbuf -oL?  stdbuf uses LD_PRELOAD which many
            # environments disable (containers, setuid, AT_SECURE).  Why not
            # PYTHONUNBUFFERED?  mempalace's shebang uses -E which ignores
            # it.  The PTY approach works unconditionally.
            master_fd, slave_fd = pty.openpty()
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
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
                    combined = '\n'.join(output_lines)
                    return Left(Error(
                        f"mempalace mine produced no output for {_LINE_TIMEOUT}s. "
                        f"Partial output: {combined}"
                    ))

                try:
                    data = os.read(master_fd, 65536)
                except OSError:
                    # Common on PTY reads after child has exited (EIO).
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

            # Flush any remaining partial line.
            if buffer:
                buffer = buffer.rstrip("\r")
                output_lines.append(buffer)
                if buffer:
                    logging.info("[mempalace] %s", buffer)

            os.close(master_fd)
            process.wait()
            combined_output = "\n".join(output_lines)

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
