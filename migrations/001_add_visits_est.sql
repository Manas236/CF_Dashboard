-- Adds the visits_est column to an existing hourly_zone_totals table.
-- schema.sql only CREATEs IF NOT EXISTS, so existing databases need this
-- run once before the visits-aware collector/app code goes live.
-- Idempotency: MySQL has no "ADD COLUMN IF NOT EXISTS" pre-8.0.x in all
-- builds, so re-running will error with "Duplicate column" — that's safe to
-- ignore (it just means the column is already there).

ALTER TABLE hourly_zone_totals
  ADD COLUMN visits_est BIGINT UNSIGNED NOT NULL DEFAULT 0 AFTER bytes_est;
