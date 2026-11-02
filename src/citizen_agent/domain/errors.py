"""Domain error type carried across the service and MCP boundary."""

from __future__ import annotations

from .enums import ErrorCode


class DomainError(Exception):
    """An anticipated, structured failure.

    Messages are short and never contain another citizen's data.
    """

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
