RSS feeds now group multiple RSS URLs under one name and optional category.
The JSON field remains `url`, but its value must be a non-empty array of HTTP(S) URLs.

Before starting the updated backend, back up the database and run:

```sh
psql "$DATABASE_URL" -f backend/schema_change/002_feed_url_list.sql
```

Run the migration once. It wraps each existing URL in an array, retaining feed IDs,
article relationships, and categories. Fresh databases use `sql/create_schema.sql`.
Do not run that destructive schema creation script against an existing database.

Create with `POST /api/news/feeds/add`; edit with `PATCH /api/news/feeds/{feed_name}`:

```json
{
  "name": "tuoitre",
  "url": [
    "https://tuoitre.vn/home.rss",
    "https://tuoitre.vn/the-gioi.rss",
    "https://tuoitre.vn/thoi-su.rss",
    "https://tuoitre.vn/suc-khoe.rss"
  ],
  "category": "News"
}
```

PATCH accepts any subset of feed fields. New articles inherit the source category;
changing a category does not rewrite previously saved articles. The crawler attempts
every unique URL and deduplicates article links across URLs. Fetch logs aggregate
counts and duration per named source. Mixed URL outcomes have status `partial` and
include the failing URLs in the error message; all failures have status `error`.
