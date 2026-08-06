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

# Fields copied into a dynamic-page item (supply / editions only).
# FLOOR (market_lowestOffer / market_totalListings) is intentionally NOT here:
# it is owned by scraper.floors (VeVe floor, tracker fallback, once a day). If we
# emitted a tracker floor here too, the two would overwrite each other in 🟠H-PRIX
# and create spurious floor changes.
DYN_ITEM_FIELDS = [
    "releaseAmount",
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
        # 🔴 LA COUVERTURE EST UNE PROPRIETE DE LA VARIANTE, PAS DU COMIC
        # (01/08/2026). Ces colonnes sont de niveau COMIC et s'appliquent
        # telles quelles aux 5 lignes de rarete — c'est voulu pour les totaux
        # d'editions. Mais `image_url` valait `media.edges[0]` : toutes les
        # raretes recevaient la couverture de base. Le SECRET_RARE de
        # « Retellings #1 (1982) » n'affichait pas la sienne.
        # ⭐ L'URL PORTE le veve_uuid de la variante
        # (`comic_cover.<veve_uuid>.<image>.full.jpeg`), donc on RECONNAIT la
        # bonne au lieu de la fabriquer — le second identifiant de l'adresse
        # est imprevisible, une URL construite serait une URL inventee.
        apparies = 0
        for p in comics:
            cols = cmap.get(p.get("series_uuid"))
            if not cols:
                continue
            p.update({k: v for k, v in cols.items() if k != "comic_id"})
            uid = str(p.get("veve_uuid") or "").strip().lower()
            propre = ""
            if uid:
                for u in str(cols.get("comic_media_urls") or "").split("\n"):
                    if uid in u.lower():
                        propre = u
                        break
            if propre:
                p["image_url"] = propre
                apparies += 1
            # ⛔ SINON ON GARDE LA COUVERTURE DE BASE, on ne vide pas le champ.
            # Une fiche sans image est un trou visible ; une fiche avec la
            # couverture de la serie est imprecise mais lisible. On degrade,
            # on ne casse pas.
        # ⭐ ON JOURNALISE LE TAUX. Un appariement qui tomberait a zero (VeVe
        # change la forme de ses URL) redonnerait exactement le comportement
        # d'avant — silencieusement, et avec des images plausibles. C'est ce
        # chiffre, pas une intuition, qui le dira.
        #
        # 🔴🔴 CE TAUX EST BAS PAR NATURE, ET CE N'EST PAS UN DEFAUT A REPARER
        # (mesure du 06/08/2026, lot 81). `641/16597` = 3,9 % avait ete pris
        # pour un appariement casse. Il ne l'est pas : `media` ne CONTIENT pas
        # les couvertures des raretes. Sur 12 series ayant 4 ou 5 couvertures
        # distinctes ON-CHAIN, l'API en a rendu 0 a 2, et 3 seulement portaient
        # un uuid de variante ; sur 975 lignes tirees au sort, 3,4 %. Le champ rend surtout des `comic_type_image.
        # <serie>`, c'est-a-dire l'image de la SERIE.
        # ⭐⭐⭐ **UN COMPTEUR QUI MESURE UNE SOURCE QUI N'A PAS LA DONNEE
        # RESSEMBLE A UN BUG ET N'EN EST PAS UN.** Il plafonne, il ne saigne
        # pas. La donnee, elle, existe : la CHAINE porte 9 065 couvertures de
        # comics, chacune avec le veve_uuid de sa piece — c'est
        # `couvertures_chaine` qui les pose, dans `sheets._normalise`.
        # ⛔ Ne pas relancer de chantier d'appariement sur ce chiffre : le
        # plancher qui compte est celui du log 🖼️, pas celui-ci.
        print(f"Comic covers matched by veve_uuid: {apparies}/{len(comics)} "
              f"(plafond attendu : `media` ne porte pas les couvertures de "
              f"rarete — la chaine les pose, cf. log 🖼️).", flush=True)

    # ---- Seed dynamic history for first-week COLLECTIBLES (comics excluded) ----
    # Dynamic data is COLLECTIBLES-ONLY, tracked as history in 'Données Dynamiques'.
    dyn_items = []
    if refresh_dynamic and enrich_mode != "all":
        recent_coll = [p["veve_uuid"] for p in collectibles if _is_recent(p, 7)]
        print(f"First-week collectible dynamic refresh: {len(recent_coll)}.", flush=True)
        if recent_coll:
            for uid, cols in veve_detail.enrich_dynamic(recent_coll, is_comic=False).items():
                if by_uuid.get(uid):
                    by_uuid[uid].update(cols)
        dyn_items = [_dyn_item(p) for p in collectibles if _is_recent(p, 7)]
    elif enrich_mode == "all":
        # Backfill: enrich() already returned the dynamic fields for collectibles.
        dyn_items = [_dyn_item(p) for p in collectibles]

    # ---- Brand / licensor logos (isolated, fault-tolerant) ----
    try:
        have = sheets.get_brand_image_uuids(sheet_id)
        reps = {}
        cid_prod = {}   # collectible representatif -> produit tracker (pour ses uuids)
        for p in collectibles:
            cid = p.get("veve_uuid")
            for uk in ("brand_uuid", "licensor_uuid"):
                u = str(p.get(uk, "") or "").strip()
                if cid and u and u not in have and u not in reps:
                    reps[u] = cid
                    cid_prod[str(cid)] = p
        if reps:
            media = veve_detail.enrich_brand_media(list(dict.fromkeys(reps.values())))
            img_rows, seen = [], set()
            # Cle = uuid TRACKER du produit representatif (celui de 🟤C-MARQUE),
            # PAS l'id GraphQL VeVe renvoye dans media (referentiel different —
            # meme bug que logos.py, corrige le 2026-07-09).
            for cid, m in media.items():
                p = cid_prod.get(str(cid)) or {}
                for kind, uk, nk, ik in (
                        ("brand", "brand_uuid", "brand_name", "brand_image"),
                        ("licensor", "licensor_uuid", "licensor_name", "licensor_image")):
                    u = str(p.get(uk, "") or "").strip()
                    img = m.get(ik)
                    if u and img and u not in seen and u not in have:
                        img_rows.append([u, kind, m.get(nk, "") or "", img])
                        seen.add(u)
            added = sheets.write_brand_images(sheet_id, img_rows)
            print(f"Brand/licensor logos added: {added}.", flush=True)
    except Exception as e:
        print(f"brand media warning: {e}", flush=True)

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
