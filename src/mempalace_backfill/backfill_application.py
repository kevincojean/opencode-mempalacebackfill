import logging
import os
import subprocess
import sys
from typing import final, Any
import inject
import typer
from datetime import datetime
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

console = Console()
app = typer.Typer(add_completion=False)

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
        min_messages: int = 1,
        exclude_title: str = None,
        output_dir: str = "./target/exports",
        state_file: str = "./target/state.json",
        include_system_prompt: bool = False,
        dry_run: bool = False,
        db_path: str = None,
    ) -> Either[Error, int]:
        try:
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
                logging.info("State loaded: %d sessions already exported", state.total_sessions_exported)

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

            logging.info("Querying sessions with filters: %s", filters)
            sessions_result = repo.get_sessions(filters)
            if sessions_result.is_left():
                return sessions_result

            sessions = sessions_result.value
            logging.info("Fetched %d sessions from database", len(sessions))

            if state:
                before = len(sessions)
                sessions = [s for s in sessions if not state.is_exported(s.id)]
                after = len(sessions)
                if before != after:
                    logging.info("After state filtering: %d -> %d sessions (skipped %d already exported)",
                                 before, after, before - after)

            if not sessions:
                console.print("[yellow]No new sessions to export.[/yellow]")
                logging.info("No new sessions to export")
                return Right(0)

            if dry_run:
                console.print(f"[cyan][DRY-RUN] Would export {len(sessions)} sessions to {output_dir}[/cyan]")
                logging.info("DRY-RUN: Would export %d sessions to %s", len(sessions), output_dir)
                return Right(len(sessions))

            logging.info("%s %d sessions to %s", log_prefix, len(sessions), output_dir)
            result = svc.export_all(sessions, output_dir, include_system_prompt)
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
        min_messages: int = 1,
        exclude_title: str = None,
        output_dir: str = "./target/exports",
        state_file: str = "./target/state.json",
        include_system_prompt: bool = False,
        dry_run: bool = False,
        db_path: str = None,
    ) -> Either[Error, int]:
        return BackfillApplication._export_sessions(
            log_prefix="Exporting",
            since=since, until=until, max_sessions=max_sessions,
            min_messages=min_messages, exclude_title=exclude_title,
            output_dir=output_dir, state_file=state_file,
            include_system_prompt=include_system_prompt,
            dry_run=dry_run, db_path=db_path,
        )

    @staticmethod
    def sync(
        since: str = None,
        until: str = None,
        max_sessions: int = 1000,
        min_messages: int = 1,
        exclude_title: str = None,
        output_dir: str = "./target/exports",
        state_file: str = "./target/state.json",
        include_system_prompt: bool = False,
        dry_run: bool = False,
        db_path: str = None,
        wing: str = "opencode-sessions",
        mempalace_db_path: str = None,
        mempalace_command: str = None,
    ) -> Either[Error, int]:
        export_result = BackfillApplication._export_sessions(
            log_prefix="Syncing",
            since=since, until=until, max_sessions=max_sessions,
            min_messages=min_messages, exclude_title=exclude_title,
            output_dir=output_dir, state_file=state_file,
            include_system_prompt=include_system_prompt,
            dry_run=dry_run, db_path=db_path,
        )

        if export_result.is_left():
            return export_result

        exported_count = export_result.value
        if exported_count > 0:
            config_svc = inject.instance(ConfigLoadService)
            mempalace_overrides: dict[str, Any] = {}
            if mempalace_db_path:
                mempalace_overrides["palace_path"] = mempalace_db_path
            if mempalace_command:
                mempalace_overrides["command"] = mempalace_command
            if mempalace_overrides:
                config_svc.load_config({"backfill": {"mempalace": mempalace_overrides}})
            launcher = inject.instance(MineLauncherService)
            launch_result = launcher.launch(output_dir, wing, dry_run)
            if launch_result.is_left():
                err = launch_result.monoid[0]
                console.print(f"[red]Mine failed: {err}[/red]")
                return Left(err)
            else:
                console.print(f"[green]Mined {launch_result.value} drawers into wing '{wing}'.[/green]")

        return Right(exported_count)


@app.command("export")
def export_cmd(
    since: str = typer.Option(None, help="Export sessions after this date (ISO format)"),
    until: str = typer.Option(None, help="Export sessions before this date"),
    max_sessions: int = typer.Option(1000, "--max-sessions", help="Maximum sessions to export"),
    min_messages: int = typer.Option(1, "--min-messages", help="Minimum messages per session"),
    exclude_title: str = typer.Option(None, "--exclude-title", help="Regex to exclude session titles"),
    output_dir: str = typer.Option("./target/exports", "--output-dir", help="Output directory"),
    state_file: str = typer.Option("./target/state.json", "--state-file", help="State file path"),
    include_system_prompt: bool = typer.Option(False, "--include-system-prompt", help="Include system prompts"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing files"),
    db_path: str = typer.Option(None, "--db-path", help="Override SQLite database path"),
):
    """Export sessions to markdown files."""
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
        db_path=db_path
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
    since: str = typer.Option(None, help="Export sessions after this date (ISO format)"),
    until: str = typer.Option(None, help="Export sessions before this date"),
    max_sessions: int = typer.Option(1000, "--max-sessions", help="Maximum sessions to export"),
    min_messages: int = typer.Option(1, "--min-messages", help="Minimum messages per session"),
    exclude_title: str = typer.Option(None, "--exclude-title", help="Regex to exclude session titles"),
    output_dir: str = typer.Option("./target/exports", "--output-dir", help="Output directory"),
    state_file: str = typer.Option("./target/state.json", "--state-file", help="State file path"),
    include_system_prompt: bool = typer.Option(False, "--include-system-prompt", help="Include system prompts"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without executing"),
    db_path: str = typer.Option(None, "--db-path", help="Path to OpenCode SQLite database"),
    wing: str = typer.Option("opencode-sessions", "--wing", help="MemPalace wing to mine into"),
    mempalace_db_path: str = typer.Option(None, "--mempalace-db-path", help="Path to MemPalace palace database (maps to mempalace --palace)"),
    mempalace_command: str = typer.Option(None, "--mempalace-command", help="Override mempalace command path (for testing)"),
):
    """Export sessions and mine them into MemPalace."""
    BackfillApplication._configure_logging()
    result = BackfillApplication.sync(
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
        mempalace_db_path=mempalace_db_path,
        mempalace_command=mempalace_command,
    )
    if result.is_left():
        console.print(f"[red]Error: {result.monoid[0]}[/red]")
        raise typer.Exit(1)


@app.command("test")
def test_cmd(
    args: str = typer.Argument(None, help="Extra arguments to pass to pytest"),
):
    """Run the test suite (uses uv run pytest in project root)."""
    cmd = ["uv", "run", "pytest", "-v"]
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
