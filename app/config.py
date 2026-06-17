"""Central configuration. All secrets come from .env (python-dotenv)."""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

CF_API_TOKEN = os.getenv("CF_API_TOKEN", "")
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID", "")
CF_GRAPHQL_ENDPOINT = "https://api.cloudflare.com/client/v4/graphql"

# The two news sites. Keys are the canonical site identifiers used in URLs
# and stored in the MySQL `site` column.
#
# Each site carries its own API token because the two sites live in SEPARATE
# Cloudflare accounts — a token issued in one account cannot read a zone in the
# other. CF_API_TOKEN_<SITE> overrides the shared CF_API_TOKEN as a fallback,
# so a single-account setup still works with just CF_API_TOKEN set.
# (Account ID is not needed: these GraphQL analytics queries authenticate with
# the token and select the zone by zone tag.)
SITES = {
    "newsband.in": {
        "label": "Newsband",
        "zone_id": os.getenv("CF_ZONE_ID_NEWSBAND", ""),
        "api_token": os.getenv("CF_API_TOKEN_NEWSBAND", "") or CF_API_TOKEN,
    },
    "naveshahar.com": {
        "label": "Nave Shahar",
        "zone_id": os.getenv("CF_ZONE_ID_NAVESHAHAR", ""),
        "api_token": os.getenv("CF_API_TOKEN_NAVESHAHAR", "") or CF_API_TOKEN,
    },
}
DEFAULT_SITE = "newsband.in"

MYSQL = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", ""),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "cf_analytics"),
}

COLLECT_HOURS = int(os.getenv("COLLECT_HOURS", "6"))
BOT_UA_FILE = os.getenv("BOT_UA_FILE", "")

# Per-hour GraphQL group limits (cardinality control on the free plan).
# Everything past the top N for an hour is dropped from dimension rollups;
# zone totals are always exact-as-sampled.
LIMIT_PATHS = int(os.getenv("LIMIT_PATHS", "500"))
LIMIT_USER_AGENTS = int(os.getenv("LIMIT_USER_AGENTS", "500"))
LIMIT_ERROR_PATHS = int(os.getenv("LIMIT_ERROR_PATHS", "300"))
LIMIT_STATUS = 50   # used by the live KPI fallback
LIMIT_CACHE = 20

# Collector batching: cheap dimensions (totals/status/cache/country) are
# fetched for RANGE_CHUNK_HOURS hours in ONE GraphQL call grouped by
# datetimeHour; heavy per-hour top-Ns (paths/UAs/error paths) are aliased
# HEAVY_BATCH_HOURS hours per call. Both sized to stay under Cloudflare's
# per-query group budget.
RANGE_CHUNK_HOURS = int(os.getenv("RANGE_CHUNK_HOURS", "12"))
HEAVY_BATCH_HOURS = int(os.getenv("HEAVY_BATCH_HOURS", "6"))

# ---- Panels ----
# Minimum hits in the current window before a path can "trend" (a 2 -> 20
# jump is +900% but means nothing editorially).
TREND_MIN_HITS = int(os.getenv("TREND_MIN_HITS", "50"))

# Paths that are not editorial content, excluded from article/category panels.
# Edit freely; matched against the start / end of the path.
ARTICLE_EXCLUDE_PREFIXES = (
    "/wp-json", "/wp-admin", "/wp-content", "/wp-includes", "/wp-login",
    "/wp-cron", "/xmlrpc.php", "/feed", "/robots.txt", "/favicon",
    "/sitemap", "/ads.txt", "/cdn-cgi/", "/.well-known",
    "/template/", "/uploads/", "/paginationblogcat",
)
ARTICLE_EXCLUDE_SUFFIXES = (
    ".js", ".css", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".otf", ".xml", ".txt", ".map", ".json",
    ".mp4", ".webm", ".pdf", ".zip",
)

# Category rule: first matching path prefix wins; anything unmatched falls
# back to a prettified first path segment ("/life-style/x" -> "Life Style"),
# "/" -> "Home", and 4-digit-year segments -> "Archive (dated)".
# Edit freely — e.g. merge sections by giving two prefixes the same label.
CATEGORY_RULES = [
    # newsband.in
    ("/article_detail/", "Articles"),
    ("/article/", "Sections"),
    ("/item/", "Archive (item)"),
    ("/category/", "Categories"),
    ("/epaper", "E-paper"),
    ("/video", "Video"),
    # naveshahar.com-style sections
    ("/news/", "News"),
    ("/interviews/", "Interviews"),
    ("/life-style/", "Life Style"),
]

DASH_HOST = os.getenv("DASH_HOST", "127.0.0.1")
DASH_PORT = int(os.getenv("DASH_PORT", "5000"))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"

# ---- Auth / session ----
# All three are read from .env; no credential is ever hardcoded here.
#   SECRET_KEY         signs the session cookie (required in production)
#   APP_USERNAME       the single shared login name
#   APP_PASSWORD_HASH  a werkzeug hash (generate_password_hash) — the plaintext
#                      password never lives in code or the repo.
SECRET_KEY = os.getenv("SECRET_KEY", "")
APP_USERNAME = os.getenv("APP_USERNAME", "")
APP_PASSWORD_HASH = os.getenv("APP_PASSWORD_HASH", "")

# Secure cookie requires HTTPS, so it's on in production and off by default for
# local HTTP dev (FLASK_DEBUG=1). Override explicitly with SESSION_COOKIE_SECURE.
SESSION_COOKIE_SECURE = os.getenv(
    "SESSION_COOKIE_SECURE", "0" if FLASK_DEBUG else "1"
) != "0"
# How long a login stays valid (sliding lifetime, minutes). Default 12h.
SESSION_LIFETIME_MINUTES = int(os.getenv("SESSION_LIFETIME_MINUTES", "720"))

# /login throttle: after LOGIN_MAX_ATTEMPTS failures from one IP within the
# window, lock that IP out for LOGIN_LOCKOUT_SECONDS.
LOGIN_MAX_ATTEMPTS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_LOCKOUT_SECONDS = int(os.getenv("LOGIN_LOCKOUT_SECONDS", "300"))
