# Riffle — design

**Status:** approved, in implementation
**Date:** 2026-09-08

A real-time subscription analytics platform: Redpanda into ClickHouse, four dashboards, and
an honest answer about which numbers actually need to be fresh.

---

## 0. Scope

Riffle ingests a stream of subscription lifecycle events, models them into subscription
periods inside ClickHouse, and serves four dashboards over the result. The event generator
is a **separate project**; the contract between the two lives here, versioned, and is the
first thing built.

The metric surface is modelled on what a subscription-infrastructure company puts in front
of app developers. Each surface was chosen for the query that is genuinely hard to get
right, not for the chart that is easy to draw.

| Surface | The hard part |
|---|---|
| Revenue & MRR | Normalising MRR across weekly, monthly, annual and lifetime SKUs, and splitting movement into new, expansion, contraction, churned and reactivated |
| Trial funnel & churn | Keeping numerator and denominator on the same cohort, and separating voluntary churn from involuntary billing failure and grace-period recovery |
| Cohort retention & LTV | Retention curves sliced by product, country and store without the query melting |
| Live operations | Nothing, analytically. Its job is to make the streaming architecture visible |

### The decision this design turns on

MRR and retention do not benefit from real time. A retention curve recomputed every four
seconds is indistinguishable from one recomputed hourly, and pretending otherwise costs
correctness: refunds arrive weeks late, cancellations get backdated, grace periods resolve
after the billing period closes. Every one of those rewrites the past.

So Riffle runs two paths. A thin incremental path keeps the live view seconds-fresh. A
refreshable path recomputes the analytical tables every one to five minutes, which absorbs
retroactive events structurally instead of by cleverness. The live tables are a ticker; the
derived tables are the record.

**Alternatives considered.** A pure incremental cascade (`AggregatingMergeTree` +
`argMax` folding) is the most ClickHouse-native option and has the tightest freshness
story, but expressing the subscription state machine in incremental MV SQL gets awkward
around grace periods and mid-period plan changes. A stateful Python consumer owning the
state machine gives the cleanest, most testable logic, but moves the interesting work out
of the database and adds a service that must be checkpointed and restarted correctly.

---

## 1. Event contract

Published from this repo as JSON Schema in `contracts/`, on topic
`subscription.events.v1`, encoded `JSONEachRow`. The generator depends on it; this project
owns it. See `contracts/subscription-event.schema.json` for the authoritative definition
and `contracts/examples/` for payloads that CI validates against it.

Event types: `INITIAL_PURCHASE`, `TRIAL_STARTED`, `TRIAL_CONVERTED`, `TRIAL_CANCELLED`,
`RENEWAL`, `CANCELLATION`, `UNCANCELLATION`, `BILLING_ISSUE`, `GRACE_PERIOD_ENTERED`,
`GRACE_PERIOD_RECOVERED`, `EXPIRATION`, `PRODUCT_CHANGE`, `REFUND`, `TRANSFER`.

The contract deliberately demands the difficult version of the world: delivery is
**at-least-once and unordered**, and an event may arrive long after its `event_ts`.
Absorbing that is Riffle's job, not the generator's — which is what makes the pipeline
worth building.

---

## 2. ClickHouse layers

| Layer | Table | Engine and keys | Freshness |
|---|---|---|---|
| L0 | `kafka_subscription_events` | Kafka engine, `JSONEachRow`, one consumer group. Never queried directly. | transient |
| L1 | `events_raw` | `ReplacingMergeTree(ingest_ts)`, `PARTITION BY toYYYYMM(event_ts)`, `ORDER BY (app_id, subscription_id, event_ts, event_id)` | on insert |
| L1 | `events_dead_letter` | `MergeTree`. Rows the Kafka engine could not parse. | on insert |
| L2 | `subscription_periods` | Refreshable MV → `ReplacingMergeTree`, one row per `(app_id, subscription_id, period_start)` | 1 min |
| L3 | `mrr_daily`, `mrr_movement_daily`, `trial_funnel_daily`, `retention_cohort`, `ltv_cohort` | Refreshable MVs → `AggregatingMergeTree`. All read L2, never L1. | 1–5 min |
| L4 | `live_events_1s`, `live_purchases`, `ingest_lag` | Incremental MVs → `SummingMergeTree`, TTL 6 h / 1 h | seconds |

**L1 detail.** `event_id` sits in the sort key so a redelivered event collapses on merge.
`ingest_ts DateTime64(3) MATERIALIZED now64(3)` is materialized rather than default, so a
producer cannot supply or forge it — which makes it a trustworthy basis for lag and for
any future arrival-time cutover.

**L2 detail.** The state machine, expressed as window functions over `events_raw FINAL`:
`is_trial`, `state` (ACTIVE / GRACE / CANCELLED / CHURNED / REFUNDED), `churned_at`,
`churn_type`, `refunded`, `cohort_month`, `is_first_period`, and
`mrr_usd = proceeds_usd * 30.0 / duration_days`. Lifetime purchases are excluded from MRR
and reported separately — otherwise they wreck the chart. Because L2 is a full recompute
over a bounded window rather than an incremental fold, retroactive events are free.

**L3 detail.** The funnel is keyed by cohort day so numerator and denominator describe the
same users. Retention is `(app_id, cohort_month, months_since, product_id, country)` →
survivors and retained MRR.

**Stated trade-off.** L4 can double-count a duplicate for a few seconds. That is correct
for a live ticker and wrong for a financial number — accuracy is L2 and L3's job, and the
README says so. Naming which layer answers which question is the difference between a demo
and a design.

---

## 3. Query API

FastAPI with `clickhouse-connect`, one query module per dashboard, parametrised queries
only — no f-string SQL — and Pydantic response models. No application-level cache: the
refreshable views *are* the cache.

| Endpoint | Reads | Serves |
|---|---|---|
| `GET /api/apps` | L2 | Filter bar population |
| `GET /api/mrr` | `mrr_daily` | MRR over time, grouped by product, store or country |
| `GET /api/mrr/movement` | `mrr_movement_daily` | New / expansion / contraction / churned / reactivated |
| `GET /api/funnel/trials` | `trial_funnel_daily` | Trial → conversion → renewal → churn, cohort-aligned |
| `GET /api/cohorts/retention` | `retention_cohort` | Retention curves by subscribers or by MRR |
| `GET /api/cohorts/ltv` | `ltv_cohort` | Cumulative realised proceeds per cohort |
| `GET /api/live/stream` | L4 | SSE at 1 Hz — counters and newest purchases |
| `GET /api/health/pipeline` | `ingest_lag` + system | Ingest lag, MV refresh times, consumer lag |

`/api/health/pipeline` answers 200 with a degraded status rather than an error. The
freshness indicator sits on every screen, and a dashboard that cannot say "the pipeline is
down" is worse than one that can.

---

## 4. Frontend

React, TypeScript, Vite, TanStack Query, Recharts. Four routes for the four surfaces, plus
a global filter bar — date range, app, product, store, country — whose state lives in the
URL, so every view is a shareable link.

The live view drives off `EventSource`. On every screen, a small freshness indicator reads
`/api/health/pipeline` and reports *data as of 14s ago*, which advertises the architecture
without a single chart having to animate.

---

## 5. Testing

- **Unit, no database.** MRR normalisation across durations, cohort assignment, churn
  classification, migration discovery and statement splitting — pure functions, fast.
- **Integration, live services.** Each materialised view's SQL run against a fixed event
  fixture, asserting exact numbers rather than shapes.
- **`make demo`.** Compose up, replay a fixture stream, land on a populated dashboard.

### The adversarial set

Small, high-signal, and the part a reviewer will actually read. Each is a scenario the
naive pipeline fails:

- A duplicate delivery does not double MRR.
- A refund arriving after the period closed reduces *the right day's* MRR once the view
  refreshes.
- A backdated cancellation lands churn on the day it happened, not the day it was received.
- A grace period that recovers is never counted as churn.
- Events replayed out of order produce the same tables as events replayed in order.
- A malformed message reaches `events_dead_letter` rather than vanishing.

---

## 6. Delivery

`docker-compose.yml` brings up Redpanda, ClickHouse, the API and the web app; the app
services sit behind a compose profile so `make up` stays fast. ClickHouse is pinned to the 25.8 LTS line, where refreshable materialized views are
generally available. `clickhouse/migrations/` holds numbered SQL applied by `riffle-migrate`, which refuses to run if an already-applied
migration changed on disk. Deployment stays compose-first; a public URL via ClickHouse
Cloud's free tier plus Fly.io is a later option, not scope.

| Milestone | Contents |
|---|---|
| **M1** | Ingest spine: compose, Kafka engine table, `events_raw`, dead letter, smoke tests |
| **M2** | `subscription_periods` plus the MRR dashboard — one cut through every layer |
| **M3** | Live operations view: L4 incremental views, SSE, freshness indicator |
| **M4** | Trial funnel and churn: cohort-aligned, voluntary vs. involuntary, grace recovery |
| **M5** | Cohort retention and LTV |
| **M6** | Adversarial suite, diagram, demo recording |
