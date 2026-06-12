import os
import shutil
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
            if os.path.exists(output_dir) and not os.path.isdir(output_dir):
                return Left(Error(f"Not a directory: {output_dir}"))

            count = 0
            if os.path.isdir(output_dir):
                for entry in os.listdir(output_dir):
                    entry_path = os.path.join(output_dir, entry)
                    if os.path.isdir(entry_path):
                        shutil.rmtree(entry_path)
                    else:
                        os.unlink(entry_path)
                    count += 1

            if os.path.exists(state_file):
                os.remove(state_file)

            return Right(count)
        except Exception as e:
            return Left(Error(f"Clean failed: {str(e)}", Just(e)))
