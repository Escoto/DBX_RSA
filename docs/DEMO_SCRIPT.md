# Demo script — Wednesday 2026-09-09

Eight minutes of clicking, plus the answers to the questions the panel will ask
while you click. Everything below runs on the `dev` target in the Slalom
workspace `dbc-66830d2c-97a4`.

**Links, in the order you need them**

| # | What | URL |
|---|------|-----|
| 1 | The app | https://movies-app-dev-2485046985091381.aws.databricksapps.com |
| 2 | Lakebase in Catalog Explorer | https://dbc-66830d2c-97a4.cloud.databricks.com/explore/data/movies_app_dev/movies |
| 3 | Dashboard | https://dbc-66830d2c-97a4.cloud.databricks.com/dashboardsv3/01f1aabfa9f11c97981e76b48407fa28?o=2485046985091381 |
| 4 | Genie space | https://dbc-66830d2c-97a4.cloud.databricks.com/genie/rooms/01f1aabfd22f1ac5a20063d5511ba352?o=2485046985091381 |
| 5 | Gold tables | https://dbc-66830d2c-97a4.cloud.databricks.com/explore/data/movies_analytics_dev/movies |
| 6 | Analytics job | https://dbc-66830d2c-97a4.cloud.databricks.com/jobs/743598470449255 |

Have 1, 3 and 4 open in tabs before you start. Do not navigate by typing.

---

## Step zero — the pre-flight (start 30 minutes early, not 5)

Everything here is stopped between sessions and none of it starts instantly.
Run these in order - deploying before the database is up is the one mistake that
costs you the most time.

1. **Start the Lakebase instance first, and wait for it** — ≥15 min ahead.
   Do this *out of band*, not with a deploy: every deploy updates the app, and
   an app update cannot resolve its `database` resource while the endpoint is
   disabled, so a deploy fails against a stopped **or still starting** instance.

   From `movies_app_bundle/` inside WSL (`make` does not exist in Git Bash):

   ```bash
   make start
   ```

   That starts the instance, polls until `AVAILABLE` printing a dot per 15s
   (10-15 min, gives up after 20 with the last state), then starts the app.
   It does **not** deploy. Run `make release` after it finishes if anything has
   changed since the last deploy - never before or during.
2. **Re-seed with `--reset`.** Showtime ids are relative to the run date, so the
   window has to be re-cut on the day; `--reset` also clears any test bookings
   so the seat map looks deliberate.

   ```bash
   make reseed
   ```

   Read the report it prints. `top demand, settled shows` must show **Iron
   Meridian / Slalom Cinema Downtown around 97%** at the top. If that line is
   missing or flat, the demand model did not load and the analytics half of the
   demo has nothing to show.
3. **Re-run the gold job.** Non-negotiable: the gold tables are a snapshot, and
   the re-seed just moved every showtime. Until this finishes, the dashboard's
   demand page and the entire Genie space describe yesterday.

   ```bash
   wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/repos/apps/dbx-movies-app/movies_app_bundle && databricks bundle run analytics_job -t dev"
   ```
4. **Start the SQL warehouse** (~20 s, auto-stops after 20 min) by opening the
   dashboard (link 3) and letting both pages load. Leave the tab open — 20
   minutes of idle will stop it again, so re-open it if the panel runs long
   before you reach step 5.
5. **Check the app**: `/api/health` reports `db: connected`, and the movies grid
   loads with all eight titles.

---

## 1 · The app (2 min)

Open link 1. Browse → pick **Iron Meridian** → pick **Slalom Cinema Downtown**
→ open the **19:30 evening** showtime.

> "Eight movies, three theaters, five auditoriums. The seat map is one query:
> the auditorium's seats left-joined to the seats already sold for this
> showtime."

The map will be visibly busy — that evening show runs 80–95% full. Point at it:

> "That is not random. The seed carries a demand model — popular titles, prime
> slots, weekend bumps — because a demo where every room is 5% full can't
> support any analytics story. I'll come back to this."

Book **two seats**, give a name and email, confirm. Land on the confirmation
page. **Note the seat labels** — you need them twice more.

## 2 · The invariant (2 min)

Open a second browser window, same showtime, and try to book **the same two
seats**. You get a `409` and the map marks them taken.

> "`UNIQUE (showtime_id, seat_id)` on `booking_seats`, and the whole booking is
> one transaction. Postgres serialises the two inserts on the same key; the
> loser rolls back and the API translates the unique violation into a 409 that
> names the seats. There is no application-level locking and no
> verify-then-write race — the database is the thing enforcing it."

If asked why not Delta: assigned-seat booking is OLTP — row locks, unique
constraints, millisecond commits. Delta enforces no uniqueness and spans no
multi-table transaction.

Now open link 2 (Catalog Explorer → `movies_app_dev.movies.booking_seats`) and
show the row you just created.

> "Same rows. This is a Postgres database registered in Unity Catalog, so it is
> governed and queryable from a warehouse without anyone building a pipeline."

## 3 · The live dashboard (1.5 min)

Open link 3, **Live operations** page. Point at *The next showtimes, filling up*
— your showtime, with the two seats you just bought included in its count.

> "This page reads the Lakebase tables directly through the Unity Catalog
> registration. There is no ETL between the booking I made forty seconds ago and
> this tile — the warehouse is querying the OLTP store live."

Hit refresh once so they see the number move if a seat was booked meanwhile.

Then the bottom table, *Where a new showing could physically go*:

> "And this is derived, not hardcoded: every room × slot combination in the next
> seven days, and which ones are running nothing. Three rooms are idle."

## 4 · Demand, and Genie (2.5 min)

Switch to the **Demand & programming** page.

> "This half reads Delta gold tables instead — `showtime_occupancy`,
> `demand_by_movie_theater_slot`, `revenue_by_day`, built by a bundle job from
> the same Lakebase catalog. Two weeks of settled shows, because forward
> bookings are still filling and would understate demand."

Point at the top of the demand bar chart: Iron Meridian evenings.

Now open link 4 and ask the Genie space, typing it live:

> **Where and for which movies should we open new functions based on popularity?**

Expected answer: **Iron Meridian, evening, at Slalom Cinema Downtown** (~97%
occupancy, ~79% sellout rate, 14 showtimes, ~$1,800 per showing) and at Lakeview
Picturehouse (~91%). Open the generated SQL and show it.

> "The space has one instruction block: a glossary that says a *function* is a
> showtime, the rule that occupancy percentages have different denominators and
> must be recomputed rather than averaged, and the ranking procedure — minimum
> three showings before a combination counts as evidence, and always answer with
> movie *and* theater *and* slot, because 'which movie' alone isn't actionable."

Follow up with a second question to show it is not a canned answer:

> **Which theater has the lowest occupancy, and what is it showing?**

**Say this out loud, before they ask it:**

> "The seed plants that demand signal deliberately. What I did *not* do is
> precompute the recommendation — there's no `expansion_candidates` table. The
> ranking lives in the space's instructions, and Genie derives it. If I'd
> materialised the answer, this would be a lookup, not a demo."

## 5 · It is all one bundle (1 min)

```bash
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/repos/apps/dbx-movies-app/movies_app_bundle && databricks bundle summary -t dev"
```

> "One bundle, one `deploy`: the Lakebase instance, its UC registration, the
> analytics catalog and schema, the warehouse, the app, the gold job, the
> dashboard and the Genie space. The dashboard is a `.lvdash.json` in the repo
> and the Genie space is a `.geniespace.json` — I edit them in the workspace when
> that is faster and round-trip them back with `bundle generate`."

Close on the trade-off you most want them to probe (pick one, do not list all
three): the OLTP/lakehouse split; the enforced-invariant write path; or what
changes at millions of users (README § *Taking it to millions*).

---

## If something breaks

| Symptom | Cause | What to do |
|---|---|---|
| App 500s on every `/api/*` | Lakebase stopped | Start it (~10 min). Talk through the seat map screenshot meanwhile. |
| Dashboard tiles spin, then error | Warehouse cold or auto-stopped | It restarts in ~20 s; refresh. Say "serverless, it was asleep." |
| Live tiles error, demand page fine | Lakebase stopped — the live page is federated straight into it | Same fix; the gold page keeps working, which is itself the point about the two paths. |
| Demand page empty or stale | `analytics_job` not re-run after the re-seed | `bundle run analytics_job` (~1 min), keep talking. |
| Genie answers something odd | Nondeterminism | Re-ask once with the exact wording above. If it still wanders, switch to the *Candidates for more showings* tile — same ranking, same numbers — and say the dashboard is the deterministic version of that answer. |
| No free seats on the showtime | Should not happen: future shows are capped at 94% | Pick the next evening's show. |

**Offline backup:** screenshots in `docs/img/` — seat map, 409, confirmation,
both dashboard pages, Genie's answer with its SQL. *(Still to capture: take them
on the morning, after the re-seed, so the numbers match what you narrate.)*
