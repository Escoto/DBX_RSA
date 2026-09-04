# Data Model

The system of record is **Lakebase** — Databricks-managed Postgres 16 — on
instance `movies-app-dev`, database `movies`, schema `movies`. The database is
registered in Unity Catalog as catalog `movies_app_dev`, so the same seven
tables are browsable in Catalog Explorer and queryable from the SQL warehouse
without any ETL.

DDL: [`movies_app_bundle/src/seed/ddl.sql`](../movies_app_bundle/src/seed/ddl.sql).
Seed loader: [`movies_app_bundle/src/seed/seed_lakebase.py`](../movies_app_bundle/src/seed/seed_lakebase.py).

---

## ER diagram

```mermaid
erDiagram
    MOVIES      ||--o{ SHOWTIMES     : "plays in"
    THEATERS    ||--o{ AUDITORIUMS   : has
    AUDITORIUMS ||--o{ SEATS         : contains
    AUDITORIUMS ||--o{ SHOWTIMES     : hosts
    SHOWTIMES   ||--o{ BOOKINGS      : "is booked by"
    SHOWTIMES   ||--o{ BOOKING_SEATS : "sells seats for"
    BOOKINGS    ||--|{ BOOKING_SEATS : allocates
    SEATS       ||--o{ BOOKING_SEATS : "is sold as"

    MOVIES {
        text    movie_id PK
        text    title
        text    synopsis
        text    genre
        text    rating
        integer runtime_min
        text    poster_url
    }
    THEATERS {
        text theater_id PK
        text name
        text city
        text address
    }
    AUDITORIUMS {
        text    auditorium_id PK
        text    theater_id FK
        text    name
        integer row_count
        integer seats_per_row
    }
    SEATS {
        text    seat_id PK
        text    auditorium_id FK
        text    row_label
        integer seat_number
        text    seat_type
    }
    SHOWTIMES {
        text        showtime_id PK
        text        movie_id FK
        text        auditorium_id FK
        timestamptz starts_at
        numeric     price_standard
        numeric     price_premium
    }
    BOOKINGS {
        uuid        booking_id PK
        text        showtime_id FK
        text        customer_name
        text        customer_email
        text        status
        numeric     total_amount
        timestamptz created_at
        timestamptz cancelled_at
    }
    BOOKING_SEATS {
        uuid    booking_id PK-FK
        text    seat_id PK-FK
        text    showtime_id FK
        text    auditorium_id FK
        numeric price
    }
```

---

## What the database enforces

Every invariant below is a constraint, not application code. This is the whole
reason the OLTP side is on Lakebase rather than on Delta: Delta cannot enforce
uniqueness, cannot enforce referential integrity, and cannot span tables in a
single transaction.

| Invariant | Mechanism | Table |
|---|---|---|
| **A seat is sold at most once per showtime** | `UNIQUE (showtime_id, seat_id)` — `uq_booking_seats_showtime_seat` | `booking_seats` |
| **A booked seat is physically in the room the showtime plays in** | composite FKs `(seat_id, auditorium_id) → seats` and `(showtime_id, auditorium_id) → showtimes` | `booking_seats` |
| **A seat row is on the same showtime as its booking header** | composite FK `(booking_id, showtime_id) → bookings` — `fk_booking_seats_booking` (ADR-003) | `booking_seats` |
| Seat positions are unique within an auditorium | `UNIQUE (auditorium_id, row_label, seat_number)` | `seats` |
| Seat types are a closed set | `CHECK seat_type IN ('standard','premium','accessible')` | `seats` |
| Booking status is a closed set | `CHECK status IN ('CONFIRMED','CANCELLED')` | `bookings` |
| A booking is cancelled iff it has a cancellation time | `CHECK ((status = 'CANCELLED') = (cancelled_at IS NOT NULL))` | `bookings` |
| Prices and totals are non-negative | `CHECK … >= 0` | `showtimes`, `bookings`, `booking_seats` |
| Cancelling a booking releases its seats | `ON DELETE CASCADE` from `bookings` | `booking_seats` |
| Every FK target exists | 8 foreign keys, 3 of them composite | all |

Verified against the live instance: a duplicate `(showtime_id, seat_id)` insert
raises `uq_booking_seats_showtime_seat`; a seat from another auditorium raises
`fk_booking_seats_seat` or `fk_booking_seats_showtime` depending on which side
the mismatched `auditorium_id` breaks; the same seat in a *different* showtime
is accepted, which is the case a naive `UNIQUE (seat_id)` would wrongly reject.
ADR-003 was added after that check: a seat row that names a different showtime
than its header now violates `fk_booking_seats_booking`. The seed script's
report prints the constraint inventory from `pg_constraint` on every run, so
the check is repeatable.

### Why `auditorium_id` is denormalised into `booking_seats`

`booking_seats` reaches an auditorium two ways — through `seats` and through
`showtimes` — and without a shared column nothing forces those two paths to
agree. Carrying `auditorium_id` on the row and pointing a composite FK down each
path makes the mismatch **unrepresentable** rather than merely unlikely.

The API still validates seat membership before it writes, so a bad request gets
a precise `422` naming the offending seats instead of an opaque FK error. The
constraints are the backstop that holds even if that check is wrong. Defence in
depth: the friendly error comes from the app, the guarantee comes from the
schema.

### Why the FK to `bookings` carries `showtime_id` too

The same reasoning, one relationship over. `booking_seats` reaches a showtime
two ways as well — directly, and through its header — and a plain `booking_id`
FK let those disagree: two showtimes in the same room satisfy both composite
FKs above while the header points at a third. Referencing
`bookings (booking_id, showtime_id)` instead pins the seat row to its header's
showtime, so the table is now fully determined: seat, showtime and header must
agree. See ADR-003.

### Why the unique constraint is on `booking_seats`, not a partial index

Cancellation deletes the `booking_seats` rows and marks the header `CANCELLED`,
setting `cancelled_at` in the same statement (a CHECK requires the two to move
together). The seats are freed by the delete, so the unique constraint never
has to be aware of booking status — no `WHERE status = 'CONFIRMED'` partial
index, no risk of a cancelled row blocking a resale. The header survives as the
audit trail, with its `total_amount` intact.

---

## Query shapes

**Seat map** (`GET /api/showtimes/{id}/seats`) — one left join; a seat is
`booked` when the join matches:

```sql
SELECT s.seat_id, s.row_label, s.seat_number, s.seat_type,
       (bs.seat_id IS NOT NULL) AS is_booked
FROM seats s
JOIN showtimes st ON st.auditorium_id = s.auditorium_id
LEFT JOIN booking_seats bs
       ON bs.showtime_id = st.showtime_id AND bs.seat_id = s.seat_id
WHERE st.showtime_id = %s
ORDER BY s.row_label, s.seat_number;
```

`ix_booking_seats_showtime` serves the join; `ix_seats_auditorium` serves the
scan. At 120 seats per auditorium this is a trivial query, and it stays trivial
at any realistic auditorium size.

**Booking write path** — see [ARCHITECTURE.md](ARCHITECTURE.md) and CLAUDE.md
§4.4. The whole booking is one transaction; a unique violation rolls it back and
becomes a `409` listing the seats that were taken.

---

## Seed data

Deterministic (`random.Random(42)`, ids derived from position, booking ids
`uuid5` of a stable name) and idempotent (`ON CONFLICT`), so re-running the
loader converges rather than duplicating.

| Table | Rows | Shape |
|---|---:|---|
| `movies` | 8 | fictional titles across 8 genres |
| `theaters` | 3 | Seattle, Chicago, Boston |
| `auditoriums` | 5 | rows A–J × 12 seats each |
| `seats` | 600 | rows E–G premium; A1, A2, A11, A12 accessible; rest standard |
| `showtimes` | 70 | 7 days × 2 slots × 5 auditoriums, movies round-robin so each plays in more than one theater |
| `bookings` | 54 | on the first two days, so the seat map is never empty |
| `booking_seats` | 128 | contiguous blocks within a row |

`--reset` truncates before loading; `--recreate` drops the tables so `ddl.sql`
can rebuild them after a schema change. `ddl.sql` is written as target state
rather than as a migration chain — this is a prototype whose only data is
regenerable seed data. A production version would carry versioned migrations
(Alembic or plain numbered SQL) instead.

---

## Verified through Unity Catalog

The same tables, read from the SQL warehouse `movies_analytics` with no copy
step in between:

```sql
SELECT m.title,
       count(DISTINCT s.showtime_id) AS showtimes,
       count(bs.seat_id)             AS seats_sold,
       round(sum(bs.price), 2)       AS revenue
FROM movies_app_dev.movies.showtimes s
JOIN movies_app_dev.movies.movies m ON m.movie_id = s.movie_id
LEFT JOIN movies_app_dev.movies.booking_seats bs ON bs.showtime_id = s.showtime_id
GROUP BY m.title
ORDER BY revenue DESC;
```

```
title                 showtimes  seats_sold  revenue
Paper Lanterns                9          22   375.50
Neon Harbor                   9          22   323.50
Iron Meridian                 9          18   280.00
Midnight Cartography          8          17   269.00
The Quiet Ledger              9          15   229.00
A Year of Tuesdays            9          13   215.00
Salt and Static               9          11   169.00
The Long Ascent               8          10   143.00
```

This query is the basis of the Phase 6 gold tables in
`movies_analytics_dev.movies`.
