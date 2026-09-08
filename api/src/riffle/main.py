"""FastAPI application.

The pipeline-health endpoint deliberately answers 200 with a degraded status
rather than an error: the freshness indicator sits on every screen, and a
dashboard that cannot say "the pipeline is down" is worse than one that can.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from clickhouse_connect.driver.client import Client
from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from riffle import __version__
from riffle.config import Settings, get_settings
from riffle.db import new_client
from riffle.models import Health, PipelineHealth

logger = logging.getLogger("riffle")

PIPELINE_QUERY = """
SELECT
    count()                  AS raw_events,
    maxOrNull(event_ts)      AS last_event_ts,
    maxOrNull(ingest_ts)     AS last_ingest_ts,
    (SELECT count() FROM events_dead_letter) AS dead_letter_events
FROM events_raw
"""

router = APIRouter(prefix="/api")


def _as_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@router.get("/health", response_model=Health, summary="Liveness")
def health() -> Health:
    return Health(status="ok", version=__version__)


@router.get("/health/pipeline", response_model=PipelineHealth, summary="Ingest freshness")
def pipeline_health(request: Request) -> PipelineHealth:
    client = getattr(request.app.state, "clickhouse", None)
    if client is None:
        return PipelineHealth(
            status="unavailable",
            clickhouse_reachable=False,
            raw_events=0,
            dead_letter_events=0,
            detail="no ClickHouse connection",
        )

    try:
        rows = client.query(PIPELINE_QUERY).result_rows
    # Any query failure is reported as degraded rather than raised: see the module docstring.
    except Exception as error:
        logger.warning("pipeline health query failed: %s", error)
        return PipelineHealth(
            status="degraded",
            clickhouse_reachable=True,
            raw_events=0,
            dead_letter_events=0,
            detail=str(error)[:300],
        )

    raw_events, last_event_ts, last_ingest_ts, dead_letter_events = rows[0]
    ingest_ts = _as_utc(last_ingest_ts)
    lag = (datetime.now(UTC) - ingest_ts).total_seconds() if ingest_ts else None

    return PipelineHealth(
        status="ok",
        clickhouse_reachable=True,
        raw_events=int(raw_events),
        dead_letter_events=int(dead_letter_events),
        last_event_ts=_as_utc(last_event_ts),
        last_ingest_ts=ingest_ts,
        ingest_lag_seconds=round(lag, 3) if lag is not None else None,
    )


def create_app(
    settings: Settings | None = None,
    *,
    client_factory: Callable[[Settings], Client] | None = None,
) -> FastAPI:
    """Build the app. `client_factory` exists so tests need no live ClickHouse."""
    resolved = settings or get_settings()
    connect = client_factory or new_client

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            app.state.clickhouse = connect(resolved)
            logger.info("connected to ClickHouse at %s", resolved.clickhouse_host)
        # A missing database must not stop the process: the health page still has to render.
        except Exception as error:
            logger.warning("could not connect to ClickHouse: %s", error)
            app.state.clickhouse = None
        try:
            yield
        finally:
            if getattr(app.state, "clickhouse", None) is not None:
                app.state.clickhouse.close()

    app = FastAPI(
        title="Riffle",
        version=__version__,
        summary="Real-time subscription analytics",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
