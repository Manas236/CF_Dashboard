import os
import secrets
from datetime import timedelta

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from . import config


def create_app():
    app = Flask(__name__)

    # --- Session secret. Required in production; fall back to an ephemeral key
    # in dev so the app still boots (every restart then invalidates sessions).
    secret = config.SECRET_KEY
    if not secret:
        app.logger.warning(
            "SECRET_KEY is not set — using a throwaway key. Logins won't survive "
            "a restart. Set SECRET_KEY in .env before going to production."
        )
        secret = secrets.token_hex(32)
    app.secret_key = secret

    # --- Hardened session cookies (the app runs behind HTTPS in production).
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=config.SESSION_COOKIE_SECURE,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=config.SESSION_LIFETIME_MINUTES),
    )

    # --- Trust one proxy hop's X-Forwarded-* (Nginx in front) so remote_addr
    # and the URL scheme reflect the real client, not 127.0.0.1.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # --- Cache-bust static assets. Cloudflare/Nginx cache css & js hard, so a
    # deploy that ships new common.js/style.css would otherwise leave returning
    # users on the stale copies (e.g. the mobile nav button rendering but its
    # click handler missing). Stamp every static URL with the file's mtime so
    # the URL changes whenever the file does, forcing a fresh fetch.
    @app.url_defaults
    def add_static_version(endpoint, values):
        if endpoint != "static" or "filename" not in values:
            return
        fpath = os.path.join(app.static_folder, values["filename"])
        try:
            values["v"] = int(os.stat(fpath).st_mtime)
        except OSError:
            pass

    from .auth import bp as auth_bp
    from .routes import bp as main_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    return app
