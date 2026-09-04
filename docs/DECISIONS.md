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

`--recreate` drops tables, which also drops their grants. The script re-applies
the app service principal's grants on every run when `--app-sp-client-id` is
passed, so the two stay in step.
