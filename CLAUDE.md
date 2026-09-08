# CLAUDE.md — Movie Ticket Booking App on Databricks

Working notes for Claude: scope, state, hazards, commands and rules. Update it
when a decision changes. What the system *is* lives in `README.md` and
`docs/ARCHITECTURE.md`; do not restate it here.

---

## 1. Mission

Take-home exercise for a **Databricks Resident Architect (Slalom)** interview.
The panel is Databricks engineers; the user (Rafael Escoto) demos live on
**Wednesday 2026-09-09** and defends the design.

**The brief:** a working prototype of a movie ticket booking app for millions of
global users: browse movies and showtimes, pick a theater, view a seat map, book
one or more assigned seats. Deployed as a Databricks App, data layer on
Databricks, panel gets code plus assets, short README, docs on data model, API,
trade-offs and scale, and a log of where AI helped and where the human
intervened (`docs/AI_USAGE_LOG.md`).

**Ground rules:** a thin working skeleton beats a broad broken one. Seed fake
data, no real payments or auth, state assumptions where the prompt is vague.
Evaluation: "a builder who ships, thinks in trade-offs, and can defend a design".

---

## 2. Current state (2026-09-08)

**Everything is built and deployed** by the bundle (direct engine, CLI 1.15.0):
Lakebase instance + UC registration, analytics catalog, schema and warehouse,
the app, the analytics job, the dashboard and the Genie space. The full click
path including the `409` on a raced seat is verified on the deployed app.
106 tests pass with `make test`. `docs/DEMO_SCRIPT.md` is written.

**Open items before the demo**

1. `docs/DECISIONS.md` stops at ADR-009. ADR-010 (materialized views instead of
   CTAS tables, one SQL file per view) exists only as the comment block at the
   top of each `src/analytics/gold_*.sql`. Write it up.
2. `docs/img/` screenshots for the offline backup: capture on the morning after
   the re-seed so numbers match the narration.
3. `src/analytics/back/gold.sql` is the pre-ADR-010 single file, still tracked.
   Delete or move it out of the bundle tree. `.claude/agents/databricks-engineer/AGENT.md`
   still references `gold.sql`.
4. Redeploy if anything is committed after the last `bundle run movies_app`.
   Never demo a build that is not the repo.
5. After any edit to the dashboard JSON, open it. The Lakeview API accepts an
   invented `widgetType` with a `200`, so a clean deploy proves nothing. Fix in
   the UI, then round-trip with `bundle generate dashboard`.

**Demo pre-flight, in order, starting 30 minutes ahead:**

1. `make start` (Lakebase takes 10 to 15 min to reach `AVAILABLE`; the app
   starts after it).
2. `make release` only if the repo has moved since the last deploy.
3. `make reseed`, then `databricks bundle run analytics_job -t dev`. The gold
   views are a snapshot, so until the job runs the demand page and Genie
   describe the previous window. The live page needs no rebuild.
4. Open the dashboard once to warm the serverless warehouse (about 20 s cold,
   20 min auto-stop), and check `/api/health` reports `db: connected`.

**Cut, not deferred:** cancellation (ADR-007). **Deferred:** seat holds with
expiry, idempotency keys, the pooling items in ADR-006's *Deferred* table.

### Hazards

1. **Databricks CLI only from WSL Ubuntu 24.04.** The `movies` profile exists
   only there. The Windows CLI's profiles point to `dbc-2ba89670-78df`, a
   **client (BioNTech) workspace that must never be used for this project**.
   Wrap every command:
   `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/repos/apps/dbx-movies-app/movies_app_bundle && databricks ..."`
2. **Never start or stop Lakebase through a deploy.** Every `bundle deploy`
   updates the app, and an app update resolves its `database` resource by
   connecting to the Lakebase endpoint, so **a deploy fails while the instance
   is stopped or still starting** (`FAILED_PRECONDITION ... Endpoint ep-… is
   disabled`). Use `make start` / `make stop` and leave `resources/lakebase.yml`
   at `stopped: false`. Order on demo morning: start, wait for `AVAILABLE`
   (10 to 15 min), then deploy. `make release` also starts app compute, so
   never use it to shut things down.
3. **`bundle destroy` deletes the Lakebase instance and its data.**
   `prevent_destroy` is `false` everywhere. Only the user runs it.
4. **`catalogs` needs the direct engine.** `bundle.engine: direct` stays;
   terraform silently drops the catalog resource.
5. **Git is denied to Claude** (`.claude/settings.json`). The user commits.
6. **Secrets.** `.claude/settings.local.json` holds a Bedrock API key; the WSL
   `~/.databrickscfg` holds a PAT. Never print, copy or reference either.
7. Two unrelated GxP apps exist in the workspace. Leave them alone.
8. **Recreating from scratch changes every id but no name.** After
   `destroy → deploy` the warehouse, dashboard, Genie space, job and the app's
   service principal all get new ids; the resource names and catalog names do
   not, because they come from bundle variables plus the target. `make seed`
   resolves the new service principal itself. The dashboard and Genie JSON
   carry the catalog names as literals (bundle variables do not reach inside
   `file_path` content), so they survive a recreate but need a search-and-
   replace if the target or the catalog variables are ever renamed.

---

## 3. Decisions that steer the work

Full rationale in `docs/DECISIONS.md` and `docs/ARCHITECTURE.md`. The short list:

| Topic | Decision |
|-------|----------|
| Stack | Python 3.11 + FastAPI serving `/api/*` and the Vue 3 + Vite + TS SPA from one app. No state library. |
| System of record | Lakebase. `UNIQUE (showtime_id, seat_id)` on `booking_seats` plus one transaction per booking is the whole double-booking story; the app only translates a unique violation into `409`. |
| Analytics | Two paths by temperature (ADR-009): the dashboard's live page reads `movies_app_dev.movies` federated through UC; the demand page and Genie read the Delta materialized views built by `analytics_job`. |
| Seed data | 21-day window (14 settled + 7 bookable), 4 slots a day, a declared demand model with two deliberate under-served gaps. Genie discovers the gaps; the demo says so out loud. |
| AI/BI as code | Dashboard and Genie space are bundle resources, round-tripped from the UI with `bundle generate`. Genie validates its export strictly; Lakeview validates nothing. |
| SPA build | On the Apps runtime at deploy time (ADR-004). No local `dist` ever reaches the platform. |
| App → DB auth | The app's own service principal with an OAuth database credential; `PGHOST` injected via `value_from: lakebase` (ADR-005). |
| Concurrency | Sync `def` handlers, pooled connections, threadpool sized from the pool, `503` + `Retry-After` on saturation (ADR-006, ADR-008). |
| Scope | No auth, no payments, no seat holds, no cancellation endpoint (ADR-007). USD, UTC. One `dev` target. |

---

## 4. Platform coupling that bites

- **Env injection.** Apps injects `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`,
  `DATABRICKS_CLIENT_SECRET`, `DATABRICKS_APP_PORT`. It does **not** inject
  `PGHOST` just because a `database` resource is attached; that is mapped in
  `resources/app.yml`. Treat every other `PG*` var as optional. `app.yaml`
  carries only the start command; env values live in `resources/app.yml`.
- **Deploy-time build.** Root `movies_app/package.json` makes the deployment
  run `npm install`, `pip install -r requirements.txt`, `npm run build`
  (`cd frontend && npm ci --include=dev && npm run build`) before the start
  command. `--include=dev` matters: every build tool is a devDependency.
- **Postgres grants.** The `database` app resource creates a role named for the
  app SP with CONNECT/CREATE, but the seed script owns the tables, so it also
  grants `USAGE` on the schema and `SELECT, INSERT, UPDATE, DELETE` on all
  tables plus default privileges (given `--app-sp-client-id`). Schemas
  `public`, `__db_system` and the `databricks_*` roles must not be touched.
  The user's role is `ra.escoto@slalom.com`.
- **Analytics job.** Three `sql_task`s, one per `src/analytics/gold_*.sql`,
  `demand_by_movie_theater_slot` depending on `showtime_occupancy`. Catalog
  and view names arrive as task parameters via `IDENTIFIER(:param)`. Schedule
  is daily 09:00 Europe/Berlin but `PAUSED` by `var.schedule`.
- **Dashboard datasets** are verified by executing them as the runtime does:
  concatenate `queryLines` with **no** separator and wrap in `WITH q AS (...)`;
  every line must carry its own `\n` (ADR-009).

---

## 5. Commands

**Every `databricks` command and every `make` target runs inside WSL Ubuntu
24.04** (CLI 1.15.0, profile `movies`; `make` does not exist in Git Bash). The
`dev` target carries the profile, so bundle commands need no `-p`; other CLI
commands do.

```bash
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/repos/apps/dbx-movies-app/movies_app_bundle && databricks bundle validate -t dev"
```

From `movies_app_bundle/` inside WSL:

```bash
make help            # deploy · release · start · stop · seed · reseed · recreate-ddl
make release         # validate + deploy + bundle run movies_app
make start           # start Lakebase, poll to AVAILABLE, start the app
make stop            # stop the app, then Lakebase
make reseed          # seed_lakebase.py --reset (python3.11, app SP grants included)

databricks bundle summary -t dev               # prints "URL: (not deployed)" for the app; trust `apps get`
databricks bundle deploy  -t dev               # resources + code upload; does NOT restart the app
databricks bundle run movies_app -t dev        # new app deployment
databricks bundle run analytics_job -t dev     # rebuild the gold materialized views
databricks bundle generate dashboard   --resource movies_operations --force   # UI edit -> repo
databricks bundle generate genie-space --resource movies_demand     --force

databricks genie start-conversation <space-id> 'Where and for which movies should we open new functions?' -p movies -o json
databricks api post /api/2.0/sql/statements --json @stmt.json -p movies   # any SQL on the warehouse
databricks database get-database-instance movies-app-dev -p movies       # state, read_write_dns
databricks apps get movies-app-dev -p movies                              # URL, status, SP client id
# runtime logs: Databricks UI -> Compute -> Apps -> movies-app-dev -> Logs
```

From `movies_app_bundle/movies_app/` inside WSL (`make help` lists them):
`make setup`, `make run_back` (:8000), `make run_front` (:5173, Windows npm via
interop), `make build` (exactly what the Apps deployment runs), `make test`.

**Python.** WSL `/usr/bin/python3.11` has `databricks-sdk` and `psycopg`, and
matches the Apps runtime; the system `python3` (3.12) has neither. From Windows
Git Bash, Python 3.13 works if pointed at the WSL profile file:
`DATABRICKS_CONFIG_FILE=//wsl.localhost/Ubuntu-24.04/home/raescoto/.databrickscfg DATABRICKS_CONFIG_PROFILE=movies`.
Windows has Node 22 and npm 10; WSL has no Node. **The Apps runtime is Python
3.11: avoid 3.12+ syntax.**

---

## 6. Conventions and rules

1. **Thin slice first.** No feature outside the decisions above without a
   `docs/DECISIONS.md` entry.
2. **Never deploy to a client workspace.** Only the Slalom workspace in §7.
3. **Never run `bundle destroy`.** Only the user does.
4. **No secrets in the repo.** `.env` is gitignored; commit `.env.example` only.
5. **Parameterized SQL only.** `%s` placeholders; identifiers are constants.
6. **Keep bundle variables and resource names in sync**; the
   `databricks-engineer` agent owns that coupling.
7. **State assumptions in code comments where they bite.** The panel reads the
   code.
8. **Update `docs/AI_USAGE_LOG.md` at the end of every phase.**
9. **The frontend is built on the platform.** Pushing code is `bundle deploy`
   then `bundle run movies_app`. Never add `dist` to `sync.include`; never put
   build steps in the `app.yaml` command.
10. **Windows paths.** Forward slashes in YAML/config; quote paths with spaces.

---

## 7. Workspace facts

| Item | Value |
|------|-------|
| Demo workspace | `https://dbc-66830d2c-97a4.cloud.databricks.com` (Slalom; `ra.escoto@slalom.com`, workspace admin; id `2485046985091381`) |
| Bundle state path | `/Workspace/Users/ra.escoto@slalom.com/.bundle/movies_app_bundle/dev` |
| Lakebase instance | `movies-app-dev` (key `movies_db`), CU_1, PG 16, port 5432, `sslmode=require`, native password login disabled. DNS changes on every recreate |
| Lakebase database / schema | `movies_dev` / `movies` |
| UC catalog for Lakebase | `movies_app_dev` (key `catalog_movies_db`) |
| Analytics catalog.schema | `movies_analytics_dev.movies` (keys `movies_analytics`, `movies`) |
| SQL warehouse | `movies_analytics` (key `movies_analytics_warehouse`). In YAML always `${resources.sql_warehouses.movies_analytics_warehouse.id}`, never a literal id |
| AI/BI dashboard | `Movies — live operations and demand` (key `movies_operations`) |
| Genie space | `Movies — cinema demand` (key `movies_demand`) |
| Analytics job | `movies-analytics-gold-dev` (key `analytics_job`) |
| App | `movies-app-dev` (key `movies_app`) · `https://movies-app-dev-2485046985091381.aws.databricksapps.com` (name + workspace id, stable across recreates) |
| Ids and URLs | Not recorded here because they change on recreate. `databricks bundle summary -t dev` prints them; `databricks apps get movies-app-dev -p movies` gives the app's service principal |

---

## 8. Tooling notes for Claude

- Model routing: `.claude/settings.json` maps `opus`/`sonnet`/`haiku` to Bedrock
  EU model ids; session default is Opus.
- The Bash tool breaks on unbalanced single quotes and long `&&` chains. Write
  prose files with Write/Edit; keep shell commands short.
- `databricks bundle schema` (WSL) is the authority for resource fields.
  Lakebase resources: `database_instances`, `database_catalogs`,
  `synced_database_tables`, `apps.*.resources[].database`.
- `databricks-engineer` agent (Sonnet) owns `databricks.yml`, `resources/`,
  `src/seed/`, `src/analytics/`, `app.yaml`. Keep backend and frontend code in
  the main session.
- `/build-check` runs `vue-tsc --noEmit` and `vite build` in
  `movies_app/frontend`. Report only, never auto-fix.
- Skills: `code-review` before the user commits; `security-review` once before
  the demo (the ADR-005 exception handler returns raw exception text to the
  client).
