# Decisions

ADR-style log. CLAUDE.md §3 holds the baseline decisions taken before the build
started; this file records decisions taken *during* the build, and any change to
that baseline.

---

## ADR-001 — Enforce the seat/auditorium invariant in the schema as well as the API

**Date:** 2026-09-04 · **Phase:** 2 · **Status:** accepted · **Changes:** CLAUDE.md §4.3, §4.4

### Context

CLAUDE.md §4.3 gave `booking_seats` two independent foreign keys, one to `seats`
and one to `showtimes`. Both resolve to an auditorium, but nothing forced the two
to be the *same* auditorium. Booking seat `aud-05-A01` into a showtime playing in
`aud-01` was therefore representable, and §4.4 step 1 dealt with it by having the
API validate seat membership before writing.

This was found while running the Phase 2 done-check: dumping `pg_constraint`
showed which invariants were actually enforced, and this one was not among them.

The gap matters more than its likelihood suggests. The central architectural
claim of this project is that assigned-seat booking is an OLTP problem and that
its invariants belong in Postgres rather than in application code — that is the
reason the system of record is Lakebase and not Delta. Leaving one invariant to
be patched by the application undercuts exactly the argument the design is built
on, and it is the first thing a reviewer probing the seat model would find.

### Decision

Enforce it in **both** places.

*Schema.* Denormalise `auditorium_id` onto `booking_seats` and point a composite
foreign key down each path:

```sql
CONSTRAINT fk_booking_seats_seat
    FOREIGN KEY (seat_id, auditorium_id)     REFERENCES seats     (seat_id, auditorium_id),
CONSTRAINT fk_booking_seats_showtime
    FOREIGN KEY (showtime_id, auditorium_id) REFERENCES showtimes (showtime_id, auditorium_id)
```

This needs a supporting unique index on each FK target — `uq_seats_id_auditorium`
and `uq_showtimes_id_auditorium`. Both are redundant with the existing primary
keys and exist only so the composite FKs are legal.

*API.* Keep the §4.4 validation. The booking service checks seat membership
before it writes and returns `422` naming the offending seat ids.

### Consequences

- A seat booked into the wrong room is now unrepresentable, not merely rejected.
- The user-facing error stays precise: the app produces a `422` that names the
  seats, rather than surfacing an opaque foreign-key violation.
- Cost is one column and two redundant unique indexes on tables that are small
  and read-mostly. Negligible.
- `ddl.sql` is target-state DDL, not a migration chain, so applying this to an
  existing database means `seed_lakebase.py --recreate`. Acceptable for a
  prototype whose only data is regenerable seed data; a production version would
  carry versioned migrations.

### Alternatives considered

- **API validation only** (the original §4.3). Simpler, one less column — but it
  leaves the guarantee in application code, which is the thing this design
  argues against.
- **A `CHECK` constraint with a subquery.** Postgres does not allow subqueries in
  `CHECK`, so this would need a trigger. More machinery, worse performance, and
  weaker guarantees than a declarative FK.
- **Deriving `showtime_id`'s auditorium at write time and trusting the join.**
  The booking `INSERT … SELECT` already joins `seats` to `showtimes` on
  `auditorium_id`, so a mismatched seat simply produces no row. That is a
  correct check, but it is still application logic, and it fails silently — the
  service must compare row counts to notice.

---

## ADR-002 — `ddl.sql` is target state, not a migration chain

**Date:** 2026-09-04 · **Phase:** 2 · **Status:** accepted

### Context

ADR-001 changed the shape of `booking_seats` after the table already existed.
`CREATE TABLE IF NOT EXISTS` silently does nothing against an existing table, so
a schema change needs either migration DDL or a rebuild.

### Decision

Keep `ddl.sql` as a single readable declaration of the target schema. Handle
schema changes with `seed_lakebase.py --recreate`, which drops the seven tables
and re-applies the DDL, followed by the normal deterministic seed.

### Consequences

- `ddl.sql` stays legible as documentation — it is one of the files a reviewer is
  most likely to read, and interleaving `ALTER`s and `DO` blocks for constraint
  existence checks would obscure it.
- Any real data would be destroyed by a schema change. Acceptable here and only
  here: the data is seed data, deterministic and regenerable byte-for-byte.
- Production would use versioned migrations (Alembic, or numbered SQL files with
  a `schema_version` table). Called out in `SCALE_TO_MILLIONS.md`.

### Note

`--recreate` drops the tables and, with them, their explicit grants. In practice
the app keeps its access on this instance: the first run's
`ALTER DEFAULT PRIVILEGES` persists in `pg_default_acl`, so tables recreated by
the same operator receive the app role's DML automatically (verified live,
2026-09-04). A fresh database, or a different operator, has no such row. The
script therefore warns when `--recreate` runs without `--app-sp-client-id` and
always prints the current grants in its report, so the state is never silent.

---

## ADR-003 — Pin `booking_seats` to its header's showtime; tie `cancelled_at` to `status`

**Date:** 2026-09-04 · **Phase:** 2 (post-review) · **Status:** accepted · **Changes:** CLAUDE.md §2, §4.3; docs/DATA_MODEL.md

### Context

ADR-001 closed the seat ↔ auditorium path but left the booking ↔ showtime path
open. `booking_seats` referenced `bookings` on `booking_id` alone, so a seat row
could carry a different `showtime_id` than its own header. Two showtimes in the
same auditorium satisfy both ADR-001 composite FKs, and a code review proved the
gap live: Postgres accepted the mismatched row.

This was found by a code review one session after the ADR that was specifically
about closing this class of gap. Logged as such in `AI_USAGE_LOG.md`.

A second, smaller gap in the same table: `status` and `cancelled_at` were
independent, so `CANCELLED` without a timestamp, or a timestamp on a `CONFIRMED`
booking, were both representable.

### Decision

The same shape as ADR-001, one relationship over:

```sql
-- bookings
CONSTRAINT uq_bookings_id_showtime UNIQUE (booking_id, showtime_id)

-- booking_seats (replaces the plain booking_id FK)
CONSTRAINT fk_booking_seats_booking
    FOREIGN KEY (booking_id, showtime_id) REFERENCES bookings (booking_id, showtime_id)
    ON DELETE CASCADE
```

and, on `bookings`:

```sql
CONSTRAINT ck_bookings_cancelled_at
    CHECK ((status = 'CANCELLED') = (cancelled_at IS NOT NULL))
```

The CHECK is taken now although cancellation is a stretch feature, because the
FK change already forces a `--recreate`; deferring it would cost a second
rebuild later.

### Consequences

- `booking_seats` is fully pinned: its seat, its showtime and its header are
  forced into agreement by the schema, not by the service.
- A header's `showtime_id` is immutable once it has seats (no `ON UPDATE
  CASCADE`). Moving a booking to another showtime is a new booking, which is
  the intended model.
- Cancellation, when built, must set `status` and `cancelled_at` in one
  `UPDATE`, and the seed script must never touch app-made headers (its total
  recompute is now scoped to seeded ids for exactly this reason).
- One more redundant unique index on `bookings` and one CHECK. Negligible.
- Applied with `seed_lakebase.py --recreate`, per ADR-002.

### Alternatives considered

- **Drop `showtime_id` from `booking_seats` and derive it through the header.**
  Impossible: the double-booking constraint `UNIQUE (showtime_id, seat_id)`
  needs the column on the seat row.
- **Leave it to the booking service**, whose `INSERT … SELECT` uses the same
  showtime parameter for header and seats. Correct today, but application
  logic, which is what this design argues against.

---

## ADR-004 — Build the SPA on the Apps runtime at deploy time

**Date:** 2026-09-04 · **Phase:** 2 → 5 · **Status:** accepted · **Changes:** CLAUDE.md §3, §4.6, §7, rule 9; `databricks.yml`; README

### Context

The baseline (CLAUDE.md §3) served a *prebuilt* SPA: `npm run build` on the
developer machine, `frontend/dist` force-included in the bundle sync, FastAPI
serving the static files. Two problems surfaced in practice:

- Node exists only on the Windows side of this machine and the Databricks CLI
  only in WSL, so every deploy was a two-shell ritual with a "forgot to
  rebuild" failure mode (rule 9 existed only to police it).
- The user proposed, from another working project, building at startup:
  `app.yaml` running `pip install && npm run build && uvicorn`. That works, but
  the Databricks Apps docs show it double-does the platform's own work.

Per the Apps deployment docs, when a `package.json` is present at the app root
every deployment runs, in order and before the `app.yaml` command:
`npm install` (root), `pip install -r requirements.txt`, then `npm run build`
if the root `package.json` defines a `build` script. The runtime ships Node.js
22 next to Python 3.11.

### Decision

- Add a root `movies_app/package.json` with no dependencies and one script:
  `"build": "cd frontend && npm ci --include=dev && npm run build"`. The
  platform runs it at deploy time, producing `frontend/dist` on the container.
- `app.yaml` command stays `["python", "-m", "backend.serve"]`: no shell, no
  install, no build; the port comes from `DATABRICKS_APP_PORT` via `config.py`.
- Drop the `sync.include` for `dist` from `databricks.yml`. `dist/` and
  `node_modules/` remain gitignored and therefore unsynced.
- `--include=dev` because every build tool in `frontend/package.json` is a
  devDependency and the docs warn dev dependencies are skipped in production
  mode. `npm ci` because the lockfile is committed.

### Consequences

- Deploying is WSL-only: `bundle deploy` then `bundle run movies_app`. No local
  build step; a stale `dist` cannot reach the platform.
- Startup stays fast (the §3 argument for a live demo holds): Node runs at
  deploy time, never at process start or restart.
- A type error or build failure fails the *deployment*, visibly, rather than
  the running app.
- Deployments take longer (an `npm ci` of the Vite toolchain plus the build,
  roughly a minute on 2 vCPUs). Acceptable.
- Local `npm run build` and `/build-check` remain useful as a pre-deploy check
  and now mirror exactly what the platform runs.

### Alternatives considered

- **Build at process start in the `app.yaml` command** (the proposal). Works,
  but rebuilds on every start and restart, adds a PyPI and npm network
  dependency to startup, and hardcodes the port. Rejected.
- **Keep the local prebuilt `dist`** (the baseline). Fast and simple on a
  single-OS machine; on this one it is the two-shell ritual. Rejected.
- **A bundle `artifacts` build step.** Runs on the deploying machine at
  `bundle deploy`, which here is WSL without Node. Rejected.

---

## ADR-005 — Inject PGHOST via valueFrom; fix connection leak and error visibility

**Date:** 2026-09-06 · **Phase:** 5 · **Status:** accepted · **Changes:** `app.yaml`, `backend/db.py`, `backend/main.py`, `backend/config.py`

### Context

The deployed app returned 500 on every `/api/*` call that touched Lakebase.
Locally the same code worked, so the issue was specific to the app's service
principal running on the Databricks Apps platform.

Investigation confirmed: the SP's Postgres role existed, had USAGE + full DML
on all 7 tables, and the Lakebase instance was AVAILABLE. But the SP was not
in the database instance's workspace-level ACL (`CAN_USE` / `CAN_MANAGE`);
only `admins` and the owner had those permissions. The `database` app resource
with `CAN_CONNECT_AND_CREATE` creates the Postgres role and grants it
CONNECT/CREATE, but does not grant the workspace-level `CAN_USE` needed to
call `GET /api/2.0/database/instances/{name}`.

The code's `_get_host()` function (in `db.py`) fell back to that SDK call when
`PGHOST` was not set, which it was not: `app.yaml` had no `valueFrom: lakebase`
mapping, and the Databricks Apps documentation confirms PG* vars are not
auto-injected — they must be declared. So every connection attempt started with
a failing API call to resolve the host, and the 500 propagated from there.

### Decision

Three changes:

1. **`app.yaml`:** add `PGHOST` with `valueFrom: lakebase`. For Lakebase
   Provisioned, `valueFrom` resolves to the instance's host DNS. This
   eliminates the `get_database_instance()` SDK call on the platform.

2. **`db.py`:** fix the connection leak in `query()` and `execute()`. Both
   used `with get_connection() as conn:`, which in psycopg 3 commits/rollbacks
   but does not close the connection. Changed to `try/finally` with explicit
   `conn.close()`. Also added `PGPASSWORD` support in `_get_token()` as a
   future-proof path in case the platform ever injects it.

3. **`main.py`:** enhanced `/api/health` to test each connection step
   individually (SDK auth type, host resolution, user resolution, credential
   generation, `SELECT 1`) and report where the failure is. Added a global
   `@app.exception_handler(Exception)` that returns structured JSON on `/api/*`
   500s with the error class and message, instead of an opaque "Internal Server
   Error".

### Consequences

- The app no longer needs workspace-level `CAN_USE` on the database instance to
  connect. The platform resolves the host at deploy time via `valueFrom`.
- `generate_database_credential()` should still work because it checks database
  instance roles (the SP is one), not workspace permissions.
- Connection leak is fixed; each `query()`/`execute()` call now properly closes
  its connection.
- If a future 500 occurs, the response body names the error class and message,
  making platform debugging possible without log access (the `apps logs` CLI
  command requires OAuth, not PAT).

### Alternatives considered

- **Grant `CAN_USE` to the SP via the workspace permissions API.** Attempted;
  the API silently ignored service principals on database instances (the SP
  never appeared in the ACL after PATCH or PUT). A platform limitation or bug.
- **Use the Databricks CLI `apps logs` command.** Requires OAuth authentication;
  the CLI profile uses a PAT. Not available for this debugging session.

---

## ADR-006 — Pool connections while the credential keeps rotating

**Date:** 2026-09-06 · **Phase:** 5 · **Status:** accepted · **Changes:** `backend/db.py`, `backend/main.py`, `backend/config.py`, CLAUDE.md §4.2

### Context

The app authenticates to Lakebase with an OAuth token from
`generate_database_credential()`, valid for roughly an hour. The original
`db.py` opened one connection per request and closed it afterwards, which made
the credential question trivial — mint a token, connect, done — at the cost of
a full TCP + TLS + authentication handshake on every API call. Against a
managed Postgres over TLS that is tens of milliseconds of pure overhead on a
seat-map read that itself takes single-digit milliseconds.

Pooling is the standard answer, but the usual pooling recipe assumes a static
password supplied once when the pool is constructed. Here the password is a
short-lived token that rotates, so a pool built the ordinary way would cache a
credential at construction time and start failing about an hour later — the
worst kind of failure for a demo, because it works perfectly right up until it
does not.

### Decision

Use `psycopg_pool.ConnectionPool`, and move credential resolution from pool
construction to connection construction.

1. **Custom connection class.** `_LakebaseConnection` subclasses
   `psycopg.Connection` and overrides the `connect()` classmethod, which is
   what the pool calls whenever it needs a new physical connection. Host, user
   and token are resolved *inside* that call, so every connection the pool
   opens — at startup, when growing under load, and when replacing an expired
   one — gets a currently valid token. The pool never sees a credential.

2. **Lifecycle in the FastAPI lifespan.** The pool is created lazily and opened
   on startup with `wait=False`, so an unreachable database delays connections
   rather than preventing the app from starting. It is closed on shutdown.

3. **Recycle before the token rotates.** `max_lifetime=45 min` sits below the
   50-minute token cache window in `_get_token()`, which in turn sits below the
   ~60-minute credential validity. A connection is therefore retired while its
   credential is still good.

4. **An escape hatch.** `PG_POOL_ENABLED` (default `true`) reverts to the
   one-connection-per-request path. If pooling misbehaves on the Apps runtime,
   the old behaviour is one environment variable away.

The handlers had to change too. Every `/api` route was `async def` while
calling blocking psycopg, so the whole application serialised on the single
event-loop thread and no more than one pooled connection could ever be checked
out — `max_size: 10` was decoration. The routes are now sync `def`, which makes
FastAPI run them in its threadpool. `tests/test_handlers_nonblocking.py` fails
if one turns back into a coroutine.

Making the handlers concurrent for the first time also made `db.py`'s module
caches (`_ws`, `_host`, `_token`, `_pool`) genuinely shared. They are guarded
by an `RLock` — re-entrant because `_get_token()` holds the lock and calls
`_client()`, which takes it again; a plain `Lock` would deadlock against
itself. Those races existed all along but were unreachable while everything ran
on one thread.

The pool stays synchronous. An `AsyncConnectionPool` would have to run the
blocking Databricks SDK calls inside `connect()`, putting the block back on the
event loop where it hurts most.

### Consequences

- The handshake leaves the critical path. Measured on the real ASGI app, four
  concurrent 300 ms queries went from 1.21 s to 0.32 s; reverting a single
  handler to `async def` restores the 1.21 s.
- On the deployed app a full browse-and-book session used three physical
  connections. The pool grew past `min_size`, which `psycopg_pool` only does
  when every existing connection is checked out — so requests genuinely
  overlapped on the platform — and every connection came back, including
  through the rollback path.
- `/api/health` reports `pool.get_stats()`, so pool state is visible without
  runtime log access.
- The app is now sensitive to a setting it did not have before: pool exhaustion
  is a new failure mode (see *Deferred* below).

### Alternatives considered

- **A static Postgres password.** Native password login is disabled on the
  instance, and CLAUDE.md §8.4 rules out storing one. `PGPASSWORD` is supported
  as a documented fallback but is not used.
- **Refresh the token on a background timer and rebuild the pool.** More moving
  parts, a window where the pool holds a dead credential, and it still needs
  the per-connection hook to be correct.
- **`AsyncConnectionPool` with async handlers.** Rejected above: the SDK calls
  are blocking, so this moves the block onto the event loop.
- **No pooling.** The honest baseline, and what `PG_POOL_ENABLED=false` still
  gives. Correct, just slower per request.

### Deferred

Known and accepted for the prototype, in rough priority order. None of these
affect the demo path; all are cheap to fix if pooling is revisited.

| # | Issue | Why it is tolerable now |
|---|-------|-------------------------|
| 1 | `/api/health` has two identical `if/else` branches and always opens a direct connection, so it never exercises the pool it reports on | The stats it prints still come from the real pool; only the `SELECT 1` bypasses it |
| 2 | `get_stats()` on an unopened pool still reports `pool_size: 2`, so a `PoolClosed` pool reads as healthy | The lifespan opens the pool; a closed pool means the app failed to start |
| 3 | `_LakebaseConnection.connect()` sets `connect_timeout=15` unconditionally, clobbering the per-attempt timeout `psycopg_pool` passes in | Only matters when the host is slow enough to exceed the pool's own 10 s budget |
| 4 | `max_lifetime` counts from connect time, not from token issuance, so a connection can in principle outlive its credential | The 45 / 50 / 60-minute margins absorb it |
| 5 | ~~FastAPI's threadpool is 40 threads against `max_size: 10` with `timeout: 10`, so heavy load raises `PoolTimeout` → 500 rather than a graceful 503~~ | **Resolved by ADR-008** |
| 6 | `PG_POOL_*` is absent from `app.yaml`, so the escape hatch needs a redeploy anyway | A redeploy is two minutes |
| 7 | `execute()` is unused, and the `if not pg_pool_enabled` branch is duplicated across all three helpers in `db.py` | Dead code, not wrong code |

---

## ADR-007 — Drop the cancellation endpoint from scope

**Date:** 2026-09-07 · **Phase:** 6 · **Status:** accepted · **Changes:** CLAUDE.md §3, §4.5

### Context

`DELETE /api/bookings/{id}` was carried through the whole build as a stretch
item: CLAUDE.md §4.5 lists it in the API contract, the schema already supports
it (`bookings.status`, `cancelled_at`, and the `ck_bookings_cancelled_at` check
that keeps the two in step; `booking_seats` cascades on delete so cancelling
frees the seats), and the frontend already renders a `CANCELLED` booking.

It was never implemented. With the remaining budget going to the analytics job
and the interview artifacts, the choice is to build it or to stop listing it.

### Decision

Cancellation is out of scope. The endpoint will not be built.

The schema support stays exactly as it is. It costs nothing, it is already
deployed, and it is the honest answer to "how would you cancel?" — the design
question the panel is likely to ask is about the *data model*, and the model
already answers it: the unique constraint lives on `booking_seats` rather than
on a status-aware partial index precisely so that deleting seat rows frees the
seats while the header survives as an audit trail.

### Consequences

- One less endpoint than CLAUDE.md §4.5 advertises. That section and the
  README's API table both need the row marked as not built rather than
  "stretch".
- `GET /api/bookings/{id}` still reads a cancelled row correctly, and there is
  a test for it, so a row cancelled by hand in SQL demonstrates the flow end to
  end without an endpoint.
- Nothing in the write path or the seat map assumes bookings are immortal.

### Alternatives considered

- **Build it anyway.** It is genuinely small — one `UPDATE ... RETURNING` plus
  a `DELETE`, inside the existing `transaction()` helper. Rejected on budget:
  the analytics job is the last unbuilt piece of the *stated* architecture, and
  a missing gold table is a bigger hole in the story than a missing DELETE.
- **Leave it listed as "stretch".** Rejected: a contract that advertises an
  endpoint the code does not serve is worse than a contract that says the
  feature was cut deliberately.

---

## ADR-008 — Size the threadpool from the pool; a saturated pool is a 503

**Date:** 2026-09-07 · **Phase:** 6 · **Status:** accepted · **Changes:**
`backend/config.py`, `backend/db.py`, `backend/main.py`; closes ADR-006
Deferred item 5

### Context

ADR-006 pooled connections and moved the API handlers to sync `def` so FastAPI
runs them in its threadpool — anyio's default, 40 threads. That number was
never chosen with this app in mind; it is anyio's own default, picked with no
knowledge of `PG_POOL_MAX=10` or the pool's `timeout`. Once all 10 pooled
connections are checked out, the other threads queue inside psycopg_pool's own
wait list, park for up to the timeout, and raise `psycopg_pool.PoolTimeout`.
That exception was unhandled, so it fell into `main.py`'s catch-all
`@app.exception_handler(Exception)` and came back as a `500` with the driver's
raw message — a client-facing "server is broken" for what is actually the
pool correctly refusing to over-admit work. Logged as ADR-006 Deferred item 5,
tolerated at the time because demo traffic is one browser.

Two things were accidental, not one: the threadpool size had no relationship
to the two numbers that actually bound this app's DB concurrency (pool size,
pool timeout), and the failure mode did not distinguish "the code is wrong"
from "the pool is full right now."

### Decision

**1. Size the threadpool from the pool.** `config.py` pulls the pool's
`timeout` out of its literal `10` inside `db.py`'s `ConnectionPool(...)` into
`pg_pool_timeout` (env `PG_POOL_TIMEOUT`, default `10`), and adds
`api_thread_pool_size` (env `API_THREAD_POOL_SIZE`), defaulting to
`pg_pool_max + 4`. `main.py`'s lifespan sets
`anyio.to_thread.current_default_thread_limiter().total_tokens` to it on
startup — inside the lifespan because anyio scopes the limiter to the running
event loop, and the lifespan runs on the loop that goes on to serve requests —
and logs a warning if it is ever configured below `pg_pool_max`, since pooled
connections would then sit idle no matter the load.

The `+4` headroom is for blocking work that does not go through the pool —
chiefly `/api/health`'s direct `get_connection()` call — so a health check
does not compete with pooled requests for the same thread budget. It is
deliberately small. The reason to bound the threadpool close to `pg_pool_max`
at all, rather than leave generous slack, is that once the pool is full the
*next* request should queue cheaply as a suspended coroutine waiting for a
thread token — no OS thread, no contention on the pool's own wait queue —
instead of piling up as a thread parked inside psycopg_pool for the full
`pg_pool_timeout`. A wide gap between the two numbers (40 vs. 10) turns pool
saturation into thread saturation as well.

**2. `PoolTimeout` is backpressure, not a fault.** `main.py` registers
`@app.exception_handler(psycopg_pool.PoolTimeout)`, returning `503` with
`Retry-After: 2` and a structured body (`{"detail": ..., "error":
"PoolTimeout"}`), instead of falling through to the generic `500` handler.
Starlette resolves exception handlers by walking the raised exception's MRO,
so registering the specific handler is enough regardless of where it sits
relative to the catch-all — no dispatch logic needed in the generic handler
itself. `Retry-After` is a short fixed hint (2s), not `pg_pool_timeout` itself:
a request that reached this handler already waited up to `pg_pool_timeout` for
a connection, so telling it to wait that long again would compound the
latency instead of giving the pool a chance to drain.

**3. `/api/health` reports all three numbers** (`pg_pool_max`,
`pg_pool_timeout`, `api_thread_pool_size`) so the relationship is visible at
runtime, not only in code.

### Consequences

- A saturated pool now surfaces as `503` with a machine-readable
  `error: "PoolTimeout"` and a retry hint, distinguishable from a genuine bug
  (`500`) by both status code and response shape.
- The threadpool no longer over-admits relative to what the pool can actually
  serve; concurrency beyond `api_thread_pool_size` queues at the cheap anyio
  layer instead of the expensive, OS-thread-holding pool layer.
- One more pair of env vars to keep in sync if `PG_POOL_MAX` changes —
  mitigated by deriving the default from `pg_pool_max` rather than hardcoding
  it, and by the startup warning if the two are set inconsistently.
- `tests/test_pool_backpressure.py` pins the response shape, the header, the
  threadpool-sizing function, and the config defaults (16 cases).

### Alternatives considered

- **Leave the threadpool at anyio's default and only fix the response code.**
  Fixes the client-visible symptom but leaves ~30 threads free to pile up
  waiting on 10 connections under load, each parked for the full timeout —
  worse behaviour under saturation than admitting fewer requests up front.
- **`Retry-After` equal to `pg_pool_timeout`.** Correct in spirit, needlessly
  slow in practice: a connection freed a moment after the timeout fires would
  leave the client waiting far longer than necessary for its retry.
- **An app-level semaphore in front of the router**, independent of anyio's
  limiter. More explicit, but duplicates a limiter FastAPI/anyio already
  provide for exactly this purpose. Rejected as unnecessary machinery.

---

## ADR-009 — The analytics layer: federated live reads, Delta gold for AI/BI, and a seed that carries a signal

**Date:** 2026-09-07 · **Phase:** 7 · **Status:** accepted · **Changes:**
`src/seed/seed_lakebase.py`, `src/analytics/gold.sql`,
`src/dashboards/movies_operations.lvdash.json`,
`src/genie/movies_demand.geniespace.json`, `resources/analytics_job.yml`,
`resources/analytics_ui.yml`

### Context

The README described a lakehouse side of the architecture that did not exist:
Delta gold tables, and the claim that the Unity Catalog registration bridges
OLTP and analytics. The remaining demo goal was to make that real, and to add
the two Databricks-native surfaces the panel will recognise — an AI/BI
dashboard showing cinemas filling up, and a Genie space that answers
programming questions in natural language ("where and for which movies should
we open new functions?").

Three things had to be settled before any of it could be built.

**1. Where does "live" data come from?** A dashboard tile showing seats selling
in real time can either read the OLTP tables directly or read a materialised
copy on a refresh cycle. Verified on the platform first: a serverless SQL
warehouse can query `movies_app_dev.movies.*` — the Lakebase database
registered in UC — live, with no ETL step
(`SELECT count(*) FROM movies_app_dev.movies.booking_seats` returns the row a
booking committed a second ago).

**2. The seed had no signal to find.** The original generator booked 2–4 random
parties per showtime on the first two days only: 132 seats across 70 showtimes
of 120 seats, uniform across every movie, theater and slot. Every auditorium
would have rendered ~95% empty, and "which movie deserves more showings?" would
have been answered by whichever combination the RNG happened to favour. That is
not a platform problem, it is a data problem, and it would have made both new
surfaces worthless — worse than worthless in front of a panel that asks "why
that recommendation?"

**3. Neither AI/BI asset validates its own definition.** Probing the Lakeview
API with `"widgetType": "flurb"` produced a `200`. Dashboard specs are stored,
not checked, so a successful deploy proves only that the JSON parsed.

### Decision

**1. Two paths, by temperature.** The hot path is federated: the four "Live
operations" datasets read `movies_app_dev.movies` through UC, so a seat booked
in the app appears on the next dashboard refresh with no pipeline in between.
The cold path is materialised: `analytics_job` (one `sql_task`) builds three
Delta tables in `movies_analytics_dev.movies` — `showtime_occupancy` (per
showtime), `demand_by_movie_theater_slot` (per movie × theater × slot, settled
shows only) and `revenue_by_day`. Genie reads only the gold tables, never the
federated ones, so there is exactly one way to compute a metric.

**2. The seed encodes a demand model, and says so.** `PROGRAMMING` in
`seed_lakebase.py` is an explicit grid of which auditorium runs which movie in
which of four daily slots, over a 21-day window (14 days of settled history,
the 7 bookable days the app exposes). Occupancy per showtime is the product of
declared factors — movie popularity, slot, theater, weekend, a matinee/late
genre bonus — times a lead-time curve for shows that have not happened yet,
capped at `MAX_FUTURE_OCCUPANCY = 0.94` so the demo can always still book a
seat. Seats fill centre-out from the good rows, and `created_at` is backdated
to a plausible moment before each show rather than left at "when the seed ran".

Two gaps in the grid are deliberate and are the answer to the Genie question:
Iron Meridian sells out evenings in `aud-01` while `aud-02` next door gives its
evening screen to a low-demand romance and runs no late show at all, and Harbor
Point never plays the strongest title in the chain. Result: 357 showtimes, 6,597
bookings, 15,526 sold seats; settled shows average 42.8% full, upcoming 22.4%;
Iron Meridian evenings at Slalom Cinema Downtown run 97.1% with a 78.6% sellout
rate, against 8.7% for documentary matinees at Harbor Point.

This is stated out loud in the demo: the seed plants a signal, the analytics
layer discovers it, and it is never told where to look.

**3. Genie is configured as code, with the reasoning written down.** The
`genie_spaces` bundle resource carries `data_sources` plus one instruction block
that defines the glossary (a *function* / *función* / *screening* is a showtime,
never a SQL function), the aggregation rule (percentages of different
denominators must be recomputed, never averaged), the ranking procedure for
programming questions (minimum three showtimes offered; always answer with
movie **and** theater **and** slot), and the caveats worth stating (settled vs
still-selling; a missing row means "never scheduled here", not "no demand").
Table and column `COMMENT`s in `gold.sql` carry the schema semantics.

**4. Verification is explicit, because the platform will not do it.** Every
dashboard dataset is executed against the warehouse and every widget field
reference is cross-checked against the returned columns before the dashboard is
believed. The Genie space is verified by asking it the actual demo question
through `genie start-conversation` and reading back the SQL it generated.

### Consequences

- The demo can show a booking made in the app appearing in a dashboard tile
  seconds later, with the honest explanation that nothing moved the data.
- Asked "Where and for which movies should we open new functions based on
  popularity?", the deployed space produced the canonical query from its
  instructions and answered with Iron Meridian evenings at Downtown (97.1%,
  78.6% sellout, 14 showtimes, $1,809/showtime) and Lakeview (90.8%) — movie,
  theater, slot, sample size and value, which is an actionable answer rather
  than a chart.
- The dashboard's **rendering** is not machine-verifiable. It was opened, and
  every tile failed — see *Lakeview's `queryLines`* below. Fixed and redeployed;
  the datasets are now verified the way the runtime actually executes them.
- The seed now writes ~22k rows and takes noticeably longer than the old one.
  Still seconds, but `--reset` is no longer instant.
- `docs/DATA_MODEL.md` describes the OLTP schema only; the gold tables are
  described by their own `COMMENT`s, which is what Genie reads.

### Genie's v2 export format, learned by probing

Undocumented in the CLI help and worth recording, since a bundle deploy fails
on each of them in turn: `serialized_space` requires `"version": 2`;
`data_sources.tables` **must be sorted by identifier**;
`instructions.text_instructions` **must be sorted by id** and **must contain at
most one item**; ids must be lowercase 32-hex without dashes. There is no field
for sample questions or example SQL in this version, which is why the canonical
query lives inside the instruction text.

### Lakeview's `queryLines`, learned the hard way

A dataset's `queryLines` are concatenated **with no separator**, and the result
is then wrapped as `WITH q AS ( <dataset sql> ) SELECT ... FROM q`. Every line
must therefore carry its own trailing `\n`. Without them the first deploy
produced `movie_idJOIN`, `current_timestamp()GROUP BY`, `rCROSS JOIN`, and — for
the one dataset that opened with a `--` comment — a `PARSE_EMPTY_STATEMENT`,
because the entire query became a single comment line. Every tile on both pages
failed.

The failure survived the first round of verification because that verification
was wrong in the same direction as the bug: it joined `queryLines` with `\n`
before executing them, which is exactly what the runtime does not do. A check
that reformats its input is not a check. The verification now concatenates with
`""` and applies the `WITH q AS (...)` wrapper, so it executes character-for-
character what the dashboard executes — which also exercises the nested-CTE case
for the datasets that begin with their own `WITH`.

Generalising: the two AI/BI surfaces fail in opposite ways. Genie validates its
export strictly and rejects a bad definition at deploy time. Lakeview stores
whatever it is given — an invented `widgetType` returns `200` — so for a
dashboard the deploy is not evidence of anything, and the only real checks are
executing each dataset exactly as the runtime will, and looking at the page.

### Alternatives considered

- **Materialise everything and let the dashboard read only Delta.** One code
  path, but it puts a refresh cycle between the booking and the tile and throws
  away the most interesting thing the architecture can demonstrate — that the
  UC registration makes the OLTP store queryable without a pipeline.
- **Point Genie at the federated Lakebase tables too.** Rejected: two ways to
  compute occupancy, no column comments on the foreign catalog, and a much
  larger surface for Genie to get lost in.
- **Ship an `expansion_candidates` gold table.** Precomputing the recommendation
  would make the Genie demo a lookup and would read as staged. The ranking lives
  in Genie's instructions, with the dashboard tile as the fallback if the model
  wanders live.
- **Leave the seed uniform and let the panel discount the analytics.** Rejected;
  see Context. Shaping the distribution and disclosing it is more defensible
  than presenting noise as a finding.
- **Author both assets in the workspace UI and only then generate them into the
  bundle.** The documented round-trip
  (`databricks bundle generate dashboard | genie-space --resource ... --force`)
  is still the intended edit loop, but starting from code meant the assets could
  be built, deployed and verified without a browser.
