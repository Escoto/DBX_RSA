"""POST /api/bookings and GET /api/bookings/{id} at the HTTP boundary.

`test_booking_service.py` covers the transaction itself. This module covers
what the router adds on top: request validation from the Pydantic models, and
the translation of the service's two exception types into the status codes and
body shapes the SPA branches on.

The 409 body is a contract, not an implementation detail: ShowtimeView.vue
reads `taken_seat_ids` to re-mark the seat map after a lost race.
"""

from __future__ import annotations

import pytest

from backend.services import booking_service
from tests.factories import booking_row, booking_seat_row

BOOKING_ID = "12345678-1234-5678-1234-567812345678"
HEADER_SQL = "FROM bookings WHERE booking_id"
SEATS_SQL = "FROM booking_seats bs"

VALID_BODY = {
    "showtime_id": "st-d0-s0-aud-01",
    "seat_ids": ["aud-01-A01", "aud-01-A02"],
    "customer": {"name": "Ana Delgado", "email": "ana@example.invalid"},
}


@pytest.fixture
def created(monkeypatch):
    """Make booking_service.create_booking return a fixed booking."""
    result = booking_row()
    result["seats"] = [booking_seat_row(), booking_seat_row("aud-01-A02", "A", 2)]
    monkeypatch.setattr(
        booking_service, "create_booking", lambda **kwargs: result
    )
    return result


@pytest.fixture
def raises(monkeypatch):
    """Make booking_service.create_booking raise a given exception."""

    def _install(exc):
        def _boom(**kwargs):
            raise exc

        monkeypatch.setattr(booking_service, "create_booking", _boom)

    return _install


# ---------------------------------------------------------------- POST happy path


def test_create_booking_201(client, created):
    res = client.post("/api/bookings", json=VALID_BODY)

    assert res.status_code == 201
    body = res.json()
    assert body["booking_id"] == BOOKING_ID
    assert body["status"] == "CONFIRMED"
    assert body["total_amount"] == 24.00
    assert [s["seat_id"] for s in body["seats"]] == ["aud-01-A01", "aud-01-A02"]


def test_create_booking_passes_trimmed_fields_through(client, monkeypatch):
    seen = {}

    def _capture(**kwargs):
        seen.update(kwargs)
        row = booking_row()
        row["seats"] = []
        return row

    monkeypatch.setattr(booking_service, "create_booking", _capture)

    client.post("/api/bookings", json=VALID_BODY)

    assert seen["showtime_id"] == "st-d0-s0-aud-01"
    assert seen["seat_ids"] == ["aud-01-A01", "aud-01-A02"]
    assert seen["customer_name"] == "Ana Delgado"
    assert seen["customer_email"] == "ana@example.invalid"


# ---------------------------------------------------------------- POST 409


def test_conflict_returns_409_with_taken_seats(client, raises):
    raises(
        booking_service.ConflictError(
            detail="Some seats are already booked",
            taken_seat_ids=["aud-01-A01"],
        )
    )

    res = client.post("/api/bookings", json=VALID_BODY)

    assert res.status_code == 409
    body = res.json()
    assert body["detail"] == "Some seats are already booked"
    assert body["taken_seat_ids"] == ["aud-01-A01"]


def test_conflict_body_always_carries_the_key(client, raises):
    """The SPA reads taken_seat_ids unconditionally; it must always exist."""
    raises(booking_service.ConflictError(detail="Some seats are already booked",
                                        taken_seat_ids=[]))

    body = client.post("/api/bookings", json=VALID_BODY).json()

    assert body["taken_seat_ids"] == []


# ---------------------------------------------------------------- POST 422


def test_validation_error_returns_422(client, raises):
    raises(booking_service.ValidationError("Showtime has already started"))

    res = client.post("/api/bookings", json=VALID_BODY)

    assert res.status_code == 422
    assert res.json()["detail"] == "Showtime has already started"


@pytest.mark.parametrize(
    "body, reason",
    [
        ({**VALID_BODY, "seat_ids": []}, "no seats"),
        ({**VALID_BODY, "seat_ids": [f"s{i}" for i in range(9)]}, "more than 8"),
        ({**VALID_BODY, "customer": {"name": "", "email": "a@b.c"}}, "blank name"),
        ({**VALID_BODY, "customer": {"name": "A", "email": ""}}, "blank email"),
        ({"seat_ids": ["a"], "customer": {"name": "A", "email": "b"}}, "no showtime"),
        ({**VALID_BODY, "customer": {"name": "A"}}, "no email"),
    ],
)
def test_request_model_rejects_bad_bodies(client, body, reason):
    """The 1..8 seat cap and required customer fields live in models.py."""
    res = client.post("/api/bookings", json=body)

    assert res.status_code == 422, reason


def test_bad_body_never_reaches_the_service(client, monkeypatch):
    def _boom(**kwargs):
        raise AssertionError("service must not be called on an invalid body")

    monkeypatch.setattr(booking_service, "create_booking", _boom)

    assert client.post("/api/bookings", json={"seat_ids": []}).status_code == 422


# ---------------------------------------------------------------- GET


def test_get_booking_attaches_seats(client, stub):
    stub.on(SEATS_SQL, [booking_seat_row(), booking_seat_row("aud-01-A02", "A", 2)])
    stub.on(HEADER_SQL, [booking_row()])

    res = client.get(f"/api/bookings/{BOOKING_ID}")

    assert res.status_code == 200
    body = res.json()
    assert body["customer_name"] == "Ana Delgado"
    assert [s["seat_id"] for s in body["seats"]] == ["aud-01-A01", "aud-01-A02"]
    assert body["seats"][0]["price"] == 12.00


def test_get_booking_404(client, stub):
    stub.on(HEADER_SQL, [])

    res = client.get(f"/api/bookings/{BOOKING_ID}")

    assert res.status_code == 404
    assert res.json()["detail"] == "Booking not found"


def test_get_booking_rejects_a_non_uuid(client):
    """booking_id is a uuid PK; the path type is the first line of defence."""
    res = client.get("/api/bookings/not-a-uuid")

    assert res.status_code == 422


def test_get_booking_queries_by_uuid_string(client, stub):
    stub.on(SEATS_SQL, [])
    stub.on(HEADER_SQL, [booking_row()])

    client.get(f"/api/bookings/{BOOKING_ID}")

    assert stub.params_for(HEADER_SQL) == (BOOKING_ID,)
    assert stub.params_for(SEATS_SQL) == (BOOKING_ID,)


def test_cancelled_booking_is_reported_as_cancelled(client, stub):
    """No cancel endpoint ships, but a row cancelled in SQL must still read back."""
    stub.on(SEATS_SQL, [])
    stub.on(
        HEADER_SQL,
        [booking_row(status="CANCELLED", cancelled_at="2026-09-07T10:00:00+00:00")],
    )

    body = client.get(f"/api/bookings/{BOOKING_ID}").json()

    assert body["status"] == "CANCELLED"
    assert body["cancelled_at"] is not None
