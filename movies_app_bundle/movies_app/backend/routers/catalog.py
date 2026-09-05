from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import db
from ..models import Movie, Showtime, Theater

router = APIRouter(prefix="/api", tags=["catalog"])


@router.get("/movies", response_model=list[Movie])
async def list_movies() -> list[dict]:
    return db.query("SELECT * FROM movies ORDER BY title")


@router.get("/movies/{movie_id}", response_model=Movie)
async def get_movie(movie_id: str) -> dict:
    rows = db.query(
        "SELECT * FROM movies WHERE movie_id = %s", (movie_id,)
    )
    if not rows:
        raise HTTPException(404, "Movie not found")
    return rows[0]


@router.get("/theaters", response_model=list[Theater])
async def list_theaters() -> list[dict]:
    return db.query("SELECT * FROM theaters ORDER BY name")


@router.get("/showtimes", response_model=list[Showtime])
async def list_showtimes(
    movie_id: str | None = Query(None),
    theater_id: str | None = Query(None),
    date: str | None = Query(None),
) -> list[dict]:
    # Past showtimes are excluded so the frontend shows only bookable times.
    sql = (
        "SELECT st.showtime_id, st.movie_id, st.auditorium_id, "
        "st.starts_at, st.price_standard, st.price_premium, "
        "m.title AS movie_title, "
        "t.theater_id, t.name AS theater_name, "
        "a.name AS auditorium_name "
        "FROM showtimes st "
        "JOIN movies m ON m.movie_id = st.movie_id "
        "JOIN auditoriums a ON a.auditorium_id = st.auditorium_id "
        "JOIN theaters t ON t.theater_id = a.theater_id "
        "WHERE st.starts_at > now()"
    )
    params: list = []
    if movie_id is not None:
        sql += " AND st.movie_id = %s"
        params.append(movie_id)
    if theater_id is not None:
        sql += " AND t.theater_id = %s"
        params.append(theater_id)
    if date is not None:
        sql += " AND st.starts_at::date = %s::date"
        params.append(date)
    sql += " ORDER BY st.starts_at, t.name, a.name"
    return db.query(sql, tuple(params) if params else None)
