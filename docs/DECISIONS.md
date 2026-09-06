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

## ADR-006 — Connection pooling with dynamic credentials

**Date:** 2026-09-06 · **Phase:** 5 · **Status:** accepted · **Changes:** \ackend/db.py\, \ackend/main.py\, \ackend/config.py\, \CLAUDE.md\

### Context

The application connects to Lakebase using an OAuth token generated via \generate_database_credential()\, which is valid for approximately one hour. Initially, the application used a "one connection per request" strategy because connection pooling with static kwargs would capture a token at pool initialization, leading to authentication failures after the token expires (typically within an hour). However, for production scale, opening a new Postgres connection per request introduces significant latency overhead.

### Decision

Implement connection pooling using \psycopg_pool.ConnectionPool\, but handle the dynamic nature of the credentials by subclassing \psycopg.Connection\. 

1. **Custom Connection Class:** Created \_LakebaseConnection\ inheriting from \psycopg.Connection\. By overriding the \connect()\ classmethod, the token is fetched dynamically *every time the pool opens a new connection*. This leverages the existing 50-minute token cache cleanly.
2. **Pool Lifecycle:** \ConnectionPool\ is instantiated lazily and hooked into FastAPI's \lifespan\ context manager so it safely opens on startup (\wait=False\ to prevent crashing on DB unavailability) and closes on shutdown.
3. **Pool Settings:** Configured with \max_lifetime=45*60\ to ensure connections are recycled *before* the 50-minute token cache rotation, avoiding any risk of a connection outliving its underlying credential logic.
4. **Fallback Hatch:** Introduced a \PG_POOL_ENABLED\ (default \	rue\) environment variable. If pooling fails in the Apps environment, flipping this variable reverts to the direct-connect path without requiring a code change.

### Consequences

- **Performance:** Connection establishment overhead is removed from the critical path of each API request.
- **Robustness:** Token rotation happens seamlessly as the pool scales or recycles older connections.
- **Observability:** Added \pool.get_stats()\ to \/api/health\ so the live pool state (size, available, waiting) is visible in the Databricks Apps environment.
- **Code Clarity:** The \	ransaction()\, \query()\, and \xecute()\ helpers were updated to use the pool's context manager, natively inheriting its strict rollback-on-exception and clean return-to-pool guarantees.
