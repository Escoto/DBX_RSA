# CLAUDE.md — Movie Ticket Booking App on Databricks

Handoff document for Claude (Opus via Bedrock, see `.claude/settings.json`).
Read this fully before changing anything. It is the single source of truth for
scope, decisions, and the build order. Update it when a decision changes.

---

## 1. Mission

Take-home exercise for a **Databricks Resident Architect (Slalom)** interview.
The panel is Databricks engineers. The candidate (Rafael Escoto, the user) will
demo live and defend the design end to end. The role is client-facing and
represents both Databricks and Slalom, so quality of judgment matters as much
as code.

**The prompt (summarized from the brief):** build a working prototype of a movie
ticket booking app for millions of global users. Users browse movies and
showtimes, pick a theater, view a seat map, and book one or more assigned seats.

**Hard requirements**

| # | Requirement | How we satisfy it |
|---|-------------|-------------------|
| R1 | Deployed as a **Databricks App**; frontend + backend served from it | One app: FastAPI serves the API and the prebuilt Vue SPA |
| R2 | **Data layer on Databricks**: real Unity Catalog / Delta schema, several tables | **Lakebase** (managed Postgres) holds the 7 transactional tables, registered in Unity Catalog as `movies_app_dev`; Delta gold tables in `movies_analytics_dev.movies` for analytics |
| R3 | Frontend: browse movies/showtimes, pick theater, seat map, book ≥1 assigned seats | Vue 3 SPA, 4 routes (see §4.5) |
| R4 | Backend API + persistent data store | FastAPI → Lakebase over Postgres protocol (psycopg), OAuth as the app's service principal |
| R5 | Panel gets access to code + Databricks assets (catalog/schema, tables, jobs) | README lists workspace, catalogs, warehouse, app URL, bundle resources |
| R6 | Short README with workspace location and run/deploy instructions | `README.md` |
| R7 | Be ready to explain data model, API design, service choices/trade-offs, scale to millions | `docs/` artifacts (§9) |
| R8 | "AI as a force multiplier": articulate where AI helped, where the human intervened, roughly how much | `docs/AI_USAGE_LOG.md` kept current |

**Ground rules from the brief:** scope ruthlessly (a thin, working walking
skeleton beats a broad broken one), seed fake data, no real payments or auth
providers, state assumptions wherever the prompt is vague, stub anything that
cannot be made to work on-platform and explain how it would map to Databricks.
Evaluation: "a builder who ships, thinks in trade-offs, and can defend a design".

**Time budget:** 4–6 focused hours total. Interview date: TBD (user to fill in §10).

---

## 2. Current state (as of 2026-09-04)

**Infrastructure is deployed** by the bundle (direct engine, CLI 1.15.0) and
verified with `databricks bundle summary -t dev`:

| Resource | Key | Name / id | File |
|----------|-----|-----------|------|
| Lakebase instance | `database_instances.movies_db` | `movies-app-dev` (CU_1, PG 16, eu-west-1) | `resources/lakebase.yml` |
| UC registration of the Postgres db | `database_catalogs.catalog_movies_db` | catalog `movies_app_dev` → database `movies` | `resources/lakebase.yml` |
| Analytics catalog (Delta) | `catalogs.movies_analytics` | `movies_analytics_dev` | `resources/lakehouse.yml` |
| Analytics schema | `schemas.movies` | **currently `movies_analytics_dev.movies_analytics_dev`** — see the known issue below | `resources/lakehouse.yml` |
| SQL warehouse | `sql_warehouses.movies_analytics_warehouse` | `movies_analytics`, id `50b70f5e18138968`, serverless PRO 2X-Small, auto-stop 20 min | `resources/lakehouse.yml` |

**Phase 1 complete.** `resources/app.yml`, `movies_app/app.yaml`,
`requirements.txt`, the FastAPI skeleton (`serve.py`, `main.py`, `config.py`,
`db.py`, `/api/health`) and a Vue/Vite scaffold are in place. The app is
deployed and `RUNNING` (`databricks apps get movies-app -p movies`); its service
principal is recorded in §10. The `lakehouse.yml` schema-name issue is fixed and
deployed — the schema is `movies_analytics_dev.movies`. Note `bundle summary`
still prints `URL: (not deployed)` for the app under the direct engine; trust
`apps get` instead.

**Phase 2 complete.** `src/seed/ddl.sql` (7 tables, 9 FKs, 3 unique constraints,
8 checks) and `src/seed/seed_lakebase.py` (deterministic, idempotent, with
`--reset`, `--recreate` and `--app-sp-client-id`) are applied to
`movies-app-dev`. Verified live: 8/3/5/600/70/54/128 rows; a duplicate
`(showtime_id, seat_id)` raises `uq_booking_seats_showtime_seat`; a
cross-auditorium seat raises one of the composite FKs; the app SP holds
USAGE + full DML on all 7 tables; all 7 tables are queryable through Unity
Catalog as `movies_app_dev.movies.*` from the `movies_analytics` warehouse.
`docs/DATA_MODEL.md` and `docs/DECISIONS.md` written.

Also in the repo: `src/seed/check_connection.py` (proves the OAuth → Postgres
path), `movies_app_vue/` (**dead** — the old placeholder SPA; `tokens.css` has
already been carried into `movies_app/frontend/`, so the directory should be
deleted), the `databricks-engineer` agent and the `/build-check` command.

**Not built yet:** the real backend routers and booking service (Phase 3), the
frontend routes and seat map (Phase 4), the analytics job (Phase 6), tests, and
the remaining docs.

**Hazards (still live)**

1. **Databricks CLI only from WSL Ubuntu 24.04.** The `movies` profile (PAT)
   for the Slalom workspace exists only there. The Windows CLI's profiles point
   to `dbc-2ba89670-78df`, a **client (BioNTech) workspace** that must never be
   used for this project. Run every `databricks` command as
   `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/repos/apps/dbx-movies-app/movies_app_bundle && databricks ..."`.
2. **Lakebase costs while running.** Set `stopped: true` in
   `resources/lakebase.yml` and deploy to pause it between sessions; set it
   back (and deploy) at least 15 minutes before the demo. `prevent_destroy` is
   `false` on every resource, so `bundle destroy` deletes the instance **and its
   data**; only the user runs it. Renaming the instance recreates it and
   changes its DNS, so code must resolve the host through the SDK.
3. **`catalogs` needs the direct engine.** `bundle.engine: direct` is set; do
   not remove it (terraform silently drops the catalog resource).
4. **Git is denied to Claude** (`.claude/settings.json`). The user commits.
5. **Secrets.** `.claude/settings.local.json` holds a Bedrock API key and the
   WSL `~/.databrickscfg` holds a PAT. Never print, copy, or reference either.
6. Two unrelated GxP apps exist in the workspace. Leave them alone.

---

## 3. Decisions and assumptions (say these out loud in the demo)

| Topic | Decision | Why / trade-off |
|-------|----------|-----------------|
| Backend language | **Python 3.11, FastAPI** | Databricks-native SDK support, Apps docs use Python, user has FastAPI experience |
| Frontend | **Vue 3 + Vite + TypeScript**, vue-router, no state library | TS gives typed API contracts; small enough to not need Pinia |
| Serving | FastAPI serves `/api/*` **and** the prebuilt SPA from `frontend/dist` | One process, one app, no Node at runtime → fast, predictable startup for a live demo |
| **System of record** | **Lakebase** (Databricks managed Postgres), instance `movies-app-dev`, database `movies`, schema `movies`, 7 tables with **enforced** PK/FK/UNIQUE/CHECK constraints | Assigned-seat booking is an OLTP problem: row locks, unique constraints, ms commits. Delta cannot enforce uniqueness or span tables in one transaction |
| Governance | The Postgres database is **registered in Unity Catalog** as catalog `movies_app_dev` | The schema is browsable in Catalog Explorer and queryable from a SQL warehouse; meets "real schema in Unity Catalog" without ETL |
| Analytics copy | Delta gold tables in `movies_analytics_dev.movies` (`occupancy_by_showtime`, `revenue_by_day`) built by a bundle job with a `sql_task` on the bundle's own warehouse `movies_analytics`, reading the Lakebase catalog | Shows the lakehouse side (Delta, jobs, warehouse) without putting OLTP on Delta. Infra exists; the job is Phase 6 |
| Infra as code | **Databricks Asset Bundles, direct engine**: instance, UC registration, catalog, schema, warehouse, app, job all in one bundle | Everything the panel sees is reproducible from the repo; `catalogs` requires the direct engine |
| App → DB auth | App connects as its **own service principal** with an OAuth token from `generate_database_credential`; the `database` app resource (`CAN_CONNECT_AND_CREATE`) creates the Postgres role | No passwords anywhere; tokens live ~1 h and are refreshed by the backend |
| Double-booking | `UNIQUE (showtime_id, seat_id)` on `booking_seats` + the whole booking in **one transaction**; a unique violation → rollback → `409` with the taken seats | The database enforces the invariant; the app only translates errors |
| Seat holds / timers | **Out of scope** (documented stretch: `seat_holds` table with `expires_at`, sweeper job) | Not needed for the walking skeleton |
| Cancellations | Stretch: `DELETE /api/bookings/{id}` marks the header `CANCELLED` and deletes its `booking_seats` rows (frees the seats, header keeps the audit trail) | Keeps the UNIQUE constraint simple |
| Pricing | Per showtime: `price_standard`, `price_premium`; seat types `standard`, `premium`, `accessible` (accessible = standard price) | Simple, shows a non-trivial join |
| Theaters | Multiple theaters, each with 1–2 auditoriums; one auditorium per showtime | Enough to show "pick a theater" |
| Auth / users | None. Booking captures `customer_name` + `customer_email` | Brief says no auth providers needed |
| Payments | None. Booking is confirmed immediately | Brief says no payment processing needed |
| Currency / timezone | USD, timestamps in UTC, displayed as-is | Avoids i18n work |
| Seed data | ~8 movies, 3 theaters, ~5 auditoriums (rows A–J × 12 seats), ~60 showtimes over the next 7 days, a few pre-existing bookings; deterministic (seeded RNG); idempotent | Makes the seat map look real |
| Environments | Single `dev` target for the interview. `staging`/`prod` described in README, not built | Time budget |

---

## 4. Architecture

### 4.1 Runtime flow

```
Browser ──HTTPS──▶ Databricks App "movies-app" (FastAPI, port $DATABRICKS_APP_PORT)
                     ├── GET /          → static Vue SPA (frontend/dist)
                     └── /api/*         → routers → services → psycopg
                                                       │  OAuth token (app SP), sslmode=require
                                                       ▼
                                          Lakebase instance "movies-app-dev"
                                          database "movies", schema "movies" (7 tables)
                                                       │ registered as UC catalog
                                                       ▼
                                          Unity Catalog: movies_app_dev.movies.*   ← browse in Catalog Explorer, query from warehouse "movies_analytics"
                                                       │ analytics job (sql_task on movies_analytics)
                                                       ▼
                                          Delta: movies_analytics_dev.movies.occupancy_by_showtime, revenue_by_day
Deploy-time:  databricks bundle deploy → instance, UC registration, catalog, schema, warehouse, app, job
              python src/seed/seed_lakebase.py → Postgres schema, tables, seed data, grants for the app SP
```

### 4.2 Backend layout (`movies_app_bundle/movies_app/backend/`)

```
backend/
├── serve.py            entrypoint: uvicorn.run(app, host=0.0.0.0, port=int(DATABRICKS_APP_PORT or 8000))
├── main.py             FastAPI app, CORS (dev only), mounts routers, serves SPA with history fallback
├── config.py           Settings from env: LAKEBASE_INSTANCE, LAKEBASE_DATABASE, LAKEBASE_SCHEMA, PGHOST/PGUSER if injected
├── db.py               Lakebase connection factory (see below), `query()` / `execute()` helpers, `transaction()` context manager
├── routers/
│   ├── catalog.py      movies, theaters, showtimes
│   ├── seats.py        seat map for a showtime
│   └── bookings.py     create / get (/ cancel)
├── services/
│   └── booking_service.py   the transaction (see 4.4)
└── models.py           Pydantic request/response models
```

**`db.py` contract.** Use `psycopg` (v3). Credentials: `WorkspaceClient()`
(picks up the app's `DATABRICKS_CLIENT_ID`/`SECRET`, or locally
`DATABRICKS_CONFIG_PROFILE=movies`) →
`w.database.generate_database_credential(request_id=str(uuid4()), instance_names=[LAKEBASE_INSTANCE]).token`.
Cache the token and refresh it after 50 minutes. Host: `PGHOST` if the platform
injects it, else `w.database.get_database_instance(LAKEBASE_INSTANCE).read_write_dns`.
User: `PGUSER` if injected, else `DATABRICKS_CLIENT_ID` (app) or the user's
email (local). Always `sslmode=require`, `dbname=LAKEBASE_DATABASE`, and
`options=-c search_path=movies`. Open one connection per request (cheap on
Lakebase, avoids token-rotation problems in a pool); note a pool as the
production optimization. All SQL is parameterized (`%s` placeholders); never
format user input into SQL. `src/seed/check_connection.py` already implements
the credential and connection logic — reuse it.

### 4.3 Data model (Postgres schema `movies`, visible in UC as `movies_app_dev.movies`)

| Table | Key | Columns (essentials) | Constraints |
|-------|-----|----------------------|-------------|
| `movies` | `movie_id text` | title, synopsis, genre, rating, runtime_min, poster_url | PK |
| `theaters` | `theater_id text` | name, city, address | PK |
| `auditoriums` | `auditorium_id text` | theater_id, name, row_count, seats_per_row | PK, FK → theaters |
| `seats` | `seat_id text` | auditorium_id, row_label, seat_number, seat_type | PK, FK → auditoriums, `CHECK seat_type IN ('standard','premium','accessible')`, `UNIQUE (auditorium_id, row_label, seat_number)`, `UNIQUE (seat_id, auditorium_id)` (FK target) |
| `showtimes` | `showtime_id text` | movie_id, auditorium_id, starts_at timestamptz, price_standard numeric(8,2), price_premium numeric(8,2) | PK, FK → movies, FK → auditoriums, `UNIQUE (showtime_id, auditorium_id)` (FK target) |
| `bookings` | `booking_id uuid default gen_random_uuid()` | showtime_id, customer_name, customer_email, status, total_amount numeric(10,2), created_at, cancelled_at | PK, FK → showtimes, `CHECK status IN ('CONFIRMED','CANCELLED')` |
| `booking_seats` | (`booking_id`, `seat_id`) | showtime_id, seat_id, **auditorium_id**, price numeric(8,2) | PK, FK → bookings (ON DELETE CASCADE), **`UNIQUE (showtime_id, seat_id)`**, composite FK `(seat_id, auditorium_id)` → seats, composite FK `(showtime_id, auditorium_id)` → showtimes, index on `showtime_id` |

`auditorium_id` on `booking_seats` is denormalised so the two composite FKs can
force the seat and the showtime into the *same* room — booking a seat into a
showtime playing elsewhere is unrepresentable, not merely validated against. The
API still checks membership first so a bad request gets a precise 422. See
`docs/DECISIONS.md` ADR-001.

The DDL lives in `src/seed/ddl.sql` (idempotent: `CREATE SCHEMA IF NOT EXISTS`,
`CREATE TABLE IF NOT EXISTS`). Document the ERD as a mermaid `erDiagram` in
`docs/DATA_MODEL.md`. Availability for a seat map: `seats` of the showtime's
auditorium `LEFT JOIN booking_seats ON showtime_id = ? AND seat_id` →
`status = 'booked' if joined else 'available'`.

### 4.4 Booking write path (the part the panel will probe)

```
POST /api/bookings {showtime_id, seat_ids[], customer{name,email}}
1. Validate: showtime exists and starts_at > now(); 1 ≤ n ≤ 8; seat_ids belong to the showtime's auditorium (→ 422 naming the offending ids).
2. BEGIN
     INSERT INTO bookings (showtime_id, customer_name, customer_email, status, total_amount)
       VALUES (...) RETURNING booking_id;
     INSERT INTO booking_seats (booking_id, showtime_id, seat_id, auditorium_id, price)
       SELECT %s, st.showtime_id, s.seat_id, s.auditorium_id,
              CASE s.seat_type WHEN 'premium' THEN st.price_premium ELSE st.price_standard END
       FROM seats s JOIN showtimes st ON st.auditorium_id = s.auditorium_id
       WHERE st.showtime_id = %s AND s.seat_id = ANY(%s);
     -- the join on auditorium_id means a foreign seat yields no row; compare
     -- rowcount to len(seat_ids) as a second guard behind the composite FKs.
     UPDATE bookings SET total_amount = (SELECT sum(price) FROM booking_seats WHERE booking_id = %s) WHERE booking_id = %s;
   COMMIT → 201 Booking
3. psycopg.errors.UniqueViolation → ROLLBACK → re-query which requested seats are taken → 409 {detail, taken_seat_ids}
```

Say in the demo: the UNIQUE constraint is the invariant, the transaction makes
the header and the seats atomic, and Postgres serializes concurrent inserts on
the same key. No application-level locking, no verify-and-compensate. Delta is
kept for what it is good at (analytics at scale, governed sharing), and the UC
registration bridges the two.

### 4.5 API contract

| Method | Path | Returns |
|--------|------|---------|
| GET | `/api/health` | `{status, instance, database, schema}` + a `SELECT 1` round-trip |
| GET | `/api/movies` | `Movie[]` |
| GET | `/api/movies/{movie_id}` | `Movie` |
| GET | `/api/theaters` | `Theater[]` |
| GET | `/api/showtimes?movie_id=&theater_id=&date=` | `Showtime[]` (joined with movie, theater, auditorium names) |
| GET | `/api/showtimes/{showtime_id}/seats` | `{showtime, rows: [{row_label, seats: [{seat_id, seat_number, seat_type, price, status}]}]}` |
| POST | `/api/bookings` | 201 `Booking` / 409 `{detail, taken_seat_ids}` / 422 |
| GET | `/api/bookings/{booking_id}` | `Booking` with seats |
| DELETE | `/api/bookings/{booking_id}` | stretch: cancel |

Frontend routes: `/` (movies grid) → `/movies/:id` (theater picker + showtimes)
→ `/showtimes/:id` (seat map + customer form + book) → `/bookings/:id`
(confirmation). Seat map: rows of buttons, `booked` disabled, selected
highlighted, running total; a 409 re-fetches the map and highlights the taken
seats.

### 4.6 Bundle resources still to add

`resources/app.yml`:

```yaml
resources:
  apps:
    movies_app:
      name: ${var.app_name}
      description: "Movie ticket booking prototype — FastAPI + Vue on Lakebase"
      source_code_path: ../movies_app
      resources:
        - name: lakebase
          description: Lakebase OLTP database for the booking app
          database:
            instance_name: ${resources.database_instances.movies_db.name}
            database_name: ${var.lakebase_database}
            permission: CAN_CONNECT_AND_CREATE
        - name: sql-warehouse
          description: Serverless SQL warehouse for analytics queries
          sql_warehouse:
            id: ${resources.sql_warehouses.movies_analytics_warehouse.id}
            permission: CAN_USE
```

`movies_app/app.yaml`:

```yaml
command: ["python", "-m", "backend.serve"]
env:
  - name: LAKEBASE_INSTANCE
    value: movies-app-dev         # must equal var.lakebase_instance_name
  - name: LAKEBASE_DATABASE
    value: movies                 # must equal var.lakebase_database
  - name: LAKEBASE_SCHEMA
    value: movies
  - name: DATABRICKS_WAREHOUSE_ID
    valueFrom: sql-warehouse
```

Databricks Apps injects `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`,
`DATABRICKS_CLIENT_SECRET`, `DATABRICKS_APP_PORT`. With a `database` resource
attached the platform is expected to also inject `PGHOST`, `PGPORT`,
`PGDATABASE`, `PGUSER`, `PGSSLMODE`; treat them as optional and log which ones
were present at startup. `requirements.txt` at the app root is installed at
deploy (Python 3.11).

`resources/analytics_job.yml` (Phase 6): one job, one `sql_task` with
`warehouse_id: ${resources.sql_warehouses.movies_analytics_warehouse.id}`
running `src/analytics/gold.sql`, which does
`CREATE OR REPLACE TABLE movies_analytics_dev.movies.<gold> AS SELECT … FROM movies_app_dev.movies.…`.

**Postgres grants for the app.** The `database` app resource creates a Postgres
role for the app's service principal (role name = the SP client id) with
CONNECT/CREATE on the database. Tables created by the seed script are owned by
the user, so the seed script also runs, when given `--app-sp-client-id`:

```sql
GRANT USAGE ON SCHEMA movies TO "<client-id>";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA movies TO "<client-id>";
ALTER DEFAULT PRIVILEGES IN SCHEMA movies GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "<client-id>";
```

Confirm the role name with `SELECT rolname FROM pg_roles` after the first app
deploy. The database currently has schemas `public` and `__db_system` and
platform roles (`databricks_superuser`, `databricks_reader_*`,
`databricks_writer_*`, `databricks_synced_table_helper`, …) that must not be
touched; the user's role is `ra.escoto@slalom.com`.

---

## 5. Target repository layout

```
dbx-movies-app/
├── CLAUDE.md                     this file
├── README.md                     panel-facing: what, where, how to run, assumptions, scale story
├── docs/
│   ├── ARCHITECTURE.md           mermaid diagram + service choices and trade-offs
│   ├── DATA_MODEL.md             mermaid erDiagram + constraint notes
│   ├── DECISIONS.md              ADR-style log (one entry per row of §3 that changes)
│   ├── SCALE_TO_MILLIONS.md      production architecture narrative
│   ├── DEMO_SCRIPT.md            5-minute click path + backup plan
│   └── AI_USAGE_LOG.md           what AI produced, what the human changed, rough % (R8)
├── .claude/
│   ├── settings.json             model + permissions (git denied)
│   ├── agents/databricks-engineer/AGENT.md
│   └── commands/build-check.md
└── movies_app_bundle/
    ├── databricks.yml            engine: direct, variables, target, sync includes     (exists)
    ├── resources/
    │   ├── lakebase.yml          database instance + UC registration                  (exists, deployed)
    │   ├── lakehouse.yml         analytics catalog + schema + SQL warehouse            (exists, deployed)
    │   ├── app.yml               Databricks App + lakebase / sql-warehouse resources
    │   └── analytics_job.yml     sql_task → Delta gold tables                          (Phase 6)
    ├── src/
    │   ├── seed/
    │   │   ├── check_connection.py  OAuth → Postgres connectivity check               (exists)
    │   │   ├── ddl.sql           schema + 7 tables + constraints + indexes (idempotent)
    │   │   └── seed_lakebase.py  runs ddl.sql, loads deterministic seed data, applies grants
    │   └── analytics/gold.sql    gold tables from the Lakebase catalog                 (Phase 6)
    └── movies_app/               ← App source_code_path (replaces movies_app_vue/)
        ├── app.yaml
        ├── requirements.txt      fastapi, uvicorn, psycopg[binary], databricks-sdk, pydantic
        ├── backend/              FastAPI (§4.2)
        ├── frontend/             Vue 3 + Vite + TS; `npm run build` → frontend/dist
        └── tests/                pytest: booking_service with a fake connection (unique-violation path)
```

---

## 6. Build plan (phased, each with a done-check)

Infrastructure is done. Work top to bottom; do not start a phase before the
previous one's check passes. Timebox is guidance for the human; Claude should
just keep moving.

**Phase 1 — App resource + skeleton (~30 min).** Fix the schema name in
`lakehouse.yml`; create `movies_app/` (move `tokens.css` over, delete the rest
of `movies_app_vue/`); `resources/app.yml` and `app.yaml` as in §4.6;
`requirements.txt`; `backend/serve.py` + a minimal `main.py` with
`/api/health`. Deploy once so the app's service principal exists.
Done-check: `databricks bundle validate -t dev` passes; `databricks apps get
movies-app -p movies` returns a URL and a `service_principal_client_id`
(record it in §10); `/api/health` answers; the schema shows as
`movies_analytics_dev.movies` in `bundle summary`.

**Phase 2 — Data layer (~45 min).** `src/seed/ddl.sql` and
`src/seed/seed_lakebase.py` (psycopg, credential via SDK, `--app-sp-client-id`
for grants). Run it against `movies-app-dev`.
Done-check: `SELECT count(*)` per table in Catalog Explorer under
`movies_app_dev.movies` matches expectations; inserting a duplicate
`(showtime_id, seat_id)` by hand fails with a unique violation;
`docs/DATA_MODEL.md` written.

**Phase 3 — Backend (~60 min).** §4.2 + §4.4 + §4.5 fully; unit tests for
`booking_service` with a fake connection (happy path, unique-violation → 409,
validation → 422). Local run with `DATABRICKS_CONFIG_PROFILE=movies`.
Done-check: `pytest` green; `curl localhost:8000/api/showtimes/<id>/seats`
returns a seat map; a POST books seats; a second POST for the same seats
returns 409 with the seat ids.

**Phase 4 — Frontend (~60 min).** Four routes from §4.5, `services/api.ts`
typed client, seat map component, loading/error states, `tokens.css` reused.
Vite dev proxy `/api` → `http://localhost:8000`.
Done-check: `/build-check` passes (vue-tsc + vite build); full click path works
locally against the real Lakebase.

**Phase 5 — Deploy + verify on platform (~30 min).** Build frontend, deploy,
open the app URL, complete a booking, show the row in Catalog Explorer
(`movies_app_dev.movies.booking_seats`) and via the SQL editor on
`movies_analytics`. Fill README placeholders (app URL). Write
`docs/DEMO_SCRIPT.md`.
Done-check: a booking made through the deployed app is visible in Unity
Catalog; README has no `TODO` left in "Where it runs".

**Phase 6 — Interview artifacts, then stretch (~45 min).**
`docs/ARCHITECTURE.md`, `docs/SCALE_TO_MILLIONS.md`, `docs/DECISIONS.md`,
`docs/AI_USAGE_LOG.md` finalized. Then, only if time remains, in this order:
1. `analytics_job` (sql_task on `movies_analytics` → Delta gold tables in
   `movies_analytics_dev.movies`), run once, show the Delta tables.
2. Cancellation endpoint.
3. Seat holds with expiry.

---

## 7. Commands

**Every `databricks` command runs inside WSL Ubuntu 24.04** (CLI 1.15.0, profile
`movies`). From the Windows shell or the Bash tool, wrap commands like this
(the `dev` target carries `profile: movies`, so bundle commands need no `-p`;
other CLI commands do):

```bash
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/repos/apps/dbx-movies-app/movies_app_bundle && databricks bundle validate -t dev"
```

Inside WSL, from `movies_app_bundle/`:

```bash
# bundle
databricks bundle validate -t dev
databricks bundle summary  -t dev              # deployed resources + URLs
databricks bundle deploy   -t dev
databricks bundle run analytics_job -t dev     # Phase 6

# lakebase
databricks database get-database-instance movies-app-dev -p movies      # state, read_write_dns
databricks database generate-database-credential -p movies --json '{"instance_names":["movies-app-dev"]}'   # 1 h token for psql

# app
databricks apps get movies-app -p movies       # URL, status, service_principal_client_id
# runtime logs: Databricks UI → Compute → Apps → movies-app → Logs
```

**Python for seed / check scripts and the local backend.** WSL Python 3.12
cannot create venvs until the user runs `sudo apt install python3.12-venv`.
Until then use Windows Python 3.13 (has `psycopg` and `databricks-sdk`) and let
the SDK read the WSL profile file. Git Bash syntax, from the repo root:

```bash
DATABRICKS_CONFIG_FILE=//wsl.localhost/Ubuntu-24.04/home/raescoto/.databrickscfg DATABRICKS_CONFIG_PROFILE=movies python movies_app_bundle/src/seed/check_connection.py
DATABRICKS_CONFIG_FILE=//wsl.localhost/Ubuntu-24.04/home/raescoto/.databrickscfg DATABRICKS_CONFIG_PROFILE=movies python movies_app_bundle/src/seed/seed_lakebase.py --app-sp-client-id <client-id>

# local dev (backend), same two DATABRICKS_CONFIG_* vars plus:
export LAKEBASE_INSTANCE=movies-app-dev LAKEBASE_DATABASE=movies LAKEBASE_SCHEMA=movies
cd movies_app_bundle/movies_app && pip install -r requirements.txt && python -m backend.serve

# local dev (frontend) — Windows (Node 22)
cd movies_app_bundle/movies_app/frontend && npm install && npm run dev    # proxies /api → http://localhost:8000
npm run build                                                             # → frontend/dist (must run before deploy)
```

Environment: Windows has Node v22.20.0, npm 10.9.3, Python 3.13.7; the Bash
tool is Git Bash. WSL has Databricks CLI 1.15.0, Python 3.12.3, no `node`. The
Apps runtime is Python 3.11 — avoid 3.12+ only syntax.

---

## 8. Conventions and rules

1. **Thin slice first.** Every phase ends with something demoable. Do not add
   features not listed in §3/§4 without writing a `docs/DECISIONS.md` entry.
2. **Never deploy to a client workspace.** The target must be the Slalom
   workspace in §10. If a command would touch `dbc-2ba89670-78df`, stop.
3. **Never run `bundle destroy`**; only the user does. With `prevent_destroy:
   false` it deletes the Lakebase instance, the catalogs and the warehouse.
4. **No secrets in the repo.** Tokens live in CLI profiles / app resources.
   `.env` files are gitignored; commit `.env.example` only.
5. **Parameterized SQL only.** `%s` placeholders; identifiers are constants.
6. **Keep `app.yaml` env values and bundle variables in sync**
   (instance/database names). The databricks-engineer agent owns that coupling.
7. **State assumptions in code comments where they bite** (token refresh, one
   connection per request, enforced constraints) — the panel will read the code.
8. **Update `docs/AI_USAGE_LOG.md` at the end of every phase**: what was
   generated, what the human changed or rejected, rough share of AI vs human.
9. **Frontend must be built before deploy.** `frontend/dist` is synced by
   explicit include; a stale or missing `dist` shows a blank app.
10. **Windows paths.** Use forward slashes in YAML/config; quote paths with
    spaces.

---

## 9. Interview artifacts to produce (docs/)

- `ARCHITECTURE.md` — one mermaid diagram (browser → app → Lakebase → UC →
  Delta), one table of Databricks services chosen vs alternatives (Apps vs
  external hosting; Lakebase vs Delta-on-warehouse for OLTP; UC registration
  vs ETL; sql_task job vs Lakeflow Declarative Pipeline for gold; DAB direct
  engine).
- `DATA_MODEL.md` — erDiagram + which constraints are enforced (all of them,
  because Postgres) and why the tables are split this way.
- `SCALE_TO_MILLIONS.md` — the production shape: Lakebase capacity
  (CU_2→CU_8, readable secondaries, child instances for branching), seat holds
  with TTL, idempotency keys, connection pooling, CDN + horizontal API scaling,
  synced tables for curated reference data, Lakeflow + Delta for analytics,
  AI/BI dashboards, multi-region, observability via system tables. One page.
- `DEMO_SCRIPT.md` — 5-minute path: open app → pick movie → pick theater →
  seat map → book 2 seats → show the row in Catalog Explorer under
  `movies_app_dev.movies` → re-book the same seats → 409 → show the bundle
  resources in the workspace. Backup: screenshots in `docs/img/`.
- `AI_USAGE_LOG.md` — running log (R8).
- `DECISIONS.md` — ADR list.

---

## 10. Workspace facts

| Item | Value |
|------|-------|
| Demo workspace | `https://dbc-66830d2c-97a4.cloud.databricks.com` (Slalom development/testing; user `ra.escoto@slalom.com`, workspace admin; workspace id `2485046985091381`) |
| CLI | Databricks CLI 1.15.0 in WSL Ubuntu 24.04, profile `movies` (PAT). Bundle engine `direct` |
| Bundle state path | `/Workspace/Users/ra.escoto@slalom.com/.bundle/movies_app_bundle/dev` |
| Lakebase instance | `movies-app-dev` (key `movies_db`), CU_1, PG 16, eu-west-1, port 5432, `sslmode=require`, native password login disabled. Resolve the DNS through the SDK (`get_database_instance(...).read_write_dns`); it changes on every recreate |
| Lakebase database / schema | `movies` / `movies` |
| UC catalog for Lakebase | `movies_app_dev` → `https://dbc-66830d2c-97a4.cloud.databricks.com/explore/data/movies_app_dev?o=2485046985091381` |
| Analytics catalog.schema (Delta) | `movies_analytics_dev.movies` (schema-name fix deployed 2026-09-04) |
| SQL warehouse | `movies_analytics`, id `50b70f5e18138968` (key `movies_analytics_warehouse`; serverless PRO, 2X-Small, auto-stop 20 min) |
| App name | `movies-app` (no collision with existing apps) |
| App URL | `https://movies-app-2485046985091381.aws.databricksapps.com` |
| App service principal client id | `2a26812a-1b82-4879-9487-6eb43f7ad56b` |
| Interview date | TODO |

---

## 11. Tooling notes for Claude

- Model routing: `.claude/settings.json` maps `opus`/`sonnet`/`haiku` to
  Bedrock EU model ids; the session default is Opus.
- **Databricks CLI only via WSL** (`wsl -d Ubuntu-24.04 -- bash -lc "..."`),
  see §7. The Windows-side CLI must not be used for this project.
- The Bash tool on this machine breaks on unbalanced single quotes
  (apostrophes) inside commands and on some long `&&` chains. Write prose
  files with the Write/Edit tools, keep shell commands short.
- `databricks bundle schema` (WSL) is the authority for resource fields.
  Lakebase-related resources: `database_instances`, `database_catalogs`,
  `synced_database_tables`, `apps.*.resources[].database`. `catalogs`,
  `schemas`, `sql_warehouses` are in use; `catalogs` is direct-engine only.
- `databricks-engineer` agent (Sonnet): owns `databricks.yml`, `resources/`,
  `src/seed/`, `src/analytics/`, `app.yaml`. Delegate bundle/Lakebase/UC work
  to it; keep backend and frontend code in the main session.
- `/build-check`: runs `vue-tsc --noEmit` and `vite build` in
  `movies_app_bundle/movies_app/frontend`. Report only, never auto-fix.
- Skills worth using: `code-review` before the user commits each phase,
  `security-review` once before the demo (SQL injection, secret leakage).
