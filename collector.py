"""Cron-runnable collector: hourly Cloudflare rollups -> MySQL.

Two passes per zone, both batched to keep API calls low:
  1. Cheap dimensions (totals, status, cache, country) for the whole window,
     grouped by datetimeHour — one GraphQL call per RANGE_CHUNK_HOURS chunk.
  2. Heavy per-hour top-Ns (paths, user agents, error paths >= 400) — one
     GraphQL call per HEAVY_BATCH_HOURS hours, aliased per hour.
A 72-hour backfill is ~18 calls per zone instead of 72.

Everything is UPSERTed; re-running an hour overwrites it. The current partial
hour is collected too and gets finalized by later runs.

Usage:
    python collector.py                 # last COLLECT_HOURS hours (default 6)
    python collector.py --hours 72     # backfill (limited by CF free retention)
    python collector.py --site newsband.in
"""
import argparse
import sys
import time
from datetime import datetime, timedelta, timezone

import pymysql

from app import bots, cloudflare, config, db

TOTALS_SQL = """
INSERT INTO hourly_zone_totals
  (site, hour_start, requests_est, bytes_est, visits_est, cached_requests_est,
   errors_4xx_est, errors_5xx_est, raw_sample_count, avg_sample_interval)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) AS new
ON DUPLICATE KEY UPDATE
  requests_est = new.requests_est,
  bytes_est = new.bytes_est,
  visits_est = new.visits_est,
  cached_requests_est = new.cached_requests_est,
  errors_4xx_est = new.errors_4xx_est,
  errors_5xx_est = new.errors_5xx_est,
  raw_sample_count = new.raw_sample_count,
  avg_sample_interval = new.avg_sample_interval
"""

# bot/human arrive in pass 2; human is derived from the stored hour total so
# the two passes never disagree.
BOT_TOTALS_SQL = """
UPDATE hourly_zone_totals
SET bot_requests_est = LEAST(%s, requests_est),
    human_requests_est = requests_est - LEAST(%s, requests_est)
WHERE site = %s AND hour_start = %s
"""

PATH_SQL = """
INSERT INTO hourly_path_stats (site, hour_start, path, requests_est, bytes_est)
VALUES (%s, %s, %s, %s, %s) AS new
ON DUPLICATE KEY UPDATE
  requests_est = new.requests_est, bytes_est = new.bytes_est
"""

ERROR_PATH_SQL = """
INSERT INTO hourly_error_path_stats (site, hour_start, path, status, requests_est)
VALUES (%s, %s, %s, %s, %s) AS new
ON DUPLICATE KEY UPDATE requests_est = new.requests_est
"""

STATUS_SQL = """
INSERT INTO hourly_status_stats (site, hour_start, status, requests_est)
VALUES (%s, %s, %s, %s) AS new
ON DUPLICATE KEY UPDATE requests_est = new.requests_est
"""

CACHE_SQL = """
INSERT INTO hourly_cache_stats (site, hour_start, cache_status, requests_est, bytes_est)
VALUES (%s, %s, %s, %s, %s) AS new
ON DUPLICATE KEY UPDATE
  requests_est = new.requests_est, bytes_est = new.bytes_est
"""

COUNTRY_SQL = """
INSERT INTO hourly_country_stats (site, hour_start, country, requests_est)
VALUES (%s, %s, %s, %s) AS new
ON DUPLICATE KEY UPDATE requests_est = new.requests_est
"""

BOT_SQL = """
INSERT INTO hourly_bot_stats (site, hour_start, bot_name, requests_est)
VALUES (%s, %s, %s, %s) AS new
ON DUPLICATE KEY UPDATE requests_est = new.requests_est
"""

CHEAP_DIM_TABLES = ("hourly_status_stats", "hourly_cache_stats", "hourly_country_stats")
HEAVY_DIM_TABLES = ("hourly_path_stats", "hourly_error_path_stats", "hourly_bot_stats")


def floor_hour(dt):
    return dt.replace(minute=0, second=0, microsecond=0)


def chunked(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _delete_hour(cur, tables, site, hour_start):
    # Rows that fell out of the top-N on a re-run must not linger.
    for table in tables:
        cur.execute(f"DELETE FROM {table} WHERE site = %s AND hour_start = %s",
                    (site, hour_start))


def _dedupe_paths(path_rows):
    """Truncate paths to the column width and merge any resulting collisions."""
    merged = {}
    for row in path_rows:
        key = (row["path"] or "")[:512]
        if key in merged:
            merged[key]["requests"] += row["requests"]
            merged[key]["bytes"] += row["bytes"]
        else:
            merged[key] = {"requests": row["requests"], "bytes": row["bytes"]}
    return merged


def store_cheap_hour(conn, site, hour_start, totals):
    """Pass 1: zone totals + status/cache/country rollups for one hour."""
    cached = sum(
        c["requests"] for c in totals["cache"]
        if (c["cache_status"] or "").lower() in cloudflare.CACHED_STATUSES
    )
    errors_4xx = sum(s["requests"] for s in totals["status"] if 400 <= s["status"] < 500)
    errors_5xx = sum(s["requests"] for s in totals["status"] if s["status"] >= 500)

    with conn.cursor() as cur:
        cur.execute(TOTALS_SQL, (
            site, hour_start, totals["requests"], totals["bytes"], totals["visits"], cached,
            errors_4xx, errors_5xx, totals["raw_count"], totals["sample_interval"],
        ))
        _delete_hour(cur, CHEAP_DIM_TABLES, site, hour_start)
        if totals["status"]:
            cur.executemany(STATUS_SQL, [
                (site, hour_start, s["status"], s["requests"]) for s in totals["status"]
            ])
        if totals["cache"]:
            cur.executemany(CACHE_SQL, [
                (site, hour_start, (c["cache_status"] or "unknown")[:32],
                 c["requests"], c["bytes"])
                for c in totals["cache"]
            ])
        if totals["country"]:
            cur.executemany(COUNTRY_SQL, [
                (site, hour_start, (c["country"] or "unknown")[:64], c["requests"])
                for c in totals["country"]
            ])
    conn.commit()


def store_heavy_hour(conn, site, hour_start, heavy):
    """Pass 2: top paths, error paths, and UA-derived bot stats for one hour."""
    bot_total, breakdown = bots.tally(heavy["user_agents"])

    with conn.cursor() as cur:
        _delete_hour(cur, HEAVY_DIM_TABLES, site, hour_start)
        paths = _dedupe_paths(heavy["paths"])
        if paths:
            cur.executemany(PATH_SQL, [
                (site, hour_start, path, v["requests"], v["bytes"])
                for path, v in paths.items()
            ])
        if heavy["error_paths"]:
            merged = {}
            for row in heavy["error_paths"]:
                key = ((row["path"] or "")[:512], row["status"])
                merged[key] = merged.get(key, 0) + row["requests"]
            cur.executemany(ERROR_PATH_SQL, [
                (site, hour_start, path, status, reqs)
                for (path, status), reqs in merged.items()
            ])
        if breakdown:
            cur.executemany(BOT_SQL, [
                (site, hour_start, name[:64], count)
                for name, count in breakdown.items()
            ])
        cur.execute(BOT_TOTALS_SQL, (bot_total, bot_total, site, hour_start))
    conn.commit()
    return bot_total


def collect(sites, hours):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    current_hour = floor_hour(now)
    # Oldest first so a partial run still leaves a contiguous history.
    hour_starts = [current_hour - timedelta(hours=i) for i in range(hours - 1, -1, -1)]

    conn = db.get_connection()
    failures = calls = 0
    try:
        for site in sites:
            zone_id = config.SITES[site]["zone_id"]
            token = config.SITES[site]["api_token"]
            if not zone_id or not token:
                missing = " and ".join(
                    label for label, value in
                    (("zone ID", zone_id), ("API token", token)) if not value)
                print(f"[{site}] SKIP: no {missing} configured in .env", file=sys.stderr)
                failures += 1
                continue

            # Pass 1: cheap dimensions, one call per chunk
            for chunk in chunked(hour_starts, config.RANGE_CHUNK_HOURS):
                try:
                    by_hour = cloudflare.fetch_range_rollup(
                        zone_id, chunk[0], chunk[-1] + timedelta(hours=1), token)
                    calls += 1
                    total_req = 0
                    for hour_start in chunk:
                        totals = by_hour.get(hour_start) or cloudflare.empty_hour_totals()
                        store_cheap_hour(conn, site, hour_start, totals)
                        total_req += totals["requests"]
                    print(f"[{site}] totals {chunk[0]:%m-%d %H:00}-{chunk[-1]:%m-%d %H:00}Z  "
                          f"~{total_req:,} req across {len(chunk)} h")
                except cloudflare.CloudflareError as exc:
                    failures += 1
                    print(f"[{site}] totals {chunk[0]:%m-%d %H:00}Z+  ERROR: {exc}",
                          file=sys.stderr)
                time.sleep(0.25)

            # Pass 2: heavy per-hour top-Ns, several hours aliased per call
            for batch in chunked(hour_starts, config.HEAVY_BATCH_HOURS):
                try:
                    by_hour = cloudflare.fetch_heavy_hours(zone_id, batch, token)
                    calls += 1
                    bot_sum = 0
                    for hour_start in batch:
                        heavy = by_hour.get(hour_start) or {
                            "paths": [], "user_agents": [], "error_paths": []}
                        bot_sum += store_heavy_hour(conn, site, hour_start, heavy)
                    print(f"[{site}] paths/UAs {batch[0]:%m-%d %H:00}-{batch[-1]:%m-%d %H:00}Z  "
                          f"~{bot_sum:,} bot req across {len(batch)} h")
                except cloudflare.CloudflareError as exc:
                    failures += 1
                    print(f"[{site}] paths/UAs {batch[0]:%m-%d %H:00}Z+  ERROR: {exc}",
                          file=sys.stderr)
                time.sleep(0.25)
    finally:
        conn.close()
    print(f"{calls} API call(s) made.")
    return failures


def main():
    parser = argparse.ArgumentParser(description="Collect Cloudflare hourly rollups into MySQL")
    parser.add_argument("--hours", type=int, default=config.COLLECT_HOURS,
                        help=f"how many recent hours to (re-)collect "
                             f"(default {config.COLLECT_HOURS}; use e.g. 72 to backfill)")
    parser.add_argument("--site", choices=list(config.SITES),
                        help="collect only this site (default: all)")
    args = parser.parse_args()

    try:
        db.ensure_schema()
    except pymysql.MySQLError as exc:
        sys.exit(f"MySQL setup failed: {exc}\n"
                 f"Check MYSQL_* in .env and that the database "
                 f"'{config.MYSQL['database']}' exists (see README step 3).")
    sites = [args.site] if args.site else list(config.SITES)
    failures = collect(sites, max(1, args.hours))
    if failures:
        print(f"Done with {failures} failure(s).", file=sys.stderr)
        sys.exit(1)
    print("Done.")


if __name__ == "__main__":
    main()
