"""
Dynamic data refresh (COLLECTIBLES) — entry point.

Runs several times a day (much more often than the daily cold catalogue). It
refreshes the fast-moving fields for every collectible and appends them, as a
time series, to the single append-only "Données Dynamiques" history page (a row
is added only when a value changed):

    - floor (market_lowestOffer) & listings  ...  from my-nft-tracker
    - store price, supply, edition counters   ...  from VeVe GraphQL

Comics are NOT tracked dynamically at all — this keeps the request volume
discreet and the history focused on collectibles.

Volume: ~2,600 GraphQL calls + ~110 tracker pages per run. On GitHub Actions this
is a few minutes; mind the free-tier minutes budget (see the workflow file).

Env: GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID, DYNAMIC_MAX (test cap),
     APIFY_PROXY_PASSWORD.
"""

from __future__ import annotations

import os
import sys
import time

from scraper.veve_scraper import scrape_catalogue
from scraper import sheets
from scraper import veve_detail

# FLOOR (market_lowestOffer / market_totalListings) is owned by scraper.floors
# now (VeVe floor, tracker fallback, once a day) — NOT emitted here, otherwise the
# tracker floor would fight the VeVe floor in 🟠H-PRIX. This step only refreshes
# supply / edition counters.
DYN_ITEM_FIELDS = [
    "releaseAmount",
    "veve_total_available", "veve_store_price", "sold_editions",
    "editions_in_circulation", "burned_editions", "withheld_editions",
    "store_allocation",
]


def _item(p):
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
    max_items = int(os.environ.get("DYNAMIC_MAX", "0") or "0")

    # ---- tracker: floor / listings / release amount for all collectibles ----
    print("Scraping collectibles from my-nft-tracker (floor / listings)...", flush=True)
    colls = [p for p in scrape_catalogue(category="collectible",
                                         limit_total=max_items or None)
             if p.get("veve_uuid")]
    if not colls:
        print("No collectibles harvested — aborting to protect your data.",
              file=sys.stderr)
        try:
            sheets.append_run_log(sheet_id,
                                  {"status": "FAILED_NO_DATA",
                                   "note": "tracker returned no collectibles."},
                                  source="dynamic")
        except Exception:
            pass
        return 1

    by_uuid = {p["veve_uuid"]: p for p in colls}

    # ---- VeVe GraphQL: store price / supply / edition counters ----
    # These change slowly, so by default we DON'T hit GraphQL on the frequent
    # (3-hourly) runs — floor/listings from the tracker are enough. A once-a-day
    # run with DYNAMIC_WITH_EDITIONS=true refreshes the edition counters.
    with_editions = os.environ.get("DYNAMIC_WITH_EDITIONS", "false").strip().lower() == "true"
    uuids = list(by_uuid.keys())
    if with_editions:
        print(f"Refreshing edition counters for {len(uuids)} collectibles via VeVe GraphQL...",
              flush=True)
        for uid, cols in veve_detail.enrich_dynamic(uuids, is_comic=False).items():
            if by_uuid.get(uid):
                by_uuid[uid].update(cols)
    else:
        print("Floor/listings only (tracker) — skipping GraphQL editions this run "
              "(set DYNAMIC_WITH_EDITIONS=true for the daily edition refresh).", flush=True)

    items = [_item(p) for p in colls]

    # ---- write the combined dynamic page + history logs ----
    summary = sheets.sync_dynamic(items, sheet_id)
    summary["duration"] = f"{time.time() - t0:.0f}s"
    try:
        sheets.append_run_log(sheet_id, summary, source="dynamic")
    except Exception as e:
        print(f"run log warning: {e}", flush=True)

    print(f"Done. status={summary.get('status')} "
          f"tracked={summary.get('tracked_collectibles')} "
          f"appended={summary.get('rows_appended')} "
          f"pruned={summary.get('rows_pruned')} "
          f"in {time.time()-t0:.0f}s", flush=True)
    return 0 if summary.get("status") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
