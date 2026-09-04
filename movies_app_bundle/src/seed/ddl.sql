-- Movies booking app — Lakebase (Postgres 16) schema.
--
-- This is the system of record. Every invariant the booking flow depends on is
-- enforced here rather than in application code:
--   * booking_seats UNIQUE (showtime_id, seat_id) makes double-booking impossible;
--     concurrent inserts for the same seat serialize on the unique index and the
--     loser gets a unique violation, which the API translates to HTTP 409.
--   * FKs keep seats inside the auditorium that the showtime plays in.
--   * CHECKs pin the small enumerations (seat_type, booking status).
-- Delta cannot enforce any of this, which is why the OLTP side lives on Lakebase
-- and the Delta side is the analytics copy.
--
-- Idempotent: safe to re-run. Object names are constants, never interpolated.

CREATE SCHEMA IF NOT EXISTS movies;

SET search_path TO movies;

-- ---------------------------------------------------------------- reference

CREATE TABLE IF NOT EXISTS movies (
    movie_id    text PRIMARY KEY,
    title       text NOT NULL,
    synopsis    text,
    genre       text,
    rating      text,
    runtime_min integer CHECK (runtime_min > 0),
    poster_url  text
);

CREATE TABLE IF NOT EXISTS theaters (
    theater_id text PRIMARY KEY,
    name       text NOT NULL,
    city       text NOT NULL,
    address    text
);

CREATE TABLE IF NOT EXISTS auditoriums (
    auditorium_id text PRIMARY KEY,
    theater_id    text NOT NULL REFERENCES theaters (theater_id),
    name          text NOT NULL,
    row_count     integer NOT NULL CHECK (row_count > 0),
    seats_per_row integer NOT NULL CHECK (seats_per_row > 0)
);

CREATE INDEX IF NOT EXISTS ix_auditoriums_theater
    ON auditoriums (theater_id);

-- One row per physical seat. seat_type drives pricing; 'accessible' is priced
-- as standard (a policy decision, see docs/DECISIONS.md).
CREATE TABLE IF NOT EXISTS seats (
    seat_id       text PRIMARY KEY,
    auditorium_id text NOT NULL REFERENCES auditoriums (auditorium_id),
    row_label     text NOT NULL,
    seat_number   integer NOT NULL CHECK (seat_number > 0),
    seat_type     text NOT NULL CHECK (seat_type IN ('standard', 'premium', 'accessible')),
    CONSTRAINT uq_seats_position UNIQUE (auditorium_id, row_label, seat_number),
    -- Redundant given the PK, but a composite FK needs a matching unique index:
    -- this is what lets booking_seats prove a seat is in the right auditorium.
    CONSTRAINT uq_seats_id_auditorium UNIQUE (seat_id, auditorium_id)
);

CREATE INDEX IF NOT EXISTS ix_seats_auditorium
    ON seats (auditorium_id);

CREATE TABLE IF NOT EXISTS showtimes (
    showtime_id     text PRIMARY KEY,
    movie_id        text NOT NULL REFERENCES movies (movie_id),
    auditorium_id   text NOT NULL REFERENCES auditoriums (auditorium_id),
    starts_at       timestamptz NOT NULL,
    price_standard  numeric(8, 2) NOT NULL CHECK (price_standard >= 0),
    price_premium   numeric(8, 2) NOT NULL CHECK (price_premium >= 0),
    -- FK target for booking_seats, as above.
    CONSTRAINT uq_showtimes_id_auditorium UNIQUE (showtime_id, auditorium_id)
);

CREATE INDEX IF NOT EXISTS ix_showtimes_movie_starts
    ON showtimes (movie_id, starts_at);

CREATE INDEX IF NOT EXISTS ix_showtimes_auditorium_starts
    ON showtimes (auditorium_id, starts_at);

-- ---------------------------------------------------------------- bookings

-- Booking header. total_amount is denormalised from booking_seats so the
-- confirmation screen is a single-row read.
CREATE TABLE IF NOT EXISTS bookings (
    booking_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    showtime_id    text NOT NULL REFERENCES showtimes (showtime_id),
    customer_name  text NOT NULL,
    customer_email text NOT NULL,
    status         text NOT NULL DEFAULT 'CONFIRMED'
                        CHECK (status IN ('CONFIRMED', 'CANCELLED')),
    total_amount   numeric(10, 2) NOT NULL DEFAULT 0 CHECK (total_amount >= 0),
    created_at     timestamptz NOT NULL DEFAULT now(),
    cancelled_at   timestamptz
);

CREATE INDEX IF NOT EXISTS ix_bookings_showtime
    ON bookings (showtime_id);

CREATE INDEX IF NOT EXISTS ix_bookings_email
    ON bookings (customer_email);

-- The seat allocation table, and the only place two invariants can be broken.
--
-- 1. uq_booking_seats_showtime_seat: a seat is sold at most once per showtime.
--    Concurrent inserts for the same seat serialize on this index; the loser
--    raises a unique violation, which the API turns into a 409.
-- 2. The two composite FKs: the denormalised auditorium_id must match BOTH the
--    seat's auditorium and the showtime's auditorium, so booking a seat into a
--    showtime playing in a different room is not representable. The API checks
--    this first to return a precise 422; these constraints are the backstop that
--    holds even if the API is wrong.
--
-- Cancelling deletes these rows (freeing the seats) while the header survives as
-- an audit trail, which is why the unique constraint lives here rather than on a
-- status-aware partial index.
CREATE TABLE IF NOT EXISTS booking_seats (
    booking_id    uuid NOT NULL REFERENCES bookings (booking_id) ON DELETE CASCADE,
    seat_id       text NOT NULL,
    showtime_id   text NOT NULL,
    auditorium_id text NOT NULL,
    price         numeric(8, 2) NOT NULL CHECK (price >= 0),
    PRIMARY KEY (booking_id, seat_id),
    CONSTRAINT uq_booking_seats_showtime_seat UNIQUE (showtime_id, seat_id),
    CONSTRAINT fk_booking_seats_seat
        FOREIGN KEY (seat_id, auditorium_id) REFERENCES seats (seat_id, auditorium_id),
    CONSTRAINT fk_booking_seats_showtime
        FOREIGN KEY (showtime_id, auditorium_id) REFERENCES showtimes (showtime_id, auditorium_id)
);

-- Drives the seat map query: seats LEFT JOIN booking_seats ON showtime_id.
CREATE INDEX IF NOT EXISTS ix_booking_seats_showtime
    ON booking_seats (showtime_id);
