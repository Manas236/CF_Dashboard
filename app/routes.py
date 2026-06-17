"""Flask routes: the dashboard shell plus JSON endpoints for the panels.

Data source policy (free-plan retention is short, so MySQL is the system of
record for history):
  - 1h  -> always live from Cloudflare, minute granularity
  - 24h -> MySQL rollups; falls back to live Cloudflare (hourly) if the
           collector hasn't populated yet or MySQL is unreachable
  - 7d / 30d -> MySQL only; an empty result returns a notice instead of
           querying Cloudflare (free retention can't cover those ranges)
"""
from datetime import timedelta

from flask import Blueprint, abort, current_app, jsonify, render_template, request

from . import cloudflare, config, panels, queries
from .auth import login_required

bp = Blueprint("main", __name__)

RANGE_HOURS = {"24h": 24, "7d": 168, "30d": 720}
RANGE_ORDER = ["1h", "24h", "7d", "30d"]


def _site():
    site = request.args.get("site", "")
    return site if site in config.SITES else config.DEFAULT_SITE


def _range():
    rk = request.args.get("range", "")
    return rk if rk in RANGE_ORDER else "24h"


def _iso_z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _hour_window(range_key):
    """(start, end, n_hours): n whole hours ending with the current partial hour."""
    n = RANGE_HOURS[range_key]
    end = cloudflare.utcnow().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return end - timedelta(hours=n), end, n


def _stored_series(site, range_key):
    """Full hour grid from MySQL with nulls for uncollected hours, or None."""
    start, end, n = _hour_window(range_key)
    try:
        rows = queries.hourly_series(site, start, end)
    except Exception as exc:
        current_app.logger.warning("MySQL read failed: %s", exc)
        return None, "db_unavailable"
    if not rows:
        return None, "no_history"
    by_hour = {r["hour_start"]: r for r in rows}
    series = []
    for i in range(n):
        h = start + timedelta(hours=i)
        row = by_hour.get(h)
        series.append({
            "ts": _iso_z(h),
            "requests": int(row["requests_est"]) if row else None,
            "bytes": int(row["bytes_est"]) if row else None,
        })
    return series, None


def _page(template):
    return render_template(
        template,
        sites=config.SITES,
        site=_site(),
        range_key=_range(),
        ranges=RANGE_ORDER,
    )


@bp.route("/")
@login_required
def dashboard():
    return _page("dashboard.html")


@bp.route("/articles")
@login_required
def articles():
    return _page("articles.html")


@bp.route("/categories")
@login_required
def categories():
    return _page("categories.html")


@bp.route("/errors")
@login_required
def errors():
    return _page("errors.html")


@bp.route("/audience")
@login_required
def audience():
    return _page("audience.html")


@bp.route("/geo")
@login_required
def geo():
    return _page("geo.html")


@bp.route("/api/panel/<name>")
@login_required
def api_panel(name):
    fn = panels.REGISTRY.get(name)
    if fn is None:
        abort(404)
    try:
        return jsonify(fn(_site(), _range()))
    except Exception as exc:
        if current_app.debug:
            raise
        current_app.logger.warning("panel %s failed: %s", name, exc)
        return jsonify({"source": "none", "notice": "db_unavailable"})


@bp.route("/api/timeseries")
@login_required
def api_timeseries():
    site, range_key = _site(), _range()
    zone_id = config.SITES[site]["zone_id"]
    token = config.SITES[site]["api_token"]
    now = cloudflare.utcnow()

    try:
        if range_key == "1h":
            series = cloudflare.fetch_timeseries(
                zone_id, now - timedelta(hours=1), now, token, granularity="minute"
            )
            return jsonify({"site": site, "range": range_key,
                            "source": "cloudflare-live", "series": series})

        series, notice = _stored_series(site, range_key)
        if series is not None:
            return jsonify({"site": site, "range": range_key,
                            "source": "mysql", "series": series})

        if range_key == "24h":
            series = cloudflare.fetch_timeseries(
                zone_id, now - timedelta(hours=24), now, token, granularity="hour"
            )
            return jsonify({"site": site, "range": range_key,
                            "source": "cloudflare-live", "series": series,
                            "notice": notice})

        # 7d/30d with no stored data: Cloudflare free retention can't fill it
        return jsonify({"site": site, "range": range_key, "source": "none",
                        "series": [], "notice": notice})
    except cloudflare.CloudflareError as exc:
        return jsonify({"error": str(exc)}), 502


@bp.route("/api/kpis")
@login_required
def api_kpis():
    site, range_key = _site(), _range()
    zone_id = config.SITES[site]["zone_id"]
    token = config.SITES[site]["api_token"]
    now = cloudflare.utcnow()

    try:
        if range_key == "1h":
            data = cloudflare.fetch_kpis(zone_id, now - timedelta(hours=1), now, token)
            return jsonify(_kpi_payload(site, range_key, "cloudflare-live", data))

        start, end, n = _hour_window(range_key)
        notice = None
        try:
            stored = queries.range_kpis(site, start, end)
        except Exception as exc:
            current_app.logger.warning("MySQL read failed: %s", exc)
            stored, notice = None, "db_unavailable"

        if stored:
            payload = _kpi_payload(site, range_key, "mysql", stored)
            payload["hours_covered"] = stored["hours_covered"]
            payload["hours_expected"] = n
            if stored["last_collected"]:
                payload["last_collected"] = _iso_z(stored["last_collected"])
            return jsonify(payload)

        if range_key == "24h":
            data = cloudflare.fetch_kpis(zone_id, now - timedelta(hours=24), now, token)
            payload = _kpi_payload(site, range_key, "cloudflare-live", data)
            payload["notice"] = notice or "no_history"
            return jsonify(payload)

        return jsonify({"site": site, "range": range_key, "source": "none",
                        "notice": notice or "no_history"})
    except cloudflare.CloudflareError as exc:
        return jsonify({"error": str(exc)}), 502


def _kpi_payload(site, range_key, source, data):
    requests_total = data["requests"]
    errors = data["errors_4xx"] + data["errors_5xx"]
    return {
        "site": site,
        "range": range_key,
        "source": source,
        "requests": requests_total,
        "bytes": data["bytes"],
        "errors_4xx": data["errors_4xx"],
        "errors_5xx": data["errors_5xx"],
        "error_rate": (errors / requests_total) if requests_total else None,
        "cache_hit_ratio": (data["cached_requests"] / requests_total) if requests_total else None,
    }
