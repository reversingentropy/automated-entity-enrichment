"""
Collect the outlets' historical archives for a one-off backfill.

Not the nightly pipeline. This reads what the outlets publish for search
engines -- CNA's public search index, and the monthly sitemaps of the Straits
Times and Zaobao -- into `article_backfill`, a table the nightly jobs never
touch. Relevance and extraction over it run on an internal model, by export
and import, because 240,000 articles is not a free-tier workload.

  python -m src.backfill count                          # what is out there
  python -m src.backfill collect cna --from 2015-01     # titles, no fetches
  python -m src.backfill collect st  --from 2024-01 --to 2024-12
  python -m src.backfill collect zb  --from 2024-01 --to 2024-12
"""
