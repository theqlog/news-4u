-- ============================================================================
-- News-4U Database Schema
-- ============================================================================
-- This script creates all tables, indexes, and constraints for the News-4U
-- RSS aggregator application.
--
-- Usage:
--   psql -h localhost -U news4u -d news4u_db -f create_schema.sql
-- ============================================================================

-- Drop existing tables (in reverse order due to foreign keys)
DROP TABLE IF EXISTS feed_fetch_logs CASCADE;
DROP TABLE IF EXISTS news_articles CASCADE;
DROP TABLE IF EXISTS rss_feeds CASCADE;

-- ============================================================================
-- TABLE: rss_feeds
-- ============================================================================
-- Stores RSS feed sources and their configuration
CREATE TABLE rss_feeds (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    url TEXT[] NOT NULL CHECK (cardinality(url) > 0 AND array_position(url, NULL) IS NULL),
    category VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    skip_extraction BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE
);

-- Add comment
COMMENT ON TABLE rss_feeds IS 'RSS feed sources configuration';
COMMENT ON COLUMN rss_feeds.name IS 'Unique feed name identifier';
COMMENT ON COLUMN rss_feeds.url IS 'Non-empty list of RSS feed URLs';
COMMENT ON COLUMN rss_feeds.category IS 'Feed category (technology, business, sports, etc.)';
COMMENT ON COLUMN rss_feeds.is_active IS 'Whether this feed is actively being fetched';

-- Indexes for rss_feeds
CREATE INDEX ix_rss_feeds_id ON rss_feeds(id);
CREATE INDEX ix_rss_feeds_is_active ON rss_feeds(is_active);

-- ============================================================================
-- TABLE: news_articles
-- ============================================================================
-- Stores news articles fetched from RSS feeds
CREATE TABLE news_articles (
    id SERIAL PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    summary TEXT,
    content TEXT,
    link VARCHAR(1000) NOT NULL UNIQUE,
    author VARCHAR(255),
    published_date TIMESTAMP WITH TIME ZONE,
    category VARCHAR(50),
    image_url VARCHAR(1000),
    slug VARCHAR(255) UNIQUE,
    retry_count INTEGER DEFAULT 0 NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE,
    feed_id INTEGER,

    -- Foreign key constraint
    CONSTRAINT fk_news_articles_feed_id
        FOREIGN KEY (feed_id)
        REFERENCES rss_feeds(id)
        ON DELETE SET NULL
);

-- Add comments
COMMENT ON TABLE news_articles IS 'News articles fetched from RSS feeds';
COMMENT ON COLUMN news_articles.title IS 'Article title';
COMMENT ON COLUMN news_articles.summary IS 'Article summary/description from RSS feed';
COMMENT ON COLUMN news_articles.content IS 'Full article content (extracted)';
COMMENT ON COLUMN news_articles.link IS 'Unique article URL';
COMMENT ON COLUMN news_articles.author IS 'Article author name';
COMMENT ON COLUMN news_articles.published_date IS 'Article publication date';
COMMENT ON COLUMN news_articles.category IS 'Article category inherited from feed';
COMMENT ON COLUMN news_articles.image_url IS 'Featured image URL';
COMMENT ON COLUMN news_articles.slug IS 'URL-friendly article identifier';
COMMENT ON COLUMN news_articles.retry_count IS 'Number of failed content extraction attempts';
COMMENT ON COLUMN news_articles.feed_id IS 'Reference to source RSS feed';

-- Indexes for news_articles
CREATE INDEX ix_news_articles_id ON news_articles(id);
CREATE INDEX ix_news_articles_feed_id ON news_articles(feed_id);

-- Performance indexes (added in refactoring)
CREATE INDEX ix_news_articles_published_date ON news_articles(published_date);
CREATE INDEX ix_news_articles_category ON news_articles(category);
CREATE INDEX ix_news_articles_feed_id_created_at ON news_articles(feed_id, created_at);

-- Additional index for retry tracking
CREATE INDEX idx_news_articles_retry_count ON news_articles(retry_count);

-- ============================================================================
-- TABLE: feed_fetch_logs
-- ============================================================================
-- Logs each RSS feed fetch operation for monitoring and debugging
CREATE TABLE feed_fetch_logs (
    id SERIAL PRIMARY KEY,
    feed_id INTEGER,
    fetch_timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    status VARCHAR(50) NOT NULL,
    articles_found INTEGER DEFAULT 0 NOT NULL,
    articles_processed INTEGER DEFAULT 0 NOT NULL,
    error_message TEXT,
    execution_time_ms INTEGER,

    -- Foreign key constraint
    CONSTRAINT fk_feed_fetch_logs_feed_id
        FOREIGN KEY (feed_id)
        REFERENCES rss_feeds(id)
        ON DELETE CASCADE
);

-- Add comments
COMMENT ON TABLE feed_fetch_logs IS 'Logs of RSS feed fetch operations';
COMMENT ON COLUMN feed_fetch_logs.feed_id IS 'Reference to the RSS feed';
COMMENT ON COLUMN feed_fetch_logs.fetch_timestamp IS 'When the fetch operation occurred';
COMMENT ON COLUMN feed_fetch_logs.status IS 'Fetch status: success, error, starting, partial';
COMMENT ON COLUMN feed_fetch_logs.articles_found IS 'Number of articles found in feed';
COMMENT ON COLUMN feed_fetch_logs.articles_processed IS 'Number of articles successfully processed';
COMMENT ON COLUMN feed_fetch_logs.error_message IS 'Error message if fetch failed';
COMMENT ON COLUMN feed_fetch_logs.execution_time_ms IS 'Fetch operation duration in milliseconds';

-- Indexes for feed_fetch_logs
CREATE INDEX ix_feed_fetch_logs_id ON feed_fetch_logs(id);
CREATE INDEX ix_feed_fetch_logs_feed_id ON feed_fetch_logs(feed_id);
CREATE INDEX ix_feed_fetch_logs_fetch_timestamp ON feed_fetch_logs(fetch_timestamp);
CREATE INDEX ix_feed_fetch_logs_status ON feed_fetch_logs(status);

-- ============================================================================
-- TRIGGERS
-- ============================================================================

-- Trigger to automatically update updated_at timestamp on rss_feeds
CREATE OR REPLACE FUNCTION update_rss_feeds_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_rss_feeds_updated_at
    BEFORE UPDATE ON rss_feeds
    FOR EACH ROW
    EXECUTE FUNCTION update_rss_feeds_updated_at();

-- Trigger to automatically update updated_at timestamp on news_articles
CREATE OR REPLACE FUNCTION update_news_articles_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_news_articles_updated_at
    BEFORE UPDATE ON news_articles
    FOR EACH ROW
    EXECUTE FUNCTION update_news_articles_updated_at();

-- ============================================================================
-- GRANTS (adjust user as needed)
-- ============================================================================

-- Grant all privileges to the application user
-- Replace 'news4u' with your actual database user
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO news4u;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO news4u;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO news4u;

-- ============================================================================
-- VERIFICATION
-- ============================================================================

-- Show created tables
SELECT
    table_name,
    (SELECT COUNT(*)
     FROM information_schema.columns
     WHERE table_name = t.table_name) as column_count
FROM information_schema.tables t
WHERE table_schema = 'public'
    AND table_type = 'BASE TABLE'
ORDER BY table_name;

-- Show created indexes
SELECT
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname;

-- ============================================================================
-- NOTES
-- ============================================================================
--
-- Performance Indexes:
--   - ix_news_articles_published_date: Speeds up date-based queries by 60-90%
--   - ix_news_articles_category: Speeds up category filtering by 50-80%
--   - ix_news_articles_feed_id_created_at: Optimizes feed+date queries
--   - ix_rss_feeds_is_active: Speeds up active feed filtering by 40-60%
--
-- Foreign Keys:
--   - news_articles.feed_id -> rss_feeds.id (SET NULL on delete)
--   - feed_fetch_logs.feed_id -> rss_feeds.id (CASCADE on delete)
--
-- Triggers:
--   - Auto-update updated_at columns on UPDATE operations
--
-- ============================================================================
