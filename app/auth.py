"""Session-based auth gate for the dashboard.

One shared credential, read entirely from the environment (never hardcoded):
  APP_USERNAME       the login name
  APP_PASSWORD_HASH  a werkzeug password hash (generate_password_hash); the
                     plaintext password never lives in code or the repo and is
                     verified with check_password_hash.

The login page is public-facing, so /login has a simple per-IP failed-attempt
lockout plus a small constant delay on every failure.
"""
import time
from functools import wraps
from urllib.parse import urlparse

from flask import (
    Blueprint, current_app, redirect, render_template, request, session, url_for,
)
from werkzeug.security import check_password_hash

from . import config

bp = Blueprint("auth", __name__)


def login_required(view):
    """Gate a view behind a valid session; bounce to /login with a next hop."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            nxt = request.full_path.rstrip("?")
            return redirect(url_for("auth.login", next=nxt))
        return view(*args, **kwargs)
    return wrapped


# ---- Per-IP failed-attempt throttle --------------------------------------
# In-memory, so it lives per worker process (deliberate: no shared store on a
# RAM-constrained box). Cloudflare's WAF rate-limiting sits in front for the
# distributed case. Maps client IP -> list of recent failure timestamps.
_attempts: dict[str, list[float]] = {}


def _client_ip():
    # ProxyFix already rewrites remote_addr from X-Forwarded-For; prefer
    # Cloudflare's canonical client header when the request came through it.
    return request.headers.get("CF-Connecting-IP") or request.remote_addr or "unknown"


def _recent_failures(ip):
    cutoff = time.time() - config.LOGIN_LOCKOUT_SECONDS
    fails = [t for t in _attempts.get(ip, []) if t > cutoff]
    if fails:
        _attempts[ip] = fails
    else:
        _attempts.pop(ip, None)
    return fails


def _is_locked(ip):
    return len(_recent_failures(ip)) >= config.LOGIN_MAX_ATTEMPTS


def _record_failure(ip):
    _attempts.setdefault(ip, []).append(time.time())


def _safe_next(target):
    """Allow only same-site relative redirects (defeats open-redirect)."""
    if not target:
        return None
    # Browsers treat "\" like "/", so "/\evil.com" is really "//evil.com".
    # Normalize before validating.
    normalized = target.replace("\\", "/")
    parsed = urlparse(normalized)
    if parsed.scheme or parsed.netloc:
        return None
    if not normalized.startswith("/") or normalized.startswith("//"):
        return None
    return normalized


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user"):
        return redirect(url_for("main.dashboard"))

    next_url = _safe_next(request.args.get("next"))
    ip = _client_ip()

    if request.method == "POST":
        if _is_locked(ip):
            current_app.logger.warning("login locked out for %s", ip)
            return render_template(
                "login.html",
                error="Too many attempts. Please wait a few minutes and try again.",
                next_url=next_url,
            ), 429

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        pw_hash = config.APP_PASSWORD_HASH

        valid = (
            bool(pw_hash)
            and username == config.APP_USERNAME
            and check_password_hash(pw_hash, password)
        )
        if valid:
            session.clear()
            session["user"] = username
            session.permanent = True
            _attempts.pop(ip, None)
            current_app.logger.info("login ok for %s from %s", username, ip)
            return redirect(_safe_next(request.form.get("next")) or url_for("main.dashboard"))

        _record_failure(ip)
        current_app.logger.warning("login failed for %r from %s", username, ip)
        time.sleep(0.6)  # constant slowdown blunts online guessing
        return render_template(
            "login.html", error="Invalid username or password.", next_url=next_url,
        ), 401

    return render_template("login.html", next_url=next_url)


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
