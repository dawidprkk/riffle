"""Fixtures that talk to live services. Run with: make test-integration"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from clickhouse_connect.driver.client import Client

from riffle.config import Settings
from riffle.db import new_client

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def live_settings() -> Settings:
    return Settings()


@pytest.fixture(scope="session")
def ch(live_settings: Settings) -> Iterator[Client]:
    client = new_client(live_settings)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture(scope="session")
def proxy_url(live_settings: Settings) -> str:
    return live_settings.redpanda_proxy_url.rstrip("/")
