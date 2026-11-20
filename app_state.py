"""Application-level state shared by PDF operation controllers."""

from collections.abc import Callable
from pathlib import Path


class AppState:
    """Stores the active file and notifies subscribed controllers on changes."""

    def __init__(self):
        self.current_file: str | None = None
        self._subscribers: list[Callable[[str | None], None]] = []

    def subscribe(self, callback: Callable[[str | None], None]) -> None:
        self._subscribers.append(callback)
        callback(self.current_file)

    def select_file(self, file_path: str) -> None:
        self.current_file = str(Path(file_path))
        for callback in self._subscribers:
            callback(self.current_file)
