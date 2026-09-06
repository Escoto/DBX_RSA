# AI Usage Log

Running log of what AI (Claude) generated, what the human changed or rejected,
and rough share of AI vs human effort. Kept current per phase (requirement R8).

---

## Phase 1 — App resource + skeleton (2026-09-04)

**What AI generated (~90% of Phase 1 code):**

- `movies_app/backend/` — `__init__.py`, `serve.py`, `main.py`, `config.py`,
  `db.py`. FastAPI app with `/api/health` endpoint, Lakebase connection factory
  with OAuth token caching, SPA history-mode fallback.
- `movies_app/frontend/` — full Vue 3 + Vite + TypeScript scaffold: `package.json`,
  `vite.config.ts`, tsconfig files, `index.html`, `App.vue`, `HomeView.vue`,
  `tokens.css` (carried from `movies_app_vue/`).
- `resources/app.yml` — Databricks App resource with lakebase and sql-warehouse
  bindings.
- `movies_app/app.yaml` — app entrypoint and env config.
- `movies_app/requirements.txt` — Python dependencies for the Apps runtime.
- This file (`docs/AI_USAGE_LOG.md`).
- Updates to `CLAUDE.md` §10 (app URL, SP client id, schema fix status).

**What the human provided:**

- `CLAUDE.md` — the full architecture spec, data model, API contract, build plan,
  and deployment instructions. This document drove all of Phase 1.
- `lakehouse.yml` schema-name fix (already applied before this session).
- `check_connection.py` — existing credential/connection logic reused in `db.py`.
- `tokens.css` — existing design tokens reused in the frontend.
- Infrastructure already deployed (Lakebase instance, UC registration, catalogs,
  SQL warehouse) from prior sessions.
- Review and commit of all generated files.

**What was changed or rejected:** TBD (human to fill in after review).

**Rough split:** ~70% AI, ~30% human (architecture, spec, infra, review).

---

## Phase 2 — Data layer (2026-09-04)

**What AI generated (~95% of Phase 2 code):**

- `src/seed/ddl.sql` — schema and 7 tables with all constraints and indexes,
  written as idempotent target-state DDL.
- `src/seed/seed_lakebase.py` — SDK credential path reused from
  `check_connection.py`, deterministic seed generation (`Random(42)`, derived
  ids, `uuid5` booking ids), idempotent upserts, `--reset` / `--recreate`, and
  the Postgres grants for the app service principal via `psycopg.sql.Identifier`.
- `docs/DATA_MODEL.md` — ER diagram, the enforced-invariants table, query shapes.
- `docs/DECISIONS.md` — ADR-001 and ADR-002.
- Throwaway verification scripts (constraint probing, UC round-trip) — run, not
  committed.

**Where the human intervened — the substantive one:**

AI implemented the data model exactly as CLAUDE.md §4.3 specified it, then found
a gap while running the phase's own done-check: dumping `pg_constraint` showed
that nothing in the schema stopped a seat from one auditorium being booked into
a showtime playing in another. The spec handled this in application code.

AI surfaced the gap with two options — enforce it in the schema, or keep the
spec's application-level check. **The human rejected the binary and asked for
both**: business logic in the app for a good error message, the database
constraint as the backstop. That is the better answer and it is now the design
(ADR-001) — the app returns a precise `422` naming the offending seats, and the
composite FKs make the bad state unrepresentable regardless.

Worth saying out loud in the demo: the AI found the gap but framed it as a
trade-off between two options; the human's defence-in-depth answer was better
than either.

**Other human input:** the CLAUDE.md spec that drove the phase, the naming
conventions, and the standing instruction to log decisions as ADRs.

**Rough split:** ~85% AI (code, DDL, docs, verification), ~15% human (spec,
the defence-in-depth call, review).

---

## Phase 2 addendum — code review of the data layer (2026-09-04)

**What happened:** a second AI pass (Claude Opus, `/code-review`) over the
Phase 2 output reported five findings, two of them verified against the live
database rather than by inspection. A third AI pass (Claude Fable) reviewed the
review before anything was changed, and re-probed the database read-only.

**The finding that mattered.** ADR-001 closed the seat ↔ auditorium gap and was
written as the ADR about closing exactly this class of gap. The same session
left the neighbouring one open: `booking_seats` referenced its header on
`booking_id` alone, so a seat row could name a different showtime than its
booking. The review proved it live. The fix is the ADR-001 shape one
relationship over (ADR-003). An honest data point: AI found and fixed one
instance of a pattern, wrote it up, and missed the second instance in the same
table. Review by a second pass caught it; the human had not.

**Where the second review was wrong, and the third caught it.** The review
claimed `--recreate` drops the app's grants. Probing `pg_default_acl` showed the
owner's `ALTER DEFAULT PRIVILEGES` persists, so recreated tables get the grants
back automatically on this instance; only a fresh database is exposed. The
fix shrank from a hard guard to a warning plus a grants section in the report,
and the ADR-002 note was corrected.

**Human decisions:** take four of the five findings now rather than the two the
review proposed (the schema rebuild was happening anyway, so the `cancelled_at`
CHECK and the scoped total recompute ride along); keep the rolling showtime
window and document the re-run behaviour instead of pinning dates; run the
`--recreate` and the git cleanup by hand from the console.

**Files touched:** `ddl.sql`, `seed_lakebase.py`, `main.py` (a comment),
`DECISIONS.md` (ADR-003, ADR-002 note), `DATA_MODEL.md`, `CLAUDE.md` §2/§4.3,
`README.md`, this file.

**Rough split for the addendum:** ~90% AI (review, counter-review, edits),
~10% human (the four-of-five call, the rolling-window call, execution).

---

## Deploy flow — build the SPA on the platform (2026-09-04)

**Human input:** the user brought a pattern from another working project: a
root `package.json` plus an `app.yaml` command that ran `pip install`, `npm run
build` and `uvicorn` in a shell at startup, and asked for a review.

**What AI did:** instead of judging the pattern from memory, it read the
Databricks Apps deployment, dependencies, runtime and system-environment docs
and found that a root `package.json` already makes the platform run `npm
install`, `pip install` and `npm run build` before the `app.yaml` command. The
proposal was therefore doing the platform's work a second time at every process
start, and hardcoded the port. AI recommended keeping the user's root
`package.json` (the part that mattered) and reverting the command to `python -m
backend.serve`, plus `npm ci --include=dev` for the devDependency caveat in the
docs. Written up as ADR-004, with CLAUDE.md, README and `databricks.yml`
updated to match.

**Outcome:** the user's instinct (stop building on the laptop) was right and
removed a real two-shell failure mode; the docs check moved the build from
startup to deploy time, which keeps the fast-startup argument from CLAUDE.md §3.

**Rough split:** ~50/50. The human supplied the working pattern and the
direction; AI supplied the docs check and the corrected shape.

---

## Phase 3 — Backend routers, booking service, and tests (2026-09-05)

**What AI generated (~95% of Phase 3 code):**

- `backend/models.py` — Pydantic v2 request/response models for the full
  §4.5 API contract: `Movie`, `Theater`, `Showtime` (with joined names),
  `SeatMapResponse` (grouped by row, each seat with price by type and
  booked/available status), `CreateBookingRequest` (with 1–8 seat validation),
  `Booking` (with nested `BookingSeat` list).
- `backend/routers/catalog.py` — `GET /api/movies`, `GET /api/movies/{id}`,
  `GET /api/theaters`, `GET /api/showtimes` with `movie_id`/`theater_id`/`date`
  filters and joined movie, theater and auditorium names; past showtimes
  excluded by default.
- `backend/routers/seats.py` — `GET /api/showtimes/{id}/seats`: the §4.3 LEFT
  JOIN seat map, grouped by row, priced by seat type from the showtime.
- `backend/routers/bookings.py` — `POST /api/bookings` (delegates to the
  service, catches `ValidationError` → 422 and `ConflictError` → 409 with
  `taken_seat_ids`), `GET /api/bookings/{id}` (header + seats).
- `backend/services/booking_service.py` — the §4.4 transaction exactly:
  validate (showtime exists and is future, 1–8 unique seats in the right
  auditorium), one transaction (INSERT header, INSERT…SELECT seats with pricing,
  rowcount guard, UPDATE total), `UniqueViolation` → rollback → re-query taken
  seats → `ConflictError`. All SQL parameterised with `%s`.
- `tests/test_booking_service.py` — 6 tests against a fake connection/cursor:
  happy path, unique-violation → `ConflictError` with the right seat ids,
  showtime not found, past showtime, invalid seats, duplicate seat ids.
- `requirements-dev.txt` — includes `requirements.txt` plus `pytest`.
- Updated `backend/main.py` to register the three routers above the SPA mount.
- Updated `CLAUDE.md` §2 with Phase 3 state.
- This log entry.

**What the human provided:**

- `CLAUDE.md` — the full architecture spec (§4.2–§4.5) that defined the router
  layout, API contract, booking write path, seat map query, and the comment
  policy for assumptions.
- The working dev environment: WSL Python 3.11 venv, Makefile, Lakebase
  credentials and seed data already in place.
- The done-check criteria: which showtime and what responses to expect.
- Review and commit of all generated files.

**What was changed or rejected:** TBD (human to fill in after review).

**Verification against the live Lakebase (2026-09-05):**

- `GET /api/movies` → 8 movies
- `GET /api/theaters` → 3 theaters
- `GET /api/showtimes` → 60 future showtimes (past excluded)
- `GET /api/showtimes/st-d1-s0-aud-01/seats` → 120 seats (115 available,
  5 booked by the seed)
- `POST /api/bookings` (seats `aud-01-A01`, `aud-01-A02`) → 201, booking id
  `6c5179dc-997b-4ea8-b966-c34668386b86`, total $24.00
- `POST /api/bookings` (same seats) → 409,
  `taken_seat_ids: ["aud-01-A01", "aud-01-A02"]`
- `GET /api/bookings/{id}` → header + 2 seats
- Seat map re-fetch confirms both seats now booked
- `pytest` → 6/6 passed

**Rough split:** ~90% AI (code, tests, verification), ~10% human (spec,
environment, review).

## Phase 4 — Frontend routes and seat map (2026-09-05)

**What AI generated (~95% of Phase 4 code):**

- `frontend/src/services/api.ts` — typed client mirroring `backend/models.py`
  one-to-one; `ApiError` carries the HTTP status, a human-readable `detail`
  (string or flattened pydantic error list) and `takenSeatIds` for the 409.
- `frontend/src/router.ts` — the four §4.5 routes with `props: true`, a
  catch-all redirect to `/`, scroll-to-top.
- `frontend/src/composables/useAsync.ts` — loading/error/data state per
  request; no state library, as decided in §3.
- `frontend/src/utils/format.ts` — USD and UTC-pinned date/time formatters,
  `dateKey` for grouping showtimes by UTC day, `seatLabel`.
- `frontend/src/components/SeatMap.vue` — presentational seat grid (screen
  arc, row labels both sides, legend). Booked seats disabled, selected and
  "just taken" seats highlighted, premium/accessible styled by type, a max-seat
  cap that disables the rest of the map at 8.
- `frontend/src/components/PosterImage.vue` — poster with an `@error`
  fallback to a gradient + initial (picsum was unreachable from the sandboxed
  browser during verification).
- `frontend/src/components/StateBlock.vue` — shared loading / error + retry.
- Views: `MoviesView` (grid), `MovieView` (theater chips filter client-side,
  showtimes grouped by day), `ShowtimeView` (seat map + running total +
  customer form; a 409 re-fetches the map, drops the lost seats from the
  selection, marks them red and explains), `BookingView` (confirmation with
  movie/room/time pulled from the seat-map endpoint, seats and total, links
  back to the seat map and the grid).
- `App.vue` header with a home link; `HomeView.vue` placeholder deleted.
- `CLAUDE.md` §2 Phase 4 state and this log entry.

**What the human provided:**

- `CLAUDE.md` §4.5 (routes, seat-map behaviour including the 409 re-fetch),
  §3 (USD/UTC, no Pinia, max 8 seats) and the existing `tokens.css`.
- The Phase 3 backend and live Lakebase to click against.
- Review and commit of all generated files.

**What was changed or rejected:** TBD (human to fill in after review).

**Verification (2026-09-05, local backend on :8000 serving `dist`, live
Lakebase):**

- `vue-tsc --noEmit` and `vite build` pass (`/build-check` equivalent).
- Grid → "A Year of Tuesdays" → theater filter "Slalom Cinema Downtown" narrows
  8 showtimes to 3 → seat map for `st-d2-s0-aud-02` (120 seats, premium rows
  E–G, accessible seats at the ends of row A).
- Selected E5 + E6, total $34.00. A rival `curl` booked `aud-02-E05` first.
  UI POST → 409: E5 rendered red as "just taken", the map refreshed, E6 stayed
  selected, total $17.00, message "Some seats are already booked: E5".
- Second POST → 201, routed to `/bookings/cd02dc6d-9658-41cd-9080-825183317f39`
  showing movie, when, room, customer, seat E6, total $17.00.
- Direct navigation to `/showtimes/st-d2-s0-aud-02` (history fallback) shows
  E5 and E6 booked. Mobile preset stacks the side panel under the map.

**Rough split:** ~90% AI (code, styling, verification), ~10% human (spec,
design tokens, review).

---

## Phase 5 — Deploy + debug Lakebase connection on the platform (2026-09-06)

**What AI did (~95% of the debugging and fix):**

- Diagnosed why the deployed app returned 500 on every API call touching
  Lakebase while working locally. Could not access the app directly (Databricks
  Apps requires OAuth, not PAT) or the runtime logs (`apps logs` needs OAuth).
- Connected to Lakebase as the owner and verified: SP Postgres role exists with
  USAGE + full DML on all 7 tables; instance AVAILABLE; all grants intact.
- Discovered the SP was absent from the database instance's workspace-level ACL
  (only `admins`, the owner, and the `users` group with `CAN_CREATE`).
  Attempted to grant `CAN_USE` via the permissions API; the API silently
  ignored service principals on database instances.
- Read the Databricks Apps documentation (resources page, environment variables
  page) and found that `valueFrom: lakebase` for a Lakebase Provisioned
  database resolves to the host DNS, and that PG* vars are NOT auto-injected —
  they must be declared explicitly in `app.yaml`.
- Root cause: `app.yaml` had no `PGHOST` mapping, so `db.py` fell back to
  `get_database_instance()` via the workspace API, which the SP can't call
  (no `CAN_USE`). The host resolution failed, making every connection attempt
  500.
- Fix (ADR-005): added `PGHOST` with `valueFrom: lakebase` to `app.yaml`.
  Also fixed the psycopg 3 connection leak in `query()`/`execute()`, added
  `PGPASSWORD` support as a future-proof fallback, enhanced `/api/health` with
  step-by-step diagnostics (SDK auth type, host, user, token, connection), and
  added a global exception handler for structured 500 responses on `/api/*`.
- `bundle validate` passes; all 6 tests pass; local smoke test (health, movies,
  showtimes) succeeds.

**What the human provided:**

- The bug report with structured debug steps.
- The standing constraints: WSL for Databricks CLI, no `bundle destroy`, no
  Windows CLI.
- Deployment and verification against the live platform (pending).

**Verification (pending):**

- `bundle deploy -t dev` then `bundle run movies_app -t dev`
- Open the app URL, hit `/api/health` — expect `status: ok`,
  `pghost_injected: true`, `db: connected`
- Complete a booking end to end: grid → movie → seat map → 201
- Confirm the booking row in Catalog Explorer
  (`movies_app_dev.movies.booking_seats`)

**Rough split:** ~90% AI (investigation, docs lookup, root cause, fix), ~10%
human (bug report, deployment).

---

## Phase 5 addendum — connection pooling: review, non-blocking fix, verification (2026-09-06)

**Where this started.** The human asked for a consolidated table of the
performance and scale optimisations proposed across `README.md` and
`DECISIONS.md` — 15 of them, from idempotency keys to multi-region — then picked
two to pursue: idempotency keys on `POST /api/bookings` and connection pooling.
AI wrote an implementation plan for both, sequencing pooling first because it is
contained entirely in `db.py` and changes no callers, while idempotency touches
DDL, service, router, frontend and tests.

**What arrived for review.** The pooling implementation landed as an uncommitted
diff across 10 files: `psycopg_pool.ConnectionPool`, a `_LakebaseConnection`
subclass overriding `connect()` so the OAuth token is minted per connection,
lifespan open/close, `PG_POOL_*` settings, pool stats in `/api/health`, and
ADR-006. *(Authorship: TBD — human to record whether this was written by hand or
in another AI session.)*

**The review (Claude Opus, `/code-review high`) — 10 findings.** The review
verified psycopg_pool's actual behaviour rather than asserting it from memory:
the library was installed into a scratchpad with `pip --target`, its `_connect`,
`connection()` and `_shrink_pool` sources read, and the pool probed directly.
That produced three facts inspection alone would have missed — the pool really
does call `connection_class.connect(conninfo, **kwargs)`, so the custom-connection
approach is sound; an unopened pool raises `PoolClosed` yet still reports
`pool_size: 2` from `get_stats()`, so a dead pool looks healthy in the health
endpoint; and `_connect` sets a per-attempt `connect_timeout` that the override
was clobbering.

**The finding that mattered.** Every route handler was `async def` while calling
blocking psycopg. The event loop is one thread, so the whole application
serialised on it, and no more than one pooled connection could ever be checked
out — `max_size: 10` was decoration. The feature had been added for concurrency
and delivered none. This is the Phase 2 addendum pattern again: an AI review pass
over AI-assisted code found what neither the implementation nor the human had.

**The human's call.** Fix only the blocking problem now; leave the other nine
findings for later. That kept the change small enough to deploy and verify in one
pass.

**The fix.** Seven `/api` handlers plus `/api/health` changed from `async def` to
`def`, so FastAPI runs them in its threadpool. That made `db.py`'s module caches
genuinely concurrent for the first time, so `_client()` and `_get_host()` gained
lock guards and `_lock` became an `RLock` — `_get_token()` holds it and calls
`_client()`, which with a plain `Lock` would have deadlocked against itself.
Those races existed all along but were unreachable while everything ran on one
thread. Added rationale comments in each router and the `db.py` docstring, plus
`tests/test_handlers_nonblocking.py` asserting no `/api` endpoint is a coroutine
function.

**Verification — measured, not asserted:**

- Four concurrent 300 ms queries through the real ASGI app: **1.21 s before,
  0.32 s after.**
- Mutation check: reverting one handler to `async def` restores the 1.21 s and
  fails the new test.
- `pytest` → 7/7.
- On the **deployed** app (human): `/api/health` showed the pool open with 2
  connections; after browsing and creating bookings, `pool_size: 3`,
  `pool_available: 3`, `connections_num: 3`, `requests_waiting: 0`. Three
  physical connections served dozens of operations (reuse), the pool grew past
  `min_size` — which psycopg_pool only does when every existing connection is
  already checked out, so requests genuinely overlapped on the platform — and
  every connection came back (no leaks, including through the rollback path).

**Documentation.** `README.md` gained a mermaid sequence diagram of a single
request through the loop, threadpool, pool and Lakebase, with prose on why the
handlers are sync. The *Taking it to millions* section still listed connection
pooling as future work and was corrected.

**Still open, deliberately deferred:** `max_lifetime` is measured from connect
time rather than token issuance, so a connection can outlive its credential;
`/api/health` has two identical `if/else` branches and therefore never exercises
the pool it reports on; `PG_POOL_*` is absent from `app.yaml`, so the documented
fallback needs a redeploy anyway; ADR-006's control characters; the
`connect_timeout` clobber; a wildcard version pin; and the duplicated non-pool
branches in the three `db.py` helpers.

**Two AI failures worth logging.** ADR-006 was written through a shell with
escaped backticks and shipped literal control characters (0x08, 0x09, 0x1B) into
a panel-facing document — exactly the quoting hazard CLAUDE.md §11 warns about,
and still uncorrected. Separately, `sed -i` silently stripped the CRLF line
endings from `main.py`, turning a one-word change into a 188-line diff; caught in
review of the diff and restored.

**Rough split:** ~85% AI (plan, review, fix, measurement, docs), ~15% human (the
two optimisations to pursue, the scope call to fix only the blocking issue,
deployment and on-platform verification).
