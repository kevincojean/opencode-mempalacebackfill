import sys
from typing import final
from pymonad.either import Either, Left, Right
from pymonad.maybe import Just
from mempalace_backfill.alias import Error


@final
class StderrSink:
    def write(self, text: str) -> Either[Error, None]:
        try:
            sys.stderr.write(text)
            sys.stderr.flush()
            return Right(None)
        except Exception as e:
            return Left(Error(f"Failed to write to stderr: {str(e)}", Just(e)))
