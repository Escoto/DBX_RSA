from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class Movie(BaseModel):
    movie_id: str
    title: str
    synopsis: str | None = None
    genre: str | None = None
    rating: str | None = None
    runtime_min: int | None = None
    poster_url: str | None = None


class Theater(BaseModel):
    theater_id: str
    name: str
    city: str
    address: str | None = None


class Showtime(BaseModel):
    showtime_id: str
    movie_id: str
    auditorium_id: str
    starts_at: datetime
    price_standard: float
    price_premium: float
    movie_title: str | None = None
    theater_id: str | None = None
    theater_name: str | None = None
    auditorium_name: str | None = None


class SeatDetail(BaseModel):
    seat_id: str
    seat_number: int
    seat_type: str
    price: float
    status: str


class SeatRow(BaseModel):
    row_label: str
    seats: list[SeatDetail]


class SeatMapShowtime(BaseModel):
    showtime_id: str
    movie_title: str
    auditorium_name: str
    starts_at: datetime
    price_standard: float
    price_premium: float


class SeatMapResponse(BaseModel):
    showtime: SeatMapShowtime
    rows: list[SeatRow]


class BookingCustomer(BaseModel):
    name: str = Field(min_length=1)
    email: str = Field(min_length=1)


class CreateBookingRequest(BaseModel):
    showtime_id: str
    seat_ids: list[str] = Field(min_length=1, max_length=8)
    customer: BookingCustomer


class BookingSeat(BaseModel):
    seat_id: str
    row_label: str
    seat_number: int
    seat_type: str
    price: float


class Booking(BaseModel):
    booking_id: UUID
    showtime_id: str
    customer_name: str
    customer_email: str
    status: str
    total_amount: float
    created_at: datetime
    cancelled_at: datetime | None = None
    seats: list[BookingSeat] | None = None
