import shutil
from pathlib import Path
from typing import final
from pymonad.either import Either, Left, Right
from pymonad.maybe import Just

from mempalace_backfill.alias import Error


@final
class CleanService:
    @staticmethod
    def clean(output_dir: str, state_file: str) -> Either[Error, int]:
        """Remove all contents from output_dir and delete state_file.

        Returns Right with the number of items removed from output_dir
        (does not count the state file in the total).
        """
        try:
            output_path = Path(output_dir)
            state_path = Path(state_file)

            if output_path.exists() and not output_path.is_dir():
                return Left(Error(f"Not a directory: {output_dir}"))

            count = 0
            if output_path.is_dir():
                for entry in output_path.iterdir():
                    if entry.is_dir():
                        shutil.rmtree(str(entry))
                    else:
                        entry.unlink()
                    count += 1

            if state_path.exists():
                state_path.unlink()

            return Right(count)
        except Exception as e:
            return Left(Error(f"Clean failed: {str(e)}", Just(e)))
