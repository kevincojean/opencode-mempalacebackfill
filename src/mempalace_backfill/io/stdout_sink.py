import sys
from typing import final
from pymonad.either import Either, Left, Right
from pymonad.maybe import Just
from mempalace_backfill.alias import Error


@final
class StdoutSink:
    def write(self, text: str) -> Either[Error, None]:
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
            return Right(None)
        except Exception as e:
            return Left(Error(f"Failed to write to stdout: {str(e)}", Just(e)))

    def write_table(self, headers: list[str], rows: list[list]) -> Either[Error, None]:
        try:
            if not headers:
                return Right(None)

            # Simple pipe-delimited table formatting
            header_str = " | ".join(headers)
            separator = "-" * len(header_str)
            
            output = [header_str, separator]
            for row in rows:
                output.append(" | ".join(map(str, row)))
            
            sys.stdout.write("\n".join(output) + "\n")
            sys.stdout.flush()
            return Right(None)
        except Exception as e:
            return Left(Error(f"Failed to write table to stdout: {str(e)}", Just(e)))
