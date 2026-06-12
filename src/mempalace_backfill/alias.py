from typing import final
from pymonad.maybe import Maybe, Nothing


@final
class Error:
    def __init__(self, message: str, exception: Maybe[Exception] = Nothing) -> None:
        self.message = message
        self.exception = exception

    def __str__(self) -> str:
        return f"Error: {self.message}" + (f" (Exception: {self.exception})" if self.exception.is_just() else "")

    def __repr__(self) -> str:
        return f"Error(message={self.message!r}, exception={self.exception!r})"
