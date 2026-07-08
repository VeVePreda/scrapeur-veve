"""
VeVe blog scraper — entry point (run on demand).

Scrapes the VeVe blog listing pages, fetches the FULL content of each new
article, and upserts everything (title, category, tags, author, reading time,
excerpt, full body, cover image, permalink) into the "📝C-BLOG" tab, then logs
the run to the "🤖LOGS" tab.

Standalone: not part of the daily workflow. Trigger it manually (GitHub Actions
"Run workflow" on blog.yml) whenever you want to refresh the blog tab.

Article pages are only fetched for articles that don't already have content in
the sheet, so the first run does a full backfill and later runs stay light.

Env:
    GOOGLE_SERVICE_ACCOUNT_JSON   service account with edit access to the sheet
    SHEET_ID                      target spreadsheet id
    BLOG_MAX_PAGES                0 = all listing pages (default); e.g. 2 = newest only
    BLOG_WITH_CONTENT             "true" (default) fetches each article's full body
    BLOG_MAX_NEW                  0 = no cap (default); cap article-page fetches/run
"""

from __future__ import annotations

import os
import sys
import time

from scraper import blog
from scraper import sheets


def _flag(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def main() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        print("ERROR: SHEET_ID env var is required.", file=sys.stderr)
        return 2

    max_pages = int(os.environ.get("BLOG_MAX_PAGES", "0") or "0")
    with_content = _flag("BLOG_WITH_CONTENT", True)
    max_new = int(os.environ.get("BLOG_MAX_NEW", "0") or "0")

    scope = "all pages" if max_pages == 0 else f"first {max_pages} page(s)"
    print(f"Scraping VeVe blog ({scope}; content={'on' if with_content else 'off'})...",
          flush=True)

    articles = blog.scrape_blog(max_pages=max_pages)
    if not articles:
        print("No blog articles harvested — aborting to protect your data.",
              file=sys.stderr)
        try:
            sheets.append_run_log(
                sheet_id,
                {"status": "FAILED_NO_DATA", "note": "blog returned no articles."},
                source="blog")
        except Exception:
            pass
        return 1

    if with_content:
        skip = blog.slugs_with_content(sheet_id)
        blog.enrich_with_content(articles, skip_slugs=skip, max_new=max_new)

    result = blog.sync_blog(articles, sheet_id)
    result["duration"] = f"{time.time() - t0:.0f}s"
    try:
        sheets.append_run_log(sheet_id, result, source="blog")
    except Exception as e:
        print(f"run log warning: {e}", flush=True)

    print(f"Done. status={result.get('status')} "
          f"rows={result.get('total_rows')} "
          f"new={result.get('new_articles')} "
          f"updated={result.get('updated_articles')} "
          f"with_content={result.get('with_content')} "
          f"in {time.time()-t0:.0f}s", flush=True)
    return 0 if result.get("status") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
