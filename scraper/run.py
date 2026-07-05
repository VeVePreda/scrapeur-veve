"""
Entry point: scrape the VeVe catalogue (my-nft-tracker), enrich collectibles with
VeVe's own detail fields, and sync everything into the Google Sheet.

Environment variables (GitHub Actions secrets / workflow env):
  GOOGLE_SERVICE_ACCOUNT_JSON  -> service-account JSON (string)         [required]
  SHEET_ID                     -> spreadsheet id                        [required]
  SHEET_TAB                    -> catalogue tab, default "Catalogue"
  ENRICH_MODE                  -> "new" (default) | "all" | "none"
                                  new  = enrich only collectibles not yet enriched
                                  all  = re-enrich every collectible (backfill / refresh)
                                  none = skip VeVe enrichment
  APIFY_PROXY_PASSWORD         -> if set, VeVe calls go via Apify residential proxy
"""

from __future__ import annotations

import os
import sys

from scraper.veve_scraper import scrape_catalogue
from scraper import sheets
from scraper import veve_detail


def main() -> int:
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        print("ERROR: SHEET_ID env var is required.", file=sys.stderr)
        return 2
    tab = os.environ.get("SHEET_TAB", "Catalogue")
    enrich_mode = os.environ.get("ENRICH_MODE", "new").strip().lower()

    print("Starting VeVe catalogue scrape...", flush=True)
    products = scrape_catalogue()
    if not products:
        print("No products harvested — aborting sheet write to avoid clearing data.", file=sys.stderr)
        return 1

    # ---- VeVe enrichment (collectibles only) ----
    if enrich_mode != "none":
        collectibles = [
            p for p in products
            if str(p.get("category", "")).lower() == "collectible" and p.get("veve_uuid")
        ]
        if enrich_mode == "all":
            targets = [p["veve_uuid"] for p in collectibles]
        else:  # "new": skip those already enriched in the sheet
            already = sheets.get_enriched_ids(sheet_id, tab)
            targets = [p["veve_uuid"] for p in collectibles if p["veve_uuid"] not in already]
        print(f"Enrichment mode={enrich_mode}: {len(targets)} collectibles to enrich "
              f"(of {len(collectibles)} total collectibles).", flush=True)
        if targets:
            enrich_map = veve_detail.enrich(targets)
            by_uuid = {p.get("veve_uuid"): p for p in products}
            for uid, cols in enrich_map.items():
                prod = by_uuid.get(uid)
                if prod:
                    prod.update({k: v for k, v in cols.items() if k != "veve_uuid"})
    else:
        print("Enrichment skipped (ENRICH_MODE=none).", flush=True)

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
