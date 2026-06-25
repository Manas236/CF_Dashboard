"""Read-side MySQL queries for the dashboard."""
from . import db


def hourly_series(site, start, end):
    """Stored hourly totals in [start, end), ascending. Naive-UTC datetimes."""
    return db.fetch_all(
        """
        SELECT hour_start, requests_est, bytes_est, visits_est
        FROM hourly_zone_totals
        WHERE site = %s AND hour_start >= %s AND hour_start < %s
        ORDER BY hour_start
        """,
        (site, start, end),
    )


def range_kpis(site, start, end):
    """Aggregated KPIs over [start, end), or None if nothing is stored."""
    row = db.fetch_one(
        """
        SELECT
          COUNT(*)                      AS hours_covered,
          SUM(requests_est)             AS requests,
          SUM(bytes_est)                AS bytes,
          SUM(visits_est)               AS visits,
          SUM(errors_4xx_est)           AS errors_4xx,
          SUM(errors_5xx_est)           AS errors_5xx,
          SUM(cached_requests_est)      AS cached_requests,
          MAX(collected_at)             AS last_collected
        FROM hourly_zone_totals
        WHERE site = %s AND hour_start >= %s AND hour_start < %s
        """,
        (site, start, end),
    )
    if not row or not row["hours_covered"]:
        return None
    return {
        "hours_covered": int(row["hours_covered"]),
        "requests": int(row["requests"] or 0),
        "bytes": int(row["bytes"] or 0),
        "visits": int(row["visits"] or 0),
        "errors_4xx": int(row["errors_4xx"] or 0),
        "errors_5xx": int(row["errors_5xx"] or 0),
        "cached_requests": int(row["cached_requests"] or 0),
        "last_collected": row["last_collected"],
    }
