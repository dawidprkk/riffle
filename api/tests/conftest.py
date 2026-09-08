"""Fakes shared by the unit tests. Nothing here touches a live service."""

from __future__ import annotations

from typing import Any

import pytest

from riffle.config import Settings


class FakeResult:
    def __init__(self, rows: list[list[Any]]) -> None:
        self.result_rows = rows


class FakeClickHouse:
    """The slice of the ClickHouse client the API actually uses."""

    def __init__(self, rows: list[list[Any]] | None = None, error: Exception | None = None) -> None:
        self._rows = rows or []
        self._error = error
        self.closed = False

    def query(self, *_args: Any, **_kwargs: Any) -> FakeResult:
        if self._error is not None:
            raise self._error
        return FakeResult(self._rows)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def settings() -> Settings:
    return Settings(
        clickhouse_host="unused",
        clickhouse_database="riffle",
        api_cors_origins="http://localhost:5173",
    )
