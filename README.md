# Newsroom Analytics — Cloudflare dashboard (Phase 3)

Self-hosted analytics for **newsband.in** and **naveshahar.com**, built only on
Cloudflare's **free-plan GraphQL Analytics API** (`httpRequestsAdaptiveGroups`).
No Google Analytics, no third-party trackers.

Phase 3 added the visual + interaction layer: a **light/dark toggle** (topbar,
persisted to `localStorage`, re-themes every chart), fully interactive ECharts
(rich tooltips, treemap drill, sunburst zoom, heatmap hover, crosshairs), the
reference look (Space Grotesk / Inter / JetBrains Mono, hero KPI tile, momentum
color-encoding where rising = warm, fading = cool, steady = indigo), and
motion (KPI count-up, line draw-in, staggered fade-up, live pulse — all gated
on `prefers-reduced-motion`). See **Verification** below.

**Panels** (every one reads MySQL rollups; site + range selectors apply everywhere):

| Page | What it answers | Visualization |
|---|---|---|
| Overview | is traffic healthy right now? | KPI tiles + traffic line |
| Top articles | what's exploding, what's dying? | momentum scatter (hits × growth, log x) + sparkline leaderboard |
| Categories | which sections carry the site? | drill-down treemap + 5-axis category radar |
| Errors | when and where is it broken? | path/status × hour heatmap + sortable broken-URLs table |
| Bots & AI | who actually reads us — and who scrapes us? | human/bot sunburst + AI-crawler timeline |
| World | does anyone outside India read us? | world choropleth (non-India focus) + ranked list |

## How the data flows

```
Cloudflare GraphQL API ──> collector.py (hourly cron) ──> MySQL rollups ──> Flask dashboard
                      └── live fallback (Overview only, 1h / 24h) ──┘
```

The collector batches its GraphQL work: cheap dimensions (totals, status,
cache, country) come back for many hours in one call grouped by
`datetimeHour`; only the per-hour top-Ns (paths, user agents, error paths)
need hour-scoped queries, and those are aliased several hours per call.
A 72-hour backfill is ~18 calls per zone (was 72); the hourly cron run is 2.

- All counts are **estimates**: the dataset is adaptively sampled, so every
  count is multiplied by `avg(sampleInterval)` before storing/display.
- Only `requestSource: "eyeball"` (real client) traffic is queried.
- Cloudflare's free-plan retention is short (on the order of days), so MySQL is
  the system of record: **7d/30d ranges read MySQL only**. 1h is always live
  from Cloudflare (minute granularity); 24h reads MySQL and falls back to a
  live query if the collector hasn't populated yet.
- Bot vs human: the free plan has no bot score, so User-Agents are matched
  against a configurable known-bot list ([app/bots.py](app/bots.py), extendable
  via `BOT_UA_FILE`). Assumed humans = eyeball total − UA-identified bots.
- The referrer dimension is not available on the free plan, so there is no
  referrer panel anywhere.

## Setup

Requirements: Python 3.10+, MySQL 8 (already running), a Cloudflare API token.

### 1. Cloudflare API token(s)

The two sites live in **separate Cloudflare accounts**, so each needs its own
token. At <https://dash.cloudflare.com/profile/api-tokens> (signed into that
site's account) create a custom token:

- Permissions: **Zone → Analytics → Read**
- Zone Resources: include that account's zone

Put each token in its own var — `CF_API_TOKEN_NEWSBAND`,
`CF_API_TOKEN_NAVESHAHAR`. `CF_API_TOKEN` is only a shared fallback for sites
without their own token (handy when every zone is in one account). Account ID
is not used by these analytics queries.

Zone IDs are on each zone's **Overview** page (right-hand API column).

### 2. Python environment

```bash
cd "Cloudflare Dashboard"
python -m venv .venv
# Linux/macOS:           source .venv/bin/activate
# Windows (PowerShell):  .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. MySQL database and user

A dedicated schema — nothing else on the server is touched. As a MySQL admin:

```sql
CREATE DATABASE cf_analytics CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'cf_dash'@'localhost' IDENTIFIED BY 'choose-a-password';
GRANT ALL PRIVILEGES ON cf_analytics.* TO 'cf_dash'@'localhost';
FLUSH PRIVILEGES;
```

### 4. Configuration

```bash
cp .env.example .env   # then fill in the values
```

Set each site's token (`CF_API_TOKEN_NEWSBAND`, `CF_API_TOKEN_NAVESHAHAR`),
both zone IDs, and the MySQL credentials. Never commit `.env`.

### 5. Create tables

```bash
python init_db.py
```

### 6. First data pull (backfill)

```bash
python collector.py --hours 72
```

Backfill only reaches as far as Cloudflare still retains data on the free plan
(roughly the last few days) — older hours simply come back empty. Each run
prints one line per zone-hour; re-running an hour overwrites it (upserts).

### 7. Run the dashboard

```bash
python run.py            # http://127.0.0.1:5000
```

For production, use a WSGI server instead of the dev server, e.g.:

```bash
pip install gunicorn && gunicorn -w 2 -b 127.0.0.1:5000 "app:create_app()"
# or on Windows: pip install waitress && waitress-serve --listen=127.0.0.1:5000 --call app:create_app
```

### 8. Cron (keeps history growing)

Run the collector hourly. Each run re-collects the last `COLLECT_HOURS` hours
(default 6), which finalizes partial hours and rides out missed runs.

```cron
7 * * * * cd /path/to/cloudflare-dashboard && .venv/bin/python collector.py >> logs/collector.log 2>&1
```

(On Windows, use Task Scheduler to run `.venv\Scripts\python.exe collector.py`
hourly.) Create the `logs/` directory first.

## Project layout

```
collector.py          cron entry point: batched Cloudflare -> MySQL upserts
init_db.py            one-shot schema setup (also adds missing indexes)
run.py                Flask dev entry point
schema.sql            MySQL schema (hourly rollup tables)
app/
  config.py           .env loading, site/zone registry, CATEGORY_RULES,
                      ARTICLE_EXCLUDE_*, batching/trending knobs
  cloudflare.py       GraphQL client + sampling correction (batched queries)
  bots.py             User-Agent bot classification + bot types (configurable)
  categories.py       path -> category mapping, article-path filter
  db.py               MySQL connections + schema/index bootstrap
  queries.py          read-side SQL for the Overview page
  panels.py           read-side data assembly for all Phase 2 panels
  routes.py           pages + /api/timeseries, /api/kpis, /api/panel/<name>
  templates/, static/ app shell, light/dark theme, per-panel ECharts pages
                      static/js/common.js — tokens, theme switch, chart registry
_verify.py           real-browser test harness (Playwright; see Verification)
```

## Verification

`_verify.py` drives headless Chromium against a live instance and asserts, for
every panel: no console/page errors, each chart initialized with data, the
chart canvas actually receives pointer events, tooltips render, segmented
toggles fire cleanly, and the light/dark switch re-themes the charts. It is the
regression guard for the Phase-2 bug where an un-hidden overlay sat on top of
the canvas and ate every mouse event.

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
python _verify.py            # 48 checks across the 6 panels
python _verify.py --shots    # also writes screenshots to _shots/ (both themes)
```

## MySQL schema (per hour, per zone — all UTC, all estimates)

| Table                     | Key                        | Holds                              |
|---------------------------|----------------------------|------------------------------------|
| `hourly_zone_totals`      | site, hour                 | requests, bytes, cached, 4xx/5xx, bot/human, sampling metadata |
| `hourly_path_stats`       | site, hour, path           | top-N paths: requests, bytes       |
| `hourly_error_path_stats` | site, hour, path, status   | top-N error paths (status ≥ 400)   |
| `hourly_status_stats`     | site, hour, status         | requests per HTTP status           |
| `hourly_cache_stats`      | site, hour, cacheStatus    | requests, bytes per cache status   |
| `hourly_country_stats`    | site, hour, country        | requests per country               |
| `hourly_bot_stats`        | site, hour, bot name       | requests per identified bot        |

`hourly_error_path_stats` was added in Phase 2: per-path error counts aren't
derivable from the other tables, so the collector grabs them as an extra
aliased selection inside its existing per-hour call (no additional HTTP
requests). Run `python init_db.py` after upgrading — it creates the table and
any missing indexes on existing databases.

## Editorial configuration

- **Categories** — `CATEGORY_RULES` in [app/config.py](app/config.py): ordered
  `(path prefix, label)` pairs; unmatched paths fall back to a prettified
  first segment. `ARTICLE_EXCLUDE_PREFIXES/SUFFIXES` filter assets, feeds and
  APIs out of the content panels.
- **Bots** — `DEFAULT_BOT_SIGNATURES` in [app/bots.py](app/bots.py), each with
  a type (`search`/`ai`/`seo`/`social`/…) used by the audience sunburst.
  Extend without code via `BOT_UA_FILE` (`Name|substring|type` per line).
- **Trending floor** — `TREND_MIN_HITS` (default 50) keeps low-volume paths
  off the momentum scatter.

## Definitions

- **Error rate** = (4xx + 5xx) / all requests; the 4xx/5xx split is shown on
  the tile.
- **Cache hit ratio** = requests with cacheStatus in
  {hit, stale, revalidated, updating} / all requests.
- **Bot** = User-Agent matched the signature list; empty User-Agents count as
  bots. Only the top 500 user agents per hour are classified — tail UAs are
  counted as human, which slightly undercounts bots.
