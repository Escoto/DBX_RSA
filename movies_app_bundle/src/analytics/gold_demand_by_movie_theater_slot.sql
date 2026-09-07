-- Movies booking app — Delta gold layer (Phase 6 analytics job). See ADR-010
-- and the header of gold_showtime_occupancy.sql for the full rationale
-- (Materialized Views over Lakehouse Federation, why the gold layer is split
-- into three files — one CREATE MATERIALIZED VIEW per sql_task — and how
-- column comments are applied with COMMENT ON COLUMN).
--
-- Runs as the `demand_by_movie_theater_slot` task in resources/analytics_job.yml,
-- with a depends_on the `showtime_occupancy` task: this MV reads FROM the
-- showtime_occupancy MV, so it must run after that one has (re)built.
--
-- Grain: movie x theater x time_slot, SETTLED showtimes only (starts_at <
-- now at job-run time). Forward showtimes are still filling with bookings
-- right up to the demo, so including them would understate true demand;
-- built from showtime_occupancy rather than re-deriving the join, since the
-- per-showtime numbers are already correct there.

CREATE OR REPLACE MATERIALIZED VIEW IDENTIFIER(:demand_by_movie_theater_slot_fqn)
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
FROM IDENTIFIER(:showtime_occupancy_fqn)
WHERE is_settled
GROUP BY movie_id, title, genre, theater_id, theater_name, city, time_slot;

COMMENT ON COLUMN IDENTIFIER(:demand_by_movie_theater_slot_fqn).movie_id              IS 'Lakebase movie id.';
COMMENT ON COLUMN IDENTIFIER(:demand_by_movie_theater_slot_fqn).title                 IS 'Movie title.';
COMMENT ON COLUMN IDENTIFIER(:demand_by_movie_theater_slot_fqn).genre                 IS 'Movie genre.';
COMMENT ON COLUMN IDENTIFIER(:demand_by_movie_theater_slot_fqn).theater_id            IS 'Lakebase theater id.';
COMMENT ON COLUMN IDENTIFIER(:demand_by_movie_theater_slot_fqn).theater_name          IS 'Theater name.';
COMMENT ON COLUMN IDENTIFIER(:demand_by_movie_theater_slot_fqn).city                  IS 'City the theater is in.';
COMMENT ON COLUMN IDENTIFIER(:demand_by_movie_theater_slot_fqn).time_slot             IS 'Screening slot: matinee (11:00 UTC), afternoon (15:00), evening (19:30) or late (22:15).';
COMMENT ON COLUMN IDENTIFIER(:demand_by_movie_theater_slot_fqn).showtimes_offered     IS 'Number of settled showtimes for this movie/theater/slot combination.';
COMMENT ON COLUMN IDENTIFIER(:demand_by_movie_theater_slot_fqn).seats_offered         IS 'Total capacity across those showtimes (sum of showtime_occupancy.capacity).';
COMMENT ON COLUMN IDENTIFIER(:demand_by_movie_theater_slot_fqn).seats_sold            IS 'Total seats booked across those showtimes.';
COMMENT ON COLUMN IDENTIFIER(:demand_by_movie_theater_slot_fqn).occupancy_pct         IS 'seats_sold / seats_offered as a percentage, 0-100, 1 decimal. The core demand signal: which movie/theater/slot combinations sell out and which do not.';
COMMENT ON COLUMN IDENTIFIER(:demand_by_movie_theater_slot_fqn).sellouts              IS 'Count of showtimes in this group that were effectively sold out (occupancy_pct >= 95).';
COMMENT ON COLUMN IDENTIFIER(:demand_by_movie_theater_slot_fqn).sellout_rate           IS 'sellouts / showtimes_offered as a percentage, 0-100, 1 decimal.';
COMMENT ON COLUMN IDENTIFIER(:demand_by_movie_theater_slot_fqn).revenue               IS 'Total booking_seats revenue across those showtimes, USD.';
COMMENT ON COLUMN IDENTIFIER(:demand_by_movie_theater_slot_fqn).revenue_per_showtime  IS 'revenue / showtimes_offered, USD. Normalizes movies/theaters with different showtime counts for fair comparison.';
