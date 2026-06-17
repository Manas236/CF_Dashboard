"""Bot vs human classification by User-Agent matching.

The free plan has no bot score, so we match User-Agents against a known-bot
list (case-insensitive substring). Anything unmatched is assumed human:
    assumed humans = eyeball total - UA-identified bots

Each signature carries a type used by the audience panel to group bots:
    search | ai | seo | social | monitor | feed | script | other

Extend the list without touching code via BOT_UA_FILE in .env (one signature
per line: "Name|substring" or "Name|substring|type"). File entries are
checked first, then the defaults below. Order matters: specific signatures
must come before the generic fallbacks at the bottom.
"""
from functools import lru_cache

from . import config

DEFAULT_BOT_SIGNATURES = [
    # (canonical name, lowercase substring matched against the User-Agent, type)
    # --- Search engines ---
    ("Googlebot", "googlebot", "search"),
    ("GoogleOther", "googleother", "search"),
    ("Bingbot", "bingbot", "search"),
    ("DuckDuckBot", "duckduckbot", "search"),
    ("Baiduspider", "baiduspider", "search"),
    ("YandexBot", "yandex", "search"),
    ("Sogou", "sogou", "search"),
    ("SeznamBot", "seznambot", "search"),
    ("PetalBot", "petalbot", "search"),
    ("Yahoo Slurp", "slurp", "search"),
    # --- AI / LLM crawlers ---
    ("GPTBot", "gptbot", "ai"),
    ("OAI-SearchBot", "oai-searchbot", "ai"),
    ("ChatGPT-User", "chatgpt-user", "ai"),
    ("ClaudeBot", "claudebot", "ai"),
    ("Claude-User", "claude-user", "ai"),
    ("Claude-SearchBot", "claude-searchbot", "ai"),
    ("Anthropic-AI", "anthropic-ai", "ai"),
    ("PerplexityBot", "perplexitybot", "ai"),
    ("Perplexity-User", "perplexity-user", "ai"),
    ("Google-Extended", "google-extended", "ai"),
    ("Applebot", "applebot", "ai"),
    ("CCBot", "ccbot", "ai"),
    ("Bytespider", "bytespider", "ai"),
    ("Amazonbot", "amazonbot", "ai"),
    ("Meta-ExternalAgent", "meta-externalagent", "ai"),
    ("Meta-ExternalFetcher", "meta-externalfetcher", "ai"),
    ("Cohere-AI", "cohere-ai", "ai"),
    ("MistralAI-User", "mistralai-user", "ai"),
    ("Diffbot", "diffbot", "ai"),
    # --- SEO / research crawlers ---
    ("AhrefsBot", "ahrefsbot", "seo"),
    ("SemrushBot", "semrushbot", "seo"),
    ("MJ12bot", "mj12bot", "seo"),
    ("DotBot", "dotbot", "seo"),
    ("DataForSeoBot", "dataforseobot", "seo"),
    ("BLEXBot", "blexbot", "seo"),
    # --- Social / link previews ---
    ("Facebook Preview", "facebookexternalhit", "social"),
    ("Twitterbot", "twitterbot", "social"),
    ("LinkedInBot", "linkedinbot", "social"),
    ("TelegramBot", "telegrambot", "social"),
    ("WhatsApp Preview", "whatsapp", "social"),
    ("Discordbot", "discordbot", "social"),
    ("Slackbot", "slackbot", "social"),
    # --- Monitoring / uptime ---
    ("UptimeRobot", "uptimerobot", "monitor"),
    ("Pingdom", "pingdom", "monitor"),
    ("StatusCake", "statuscake", "monitor"),
    # --- Feed readers ---
    ("Feedly", "feedly", "feed"),
    ("Feedbin", "feedbin", "feed"),
    # --- Scripts and HTTP clients ---
    ("HTTP client", "python-requests", "script"),
    ("HTTP client", "python-urllib", "script"),
    ("HTTP client", "aiohttp", "script"),
    ("HTTP client", "httpx", "script"),
    ("HTTP client", "scrapy", "script"),
    ("HTTP client", "curl/", "script"),
    ("HTTP client", "wget/", "script"),
    ("HTTP client", "go-http-client", "script"),
    ("HTTP client", "okhttp", "script"),
    ("HTTP client", "java/", "script"),
    ("HTTP client", "libwww-perl", "script"),
    ("Headless browser", "headlesschrome", "script"),
    ("Headless browser", "phantomjs", "script"),
    # --- Generic fallbacks (keep LAST) ---
    ("Other bot", "bot", "other"),
    ("Other crawler", "crawler", "other"),
    ("Other crawler", "spider", "other"),
]

VALID_TYPES = {"search", "ai", "seo", "social", "monitor", "feed", "script", "other"}


@lru_cache(maxsize=1)
def signatures():
    """Active signature list: BOT_UA_FILE entries (if any) + defaults."""
    custom = []
    if config.BOT_UA_FILE:
        for line in open(config.BOT_UA_FILE, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) == 1:
                custom.append((parts[0], parts[0].lower(), "other"))
            else:
                btype = parts[2].lower() if len(parts) > 2 and parts[2].lower() in VALID_TYPES else "other"
                custom.append((parts[0], parts[1].lower(), btype))
    return custom + DEFAULT_BOT_SIGNATURES


@lru_cache(maxsize=1)
def _type_by_name():
    mapping = {"Empty UA": "other"}
    for name, _needle, btype in signatures():
        mapping.setdefault(name, btype)
    return mapping


def bot_type(name):
    """Type for a stored bot name; unknown names (e.g. removed signatures)
    fall back to 'other'."""
    return _type_by_name().get(name, "other")


def classify(user_agent):
    """Return the bot name for a User-Agent, or None if assumed human.

    An empty/missing UA never comes from a real browser, so it counts as bot.
    """
    if not user_agent or not user_agent.strip():
        return "Empty UA"
    ua = user_agent.lower()
    for name, needle, _btype in signatures():
        if needle in ua:
            return name
    return None


def tally(user_agent_rows):
    """Aggregate [{user_agent, requests}] into (bot_total, {bot_name: requests})."""
    bot_total = 0
    breakdown = {}
    for row in user_agent_rows:
        name = classify(row.get("user_agent", ""))
        if name:
            bot_total += row["requests"]
            breakdown[name] = breakdown.get(name, 0) + row["requests"]
    return bot_total, breakdown
