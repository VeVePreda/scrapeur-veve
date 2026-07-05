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

    # ---- VeVe enrichment (collectibles + comics) ----
    if enrich_mode != "none":
        already = sheets.get_enriched_ids(sheet_id, tab) if enrich_mode != "all" else set()

        def cat(p):
            return str(p.get("category", "")).lower()

        # Collectibles: enrich by the VeVe collectible id (== veve_uuid).
        collectibles = [p for p in products if cat(p) == "collectible" and p.get("veve_uuid")]
        coll_targets = [
            p["veve_uuid"] for p in collectibles
            if enrich_mode == "all" or p["veve_uuid"] not in already
        ]

        # Comics: the VeVe comic id == tracker series.externalReference (our series_uuid).
        # One comic groups all its rarity rows, so we enrich per unique comic id and
        # apply the comic-level fields to every rarity row sharing that id.
        comics = [p for p in products if cat(p) == "comic" and p.get("series_uuid")]
        comic_products_todo = [
            p for p in comics
            if enrich_mode == "all" or p.get("veve_uuid") not in already
        ]
        comic_ids = list(dict.fromkeys(p["series_uuid"] for p in comic_products_todo))

        print(f"Enrichment mode={enrich_mode}: {len(coll_targets)} collectibles + "
              f"{len(comic_ids)} unique comics to enrich "
              f"(collectibles total={len(collectibles)}, comics total={len(comics)}).",
              flush=True)

        by_uuid = {p.get("veve_uuid"): p for p in products}

        if coll_targets:
            coll_map = veve_detail.enrich(coll_targets)
            for uid, cols in coll_map.items():
                prod = by_uuid.get(uid)
                if prod:
                    prod.update({k: v for k, v in cols.items() if k != "veve_uuid"})

        if comic_ids:
            comic_map = veve_detail.enrich_comics(comic_ids)
            applied = 0
            for p in comics:
                cols = comic_map.get(p.get("series_uuid"))
                if cols:
                    p.update({k: v for k, v in cols.items() if k != "comic_id"})
                    applied += 1
            print(f"Applied comic enrichment to {applied} rarity rows.", flush=True)
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
