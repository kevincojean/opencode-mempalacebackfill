from typing import final
import inject
from pymonad.either import Left, Right, Either
from pymonad.maybe import Just

from mempalace_backfill.alias import Error
from mempalace_backfill.classify.session_classifier import ClassifiedSegment
from mempalace_backfill.classify.regex_classifier import RegexClassifier
from mempalace_backfill.config_load_service import ConfigLoadService


@final
class ClassifyPipeline:
    """Orchestrator for classifying session files and applying markers."""

    @inject.autoparams()
    def __init__(
        self,
        config_service: ConfigLoadService,
        regex_classifier: RegexClassifier,
    ) -> None:
        self._config_service = config_service
        self._regex_classifier = regex_classifier

    def classify_file(self, file_path: str) -> Either[Error, list[ClassifiedSegment]]:
        """
        Classifies the content of a file using the regex classifier.
        """
        config = self._config_service.load_config()
        pre_config = config["backfill"]["preclassification"]

        if not pre_config.get("enabled", True):
            return Right([])

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return Left(Error(f"Failed to read file for classification: {file_path}", Just(e)))

        markers = pre_config.get("markers", [])

        return self._regex_classifier.classify(content, markers)

    def apply_markers(
        self, file_path: str, segments: list[ClassifiedSegment]
    ) -> Either[Error, bool]:
        """
        Prefixes segments in the file with [marker] tags.
        Handles multiple markers by concatenating them: [marker1][marker2].

        Returns:
            An Either containing an Error or a bool indicating whether any
            markers were actually applied to the file (True = modified).
        """
        if not segments:
            return Right(False)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Sort segments by start_offset descending to avoid offset shift issues
            sorted_segments = sorted(segments, key=lambda s: s.start_offset, reverse=True)

            new_content = content
            modified = False
            for segment in sorted_segments:
                if not segment.markers:
                    continue

                markers_prefix = "".join([f"[{m}]" for m in segment.markers])

                # Prefix at the start_offset
                prefix = new_content[: segment.start_offset]
                suffix = new_content[segment.start_offset :]

                # Idempotency check: don't double-prefix if already starts with same markers
                if not suffix.startswith(markers_prefix):
                    new_content = prefix + markers_prefix + "\n" + suffix
                    modified = True

            if modified:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(new_content)

            return Right(modified)
        except Exception as e:
            return Left(Error(f"Failed to apply markers to {file_path}", Just(e)))


