"""
Daily COLD catalogue sync — entry point.

Two modes (via ENRICH_MODE):
- "new" (DAILY, default): LIGHT run. Fetch only the upcoming + recently-released
  window from my-nft-tracker, detect NEW products vs the sheet, enrich only those
  cold fields from VeVe, rebuild the two cold catalogue tabs + the Marques &
  Licences page, and seed the dynamic page for first-week items. Minimal load on
  my-nft-tracker (~40-80 requests/day). The DYNAMIC data (floor / listings /
  supply for every collectible) is refreshed separately, several times a day, by
  scraper.dynamic_run.
- "all"  (BACKFILL, manual): FULL run. Scrape the whole catalogue, (re)enrich
  everything (cold + dynamic), rebuild every tab.

Env: GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID, ENRICH_MODE, WINDOW_DAYS,
     REFRESH_DYNAMIC, APIFY_PROXY_PASSWORD.
"""

from __future__ import annotations

import os
import sys
import time

from scraper.veve_scraper import scrape_catalogue, scrape_window
from scraper import sheets
from scraper import veve_detail

# Fields copied into a dynamic-page item (tracker + enrichment).
DYN_ITEM_FIELDS = [
    "market_lowestOffer", "market_totalListings", "releaseAmount",
    "veve_total_available", "veve_store_price", "sold_editions",
    "editions_in_circulation", "burned_editions", "withheld_editions",
    "store_allocation",
]


def _cat(p):
    return str(p.get("category", "")).lower()


def _key(p):
    return p.get("veve_uuid") or p.get("tracker_uuid")


def _is_recent(p, days=7):
    from scraper.sheets import _is_recent as r
    import datetime as dt
    return r(p, dt.datetime.utcnow(), days)


def _dyn_item(p):
    it = {"veve_uuid": p.get("veve_uuid"), "name": p.get("name"),
          "category": p.get("category")}
    for f in DYN_ITEM_FIELDS:
        if p.get(f) not in (None, ""):
            it[f] = p.get(f)
    return it


def main() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        print("ERROR: SHEET_ID env var is required.", file=sys.stderr)
        return 2
    enrich_mode = os.environ.get("ENRICH_MODE", "new").strip().lower()
    window_days = int(os.environ.get("WINDOW_DAYS", "8"))
    refresh_dynamic = os.environ.get("REFRESH_DYNAMIC", "true").strip().lower() != "false"

    # ---- Scrape ----
    if enrich_mode == "all":
        print("FULL scrape (backfill mode)...", flush=True)
        products = scrape_catalogue()
    else:
        print("LIGHT scrape: window (upcoming + recent) only...", flush=True)
        products = [p for p in scrape_window(days_back=window_days)
                    if p.get("veve_uuid")]
        print(f"Working set: {len(products)} products.", flush=True)

    if not products:
        print("No products harvested — aborting to protect your data.", file=sys.stderr)
        try:
            sheets.append_run_log(sheet_id, {
                "status": "FAILED_NO_DATA", "total_rows": "", "new_items": 0,
                "note": "my-nft-tracker returned no data (down/blocked?).",
            })
        except Exception as e:
            print(f"run log warning: {e}", flush=True)
        return 1

    by_uuid = {p.get("veve_uuid"): p for p in products}
    collectibles = [p for p in products if _cat(p) == "collectible" and p.get("veve_uuid")]
    comics = [p for p in products if _cat(p) == "comic" and p.get("series_uuid")]

    # ---- Enrich cold fields (NEW products only in daily; everything in backfill) ----
    if enrich_mode == "all":
        coll_targets = [p["veve_uuid"] for p in collectibles]
        comic_ids = list(dict.fromkeys(p["series_uuid"] for p in comics))
    else:
        existing = sheets.get_existing_ids(sheet_id)
        coll_targets = [p["veve_uuid"] for p in collectibles if p["veve_uuid"] not in existing]
        new_comics = [p for p in comics if p.get("veve_uuid") not in existing]
        comic_ids = list(dict.fromkeys(p["series_uuid"] for p in new_comics))
    print(f"To enrich (cold): {len(coll_targets)} collectibles + {len(comic_ids)} comics.",
          flush=True)

    if coll_targets:
        for uid, cols in veve_detail.enrich(coll_targets).items():
            if by_uuid.get(uid):
                by_uuid[uid].update({k: v for k, v in cols.items() if k != "veve_uuid"})
    if comic_ids:
        cmap = veve_detail.enrich_comics(comic_ids)
        for p in comics:
            cols = cmap.get(p.get("series_uuid"))
            if cols:
                p.update({k: v for k, v in cols.items() if k != "comic_id"})

    # ---- Refresh dynamic fields for first-week items (both categories) ----
    dyn_items = []
    if refresh_dynamic and enrich_mode != "all":
        recent_coll = [p["veve_uuid"] for p in collectibles if _is_recent(p, 7)]
        recent_comic_ids = list(dict.fromkeys(
            p["series_uuid"] for p in comics if _is_recent(p, 7)))
        print(f"First-week dynamic refresh: {len(recent_coll)} collectibles + "
              f"{len(recent_comic_ids)} comics.", flush=True)
        if recent_coll:
            for uid, cols in veve_detail.enrich_dynamic(recent_coll, is_comic=False).items():
                if by_uuid.get(uid):
                    by_uuid[uid].update(cols)
        if recent_comic_ids:
            dyn = veve_detail.enrich_dynamic(recent_comic_ids, is_comic=True)
            for p in comics:
                cols = dyn.get(p.get("series_uuid"))
                if cols:
                    p.update(cols)
        dyn_items = [_dyn_item(p) for p in products if _is_recent(p, 7)]
    elif enrich_mode == "all":
        # Backfill: enrich() / enrich_comics() already returned the dynamic fields.
        dyn_items = [_dyn_item(p) for p in products]

    # ---- Sync cold catalogue + Marques & Licences ----
    print(f"Syncing {len(products)} products into cold catalogue tabs...", flush=True)
    summary = sheets.sync_catalogue(products, sheet_id)
    try:
        sheets.append_run_log(sheet_id, summary, duration_sec=time.time() - t0)
    except Exception as e:
        print(f"run log warning: {e}", flush=True)

    # ---- Seed / refresh the dynamic page for the items we just refreshed ----
    if dyn_items:
        try:
            dsum = sheets.sync_dynamic(dyn_items, sheet_id)
            print(f"Dynamic seed: {dsum}", flush=True)
        except Exception as e:
            print(f"dynamic seed warning: {e}", flush=True)

    print(f"Done. status={summary.get('status')} total={summary.get('total_rows')} "
          f"new={summary.get('new_items')} (coll={summary.get('new_collectibles')}, "
          f"comics={summary.get('new_comics')}) upcoming={summary.get('upcoming_drops')} "
          f"brands={summary.get('brands')} licensors={summary.get('licensors')} "
          f"in {time.time()-t0:.0f}s", flush=True)

    return 0 if summary.get("status") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
