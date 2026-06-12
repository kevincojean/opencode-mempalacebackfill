import logging
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
logger = logging.getLogger(__name__)

@final
class BackfillApplication:
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
        mempalace_config: dict[str, Any] = {}
        
        if cli_args.get("db_path"):
            mempalace_config["database_path"] = cli_args["db_path"]
        if cli_args.get("wing"):
            mempalace_config["wing"] = cli_args["wing"]
        if cli_args.get("state_file"):
            backfill_config["state_file"] = cli_args["state_file"]
        if cli_args.get("output_dir"):
            backfill_config["output_dir"] = cli_args["output_dir"]
        if cli_args.get("source_dir"):
            backfill_config["source_dir"] = cli_args["source_dir"]
        
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
    def export(
        since: str = None,
        until: str = None,
        max_sessions: int = None,
        min_messages: int = None,
        exclude_title: str = None,
        output_dir: str = "./target/exports",
        state_file: str = "./target/state.json",
        include_system_prompt: bool = False,
        dry_run: bool = False,
        db_path: str = None,
    ) -> Either[Error, int]:
        try:
            inject.clear_and_configure(BackfillApplication._configure_injector)
            
            config_svc = inject.instance(ConfigLoadService)
            overrides = BackfillApplication._build_overrides(locals())
            config_svc.load_config(overrides)
            
            repo = inject.instance(SessionQueryRepository)
            state_repo = inject.instance(StateFileRepository)
            svc = inject.instance(MarkdownConversionService)
            
            state_result = state_repo.load()
            state = state_result.value if state_result.is_right() else None
            
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
            
            sessions_result = repo.get_sessions(filters)
            if sessions_result.is_left():
                return sessions_result
            
            sessions = sessions_result.value
            
            if state:
                sessions = [s for s in sessions if not state.is_exported(s.id)]
            
            if not sessions:
                console.print("[yellow]No new sessions to export.[/yellow]")
                return Right(0)
            
            if dry_run:
                console.print(f"[cyan][DRY-RUN] Would export {len(sessions)} sessions to {output_dir}[/cyan]")
                return Right(len(sessions))
            
            result = svc.export_all(sessions, output_dir, include_system_prompt)
            if result.is_left():
                return result
            
            exported_ids = result.value
            if state:
                for s_id in exported_ids:
                    state = state.mark_exported(s_id)
                save_result = state_repo.save(state)
                if save_result.is_left():
                    logger.warning("State file save failed (non-critical): %s", save_result.value)
            
            count = len(exported_ids)
            console.print(f"[green]Successfully exported {count} sessions.[/green]")
            return Right(count)
        except Exception as e:
            return Left(Error(f"Export failed: {str(e)}", Just(e)))

    @staticmethod
    def sync(
        since: str = None,
        until: str = None,
        max_sessions: int = None,
        min_messages: int = None,
        exclude_title: str = None,
        output_dir: str = "./target/exports",
        state_file: str = "./target/state.json",
        include_system_prompt: bool = False,
        dry_run: bool = False,
        db_path: str = None,
        wing: str = "opencode-sessions",
    ) -> Either[Error, int]:
        export_result = BackfillApplication.export(
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
            launcher = inject.instance(MineLauncherService)
            launch_result = launcher.launch(output_dir, wing, dry_run)
            if launch_result.is_left():
                err = launch_result.value
                console.print(f"[red]Mine failed: {err}[/red]")
                return Left(err)
            else:
                console.print(f"[green]Mined {launch_result.value} drawers into wing '{wing}'.[/green]")
        
        return Right(exported_count)


@app.command("export")
def export_cmd(
    since: str = typer.Option(None, help="Export sessions after this date (ISO format)"),
    until: str = typer.Option(None, help="Export sessions before this date"),
    max_sessions: int = typer.Option(None, "--max-sessions", help="Maximum sessions to export"),
    min_messages: int = typer.Option(None, "--min-messages", help="Minimum messages per session"),
    exclude_title: str = typer.Option(None, "--exclude-title", help="Regex to exclude session titles"),
    output_dir: str = typer.Option("./target/exports", "--output-dir", help="Output directory"),
    state_file: str = typer.Option("./target/state.json", "--state-file", help="State file path"),
    include_system_prompt: bool = typer.Option(False, "--include-system-prompt", help="Include system prompts"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing files"),
    db_path: str = typer.Option(None, "--db-path", help="Override SQLite database path"),
):
    """Export sessions to markdown files."""
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
    max_sessions: int = typer.Option(None, "--max-sessions", help="Maximum sessions to export"),
    min_messages: int = typer.Option(None, "--min-messages", help="Minimum messages per session"),
    exclude_title: str = typer.Option(None, "--exclude-title", help="Regex to exclude session titles"),
    output_dir: str = typer.Option("./target/exports", "--output-dir", help="Output directory"),
    state_file: str = typer.Option("./target/state.json", "--state-file", help="State file path"),
    include_system_prompt: bool = typer.Option(False, "--include-system-prompt", help="Include system prompts"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without executing"),
    db_path: str = typer.Option(None, "--db-path", help="Override SQLite database path"),
    wing: str = typer.Option("opencode-sessions", "--wing", help="MemPalace wing to mine into"),
):
    """Export sessions and mine them into MemPalace."""
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
        wing=wing
    )
    if result.is_left():
        console.print(f"[red]Error: {result.monoid[0]}[/red]")
        raise typer.Exit(1)
