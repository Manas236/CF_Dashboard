"""Path -> editorial category derivation (rules live in config.CATEGORY_RULES)."""
import re

from . import config

_YEAR_RE = re.compile(r"^\d{4}$")


def is_article_path(path):
    """False for assets/feeds/APIs that should not appear in content panels."""
    p = (path or "").lower()
    if any(p.startswith(prefix) for prefix in config.ARTICLE_EXCLUDE_PREFIXES):
        return False
    if any(p.endswith(suffix) for suffix in config.ARTICLE_EXCLUDE_SUFFIXES):
        return False
    return True


def categorize(path):
    """Category label for a path: first matching configured prefix wins,
    otherwise the prettified first path segment."""
    p = path or "/"
    for prefix, label in config.CATEGORY_RULES:
        if p.startswith(prefix):
            return label
    segment = p.lstrip("/").split("/", 1)[0].split("?", 1)[0]
    if not segment:
        return "Home"
    if _YEAR_RE.match(segment):
        return "Archive (dated)"
    return segment.replace("-", " ").replace("_", " ").strip().title() or "Home"


def article_title(path):
    """Human-ish title from a path slug, for treemap tiles and tooltips."""
    slug = (path or "").rstrip("/").rsplit("/", 1)[-1]
    slug = slug.split("?", 1)[0].split(".", 1)[0]
    title = slug.replace("-", " ").replace("_", " ").strip()
    if not title:
        return path or "/"
    return title[:80].capitalize()
