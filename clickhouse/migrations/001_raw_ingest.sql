-- 001 — L0 ingest and L1 raw storage.
--
-- Statements are separated by a semicolon at end of line; the runner does not
-- parse SQL, so keep one statement per terminated block.

CREATE TABLE IF NOT EXISTS kafka_subscription_events
(
    event_id            String,
    event_ts            DateTime64(3, 'UTC'),
    app_id              LowCardinality(String),
    customer_id         String,
    subscription_id     String,
    event_type          LowCardinality(String),
    product_id          LowCardinality(String),
    period_type         LowCardinality(String),
    duration            LowCardinality(String),
    store               LowCardinality(String),
    country             LowCardinality(String),
    currency            LowCardinality(String),
    price               Decimal(18, 6),
    price_usd           Decimal(18, 6),
    proceeds_usd        Decimal(18, 6),
    period_start        DateTime64(3, 'UTC'),
    period_end          Nullable(DateTime64(3, 'UTC')),
    cancel_reason       LowCardinality(String),
    acquisition_channel LowCardinality(String)
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'redpanda:9092',
    kafka_topic_list = 'subscription.events.v1',
    kafka_group_name = 'riffle-ingest',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 1,
    kafka_handle_error_mode = 'stream',
    input_format_skip_unknown_fields = 1,
    input_format_null_as_default = 1,
    date_time_input_format = 'best_effort';

-- L1. `event_id` sits in the sort key so a redelivered event collapses on merge;
-- `ingest_ts` is MATERIALIZED rather than DEFAULT so a producer cannot supply it.
CREATE TABLE IF NOT EXISTS events_raw
(
    event_id            String,
    event_ts            DateTime64(3, 'UTC'),
    ingest_ts           DateTime64(3, 'UTC') MATERIALIZED now64(3, 'UTC'),
    app_id              LowCardinality(String),
    customer_id         String,
    subscription_id     String,
    event_type          LowCardinality(String),
    product_id          LowCardinality(String),
    period_type         LowCardinality(String),
    duration            LowCardinality(String),
    store               LowCardinality(String),
    country             LowCardinality(String),
    currency            LowCardinality(String),
    price               Decimal(18, 6),
    price_usd           Decimal(18, 6),
    proceeds_usd        Decimal(18, 6),
    period_start        DateTime64(3, 'UTC'),
    period_end          Nullable(DateTime64(3, 'UTC')),
    cancel_reason       LowCardinality(String),
    acquisition_channel LowCardinality(String)
)
ENGINE = ReplacingMergeTree(ingest_ts)
PARTITION BY toYYYYMM(event_ts)
ORDER BY (app_id, subscription_id, event_ts, event_id);

-- Rows the Kafka engine could not parse. Without this they vanish silently,
-- which is the one failure mode the contract forbids.
CREATE TABLE IF NOT EXISTS events_dead_letter
(
    ingest_ts   DateTime64(3, 'UTC') DEFAULT now64(3, 'UTC'),
    topic       LowCardinality(String),
    partition   UInt64,
    offset      UInt64,
    raw_message String,
    error       String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ingest_ts)
ORDER BY (ingest_ts, topic, partition, offset);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_kafka_to_events_raw TO events_raw AS
SELECT
    event_id, event_ts, app_id, customer_id, subscription_id, event_type,
    product_id, period_type, duration, store, country, currency,
    price, price_usd, proceeds_usd, period_start, period_end,
    cancel_reason, acquisition_channel
FROM kafka_subscription_events
WHERE length(_error) = 0;

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_kafka_to_dead_letter TO events_dead_letter AS
SELECT
    now64(3, 'UTC') AS ingest_ts,
    _topic          AS topic,
    _partition      AS partition,
    _offset         AS offset,
    _raw_message    AS raw_message,
    _error          AS error
FROM kafka_subscription_events
WHERE length(_error) > 0;
