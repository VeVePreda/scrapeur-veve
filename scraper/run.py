"""
Entry point.

Two modes (via ENRICH_MODE):
- "new" (DAILY, default): LIGHT run. Fetch only the upcoming + recently-released window
  from my-nft-tracker, plus all collectibles (for floor tracking). Detect NEW products
  vs the sheet, enrich only those from VeVe, refresh sold/in-circulation only for items
  in their first week, and sync. Minimal load on my-nft-tracker (~150 requests/day).
- "all"  (BACKFILL, manual): FULL run. Scrape the whole catalogue and (re)enrich everything.

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


def _cat(p):
    return str(p.get("category", "")).lower()


def _key(p):
    return p.get("veve_uuid") or p.get("tracker_uuid")


def _is_recent(p, days=7):
    from scraper.sheets import _is_recent as r
    import datetime as dt
    return r(p, dt.datetime.utcnow(), days)


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
        print("LIGHT scrape: window (upcoming + recent) + all collectibles...", flush=True)
        window = scrape_window(days_back=window_days)
        colls = scrape_catalogue(category="collectible")   # floor tracking for all collectibles
        combined = {_key(p): p for p in colls}
        for p in window:
            combined[_key(p)] = p
        products = [p for p in combined.values() if p.get("veve_uuid")]
        print(f"Combined working set: {len(products)} products "
              f"({len(window)} window + {len(colls)} collectibles).", flush=True)

    if not products:
        print("No products harvested — aborting to protect your data.", file=sys.stderr)
        try:
            sheets.append_run_log(sheet_id, {
                "status": "FAILED_NO_DATA", "total_rows": "", "new_items": 0,
                "updated_items": 0, "new_collectibles": 0, "new_comics": 0,
                "upcoming_drops": 0, "price_history_added": 0,
                "editions_history_added": 0, "new_item_names": [],
                "note": "my-nft-tracker returned no data (down/blocked?).",
            })
        except Exception as e:
            print(f"run log warning: {e}", flush=True)
        return 1

    by_uuid = {p.get("veve_uuid"): p for p in products}
    collectibles = [p for p in products if _cat(p) == "collectible" and p.get("veve_uuid")]
    comics = [p for p in products if _cat(p) == "comic" and p.get("series_uuid")]

    # ---- Enrich NEW products only (description & other VeVe-only fields) ----
    if enrich_mode == "all":
        coll_targets = [p["veve_uuid"] for p in collectibles]
        comic_ids = list(dict.fromkeys(p["series_uuid"] for p in comics))
    else:
        existing = sheets.get_existing_ids(sheet_id)
        coll_targets = [p["veve_uuid"] for p in collectibles if p["veve_uuid"] not in existing]
        new_comics = [p for p in comics if p.get("veve_uuid") not in existing]
        comic_ids = list(dict.fromkeys(p["series_uuid"] for p in new_comics))
    print(f"New to enrich: {len(coll_targets)} collectibles + {len(comic_ids)} comics.", flush=True)

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

    # ---- Refresh sold / in-circulation ONLY for first-week items ----
    if refresh_dynamic and enrich_mode != "all":
        recent_coll = [p["veve_uuid"] for p in collectibles if _is_recent(p, 7)]
        recent_comic_ids = list(dict.fromkeys(
            p["series_uuid"] for p in comics if _is_recent(p, 7)))
        print(f"First-week refresh: {len(recent_coll)} collectibles + "
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

    # ---- Sync + logs ----
    print(f"Syncing {len(products)} products into "
          f"'{sheets.COMICS_TAB}' / '{sheets.COLLECT_TAB}'...", flush=True)
    summary = sheets.sync_products(products, sheet_id)
    try:
        sheets.append_run_log(sheet_id, summary, duration_sec=time.time() - t0)
    except Exception as e:
        print(f"run log warning: {e}", flush=True)

    print(f"Done. status={summary.get('status')} total={summary.get('total_rows')} "
          f"new={summary.get('new_items')} (coll={summary.get('new_collectibles')}, "
          f"comics={summary.get('new_comics')}) upcoming={summary.get('upcoming_drops')} "
          f"price_hist+={summary.get('price_history_added')} "
          f"editions_hist+={summary.get('editions_history_added')} "
          f"in {time.time()-t0:.0f}s", flush=True)

    return 0 if summary.get("status") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
