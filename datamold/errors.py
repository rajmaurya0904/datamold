"""Exception types shared across datamold."""

from __future__ import annotations


class DatamoldError(Exception):
    """Base class for all expected datamold failures."""


class MappingSyntaxError(DatamoldError):
    """The mapping text could not be parsed."""

    def __init__(self, message: str, line: int | None = None):
        self.line = line
        prefix = f"mapping line {line}: " if line else "mapping: "
        super().__init__(prefix + message)


class RowError(DatamoldError):
    """A single CSV row could not be converted."""

    def __init__(self, message: str, row: int):
        self.row = row
        super().__init__(f"row {row}: {message}")
