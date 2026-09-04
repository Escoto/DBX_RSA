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
