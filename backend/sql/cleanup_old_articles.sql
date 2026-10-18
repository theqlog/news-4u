-- Run with psql; preview by default, or pass --set=apply=true to delete.
\set ON_ERROR_STOP on
\if :{?apply}
\else
    \set apply false
\endif

BEGIN;
SET LOCAL TIME ZONE 'UTC';

SELECT CURRENT_TIMESTAMP - INTERVAL '1 month' AS cutoff,
       COUNT(*) AS articles_to_delete
FROM news_articles
WHERE COALESCE(published_date, created_at) < CURRENT_TIMESTAMP - INTERVAL '1 month';

\if :apply
    DELETE FROM news_articles
    WHERE COALESCE(published_date, created_at) < CURRENT_TIMESTAMP - INTERVAL '1 month';
    COMMIT;
\else
    ROLLBACK;
    \echo 'Preview only. Run again with --set=apply=true to delete these articles.'
\endif
