"""Row builders shaped like what `backend.db.query` returns.

Column names match `src/seed/ddl.sql` exactly, and the aliases match the
SELECT lists in `backend/routers/`. If a column is renamed in either place
without updating the other, these tests break — which is the point of keeping
the fixtures literal rather than generating them.
"""

from __future__ import annotations


def movie_row(movie_id: str = "mov-01", title: str = "Neon Harbor", **over) -> dict:
    row = {
        "movie_id": movie_id,
        "title": title,
        "synopsis": "A dockworker finds the tide charts are forged.",
        "genre": "Sci-Fi",
        "rating": "PG-13",
        "runtime_min": 128,
        "poster_url": "https://example.invalid/p.jpg",
    }
    row.update(over)
    return row


def theater_row(theater_id: str = "th-01", **over) -> dict:
    row = {
        "theater_id": theater_id,
        "name": "Slalom Cinema Downtown",
        "city": "Seattle",
        "address": "1201 Pike Street",
    }
    row.update(over)
    return row


def showtime_row(showtime_id: str = "st-d0-s0-aud-01", **over) -> dict:
    """A row from the /api/showtimes SELECT (joined with names)."""
    row = {
        "showtime_id": showtime_id,
        "movie_id": "mov-01",
        "auditorium_id": "aud-01",
        "starts_at": "2026-09-10T15:00:00+00:00",
        "price_standard": 12.00,
        "price_premium": 17.00,
        "movie_title": "Neon Harbor",
        "theater_id": "th-01",
        "theater_name": "Slalom Cinema Downtown",
        "auditorium_name": "Auditorium 1",
    }
    row.update(over)
    return row


def seatmap_header_row(showtime_id: str = "st-d0-s0-aud-01", **over) -> dict:
    """A row from the seat-map header SELECT in routers/seats.py."""
    row = {
        "showtime_id": showtime_id,
        "movie_id": "mov-01",
        "auditorium_id": "aud-01",
        "starts_at": "2026-09-10T15:00:00+00:00",
        "price_standard": 12.00,
        "price_premium": 17.00,
        "movie_title": "Neon Harbor",
        "auditorium_name": "Auditorium 1",
    }
    row.update(over)
    return row


def seat_row(
    seat_id: str = "aud-01-A01",
    row_label: str = "A",
    seat_number: int = 1,
    seat_type: str = "standard",
    is_booked: bool = False,
) -> dict:
    """A row from the seat-map SELECT: `is_booked` is the LEFT JOIN result."""
    return {
        "seat_id": seat_id,
        "row_label": row_label,
        "seat_number": seat_number,
        "seat_type": seat_type,
        "is_booked": is_booked,
    }


def booking_row(
    booking_id: str = "12345678-1234-5678-1234-567812345678", **over
) -> dict:
    row = {
        "booking_id": booking_id,
        "showtime_id": "st-d0-s0-aud-01",
        "customer_name": "Ana Delgado",
        "customer_email": "ana@example.invalid",
        "status": "CONFIRMED",
        "total_amount": 24.00,
        "created_at": "2026-09-07T09:00:00+00:00",
        "cancelled_at": None,
    }
    row.update(over)
    return row


def booking_seat_row(
    seat_id: str = "aud-01-A01",
    row_label: str = "A",
    seat_number: int = 1,
    seat_type: str = "standard",
    price: float = 12.00,
) -> dict:
    return {
        "seat_id": seat_id,
        "row_label": row_label,
        "seat_number": seat_number,
        "seat_type": seat_type,
        "price": price,
    }
