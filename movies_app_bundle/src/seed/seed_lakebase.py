"""Create the Lakebase schema and load deterministic demo data.

Auth is the same path the app uses at runtime: a short-lived OAuth credential
minted through the Databricks SDK, presented as the Postgres password over TLS.
Locally the identity is the CLI profile user; on Databricks Apps it is the app's
service principal. See src/seed/check_connection.py.

Everything here is deterministic (seeded RNG, derived ids) and idempotent
(ON CONFLICT), so re-running converges on the same database instead of piling
up duplicates. --reset truncates first, for a clean pre-demo state.

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
DATABASE = os.environ.get("LAKEBASE_DATABASE", "movies")
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

DAYS_AHEAD = 7
SHOW_SLOTS_UTC = [(15, 0), (19, 30)]  # (hour, minute)

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


def build_showtimes(now: datetime) -> list[tuple[str, str, str, datetime, float, float]]:
    """One showtime per (day, slot, auditorium), movies assigned round-robin.

    The round-robin runs across auditoriums, so every movie ends up playing in
    more than one theater — which is what makes the 'pick a theater' step of the
    demo meaningful.
    """
    theater_order = {th[0]: idx for idx, th in enumerate(THEATERS)}
    theater_index = {aud: theater_order[th] for aud, th, _n in AUDITORIUMS}
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = []
    counter = 0
    for day in range(DAYS_AHEAD):
        for slot, (hour, minute) in enumerate(SHOW_SLOTS_UTC):
            for auditorium_id, _theater_id, _name in AUDITORIUMS:
                movie_id = MOVIES[counter % len(MOVIES)][0]
                counter += 1
                starts_at = day0 + timedelta(days=day, hours=hour, minutes=minute)
                # City surcharge plus an evening bump; premium is a flat +$5.
                base = 12.00 + 1.50 * theater_index[auditorium_id] + (2.00 if slot else 0.00)
                rows.append(
                    (
                        f"st-d{day}-s{slot}-{auditorium_id}",
                        movie_id,
                        auditorium_id,
                        starts_at,
                        round(base, 2),
                        round(base + 5.00, 2),
                    )
                )
    return rows


def build_bookings(showtimes, seats_by_auditorium, rng):
    """Pre-existing bookings so the seat map does not look empty on first load.

    Booking ids are uuid5 of a stable name, so re-running the seed updates the
    same rows instead of creating new ones.
    """
    aud_of = {s[0]: s[2] for s in showtimes}
    price_of = {s[0]: (float(s[4]), float(s[5])) for s in showtimes}
    seat_type = {}
    for rows in seats_by_auditorium.values():
        for seat_id, _aud, _row, _num, stype in rows:
            seat_type[seat_id] = stype

    # Spread the pre-booked showtimes over the first two days so the demo click
    # path lands on a map that already has sold seats.
    target_showtimes = [s[0] for s in showtimes if s[0].startswith(("st-d0-", "st-d1-"))]

    bookings = []          # (booking_id, showtime_id, name, email, status)
    booking_seats = []     # (booking_id, seat_id, showtime_id, auditorium_id, price)
    for showtime_id in target_showtimes:
        taken: set[str] = set()
        pool = [row[0] for row in seats_by_auditorium[aud_of[showtime_id]]]
        for n in range(rng.randint(2, 4)):
            first = rng.choice(CUSTOMER_FIRST)
            last = rng.choice(CUSTOMER_LAST)
            booking_id = uuid.uuid5(SEED_NAMESPACE, f"{showtime_id}:{n}")
            party = rng.randint(1, 4)
            chosen = []
            # Pick a contiguous block where possible; people book together.
            for _attempt in range(20):
                start = rng.randrange(0, len(pool) - party)
                block = pool[start : start + party]
                same_row = len({seat_id.rsplit("-", 1)[1][0] for seat_id in block}) == 1
                if same_row and not (set(block) & taken):
                    chosen = block
                    break
            if not chosen:
                continue
            taken.update(chosen)
            std, prem = price_of[showtime_id]
            bookings.append(
                (
                    booking_id,
                    showtime_id,
                    f"{first} {last}",
                    f"{first.lower()}.{last.lower()}@example.com",
                    "CONFIRMED",
                )
            )
            for seat_id in chosen:
                price = prem if seat_type[seat_id] == "premium" else std
                booking_seats.append(
                    (booking_id, seat_id, showtime_id, aud_of[showtime_id], price)
                )
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
    showtimes = build_showtimes(now)
    bookings, booking_seats = build_bookings(showtimes, seats_by_auditorium, rng)

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
            "INSERT INTO bookings (booking_id, showtime_id, customer_name, customer_email, status) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (booking_id) DO NOTHING",
            bookings,
        )

        # DO NOTHING, not DO UPDATE: if a real booking made through the app already
        # holds one of these seats, the seed must yield rather than steal it.
        cur.executemany(
            "INSERT INTO booking_seats (booking_id, seat_id, showtime_id, auditorium_id, price) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            booking_seats,
        )

        # Recompute headers from what actually landed.
        cur.execute(
            "UPDATE bookings b SET total_amount = COALESCE(("
            "  SELECT sum(bs.price) FROM booking_seats bs WHERE bs.booking_id = b.booking_id"
            "), 0)"
        )

        # Drop seeded headers that lost every seat to a real booking. Scoped to the
        # ids this script generated so a booking made through the app is never touched.
        cur.execute(
            "DELETE FROM bookings b WHERE b.booking_id = ANY(%s) "
            "AND NOT EXISTS (SELECT 1 FROM booking_seats bs WHERE bs.booking_id = b.booking_id)",
            ([row[0] for row in bookings],),
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
