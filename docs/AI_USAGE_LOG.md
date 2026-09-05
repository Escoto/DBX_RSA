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
