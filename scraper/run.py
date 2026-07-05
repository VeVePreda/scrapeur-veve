"""
Entry point: scrape the full VeVe catalogue and sync it into the Google Sheet.

Environment variables (set as GitHub Actions secrets):
  GOOGLE_SERVICE_ACCOUNT_JSON  -> the full service-account JSON (as a string)
  SHEET_ID                     -> the spreadsheet id (from its URL)
  SHEET_TAB                    -> optional, defaults to "Catalogue"

Run locally:
  pip install -r requirements.txt
  export GOOGLE_SERVICE_ACCOUNT_JSON="$(cat service_account.json)"
  export SHEET_ID="1YMsK90zwxdmRuYiThVcDsJ2re_Rx_Nz1v5KlLGxnUHA"
  python -m scraper.run
"""

from __future__ import annotations

import os
import sys

from scraper.veve_scraper import scrape_catalogue
from scraper import sheets


def main() -> int:
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        print("ERROR: SHEET_ID env var is required.", file=sys.stderr)
        return 2
    tab = os.environ.get("SHEET_TAB", "Catalogue")

    print("Starting VeVe catalogue scrape...", flush=True)
    products = scrape_catalogue()
    if not products:
        print("No products harvested — aborting sheet write to avoid clearing data.", file=sys.stderr)
        return 1

    print(f"Syncing {len(products)} products into sheet {sheet_id} / tab '{tab}'...", flush=True)
    result = sheets.sync_products(products, sheet_id, tab=tab)
    print(
        f"Done. added={result['added']} updated={result['updated']} "
        f"total={result['total']} price_history_rows={result['history_added']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
