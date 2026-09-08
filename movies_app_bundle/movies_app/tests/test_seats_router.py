"""GET /api/showtimes/{id}/seats — the seat map.

The handler does the only non-trivial shaping in the read path: it flattens a
flat seat list into rows, resolves each seat's price from the showtime, and
maps the LEFT JOIN result to `available` / `booked`. All three are business
rules a refactor can quietly break, so each has a test.
"""

from __future__ import annotations

from tests.factories import seat_row, seatmap_header_row

HEADER_SQL = "FROM showtimes st JOIN movies m"
SEATS_SQL = "LEFT JOIN booking_seats bs"

SHOWTIME_ID = "st-d0-s0-aud-01"
URL = f"/api/showtimes/{SHOWTIME_ID}/seats"


def _stub_map(stub, seats, **header_over):
    stub.on(SEATS_SQL, seats)
    stub.on(HEADER_SQL, [seatmap_header_row(SHOWTIME_ID, **header_over)])
    return stub


def test_seat_map_header(client, stub):
    _stub_map(stub, [seat_row()])

    res = client.get(URL)

    assert res.status_code == 200
    head = res.json()["showtime"]
    assert head["showtime_id"] == SHOWTIME_ID
    assert head["movie_id"] == "mov-01"
    assert head["movie_title"] == "Neon Harbor"
    assert head["auditorium_name"] == "Auditorium 1"
    assert head["price_standard"] == 12.00
    assert head["price_premium"] == 17.00


def test_seat_map_404(client, stub):
    stub.on(HEADER_SQL, [])

    res = client.get("/api/showtimes/st-nope/seats")

    assert res.status_code == 404
    assert res.json()["detail"] == "Showtime not found"


def test_seat_map_groups_into_rows(client, stub):
    _stub_map(
        stub,
        [
            seat_row("aud-01-A01", "A", 1),
            seat_row("aud-01-A02", "A", 2),
            seat_row("aud-01-B01", "B", 1),
        ],
    )

    rows = client.get(URL).json()["rows"]

    assert [r["row_label"] for r in rows] == ["A", "B"]
    assert [s["seat_number"] for s in rows[0]["seats"]] == [1, 2]
    assert len(rows[1]["seats"]) == 1


def test_seat_map_row_order_follows_query_order(client, stub):
    """The SQL orders by row_label, seat_number; grouping must not reshuffle."""
    _stub_map(
        stub,
        [
            seat_row("aud-01-A01", "A", 1),
            seat_row("aud-01-B01", "B", 1),
            seat_row("aud-01-C01", "C", 1),
        ],
    )

    rows = client.get(URL).json()["rows"]

    assert [r["row_label"] for r in rows] == ["A", "B", "C"]
    assert "ORDER BY s.row_label, s.seat_number" in stub.sql_for(SEATS_SQL)


def test_booked_seats_are_marked(client, stub):
    _stub_map(
        stub,
        [
            seat_row("aud-01-A01", "A", 1, is_booked=False),
            seat_row("aud-01-A02", "A", 2, is_booked=True),
        ],
    )

    seats = client.get(URL).json()["rows"][0]["seats"]

    assert seats[0]["status"] == "available"
    assert seats[1]["status"] == "booked"


def test_premium_seats_use_premium_price(client, stub):
    _stub_map(
        stub,
        [
            seat_row("aud-01-E01", "E", 1, seat_type="premium"),
            seat_row("aud-01-J01", "J", 1, seat_type="standard"),
        ],
    )

    rows = {r["row_label"]: r["seats"][0] for r in client.get(URL).json()["rows"]}

    assert rows["E"]["price"] == 17.00
    assert rows["J"]["price"] == 12.00


def test_accessible_seats_are_priced_as_standard(client, stub):
    """A stated product decision (CLAUDE.md §3), not an accident of the code."""
    _stub_map(
        stub,
        [
            seat_row("aud-01-A01", "A", 1, seat_type="accessible"),
            seat_row("aud-01-A03", "A", 3, seat_type="standard"),
        ],
    )

    seats = client.get(URL).json()["rows"][0]["seats"]

    assert seats[0]["seat_type"] == "accessible"
    assert seats[0]["price"] == seats[1]["price"] == 12.00


def test_seat_map_is_parameterized_on_showtime(client, stub):
    _stub_map(stub, [seat_row()])

    client.get(URL)

    assert stub.params_for(SEATS_SQL) == (SHOWTIME_ID,)
    assert stub.params_for(HEADER_SQL) == (SHOWTIME_ID,)


def test_empty_auditorium_yields_no_rows(client, stub):
    _stub_map(stub, [])

    body = client.get(URL).json()

    assert body["rows"] == []
    assert body["showtime"]["showtime_id"] == SHOWTIME_ID
