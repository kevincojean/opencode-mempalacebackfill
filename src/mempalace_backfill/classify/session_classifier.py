from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import final

from pymonad.either import Either

from mempalace_backfill.alias import Error


@final
@dataclass(frozen=True)
class ClassifiedSegment:
    """A segment of a session classified by its purpose/nature."""
    content: str
    markers: list[str]
    start_offset: int
    end_offset: int


class SessionClassifier(ABC):
    """Abstract interface for session classifiers."""

    @abstractmethod
    def classify(self, session_content: str, markers: list[str]) -> Either[Error, list[ClassifiedSegment]]:
        """
        Classifies session content into segments based on markers.

        Args:
            session_content: The full content of the session.
            markers: The list of markers to search for.

        Returns:
            An Either containing an Error or a list of ClassifiedSegments.
        """
        pass
