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


# An article slug is a headline "sentence"; a section/category is one or two
# words; "/" is the home page. Below this many slug words a path is treated as
# a section, not an article.
ARTICLE_MIN_SLUG_WORDS = 3


def is_article(path):
    """True only for an actual article (a headline), not the home page or a
    section/category landing page.

    Rule (from the site's URL shape): "/" is Home; a final path segment of one
    or two words (e.g. "cricket", "health-wellness") is a section; a multi-word
    slug (a headline, e.g. "morbe-at-26-water-cuts-continue") is an article.
    """
    if not is_article_path(path):
        return False
    p = (path or "").split("?", 1)[0].split("#", 1)[0].rstrip("/")
    if not p:                      # "/" -> Home
        return False
    slug = p.rsplit("/", 1)[-1]
    words = [w for w in re.split(r"[-_]+", slug) if w]
    return len(words) >= ARTICLE_MIN_SLUG_WORDS


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
