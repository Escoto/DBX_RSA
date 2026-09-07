-- Movies booking app — Delta gold layer (Phase 6 analytics job).
--
-- Reads the Lakebase OLTP tables through their Unity Catalog registration
-- (`movies_app_dev.movies.*`) and rebuilds three Delta tables in
-- `movies_analytics_dev.movies`. This is the lakehouse side of the
-- architecture: Postgres stays the system of record for bookings (row locks,
-- unique constraints, ms commits — see ddl.sql), Delta is the read-optimized
-- copy for BI/Genie. Target state, not a migration chain, same philosophy as
-- ddl.sql (ADR-002): every run fully replaces every table.
--
-- Catalog/schema names are never hardcoded — they arrive as SQL task
-- parameters (set in resources/analytics_job.yml from the bundle's own
-- resource names) and are substituted with IDENTIFIER(:param), which is
-- supported for both CREATE TABLE targets and FROM-clause sources on this
-- warehouse (verified against movies_analytics_warehouse before wiring the
-- job). The only thing this file assumes about a target environment is that
-- it has a matching set of four parameters.
--
-- CREATE OR REPLACE TABLE ... AS SELECT does not accept an explicit column
-- list ("Schema may not be specified in a Replace Table As Select
-- statement"), so column comments are applied as a second pass with
-- ALTER TABLE ... ALTER COLUMN ... COMMENT, one statement per column. Verbose,
-- but it is what the warehouse accepts, and Genie reads exactly this
-- metadata to answer questions over these tables.
--
-- Every showtime join to booking_seats is a LEFT JOIN: a showtime nobody
-- booked is a real data point (an empty slot in the demand signal), not a
-- row to drop.

-- ============================================================ 1. showtime_occupancy
-- Grain: one row per showtime.

CREATE OR REPLACE TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy')
COMMENT 'Gold. One row per showtime: seats sold, revenue and occupancy, including showtimes with zero bookings. Source: movies_app_dev.movies (Lakebase, via Unity Catalog). Rebuilt on every job run.'
AS
WITH capacity AS (
    SELECT
        auditorium_id,
        row_count * seats_per_row AS capacity
    FROM IDENTIFIER(:lakebase_catalog || '.' || :lakebase_schema || '.auditoriums')
),
agg AS (
    SELECT
        st.showtime_id,
        st.movie_id,
        m.title,
        m.genre,
        th.theater_id,
        th.name              AS theater_name,
        th.city,
        st.auditorium_id,
        au.name              AS auditorium_name,
        st.starts_at,
        cap.capacity,
        st.price_standard,
        st.price_premium,
        count(bs.seat_id)         AS seats_sold,
        coalesce(sum(bs.price), 0) AS revenue
    FROM IDENTIFIER(:lakebase_catalog || '.' || :lakebase_schema || '.showtimes') st
    JOIN IDENTIFIER(:lakebase_catalog || '.' || :lakebase_schema || '.movies') m
        ON m.movie_id = st.movie_id
    JOIN IDENTIFIER(:lakebase_catalog || '.' || :lakebase_schema || '.auditoriums') au
        ON au.auditorium_id = st.auditorium_id
    JOIN IDENTIFIER(:lakebase_catalog || '.' || :lakebase_schema || '.theaters') th
        ON th.theater_id = au.theater_id
    JOIN capacity cap
        ON cap.auditorium_id = st.auditorium_id
    LEFT JOIN IDENTIFIER(:lakebase_catalog || '.' || :lakebase_schema || '.booking_seats') bs
        ON bs.showtime_id = st.showtime_id
    GROUP BY
        st.showtime_id, st.movie_id, m.title, m.genre, th.theater_id, th.name, th.city,
        st.auditorium_id, au.name, st.starts_at, cap.capacity, st.price_standard, st.price_premium
)
SELECT
    showtime_id,
    movie_id,
    title,
    genre,
    theater_id,
    theater_name,
    city,
    auditorium_id,
    auditorium_name,
    starts_at,
    date(starts_at)                AS show_date,
    date_format(starts_at, 'EEEE') AS day_of_week,
    CASE hour(starts_at)
        WHEN 11 THEN 'matinee'
        WHEN 15 THEN 'afternoon'
        WHEN 19 THEN 'evening'
        WHEN 22 THEN 'late'
        ELSE 'other'
    END                             AS time_slot,
    capacity,
    seats_sold,
    capacity - seats_sold                    AS seats_available,
    round(100.0 * seats_sold / capacity, 1)  AS occupancy_pct,
    revenue,
    price_standard,
    price_premium,
    round(100.0 * seats_sold / capacity, 1) >= 95 AS is_sellout,
    starts_at < current_timestamp()               AS is_settled
FROM agg;

ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN showtime_id      COMMENT 'Lakebase showtime id (movies_app_dev.movies.showtimes.showtime_id). Primary key of this table.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN movie_id         COMMENT 'Lakebase movie id.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN title            COMMENT 'Movie title.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN genre            COMMENT 'Movie genre.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN theater_id       COMMENT 'Lakebase theater id.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN theater_name     COMMENT 'Theater name.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN city             COMMENT 'City the theater is in.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN auditorium_id    COMMENT 'Lakebase auditorium id. One auditorium plays one showtime at a time.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN auditorium_name  COMMENT 'Auditorium name/number within the theater.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN starts_at        COMMENT 'Showtime start, UTC.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN show_date        COMMENT 'Calendar date (UTC) the showtime starts on.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN day_of_week      COMMENT 'Full weekday name (UTC) the showtime starts on, e.g. Monday.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN time_slot        COMMENT 'Screening slot derived from the UTC start hour: matinee (11:00), afternoon (15:00), evening (19:30) or late (22:15).';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN capacity         COMMENT 'Total bookable seats in the auditorium (row_count * seats_per_row). Fixed per auditorium, independent of sales.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN seats_sold       COMMENT 'Count of seats booked for this showtime (rows in booking_seats). 0 for a showtime nobody has booked yet.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN seats_available  COMMENT 'capacity - seats_sold. Seats still bookable as of the job run.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN occupancy_pct    COMMENT 'Percent of the auditorium''s seats sold for this showtime, 0-100, rounded to 1 decimal.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN revenue          COMMENT 'Sum of booking_seats.price for this showtime, in USD. 0 if unsold.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN price_standard   COMMENT 'Listed price for a standard/accessible seat at this showtime, USD.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN price_premium    COMMENT 'Listed price for a premium seat at this showtime, USD.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN is_sellout       COMMENT 'True if occupancy_pct >= 95, i.e. the showtime is effectively sold out.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy') ALTER COLUMN is_settled       COMMENT 'True once the showtime has started (starts_at < now). Settled rows are final; unsettled rows can still gain bookings before the demo re-seed.';

-- ============================================================ 2. demand_by_movie_theater_slot
-- Grain: movie x theater x time_slot, SETTLED showtimes only (starts_at <
-- now at job-run time). Forward showtimes are still filling with bookings
-- right up to the demo, so including them would understate true demand;
-- built from showtime_occupancy rather than re-deriving the join, since the
-- per-showtime numbers are already correct there.

CREATE OR REPLACE TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.demand_by_movie_theater_slot')
COMMENT 'Gold. One row per movie x theater x time_slot, aggregated over SETTLED showtimes only (starts_at in the past at job-run time), so demand reflects actual attendance rather than still-filling future bookings. Answers "where should we add showings?". Source: showtime_occupancy.'
AS
SELECT
    movie_id,
    title,
    genre,
    theater_id,
    theater_name,
    city,
    time_slot,
    count(*)                                                          AS showtimes_offered,
    sum(capacity)                                                      AS seats_offered,
    sum(seats_sold)                                                    AS seats_sold,
    round(100.0 * sum(seats_sold) / sum(capacity), 1)                  AS occupancy_pct,
    sum(CASE WHEN is_sellout THEN 1 ELSE 0 END)                        AS sellouts,
    round(100.0 * sum(CASE WHEN is_sellout THEN 1 ELSE 0 END) / count(*), 1) AS sellout_rate,
    sum(revenue)                                                       AS revenue,
    round(sum(revenue) / count(*), 2)                                  AS revenue_per_showtime
FROM IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.showtime_occupancy')
WHERE is_settled
GROUP BY movie_id, title, genre, theater_id, theater_name, city, time_slot;

ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.demand_by_movie_theater_slot') ALTER COLUMN movie_id              COMMENT 'Lakebase movie id.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.demand_by_movie_theater_slot') ALTER COLUMN title                 COMMENT 'Movie title.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.demand_by_movie_theater_slot') ALTER COLUMN genre                 COMMENT 'Movie genre.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.demand_by_movie_theater_slot') ALTER COLUMN theater_id            COMMENT 'Lakebase theater id.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.demand_by_movie_theater_slot') ALTER COLUMN theater_name          COMMENT 'Theater name.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.demand_by_movie_theater_slot') ALTER COLUMN city                  COMMENT 'City the theater is in.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.demand_by_movie_theater_slot') ALTER COLUMN time_slot             COMMENT 'Screening slot: matinee (11:00 UTC), afternoon (15:00), evening (19:30) or late (22:15).';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.demand_by_movie_theater_slot') ALTER COLUMN showtimes_offered     COMMENT 'Number of settled showtimes for this movie/theater/slot combination.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.demand_by_movie_theater_slot') ALTER COLUMN seats_offered         COMMENT 'Total capacity across those showtimes (sum of showtime_occupancy.capacity).';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.demand_by_movie_theater_slot') ALTER COLUMN seats_sold            COMMENT 'Total seats booked across those showtimes.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.demand_by_movie_theater_slot') ALTER COLUMN occupancy_pct         COMMENT 'seats_sold / seats_offered as a percentage, 0-100, 1 decimal. The core demand signal: which movie/theater/slot combinations sell out and which do not.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.demand_by_movie_theater_slot') ALTER COLUMN sellouts              COMMENT 'Count of showtimes in this group that were effectively sold out (occupancy_pct >= 95).';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.demand_by_movie_theater_slot') ALTER COLUMN sellout_rate           COMMENT 'sellouts / showtimes_offered as a percentage, 0-100, 1 decimal.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.demand_by_movie_theater_slot') ALTER COLUMN revenue               COMMENT 'Total booking_seats revenue across those showtimes, USD.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.demand_by_movie_theater_slot') ALTER COLUMN revenue_per_showtime  COMMENT 'revenue / showtimes_offered, USD. Normalizes movies/theaters with different showtime counts for fair comparison.';

-- ============================================================ 3. revenue_by_day
-- Grain: show_date x theater.

CREATE OR REPLACE TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.revenue_by_day')
COMMENT 'Gold. One row per calendar date (UTC) x theater: showtimes offered, distinct bookings, seats sold and revenue. Source: movies_app_dev.movies (Lakebase, via Unity Catalog). Rebuilt on every job run.'
AS
WITH capacity AS (
    SELECT
        auditorium_id,
        row_count * seats_per_row AS capacity
    FROM IDENTIFIER(:lakebase_catalog || '.' || :lakebase_schema || '.auditoriums')
),
per_showtime AS (
    -- One row per showtime first, so capacity and distinct booking counts
    -- are not inflated by the join to booking_seats (a showtime with many
    -- sold seats would otherwise duplicate its capacity once per seat row).
    SELECT
        st.showtime_id,
        date(st.starts_at) AS show_date,
        th.theater_id,
        th.name             AS theater_name,
        th.city,
        cap.capacity,
        st.starts_at,
        count(bs.seat_id)              AS seats_sold,
        coalesce(sum(bs.price), 0)     AS revenue,
        count(DISTINCT bs.booking_id)  AS bookings
    FROM IDENTIFIER(:lakebase_catalog || '.' || :lakebase_schema || '.showtimes') st
    JOIN IDENTIFIER(:lakebase_catalog || '.' || :lakebase_schema || '.auditoriums') au
        ON au.auditorium_id = st.auditorium_id
    JOIN IDENTIFIER(:lakebase_catalog || '.' || :lakebase_schema || '.theaters') th
        ON th.theater_id = au.theater_id
    JOIN capacity cap
        ON cap.auditorium_id = st.auditorium_id
    LEFT JOIN IDENTIFIER(:lakebase_catalog || '.' || :lakebase_schema || '.booking_seats') bs
        ON bs.showtime_id = st.showtime_id
    GROUP BY st.showtime_id, show_date, th.theater_id, th.name, th.city, cap.capacity, st.starts_at
)
SELECT
    show_date,
    theater_id,
    theater_name,
    city,
    count(*)                                          AS showtimes_offered,
    -- Safe to sum per-showtime distinct booking counts: a booking is for
    -- exactly one showtime (bookings.showtime_id is fixed per booking), so
    -- no booking is double-counted across the showtimes summed here.
    sum(bookings)                                      AS bookings,
    sum(seats_sold)                                     AS seats_sold,
    sum(capacity)                                        AS seats_offered,
    round(100.0 * sum(seats_sold) / sum(capacity), 1)     AS occupancy_pct,
    sum(revenue)                                          AS revenue,
    max(starts_at) < current_timestamp()                  AS is_settled
FROM per_showtime
GROUP BY show_date, theater_id, theater_name, city;

ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.revenue_by_day') ALTER COLUMN show_date          COMMENT 'Calendar date (UTC) the showtimes start on.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.revenue_by_day') ALTER COLUMN theater_id        COMMENT 'Lakebase theater id.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.revenue_by_day') ALTER COLUMN theater_name      COMMENT 'Theater name.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.revenue_by_day') ALTER COLUMN city              COMMENT 'City the theater is in.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.revenue_by_day') ALTER COLUMN showtimes_offered COMMENT 'Number of showtimes at this theater on this date.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.revenue_by_day') ALTER COLUMN bookings         COMMENT 'Distinct bookings made for this theater/date (count of distinct booking_seats.booking_id).';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.revenue_by_day') ALTER COLUMN seats_sold       COMMENT 'Total seats booked at this theater on this date, across all showtimes.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.revenue_by_day') ALTER COLUMN seats_offered    COMMENT 'Total capacity at this theater on this date, across all showtimes.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.revenue_by_day') ALTER COLUMN occupancy_pct    COMMENT 'seats_sold / seats_offered as a percentage, 0-100, 1 decimal.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.revenue_by_day') ALTER COLUMN revenue          COMMENT 'Total booking_seats revenue at this theater on this date, USD.';
ALTER TABLE IDENTIFIER(:analytics_catalog || '.' || :analytics_schema || '.revenue_by_day') ALTER COLUMN is_settled       COMMENT 'True once every showtime at this theater on this date has started (max starts_at < now). False means the day''s total can still grow before the demo re-seed.';
