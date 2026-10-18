-- Preserve feed IDs, article relationships, and existing single URLs.
-- Run once before deploying the backend with list-valued URLs.
BEGIN;
ALTER TABLE rss_feeds
    ALTER COLUMN url TYPE TEXT[] USING ARRAY[url::text];
ALTER TABLE rss_feeds ADD CONSTRAINT rss_feeds_url_nonempty
    CHECK (cardinality(url) > 0 AND array_position(url, NULL) IS NULL);
COMMENT ON COLUMN rss_feeds.url IS 'Non-empty list of RSS feed URLs';
COMMIT;
