from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from riffle.config import Settings
from riffle.main import create_app
from tests.conftest import FakeClickHouse


def _app(settings: Settings, fake: FakeClickHouse | None) -> tuple[object, TestClient]:
    def factory(_: Settings) -> FakeClickHouse:
        if fake is None:
            raise ConnectionError("clickhouse unreachable")
        return fake

    app = create_app(settings, client_factory=factory)  # type: ignore[arg-type]
    return app, TestClient(app)


def test_liveness_reports_ok(settings: Settings) -> None:
    _, client = _app(settings, FakeClickHouse())
    with client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_pipeline_health_reports_counts_and_lag(settings: Settings) -> None:
    ingested = datetime.now(UTC) - timedelta(seconds=4)
    fake = FakeClickHouse(rows=[[1234, datetime(2026, 9, 8, 12, 0, tzinfo=UTC), ingested, 2]])
    _, client = _app(settings, fake)
    with client:
        body = client.get("/api/health/pipeline").json()

    assert body["status"] == "ok"
    assert body["raw_events"] == 1234
    assert body["dead_letter_events"] == 2
    assert 3.0 <= body["ingest_lag_seconds"] <= 10.0


def test_pipeline_health_reports_empty_pipeline_without_a_lag(settings: Settings) -> None:
    fake = FakeClickHouse(rows=[[0, None, None, 0]])
    _, client = _app(settings, fake)
    with client:
        body = client.get("/api/health/pipeline").json()

    assert body["status"] == "ok"
    assert body["raw_events"] == 0
    assert body["ingest_lag_seconds"] is None


def test_pipeline_health_stays_200_when_clickhouse_is_down(settings: Settings) -> None:
    """The freshness indicator must still render, saying the pipeline is down."""
    _, client = _app(settings, None)
    with client:
        response = client.get("/api/health/pipeline")

    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["clickhouse_reachable"] is False


def test_pipeline_health_degrades_when_the_query_fails(settings: Settings) -> None:
    fake = FakeClickHouse(error=RuntimeError("table events_raw does not exist"))
    _, client = _app(settings, fake)
    with client:
        body = client.get("/api/health/pipeline").json()

    assert body["status"] == "degraded"
    assert "events_raw" in body["detail"]
