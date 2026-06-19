"""Cloudflare GraphQL Analytics client (free-plan httpRequestsAdaptiveGroups).

Free-plan constraints honoured here:
  - dataset: httpRequestsAdaptiveGroups only (adaptively sampled)
  - sampling correction: estimated total = count * avg(sampleInterval);
    sum fields (bytes) are corrected the same way
  - requestSource: "eyeball" filters to real client traffic
  - no clientRefererHost (not available on free), no bot score

All datetimes in and out of this module are naive UTC.
"""
import re
from datetime import datetime, timedelta, timezone

import requests

from . import config


class CloudflareError(Exception):
    """Auth failure, GraphQL error, or malformed response."""


# Cache statuses counted as "served from edge cache" for the hit ratio.
CACHED_STATUSES = {"hit", "stale", "revalidated", "updating"}

_ZONE_ID_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _graphql(query, token):
    if not token:
        raise CloudflareError(
            "No Cloudflare API token configured (set CF_API_TOKEN, or a per-site "
            "CF_API_TOKEN_<SITE>, in your .env)"
        )
    try:
        resp = requests.post(
            config.CF_GRAPHQL_ENDPOINT,
            json={"query": query},
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )
    except requests.RequestException as exc:
        raise CloudflareError(f"Cloudflare API unreachable: {exc}") from exc
    try:
        payload = resp.json()
    except ValueError:
        raise CloudflareError(f"Non-JSON response from Cloudflare (HTTP {resp.status_code})")
    if payload.get("errors"):
        msgs = "; ".join(e.get("message", "unknown") for e in payload["errors"])
        raise CloudflareError(f"GraphQL error: {msgs}")
    if resp.status_code != 200:
        raise CloudflareError(f"Cloudflare API returned HTTP {resp.status_code}")
    return payload.get("data") or {}


def _zone(data):
    zones = (data.get("viewer") or {}).get("zones") or []
    if not zones:
        raise CloudflareError(
            "Zone not found — check the zone ID and that the API token has "
            "Analytics:Read on this zone"
        )
    return zones[0]


def _check_zone_id(zone_id):
    # zone_id is interpolated into the query text, so be strict about its shape
    if not _ZONE_ID_RE.match(zone_id or ""):
        raise CloudflareError(f"Invalid zone ID {zone_id!r} (expected 32 hex chars)")
    return zone_id


def _time_filter(start, end):
    return (
        f'{{datetime_geq: "{_iso(start)}", datetime_lt: "{_iso(end)}", '
        f'requestSource: "eyeball"}}'
    )


def _interval(group):
    return ((group.get("avg") or {}).get("sampleInterval")) or 1


def _est_requests(group):
    """Sampled row count -> estimated true request count."""
    return int(group.get("count") or 0)


def _est_bytes(group):
    raw = (group.get("sum") or {}).get("edgeResponseBytes") or 0
    return int(raw)


def _parse_hour(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


def empty_hour_totals():
    return {"requests": 0, "bytes": 0, "raw_count": 0, "sample_interval": 1,
            "status": [], "cache": [], "country": []}


def fetch_range_rollup(zone_id, start, end, token):
    """Cheap dimensions for every hour in [start, end) in ONE API call:
    totals, status, cache and country, each grouped by datetimeHour.

    Returns {hour_start: {requests, bytes, raw_count, sample_interval,
                          status: [...], cache: [...], country: [...]}}
    (hours with no sampled traffic are absent). The window should stay
    within RANGE_CHUNK_HOURS to respect the per-query group budget.
    """
    _check_zone_id(zone_id)
    hours = max(1, int((end - start).total_seconds() // 3600))
    flt = _time_filter(start, end)
    query = f"""
    {{
      viewer {{
        zones(filter: {{zoneTag: "{zone_id}"}}) {{
          totalByHour: httpRequestsAdaptiveGroups(limit: {hours + 2}, filter: {flt}, orderBy: [datetimeHour_ASC]) {{
            count
            avg {{ sampleInterval }}
            sum {{ edgeResponseBytes }}
            dimensions {{ datetimeHour }}
          }}
          statusByHour: httpRequestsAdaptiveGroups(limit: {hours * 60}, filter: {flt}, orderBy: [count_DESC]) {{
            count
            avg {{ sampleInterval }}
            dimensions {{ datetimeHour, edgeResponseStatus }}
          }}
          cacheByHour: httpRequestsAdaptiveGroups(limit: {hours * 15}, filter: {flt}, orderBy: [count_DESC]) {{
            count
            avg {{ sampleInterval }}
            sum {{ edgeResponseBytes }}
            dimensions {{ datetimeHour, cacheStatus }}
          }}
          countryByHour: httpRequestsAdaptiveGroups(limit: {hours * 260}, filter: {flt}, orderBy: [count_DESC]) {{
            count
            avg {{ sampleInterval }}
            dimensions {{ datetimeHour, clientCountryName }}
          }}
        }}
      }}
    }}
    """
    zone = _zone(_graphql(query, token))

    by_hour = {}

    def bucket(group):
        hour = _parse_hour(group["dimensions"]["datetimeHour"])
        return by_hour.setdefault(hour, empty_hour_totals())

    for g in zone.get("totalByHour") or []:
        b = bucket(g)
        b["requests"] = _est_requests(g)
        b["bytes"] = _est_bytes(g)
        b["raw_count"] = g.get("count") or 0
        b["sample_interval"] = _interval(g)
    for g in zone.get("statusByHour") or []:
        bucket(g)["status"].append(
            {"status": g["dimensions"]["edgeResponseStatus"], "requests": _est_requests(g)})
    for g in zone.get("cacheByHour") or []:
        bucket(g)["cache"].append(
            {"cache_status": g["dimensions"]["cacheStatus"],
             "requests": _est_requests(g), "bytes": _est_bytes(g)})
    for g in zone.get("countryByHour") or []:
        bucket(g)["country"].append(
            {"country": g["dimensions"]["clientCountryName"], "requests": _est_requests(g)})
    return by_hour


def fetch_heavy_hours(zone_id, hour_starts, token):
    """Per-hour top-N groups that genuinely need an hour-scoped query:
    top paths, top user agents, top error paths. All requested hours are
    packed into ONE API call as aliased selections; callers should pass at
    most HEAVY_BATCH_HOURS hours per call.

    Returns {hour_start: {paths: [...], user_agents: [...], error_paths: [...]}}.
    """
    _check_zone_id(zone_id)
    blocks = []
    for i, hour in enumerate(hour_starts):
        flt = _time_filter(hour, hour + timedelta(hours=1))
        err_flt = (
            f'{{datetime_geq: "{_iso(hour)}", datetime_lt: "{_iso(hour + timedelta(hours=1))}", '
            f'requestSource: "eyeball", edgeResponseStatus_geq: 400}}'
        )
        blocks.append(f"""
          h{i}_paths: httpRequestsAdaptiveGroups(limit: {config.LIMIT_PATHS}, filter: {flt}, orderBy: [count_DESC]) {{
            count
            avg {{ sampleInterval }}
            sum {{ edgeResponseBytes }}
            dimensions {{ clientRequestPath }}
          }}
          h{i}_uas: httpRequestsAdaptiveGroups(limit: {config.LIMIT_USER_AGENTS}, filter: {flt}, orderBy: [count_DESC]) {{
            count
            avg {{ sampleInterval }}
            dimensions {{ userAgent }}
          }}
          h{i}_errs: httpRequestsAdaptiveGroups(limit: {config.LIMIT_ERROR_PATHS}, filter: {err_flt}, orderBy: [count_DESC]) {{
            count
            avg {{ sampleInterval }}
            dimensions {{ clientRequestPath, edgeResponseStatus }}
          }}""")

    query = f"""
    {{
      viewer {{
        zones(filter: {{zoneTag: "{zone_id}"}}) {{
          {"".join(blocks)}
        }}
      }}
    }}
    """
    zone = _zone(_graphql(query, token))

    result = {}
    for i, hour in enumerate(hour_starts):
        result[hour] = {
            "paths": [
                {"path": g["dimensions"]["clientRequestPath"],
                 "requests": _est_requests(g), "bytes": _est_bytes(g)}
                for g in zone.get(f"h{i}_paths") or []
            ],
            "user_agents": [
                {"user_agent": g["dimensions"]["userAgent"], "requests": _est_requests(g)}
                for g in zone.get(f"h{i}_uas") or []
            ],
            "error_paths": [
                {"path": g["dimensions"]["clientRequestPath"],
                 "status": g["dimensions"]["edgeResponseStatus"],
                 "requests": _est_requests(g)}
                for g in zone.get(f"h{i}_errs") or []
            ],
        }
    return result


def fetch_timeseries(zone_id, start, end, token, granularity="hour"):
    """Live time series: [{ts: ISO-8601 Z, requests, bytes}], ascending."""
    _check_zone_id(zone_id)
    dim = "datetimeHour" if granularity == "hour" else "datetimeMinute"
    flt = _time_filter(start, end)
    query = f"""
    {{
      viewer {{
        zones(filter: {{zoneTag: "{zone_id}"}}) {{
          series: httpRequestsAdaptiveGroups(limit: 2000, filter: {flt}, orderBy: [{dim}_ASC]) {{
            count
            avg {{ sampleInterval }}
            sum {{ edgeResponseBytes }}
            dimensions {{ {dim} }}
          }}
        }}
      }}
    }}
    """
    zone = _zone(_graphql(query, token))
    return [
        {"ts": g["dimensions"][dim], "requests": _est_requests(g), "bytes": _est_bytes(g)}
        for g in zone.get("series") or []
    ]


def fetch_kpis(zone_id, start, end, token):
    """Live KPI aggregates over [start, end): requests, bytes, errors, cache."""
    _check_zone_id(zone_id)
    flt = _time_filter(start, end)
    query = f"""
    {{
      viewer {{
        zones(filter: {{zoneTag: "{zone_id}"}}) {{
          total: httpRequestsAdaptiveGroups(limit: 1, filter: {flt}) {{
            count
            avg {{ sampleInterval }}
            sum {{ edgeResponseBytes }}
          }}
          byStatus: httpRequestsAdaptiveGroups(limit: {config.LIMIT_STATUS}, filter: {flt}) {{
            count
            avg {{ sampleInterval }}
            dimensions {{ edgeResponseStatus }}
          }}
          byCache: httpRequestsAdaptiveGroups(limit: {config.LIMIT_CACHE}, filter: {flt}) {{
            count
            avg {{ sampleInterval }}
            dimensions {{ cacheStatus }}
          }}
        }}
      }}
    }}
    """
    zone = _zone(_graphql(query, token))
    totals = zone.get("total") or [{}]
    total_group = totals[0] if totals else {}

    errors_4xx = errors_5xx = 0
    for g in zone.get("byStatus") or []:
        status = g["dimensions"]["edgeResponseStatus"]
        if 400 <= status < 500:
            errors_4xx += _est_requests(g)
        elif status >= 500:
            errors_5xx += _est_requests(g)

    cached = sum(
        _est_requests(g)
        for g in zone.get("byCache") or []
        if (g["dimensions"]["cacheStatus"] or "").lower() in CACHED_STATUSES
    )

    return {
        "requests": _est_requests(total_group),
        "bytes": _est_bytes(total_group),
        "errors_4xx": errors_4xx,
        "errors_5xx": errors_5xx,
        "cached_requests": cached,
    }
