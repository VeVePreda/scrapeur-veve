"""
Comic STORE PRICE sync — script dedie par type de donnee (COMICS, 1x/jour).

Pourquoi : le revenue des drops comics (mints x prix store) valait 0 car aucun
prix comic n'etait collecte. Les pages catalogue de my-nft-tracker exposent
`storePrice` pour les comics -> une passe GET quotidienne sur le catalogue
comics (~16k fiches / 24 par page ~ 675 pages, ~6-8 min) suffit.

Champs suivis pour les comics : `veve_store_price` + `market_lowestOffer` /
`market_totalListings` (floor quotidien, demande Preda 2026-07-09 — un seul
releve par jour, memes donnees que le prix store donc zero requete en plus).
Les lignes atterrissent dans 🟠H-PRIX via sheets.sync_dynamic, cle = le MEME
veve_uuid que 🟢C-COMICS (join direct). NB : le floor des COLLECTIBLES reste
la propriete exclusive de floors.py (regle anti-conflit) — ici on n'ecrit que
des uuids comics, aucun chevauchement.

Env : GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID, COMIC_PRICES_MAX (cap de test).
"""

from __future__ import annotations

import os
import sys
import time

from scraper import sheets
from scraper.veve_scraper import scrape_catalogue

# Garde-fou : ~16 100 comics attendus ; si la recolte est tres en-dessous,
# on n'ecrit rien (protege l'etat _DynState d'une recolte partielle).
EXPECTED_MIN = 8000


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
    max_items = int(os.environ.get("COMIC_PRICES_MAX", "0") or "0")

    print("Listing comics from my-nft-tracker (store prices)...", flush=True)
    comics = [p for p in scrape_catalogue(category="comic",
                                          limit_total=max_items or None)
              if p.get("veve_uuid")]
    floor_expected = 1 if max_items else EXPECTED_MIN
    if len(comics) < floor_expected:
        print(f"Only {len(comics)} comics harvested (< {floor_expected}) — "
              "aborting to protect your data.", file=sys.stderr)
        try:
            sheets.append_run_log(sheet_id,
                                  {"status": "FAILED_NO_DATA",
                                   "note": f"tracker returned {len(comics)} comics."},
                                  source="comic_prices")
        except Exception:
            pass
        return 1

    items = []
    n_price, n_floor, n_empty = 0, 0, 0
    for p in comics:
        price = _num(p.get("storePrice"))
        floor = _num(p.get("market_lowestOffer"))
        listings = _num(p.get("market_totalListings"))
        it = {"veve_uuid": p["veve_uuid"], "name": p.get("name"),
              "category": "comic"}
        if price is not None:
            it["veve_store_price"] = price
            n_price += 1
        if floor is not None:
            it["market_lowestOffer"] = floor
            n_floor += 1
        if listings is not None:
            it["market_totalListings"] = listings
        if len(it) == 3:      # ni prix ni floor -> rien a ecrire
            n_empty += 1
            continue
        items.append(it)

    summary = sheets.sync_dynamic(items, sheet_id)
    summary["comics_priced"] = n_price
    summary["comics_floor"] = n_floor
    summary["comics_empty"] = n_empty
    summary["duration"] = f"{time.time() - t0:.0f}s"
    try:
        sheets.append_run_log(sheet_id, summary, source="comic_prices")
    except Exception as e:
        print(f"run log warning: {e}", flush=True)

    print(f"Done. status={summary.get('status')} priced={n_price} "
          f"floor={n_floor} empty={n_empty} "
          f"appended={summary.get('rows_appended')} "
          f"in {time.time()-t0:.0f}s", flush=True)
    return 0 if summary.get("status") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
