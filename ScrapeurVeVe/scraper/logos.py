"""
Brand / licensor LOGO sync — dedicated per-type script (once a day, cheap).

What it does
------------
For each BRAND that doesn't yet have a logo recorded, it fetches one representative
collectible of that brand from VeVe GraphQL and reads `brand.landscapeImage`
(the real logo field — confirmed live). Logos are stored in the hidden
"_BrandImages" tab via sheets.write_brand_images; the daily catalogue run then
merges them into the "🟤C-MARQUE" reference page (existing behaviour, no change
needed there).

Only brands WITHOUT a logo yet are looked up, so the first run fetches all brands
and later runs are essentially free (just any newly-seen brand). Collectibles only.

Licensor logos are NOT fetched here: `publicCollectibleType` exposes only the
licensor's id/name, not its image. That needs the /brands licence-page query
(captured separately); once available it can be added as a second pass.

Run once a day. Env: GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID, LOGOS_MAX (test cap),
APIFY_PROXY_PASSWORD (optional egress proxy, auto-fallback to direct).
"""

from __future__ import annotations

import os
import sys
import time

from scraper import sheets
from scraper import veve_detail
from scraper.veve_scraper import scrape_catalogue


def main() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        print("ERROR: SHEET_ID env var is required.", file=sys.stderr)
        return 2
    max_items = int(os.environ.get("LOGOS_MAX", "0") or "0")

    # Brands that already have a logo recorded -> skip (never re-fetch).
    have = sheets.get_brand_image_uuids(sheet_id)

    print("Listing collectibles from my-nft-tracker (one per brand)...", flush=True)
    colls = scrape_catalogue(category="collectible", limit_total=max_items or None)

    # One representative collectible uuid per brand still missing a logo.
    reps = {}  # brand_uuid -> representative veve_uuid
    for p in colls:
        b = str(p.get("brand_uuid") or "").strip()
        cid = str(p.get("veve_uuid") or "").strip()
        if b and cid and b not in have and b not in reps:
            reps[b] = cid

    if not reps:
        print("No new brand logo to fetch — all known brands already have one.",
              flush=True)
        try:
            sheets.append_run_log(sheet_id,
                                  {"status": "OK", "new_logos": 0,
                                   "note": "no new brand"}, source="logos")
        except Exception:
            pass
        return 0

    print(f"Fetching logos for {len(reps)} new brand(s)...", flush=True)
    media = veve_detail.enrich_brand_media(list(reps.values()))

    rows = []
    seen = set()
    for _cid, m in media.items():
        bu = str(m.get("brand_uuid") or "").strip()
        img = m.get("brand_image")
        if bu and img and bu not in seen:
            rows.append([bu, "Marque", m.get("brand_name") or "", img])
            seen.add(bu)

    added = sheets.write_brand_images(sheet_id, rows)
    summary = {"status": "OK", "brands_probed": len(reps),
               "logos_found": len(rows), "new_logos": added,
               "duration": f"{time.time() - t0:.0f}s"}
    try:
        sheets.append_run_log(sheet_id, summary, source="logos")
    except Exception as e:
        print(f"run log warning: {e}", flush=True)

    print(f"Done. found={len(rows)} new={added} in {time.time()-t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
