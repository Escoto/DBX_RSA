-- Movies booking app — Delta gold layer (Phase 6 analytics job). See ADR-010
-- and the header of gold_showtime_occupancy.sql for the full rationale
-- (Materialized Views over Lakehouse Federation, why the gold layer is split
-- into three files — one CREATE MATERIALIZED VIEW per sql_task — and how
-- column comments are applied with COMMENT ON COLUMN).
--
-- Runs as the `revenue_by_day` task in resources/analytics_job.yml. Reads
-- directly from the Lakebase tables (not from showtime_occupancy), so it has
-- no dependency on the other two tasks and can run in parallel with them.
--
-- Grain: show_date x theater.

CREATE OR REPLACE MATERIALIZED VIEW IDENTIFIER(:revenue_by_day_fqn)
COMMENT 'Gold. One row per calendar date (UTC) x theater: showtimes offered, distinct bookings, seats sold and revenue. Source: movies_app_dev.movies (Lakebase, via Unity Catalog). Rebuilt on every job run (full recompute — Lakehouse Federation over Postgres has no incremental refresh path, ADR-010).'
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

COMMENT ON COLUMN IDENTIFIER(:revenue_by_day_fqn).show_date          IS 'Calendar date (UTC) the showtimes start on.';
COMMENT ON COLUMN IDENTIFIER(:revenue_by_day_fqn).theater_id        IS 'Lakebase theater id.';
COMMENT ON COLUMN IDENTIFIER(:revenue_by_day_fqn).theater_name      IS 'Theater name.';
COMMENT ON COLUMN IDENTIFIER(:revenue_by_day_fqn).city              IS 'City the theater is in.';
COMMENT ON COLUMN IDENTIFIER(:revenue_by_day_fqn).showtimes_offered IS 'Number of showtimes at this theater on this date.';
COMMENT ON COLUMN IDENTIFIER(:revenue_by_day_fqn).bookings         IS 'Distinct bookings made for this theater/date (count of distinct booking_seats.booking_id).';
COMMENT ON COLUMN IDENTIFIER(:revenue_by_day_fqn).seats_sold       IS 'Total seats booked at this theater on this date, across all showtimes.';
COMMENT ON COLUMN IDENTIFIER(:revenue_by_day_fqn).seats_offered    IS 'Total capacity at this theater on this date, across all showtimes.';
COMMENT ON COLUMN IDENTIFIER(:revenue_by_day_fqn).occupancy_pct    IS 'seats_sold / seats_offered as a percentage, 0-100, 1 decimal.';
COMMENT ON COLUMN IDENTIFIER(:revenue_by_day_fqn).revenue          IS 'Total booking_seats revenue at this theater on this date, USD.';
COMMENT ON COLUMN IDENTIFIER(:revenue_by_day_fqn).is_settled       IS 'True once every showtime at this theater on this date has started (max starts_at < now). False means the day''s total can still grow before the demo re-seed.';
