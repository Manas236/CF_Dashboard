"""Read-side data assembly for the Phase 2 panels.

Every function takes (site, range_key), reads ONLY the MySQL rollup tables,
and returns a JSON-able dict with the same source/notice contract as the
Phase 1 endpoints:
    {"source": "mysql", ...}                      -> data
    {"source": "none", "notice": "no_history"}    -> nothing stored for range

All *_est numbers are sampling-corrected estimates (see collector).
"""
from datetime import datetime, timedelta, timezone

from . import bots, categories, config, db

RANGE_HOURS = {"1h": 1, "24h": 24, "7d": 168, "30d": 720}


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso_z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def window(range_key):
    """(start, end, n_hours): n whole hour buckets ending with the current
    partial hour — matches what the collector stores."""
    n = RANGE_HOURS[range_key]
    end = _utcnow().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return end - timedelta(hours=n), end, n


def hours_covered(site, start, end):
    row = db.fetch_one(
        "SELECT COUNT(*) n FROM hourly_zone_totals "
        "WHERE site = %s AND hour_start >= %s AND hour_start < %s",
        (site, start, end),
    )
    return int(row["n"]) if row else 0


def _no_history():
    return {"source": "none", "notice": "no_history"}


def _growth_pct(cur, prior):
    return (cur - prior) / max(prior, 1) * 100.0


def _trend_class(growth, is_new):
    if is_new:
        return "new"
    if growth >= 25:
        return "rising"
    if growth <= -25:
        return "fading"
    return "steady"


# The scatter caps growth display at +500%; the momentum score caps the same
# way so one freak ratio can't dominate the trending leaderboard.
TREND_DISPLAY_CAP = 500.0


def visits_factor(site, start, end):
    """Zone-wide visits-per-request ratio over the window.

    Per-path "visits" (Cloudflare reading sessions — arrivals from an external
    referer) aren't stored; only request counts are. So a path's estimated
    visits is its requests scaled by this zone-wide ratio. Returns a float in
    (0, 1], or None when it can't be computed (no requests, or no stored
    visits), in which case the UI falls back to showing raw hits.
    """
    row = db.fetch_one(
        "SELECT SUM(requests_est) r, SUM(visits_est) v FROM hourly_zone_totals "
        "WHERE site = %s AND hour_start >= %s AND hour_start < %s",
        (site, start, end),
    )
    if not row:
        return None
    req, vis = int(row["r"] or 0), int(row["v"] or 0)
    if req <= 0 or vis <= 0:
        return None
    return min(vis / req, 1.0)


def _momentum(item):
    """Trending score: the absolute gain in hits amplified by the growth rate,
    so a big surging story outranks both a flat giant and a tiny page with a
    freak percentage. A uniform views factor scales every score equally, so
    ranking on hits is the same as ranking on estimated visits."""
    change = max(item["change"], 0)
    if item["cls"] == "new":
        rate = TREND_DISPLAY_CAP / 100.0          # brand-new = treated as a full surge
    elif item["growth"] is None:
        return float(change)                      # no prior coverage -> rank on volume
    else:
        rate = min(max(item["growth"], 0.0), TREND_DISPLAY_CAP) / 100.0
    return change * (1.0 + rate)


# --------------------------------------------------------------------------
# Panel A — Trending & Top Articles
# --------------------------------------------------------------------------

def articles_panel(site, range_key):
    start, end, n = window(range_key)
    prior_start = start - timedelta(hours=n)

    cur_cov = hours_covered(site, start, end)
    if cur_cov == 0:
        return _no_history()
    prior_cov = hours_covered(site, prior_start, start)

    rows = db.fetch_all(
        """
        SELECT path,
          SUM(CASE WHEN hour_start >= %s THEN requests_est ELSE 0 END) AS cur,
          SUM(CASE WHEN hour_start <  %s THEN requests_est ELSE 0 END) AS prior
        FROM hourly_path_stats
        WHERE site = %s AND hour_start >= %s AND hour_start < %s
        GROUP BY path
        """,
        (start, start, site, prior_start, end),
    )

    items = []
    for r in rows:
        if not categories.is_article_path(r["path"]):
            continue
        cur, prior = int(r["cur"]), int(r["prior"])
        if cur == 0:
            continue
        is_new = prior == 0 and prior_cov > 0
        growth = None if is_new or prior_cov == 0 else _growth_pct(cur, prior)
        items.append({
            "path": r["path"],
            "cur": cur,
            "prior": prior,
            "growth": round(growth, 1) if growth is not None else None,
            "change": cur - prior,
            "cls": _trend_class(growth if growth is not None else 0, is_new),
        })
    for it in items:
        it["momentum"] = round(_momentum(it), 1)

    factor = visits_factor(site, start, end)

    items.sort(key=lambda x: x["cur"], reverse=True)
    scatter = [i for i in items if i["cur"] >= config.TREND_MIN_HITS][:150]

    # Leaderboard = most-trending (momentum), not most-read. A volume floor keeps
    # a freak-growth micro-article from crowding out the real stories.
    leaderboard = sorted(
        (i for i in items if i["cur"] >= config.TREND_MIN_HITS),
        key=lambda x: x["momentum"], reverse=True,
    )[:15]

    # Sparklines: fixed last-24h hourly trajectory for the leaderboard paths.
    spark_start = _utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(hours=23)
    sparks = {i["path"]: [0] * 24 for i in leaderboard}
    if leaderboard:
        placeholders = ", ".join(["%s"] * len(leaderboard))
        spark_rows = db.fetch_all(
            f"""
            SELECT path, hour_start, requests_est
            FROM hourly_path_stats
            WHERE site = %s AND hour_start >= %s AND path IN ({placeholders})
            """,
            [site, spark_start] + [i["path"] for i in leaderboard],
        )
        for r in spark_rows:
            idx = int((r["hour_start"] - spark_start).total_seconds() // 3600)
            if 0 <= idx < 24:
                sparks[r["path"]][idx] = int(r["requests_est"])
    for i in leaderboard:
        i["spark"] = sparks[i["path"]]

    return {
        "source": "mysql",
        "min_hits": config.TREND_MIN_HITS,
        "current_hours": cur_cov,
        "prior_hours": prior_cov,
        "window_start": _iso_z(start),
        "prior_start": _iso_z(prior_start),
        "views_factor": factor,
        "scatter": scatter,
        "leaderboard": leaderboard,
    }


# --------------------------------------------------------------------------
# Panel B — Category Analytics
# --------------------------------------------------------------------------

# Radar axes are limited to what the rollups can actually answer per category.
# (bot % and cache hit % would need path x userAgent / path x cacheStatus
# rollups, which the free-plan collector deliberately doesn't store.)
RADAR_AXES = ["View share", "Growth", "Active articles", "Error rate", "Bandwidth share"]


def categories_panel(site, range_key):
    start, end, n = window(range_key)
    prior_start = start - timedelta(hours=n)

    cur_cov = hours_covered(site, start, end)
    if cur_cov == 0:
        return _no_history()
    prior_cov = hours_covered(site, prior_start, start)

    rows = db.fetch_all(
        """
        SELECT path,
          SUM(CASE WHEN hour_start >= %s THEN requests_est ELSE 0 END) AS cur,
          SUM(CASE WHEN hour_start <  %s THEN requests_est ELSE 0 END) AS prior,
          SUM(CASE WHEN hour_start >= %s THEN bytes_est ELSE 0 END) AS bytes
        FROM hourly_path_stats
        WHERE site = %s AND hour_start >= %s AND hour_start < %s
        GROUP BY path
        """,
        (start, start, start, site, prior_start, end),
    )

    cats = {}
    for r in rows:
        if not categories.is_article_path(r["path"]):
            continue
        cur = int(r["cur"])
        if cur == 0 and int(r["prior"]) == 0:
            continue
        cat = cats.setdefault(categories.categorize(r["path"]), {
            "cur": 0, "prior": 0, "bytes": 0, "paths": 0, "errors": 0, "top": []})
        cat["cur"] += cur
        cat["prior"] += int(r["prior"])
        cat["bytes"] += int(r["bytes"])
        if cur > 0:
            cat["paths"] += 1
            cat["top"].append({"path": r["path"], "value": cur})

    cats = {k: v for k, v in cats.items() if v["cur"] > 0}
    if not cats:
        return {"source": "mysql", "notice": "no_articles",
                "treemap": [], "radar": None, "total": 0}

    # Errors per category (current window) from the error-path rollup.
    err_rows = db.fetch_all(
        """
        SELECT path, SUM(requests_est) AS errs
        FROM hourly_error_path_stats
        WHERE site = %s AND hour_start >= %s AND hour_start < %s
        GROUP BY path
        """,
        (site, start, end),
    )
    for r in err_rows:
        cat = cats.get(categories.categorize(r["path"]))
        if cat is not None and categories.is_article_path(r["path"]):
            cat["errors"] += int(r["errs"])

    total = sum(c["cur"] for c in cats.values())
    total_bytes = sum(c["bytes"] for c in cats.values()) or 1
    ordered = sorted(cats.items(), key=lambda kv: kv[1]["cur"], reverse=True)

    treemap = []
    for name, c in ordered[:12]:
        children = sorted(c["top"], key=lambda x: x["value"], reverse=True)[:10]
        treemap.append({
            "name": name,
            "value": c["cur"],
            "children": [
                {"name": categories.article_title(p["path"]),
                 "value": p["value"], "path": p["path"]}
                for p in children
            ],
        })
    if len(ordered) > 12:
        rest = sum(c["cur"] for _, c in ordered[12:])
        treemap.append({"name": "Other", "value": rest, "children": []})

    # Radar: top 5 categories, each axis normalized 0-100 across them.
    top5 = ordered[:5]
    raw = []
    for name, c in top5:
        growth = 0.0 if prior_cov == 0 else max(-100.0, min(_growth_pct(c["cur"], c["prior"]), 500.0))
        raw.append({
            "name": name,
            "View share": round(c["cur"] / max(total, 1) * 100, 1),
            "Growth": round(growth, 1),
            "Active articles": c["paths"],
            "Error rate": round(min(c["errors"] / max(c["cur"], 1), 1.0) * 100, 2),
            "Bandwidth share": round(c["bytes"] / total_bytes * 100, 1),
        })

    def normalize(axis):
        values = [r[axis] for r in raw]
        lo, hi = min(values), max(values)
        if hi == lo:
            return [50.0] * len(values)
        return [round((v - lo) / (hi - lo) * 100, 1) for v in values]

    norms = {axis: normalize(axis) for axis in RADAR_AXES}
    radar = {
        "axes": RADAR_AXES,
        "series": [
            {"name": r["name"],
             "norm": [norms[axis][i] for axis in RADAR_AXES],
             "raw": {axis: r[axis] for axis in RADAR_AXES}}
            for i, r in enumerate(raw)
        ],
        "growth_available": prior_cov > 0,
    }

    return {
        "source": "mysql",
        "total": total,
        "current_hours": cur_cov,
        "prior_hours": prior_cov,
        "views_factor": visits_factor(site, start, end),
        "treemap": treemap,
        "radar": radar,
    }


# --------------------------------------------------------------------------
# Panel C — Error Monitoring
# --------------------------------------------------------------------------

def _buckets(start, n_hours):
    """Heatmap columns: hourly up to 7d, daily for 30d (720 columns would be
    unreadable and slow)."""
    bucket_hours = 24 if n_hours > 168 else 1
    count = (n_hours + bucket_hours - 1) // bucket_hours
    cols = [_iso_z(start + timedelta(hours=i * bucket_hours)) for i in range(count)]
    return bucket_hours, count, cols


def errors_panel(site, range_key):
    start, end, n = window(range_key)
    cur_cov = hours_covered(site, start, end)
    if cur_cov == 0:
        return _no_history()

    totals = db.fetch_one(
        """
        SELECT SUM(requests_est) requests, SUM(errors_4xx_est) e4, SUM(errors_5xx_est) e5
        FROM hourly_zone_totals
        WHERE site = %s AND hour_start >= %s AND hour_start < %s
        """,
        (site, start, end),
    )
    bucket_hours, n_cols, cols = _buckets(start, n)

    def bucket_idx(hour_start):
        return int((hour_start - start).total_seconds() // (3600 * bucket_hours))

    # Rows by path: top error-producing paths across the range.
    top_paths = db.fetch_all(
        """
        SELECT path, SUM(requests_est) total
        FROM hourly_error_path_stats
        WHERE site = %s AND hour_start >= %s AND hour_start < %s
        GROUP BY path ORDER BY total DESC LIMIT 12
        """,
        (site, start, end),
    )
    path_rows = []
    if top_paths:
        placeholders = ", ".join(["%s"] * len(top_paths))
        cells = db.fetch_all(
            f"""
            SELECT path, hour_start, SUM(requests_est) r
            FROM hourly_error_path_stats
            WHERE site = %s AND hour_start >= %s AND hour_start < %s
              AND path IN ({placeholders})
            GROUP BY path, hour_start
            """,
            [site, start, end] + [p["path"] for p in top_paths],
        )
        grid = {p["path"]: [0] * n_cols for p in top_paths}
        for c in cells:
            idx = bucket_idx(c["hour_start"])
            if 0 <= idx < n_cols:
                grid[c["path"]][idx] += int(c["r"])
        path_rows = [{"label": p["path"], "total": int(p["total"]),
                      "cells": grid[p["path"]]} for p in top_paths]

    # Rows by status code, from the zone-wide status rollup.
    status_cells = db.fetch_all(
        """
        SELECT status, hour_start, requests_est r
        FROM hourly_status_stats
        WHERE site = %s AND hour_start >= %s AND hour_start < %s AND status >= 400
        """,
        (site, start, end),
    )
    status_grid = {}
    status_totals = {}
    for c in status_cells:
        s = int(c["status"])
        status_grid.setdefault(s, [0] * n_cols)
        idx = bucket_idx(c["hour_start"])
        if 0 <= idx < n_cols:
            status_grid[s][idx] += int(c["r"])
        status_totals[s] = status_totals.get(s, 0) + int(c["r"])
    top_statuses = sorted(status_totals, key=status_totals.get, reverse=True)[:10]
    status_rows = [{"label": str(s), "total": status_totals[s],
                    "cells": status_grid[s]} for s in top_statuses]

    # Action table: top broken URLs by (path, status).
    table_rows = db.fetch_all(
        """
        SELECT path, status, SUM(requests_est) errors
        FROM hourly_error_path_stats
        WHERE site = %s AND hour_start >= %s AND hour_start < %s
        GROUP BY path, status ORDER BY errors DESC LIMIT 100
        """,
        (site, start, end),
    )
    table = [{"path": r["path"], "status": int(r["status"]),
              "errors": int(r["errors"])} for r in table_rows]

    # Error share of each path's own traffic, where the path made the top-N
    # path rollup (long-tail paths have no stored hit total -> share unknown).
    if table:
        paths = list({r["path"] for r in table})
        placeholders = ", ".join(["%s"] * len(paths))
        hit_rows = db.fetch_all(
            f"""
            SELECT path, SUM(requests_est) hits
            FROM hourly_path_stats
            WHERE site = %s AND hour_start >= %s AND hour_start < %s
              AND path IN ({placeholders})
            GROUP BY path
            """,
            [site, start, end] + paths,
        )
        hits = {r["path"]: int(r["hits"]) for r in hit_rows}
        for r in table:
            h = hits.get(r["path"])
            r["share"] = round(min(r["errors"] / h, 1.0), 4) if h else None

    return {
        "source": "mysql",
        "current_hours": cur_cov,
        "totals": {
            "requests": int(totals["requests"] or 0),
            "e4": int(totals["e4"] or 0),
            "e5": int(totals["e5"] or 0),
        },
        "bucket_hours": bucket_hours,
        "cols": cols,
        "path_rows": path_rows,
        "status_rows": status_rows,
        "table": table,
    }


# --------------------------------------------------------------------------
# Panel D — Audience Composition (Human / Bot / AI)
# --------------------------------------------------------------------------

SUBTYPE_LABELS = {"search": "Search engines", "ai": "AI crawlers"}
SUBTYPE_OTHER = "Other bots"


def _subtype(bot_name):
    return SUBTYPE_LABELS.get(bots.bot_type(bot_name), SUBTYPE_OTHER)


def _report_sunburst(by_name, human, search, ai, other_bots):
    """Humans-vs-bots sunburst for the board report, sized to match the report's
    audience split (which counts bots from Cloudflare's own classification, not
    just named UAs). Inner ring = human vs bots; middle ring = bot families;
    outer ring drills Search/AI into the named crawlers behind them. "Other bots"
    stays a leaf — it's mostly CF-flagged traffic with no UA name to break down."""
    grouped = {}
    for b in by_name:
        grouped.setdefault(_subtype(b["bot_name"]), []).append(
            {"name": b["bot_name"], "value": int(b["r"] or 0)})

    def children(label):
        lst = sorted(grouped.get(label, []), key=lambda b: b["value"], reverse=True)
        top, rest = lst[:6], lst[6:]
        out = list(top)
        if rest:
            out.append({"name": "(others)", "value": sum(b["value"] for b in rest)})
        return out

    tree = [{"name": "Human (est.)", "value": human, "itemStyle": {"color": "#4f8ff7"}}]
    bot_children = []
    for label, color, span, drill in (
        ("Search engines", "#3fb96f", search, True),
        ("AI crawlers", "#f6821f", ai, True),
        (SUBTYPE_OTHER, "#8a93a6", other_bots, False),
    ):
        if span <= 0:
            continue
        node = {"name": label, "itemStyle": {"color": color}}
        kids = children(label) if drill else []
        if kids and sum(k["value"] for k in kids) > 0:
            node["children"] = kids   # ECharts sizes the ring by its children's sum
        else:
            node["value"] = span
        bot_children.append(node)
    if bot_children:
        tree.append({"name": "Bots", "itemStyle": {"color": "#e5a94b"}, "children": bot_children})
    return tree


def audience_panel(site, range_key):
    start, end, n = window(range_key)
    cur_cov = hours_covered(site, start, end)
    if cur_cov == 0:
        return _no_history()

    totals = db.fetch_one(
        """
        SELECT SUM(requests_est) requests, SUM(bot_requests_est) bot
        FROM hourly_zone_totals
        WHERE site = %s AND hour_start >= %s AND hour_start < %s
        """,
        (site, start, end),
    )
    requests_total = int(totals["requests"] or 0)

    by_name = db.fetch_all(
        """
        SELECT bot_name, SUM(requests_est) r
        FROM hourly_bot_stats
        WHERE site = %s AND hour_start >= %s AND hour_start < %s
        GROUP BY bot_name ORDER BY r DESC
        """,
        (site, start, end),
    )

    subtypes = {}
    for row in by_name:
        subtypes.setdefault(_subtype(row["bot_name"]), []).append(
            {"name": row["bot_name"], "value": int(row["r"])})
    bot_total = sum(b["value"] for lst in subtypes.values() for b in lst)
    bot_total = min(bot_total, requests_total)
    human_total = requests_total - bot_total

    def subtype_children(lst):
        top, rest = lst[:6], lst[6:]
        children = list(top)
        if rest:
            children.append({"name": "(others)", "value": sum(b["value"] for b in rest)})
        return children

    sunburst = [{
        "name": "Human (est.)",
        "value": human_total,
        "itemStyle": {"color": "#4f8ff7"},
    }]
    subtype_colors = {"Search engines": "#3fb96f", "AI crawlers": "#f6821f",
                      SUBTYPE_OTHER: "#8a93a6"}
    bot_children = []
    for label in ("Search engines", "AI crawlers", SUBTYPE_OTHER):
        lst = subtypes.get(label)
        if lst:
            bot_children.append({
                "name": label,
                "itemStyle": {"color": subtype_colors[label]},
                "children": subtype_children(lst),
            })
    if bot_children:
        sunburst.append({
            "name": "Bots",
            "itemStyle": {"color": "#e5a94b"},
            "children": bot_children,
        })

    # Timelines over the full hour grid of the window.
    hour_grid = [start + timedelta(hours=i) for i in range(n)]
    cols = [_iso_z(h) for h in hour_grid]
    idx = {h: i for i, h in enumerate(hour_grid)}

    # Estimated humans per hour (requests - identified bots).
    human_data = [None] * n
    hourly = db.fetch_all(
        """
        SELECT hour_start, requests_est, bot_requests_est
        FROM hourly_zone_totals
        WHERE site = %s AND hour_start >= %s AND hour_start < %s
        """,
        (site, start, end),
    )
    for r in hourly:
        i = idx.get(r["hour_start"])
        if i is not None:
            human_data[i] = max(int(r["requests_est"]) - int(r["bot_requests_est"]), 0)

    # AI crawlers per hour, one series per top bot.
    ai_names = [row["bot_name"] for row in by_name
                if bots.bot_type(row["bot_name"]) == "ai"][:6]
    ai_series = []
    if ai_names:
        placeholders = ", ".join(["%s"] * len(ai_names))
        rows = db.fetch_all(
            f"""
            SELECT bot_name, hour_start, requests_est
            FROM hourly_bot_stats
            WHERE site = %s AND hour_start >= %s AND hour_start < %s
              AND bot_name IN ({placeholders})
            """,
            [site, start, end] + ai_names,
        )
        grid = {name: [0] * n for name in ai_names}
        for r in rows:
            i = idx.get(r["hour_start"])
            if i is not None:
                grid[r["bot_name"]][i] = int(r["requests_est"])
        ai_series = [{"name": name, "data": grid[name]} for name in ai_names]

    search_total = sum(b["value"] for b in subtypes.get("Search engines", []))
    ai_total = sum(b["value"] for b in subtypes.get("AI crawlers", []))

    return {
        "source": "mysql",
        "current_hours": cur_cov,
        "totals": {
            "requests": requests_total,
            "human": human_total,
            "bot": bot_total,
            "search": search_total,
            "ai": ai_total,
            "other_bots": bot_total - search_total - ai_total,
        },
        "views_factor": visits_factor(site, start, end),
        "sunburst": sunburst,
        "timeline": {"cols": cols, "ai_series": ai_series, "human": human_data},
    }


# --------------------------------------------------------------------------
# Panel E — International Reach
# --------------------------------------------------------------------------

HOME_COUNTRY = "IN"   # the dominant market; the panel focuses on the rest


def geo_panel(site, range_key):
    start, end, n = window(range_key)
    cur_cov = hours_covered(site, start, end)
    if cur_cov == 0:
        return _no_history()

    rows = db.fetch_all(
        """
        SELECT country, SUM(requests_est) r
        FROM hourly_country_stats
        WHERE site = %s AND hour_start >= %s AND hour_start < %s
        GROUP BY country ORDER BY r DESC
        """,
        (site, start, end),
    )
    countries = [{"code": r["country"], "requests": int(r["r"])} for r in rows]
    total = sum(c["requests"] for c in countries)
    home = next((c["requests"] for c in countries if c["code"] == HOME_COUNTRY), 0)

    return {
        "source": "mysql",
        "current_hours": cur_cov,
        "home_country": HOME_COUNTRY,
        "total": total,
        "home": home,
        "views_factor": visits_factor(site, start, end),
        "countries": countries,
    }


# --------------------------------------------------------------------------
# Panel F — Board Report (executive summary + day-by-day breakdown)
# --------------------------------------------------------------------------

# How many top stories get an hour-by-hour traction timeline per day.
TRACTION_PER_DAY = 6


def report_window(range_key):
    """Whole UTC calendar days for the report: (start, end, days, prior_start).

    Unlike the hour-aligned `window()`, the report buckets by calendar day so
    each row is a clean "what happened on the 21st" and the day-bucketed
    Cloudflare uniques line up. `days` = N whole days ending with today."""
    days = max(1, RANGE_HOURS[range_key] // 24)
    today = _utcnow().date()
    end = datetime.combine(today + timedelta(days=1), datetime.min.time())
    start = end - timedelta(days=days)
    return start, end, days, start - timedelta(days=days)


def _delta_pct(cur, prior):
    """Percent change cur vs prior, or None when there's no prior to compare."""
    if not prior:
        return None
    return (cur - prior) / prior * 100.0


def report_panel(site, range_key):
    """Board-meeting view: an executive summary with week-over-week deltas, a
    day-by-day table (each day's top story + fastest riser), the standout
    "story of the week", and audience/category context. MySQL-only; per-day and
    deduped unique-visitor figures are attached live by the route."""
    start, end, days, prior_start = report_window(range_key)

    cur_cov = hours_covered(site, start, end)
    if cur_cov == 0:
        return _no_history()
    prior_cov = hours_covered(site, prior_start, start)

    current_days = [(start + timedelta(days=i)).date() for i in range(days)]
    prior_days = [(prior_start + timedelta(days=i)).date() for i in range(days)]

    # Zone daily aggregates for the current AND prior window in one query.
    zrows = db.fetch_all(
        """
        SELECT DATE(hour_start) d, COUNT(*) hrs,
               SUM(requests_est) requests, SUM(visits_est) visits,
               SUM(bytes_est) bytes, SUM(bot_requests_est) bot,
               SUM(cached_requests_est) cached,
               SUM(errors_4xx_est) + SUM(errors_5xx_est) errors
        FROM hourly_zone_totals
        WHERE site = %s AND hour_start >= %s AND hour_start < %s
        GROUP BY DATE(hour_start)
        """,
        (site, prior_start, end),
    )
    by_day = {r["d"]: r for r in zrows}

    def _sum(day_list, key):
        return sum(int(by_day[d][key] or 0) for d in day_list if d in by_day)

    cur_req, prior_req = _sum(current_days, "requests"), _sum(prior_days, "requests")
    cur_vis, prior_vis = _sum(current_days, "visits"), _sum(prior_days, "visits")
    cur_byt, prior_byt = _sum(current_days, "bytes"), _sum(prior_days, "bytes")
    cur_err, prior_err = _sum(current_days, "errors"), _sum(prior_days, "errors")
    cur_cache = _sum(current_days, "cached")
    cur_bot = _sum(current_days, "bot")

    cur_err_rate = cur_err / cur_req if cur_req else 0.0
    prior_err_rate = prior_err / prior_req if prior_req else 0.0
    cur_cache_ratio = cur_cache / cur_req if cur_req else 0.0

    summary = {
        "requests": {"value": cur_req, "delta": _delta_pct(cur_req, prior_req) if prior_cov else None},
        "visits": {"value": cur_vis, "delta": _delta_pct(cur_vis, prior_vis) if prior_cov else None},
        "bytes": {"value": cur_byt, "delta": _delta_pct(cur_byt, prior_byt) if prior_cov else None},
        # uniques are filled in live by the route (not summable from rollups)
        "uniques": {"value": None, "delta": None},
        "error_rate": {"value": round(cur_err_rate, 5),
                       "delta_pp": round((cur_err_rate - prior_err_rate) * 100, 3) if prior_cov else None},
        "cache_hit_ratio": {"value": round(cur_cache_ratio, 5), "delta_pp": None},
    }

    # Per-path, per-day hits (current + one prior window so day 1 has a baseline
    # for "fastest riser"). Article paths only.
    prows = db.fetch_all(
        """
        SELECT DATE(hour_start) d, path, SUM(requests_est) hits
        FROM hourly_path_stats
        WHERE site = %s AND hour_start >= %s AND hour_start < %s
        GROUP BY DATE(hour_start), path
        """,
        (site, prior_start, end),
    )
    by_path_day = {}
    for r in prows:
        if not categories.is_article_path(r["path"]):
            continue
        by_path_day.setdefault(r["d"], {})[r["path"]] = int(r["hits"] or 0)

    def _surge(path, frm, to, day):
        return {"path": path, "title": categories.article_title(path),
                "gain": to - frm, "from": frm, "to": to, "date": day.strftime("%Y-%m-%d")}

    daily = []
    best_story = None   # biggest single-day surge of the week
    cat_totals = {}
    for day in current_days:
        z = by_day.get(day)
        req = int(z["requests"] or 0) if z else 0
        errors = int(z["errors"] or 0) if z else 0
        paths = by_path_day.get(day, {})
        prev = by_path_day.get(day - timedelta(days=1), {})
        # Top story / fastest riser must be real articles (headlines), not the
        # home page or a section landing; categories below stay broad.
        apaths = {p: h for p, h in paths.items() if categories.is_article(p)}

        top = None
        if apaths:
            tp = max(apaths, key=apaths.get)
            top = {"path": tp, "title": categories.article_title(tp), "hits": apaths[tp]}

        riser, best_gain = None, 0
        for path, hits in apaths.items():
            gain = hits - prev.get(path, 0)
            if gain > best_gain:
                best_gain, riser = gain, _surge(path, prev.get(path, 0), hits, day)
        if riser is not None and (best_story is None or riser["gain"] > best_story["gain"]):
            best_story = riser

        for path, hits in paths.items():
            cat = categories.categorize(path)
            cat_totals[cat] = cat_totals.get(cat, 0) + hits

        daily.append({
            "date": day.strftime("%Y-%m-%d"),
            "hours_covered": int(z["hrs"]) if z else 0,
            "requests": req,
            "visits": int(z["visits"] or 0) if z else 0,
            "bytes": int(z["bytes"] or 0) if z else 0,
            "error_rate": round(errors / req, 5) if req else 0.0,
            "uniques": None,   # filled live by the route
            "top": top,
            "riser": ({"path": riser["path"], "title": riser["title"],
                       "gain": riser["gain"]} if riser else None),
        })

    # Audience split over the current window (human / search / AI / other bots).
    by_name = db.fetch_all(
        """
        SELECT bot_name, SUM(requests_est) r
        FROM hourly_bot_stats
        WHERE site = %s AND hour_start >= %s AND hour_start < %s
        GROUP BY bot_name
        """,
        (site, start, end),
    )
    search = sum(int(b["r"] or 0) for b in by_name if bots.bot_type(b["bot_name"]) == "search")
    ai = sum(int(b["r"] or 0) for b in by_name if bots.bot_type(b["bot_name"]) == "ai")
    bot_total = min(cur_bot, cur_req)
    human = max(cur_req - bot_total, 0)
    other_bots = max(bot_total - min(search, bot_total) - min(ai, bot_total), 0)
    audience = {
        "total": cur_req,
        "human": human,
        "search": min(search, bot_total),
        "ai": min(ai, bot_total),
        "other_bots": other_bots,
        "sunburst": _report_sunburst(by_name, human, search, ai, other_bots),
    }

    cat_total = sum(cat_totals.values()) or 1
    top_categories = [
        {"name": name, "value": val, "share": round(val / cat_total * 100, 1)}
        for name, val in sorted(cat_totals.items(), key=lambda kv: kv[1], reverse=True)[:8]
    ]

    # Story timelines: for each day, its top articles with their hour-by-hour
    # trajectory, peak time and first surge — "how each story gained traction
    # and when". One hourly query covers every selected path across the window.
    selected = {}
    union = set()
    for day in current_days:
        paths = {p: h for p, h in by_path_day.get(day, {}).items() if categories.is_article(p)}
        topk = sorted(paths, key=paths.get, reverse=True)[:TRACTION_PER_DAY]
        if topk:
            selected[day] = topk
            union.update(topk)

    hourly_by_path = {}
    if union:
        placeholders = ", ".join(["%s"] * len(union))
        hrows = db.fetch_all(
            f"""
            SELECT hour_start, path, requests_est
            FROM hourly_path_stats
            WHERE site = %s AND hour_start >= %s AND hour_start < %s
              AND path IN ({placeholders})
            """,
            [site, start, end] + list(union),
        )
        for r in hrows:
            hourly_by_path.setdefault(r["path"], {})[r["hour_start"]] = int(r["requests_est"] or 0)

    now_hour = _utcnow().replace(minute=0, second=0, microsecond=0)
    traction = []
    for day in current_days:
        paths = selected.get(day)
        if not paths:
            continue
        day_start = datetime.combine(day, datetime.min.time())
        day_last = min(day_start + timedelta(hours=24), now_hour + timedelta(hours=1))
        hour_grid = []
        h = day_start
        while h < day_last:
            hour_grid.append(h)
            h += timedelta(hours=1)

        articles = []
        for path in paths:
            series = hourly_by_path.get(path, {})
            hourly = [{"ts": _iso_z(hr), "hits": series.get(hr, 0)} for hr in hour_grid]
            total = sum(p["hits"] for p in hourly)
            if total <= 0:
                continue
            peak = max(hourly, key=lambda p: p["hits"])
            threshold = max(peak["hits"] * 0.25, 1)   # "started gaining traction"
            first = next((p for p in hourly if p["hits"] >= threshold), peak)
            articles.append({
                "path": path,
                "title": categories.article_title(path),
                "total": total,
                "hourly": hourly,
                "peak_ts": peak["ts"],
                "peak_hits": peak["hits"],
                "first_ts": first["ts"],
            })
        if articles:
            traction.append({"date": day.strftime("%Y-%m-%d"), "articles": articles})

    return {
        "source": "mysql",
        "range": range_key,
        "days": days,
        "window_start": _iso_z(start),
        "window_end": _iso_z(end),
        "current_hours": cur_cov,
        "prior_hours": prior_cov,
        "prior_available": prior_cov > 0,
        "summary": summary,
        "daily": daily,
        "story": best_story,
        "audience": audience,
        "categories": top_categories,
        "traction": traction,
    }


REGISTRY = {
    "articles": articles_panel,
    "categories": categories_panel,
    "errors": errors_panel,
    "audience": audience_panel,
    "geo": geo_panel,
}
