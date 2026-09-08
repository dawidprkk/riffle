"""M1: an event published to Redpanda arrives in events_raw, exactly once."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import httpx
import pytest
from clickhouse_connect.driver.client import Client

from riffle.config import Settings
from tests.integration.conftest import REPO_ROOT

pytestmark = pytest.mark.integration

PROXY_CONTENT_TYPE = "application/vnd.kafka.json.v2+json"
EXAMPLE = REPO_ROOT / "contracts" / "examples" / "initial_purchase.json"


def _event(**overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = json.loads(EXAMPLE.read_text())
    event["event_id"] = f"test-{uuid.uuid4()}"
    event.update(overrides)
    return event


def _publish(proxy_url: str, topic: str, *events: dict[str, Any]) -> None:
    response = httpx.post(
        f"{proxy_url}/topics/{topic}",
        headers={"Content-Type": PROXY_CONTENT_TYPE},
        json={"records": [{"value": event} for event in events]},
        timeout=30.0,
    )
    response.raise_for_status()

    # The proxy answers 200 even when a record was rejected, reporting the failure
    # per offset instead. Trusting the status code alone silently drops events.
    rejected = [offset for offset in response.json().get("offsets", []) if offset.get("error_code")]
    if rejected:
        raise AssertionError(f"redpanda rejected {len(rejected)} record(s): {rejected}")


def _await_rows(ch: Client, event_id: str, *, final: bool, timeout: float = 60.0) -> int:
    """Poll until the event shows up, then return how many rows it occupies."""
    table = "events_raw FINAL" if final else "events_raw"
    deadline = time.monotonic() + timeout
    count = 0
    while time.monotonic() < deadline:
        count = int(
            ch.query(
                f"SELECT count() FROM {table} WHERE event_id = {{id:String}}",
                parameters={"id": event_id},
            ).result_rows[0][0]
        )
        if count:
            return count
        time.sleep(1.0)
    raise AssertionError(f"{event_id} never arrived in events_raw within {timeout:.0f}s")


def test_published_event_lands_in_events_raw(
    ch: Client, proxy_url: str, live_settings: Settings
) -> None:
    event = _event()
    _publish(proxy_url, live_settings.riffle_topic, event)

    assert _await_rows(ch, event["event_id"], final=True) == 1

    stored = ch.query(
        "SELECT app_id, event_type, proceeds_usd, ingest_ts >= event_ts AS ordered "
        "FROM events_raw FINAL WHERE event_id = {id:String}",
        parameters={"id": event["event_id"]},
    ).result_rows[0]
    assert stored[0] == event["app_id"]
    assert stored[1] == event["event_type"]
    assert float(stored[2]) == pytest.approx(event["proceeds_usd"])
    assert stored[3] == 1, "ingest_ts is stamped on arrival, never before the event happened"


def test_duplicate_delivery_collapses_to_one_row(
    ch: Client, proxy_url: str, live_settings: Settings
) -> None:
    """At-least-once delivery is the contract; event_id in the sort key is the answer."""
    event = _event()
    _publish(proxy_url, live_settings.riffle_topic, event, event, event)
    _await_rows(ch, event["event_id"], final=False)

    ch.command("OPTIMIZE TABLE events_raw FINAL")
    deduplicated = int(
        ch.query(
            "SELECT count() FROM events_raw FINAL WHERE event_id = {id:String}",
            parameters={"id": event["event_id"]},
        ).result_rows[0][0]
    )
    assert deduplicated == 1


def test_unparseable_message_goes_to_the_dead_letter_table(
    ch: Client, proxy_url: str, live_settings: Settings
) -> None:
    """Nothing vanishes silently — a malformed event is durably categorised."""
    before = int(ch.query("SELECT count() FROM events_dead_letter").result_rows[0][0])
    malformed = {"event_id": "broken", "event_ts": "not-a-date"}
    _publish(proxy_url, live_settings.riffle_topic, malformed)

    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        after = int(ch.query("SELECT count() FROM events_dead_letter").result_rows[0][0])
        if after > before:
            return
        time.sleep(1.0)
    raise AssertionError("malformed event never reached events_dead_letter")
