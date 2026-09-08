# Movies Booking App on Databricks

A thin, end-to-end prototype of a movie ticket booking service: browse movies,
pick a theater and showtime, choose assigned seats on a seat map, and book them.
It runs entirely on Databricks: a **Databricks App** (FastAPI + Vue 3) on top of
**Lakebase** (managed Postgres) registered in **Unity Catalog**, with Delta
materialized views, an AI/BI dashboard and a Genie space for analytics, all
deployed with **Databricks Asset Bundles**.

Built for the Databricks Resident Architect take-home exercise.

> **Status (2026-09-08):** deployed and verified on the platform. The full
> booking flow, including the `409` on a seat lost to a race, works on the
> deployed app and the rows are visible in Catalog Explorer. The analytics layer
> (gold materialized views, refresh job, dashboard, Genie space) is deployed by
> the same bundle. 106 backend tests pass without credentials.

---

## Where it runs

| Item | Value |
|------|-------|
| App URL | `https://movies-app-dev-2485046985091381.aws.databricksapps.com` |
| Workspace | `https://dbc-66830d2c-97a4.cloud.databricks.com` (Slalom) |
| Lakebase instance | `movies-app-dev` (CU_1, Postgres 16), database `movies_dev`, schema `movies` |
| Transactional tables (UC) | `movies_app_dev.movies` — the Lakebase database registered as a Unity Catalog catalog |
| Analytics (UC, Delta) | `movies_analytics_dev.movies` — materialized views `showtime_occupancy`, `demand_by_movie_theater_slot`, `revenue_by_day`, refreshed by job `movies-analytics-gold-dev` |
| SQL warehouse | `movies_analytics` (serverless, 2X-Small) |
| AI/BI dashboard | `Movies — live operations and demand` |
| Genie space | `Movies — cinema demand` |
| Bundle | `movies_app_bundle`, target `dev`, direct engine |

---

## What you can do

**In the app**

1. Browse the movies playing this week.
2. Pick a theater and one of its showtimes.
3. See the auditorium seat map with live availability (standard, premium and
   accessible seats; booked seats greyed out).
4. Select one or more seats, enter a name and email, and book.
5. Get a confirmation with a booking id. The booking is committed in Lakebase
   and visible in Unity Catalog.
6. Book the same seats again and get a `409 Conflict` listing the taken seats.
   The database's unique constraint rejects it, not application code.

No login and no payment: both are out of scope for the exercise.

**In Databricks**

7. Watch auditoriums fill on the **AI/BI dashboard**. Its live page queries the
   Lakebase tables through their Unity Catalog registration, so a seat booked in
   the app shows up on the next refresh with no pipeline in between. Its second
   page reads the Delta materialized views for two weeks of settled demand.
8. Ask the **Genie space** a programming question in plain language, such as
   *"where and for which movies should we open new functions?"*, and get back
   movie, theater, time slot and sample size.

The seed data carries a deliberate demand pattern (popular titles, prime slots,
weekend bumps, two under-served gaps) rather than uniform noise, so the analytics
layer has something real to find. It discovers the signal; it is never told
where it is.

---

## Architecture in one paragraph

One Databricks App serves the Vue SPA and the FastAPI API. The API talks to
Lakebase over the Postgres protocol as the app's own service principal, with a
pooled connection and a short-lived OAuth token. Lakebase is the system of
record because assigned-seat booking needs enforced uniqueness, row locks and
millisecond commits. The same database is registered in Unity Catalog, which is
how the dashboard's live page reads it with no ETL, and how a bundle job builds
Delta materialized views for the demand page and Genie. Every resource, from the
Lakebase instance to the Genie space, is declared in one Asset Bundle.

The full picture, including the request lifecycle, the booking transaction and
the Lakebase-to-lakehouse data flow, is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Repository layout

```
dbx-movies-app/
├── README.md                       this file
├── CLAUDE.md                       working notes for AI-assisted development
├── docs/                           ARCHITECTURE, DATA_MODEL, DECISIONS, DEMO_SCRIPT, AI_USAGE_LOG
└── movies_app_bundle/              Databricks Asset Bundle (direct engine)
    ├── databricks.yml              variables and the dev target
    ├── Makefile                    deploy / release / start / stop / seed / reseed
    ├── resources/                  lakebase, lakehouse, app, analytics_job, analytics_ui
    ├── src/seed/                   ddl.sql, seed_lakebase.py, check_connection.py
    ├── src/analytics/              one SQL file per gold materialized view
    ├── src/dashboards/             movies_operations.lvdash.json
    ├── src/genie/                  movies_demand.geniespace.json
    └── movies_app/                 the Databricks App (source_code_path)
        ├── app.yaml                start command; env comes from resources/app.yml
        ├── package.json            build script the Apps runtime runs at deploy
        ├── backend/                FastAPI: routers, services, db, models
        ├── frontend/               Vue 3 + Vite + TypeScript
        └── tests/                  106 pytest cases, no credentials needed
```

---

## Run it

### Prerequisites

- Databricks CLI 1.15 or newer, with a profile named `movies` for the target
  workspace. The bundle's `dev` target references that profile.
- Python 3.11 with `databricks-sdk` and `psycopg[binary]` to seed the database.
- Node 20 or newer only for local frontend development. The SPA is built on the
  Databricks Apps runtime at deploy time, so no local build is needed to deploy.
- Permission to create a Lakebase instance, catalogs, a SQL warehouse and an app
  in the workspace.

### Deploy to Databricks

From `movies_app_bundle/`:

```bash
make release
```

That validates and deploys every bundle resource, then starts a new app
deployment (the runtime runs `npm install`, `pip install` and `npm run build`
before starting the server). The first deploy provisions the Lakebase instance,
which takes a few minutes. Then seed the database and build the analytics layer:

```bash
make seed
```

```bash
databricks bundle run analytics_job -t dev
```

`make seed` applies the schema, loads deterministic fake data and grants the
app's service principal access to the tables. `make reseed` truncates and
reloads; showtimes are generated relative to the run date, so re-seed when the
seven-day window has drifted, then re-run the analytics job.

The Lakebase instance and the app are stopped between sessions with `make stop`
and started with `make start`, which waits for the instance to become available
before starting the app. Deploy only while the instance is running: an app
update has to reach the database endpoint, so a deploy against a stopped or
starting instance fails.

### Recreating from scratch

`databricks bundle destroy` deletes the Lakebase instance and its data, both
catalogs, the warehouse, the app, the job, the dashboard and the Genie space.
To rebuild: deploy, wait for the Lakebase instance, `make seed`, then run the
analytics job. Every resource keeps its name, since names come from bundle
variables and the target, but every id and the app's service principal are
new. The seed target resolves the new service principal itself. The dashboard
and Genie definitions reference the catalogs by name, so they need editing only
if the target or the catalog variables are renamed.

### Run locally

From `movies_app_bundle/movies_app/`:

```bash
make setup && make run_back
```

```bash
make run_front
```

The backend serves `http://localhost:8000`; the Vite dev server on
`http://localhost:5173` proxies `/api` to it. Locally the backend authenticates
to Lakebase as you through the CLI profile; on the platform it authenticates as
the app's service principal. Same code path. `make test` runs the backend suite
with the database layer stubbed, so it needs no credentials.

---

## Assumptions and scope cuts

| Area | Assumption |
|------|-----------|
| Users | No authentication; a booking records a name and email |
| Payments | None; a booking is confirmed immediately |
| Pricing | Per showtime `standard` and `premium` prices; `accessible` seats priced as standard |
| Seat holds | No temporary holds or timers; the booking transaction is the reservation |
| Cancellations | Cut (ADR-007). The schema supports it, no endpoint ships |
| Theaters | Several theaters with one or two auditoriums each; one auditorium per showtime |
| Currency / time | USD; timestamps stored and shown in UTC |
| Environments | One `dev` target. Staging and prod would add a service-principal deployer and a `mode: production` target |
| Data | Seeded, deterministic fake data over a 21-day window: 14 days of history plus 7 bookable days |

---

## Taking it to millions of users

- **Lakebase capacity.** Scale the instance (CU_1 to CU_8), add readable
  secondaries for seat-map reads, use child instances for staging branches. Add
  a `seat_holds` table with expiry for checkout timers and idempotency keys on
  booking requests.
- **Reference data from the lakehouse.** Curate movies, theaters and schedules
  in Delta and push them into Lakebase with synced tables, so the app only
  writes bookings.
- **Analytics.** Lakeflow Declarative Pipelines from bronze to gold, with the
  dashboard and Genie already reading governed materialized views over the
  Unity Catalog registration of the Lakebase database.
- **API tier.** Pooling with token refresh is already in place. What remains is
  a stateless API behind a CDN, horizontal scaling across app instances and
  per-client rate limiting.
- **Operations.** Unity Catalog audit logs and system tables for observability,
  regional Lakebase instances for multi-region, and bundles promoted from dev
  through staging to prod by a service principal.

---

## How AI was used

The exercise asks for AI as a force multiplier. The running log of what was
generated, what was corrected by hand and the rough split is in
[docs/AI_USAGE_LOG.md](docs/AI_USAGE_LOG.md). In short: AI drafted the
architecture options, the bundle resources, the schema and seed data, most of
the backend and frontend code, and the docs. The human set the scope, chose
Lakebase over Delta for the transactional path, defined naming and bundle
structure, reviewed every Databricks resource before deploying, and validated
the booking flow on the platform.

---

## Documentation

| Document | What it covers |
|----------|----------------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Databricks services in use, app architecture, request lifecycle, booking transaction, Lakebase-to-lakehouse data flow |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | ER diagram, the enforced constraints and why, query shapes, seed data |
| [docs/DECISIONS.md](docs/DECISIONS.md) | ADR-001 to ADR-009, the trade-offs behind each choice |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | The live demo path, pre-flight checklist and fallbacks |
| [docs/AI_USAGE_LOG.md](docs/AI_USAGE_LOG.md) | Where AI helped and where the human intervened, per phase |
