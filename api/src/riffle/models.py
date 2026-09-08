"""Response models. Every endpoint returns one of these, never a bare dict."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Health(BaseModel):
    status: str = Field(description="ok when the process is serving")
    version: str


class PipelineHealth(BaseModel):
    """What the freshness indicator in the UI reads on every screen."""

    status: str = Field(description="ok, degraded, or unavailable")
    clickhouse_reachable: bool
    raw_events: int = Field(description="rows in events_raw")
    dead_letter_events: int = Field(description="rows the Kafka engine could not parse")
    last_event_ts: datetime | None = Field(default=None, description="newest event_ts seen")
    last_ingest_ts: datetime | None = Field(default=None, description="newest arrival")
    ingest_lag_seconds: float | None = Field(
        default=None, description="now minus last_ingest_ts; None when nothing has arrived"
    )
    detail: str | None = None
