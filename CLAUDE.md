# CLAUDE.md — Movie Ticket Booking App on Databricks

Handoff document for Claude. Single source of truth for scope, decisions and
build order. Update it when a decision changes.

---

## 1. Mission

Take-home exercise for a **Databricks Resident Architect (Slalom)** interview.
The panel is Databricks engineers; the user (Rafael Escoto) demos live and
defends the design end to end.

**The brief:** a working prototype of a movie ticket booking app for millions of
global users — browse movies and showtimes, pick a theater, view a seat map,
book one or more assigned seats.

| # | Requirement | How we satisfy it |
|---|-------------|-------------------|
| R1 | Deployed as a **Databricks App**; frontend + backend served from it | One app: FastAPI serves the API and the Vue SPA |
| R2 | **Data layer on Databricks**: real UC / Delta schema, several tables | **Lakebase** (managed Postgres) holds the 7 transactional tables, registered in UC as `movies_app_dev`; Delta gold tables in `movies_analytics_dev.movies` |
| R3 | Browse movies/showtimes, pick theater, seat map, book ≥1 assigned seats | Vue 3 SPA, 4 routes (§4.5) |
| R4 | Backend API + persistent store | FastAPI → Lakebase over the Postgres protocol (psycopg), OAuth as the app's service principal |
| R5 | Panel gets code + Databricks assets | README lists workspace, catalogs, warehouse, app URL, bundle resources |
| R6 | Short README with location and run/deploy instructions | `README.md` |
| R7 | Explain data model, API design, trade-offs, scale to millions | `docs/` (§9) |
| R8 | "AI as a force multiplier": where AI helped, where the human intervened | `docs/AI_USAGE_LOG.md` |

**Ground rules:** scope ruthlessly (a thin working skeleton beats a broad broken
one), seed fake data, no real payments or auth, state assumptions where the
prompt is vague, stub what cannot run on-platform and explain how it would map.
Evaluation: "a builder who ships, thinks in trade-offs, and can defend a design".

**Time budget:** 4–6 focused hours. **Interview: Wednesday 2026-09-09** (live demo).

---

## 2. Current state (2026-09-07)

**Deployed by the bundle** (direct engine, CLI 1.15.0), verified with
`bundle summary -t dev`. Details in §10.

| Resource | Key | File |
|----------|-----|------|
| Lakebase instance `movies-app-dev` | `database_instances.movies_db` | `resources/lakebase.yml` |
| UC registration → catalog `movies_app_dev` | `database_catalogs.catalog_movies_db` | `resources/lakebase.yml` |
| Analytics catalog `movies_analytics_dev` | `catalogs.movies_analytics` | `resources/lakehouse.yml` |
| Analytics schema `movies_analytics_dev.movies` | `schemas.movies` | `resources/lakehouse.yml` |
| SQL warehouse `movies_analytics` | `sql_warehouses.movies_analytics_warehouse` | `resources/lakehouse.yml` |
| App `movies-app-dev` | `apps.movies_app` | `resources/app.yml` |

**Phases 1–5 complete.** App resource + FastAPI skeleton; `src/seed/ddl.sql`
(7 tables, 8 FKs of which 3 composite, 5 unique constraints, 11 checks) and
`src/seed/seed_lakebase.py` applied to the live instance; backend routers,
`booking_service`, and the Vue SPA with all four routes. The full click path —
grid → movie → theater → seat map → book → 409 on a raced seat → confirmation —
is verified **on the deployed app**, and bookings are visible in
`movies_app_dev.movies.booking_seats`. Per-phase verification detail lives in
`docs/AI_USAGE_LOG.md` and `docs/DECISIONS.md`.

Phase 5 also resolved the deployed app's 500s on every `/api/*` call touching
Lakebase. Root cause (ADR-005): the platform does **not** inject `PGHOST`, so
`db.py` fell back to `get_database_instance()` over the workspace API, which
the app SP cannot call. Fix: `PGHOST` via `value_from: lakebase` (now declared
in `resources/app.yml` under `apps.movies_app.config.env`),
plus a psycopg 3 connection-leak fix, `PGPASSWORD` support, step-by-step
`/api/health` diagnostics, and a global exception handler. Connection pooling
followed (ADR-006), which required turning every `/api` handler from
`async def` into `def`. All of this is merged to `main`.

**Phase 6 in progress.** Repository review; the pytest suite went from 7 to 107
cases (routers, app shell, `/api/health`, `db.py`, pool backpressure) with
`pytest.ini` and a `make test` target (108 after B7/B13/B16 follow-ups); a real
bug fixed (the SPA 404 handler
was discarding the routers' 404 details); ADR-006 rewritten after shipping
literal control characters; ADR-007 records cancellation as cut; ADR-008
closes ADR-006 Deferred item 5 — the API threadpool is now sized from
`pg_pool_max` rather than anyio's default, and a saturated pool returns `503`
+ `Retry-After` instead of a `500`.

**Phase 7 complete — the analytics layer (2026-09-07).** ADR-009. Three pieces,
all deployed by the bundle and all verified on the platform:

- **The seed carries a demand signal.** `seed_lakebase.py` was rewritten around
  an explicit `PROGRAMMING` grid and a demand model (movie × slot × theater ×
  weekend, a lead-time curve for unplayed shows, centre-out seat filling,
  backdated `created_at`) over a 21-day window — 14 days of settled history
  plus the 7 bookable days. 357 showtimes, 6,597 bookings, 15,526 sold seats;
  settled shows 42.8% full, upcoming 22.4%. Two gaps in the grid are deliberate
  and are what the Genie question discovers. The old seed booked uniform noise
  on two days only (1.6% fill), which would have left both new surfaces with
  nothing to find.
- **Gold tables + `analytics_job`.** `src/analytics/gold.sql` builds
  `showtime_occupancy` (357), `demand_by_movie_theater_slot` (19) and
  `revenue_by_day` (63) in `movies_analytics_dev.movies`, every table and column
  commented (Genie reads those comments). Catalog names come in as `sql_task`
  parameters via `IDENTIFIER(:param)`; column comments need a second-pass
  `ALTER TABLE` because `CREATE OR REPLACE TABLE ... AS SELECT` rejects an
  inline column schema.
- **Dashboard + Genie space, both as bundle resources** (`resources/analytics_ui.yml`).
  The dashboard's "Live operations" page reads `movies_app_dev.movies` federated
  through UC — a booking appears on refresh with no pipeline — while "Demand &
  programming" reads the Delta gold tables. Genie reads only the gold tables.
  Asked the demo question verbatim it produces the canonical query from its
  instructions and answers with movie + theater + slot + sample size.

**Not built:** `docs/DEMO_SCRIPT.md` (with `docs/img/` screenshots).
`docs/ARCHITECTURE.md` / `docs/SCALE_TO_MILLIONS.md` were **dropped** on
2026-09-07: the README already carries the diagram, the service-choice table
and the scale prose, and its "still to be written" pointers were removed rather
than left aimed at files nobody was going to write before the demo.

**Demo pre-flight — Wednesday 2026-09-09.** The seed of 2026-09-07 covers
2026-09-07 → 2026-09-13, so the 9th is inside the window and nothing expires
before the demo. Still do this on the morning:

1. Re-seed with `--reset` (showtime ids are `now`-relative and
   `/api/showtimes` filters `starts_at > now()`, so the window shrinks daily
   and empties seven days after the last seed; `--reset` also clears test
   bookings so the seat map looks deliberate).
2. **Re-run `analytics_job` immediately after re-seeding.** The gold tables are
   a snapshot: re-seeding moves every showtime and rewrites every booking, so
   until the job runs again the dashboard's *Demand & programming* page and the
   whole Genie space describe yesterday's window. The *Live operations* page is
   federated and needs no rebuild.
3. Start the Lakebase instance and the app compute ≥15 min ahead — both are
   stopped between sessions — and the `movies_analytics` warehouse ≥5 min ahead
   (serverless, ~20 s cold start, 20 min auto-stop). The dashboard's live tiles
   need **both** Lakebase and the warehouse running.
4. Confirm `/api/health` reports `db: connected`, and open the dashboard once so
   the tiles are warm.

Also redeploy if anything is committed after the last `bundle run`: as of
2026-09-07 the deployed app was one commit behind (`af3c891`, the timezone
fix). Harmless — the frontend never sends `?date=` — but do not demo a build
that is not the repo.

### Hazards (live)

1. **Databricks CLI only from WSL Ubuntu 24.04.** The `movies` profile (PAT)
   exists only there. The Windows CLI's profiles point to `dbc-2ba89670-78df`,
   a **client (BioNTech) workspace that must never be used for this project**.
   Wrap every command:
   `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/repos/apps/dbx-movies-app/movies_app_bundle && databricks ..."`
2. **Lakebase costs while running — but do not stop or start it with a deploy.**
   Every `bundle deploy` updates `apps.movies_app`, and an app update makes the
   platform resolve the app's `database` resource by connecting to the Lakebase
   endpoint. So **any deploy fails while the instance is stopped or still
   starting**, with `FAILED_PRECONDITION: ... Endpoint ep-… is disabled. Cannot
   connect to the pg instance`. Stopping via `stopped: true` + deploy "works"
   only in the sense that the instance stops before the app update blows up.

   Start and stop out of band instead, and leave `resources/lakebase.yml` at
   `stopped: false` so a deploy is always safe:

   ```bash
   databricks database update-database-instance movies-app-dev stopped --json '{"name":"movies-app-dev","stopped":true}' -p movies        # stop
   databricks database update-database-instance movies-app-dev stopped --json '{"name":"movies-app-dev","stopped":false}' -p movies  # start
   databricks database get-database-instance movies-app-dev -p movies                             # poll for AVAILABLE
   ```

   **Order on demo morning: start the instance, wait for `AVAILABLE` (~10–15
   min), and only then deploy.** Deploying while it is `STARTING` hits the same
   error. Note `make release` also runs `bundle run movies_app`, which starts app
   compute — never use it to shut things down. `prevent_destroy` is `false` everywhere, so
   `bundle destroy` deletes the instance **and its data** — only the user runs
   it. Renaming the instance recreates it and changes its DNS; on-platform
   `PGHOST` is injected via `valueFrom` (ADR-005) so a rename is handled at
   deploy time, but local runs still resolve through the SDK.
3. **`catalogs` needs the direct engine.** `bundle.engine: direct` is set; do
   not remove it (terraform silently drops the catalog resource).
4. **Git is denied to Claude** (`.claude/settings.json`). The user commits.
5. **Secrets.** `.claude/settings.local.json` holds a Bedrock API key; the WSL
   `~/.databrickscfg` holds a PAT. Never print, copy or reference either.
6. Two unrelated GxP apps exist in the workspace. Leave them alone.

---

## 3. Decisions and assumptions (say these out loud in the demo)

| Topic | Decision | Why / trade-off |
|-------|----------|-----------------|
| Backend | **Python 3.11, FastAPI** | Databricks-native SDK support, Apps docs use Python, user has FastAPI experience |
| Frontend | **Vue 3 + Vite + TypeScript**, vue-router, no state library | TS gives typed API contracts; too small to need Pinia |
| Serving | FastAPI serves `/api/*` **and** the SPA from `frontend/dist`; the SPA is built **on the Apps runtime at deploy time** (ADR-004) | One process, one app, no Node at runtime → predictable startup; no local build, so a stale `dist` cannot reach the platform |
| **System of record** | **Lakebase** (managed Postgres), 7 tables with **enforced** PK/FK/UNIQUE/CHECK | Assigned-seat booking is OLTP: row locks, unique constraints, ms commits. Delta enforces no uniqueness and spans no multi-table transaction |
| Governance | The Postgres database is **registered in Unity Catalog** as `movies_app_dev` | Browsable in Catalog Explorer, queryable from a warehouse — "real schema in UC" without ETL |
| Analytics copy | Delta gold tables in `movies_analytics_dev.movies` built by a bundle job (`sql_task` on `movies_analytics`) reading the Lakebase catalog | Shows the lakehouse side without putting OLTP on Delta. Built in Phase 7 |
| Live vs. historical analytics | **Two paths by temperature** (ADR-009): the dashboard's live page queries `movies_app_dev.movies` federated through UC; the demand page and the whole Genie space read the Delta gold tables | Live tiles need no pipeline at all — the UC registration is the bridge. Genie sees one curated model, so there is exactly one way to compute a metric |
| Seed data | 8 movies, 3 theaters, 5 auditoriums (rows A–J × 12), 4 slots/day over a 21-day window (14 past + 7 future), ~357 showtimes, ~6.6k bookings; deterministic and idempotent. Occupancy follows a **declared demand model**, not uniform noise, with two deliberate under-served gaps | Uniform bookings left the dashboard flat and Genie with nothing to find. The seed plants a signal and the demo says so out loud — the analytics layer discovers it, it is never told |
| AI/BI as code | Dashboard (`.lvdash.json`) and Genie space (`.geniespace.json`) are bundle resources, edited in the repo and round-tripped from the UI with `bundle generate dashboard \| genie-space` | Both surfaces deploy with everything else. Note the asymmetry: Genie validates its export strictly, Lakeview validates nothing (it accepts an invented `widgetType`) |
| Infra as code | **Asset Bundles, direct engine** — every resource in one bundle | Reproducible from the repo; `catalogs` requires the direct engine |
| App → DB auth | App connects as its **own service principal** with an OAuth token from `generate_database_credential`; the `database` app resource (`CAN_CONNECT_AND_CREATE`) creates the Postgres role | No passwords; tokens live ~1 h, refreshed by the backend |
| Double-booking | `UNIQUE (showtime_id, seat_id)` on `booking_seats` + the whole booking in **one transaction**; unique violation → rollback → `409` with the taken seats | The database enforces the invariant; the app only translates errors |
| Seat holds / timers | **Out of scope** (stretch: `seat_holds` with `expires_at` + sweeper) | Not needed for the walking skeleton |
| Cancellations | **Cut** (ADR-007). The schema still supports it: `status` + `cancelled_at` with a CHECK keeping them in step, and `booking_seats` cascades on delete | The UNIQUE constraint lives on `booking_seats`, not on a status-aware partial index, precisely so deleting seat rows frees the seats while the header survives as an audit trail |
| Pricing | Per showtime: `price_standard`, `price_premium`; seat types `standard`/`premium`/`accessible` (accessible priced as standard) | Simple, shows a non-trivial join |
| Theaters | Several theaters, 1–2 auditoriums each; one auditorium per showtime | Enough to show "pick a theater" |
| Auth / payments | None. A booking captures `customer_name` + `customer_email` and is confirmed immediately | Brief excludes both |
| Currency / timezone | USD, UTC, displayed as-is | Avoids i18n work |
| Environments | Single `dev` target. `staging`/`prod` described in README, not built | Time budget |

---

## 4. Architecture

### 4.1 Runtime flow

```
Browser ──HTTPS──▶ Databricks App "movies-app" (FastAPI, $DATABRICKS_APP_PORT)
                     ├── GET /    → static Vue SPA (frontend/dist)
                     └── /api/*   → routers → services → psycopg
                                        │ OAuth token (app SP), sslmode=require
                                        ▼
                          Lakebase "movies-app-dev" · db movies_dev · schema movies
                                        │ registered as a UC catalog
                                        ▼
                          UC: movies_app_dev.movies.*   ← Catalog Explorer, warehouse movies_analytics
                                        │ analytics job (sql_task) — Phase 6
                                        ▼
                          Delta: movies_analytics_dev.movies.{occupancy_by_showtime, revenue_by_day}

Deploy:  bundle deploy            → all resources; uploads movies_app/
         bundle run movies_app    → npm install, pip install, npm run build, then app.yaml command
         seed_lakebase.py         → schema, tables, seed data, grants for the app SP
```

### 4.2 Backend layout (`movies_app_bundle/movies_app/backend/`)

```
serve.py       entrypoint: uvicorn.run(app, host=0.0.0.0, port=DATABRICKS_APP_PORT or 8000)
main.py        FastAPI app, routers, global exception handler, SPA mount + history fallback
config.py      Settings from env: LAKEBASE_*, PGHOST/PGPORT/PGUSER/PGPASSWORD/PGSSLMODE if injected
db.py          connection factory, query() / execute(), transaction() context manager
models.py      Pydantic v2 request/response models
routers/       catalog.py (movies, theaters, showtimes) · seats.py (seat map) · bookings.py
services/      booking_service.py — the §4.4 transaction
```

**`db.py` contract.** `psycopg` v3. Credentials: `WorkspaceClient()` (picks up
the app's `DATABRICKS_CLIENT_ID`/`SECRET`, or locally
`DATABRICKS_CONFIG_PROFILE=movies`) → `generate_database_credential(...)`,
cached and refreshed after 50 min; short-circuited by `PGPASSWORD` when
injected. Host: `PGHOST` if set, else `get_database_instance(...).read_write_dns`.
User: `PGUSER`, else `DATABRICKS_CLIENT_ID` (app) or the user's email (local).
Always `sslmode=require`, `dbname=LAKEBASE_DATABASE`,
`options=-c search_path=movies`. Uses a connection pool (`psycopg_pool.ConnectionPool`)
by default (controlled by `PG_POOL_ENABLED`) with a custom connection class to handle
dynamic token minting at connect time. All SQL is parameterized
with `%s`; never format user input into SQL. `src/seed/check_connection.py`
implements the same credential path — reuse it.

### 4.3 Data model (Postgres schema `movies`, in UC as `movies_app_dev.movies`)

Seven tables: `movies`, `theaters`, `auditoriums`, `seats`, `showtimes`,
`bookings`, `booking_seats`. Full column list, constraint inventory and the
mermaid ERD are in **`docs/DATA_MODEL.md`**; the DDL is `src/seed/ddl.sql`
(idempotent target state, not a migration chain — ADR-002).

The three things worth knowing here:

- **`UNIQUE (showtime_id, seat_id)` on `booking_seats` is the business
  invariant.** Everything else in the write path exists to let Postgres enforce
  it cleanly.
- **`booking_seats` denormalises `auditorium_id`** so two composite FKs
  (`(seat_id, auditorium_id)` → seats, `(showtime_id, auditorium_id)` →
  showtimes) force the seat and the showtime into the *same room*. Its FK to
  `bookings` is composite on `(booking_id, showtime_id)` for the same reason.
  A seat sold into the wrong room is unrepresentable, not merely validated
  against (ADR-001, ADR-003).
- **Seat-map availability**: `seats` of the showtime's auditorium
  `LEFT JOIN booking_seats ON showtime_id = ? AND seat_id` → `booked` if
  joined, else `available`.

### 4.4 Booking write path (the part the panel will probe)

```
POST /api/bookings {showtime_id, seat_ids[], customer{name,email}}
1. Validate: showtime exists and starts_at > now(); 1 ≤ n ≤ 8; no duplicate ids;
   every seat belongs to the showtime's auditorium (→ 422 naming the bad ids).
2. BEGIN
     INSERT INTO bookings (...) RETURNING booking_id
     INSERT INTO booking_seats (booking_id, showtime_id, seat_id, auditorium_id, price)
       SELECT ... FROM seats s JOIN showtimes st ON st.auditorium_id = s.auditorium_id
       WHERE st.showtime_id = %s AND s.seat_id = ANY(%s)
       -- the join means a foreign seat yields no row; rowcount vs len(seat_ids)
       -- is a second guard behind the composite FKs
     UPDATE bookings SET total_amount = (SELECT sum(price) ...)
   COMMIT → 201
3. UniqueViolation → ROLLBACK → re-query which seats are taken → 409 {detail, taken_seat_ids}
```

Say in the demo: the UNIQUE constraint is the invariant, the transaction makes
header and seats atomic, and Postgres serializes concurrent inserts on the same
key. No application locking, no verify-and-compensate. Delta stays what it is
good at (analytics at scale, governed sharing); the UC registration bridges the
two.

### 4.5 API contract

| Method | Path | Returns |
|--------|------|---------|
| GET | `/api/health` | status + step-by-step credential/connection diagnostics + `SELECT 1` |
| GET | `/api/movies` · `/api/movies/{id}` | `Movie[]` · `Movie` |
| GET | `/api/theaters` | `Theater[]` |
| GET | `/api/showtimes?movie_id=&theater_id=&date=` | `Showtime[]` (joined with movie, theater, auditorium names) |
| GET | `/api/showtimes/{id}/seats` | `{showtime, rows: [{row_label, seats: [...]}]}` |
| POST | `/api/bookings` | 201 `Booking` / 409 `{detail, taken_seat_ids}` / 422 |
| GET | `/api/bookings/{id}` | `Booking` with seats |
| ~~DELETE~~ | ~~`/api/bookings/{id}`~~ | **not built** — cancellation cut, ADR-007 |

Frontend routes: `/` (movies grid) → `/movies/:id` (theater picker +
showtimes) → `/showtimes/:id` (seat map + customer form) → `/bookings/:id`
(confirmation). A 409 re-fetches the map and marks the lost seats.

### 4.6 Platform coupling (the non-obvious parts)

`resources/app.yml` and `movies_app/app.yaml` **exist and are deployed** — read
them rather than reconstructing them. What is not obvious from the files:

**Env var injection.** Apps injects `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`,
`DATABRICKS_CLIENT_SECRET`, `DATABRICKS_APP_PORT`. It does **not** inject
`PGHOST` just because a `database` resource is attached — that was the ADR-005
outage. `PGHOST` is mapped explicitly with `valueFrom: lakebase`. Treat every
other `PG*` var as optional and log which were present at startup.

**The deploy-time build (ADR-004).** A root `movies_app/package.json` makes the
Apps deployment run, in order and before the `app.yaml` command: `npm install`
(root), `pip install -r requirements.txt`, `npm run build` (root), which does
`cd frontend && npm ci --include=dev && npm run build`. `--include=dev` matters
— every build tool is a devDependency and the platform may install in
production mode. A type error fails the deployment, not the running app.

**Postgres grants.** The `database` app resource creates a Postgres role named
for the app SP client id with CONNECT/CREATE on the database, but the seed
script owns the tables, so it also runs (given `--app-sp-client-id`):

```sql
GRANT USAGE ON SCHEMA movies TO "<client-id>";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA movies TO "<client-id>";
ALTER DEFAULT PRIVILEGES IN SCHEMA movies GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "<client-id>";
```

The database also has schemas `public` and `__db_system` and platform roles
(`databricks_superuser`, `databricks_reader_*`, `databricks_writer_*`,
`databricks_synced_table_helper`, …) that must not be touched. The user's role
is `ra.escoto@slalom.com`.

**Phase 6 job.** `resources/analytics_job.yml`: one job, one `sql_task` with
`warehouse_id: ${resources.sql_warehouses.movies_analytics_warehouse.id}`
running `src/analytics/gold.sql`
(`CREATE OR REPLACE TABLE movies_analytics_dev.movies.<gold> AS SELECT … FROM movies_app_dev.movies.…`).

---

## 5. Repository layout

The panel-facing tree is in `README.md`. What matters for editing:

```
docs/            DATA_MODEL.md, DECISIONS.md (ADR-001..009), AI_USAGE_LOG.md exist;
                 DEMO_SCRIPT.md to write. ARCHITECTURE.md / SCALE_TO_MILLIONS.md
                 dropped 2026-09-07 — the README carries that content (§9)
.claude/         settings.json (git denied), agents/databricks-engineer/, commands/build-check.md
movies_app_bundle/
├── databricks.yml           engine: direct, variables, target
├── resources/               lakebase.yml, lakehouse.yml, app.yml,
│                            analytics_job.yml, analytics_ui.yml (dashboard + Genie)
├── src/seed/                check_connection.py, ddl.sql, seed_lakebase.py
├── src/analytics/           gold.sql — the three Delta gold tables
├── src/dashboards/          movies_operations.lvdash.json — 9 datasets, 2 pages
├── src/genie/               movies_demand.geniespace.json — tables + instructions
└── movies_app/              App source_code_path
    ├── app.yaml, package.json, requirements.txt, requirements-dev.txt, Makefile
    ├── backend/  (§4.2)     frontend/  Vue 3 + Vite + TS
    ├── pytest.ini           testpaths, pythonpath; `make test` is the gate
    └── tests/               108 cases. Only backend.db is stubbed, so they need
                             no credentials and pass with Lakebase stopped
```

---

## 6. Build plan

Phases 1–5 are complete (§2). Do not start a phase before the previous
done-check passes.

**Phase 7 — the analytics layer — is complete** (§2, ADR-009): the seed's demand
model, the three gold tables + `analytics_job`, and the dashboard + Genie space
as bundle resources. `bundle run analytics_job` succeeds, all three tables have
rows, all nine dashboard datasets execute, and Genie answers the demo question
from its own instructions.

**Remaining before the demo (~40 min):**

1. **Look at the dashboard again after any edit to its JSON.** The Lakeview API
   stores widget definitions without validating them — it accepts an invented
   `widgetType` with a `200` — so a clean deploy is not evidence. Datasets are
   verified by executing them the way the runtime does (concatenate `queryLines`
   with **no** separator, then wrap in `WITH q AS (...)`; every line must carry
   its own `\n` — ADR-009). The visual specs can only be checked by opening the
   page. Fix anything ugly in the UI, then round-trip it back:
   `databricks bundle generate dashboard --resource movies_operations --force`.
2. `docs/DEMO_SCRIPT.md`, with the re-seed, the `analytics_job` re-run and the
   three compute starts as step zero, plus `docs/img/` screenshots as the
   offline backup.
3. ~~`docs/ARCHITECTURE.md` / `docs/SCALE_TO_MILLIONS.md`~~ — dropped
   2026-09-07; the content lives in the README and the promises were removed.

*Done-check:* the dashboard renders both pages with data; a cold reader can
follow `DEMO_SCRIPT.md` to a booking, to that booking appearing on the live
tile, and to Genie's recommendation, without asking a question.

**Cut, not deferred:** cancellation (ADR-007). **Still deferred:** seat holds
with expiry, idempotency keys, and the seven pooling items in ADR-006's
*Deferred* table.

---

## 7. Commands

**Every `databricks` command runs inside WSL Ubuntu 24.04** (CLI 1.15.0,
profile `movies`). From Windows or the Bash tool, wrap it (the `dev` target
carries `profile: movies`, so bundle commands need no `-p`; other CLI commands
do):

```bash
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/repos/apps/dbx-movies-app/movies_app_bundle && databricks bundle validate -t dev"
```

Inside WSL, from `movies_app_bundle/`:

```bash
databricks bundle validate -t dev
databricks bundle summary  -t dev              # deployed resources (prints "URL: (not deployed)" for the app under
                                               # the direct engine — trust `apps get` instead)
databricks bundle deploy   -t dev              # uploads code + updates resources; does NOT restart the app
databricks bundle run movies_app -t dev        # new app deployment: npm install, pip install, npm run build, start
databricks bundle run analytics_job -t dev     # rebuild the Delta gold tables

# AI/BI — round-trip a UI edit back into the repo (then commit the JSON)
databricks bundle generate dashboard   --resource movies_operations --force
databricks bundle generate genie-space --resource movies_demand     --force

# ask the deployed Genie space a question without a browser
databricks genie start-conversation <space-id> 'Where and for which movies should we open new functions?' -p movies -o json
databricks genie get-message <space-id> <conversation-id> <message-id> -p movies -o json

# run a dashboard dataset / any SQL against the warehouse
databricks api post /api/2.0/sql/statements --json @stmt.json -p movies

databricks database get-database-instance movies-app-dev -p movies   # state, read_write_dns
databricks database generate-database-credential -p movies --json '{"instance_names":["movies-app-dev"]}'

databricks apps get movies-app-dev -p movies   # URL, status, service_principal_client_id
# runtime logs: Databricks UI → Compute → Apps → movies-app → Logs
```

**Python for seed scripts and the local backend.**

*From WSL (preferred — matches the Apps runtime):* `/usr/bin/python3.11` has
`databricks-sdk`; add psycopg with
`python3.11 -m pip install --user "psycopg[binary]"`. From
`/mnt/c/repos/apps/dbx-movies-app`:

```bash
DATABRICKS_CONFIG_PROFILE=movies python3.11 movies_app_bundle/src/seed/seed_lakebase.py --app-sp-client-id <client-id>
```

Do not use the system `python3` (3.12): neither package, externally-managed,
and no venv until `sudo apt install python3.12-venv`.

*From Windows (Git Bash):* Python 3.13 has both packages; point the SDK at the
WSL profile file. From the repo root:

```bash
DATABRICKS_CONFIG_FILE=//wsl.localhost/Ubuntu-24.04/home/raescoto/.databrickscfg DATABRICKS_CONFIG_PROFILE=movies python movies_app_bundle/src/seed/check_connection.py

# local backend — same two DATABRICKS_CONFIG_* vars plus:
export LAKEBASE_INSTANCE=movies-app-dev LAKEBASE_DATABASE=movies_dev LAKEBASE_SCHEMA=movies
cd movies_app_bundle/movies_app && pip install -r requirements.txt && python -m backend.serve

# local frontend (the platform builds dist at deploy; a local build is only a check)
cd movies_app_bundle/movies_app/frontend && npm install && npm run dev   # proxies /api → :8000
cd movies_app_bundle/movies_app && npm run build                         # exactly what the Apps deployment runs
```

Environment: Windows has Node 22.20.0, npm 10.9.3, Python 3.13.7; the Bash tool
is Git Bash. WSL has CLI 1.15.0, Python 3.12.3, no `node`. **The Apps runtime is
Python 3.11 — avoid 3.12+ only syntax.**

---

## 8. Conventions and rules

1. **Thin slice first.** Every phase ends with something demoable. No feature
   outside §3/§4 without a `docs/DECISIONS.md` entry.
2. **Never deploy to a client workspace.** Target must be the Slalom workspace
   in §10. If a command would touch `dbc-2ba89670-78df`, stop.
3. **Never run `bundle destroy`**; only the user does. It deletes the Lakebase
   instance, the catalogs and the warehouse.
4. **No secrets in the repo.** Tokens live in CLI profiles / app resources.
   `.env` is gitignored; commit `.env.example` only.
5. **Parameterized SQL only.** `%s` placeholders; identifiers are constants.
6. **Keep `app.yaml` env values and bundle variables in sync** (instance and
   database names). The databricks-engineer agent owns that coupling.
7. **State assumptions in code comments where they bite** (token refresh, one
   connection per request, enforced constraints) — the panel reads the code.
8. **Update `docs/AI_USAGE_LOG.md` at the end of every phase**: what was
   generated, what the human changed or rejected, the rough AI/human split.
9. **The frontend is built on the platform, not locally** (ADR-004). Pushing
   code is always `bundle deploy` then `bundle run movies_app`. Never add
   `dist` to `sync.include`; never put build steps in the `app.yaml` command.
10. **Windows paths.** Forward slashes in YAML/config; quote paths with spaces.

---

## 9. Interview artifacts (docs/)

Existing: `DATA_MODEL.md` (ERD + constraint notes), `DECISIONS.md`
(ADR-001…009), `AI_USAGE_LOG.md` (R8, running log, Phases 1–7).

To write:

- **`DEMO_SCRIPT.md`** — the path: open app → movie → theater → seat map →
  book 2 seats → show the row in Catalog Explorer → re-book the same seats →
  409 → **the booking on the live dashboard tile** → **ask Genie where to open
  new functions** → show the bundle resources that deployed all of it. Backup:
  screenshots in `docs/img/`. **Step zero is the pre-flight** (§2): re-seed with
  `--reset`, re-run `analytics_job`, start Lakebase + app compute ≥15 min ahead
  and the warehouse ≥5 min ahead, confirm `/api/health` reports `db: connected`.

**Dropped 2026-09-07:** `ARCHITECTURE.md` and `SCALE_TO_MILLIONS.md`. The
README's §Architecture already carries the diagram and the services-vs-
alternatives table, and §Taking it to millions carries the scale prose; the
"still to be written" pointers were removed from the README rather than left
aimed at files that would not exist by the demo.

---

## 10. Workspace facts

| Item | Value |
|------|-------|
| Demo workspace | `https://dbc-66830d2c-97a4.cloud.databricks.com` (Slalom dev/test; `ra.escoto@slalom.com`, workspace admin; id `2485046985091381`) |
| CLI | Databricks CLI 1.15.0 in WSL Ubuntu 24.04, profile `movies` (PAT). Bundle engine `direct` |
| Bundle state path | `/Workspace/Users/ra.escoto@slalom.com/.bundle/movies_app_bundle/dev` |
| Lakebase instance | `movies-app-dev` (key `movies_db`), CU_1, PG 16, eu-west-1, port 5432, `sslmode=require`, native password login disabled. DNS changes on every recreate — on-platform it arrives via `PGHOST`/`valueFrom` (ADR-005); locally resolve with `get_database_instance(...).read_write_dns` |
| Lakebase database / schema | `movies_dev` / `movies` |
| UC catalog for Lakebase | `movies_app_dev` → `https://dbc-66830d2c-97a4.cloud.databricks.com/explore/data/movies_app_dev?o=2485046985091381` |
| Analytics catalog.schema (Delta) | `movies_analytics_dev.movies` |
| SQL warehouse | `movies_analytics`, id `72704e9c199eb256` (key `movies_analytics_warehouse`; serverless PRO, 2X-Small, auto-stop 20 min). **The id changes whenever the warehouse is recreated** — the previously recorded `50b70f5e18138968` was stale and returned "warehouse not found". Reference it as `${resources.sql_warehouses.movies_analytics_warehouse.id}`, never as a literal; re-check with `databricks warehouses list` before trusting this cell |
| AI/BI dashboard | `Movies — live operations and demand`, id `01f1aabfa9f11c97981e76b48407fa28` (key `movies_operations`) |
| Genie space | `Movies — cinema demand`, id `01f1aabfd22f1ac5a20063d5511ba352` (key `movies_demand`) |
| Analytics job | `movies-analytics-gold-dev`, id `743598470449255` (key `analytics_job`) |
| App name / URL | `movies-app-dev` · `https://movies-app-dev-2485046985091381.aws.databricksapps.com` |
| App SP client id | `010ae2f6-6206-498c-a005-17daf4850a48` |
| Interview date | **Wednesday 2026-09-09** |

---

## 11. Tooling notes for Claude

- Model routing: `.claude/settings.json` maps `opus`/`sonnet`/`haiku` to Bedrock
  EU model ids; session default is Opus.
- **Databricks CLI only via WSL** (§7). The Windows CLI must not be used here.
- The Bash tool breaks on unbalanced single quotes (apostrophes) and some long
  `&&` chains. Write prose files with Write/Edit; keep shell commands short.
- `databricks bundle schema` (WSL) is the authority for resource fields.
  Lakebase resources: `database_instances`, `database_catalogs`,
  `synced_database_tables`, `apps.*.resources[].database`. `catalogs` is
  direct-engine only.
- `databricks-engineer` agent (Sonnet) owns `databricks.yml`, `resources/`,
  `src/seed/`, `src/analytics/`, `app.yaml`. Delegate bundle/Lakebase/UC work to
  it; keep backend and frontend code in the main session.
- `/build-check`: runs `vue-tsc --noEmit` and `vite build` in
  `movies_app/frontend`. Report only, never auto-fix.
- Skills: `code-review` before the user commits each phase; `security-review`
  once before the demo (SQL injection, secret leakage — note the ADR-005
  exception handler returns raw exception text to the client).
