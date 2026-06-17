-- Cloudflare analytics rollups. One row = one hour of one zone (or one
-- hour x dimension value). All *_est columns are ESTIMATES: Cloudflare's
-- httpRequestsAdaptiveGroups dataset is adaptively sampled, and the collector
-- multiplies sampled counts by avg(sampleInterval) before storing.
--
-- hour_start is always UTC.

CREATE TABLE IF NOT EXISTS hourly_zone_totals (
    site                VARCHAR(64)     NOT NULL,
    hour_start          DATETIME        NOT NULL,
    requests_est        BIGINT UNSIGNED NOT NULL DEFAULT 0,
    bytes_est           BIGINT UNSIGNED NOT NULL DEFAULT 0,
    -- cacheStatus in (hit, stale, revalidated, updating)
    cached_requests_est BIGINT UNSIGNED NOT NULL DEFAULT 0,
    errors_4xx_est      BIGINT UNSIGNED NOT NULL DEFAULT 0,
    errors_5xx_est      BIGINT UNSIGNED NOT NULL DEFAULT 0,
    -- bot = User-Agent matched the configurable bot list (human = total - bot)
    bot_requests_est    BIGINT UNSIGNED NOT NULL DEFAULT 0,
    human_requests_est  BIGINT UNSIGNED NOT NULL DEFAULT 0,
    -- raw sampled-row count and the sample interval used for the estimate,
    -- kept for transparency/debugging of sampling correction
    raw_sample_count    BIGINT UNSIGNED NOT NULL DEFAULT 0,
    avg_sample_interval DOUBLE          NOT NULL DEFAULT 1,
    collected_at        TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP
                                        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (site, hour_start)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Top paths per hour (top N by request count, long tail is not stored).
-- utf8mb4_bin so /Foo and /foo stay distinct.
CREATE TABLE IF NOT EXISTS hourly_path_stats (
    site         VARCHAR(64)     NOT NULL,
    hour_start   DATETIME        NOT NULL,
    path         VARCHAR(512)    COLLATE utf8mb4_bin NOT NULL,
    requests_est BIGINT UNSIGNED NOT NULL DEFAULT 0,
    bytes_est    BIGINT UNSIGNED NOT NULL DEFAULT 0,
    PRIMARY KEY (site, hour_start, path),
    KEY idx_path_site_path (site, path, hour_start)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Per-hour error paths (edgeResponseStatus >= 400 only, top N per hour).
-- Added in Phase 2 so the error panel can show WHICH URLs fail, not just
-- how many errors occurred.
CREATE TABLE IF NOT EXISTS hourly_error_path_stats (
    site         VARCHAR(64)       NOT NULL,
    hour_start   DATETIME          NOT NULL,
    path         VARCHAR(512)      COLLATE utf8mb4_bin NOT NULL,
    status       SMALLINT UNSIGNED NOT NULL,
    requests_est BIGINT UNSIGNED   NOT NULL DEFAULT 0,
    PRIMARY KEY (site, hour_start, path, status),
    KEY idx_errpath_site_path (site, path, hour_start)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hourly_status_stats (
    site         VARCHAR(64)       NOT NULL,
    hour_start   DATETIME          NOT NULL,
    status       SMALLINT UNSIGNED NOT NULL,
    requests_est BIGINT UNSIGNED   NOT NULL DEFAULT 0,
    PRIMARY KEY (site, hour_start, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hourly_cache_stats (
    site         VARCHAR(64)     NOT NULL,
    hour_start   DATETIME        NOT NULL,
    cache_status VARCHAR(32)     NOT NULL,
    requests_est BIGINT UNSIGNED NOT NULL DEFAULT 0,
    bytes_est    BIGINT UNSIGNED NOT NULL DEFAULT 0,
    PRIMARY KEY (site, hour_start, cache_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hourly_country_stats (
    site         VARCHAR(64)     NOT NULL,
    hour_start   DATETIME        NOT NULL,
    country      VARCHAR(64)     NOT NULL,
    requests_est BIGINT UNSIGNED NOT NULL DEFAULT 0,
    PRIMARY KEY (site, hour_start, country)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Named bots seen in the hour (from the top-N user agents of that hour).
CREATE TABLE IF NOT EXISTS hourly_bot_stats (
    site         VARCHAR(64)     NOT NULL,
    hour_start   DATETIME        NOT NULL,
    bot_name     VARCHAR(64)     NOT NULL,
    requests_est BIGINT UNSIGNED NOT NULL DEFAULT 0,
    PRIMARY KEY (site, hour_start, bot_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
