import logging
import os
import tempfile
import re
from typing import final
import inject
from pymonad.either import Either, Left, Right
from pymonad.maybe import Just

from mempalace_backfill.alias import Error
from mempalace_backfill.config_load_service import ConfigLoadService
from mempalace_backfill.db.models import Session, Message
from mempalace_backfill.db.message_query_repository import MessageQueryRepository
from mempalace_backfill.export.content_normalization_service import ContentNormalizationService


@final
class MarkdownConversionService:
    @inject.autoparams()
    def __init__(
        self, 
        config_service: ConfigLoadService,
        message_repo: MessageQueryRepository,
        normalizer: ContentNormalizationService
    ) -> None:
        self._config_service = config_service
        self._message_repo = message_repo
        self._normalizer = normalizer

    def convert_to_markdown(self, session: Session, messages: list[Message]) -> Either[Error, str]:
        try:
            lines = [
                f"# {session.subject}",
                f"> Session ID: {session.id}",
                f"> Date: {session.created_at}",
                ""
            ]

            for msg in messages:
                role_label = "User" if msg.role.lower() == "user" else "Assistant"
                if role_label == "User":
                    lines.append("> User")
                    lines.append("")
                    lines.append(msg.content)
                    lines.append("")
                else:
                    lines.append("Assistant")
                    lines.append("")
                    lines.append(msg.content)
                    lines.append("")

            lines.append("---")
            return Right("\n".join(lines))
        except Exception as e:
            return Left(Error(f"Failed to convert session to markdown: {str(e)}", Just(e)))

    def write_file(self, output_dir: str, session_id: str, content: str) -> Either[Error, str]:
        try:
            os.makedirs(output_dir, exist_ok=True)
            
            safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', session_id)
            file_path = os.path.join(output_dir, f"{safe_id}.md")
            
            fd, temp_path = tempfile.mkstemp(dir=output_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, 'w') as f:
                    f.write(content)
                os.replace(temp_path, file_path)
            except Exception:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise
                
            return Right(file_path)
        except Exception as e:
            return Left(Error(f"Failed to write markdown file: {str(e)}", Just(e)))

    def export_all(self, sessions: list[Session], output_dir: str, include_system: bool = False) -> Either[Error, list[str]]:
        try:
            logging.info("Exporting %d sessions to %s (include_system=%s)", len(sessions), output_dir, include_system)
            exported_ids = []
            for session in sessions:
                messages_either = self._message_repo.get_messages(session.id, include_system=True)
                if messages_either.is_left():
                    continue
                
                normalized_either = self._normalizer.normalize_messages(messages_either.value, include_system=include_system)
                if normalized_either.is_left():
                    continue
                
                markdown_either = self.convert_to_markdown(session, normalized_either.value)
                if markdown_either.is_left():
                    continue
                
                write_either = self.write_file(output_dir, session.id, markdown_either.value)
                if write_either.is_right():
                    exported_ids.append(session.id)
            
            return Right(exported_ids)
        except Exception as e:
            return Left(Error(f"Failed to export sessions: {str(e)}", Just(e)))
