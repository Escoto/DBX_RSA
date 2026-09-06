"""Tests for the booking write path (§4.4).

Covers: happy path, unique-violation → ConflictError with taken seat ids,
and validation failures (showtime not found, past showtime, invalid seats,
duplicate seat ids).

Run from movies_app/:
    pip install -r requirements-dev.txt
    python -m pytest tests/ -v
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from backend.services.booking_service import (
    ConflictError,
    ValidationError,
    create_booking,
)

BOOKING_ID = UUID("12345678-1234-5678-1234-567812345678")
CREATED_AT = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)


def _fake_transaction(cursor):
    """Return a replacement for db.transaction that yields a mock connection."""
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False

    @contextmanager
    def _tx():
        yield conn

    return _tx


def _happy_cursor():
    """A mock cursor that handles the full booking INSERT sequence."""
    cur = MagicMock()

    def _execute(sql, params=None):
        if "INSERT INTO bookings" in sql and "booking_seats" not in sql:
            cur.description = [
                ("booking_id",),
                ("showtime_id",),
                ("customer_name",),
                ("customer_email",),
                ("status",),
                ("total_amount",),
                ("created_at",),
                ("cancelled_at",),
            ]
            cur.fetchone.return_value = (
                BOOKING_ID,
                "st-1",
                "Alice",
                "alice@example.com",
                "CONFIRMED",
                Decimal(0),
                CREATED_AT,
                None,
            )
        elif "INSERT INTO booking_seats" in sql:
            cur.rowcount = 2
        elif "UPDATE bookings" in sql:
            cur.description = [("total_amount",)]
            cur.fetchone.return_value = (Decimal("25.00"),)
        elif "booking_seats bs" in sql:
            cur.description = [
                ("seat_id",),
                ("row_label",),
                ("seat_number",),
                ("seat_type",),
                ("price",),
            ]
            cur.fetchall.return_value = [
                ("aud-01-A01", "A", 1, "standard", Decimal("12.50")),
                ("aud-01-A02", "A", 2, "standard", Decimal("12.50")),
            ]

    cur.execute.side_effect = _execute
    return cur


# ---- happy path ----


@patch("backend.services.booking_service.db")
def test_create_booking_happy_path(mock_db):
    mock_db.query.side_effect = [
        [{"showtime_id": "st-1", "auditorium_id": "aud-01"}],
        [{"seat_id": "aud-01-A01"}, {"seat_id": "aud-01-A02"}],
    ]
    cur = _happy_cursor()
    mock_db.transaction = _fake_transaction(cur)

    result = create_booking(
        showtime_id="st-1",
        seat_ids=["aud-01-A01", "aud-01-A02"],
        customer_name="Alice",
        customer_email="alice@example.com",
    )

    assert result["booking_id"] == BOOKING_ID
    assert result["status"] == "CONFIRMED"
    assert result["total_amount"] == Decimal("25.00")
    assert len(result["seats"]) == 2
    assert result["seats"][0]["seat_id"] == "aud-01-A01"
    assert result["seats"][1]["seat_id"] == "aud-01-A02"


# ---- unique violation → 409 with taken seat ids ----


@patch("backend.services.booking_service.db")
def test_unique_violation_returns_taken_seats(mock_db):
    from psycopg.errors import UniqueViolation

    mock_db.query.side_effect = [
        [{"showtime_id": "st-1", "auditorium_id": "aud-01"}],
        [{"seat_id": "aud-01-A01"}, {"seat_id": "aud-01-A02"}],
        [{"seat_id": "aud-01-A01"}],
    ]

    cur = MagicMock()

    def _execute(sql, params=None):
        if "INSERT INTO bookings" in sql and "booking_seats" not in sql:
            cur.description = [
                ("booking_id",),
                ("showtime_id",),
                ("customer_name",),
                ("customer_email",),
                ("status",),
                ("total_amount",),
                ("created_at",),
                ("cancelled_at",),
            ]
            cur.fetchone.return_value = (
                BOOKING_ID,
                "st-1",
                "Alice",
                "alice@example.com",
                "CONFIRMED",
                Decimal(0),
                CREATED_AT,
                None,
            )
        elif "INSERT INTO booking_seats" in sql:
            raise UniqueViolation("duplicate key value violates unique constraint")

    cur.execute.side_effect = _execute
    mock_db.transaction = _fake_transaction(cur)

    with pytest.raises(ConflictError) as exc_info:
        create_booking(
            showtime_id="st-1",
            seat_ids=["aud-01-A01", "aud-01-A02"],
            customer_name="Alice",
            customer_email="alice@example.com",
        )

    assert exc_info.value.taken_seat_ids == ["aud-01-A01"]
    assert "already booked" in exc_info.value.detail


# ---- validation: showtime not found ----


@patch("backend.services.booking_service.db")
def test_showtime_not_found(mock_db):
    mock_db.query.side_effect = [
        [],
        [],
    ]

    with pytest.raises(ValidationError) as exc_info:
        create_booking("st-gone", ["aud-01-A01"], "Alice", "a@b.com")

    assert "not found" in exc_info.value.detail.lower()


# ---- validation: past showtime ----


@patch("backend.services.booking_service.db")
def test_past_showtime(mock_db):
    mock_db.query.side_effect = [
        [],
        [{"x": 1}],
    ]

    with pytest.raises(ValidationError) as exc_info:
        create_booking("st-past", ["aud-01-A01"], "Alice", "a@b.com")

    assert "started" in exc_info.value.detail.lower()


# ---- validation: seats not in the auditorium ----


@patch("backend.services.booking_service.db")
def test_invalid_seats(mock_db):
    mock_db.query.side_effect = [
        [{"showtime_id": "st-1", "auditorium_id": "aud-01"}],
        [{"seat_id": "aud-01-A01"}],
    ]

    with pytest.raises(ValidationError) as exc_info:
        create_booking("st-1", ["aud-01-A01", "aud-99-Z01"], "Alice", "a@b.com")

    assert "aud-99-Z01" in exc_info.value.detail


# ---- validation: duplicate seat ids ----


@patch("backend.services.booking_service.db")
def test_duplicate_seat_ids(mock_db):
    mock_db.query.side_effect = [
        [{"showtime_id": "st-1", "auditorium_id": "aud-01"}],
    ]

    with pytest.raises(ValidationError) as exc_info:
        create_booking("st-1", ["aud-01-A01", "aud-01-A01"], "Alice", "a@b.com")

    assert "duplicate" in exc_info.value.detail.lower()
