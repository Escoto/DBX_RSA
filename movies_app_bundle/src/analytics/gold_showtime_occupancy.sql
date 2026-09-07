-- Movies booking app — Delta gold layer (Phase 6 analytics job).
--
-- Reads the Lakebase OLTP tables through their Unity Catalog registration
-- (`movies_app_dev.movies.*`) and rebuilds three gold objects in
-- `movies_analytics_dev.movies`. This is the lakehouse side of the
-- architecture: Postgres stays the system of record for bookings (row locks,
-- unique constraints, ms commits — see ddl.sql), Delta is the read-optimized
-- copy for BI/Genie. Target state, not a migration chain, same philosophy as
-- ddl.sql (ADR-002): every run fully replaces every object.
--
-- ADR-010 — Materialized Views, not CTAS tables, one file per MV
-- (2026-09-07). Empirically verified on movies_analytics_warehouse before
-- converting this file (this comment block is duplicated in
-- gold_demand_by_movie_theater_slot.sql and gold_revenue_by_day.sql — the
-- three files are siblings, split out of what was one gold.sql):
--   * CREATE MATERIALIZED VIEW over a Lakehouse Federation source (our
--     Postgres-backed movies_app_dev catalog) is accepted and the object
--     populates immediately.
--   * REFRESH MATERIALIZED VIEW succeeds, but DESCRIBE EXTENDED always shows
--     "Last Refresh Type: RECOMPUTED" — every refresh is a full recompute.
--     Lakehouse Federation over Postgres has no CDC/streaming read path, so
--     Enzyme's incremental-maintenance engine cannot do anything but
--     recompute. There is therefore no performance upside to the MV here
--     versus the CTAS this replaced — the upside is a governed object with
--     UC-native refresh history/status ("Refresh Information" in DESCRIBE
--     EXTENDED) instead of an opaque CREATE OR REPLACE TABLE.
--   * Each CREATE (OR REPLACE) MATERIALIZED VIEW gets an implicit backing
--     Lakeflow pipeline (named "MV-<catalog>.<schema>.<view>"), serverless,
--     billed only while an update is running (idle cost verified as $0 — the
--     pipeline sits IDLE between refreshes). Repeated CREATE OR REPLACE calls
--     against an *already-materialized-view* target reuse the same pipeline
--     id (verified), so re-running this job going forward does not leak a new
--     pipeline, event log or materialization table per run.
--   * Each MV also permanently owns two hidden UC tables in this same schema:
--     `event_log_<pipeline_id>` and
--     `__materialization_mat_<pipeline_id>_<view>_1` (verified — visible in
--     information_schema.tables, table_type MANAGED). These are not test
--     debris and not something this job or a `DROP ... IF EXISTS` cleans up;
--     they are the MV's own storage/telemetry for as long as the MV exists,
--     and they only disappear if the MV itself is dropped. Expect Catalog
--     Explorer to show 9 objects in movies_analytics_dev.movies (3 gold MVs +
--     6 of these), not 3.
--   * MATERIALIZED_VIEW_OPERATION_NOT_ALLOWED.REPLACE_DELTA_LIVE_TABLE
--     (verified): CREATE OR REPLACE MATERIALIZED VIEW cannot convert an
--     existing plain Delta TABLE of the same name into an MV — only DROP
--     TABLE + CREATE can. Converting these three objects from the CTAS tables
--     Phase 7 built therefore needed a one-time `DROP TABLE IF EXISTS` run by
--     hand outside this file (2026-09-07), not a step baked in here: a
--     DROP-then-CREATE pattern *inside* this script would tear down and
--     rebuild the pipeline on every single job run, and each teardown leaves
--     an orphaned `event_log_<pipeline_id>` and
--     `__materialization_mat_<pipeline_id>_<view>_1` table behind in this
--     schema (verified — neither DROP MATERIALIZED VIEW nor DROP TABLE
--     garbage-collects them). Doing the conversion once, by hand, means this
--     file only ever needs a stable, artifact-free CREATE OR REPLACE against
--     an object that is already a materialized view. If this file is ever
--     pointed at a fresh environment where the name doesn't exist yet, the
--     first run is a plain CREATE and needs no such step.
--   * A `resources.pipelines` bundle resource (the alternative "declare a
--     Lakeflow Declarative Pipeline as first-class IaC" option) was tried and
--     rejected: DLT/Lakeflow pipeline SQL libraries only accept
--     `CREATE MATERIALIZED VIEW`, `CREATE STREAMING TABLE`,
--     `APPLY CHANGES INTO` and `SET` statements — a `COMMENT ON COLUMN` in the
--     same file fails pipeline analysis outright (DLTAnalysisException,
--     verified). Keeping comments would have meant a second bundle resource
--     (a job task chained after the pipeline update) purely to run the column
--     comments — more moving parts for a refresh semantics that is identical
--     either way (full recompute).
--   * Why three files instead of one: a `sql_task.file` that contains a
--     CREATE MATERIALIZED VIEW is compiled the same way a Lakeflow pipeline
--     SQL file is, and that compiler enforces "exactly one CREATE
--     MATERIALIZED VIEW / STREAMING TABLE / LIVE TABLE statement" per file —
--     verified by reproducing `[...] statement expected, but 0 found` when
--     this job ran the original single gold.sql with three CREATE
--     MATERIALIZED VIEW statements in it. Mixing one CREATE MATERIALIZED VIEW
--     with unrelated statements (COMMENT ON COLUMN, in this case) in the same
--     file is fine — verified with a one-off job submission — so each of the
--     three gold objects gets its own file (this one, plus
--     gold_demand_by_movie_theater_slot.sql and gold_revenue_by_day.sql), and
--     resources/analytics_job.yml runs the three as separate sql_tasks
--     instead of the previous single task on one gold.sql.
--   * The CREATE MATERIALIZED VIEW target itself has the same IDENTIFIER(...)
--     restriction as COMMENT ON COLUMN, one level further than expected: it
--     must be IDENTIFIER(:single_param), not IDENTIFIER(:cat || '.' || :sch
--     || '.table'). That concatenation form works for a plain CREATE TABLE
--     (the CTAS this replaced used it) and for every FROM-clause source in
--     these files, but it is invisible to whatever pre-parses a sql_task file
--     for "is there exactly one CREATE MATERIALIZED VIEW here" — verified by
--     reproducing the same `0 found` error from a file whose only difference
--     from a passing one was the target using concatenation instead of a bare
--     parameter. So the CREATE target below uses the same `*_fqn` parameter
--     the COMMENT ON COLUMN pass already needed.
--
-- Catalog/schema names are never hardcoded — they arrive as SQL task
-- parameters (set in resources/analytics_job.yml from the bundle's own
-- resource names) and are substituted with IDENTIFIER(:param), which is
-- supported for both CREATE MATERIALIZED VIEW targets and FROM-clause sources
-- on this warehouse (verified against movies_analytics_warehouse before
-- wiring the job).
--
-- CREATE (OR REPLACE) MATERIALIZED VIEW does not accept an inline column list
-- with comments the way it looks like it should: the CREATE succeeds and
-- silently drops the column comments (verified — DESCRIBE / information_schema
-- both come back null). Column comments are therefore applied as a second
-- pass with COMMENT ON COLUMN ... IS '...', one statement per column — the MV
-- equivalent of the ALTER TABLE ... ALTER COLUMN ... COMMENT pass a plain
-- table would use (ALTER TABLE itself rejects a view/MV target:
-- EXPECT_TABLE_NOT_VIEW.NO_ALTERNATIVE, verified). One more wrinkle, also
-- verified empirically: COMMENT ON COLUMN's IDENTIFIER(...) target accepts a
-- single bare parameter but not a concatenation expression inside it (the
-- `:analytics_catalog || '.' || :analytics_schema || '.table'` form used for
-- CREATE/FROM elsewhere in this file throws PARSE_SYNTAX_ERROR here). So each
-- gold table's fully qualified name arrives pre-concatenated as its own
-- parameter (`*_fqn`, built with bundle `${...}` interpolation in
-- resources/analytics_job.yml, not a runtime SQL expression), and the column
-- name is appended as a literal after IDENTIFIER(:table_fqn).column_name.
-- Table-level comments do not have this problem: COMMENT '...' inline on
-- CREATE (OR REPLACE) MATERIALIZED VIEW works and is reasserted on every run
-- (a CREATE OR REPLACE with no COMMENT clause silently clears a previously-set
-- one — verified — so the statement below always carries its COMMENT).
--
-- Every showtime join to booking_seats is a LEFT JOIN: a showtime nobody
-- booked is a real data point (an empty slot in the demand signal), not a
-- row to drop.

-- ============================================================ showtime_occupancy
-- Grain: one row per showtime.

CREATE OR REPLACE MATERIALIZED VIEW IDENTIFIER(:showtime_occupancy_fqn)
COMMENT 'Gold. One row per showtime: seats sold, revenue and occupancy, including showtimes with zero bookings. Source: movies_app_dev.movies (Lakebase, via Unity Catalog). Rebuilt on every job run (full recompute — Lakehouse Federation over Postgres has no incremental refresh path, ADR-010).'
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

COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).showtime_id      IS 'Lakebase showtime id (movies_app_dev.movies.showtimes.showtime_id). Primary key of this table.';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).movie_id         IS 'Lakebase movie id.';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).title            IS 'Movie title.';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).genre            IS 'Movie genre.';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).theater_id       IS 'Lakebase theater id.';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).theater_name     IS 'Theater name.';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).city             IS 'City the theater is in.';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).auditorium_id    IS 'Lakebase auditorium id. One auditorium plays one showtime at a time.';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).auditorium_name  IS 'Auditorium name/number within the theater.';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).starts_at        IS 'Showtime start, UTC.';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).show_date        IS 'Calendar date (UTC) the showtime starts on.';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).day_of_week      IS 'Full weekday name (UTC) the showtime starts on, e.g. Monday.';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).time_slot        IS 'Screening slot derived from the UTC start hour: matinee (11:00), afternoon (15:00), evening (19:30) or late (22:15).';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).capacity         IS 'Total bookable seats in the auditorium (row_count * seats_per_row). Fixed per auditorium, independent of sales.';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).seats_sold       IS 'Count of seats booked for this showtime (rows in booking_seats). 0 for a showtime nobody has booked yet.';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).seats_available  IS 'capacity - seats_sold. Seats still bookable as of the job run.';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).occupancy_pct    IS 'Percent of the auditorium''s seats sold for this showtime, 0-100, rounded to 1 decimal.';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).revenue          IS 'Sum of booking_seats.price for this showtime, in USD. 0 if unsold.';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).price_standard   IS 'Listed price for a standard/accessible seat at this showtime, USD.';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).price_premium    IS 'Listed price for a premium seat at this showtime, USD.';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).is_sellout       IS 'True if occupancy_pct >= 95, i.e. the showtime is effectively sold out.';
COMMENT ON COLUMN IDENTIFIER(:showtime_occupancy_fqn).is_settled       IS 'True once the showtime has started (starts_at < now). Settled rows are final; unsettled rows can still gain bookings before the demo re-seed.';
