from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import db
from ..models import SeatDetail, SeatMapResponse, SeatMapShowtime, SeatRow

router = APIRouter(prefix="/api", tags=["seats"])


@router.get("/showtimes/{showtime_id}/seats", response_model=SeatMapResponse)
async def get_seat_map(showtime_id: str) -> SeatMapResponse:
    st_rows = db.query(
        "SELECT st.showtime_id, st.auditorium_id, st.starts_at, "
        "st.price_standard, st.price_premium, "
        "m.title AS movie_title, a.name AS auditorium_name "
        "FROM showtimes st "
        "JOIN movies m ON m.movie_id = st.movie_id "
        "JOIN auditoriums a ON a.auditorium_id = st.auditorium_id "
        "WHERE st.showtime_id = %s",
        (showtime_id,),
    )
    if not st_rows:
        raise HTTPException(404, "Showtime not found")
    st = st_rows[0]

    # Seat map query from DATA_MODEL.md: LEFT JOIN gives booked/available.
    seats = db.query(
        "SELECT s.seat_id, s.row_label, s.seat_number, s.seat_type, "
        "(bs.seat_id IS NOT NULL) AS is_booked "
        "FROM seats s "
        "JOIN showtimes st ON st.auditorium_id = s.auditorium_id "
        "LEFT JOIN booking_seats bs "
        "ON bs.showtime_id = st.showtime_id AND bs.seat_id = s.seat_id "
        "WHERE st.showtime_id = %s "
        "ORDER BY s.row_label, s.seat_number",
        (showtime_id,),
    )

    rows_map: dict[str, list[SeatDetail]] = {}
    for seat in seats:
        price = (
            st["price_premium"]
            if seat["seat_type"] == "premium"
            else st["price_standard"]
        )
        detail = SeatDetail(
            seat_id=seat["seat_id"],
            seat_number=seat["seat_number"],
            seat_type=seat["seat_type"],
            price=float(price),
            status="booked" if seat["is_booked"] else "available",
        )
        rows_map.setdefault(seat["row_label"], []).append(detail)

    seat_rows = [
        SeatRow(row_label=label, seats=seat_list)
        for label, seat_list in rows_map.items()
    ]

    return SeatMapResponse(
        showtime=SeatMapShowtime(
            showtime_id=st["showtime_id"],
            movie_title=st["movie_title"],
            auditorium_name=st["auditorium_name"],
            starts_at=st["starts_at"],
            price_standard=float(st["price_standard"]),
            price_premium=float(st["price_premium"]),
        ),
        rows=seat_rows,
    )
