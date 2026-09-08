"""ClickHouse client construction and the FastAPI dependency that hands it out."""

from __future__ import annotations

from typing import Annotated

import clickhouse_connect
from clickhouse_connect.driver.client import Client
from fastapi import Depends, Request

from riffle.config import Settings


def new_client(settings: Settings, *, database: str | None = None) -> Client:
    """Open a ClickHouse client. Pass `database` to override the configured one."""
    return clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=settings.clickhouse_database if database is None else database,
        connect_timeout=10,
        send_receive_timeout=60,
    )


def get_client(request: Request) -> Client:
    client: Client = request.app.state.clickhouse
    return client


ClickHouse = Annotated[Client, Depends(get_client)]
