from typing import final
import inject
from pymonad.either import Either, Left, Right
from pymonad.maybe import Just

from mempalace_backfill.alias import Error
from mempalace_backfill.config_load_service import ConfigLoadService
from mempalace_backfill.db.models import Message


@final
class ContentNormalizationService:
    @inject.autoparams()
    def __init__(self, config_service: ConfigLoadService) -> None:
        self._config_service = config_service

    def normalize_messages(self, messages: list[Message], include_system: bool = False) -> Either[Error, list[Message]]:
        try:
            if include_system:
                return Right(messages)
            
            normalized = [msg for msg in messages if msg.role != "system"]
            return Right(normalized)
        except Exception as e:
            return Left(Error(f"Failed to normalize messages: {str(e)}", Just(e)))
