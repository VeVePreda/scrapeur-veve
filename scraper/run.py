"""
Entry point: scrape the VeVe catalogue (my-nft-tracker), enrich collectibles & comics
with VeVe detail fields, refresh variable fields daily, and sync into the Google Sheet.

Environment variables:
  GOOGLE_SERVICE_ACCOUNT_JSON  -> service-account JSON (string)         [required]
  SHEET_ID                     -> spreadsheet id                        [required]
  SHEET_TAB                    -> catalogue tab, default "Catalogue"
  ENRICH_MODE                  -> "new" (default) | "all" | "none"
  REFRESH_DYNAMIC              -> "true" (default) | "false"
                                  When true and ENRICH_MODE=new, re-fetch the variable
                                  fields (sold / in-circulation / burned / withheld /
                                  available) for the whole catalogue each run, so
                                  EditionsHistory can track them over time.
  APIFY_PROXY_PASSWORD         -> optional Apify residential proxy (auto-fallback to direct)
"""

from __future__ import annotations

import os
import sys
import time

from scraper.veve_scraper import scrape_catalogue
from scraper import sheets
from scraper import veve_detail


def _cat(p):
    return str(p.get("category", "")).lower()


def main() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        print("ERROR: SHEET_ID env var is required.", file=sys.stderr)
        return 2
    tab = os.environ.get("SHEET_TAB", "Catalogue")
    enrich_mode = os.environ.get("ENRICH_MODE", "new").strip().lower()
    refresh_dynamic = os.environ.get("REFRESH_DYNAMIC", "true").strip().lower() != "false"

    print("Starting VeVe catalogue scrape...", flush=True)
    products = scrape_catalogue()
    if not products:
        print("No products harvested — aborting to protect your data.", file=sys.stderr)
        try:
            sheets.append_run_log(sheet_id, {
                "status": "FAILED_NO_DATA", "total_rows": "", "new_items": 0,
                "updated_items": 0, "new_collectibles": 0, "new_comics": 0,
                "upcoming_this_week": 0, "price_history_added": 0,
                "editions_history_added": 0, "new_item_names": [],
                "note": "my-nft-tracker returned no data (down/blocked?).",
            })
        except Exception as e:
            print(f"run log warning: {e}", flush=True)
        return 1

    by_uuid = {p.get("veve_uuid"): p for p in products}
    collectibles = [p for p in products if _cat(p) == "collectible" and p.get("veve_uuid")]
    comics = [p for p in products if _cat(p) == "comic" and p.get("series_uuid")]

    # ---- Static enrichment (description, edition type, drop info, etc.) ----
    if enrich_mode != "none":
        already = sheets.get_enriched_ids(sheet_id, tab) if enrich_mode != "all" else set()
        coll_targets = [p["veve_uuid"] for p in collectibles
                        if enrich_mode == "all" or p["veve_uuid"] not in already]
        comic_todo = [p for p in comics
                      if enrich_mode == "all" or p.get("veve_uuid") not in already]
        comic_ids = list(dict.fromkeys(p["series_uuid"] for p in comic_todo))
        print(f"Enrichment mode={enrich_mode}: {len(coll_targets)} collectibles + "
              f"{len(comic_ids)} unique comics to enrich.", flush=True)

        if coll_targets:
            for uid, cols in veve_detail.enrich(coll_targets).items():
                if by_uuid.get(uid):
                    by_uuid[uid].update({k: v for k, v in cols.items() if k != "veve_uuid"})
        if comic_ids:
            cmap = veve_detail.enrich_comics(comic_ids)
            applied = 0
            for p in comics:
                cols = cmap.get(p.get("series_uuid"))
                if cols:
                    p.update({k: v for k, v in cols.items() if k != "comic_id"})
                    applied += 1
            print(f"Applied comic enrichment to {applied} rarity rows.", flush=True)

    # ---- Daily refresh of VARIABLE fields for the whole catalogue ----
    # (Skipped for mode=all, which already fetched fresh values above.)
    if refresh_dynamic and enrich_mode == "new":
        coll_ids = [p["veve_uuid"] for p in collectibles]
        comic_ids_all = list(dict.fromkeys(p["series_uuid"] for p in comics))
        dyn_coll = veve_detail.enrich_dynamic(coll_ids, is_comic=False)
        for uid, cols in dyn_coll.items():
            if by_uuid.get(uid):
                by_uuid[uid].update(cols)
        dyn_comic = veve_detail.enrich_dynamic(comic_ids_all, is_comic=True)
        for p in comics:
            cols = dyn_comic.get(p.get("series_uuid"))
            if cols:
                p.update(cols)

    # ---- Sync + logs ----
    print(f"Syncing {len(products)} products into '{tab}'...", flush=True)
    summary = sheets.sync_products(products, sheet_id, tab=tab)
    try:
        sheets.append_run_log(sheet_id, summary, duration_sec=time.time() - t0)
    except Exception as e:
        print(f"run log warning: {e}", flush=True)

    print(f"Done. status={summary.get('status')} total={summary.get('total_rows')} "
          f"new={summary.get('new_items')} (coll={summary.get('new_collectibles')}, "
          f"comics={summary.get('new_comics')}) upcoming_this_week={summary.get('upcoming_this_week')} "
          f"price_hist+={summary.get('price_history_added')} "
          f"editions_hist+={summary.get('editions_history_added')} "
          f"in {time.time()-t0:.0f}s", flush=True)

    if summary.get("status") != "OK":
        print(f"WARNING: {summary.get('note','non-OK status')}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
