"""Create the Lakebase schema and load deterministic demo data.

Auth is the same path the app uses at runtime: a short-lived OAuth credential
minted through the Databricks SDK, presented as the Postgres password over TLS.
Locally the identity is the CLI profile user; on Databricks Apps it is the app's
service principal. See src/seed/check_connection.py.

Everything here is deterministic (seeded RNG, derived ids) and idempotent
(ON CONFLICT), so re-running converges on the same database instead of piling
up duplicates. --reset truncates first, for a clean pre-demo state.

Showtime ids are relative to the run date (st-d00-* is today, st-m03-* is three
days ago), so the schedule is a rolling window: 14 days of settled history for
the analytics layer plus the 7 bookable days the app exposes. Re-running on a
later day WITHOUT --reset moves the existing showtimes, and every booking on
them, forward to the new window. Deliberate for a demo whose date is not fixed;
always re-seed with --reset right before the demo.

Bookings are not uniform noise: PROGRAMMING and the demand model below encode a
deliberate distribution (popular titles, prime slots, weekend bumps, and two
under-served gaps), so the dashboard and the Genie space have a real signal to
discover. See the comment above MOVIE_DEMAND.

Usage (Windows Python, reading the WSL CLI profile):

    DATABRICKS_CONFIG_FILE=//wsl.localhost/Ubuntu-24.04/home/raescoto/.databrickscfg \
    DATABRICKS_CONFIG_PROFILE=movies \
    python movies_app_bundle/src/seed/seed_lakebase.py \
        --app-sp-client-id 2a26812a-1b82-4879-9487-6eb43f7ad56b
"""

from __future__ import annotations

import argparse
import os
import random
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from databricks.sdk import WorkspaceClient
from psycopg import sql

INSTANCE = os.environ.get("LAKEBASE_INSTANCE", "movies-app-dev")
DATABASE = os.environ.get("LAKEBASE_DATABASE", "movies_dev")
SCHEMA = os.environ.get("LAKEBASE_SCHEMA", "movies")

DDL_PATH = Path(__file__).resolve().parent / "ddl.sql"

RNG_SEED = 42
SEED_NAMESPACE = uuid.UUID("6f2e1c40-7a3b-4d51-9c8e-0b1d2f3a4b5c")

# Truncate order is irrelevant with CASCADE, but listing children first keeps the
# intent obvious to a reader.
TABLES_CHILD_FIRST = [
    "booking_seats",
    "bookings",
    "showtimes",
    "seats",
    "auditoriums",
    "theaters",
    "movies",
]

# ------------------------------------------------------------------ seed data

MOVIES = [
    ("mov-01", "Neon Harbor", "A dockworker in a flooded megacity discovers the tide charts are being forged.", "Sci-Fi", "PG-13", 128),
    ("mov-02", "The Quiet Ledger", "An auditor at a failing bank finds a second set of books and a reason to keep quiet.", "Thriller", "R", 114),
    ("mov-03", "Paper Lanterns", "Two siblings build a flying machine out of festival scraps to reach their grandmother.", "Animation", "PG", 96),
    ("mov-04", "Iron Meridian", "A decommissioned icebreaker crew races a storm front across the Arctic shipping lane.", "Action", "PG-13", 141),
    ("mov-05", "Salt and Static", "A radio operator on a remote island starts receiving her own broadcasts a day early.", "Horror", "R", 102),
    ("mov-06", "A Year of Tuesdays", "Two commuters share a delayed train platform every week for a year, and never exchange names.", "Romance", "PG-13", 108),
    ("mov-07", "The Long Ascent", "Four climbers attempt a route that has never been finished, filmed entirely on the wall.", "Documentary", "PG", 89),
    ("mov-08", "Midnight Cartography", "A night-shift mapmaker notices a street that appears on no other city plan.", "Mystery", "PG-13", 121),
]

THEATERS = [
    ("th-01", "Slalom Cinema Downtown", "Seattle", "1201 Pike Street"),
    ("th-02", "Lakeview Picturehouse", "Chicago", "88 North Wacker Drive"),
    ("th-03", "Harbor Point Cineplex", "Boston", "400 Seaport Boulevard"),
]

# (auditorium_id, theater_id, name). Every auditorium is 10 rows (A-J) x 12 seats.
AUDITORIUMS = [
    ("aud-01", "th-01", "Auditorium 1"),
    ("aud-02", "th-01", "Auditorium 2"),
    ("aud-03", "th-02", "Grand Hall"),
    ("aud-04", "th-02", "Screen 2"),
    ("aud-05", "th-03", "Harbor IMAX"),
]

ROW_LABELS = list("ABCDEFGHIJ")
SEATS_PER_ROW = 12

# Middle rows are the good seats; the front row keeps four accessible positions
# at the aisles. Accessible seats are priced as standard.
PREMIUM_ROWS = {"E", "F", "G"}
ACCESSIBLE_ROW = "A"
ACCESSIBLE_NUMBERS = {1, 2, 11, 12}

DAYS_BACK = 14   # settled history, for the analytics layer
DAYS_AHEAD = 7   # the bookable window the app exposes

# (hour, minute) in UTC. The labels are the schedule's own names for its slots,
# not a derivation from each city's local time — the whole app displays UTC as
# is (see CLAUDE.md §3), and the analytics layer inherits that.
SHOW_SLOTS_UTC = [(11, 0), (15, 0), (19, 30), (22, 15)]
SLOT_LABELS = ["matinee", "afternoon", "evening", "late"]
SLOT_PRICE_DELTA = {0: -1.50, 1: 0.00, 2: 2.00, 3: 0.50}

# ------------------------------------------------------------- demand model
#
# The seed encodes a deliberate demand distribution instead of booking seats
# uniformly at random. Uniform noise makes every auditorium look equally empty
# and leaves the analytics layer with nothing to find: a dashboard of flat bars
# and a Genie space that answers "which movie should we add showings for?" with
# whatever the RNG happened to favour. Say this out loud in the demo — the seed
# plants a signal, the analytics layer discovers it; it is never told about it.
#
# Expected share of a full house for each movie in a prime evening slot at the
# strongest theater, before slot/theater/weekend factors.
MOVIE_DEMAND = {
    "mov-04": 0.95,  # Iron Meridian     — the tentpole, sells out evenings
    "mov-01": 0.72,  # Neon Harbor       — solid second title
    "mov-08": 0.58,  # Midnight Cartography
    "mov-05": 0.50,  # Salt and Static   — horror, skews late
    "mov-02": 0.44,  # The Quiet Ledger
    "mov-03": 0.40,  # Paper Lanterns    — family, skews matinee
    "mov-06": 0.33,  # A Year of Tuesdays
    "mov-07": 0.18,  # The Long Ascent   — documentary, the control case
}
SLOT_FACTOR = {0: 0.45, 1: 0.70, 2: 1.00, 3: 0.55}
THEATER_FACTOR = {"th-01": 1.00, "th-02": 0.88, "th-03": 0.80}
WEEKEND_FACTOR = 1.25            # Friday, Saturday, Sunday
WEEKEND_WEEKDAYS = {4, 5, 6}     # datetime.weekday(): Mon=0
# (movie, slot) pairs that beat their slot's baseline: kids at the matinee,
# horror at the late show, the climbing documentary with the morning crowd.
MOVIE_SLOT_BONUS = {("mov-03", 0): 1.60, ("mov-05", 3): 1.40, ("mov-07", 0): 1.20}

# How much of a showtime's final demand has already been sold, by days until
# the show. Tonight is nearly settled; next Sunday has barely opened. This is
# what makes the live dashboard interesting: the near-term shows are filling
# and the far ones are not.
LEAD_TIME_SOLD = {0: 0.92, 1: 0.78, 2: 0.62, 3: 0.48, 4: 0.38, 5: 0.30, 6: 0.24}
# Never sell a future show right out — the demo has to be able to book a seat.
MAX_FUTURE_OCCUPANCY = 0.94

# The programming grid: auditorium -> slot -> the movies that rotate through it
# (indexed by day), or None where the auditorium runs no show in that slot.
#
# Two gaps are deliberate, and they are the answer to the Genie question:
#   1. Iron Meridian sells out evenings in aud-01, while next door aud-02 gives
#      its evening screen to a low-demand romance and runs no late show at all.
#   2. Harbor Point (th-03) never plays Iron Meridian, despite being the only
#      screen in its city.
PROGRAMMING: dict[str, dict[int, list[str] | None]] = {
    # th-01 Slalom Cinema Downtown, Seattle
    "aud-01": {0: ["mov-03"], 1: ["mov-01", "mov-08"], 2: ["mov-04"], 3: ["mov-05"]},
    "aud-02": {0: ["mov-07"], 1: ["mov-02"], 2: ["mov-06"], 3: None},
    # th-02 Lakeview Picturehouse, Chicago
    "aud-03": {0: ["mov-03"], 1: ["mov-08"], 2: ["mov-04"], 3: ["mov-05"]},
    "aud-04": {0: None, 1: ["mov-06"], 2: ["mov-01"], 3: ["mov-02"]},
    # th-03 Harbor Point Cineplex, Boston
    "aud-05": {0: ["mov-03", "mov-07"], 1: ["mov-08"], 2: ["mov-01"], 3: None},
}

# Where people actually sit: middle rows first, centre outwards. Drives both a
# believable seat map and a believable occupancy curve.
ROW_DESIRABILITY = ["F", "E", "G", "D", "H", "C", "I", "B", "J", "A"]
PARTY_SIZES = [1, 2, 3, 4, 5]
PARTY_WEIGHTS = [18, 42, 22, 12, 6]

CUSTOMER_FIRST = ["Ana", "Marcus", "Priya", "Tomas", "Lena", "Owen", "Chidi", "Yuki", "Rosa", "Ibrahim"]
CUSTOMER_LAST = ["Delgado", "Fisher", "Raman", "Novak", "Bauer", "Whitfield", "Okafor", "Tanaka", "Iglesias", "Haddad"]


def seat_type_for(row_label: str, seat_number: int) -> str:
    if row_label == ACCESSIBLE_ROW and seat_number in ACCESSIBLE_NUMBERS:
        return "accessible"
    if row_label in PREMIUM_ROWS:
        return "premium"
    return "standard"


def seat_id_for(auditorium_id: str, row_label: str, seat_number: int) -> str:
    return f"{auditorium_id}-{row_label}{seat_number:02d}"


def build_seats() -> list[tuple[str, str, str, int, str]]:
    rows = []
    for auditorium_id, _theater_id, _name in AUDITORIUMS:
        for row_label in ROW_LABELS:
            for seat_number in range(1, SEATS_PER_ROW + 1):
                rows.append(
                    (
                        seat_id_for(auditorium_id, row_label, seat_number),
                        auditorium_id,
                        row_label,
                        seat_number,
                        seat_type_for(row_label, seat_number),
                    )
                )
    return rows


def showtime_id_for(day: int, slot: int, auditorium_id: str) -> str:
    """Ids are relative to the run date: st-m03-* is three days ago, st-d03-* in three."""
    stamp = f"m{-day:02d}" if day < 0 else f"d{day:02d}"
    return f"st-{stamp}-s{slot}-{auditorium_id}"


def build_showtimes(now: datetime):
    """The programming grid over the window, from DAYS_BACK ago to DAYS_AHEAD out.

    Returns the insertable rows plus a metadata map the booking generator needs
    (slot, theater, how far off the show is) so it never has to parse ids back.

    Every movie plays in at least two theaters, which is what makes the 'pick a
    theater' step of the demo meaningful; PROGRAMMING is what decides where.
    """
    theater_order = {th[0]: idx for idx, th in enumerate(THEATERS)}
    theater_of = {aud: th for aud, th, _n in AUDITORIUMS}
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = []
    meta: dict[str, dict] = {}
    for day in range(-DAYS_BACK, DAYS_AHEAD):
        for slot, (hour, minute) in enumerate(SHOW_SLOTS_UTC):
            for auditorium_id, theater_id, _name in AUDITORIUMS:
                rotation = PROGRAMMING[auditorium_id][slot]
                if rotation is None:
                    continue  # the auditorium is dark in this slot — free capacity
                movie_id = rotation[(day + DAYS_BACK) % len(rotation)]
                starts_at = day0 + timedelta(days=day, hours=hour, minutes=minute)
                # City surcharge plus a per-slot delta; premium is a flat +$5.
                base = 12.00 + 1.50 * theater_order[theater_id] + SLOT_PRICE_DELTA[slot]
                showtime_id = showtime_id_for(day, slot, auditorium_id)
                rows.append(
                    (
                        showtime_id,
                        movie_id,
                        auditorium_id,
                        starts_at,
                        round(base, 2),
                        round(base + 5.00, 2),
                    )
                )
                meta[showtime_id] = {
                    "movie_id": movie_id,
                    "auditorium_id": auditorium_id,
                    "theater_id": theater_of[auditorium_id],
                    "slot": slot,
                    "day": day,
                    "starts_at": starts_at,
                    "price_standard": round(base, 2),
                    "price_premium": round(base + 5.00, 2),
                }
    return rows, meta


def demand_for(info: dict) -> float:
    """Share of the house this showtime ends up selling, before lead time.

    Product of the factors declared above, so every number in the analytics
    layer traces back to one line of the demand model.
    """
    share = MOVIE_DEMAND[info["movie_id"]]
    share *= SLOT_FACTOR[info["slot"]]
    share *= THEATER_FACTOR[info["theater_id"]]
    share *= MOVIE_SLOT_BONUS.get((info["movie_id"], info["slot"]), 1.0)
    if info["starts_at"].weekday() in WEEKEND_WEEKDAYS:
        share *= WEEKEND_FACTOR
    return share


def rows_by_label(seat_rows) -> dict[str, list[str]]:
    """Seat ids per row, in seat-number order (so adjacency in the list is adjacency in the row)."""
    by_row: dict[str, list[tuple[int, str]]] = {}
    for seat_id, _aud, row_label, seat_number, _stype in seat_rows:
        by_row.setdefault(row_label, []).append((seat_number, seat_id))
    return {label: [sid for _num, sid in sorted(pairs)] for label, pairs in by_row.items()}


def weighted_row_order(rng: random.Random) -> list[str]:
    """A random row order biased towards the good rows (Efraimidis-Spirakis weighted shuffle)."""
    keyed = []
    for idx, row_label in enumerate(ROW_DESIRABILITY):
        weight = len(ROW_DESIRABILITY) - idx
        keyed.append((rng.random() ** (1.0 / weight), row_label))
    keyed.sort(reverse=True)
    return [label for _key, label in keyed]


def pick_block(by_row: dict[str, list[str]], taken: set[str], party: int, rng: random.Random):
    """A free contiguous block of `party` seats, preferring good rows and centre seats.

    Falls back to smaller parties rather than scattering a group across the room,
    and returns None only when the house is genuinely full.
    """
    for size in range(party, 0, -1):
        for row_label in weighted_row_order(rng):
            seats = by_row[row_label]
            centre = (len(seats) - 1) / 2
            candidates = []
            for start in range(len(seats) - size + 1):
                block = seats[start : start + size]
                if any(seat_id in taken for seat_id in block):
                    continue
                candidates.append((abs((start + (size - 1) / 2) - centre), block))
            if candidates:
                candidates.sort(key=lambda c: c[0])
                return rng.choice(candidates[:3])[1]
    return None


def booked_at_for(starts_at: datetime, now: datetime, rng: random.Random) -> datetime:
    """When the booking was made: mostly in the last days before the show.

    Without this every row would carry a created_at of 'the moment the seed ran',
    which would make any sales-over-time chart a single spike and any question
    about booking lead time unanswerable.
    """
    lead_days = rng.choices([0, 1, 2, 3, 5, 8, 12], weights=[30, 22, 16, 12, 10, 6, 4])[0]
    booked = starts_at - timedelta(
        days=lead_days, hours=rng.randrange(0, 24), minutes=rng.randrange(0, 60)
    )
    if booked >= now:
        # A show still in the future cannot have been booked after 'now'.
        booked = now - timedelta(hours=rng.randrange(1, 72), minutes=rng.randrange(0, 60))
    return booked


def build_bookings(showtimes, meta, seats_by_auditorium, rng, now: datetime):
    """Sell each showtime to the occupancy its demand model implies.

    Past shows are settled at their full demand; future ones are sold down the
    lead-time curve, capped so the demo can always still book a seat. Booking
    ids are uuid5 of a stable name, so re-running the seed converges on the same
    rows instead of piling up duplicates.
    """
    seat_type = {}
    for seat_rows in seats_by_auditorium.values():
        for seat_id, _aud, _row, _num, stype in seat_rows:
            seat_type[seat_id] = stype
    rows_of = {aud: rows_by_label(seat_rows) for aud, seat_rows in seats_by_auditorium.items()}

    bookings = []          # (booking_id, showtime_id, name, email, status, created_at)
    booking_seats = []     # (booking_id, seat_id, showtime_id, auditorium_id, price)
    for showtime_id, _movie, auditorium_id, starts_at, std, prem in showtimes:
        info = meta[showtime_id]
        share = demand_for(info)
        if info["day"] >= 0:
            share *= LEAD_TIME_SOLD.get(info["day"], min(LEAD_TIME_SOLD.values()))
            share = min(share, MAX_FUTURE_OCCUPANCY)
        else:
            share = min(share, 1.0)
        share *= rng.uniform(0.88, 1.12)  # no two showtimes land on the same number
        capacity = len(seats_by_auditorium[auditorium_id])
        target = max(0, min(capacity, round(share * capacity)))

        by_row = rows_of[auditorium_id]
        taken: set[str] = set()
        sold = 0
        n = 0
        while sold < target and n < 200:
            party = min(rng.choices(PARTY_SIZES, weights=PARTY_WEIGHTS)[0], target - sold)
            block = pick_block(by_row, taken, party, rng)
            if block is None:
                break
            taken.update(block)
            sold += len(block)
            first = rng.choice(CUSTOMER_FIRST)
            last = rng.choice(CUSTOMER_LAST)
            booking_id = uuid.uuid5(SEED_NAMESPACE, f"{showtime_id}:{n}")
            n += 1
            bookings.append(
                (
                    booking_id,
                    showtime_id,
                    f"{first} {last}",
                    f"{first.lower()}.{last.lower()}@example.com",
                    "CONFIRMED",
                    booked_at_for(starts_at, now, rng),
                )
            )
            for seat_id in block:
                price = float(prem) if seat_type[seat_id] == "premium" else float(std)
                booking_seats.append((booking_id, seat_id, showtime_id, auditorium_id, price))
    return bookings, booking_seats


# ------------------------------------------------------------------ database


def connect(w: WorkspaceClient) -> psycopg.Connection:
    instance = w.database.get_database_instance(INSTANCE)
    host = os.environ.get("PGHOST") or instance.read_write_dns
    user = os.environ.get("PGUSER") or os.environ.get("DATABRICKS_CLIENT_ID") or w.current_user.me().user_name
    # Valid for about an hour; never logged.
    cred = w.database.generate_database_credential(
        request_id=str(uuid.uuid4()), instance_names=[INSTANCE]
    )
    print(f"instance={INSTANCE} state={instance.state} host={host} db={DATABASE} user={user}")
    return psycopg.connect(
        host=host,
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=DATABASE,
        user=user,
        password=cred.token,
        sslmode="require",
        connect_timeout=20,
        # Harmless on the very first run, when the schema does not exist yet:
        # CREATE SCHEMA does not consult search_path.
        options=f"-c search_path={SCHEMA}",
    )


def drop_all(conn: psycopg.Connection) -> None:
    """Drop every app table so ddl.sql can rebuild the current shape.

    ddl.sql is written as target state (CREATE TABLE IF NOT EXISTS), not as a
    migration chain: this is a prototype whose only data is regenerable seed
    data. When the schema changes, --recreate is the migration.
    """
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(
                sql.SQL(", ").join(
                    sql.Identifier(SCHEMA, table) for table in TABLES_CHILD_FIRST
                )
            )
        )
    conn.commit()
    print("dropped all tables (--recreate)")


def apply_ddl(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(DDL_PATH.read_text(encoding="utf-8"))
    conn.commit()
    print(f"ddl applied from {DDL_PATH.name}")


def truncate_all(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                sql.SQL(", ").join(
                    sql.Identifier(SCHEMA, table) for table in TABLES_CHILD_FIRST
                )
            )
        )
    conn.commit()
    print("truncated all tables (--reset)")


def load(conn: psycopg.Connection, now: datetime) -> None:
    rng = random.Random(RNG_SEED)
    seats = build_seats()
    seats_by_auditorium: dict[str, list] = {}
    for row in seats:
        seats_by_auditorium.setdefault(row[1], []).append(row)
    showtimes, showtime_meta = build_showtimes(now)
    bookings, booking_seats = build_bookings(
        showtimes, showtime_meta, seats_by_auditorium, rng, now
    )

    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO movies (movie_id, title, synopsis, genre, rating, runtime_min, poster_url) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (movie_id) DO UPDATE SET title = EXCLUDED.title, synopsis = EXCLUDED.synopsis, "
            "genre = EXCLUDED.genre, rating = EXCLUDED.rating, runtime_min = EXCLUDED.runtime_min, "
            "poster_url = EXCLUDED.poster_url",
            [
                (mid, title, synopsis, genre, rating, runtime, f"https://picsum.photos/seed/{mid}/320/480")
                for mid, title, synopsis, genre, rating, runtime in MOVIES
            ],
        )

        cur.executemany(
            "INSERT INTO theaters (theater_id, name, city, address) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (theater_id) DO UPDATE SET name = EXCLUDED.name, city = EXCLUDED.city, "
            "address = EXCLUDED.address",
            THEATERS,
        )

        cur.executemany(
            "INSERT INTO auditoriums (auditorium_id, theater_id, name, row_count, seats_per_row) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (auditorium_id) DO UPDATE SET theater_id = EXCLUDED.theater_id, "
            "name = EXCLUDED.name, row_count = EXCLUDED.row_count, seats_per_row = EXCLUDED.seats_per_row",
            [(aud, th, name, len(ROW_LABELS), SEATS_PER_ROW) for aud, th, name in AUDITORIUMS],
        )

        cur.executemany(
            "INSERT INTO seats (seat_id, auditorium_id, row_label, seat_number, seat_type) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (seat_id) DO UPDATE SET seat_type = EXCLUDED.seat_type",
            seats,
        )

        cur.executemany(
            "INSERT INTO showtimes (showtime_id, movie_id, auditorium_id, starts_at, price_standard, price_premium) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (showtime_id) DO UPDATE SET movie_id = EXCLUDED.movie_id, "
            "auditorium_id = EXCLUDED.auditorium_id, starts_at = EXCLUDED.starts_at, "
            "price_standard = EXCLUDED.price_standard, price_premium = EXCLUDED.price_premium",
            showtimes,
        )

        cur.executemany(
            "INSERT INTO bookings (booking_id, showtime_id, customer_name, customer_email, "
            "status, created_at) VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (booking_id) DO NOTHING",
            bookings,
        )

        # DO NOTHING, not DO UPDATE: if a real booking made through the app already
        # holds one of these seats, the seed must yield rather than steal it.
        cur.executemany(
            "INSERT INTO booking_seats (booking_id, seat_id, showtime_id, auditorium_id, price) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            booking_seats,
        )

        # Recompute the seeded headers from what actually landed. Both statements
        # are scoped to the ids this script generated, so a booking made through
        # the app is never touched: a cancelled one keeps its seats deleted and
        # its total_amount intact as the audit trail.
        seeded_ids = [row[0] for row in bookings]
        cur.execute(
            "UPDATE bookings b SET total_amount = COALESCE(("
            "  SELECT sum(bs.price) FROM booking_seats bs WHERE bs.booking_id = b.booking_id"
            "), 0) WHERE b.booking_id = ANY(%s)",
            (seeded_ids,),
        )

        # Drop seeded headers that lost every seat to a real booking.
        cur.execute(
            "DELETE FROM bookings b WHERE b.booking_id = ANY(%s) "
            "AND NOT EXISTS (SELECT 1 FROM booking_seats bs WHERE bs.booking_id = b.booking_id)",
            (seeded_ids,),
        )
    conn.commit()
    print("seed data loaded")


def grant_to_app(conn: psycopg.Connection, client_id: str) -> None:
    """Grant the app's service principal DML on the schema.

    The `database` app resource creates the Postgres role (named after the SP
    client id) with CONNECT/CREATE on the database, but the tables are owned by
    whoever ran this script, so the table-level grants have to be made here.
    """
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", client_id):
        raise SystemExit(f"--app-sp-client-id does not look like a UUID: {client_id!r}")
    role = sql.Identifier(client_id)
    schema = sql.Identifier(SCHEMA)
    statements = [
        sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, role),
        sql.SQL(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {} TO {}"
        ).format(schema, role),
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA {} "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
        ).format(schema, role),
    ]
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
    conn.commit()
    print(f"granted schema {SCHEMA} DML to role {client_id}")


def report(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        print("\nrow counts")
        for table in reversed(TABLES_CHILD_FIRST):
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(SCHEMA, table)))
            print(f"  {table:<16} {cur.fetchone()[0]}")

        cur.execute(
            sql.SQL(
                "SELECT m.title, count(*) FROM {st} s JOIN {mv} m USING (movie_id) "
                "GROUP BY m.title ORDER BY m.title"
            ).format(st=sql.Identifier(SCHEMA, "showtimes"), mv=sql.Identifier(SCHEMA, "movies"))
        )
        print("\nshowtimes per movie")
        for title, count in cur.fetchall():
            print(f"  {title:<24} {count}")

        # The demand model, read back out of the data. Past shows are settled;
        # upcoming ones are partly sold down the lead-time curve. This is the
        # done-check for the analytics layer: if these numbers are flat, the
        # dashboard and the Genie space have nothing to find.
        occupancy = sql.SQL(
            "SELECT {dims}, count(*) AS shows, "
            "  round(100.0 * sum(x.sold) / sum(a.row_count * a.seats_per_row), 1) AS pct "
            "FROM {st} s "
            "JOIN {au} a USING (auditorium_id) "
            "JOIN {mv} m USING (movie_id) "
            "JOIN {th} t USING (theater_id) "
            "LEFT JOIN LATERAL ("
            "  SELECT count(*) AS sold FROM {bs} bs WHERE bs.showtime_id = s.showtime_id"
            ") x ON true "
            "{where} GROUP BY {group} ORDER BY {order} {limit}"
        )
        parts = {
            "st": sql.Identifier(SCHEMA, "showtimes"),
            "au": sql.Identifier(SCHEMA, "auditoriums"),
            "mv": sql.Identifier(SCHEMA, "movies"),
            "th": sql.Identifier(SCHEMA, "theaters"),
            "bs": sql.Identifier(SCHEMA, "booking_seats"),
        }
        cur.execute(
            occupancy.format(
                dims=sql.SQL("CASE WHEN s.starts_at < now() THEN 'past' ELSE 'upcoming' END"),
                where=sql.SQL(""),
                group=sql.SQL("1"),
                order=sql.SQL("1"),
                limit=sql.SQL(""),
                **parts,
            )
        )
        print("\noccupancy by window")
        for window, shows, pct in cur.fetchall():
            print(f"  {window:<10} shows={shows:<5} {pct}% full")

        cur.execute(
            occupancy.format(
                dims=sql.SQL("m.title, t.name"),
                where=sql.SQL("WHERE s.starts_at < now()"),
                group=sql.SQL("1, 2"),
                order=sql.SQL("pct DESC"),
                limit=sql.SQL("LIMIT 6"),
                **parts,
            )
        )
        print("\ntop demand, settled shows (movie x theater)")
        for title, theater, shows, pct in cur.fetchall():
            print(f"  {pct:>5}%  {title:<24} {theater:<26} shows={shows}")

        # What the schema actually enforces, from the catalog rather than from
        # ddl.sql: this is the Phase 2 done-check made repeatable.
        cur.execute(
            "SELECT c.contype, count(*) FROM pg_constraint c "
            "JOIN pg_namespace n ON n.oid = c.connamespace "
            "WHERE n.nspname = %s GROUP BY c.contype ORDER BY c.contype",
            (SCHEMA,),
        )
        labels = {"p": "primary key", "f": "foreign key", "u": "unique", "c": "check"}
        print("\nconstraints")
        for contype, count in cur.fetchall():
            print(f"  {labels.get(contype, contype):<16} {count}")

        # Never silent about grants: --recreate drops the tables, and only the
        # owner's default privileges (or --app-sp-client-id) put them back.
        cur.execute(
            "SELECT grantee, count(DISTINCT table_name), "
            "array_agg(DISTINCT privilege_type ORDER BY privilege_type) "
            "FROM information_schema.role_table_grants "
            "WHERE table_schema = %s AND grantee <> current_user "
            "GROUP BY grantee ORDER BY grantee",
            (SCHEMA,),
        )
        grants = cur.fetchall()
        print("\ntable grants to roles other than the owner")
        if not grants:
            print("  none: the app cannot read the tables. Re-run with --app-sp-client-id.")
        for grantee, table_count, privileges in grants:
            # array_agg comes back as a Postgres array literal string, not a list.
            listed = privileges if isinstance(privileges, str) else ",".join(privileges)
            print(f"  {grantee}  tables={table_count}  {listed.strip('{}')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--app-sp-client-id",
        help="Service principal client id of the Databricks App; grants it DML on the schema.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="TRUNCATE every table before loading. Destroys bookings made through the app.",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="DROP every table before applying ddl.sql. Use after a schema change.",
    )
    args = parser.parse_args()

    if args.recreate and not args.app_sp_client_id:
        # Not fatal: on this instance the owner's default privileges re-grant the
        # app automatically (see ADR-002). On a fresh database they do not, and
        # the app would start with no access. The report below shows which.
        print(
            "WARNING: --recreate without --app-sp-client-id; "
            "check the grants section of the report.",
            file=sys.stderr,
        )

    w = WorkspaceClient()
    with connect(w) as conn:
        if args.recreate:
            drop_all(conn)
        apply_ddl(conn)
        if args.reset:
            truncate_all(conn)
        load(conn, datetime.now(timezone.utc))
        if args.app_sp_client_id:
            grant_to_app(conn, args.app_sp_client_id)
        report(conn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
