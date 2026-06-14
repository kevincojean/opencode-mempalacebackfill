import json
import logging
import os
import subprocess
import sys
from typing import final, Any, Iterator
import inject
import typer
import shutil
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timedelta
from rich.console import Console
from pymonad.either import Either, Left, Right
from pymonad.maybe import Just

from mempalace_backfill.alias import Error
from mempalace_backfill.config_load_service import ConfigLoadService
from mempalace_backfill.db.session_query_repository import SessionQueryRepository
from mempalace_backfill.db.message_query_repository import MessageQueryRepository
from mempalace_backfill.export.content_normalization_service import ContentNormalizationService
from mempalace_backfill.export.markdown_conversion_service import MarkdownConversionService
from mempalace_backfill.state.state_file_repository import StateFileRepository
from mempalace_backfill.mempalace.mine_launcher_service import MineLauncherService
from mempalace_backfill.classify.classify_pipeline import ClassifyPipeline
from mempalace_backfill.classify.regex_classifier import RegexClassifier

_XDG_DATA_HOME = Path.home() / ".local" / "share" / "com.kevincojean.opencode-mempalacebackfill"
_DEFAULT_EXPORT_DIR = str(_XDG_DATA_HOME / "exports")
_DEFAULT_STATE_FILE = str(_XDG_DATA_HOME / "state.json")
_DEFAULT_PALACE_DIR = str(Path.home() / ".mempalace" / "palace")

console = Console()


def _resolve_palace_path(config: dict, cli_palace_path: str | None) -> str:
    """Resolve the MemPalace palace database path."""
    if cli_palace_path:
        return cli_palace_path
    try:
        return (
            config.get("backfill", {})
            .get("mempalace", {})
            .get("palace_path", _DEFAULT_PALACE_DIR)
        )
    except Exception:
        return _DEFAULT_PALACE_DIR


def _run_delete_drawers_subprocess(
    palace_path: str,
    source_files: set[str],
    extract_mode: str | None = "exchange",
) -> Either[Error, int]:
    """Run drawer deletion in a subprocess to isolate ChromaDB segfaults.

    ChromaDB 1.5.8 (used by MemPalace 3.4.0) can segfault in the HNSW
    segment writer during ``collection.delete()``.  Running it in a
    subprocess prevents the segfault from killing the main process.

    Returns:
        Right with count of deleted drawers (0 if nothing to delete),
        or Left on error (including segfault).
    """
    if not source_files:
        return Right(0)

    helper_path = Path(__file__).parent / "delete_drawers_helper.py"
    if not helper_path.is_file():
        logging.warning("Deletion helper not found at %s — skipping deletion", helper_path)
        return Right(0)

    args = {
        "palace_path": palace_path,
        "source_files": sorted(source_files),
        "extract_mode": extract_mode,
    }

    try:
        proc = subprocess.run(
            [sys.executable, str(helper_path), json.dumps(args)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        logging.warning("Drawer deletion timed out after 120s — skipping")
        return Left(Error("Deletion timed out"))

    # SIGSEGV (exit code -11) — ChromaDB segfault, palace may be corrupted.
    if proc.returncode == -11:
        logging.warning(
            "ChromaDB deletion segfaulted (HNSW segment writer crash). "
            "Palace index may need repair."
        )
        return Left(Error("ChromaDB segfault during deletion"))

    if proc.returncode != 0:
        try:
            result = json.loads(proc.stdout)
            msg = result.get("message", proc.stderr or proc.stdout or f"exit code {proc.returncode}")
        except (json.JSONDecodeError, KeyError):
            msg = proc.stderr or proc.stdout or f"exit code {proc.returncode}"
        logging.warning("Drawer deletion failed: %s", msg)
        return Left(Error(f"Deletion failed: {msg}"))

    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        logging.warning("Could not parse deletion helper output: %s", proc.stdout)
        return Right(0)

    deleted = result.get("deleted", 0)
    status = result.get("status", "ok")
    if status == "partial":
        failed = result.get("failed", [])
        logging.warning(
            "Drawer deletion partial: deleted %d, %d file(s) failed: %s",
            deleted, len(failed), "; ".join(failed),
        )
    elif deleted:
        logging.info("Deleted %d stale drawer(s) from %d file(s)", deleted, len(source_files))
    return Right(deleted)


def _repair_palace(palace_path: str) -> Either[Error, str]:
    """Rebuild the palace vector index using ``mempalace repair --mode from-sqlite``.

    This bypasses the ChromaDB client entirely, reading rows directly from
    ``chroma.sqlite3``, and is the safest recovery path after an HNSW
    segfault.

    Returns:
        Right with repair output, or Left on failure.
    """
    try:
        proc = subprocess.run(
            ["mempalace", "repair", "--mode", "from-sqlite", "--yes", "--archive-existing", "--palace", palace_path],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except FileNotFoundError:
        return Left(Error("mempalace not found in PATH — cannot repair palace"))
    except subprocess.TimeoutExpired:
        return Left(Error("Palace repair timed out after 600s"))

    if proc.returncode == 0:
        logging.info("Palace repair completed successfully")
        return Right(proc.stdout)
    else:
        msg = f"Palace repair failed (exit {proc.returncode}): {proc.stderr or proc.stdout}"
        logging.warning(msg)
        return Left(Error(msg))


def _delete_palace_drawers(
    palace_path: str,
    source_files: set[str],
    extract_mode: str | None = "exchange",
) -> Either[Error, int]:
    """Delete drawers for given source files from the palace ChromaDB.

    Runs the ChromaDB operation in a **subprocess** to isolate segfaults
    from the HNSW segment writer (ChromaDB 1.5.8 known issue).

    On segfault, attempts automatic palace repair via
    ``mempalace repair --mode from-sqlite`` before returning.

    Returns:
        Right with count of deleted drawers (0 if segfault-repaired),
        or Left on error.
    """
    result = _run_delete_drawers_subprocess(palace_path, source_files, extract_mode)

    if result.is_right():
        return result

    # If the subprocess segfaulted, try to repair the palace index
    # before giving up.  The caller can decide whether to retry.
    error_msg = str(result.value)
    if "segfault" in error_msg or "HNSW" in error_msg:
        logging.info("Attempting palace repair after deletion segfault...")
        repair_result = _repair_palace(palace_path)
        if repair_result.is_right():
            logging.info("Palace repaired — deletions not applied, will re-mine all files")
            return Right(0)
        else:
            logging.warning("Palace repair also failed: %s", repair_result.value)

    return result
app = typer.Typer(add_completion=False)


@contextmanager
def _managed_mine_source(output_dir: str, max_sessions: int | None, force_temp: bool = False) -> Iterator[str]:
    """Yield a directory to mine from, creating a temp subset when max_sessions is set
    or force_temp is True.

    When max_sessions is specified or force_temp is True, copies the markdown files from the
    output directory (including any wing subdirectory structure) into a temporary
    subdirectory inside the output directory, preserving relative paths.
    If max_sessions is set, only the first N files are copied.
    The temp directory is cleaned up on completion, error, or interrupt via the
    context manager's finally block.
    """
    if max_sessions is None and not force_temp:
        yield output_dir
        return

    tmp_dir = Path(output_dir) / f".tmp_sync_{os.urandom(4).hex()}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        md_files = sorted(Path(output_dir).rglob("*.md"))
        copied = 0
        for f in md_files:
            if max_sessions is not None and copied >= max_sessions:
                break
            rel = f.relative_to(output_dir)
            dest = tmp_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(f), str(dest))
            copied += 1
        
        limit_info = f"{copied}/{len(md_files)}" if max_sessions else f"{copied}"
        logging.debug("Temp mine dir %s: copied %s markdown files", tmp_dir, limit_info)
        yield str(tmp_dir)
    finally:
        if tmp_dir.exists():
            shutil.rmtree(str(tmp_dir))


@final
class BackfillApplication:
    @staticmethod
    def _configure_logging() -> None:
        root = logging.getLogger()
        log_level_str = os.environ.get("LOG_LEVEL", "INFO").upper()
        log_level = getattr(logging, log_level_str, logging.INFO)
        root.setLevel(log_level)

        if not root.handlers:
            fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

            stdout_handler = logging.StreamHandler(sys.stdout)
            stdout_handler.setLevel(log_level)
            stdout_handler.addFilter(lambda record: record.levelno < logging.ERROR)
            stdout_handler.setFormatter(fmt)

            stderr_handler = logging.StreamHandler(sys.stderr)
            stderr_handler.setLevel(logging.ERROR)
            stderr_handler.setFormatter(fmt)

            root.addHandler(stdout_handler)
            root.addHandler(stderr_handler)

    @staticmethod
    def _configure_injector(binder: inject.Binder) -> None:
        config_svc = ConfigLoadService()
        binder.bind(ConfigLoadService, config_svc)
        binder.bind_to_constructor(SessionQueryRepository, SessionQueryRepository)
        binder.bind_to_constructor(MessageQueryRepository, MessageQueryRepository)
        binder.bind_to_constructor(ContentNormalizationService, ContentNormalizationService)
        binder.bind_to_constructor(MarkdownConversionService, MarkdownConversionService)
        binder.bind_to_constructor(StateFileRepository, StateFileRepository)
        binder.bind_to_constructor(MineLauncherService, MineLauncherService)

        # Classification
        def configure_regex(config_svc_inst: ConfigLoadService):
            config = config_svc_inst.load_config()
            custom = config["backfill"]["preclassification"].get("custom_patterns", {})
            return RegexClassifier(custom_patterns=custom)

        binder.bind_to_provider(RegexClassifier, lambda: configure_regex(inject.instance(ConfigLoadService)))
        binder.bind_to_constructor(ClassifyPipeline, ClassifyPipeline)

    @staticmethod
    def _build_overrides(cli_args: dict) -> dict:
        overrides: dict[str, Any] = {}
        backfill_config: dict[str, Any] = {}
        opencode_config: dict[str, Any] = {}
        mempalace_config: dict[str, Any] = {}
        
        if cli_args.get("db_path"):
            opencode_config["database_path"] = cli_args["db_path"]
        if cli_args.get("mempalace_db_path"):
            mempalace_config["palace_path"] = cli_args["mempalace_db_path"]
        if cli_args.get("wing"):
            mempalace_config["wing"] = cli_args["wing"]
        if cli_args.get("state_file"):
            backfill_config["state_file"] = cli_args["state_file"]
        if cli_args.get("output_dir"):
            backfill_config["output_dir"] = cli_args["output_dir"]
        if cli_args.get("source_dir"):
            backfill_config["source_dir"] = cli_args["source_dir"]
        
        if opencode_config:
            backfill_config["opencode"] = opencode_config
        if mempalace_config:
            backfill_config["mempalace"] = mempalace_config
        if backfill_config:
            overrides["backfill"] = backfill_config
            
        return overrides

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str)
        except ValueError:
            return None

    @staticmethod
    def _export_sessions(
        log_prefix: str,
        since: str = None,
        until: str = None,
        max_sessions: int = 1000,
        min_messages: int = 5,
        exclude_title: str = None,
        output_dir: str = _DEFAULT_EXPORT_DIR,
        state_file: str = _DEFAULT_STATE_FILE,
        include_system_prompt: bool = False,
        dry_run: bool = False,
        db_path: str = None,
        wing: str | None = None,
    ) -> Either[Error, int]:
        try:
            if since is None and until is None:
                since = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
                logging.debug("No --since/--until provided, defaulting --since to 3 months ago: %s", since)

            logging.info("%s sessions: max_sessions=%s, since=%s, until=%s, exclude_title=%s, min_messages=%s, output_dir=%s",
                         log_prefix, max_sessions, since, until, exclude_title, min_messages, output_dir)

            inject.clear_and_configure(BackfillApplication._configure_injector)

            config_svc = inject.instance(ConfigLoadService)
            overrides = BackfillApplication._build_overrides(locals())
            config_svc.load_config(overrides)

            repo = inject.instance(SessionQueryRepository)
            state_repo = inject.instance(StateFileRepository)
            svc = inject.instance(MarkdownConversionService)

            state_result = state_repo.load()
            state = state_result.value if state_result.is_right() else None
            if state:
                logging.debug("State loaded: %d sessions already exported", state.total_sessions_exported)

            filters = {}
            if since:
                filters["since"] = BackfillApplication._parse_date(since)
            if until:
                filters["until"] = BackfillApplication._parse_date(until)
            if max_sessions:
                filters["max_sessions"] = max_sessions
            if min_messages:
                filters["min_messages"] = min_messages
            if exclude_title:
                filters["exclude_title"] = exclude_title

            logging.debug("Querying sessions with filters: %s", filters)
            sessions_result = repo.get_sessions(filters)
            if sessions_result.is_left():
                return sessions_result

            sessions = sessions_result.value
            fetched_count = len(sessions)
            logging.debug("Fetched %d sessions from database", fetched_count)

            if state:
                before = fetched_count
                sessions = [s for s in sessions if not state.is_exported(s.id)]
                after = len(sessions)
                if before != after:
                    hit_limit = (before == max_sessions)
                    if after == 0 and hit_limit:
                        logging.warning(
                            "After state filtering: %d -> %d sessions (skipped %d already exported). "
                            "All fetched sessions were already exported AND the query hit LIMIT=%d — "
                            "there may be older unexported sessions beyond this limit. "
                            "Try a higher --max-sessions value.",
                            before, after, before - after, max_sessions,
                        )
                    else:
                        logging.info("After state filtering: %d -> %d sessions (skipped %d already exported)",
                                     before, after, before - after)

            if not sessions:
                if state and fetched_count == max_sessions:
                    msg = (
                        "No new sessions to export — the SQL query hit LIMIT=%d and all fetched "
                        "sessions were already exported. Older unexported sessions may exist "
                        "beyond this limit. Try a higher --max-sessions value."
                    )
                    logging.warning(msg, max_sessions)
                    console.print(f"[yellow]{msg % max_sessions}[/yellow]")
                else:
                    logging.info("No new sessions to export")
                    console.print("[yellow]No new sessions to export.[/yellow]")
                return Right(0)

            if dry_run:
                console.print(f"[cyan][DRY-RUN] Would export {len(sessions)} sessions to {output_dir}[/cyan]")
                logging.info("DRY-RUN: Would export %d sessions to %s", len(sessions), output_dir)
                return Right(len(sessions))

            logging.info("%s %d sessions to %s (wing=%s)", log_prefix, len(sessions), output_dir, wing or "auto")
            result = svc.export_all(sessions, output_dir, include_system_prompt, wing=wing)
            if result.is_left():
                return result

            exported_ids = result.value
            if state:
                for s_id in exported_ids:
                    state = state.mark_exported(s_id)
                save_result = state_repo.save(state)
                if save_result.is_left():
                    logging.warning("State file save failed (non-critical): %s", save_result.value)

            count = len(exported_ids)
            console.print(f"[green]Successfully exported {count} sessions.[/green]")
            logging.info("Successfully exported %d sessions to %s", count, output_dir)
            return Right(count)
        except Exception as e:
            logging.error("Export failed: %s", e)
            return Left(Error(f"Export failed: {str(e)}", Just(e)))

    @staticmethod
    def export(
        since: str = None,
        until: str = None,
        max_sessions: int = 1000,
        min_messages: int = 5,
        exclude_title: str = None,
        output_dir: str = _DEFAULT_EXPORT_DIR,
        state_file: str = _DEFAULT_STATE_FILE,
        include_system_prompt: bool = False,
        dry_run: bool = False,
        db_path: str = None,
        wing: str | None = None,
    ) -> Either[Error, int]:
        return BackfillApplication._export_sessions(
            log_prefix="Exporting",
            since=since, until=until, max_sessions=max_sessions,
            min_messages=min_messages, exclude_title=exclude_title,
            output_dir=output_dir, state_file=state_file,
            include_system_prompt=include_system_prompt,
            dry_run=dry_run, db_path=db_path, wing=wing,
        )

    @staticmethod
    def sync(
        output_dir: str = _DEFAULT_EXPORT_DIR,
        dry_run: bool = False,
        wing: str | None = None,
        mempalace_db_path: str | None = None,
        mempalace_command: str | None = None,
        max_sessions: int | None = None,
    ) -> Either[Error, int]:
        try:
            inject.clear_and_configure(BackfillApplication._configure_injector)
            config_svc = inject.instance(ConfigLoadService)

            mempalace_overrides: dict[str, Any] = {}
            if mempalace_db_path:
                mempalace_overrides["palace_path"] = mempalace_db_path
            if mempalace_command:
                mempalace_overrides["command"] = mempalace_command

            overrides: dict[str, Any] = {}
            if mempalace_overrides:
                overrides.setdefault("backfill", {})["mempalace"] = mempalace_overrides
            config = config_svc.load_config(overrides)
            pre_config = config["backfill"].get("preclassification", {})
            preclass_enabled = pre_config.get("enabled", False)
            palace_path = _resolve_palace_path(config, mempalace_db_path)
            launcher = inject.instance(MineLauncherService)
            classifier = inject.instance(ClassifyPipeline)

            if wing:
                wing_dirs: dict[str, str] = {wing: output_dir}
            else:
                wing_dirs = BackfillApplication._discover_wing_dirs(output_dir)
                if not wing_dirs:
                    wing_dirs = {"opencode-sessions": output_dir}

            total_mined = 0
            for w, source in wing_dirs.items():
                modified_files: set[str] = set()

                # ── Step 1: Classify original files in-place ──────────────
                if preclass_enabled and not dry_run:
                    md_files = sorted(
                        p for p in Path(source).rglob("*.md")
                        if ".tmp_sync_" not in p.parts
                    )
                    logging.info(
                        "Pre-classifying %d sessions in wing '%s' (in-place)",
                        len(md_files), w,
                    )
                    for f in md_files:
                        classify_result = classifier.classify_file(str(f))
                        if classify_result.is_right():
                            segments = classify_result.value
                            if segments:
                                apply_result = classifier.apply_markers(str(f), segments)
                                if apply_result.is_right() and apply_result.value:
                                    modified_files.add(str(f))

                    if modified_files:
                        logging.info(
                            "  → %d file(s) got new markers",
                            len(modified_files),
                        )

                # ── Step 2: Delete stale palace drawers for modified files ──
                # Only delete when NOT using a temp dir for mining (temp dirs
                # create different source_file paths that don't match the
                # original paths stored in the palace).
                if modified_files and not dry_run and max_sessions is None:
                    logging.info(
                        "Deleting stale palace drawers for %d modified file(s)",
                        len(modified_files),
                    )
                    delete_result = _delete_palace_drawers(
                        palace_path, modified_files,
                    )
                    if delete_result.is_left():
                        logging.warning(
                            "Palace drawer deletion failed (non-fatal): %s",
                            delete_result.value,
                        )

                # ── Step 3: Mine ──────────────────────────────────────────
                # When max_sessions is set, use a temp dir (old behavior:
                # copy + classify + mine on subset).  The classification
                # above already modified originals, so the temp copy picks
                # up classified files.  Stale-drawer deletion is skipped
                # for the temp-dir case because temp paths are ephemeral.
                # When no max_sessions, mine the original dir directly so
                # mempalace sees the same source_file paths and can
                # skip-unchanged / re-mine only deleted drawers.
                use_temp = max_sessions is not None
                with _managed_mine_source(source, max_sessions, force_temp=use_temp) as source_dir:
                    logging.info("Starting mempalace mine: wing=%s, dir=%s", w, source_dir)
                    launch_result = launcher.launch(
                        source_dir, w, dry_run,
                        extract_general=preclass_enabled,
                    )
                    if launch_result.is_left():
                        return launch_result
                    mined = launch_result.value
                    total_mined += mined
                    if not dry_run:
                        num_str = f"{mined} drawer{'s' if mined != 1 else ''}"
                        console.print(f"[green]Mined {num_str} into wing '{w}'.[/green]")
                        logging.info("Mine complete: %d drawers into wing '%s'", mined, w)

            if not dry_run:
                total_str = f"{total_mined} drawer{'s' if total_mined != 1 else ''}"
                console.print(f"[green]Total: {total_str} across {len(wing_dirs)} wing(s).[/green]")

            return Right(total_mined)
        except Exception as e:
            logging.error("Sync failed: %s", e)
            return Left(Error(f"Sync failed: {str(e)}", Just(e)))

    @staticmethod
    def _discover_wing_dirs(output_dir: str) -> dict[str, str]:
        """Discover wing subdirectories in the output directory.

        Each subdirectory whose name starts with ``wing_`` is treated as a wing
        group. Returns a dict mapping wing name to source directory path.
        Falls back to an empty dict if no wing subdirectories exist.
        """
        result: dict[str, str] = {}
        try:
            output_path = Path(output_dir)
            if not output_path.is_dir():
                return result
            for entry in output_path.iterdir():
                if entry.is_dir() and entry.name.startswith("wing_"):
                    result[entry.name] = str(entry)
        except FileNotFoundError:
            pass
        return result

    @staticmethod
    def classify_only(
        output_dir: str = _DEFAULT_EXPORT_DIR,
        wing: str | None = None,
        max_sessions: int | None = None,
        preview: bool = False,
    ) -> Either[Error, int]:
        """Classify exported sessions without mining to MemPalace.

        By default, markers are written directly to the original export files
        (in-place).  When *preview* is True, classification runs on temp
        copies so originals are left untouched (the old behaviour).

        Does NOT call ``mempalace mine``.  After reviewing the output, run
        ``mempalace-backfill sync`` to mine the classified files into
        MemPalace.
        """
        try:
            inject.clear_and_configure(BackfillApplication._configure_injector)
            config_svc = inject.instance(ConfigLoadService)
            config = config_svc.load_config()
            pre_config = config["backfill"].get("preclassification", {})

            if not pre_config.get("enabled", False):
                console.print("[yellow]Preclassification is disabled in config — nothing to do.[/yellow]")
                return Right(0)

            classifier = inject.instance(ClassifyPipeline)

            if wing:
                wing_dirs: dict[str, str] = {wing: output_dir}
            else:
                wing_dirs = BackfillApplication._discover_wing_dirs(output_dir)
                if not wing_dirs:
                    wing_dirs = {"opencode-sessions": output_dir}

            total_modified = 0
            total_marker_hits = 0
            total_files = 0
            for w, source in wing_dirs.items():
                if preview:
                    work_dir_gen = _managed_mine_source(source, max_sessions, force_temp=True)
                else:
                    work_dir_gen = _managed_mine_source(source, max_sessions, force_temp=False)

                with work_dir_gen as source_dir:
                    md_files = sorted(
                        p for p in Path(source_dir).rglob("*.md")
                        if ".tmp_sync_" not in p.parts
                    )
                    logging.info("Classifying %d sessions in wing '%s'", len(md_files), w)

                    wing_modified = 0
                    marker_counts: dict[str, int] = {}
                    for f in md_files:
                        total_files += 1
                        result = classifier.classify_file(str(f))
                        if result.is_right():
                            segments = result.value
                            if segments:
                                apply_result = classifier.apply_markers(str(f), segments)
                                if apply_result.is_right() and apply_result.value:
                                    wing_modified += 1
                                    total_modified += 1
                                for s in segments:
                                    for m in s.markers:
                                        marker_counts[m] = marker_counts.get(m, 0) + 1
                                        total_marker_hits += 1
                        else:
                            logging.warning("Classification failed for %s: %s", f, result.value)

                    if wing_modified:
                        markers_summary = ", ".join(
                            f"{k}={v}" for k, v in sorted(marker_counts.items())
                        )
                        console.print(
                            f"[cyan]Wing '{w}':[/cyan] {wing_modified}/{len(md_files)} files "
                            f"got markers ({markers_summary})"
                        )
                    else:
                        console.print(f"[dim]Wing '{w}': 0/{len(md_files)} files changed[/dim]")

            if total_modified:
                verb = "Preview:" if preview else "Applied:"
                console.print(
                    f"[green]{verb} {total_modified}/{total_files} files modified "
                    f"({total_marker_hits} marker hits). "
                    f"Run `sync` to mine the results into MemPalace.[/green]"
                )
            else:
                console.print("[yellow]No files were modified (all already had markers?).[/yellow]")

            return Right(total_modified)
        except Exception as e:
            logging.error("Classify failed: %s", e)
            return Left(Error(f"Classify failed: {str(e)}", Just(e)))

    @staticmethod
    def clean(
        output_dir: str = _DEFAULT_EXPORT_DIR,
        state_file: str = _DEFAULT_STATE_FILE,
    ) -> Either[Error, int]:
        from mempalace_backfill.clean_service import CleanService

        output_path = Path(output_dir)
        state_path = Path(state_file)
        state_existed = state_path.exists()
        dir_exists = output_path.is_dir()

        result = CleanService.clean(output_dir, state_file)

        if result.is_right():
            count = result.value
            if not dir_exists and not state_existed:
                console.print("[yellow]Nothing to clean. Output directory and state file do not exist.[/yellow]")
            else:
                status = f"output directory ({count} items removed)"
                if state_existed:
                    status += ", state file removed"
                console.print(f"[green]Cleaned: {status}[/green]")

        return result


@app.command("export")
def export_cmd(
    since: str = typer.Option(None, help="Export sessions after this date (ISO format, defaults to 3 months ago)"),
    until: str = typer.Option(None, help="Export sessions before this date"),
    max_sessions: int = typer.Option(1000, "--max-sessions", help="Maximum sessions to export"),
    min_messages: int = typer.Option(5, "--min-messages", help="Minimum messages per session"),
    exclude_title: str = typer.Option(None, "--exclude-title", help="Regex to exclude session titles"),
    output_dir: str | None = typer.Option(None, "--output-dir", help="Output directory (default: <project-root>/target/exports)"),
    state_file: str | None = typer.Option(None, "--state-file", help="State file path (default: <project-root>/target/state.json)"),
    include_system_prompt: bool = typer.Option(False, "--include-system-prompt", help="Include system prompts"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing files"),
    db_path: str = typer.Option(None, "--db-path", help="Override SQLite database path"),
    wing: str = typer.Option(None, "--wing", help="Target MemPalace wing (default: auto-detected from session project path)"),
):
    """Export sessions to markdown files, organized by wing."""
    if output_dir is None:
        output_dir = _DEFAULT_EXPORT_DIR
    if state_file is None:
        state_file = _DEFAULT_STATE_FILE
    BackfillApplication._configure_logging()
    result = BackfillApplication.export(
        since=since,
        until=until,
        max_sessions=max_sessions,
        min_messages=min_messages,
        exclude_title=exclude_title,
        output_dir=output_dir,
        state_file=state_file,
        include_system_prompt=include_system_prompt,
        dry_run=dry_run,
        db_path=db_path,
        wing=wing,
    )
    if result.is_left():
        err = result.monoid[0]
        if err:
            msg = f"[red]Error: {err.message}[/red]"
            if err.exception.is_just():
                msg += f" (Exception: {err.exception.value})"
            console.print(msg)
        else:
            console.print("[red]Error: Unknown error.[/red]")
        raise typer.Exit(1)

@app.command("sync")
def sync_cmd(
    output_dir: str | None = typer.Option(None, "--output-dir", help="Output directory containing exported sessions (default: <project-root>/target/exports)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without executing"),
    wing: str = typer.Option(None, "--wing", help="MemPalace wing to mine into (default: auto-detected from export subdirectories)"),
    max_sessions: int | None = typer.Option(None, "--max-sessions", help="Maximum number of session files to mine (copies first N into a temp dir)"),
    mempalace_db_path: str = typer.Option(None, "--mempalace-db-path", help="Path to MemPalace palace database (maps to mempalace --palace)"),
    mempalace_command: str = typer.Option(None, "--mempalace-command", help="Override mempalace command path (for testing)"),
):
    """Mine existing exported sessions into MemPalace.

    When pre-classification is enabled, markers are applied directly to
    the original export files in-place (no temp copy).  Stale palace
    drawers for files that received new markers are deleted before the
    mine, so only changed files get re-processed by ``mempalace mine``.

    When ``--max-sessions`` is set, a temp copy is still used to limit
    the number of files sent to the mine, and stale-drawer deletion is
    skipped (temp paths are ephemeral).
    """
    if output_dir is None:
        output_dir = _DEFAULT_EXPORT_DIR
    BackfillApplication._configure_logging()
    result = BackfillApplication.sync(
        output_dir=output_dir,
        dry_run=dry_run,
        wing=wing,
        max_sessions=max_sessions,
        mempalace_db_path=mempalace_db_path,
        mempalace_command=mempalace_command,
    )
    if result.is_left():
        err = result.monoid[0]
        if err:
            msg = f"[red]Error: {err.message}[/red]"
            if err.exception.is_just():
                msg += f" (Exception: {err.exception.value})"
            console.print(msg)
        else:
            console.print("[red]Error: Unknown error.[/red]")
        raise typer.Exit(1)


@app.command("classify")
def classify_cmd(
    output_dir: str | None = typer.Option(None, "--output-dir", help="Output directory containing exported sessions (default: ~/.local/share/.../exports)"),
    wing: str = typer.Option(None, "--wing", help="Only classify sessions in this wing"),
    max_sessions: int | None = typer.Option(None, "--max-sessions", help="Limit to first N files per wing"),
    preview: bool = typer.Option(False, "--preview", help="Run on temp copies without modifying originals"),
):
    """Classify exported sessions without mining to MemPalace.

    Prefixes passages with [decision] / [milestone] / etc. markers.

    By default markers are written directly to the original export files
    (in-place).  Use --preview to run on temp copies and see what would
    change without modifying anything.

    After reviewing the output, run \b
        mempalace-backfill sync
    to mine the classified files into MemPalace.
    """
    if output_dir is None:
        output_dir = _DEFAULT_EXPORT_DIR
    BackfillApplication._configure_logging()

    if preview:
        console.print("[dim](Preview mode — using temp copies, originals unchanged)[/dim]")

    result = BackfillApplication.classify_only(
        output_dir=output_dir,
        wing=wing,
        max_sessions=max_sessions,
        preview=preview,
    )
    if result.is_left():
        err = result.monoid[0]
        if err:
            msg = f"[red]Error: {err.message}[/red]"
            if err.exception.is_just():
                msg += f" (Exception: {err.exception.value})"
            console.print(msg)
        else:
            console.print("[red]Error: Unknown error.[/red]")
        raise typer.Exit(1)


@app.command("clean")
def clean_cmd(
    output_dir: str | None = typer.Option(None, "--output-dir", help="Output directory to clean (default: <project-root>/target/exports)"),
    state_file: str | None = typer.Option(None, "--state-file", help="State file to remove (default: <project-root>/target/state.json)"),
):
    """Remove all contents from the output directory and reset the export state."""
    if output_dir is None:
        output_dir = _DEFAULT_EXPORT_DIR
    if state_file is None:
        state_file = _DEFAULT_STATE_FILE
    BackfillApplication._configure_logging()
    result = BackfillApplication.clean(
        output_dir=output_dir,
        state_file=state_file,
    )
    if result.is_left():
        err = result.monoid[0]
        if err:
            msg = f"[red]Error: {err.message}[/red]"
            if err.exception.is_just():
                msg += f" (Exception: {err.exception.value})"
            console.print(msg)
        else:
            console.print("[red]Error: Unknown error.[/red]")
        raise typer.Exit(1)


@app.command("test")
def test_cmd(
    args: str = typer.Argument(None, help="Extra arguments to pass to pytest"),
):
    """Run the test suite (uses uv run pytest in project root)."""
    cmd = ["uv", "run", "pytest", "-v", "-n", "auto"]
    if args:
        cmd.extend(args.split())
    result = subprocess.run(cmd)
    raise typer.Exit(result.returncode)


@app.command("reinstall")
def reinstall_cmd(
    project_dir: str = typer.Argument(".", help="Path to project root (must contain pyproject.toml)"),
):
    """Reinstall the tool from source (uv tool install . --force --reinstall)."""
    cmd = ["uv", "tool", "install", ".", "--force", "--reinstall"]
    console.print(f"[cyan]Reinstalling from {project_dir}...[/cyan]")
    result = subprocess.run(cmd, cwd=project_dir)
    if result.returncode == 0:
        console.print("[green]Reinstall complete.[/green]")
    raise typer.Exit(result.returncode)


if __name__ == "__main__":
    app()
