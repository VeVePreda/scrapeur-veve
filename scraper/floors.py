"""
Collectible FLOOR sync — dedicated per-type script (COLLECTIBLES only, once a day).

Floor source priority (as requested):
  1. VeVe's own floor — `floorMarketPrice` / `totalMarketListings` on
     publicCollectibleType (VeVe GraphQL). VeVe only fills this once a drop is
     SOLD OUT (totalAvailable == 0); while it's still on sale the field is null.
  2. Fallback — my-nft-tracker's `market_lowestOffer` / `market_totalListings`
     (used whenever VeVe has no floor for that collectible yet).

The chosen floor is appended, as a time series, to the shared "🟠H-PRIX" history
page via sheets.sync_dynamic (one row per change only). Edition counters are NOT
touched here — that's a separate script.

Run once a day. Env: GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID, FLOORS_MAX (test cap),
APIFY_PROXY_PASSWORD (optional egress proxy, auto-fallback to direct).
"""

from __future__ import annotations

import os
import sys
import time

from scraper import sheets
from scraper import veve_detail
from scraper.veve_scraper import scrape_catalogue


def _num(x):
    if x in (None, ""):
        return None
    try:
        f = float(str(x).replace(",", "."))
        return int(f) if f.is_integer() else f
    except (ValueError, TypeError):
        return None


def main() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        print("ERROR: SHEET_ID env var is required.", file=sys.stderr)
        return 2
    max_items = int(os.environ.get("FLOORS_MAX", "0") or "0")

    # 🌉 LE PONT (15/07) : le floor collectible peut etre CEDE au pont veille→
    # 🟠H-PRIX (jetonveve, horaire). Ici on garde le meme fichier, mais on
    # n'ecrit plus `market_lowestOffer` : une seule source par champ (le pont),
    # zero course sur _DynState. `market_totalListings` reste ecrit ici (le pont
    # ne le connait pas). FLOORS_FLOOR_SOURCE=bridge pour ceder ; "self" (defaut)
    # = comportement historique, tant que le pont n'est pas verifie.
    cede_floor = os.environ.get("FLOORS_FLOOR_SOURCE", "self").lower() == "bridge"
    print(f"Floor collectible : source = {'PONT (cede)' if cede_floor else 'floors.py'}.",
          flush=True)

    # ---- collectibles + tracker floor (fallback source) ----
    print("Listing collectibles from my-nft-tracker (fallback floor)...", flush=True)
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
                                  source="floors")
        except Exception:
            pass
        return 1

    by_uuid = {p["veve_uuid"]: p for p in colls}

    # ---- VeVe floor (priority source) ----
    veve = veve_detail.enrich_floors(list(by_uuid.keys()))

    items = []
    n_veve, n_tracker, n_none = 0, 0, 0
    for uid, p in by_uuid.items():
        v = veve.get(uid) or {}
        veve_floor = _num(v.get("veve_floor_price"))
        if veve_floor:  # VeVe fills this only when sold out -> authoritative
            floor = veve_floor
            listings = _num(v.get("veve_total_market_listings"))
            n_veve += 1
        else:           # still on sale (or VeVe miss) -> tracker fallback
            floor = _num(p.get("market_lowestOffer"))
            listings = _num(p.get("market_totalListings"))
            if floor is not None:
                n_tracker += 1
            else:
                n_none += 1
        item = {"veve_uuid": uid, "name": p.get("name"), "category": "collectible"}
        if floor is not None and not cede_floor:   # 🌉 cede -> le pont ecrit le floor
            item["market_lowestOffer"] = floor
        if listings is not None:
            item["market_totalListings"] = listings
        if len(item) > 3:                          # ni floor ni listings -> rien a ecrire
            items.append(item)

    # ---- append changes to the shared 🟠H-PRIX history ----
    summary = sheets.sync_dynamic(items, sheet_id)
    summary["floor_from_veve"] = n_veve
    summary["floor_from_tracker"] = n_tracker
    summary["floor_missing"] = n_none
    summary["duration"] = f"{time.time() - t0:.0f}s"
    try:
        sheets.append_run_log(sheet_id, summary, source="floors")
    except Exception as e:
        print(f"run log warning: {e}", flush=True)

    print(f"Done. status={summary.get('status')} "
          f"veve={n_veve} tracker={n_tracker} missing={n_none} "
          f"appended={summary.get('rows_appended')} "
          f"in {time.time()-t0:.0f}s", flush=True)
    return 0 if summary.get("status") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
