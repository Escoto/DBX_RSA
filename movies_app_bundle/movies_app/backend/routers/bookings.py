from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from .. import db
from ..models import Booking, CreateBookingRequest
from ..services import booking_service

router = APIRouter(prefix="/api", tags=["bookings"])


@router.post("/bookings", response_model=Booking, status_code=201)
async def create_booking(body: CreateBookingRequest):
    try:
        return booking_service.create_booking(
            showtime_id=body.showtime_id,
            seat_ids=body.seat_ids,
            customer_name=body.customer.name,
            customer_email=body.customer.email,
        )
    except booking_service.ValidationError as exc:
        raise HTTPException(422, detail=exc.detail)
    except booking_service.ConflictError as exc:
        return JSONResponse(
            status_code=409,
            content={
                "detail": exc.detail,
                "taken_seat_ids": exc.taken_seat_ids,
            },
        )


@router.get("/bookings/{booking_id}", response_model=Booking)
async def get_booking(booking_id: UUID):
    rows = db.query(
        "SELECT booking_id, showtime_id, customer_name, customer_email, "
        "status, total_amount, created_at, cancelled_at "
        "FROM bookings WHERE booking_id = %s",
        (str(booking_id),),
    )
    if not rows:
        raise HTTPException(404, "Booking not found")
    booking = rows[0]
    booking["seats"] = db.query(
        "SELECT bs.seat_id, s.row_label, s.seat_number, "
        "s.seat_type, bs.price "
        "FROM booking_seats bs "
        "JOIN seats s ON s.seat_id = bs.seat_id "
        "WHERE bs.booking_id = %s "
        "ORDER BY s.row_label, s.seat_number",
        (str(booking_id),),
    )
    return booking
