"""GET /api/movies, /api/theaters, /api/showtimes.

Two things are worth guarding here beyond "it returns 200":

* the showtimes filter builds its WHERE clause by concatenation, so the tests
  assert the *parameter order* matches the placeholder order. Getting that pair
  out of step is the classic way to break a hand-built query, and it would fail
  silently as "no showtimes found" rather than as an error.
* every value still reaches the driver as a `%s` parameter (CLAUDE.md §8.5).
"""

from __future__ import annotations

from tests.factories import movie_row, showtime_row, theater_row

MOVIES_SQL = "FROM movies ORDER BY title"
MOVIE_BY_ID_SQL = "FROM movies WHERE movie_id"
THEATERS_SQL = "FROM theaters ORDER BY name"
SHOWTIMES_SQL = "FROM showtimes st"


# ---------------------------------------------------------------- movies


def test_list_movies(client, stub):
    stub.on(MOVIES_SQL, [movie_row(), movie_row("mov-02", "The Quiet Ledger")])

    res = client.get("/api/movies")

    assert res.status_code == 200
    body = res.json()
    assert [m["movie_id"] for m in body] == ["mov-01", "mov-02"]
    assert body[0]["title"] == "Neon Harbor"
    assert body[0]["runtime_min"] == 128


def test_list_movies_empty(client, stub):
    stub.on(MOVIES_SQL, [])

    res = client.get("/api/movies")

    assert res.status_code == 200
    assert res.json() == []


def test_movie_nullable_columns_survive(client, stub):
    """synopsis/genre/rating/runtime/poster are all nullable in ddl.sql."""
    stub.on(
        MOVIES_SQL,
        [
            movie_row(
                synopsis=None, genre=None, rating=None, runtime_min=None,
                poster_url=None,
            )
        ],
    )

    body = client.get("/api/movies").json()

    assert body[0]["synopsis"] is None
    assert body[0]["poster_url"] is None


def test_get_movie(client, stub):
    stub.on(MOVIE_BY_ID_SQL, [movie_row()])

    res = client.get("/api/movies/mov-01")

    assert res.status_code == 200
    assert res.json()["movie_id"] == "mov-01"
    assert stub.params_for(MOVIE_BY_ID_SQL) == ("mov-01",)


def test_get_movie_404(client, stub):
    stub.on(MOVIE_BY_ID_SQL, [])

    res = client.get("/api/movies/mov-nope")

    assert res.status_code == 404
    assert res.json()["detail"] == "Movie not found"


def test_get_movie_id_is_parameterized(client, stub):
    """A quote in the path must travel as a parameter, never as SQL text."""
    stub.on(MOVIE_BY_ID_SQL, [])

    client.get("/api/movies/' OR 1=1 --")

    sql = stub.sql_for(MOVIE_BY_ID_SQL)
    assert "OR 1=1" not in sql
    assert sql.count("%s") == 1
    assert stub.params_for(MOVIE_BY_ID_SQL) == ("' OR 1=1 --",)


# ---------------------------------------------------------------- theaters


def test_list_theaters(client, stub):
    stub.on(THEATERS_SQL, [theater_row(), theater_row("th-02", name="Lakeview")])

    res = client.get("/api/theaters")

    assert res.status_code == 200
    assert [t["theater_id"] for t in res.json()] == ["th-01", "th-02"]


# ---------------------------------------------------------------- showtimes


def test_list_showtimes_unfiltered(client, stub):
    stub.on(SHOWTIMES_SQL, [showtime_row()])

    res = client.get("/api/showtimes")

    assert res.status_code == 200
    sql = stub.sql_for(SHOWTIMES_SQL)
    # Past showtimes are never bookable, so the filter is unconditional.
    assert "st.starts_at > now()" in sql
    assert "%s" not in sql
    assert stub.params_for(SHOWTIMES_SQL) is None


def test_list_showtimes_joins_names(client, stub):
    """The response carries movie/theater/auditorium names, not just ids."""
    stub.on(SHOWTIMES_SQL, [showtime_row()])

    body = client.get("/api/showtimes").json()

    assert body[0]["movie_title"] == "Neon Harbor"
    assert body[0]["theater_name"] == "Slalom Cinema Downtown"
    assert body[0]["auditorium_name"] == "Auditorium 1"


def test_list_showtimes_by_movie(client, stub):
    stub.on(SHOWTIMES_SQL, [showtime_row()])

    client.get("/api/showtimes?movie_id=mov-01")

    assert "AND st.movie_id = %s" in stub.sql_for(SHOWTIMES_SQL)
    assert stub.params_for(SHOWTIMES_SQL) == ("mov-01",)


def test_list_showtimes_by_theater(client, stub):
    stub.on(SHOWTIMES_SQL, [showtime_row()])

    client.get("/api/showtimes?theater_id=th-01")

    assert "AND t.theater_id = %s" in stub.sql_for(SHOWTIMES_SQL)
    assert stub.params_for(SHOWTIMES_SQL) == ("th-01",)


def test_list_showtimes_all_filters_keep_placeholder_order(client, stub):
    """Placeholders are appended movie -> theater; params must match."""
    stub.on(SHOWTIMES_SQL, [showtime_row()])

    client.get("/api/showtimes?movie_id=mov-01&theater_id=th-01")

    sql = stub.sql_for(SHOWTIMES_SQL)
    params = stub.params_for(SHOWTIMES_SQL)
    assert params == ("mov-01", "th-01")
    assert sql.count("%s") == 2
    assert sql.index("st.movie_id = %s") < sql.index("t.theater_id = %s")


def test_list_showtimes_ordering_is_stable(client, stub):
    """The UI groups by day, so time must be the leading sort key."""
    stub.on(SHOWTIMES_SQL, [showtime_row()])

    client.get("/api/showtimes")

    assert "ORDER BY st.starts_at, t.name, a.name" in stub.sql_for(SHOWTIMES_SQL)
