"""Booking transaction — the write path the panel will probe.

The UNIQUE constraint on booking_seats (showtime_id, seat_id) is the invariant
that prevents double-booking.  This service validates, writes one transaction,
and translates database errors into structured exceptions for the router.
It never formats user input into SQL; all values go through %s placeholders.
"""

from __future__ import annotations

import logging
from typing import Any

from psycopg.errors import UniqueViolation

from .. import db

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail


class ConflictError(Exception):
    def __init__(self, detail: str, taken_seat_ids: list[str]) -> None:
        self.detail = detail
        self.taken_seat_ids = taken_seat_ids


def create_booking(
    showtime_id: str,
    seat_ids: list[str],
    customer_name: str,
    customer_email: str,
) -> dict[str, Any]:
    # ---- Step 1: validate before opening a transaction ----

    # Showtime must exist and start in the future.
    rows = db.query(
        "SELECT showtime_id, auditorium_id FROM showtimes "
        "WHERE showtime_id = %s AND starts_at > now()",
        (showtime_id,),
    )
    if not rows:
        exists = db.query(
            "SELECT 1 FROM showtimes WHERE showtime_id = %s",
            (showtime_id,),
        )
        if exists:
            raise ValidationError("Showtime has already started")
        raise ValidationError("Showtime not found")

    auditorium_id = rows[0]["auditorium_id"]

    if len(set(seat_ids)) != len(seat_ids):
        raise ValidationError("Duplicate seat IDs in request")

    # Every requested seat must belong to the showtime's auditorium.  The API
    # checks this first so the user gets a precise 422 naming the bad seats
    # instead of an opaque FK violation from the composite constraints.
    valid_seats = db.query(
        "SELECT seat_id FROM seats WHERE auditorium_id = %s AND seat_id = ANY(%s)",
        (auditorium_id, seat_ids),
    )
    valid_ids = {r["seat_id"] for r in valid_seats}
    invalid = [sid for sid in seat_ids if sid not in valid_ids]
    if invalid:
        raise ValidationError(f"Seats not in this auditorium: {', '.join(invalid)}")

    # ---- Step 2: one transaction for header + seats + total ----
    # Connections are drawn from a psycopg connection pool. The pool handles
    # dynamic credential rotation in the background (ADR-006).
    try:
        with db.transaction() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO bookings "
                "(showtime_id, customer_name, customer_email, "
                "status, total_amount) "
                "VALUES (%s, %s, %s, 'CONFIRMED', 0) "
                "RETURNING booking_id, showtime_id, customer_name, "
                "customer_email, status, total_amount, "
                "created_at, cancelled_at",
                (showtime_id, customer_name, customer_email),
            )
            cols = [d[0] for d in cur.description]
            booking = dict(zip(cols, cur.fetchone()))
            booking_id = booking["booking_id"]

            # INSERT … SELECT prices the seats from the showtime in one
            # round-trip.  The join on auditorium_id means a foreign seat
            # yields no row — a second guard behind the composite FKs.
            cur.execute(
                "INSERT INTO booking_seats "
                "(booking_id, showtime_id, seat_id, auditorium_id, price) "
                "SELECT %s, st.showtime_id, s.seat_id, s.auditorium_id, "
                "CASE s.seat_type WHEN 'premium' THEN st.price_premium "
                "ELSE st.price_standard END "
                "FROM seats s "
                "JOIN showtimes st ON st.auditorium_id = s.auditorium_id "
                "WHERE st.showtime_id = %s AND s.seat_id = ANY(%s)",
                (booking_id, showtime_id, seat_ids),
            )
            if cur.rowcount != len(seat_ids):
                raise ValidationError(
                    f"Expected {len(seat_ids)} seat rows, got {cur.rowcount}"
                )

            cur.execute(
                "UPDATE bookings SET total_amount = ("
                "SELECT sum(price) FROM booking_seats "
                "WHERE booking_id = %s"
                ") WHERE booking_id = %s "
                "RETURNING total_amount",
                (booking_id, booking_id),
            )
            booking["total_amount"] = cur.fetchone()[0]

            cur.execute(
                "SELECT bs.seat_id, s.row_label, s.seat_number, "
                "s.seat_type, bs.price "
                "FROM booking_seats bs "
                "JOIN seats s ON s.seat_id = bs.seat_id "
                "WHERE bs.booking_id = %s "
                "ORDER BY s.row_label, s.seat_number",
                (booking_id,),
            )
            seat_cols = [d[0] for d in cur.description]
            booking["seats"] = [dict(zip(seat_cols, row)) for row in cur.fetchall()]

            return booking

    except UniqueViolation:
        # ---- Step 3: the UNIQUE constraint fired ----
        # Another booking took one or more of our seats between validation
        # and INSERT.  The transaction context manager already rolled back.
        # Re-query on a fresh connection to find which seats are taken.
        taken = db.query(
            "SELECT seat_id FROM booking_seats "
            "WHERE showtime_id = %s AND seat_id = ANY(%s)",
            (showtime_id, seat_ids),
        )
        taken_ids = [r["seat_id"] for r in taken]
        raise ConflictError(
            detail="Some seats are already booked",
            taken_seat_ids=taken_ids,
        )
