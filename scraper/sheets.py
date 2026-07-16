"""
Google Sheets sync for the VeVe catalogue.

Architecture (v5 — 2026-07-07)
------------------------------
The sheet now separates COLD data (rarely/never changes — refreshed once a day,
only to add brand-new drops) from DYNAMIC data (supply / listings / floor —
refreshed several times a day).

Tabs maintained:

1. "🔵C-COLLECTIBLE" / "🟢C-COMICS"
        — COLD catalogue, one row per product UUID, physically split by category.
          Only stable fields (identity, rarity, series/brand/licensor, description,
          drop method, market fee…). Rows are never deleted (we always start from
          what's already there), so a source outage can't wipe your data.
2. "Marques & Licences"
        — COLD reference page: one row per brand and per licensor, with product
          counts. Rebuilt each day from the catalogue.
3. "Données Dynamiques"
        — DYNAMIC snapshot, one COMBINED page (collectibles + comics), one row per
          product with the variable fields (floor, listings, supply, editions…).
          Collectible rows are refreshed several times a day by dynamic_run.py;
          comic rows are refreshed once a day (first-week items) by run.py.
4. "PriceHistory"   — append-only floor-price log (COLLECTIBLES only), one row per change.
5. "EditionsHistory"— append-only log of the edition counters, one row per change.
6. "Logs"           — unified run log (catalogue / dynamic / pseudos / chain).

NOTE (market_fee): VeVe returns marketFee in tenths of a percent (e.g. 85 -> 8.5%).
We store it formatted as a percentage string. If VeVe's raw scale ever differs,
change FEE_DIVISOR below (single source of truth).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
from typing import Any, Dict, List, Optional

import gspread
from google.oauth2.service_account import Credentials

from scraper.veve_scraper import build_veve_url

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ---------------------------------------------------------------------------
# Column model
# ---------------------------------------------------------------------------
# COLD columns kept in each catalogue tab (order = display order).
COLLECTIBLE_COLD = [
    "veve_uuid", "name", "category", "edition_type", "rarity", "releaseDate",
    "daily_mcp_points", "gemsPerMcp", "veve_series_name", "series_uuid",
    "veve_brand", "brand_uuid", "veve_licensor", "licensor_uuid",
    "veve_url", "image_url", "tracker_uuid", "description", "special_edition",
    "market_fee", "supply", "store_price_gems",
    "first_available_edition", "is_blindbox", "drop_method",
    # ATH/ATL du floor (source : allTimeHighest/Lowest de MyNftTracker, deja
    # collecte gratuitement par veve_scraper). Ajoutees EN FIN pour ne rien
    # decaler.
    "atl", "atl_date", "ath", "ath_date",
]
COMICS_COLD = [
    "veve_uuid", "name", "category", "edition_type", "rarity", "releaseDate",
    "daily_mcp_points", "noMarketListing", "gemsPerMcp", "veve_series_name",
    "series_uuid", "veve_brand", "brand_uuid", "veve_licensor", "licensor_uuid",
    "veve_url", "image_url", "tracker_uuid", "description", "drop_method",
    "market_fee", "supply", "supply_rarete", "store_price_gems",
    "veve_exclusive", "first_available_edition", "start_year",
    "atl", "atl_date", "ath", "ath_date",
]
# ---------------------------------------------------------------------------
# Colonnes FROIDES ajoutees le 2026-07-13 (chantier "page Classement").
#
#   supply           = nombre total d'editions emises (GraphQL `totalIssued`).
#                      COMICS : c'est le total de la SERIE (toutes raretes
#                      confondues), repete sur chaque ligne de rarete — c'est
#                      exactement le "Supply" des cartes Discord de Preda.
#                      COLLECTIBLES : le supply de l'item.
#   store_price_gems = prix boutique en gems (GraphQL `storePrice`, 1 gem ~ 1 $).
#   veve_exclusive   = TRUE si la description annonce une cover exclusive VeVe.
#
# PAS de colonne MCP : le cout en points de l'acces prioritaire est CONSTANT
# (5 000, confirme par Preda le 13/07) et VeVe ne l'expose nulle part (30 noms de
# champs sondes sur publicComicType/publicCollectibleType : "Invalid request").
# Une colonne qui repete 18 700 fois la meme constante ne vaut pas une colonne.
#
# Ces valeurs etaient DEJA collectees (veve_detail.COMIC_QUERY / _map_node) puis
# JETEES par DROP_COLUMNS juste avant l'ecriture. On les recopie desormais dans
# des colonnes froides dediees ; DROP_COLUMNS continue de jeter les champs bruts
# (`rarity_editions`, `veve_store_price`) qui, eux, appartiennent a 🟠H-PRIX.
# ---------------------------------------------------------------------------
NEW_COLD_COLUMNS = ["supply", "supply_rarete", "store_price_gems", "veve_exclusive"]
# Operational bookkeeping columns appended after the cold columns (needed by the
# pipeline: new-drop detection, ordering, enrichment tracking).
BOOKKEEPING = ["veve_enriched_at", "first_seen", "last_seen"]

# Columns that must never reach the sheet (duplicates or moved to the dynamic page).
DROP_COLUMNS = {
    # legacy empties
    "provider", "series_edition", "licensor_fee", "isEcl", "image_cloudflare",
    "season",
    # duplicates folded into veve_* / edition_type
    "series_name", "brand_name", "licensor_name", "edition",
    "storePrice", "availableAmount", "drop_date", "rarity_editions",
    "veve_comic_name",
    # derived elsewhere (another sheet)
    "allTimeLow", "allTimeHigh", "change_1d_pct", "change_7d_pct", "change_30d_pct",
    # dynamic fields (live on the dynamic page, not in the cold catalogue)
    "market_lowestOffer", "market_totalListings", "releaseAmount",
    "veve_total_available", "veve_store_price", "sold_editions",
    "editions_in_circulation", "burned_editions", "withheld_editions",
    "store_allocation",
}

FIRST_SEEN = "first_seen"
LAST_SEEN = "last_seen"
KEY_COLUMN = "veve_uuid"

FEE_DIVISOR = 10.0  # VeVe marketFee is in tenths of a percent (85 -> 8.5%)

# Physical catalogue split (one tab per category) + legacy tab (migrated then deleted)
COMICS_TAB = "🟢C-COMICS"
COLLECT_TAB = "🔵C-COLLECTIBLE"
CATALOGUE_TABS = (COMICS_TAB, COLLECT_TAB)
LEGACY_CATALOGUE_TAB = "Catalogue"

MARQUES_TAB = "🟤C-MARQUE"
MARQUES_HEADER = ["kind", "name", "uuid", "image_url", "licensor_name",
                  "licensor_uuid", "n_total", "n_collectibles", "n_comics"]

# Hidden store of brand / licensor logo URLs (fetched from VeVe GraphQL), merged
# into the Marques & Licences page. Kept separately so it accumulates across runs.
BRAND_IMAGES_TAB = "_BrandImages"
BRAND_IMAGES_HEADER = ["uuid", "kind", "name", "image_url"]

# Single append-only DYNAMIC HISTORY page (COLLECTIBLES only). It merges what used
# to be three tabs (snapshot + PriceHistory + EditionsHistory) so the whole
# evolution of every collectible lives on ONE page. One row is appended whenever
# any tracked value changes. A hidden state tab holds the last-known values for a
# fast diff (no need to re-read the whole history each run).
DYN_TAB = "🟠H-PRIX"
DYN_STATE_TAB = "_DynState"          # hidden: last snapshot per uuid (for diffing)
DYN_FIELDS = [
    "market_lowestOffer", "market_totalListings", "releaseAmount",
    "veve_total_available", "veve_store_price",
    "sold_editions", "editions_in_circulation", "burned_editions",
    "withheld_editions", "store_allocation",
]
DYN_HEADER = ["snapshot_date", "veve_uuid", "name", "category"] + DYN_FIELDS
DYN_STATE_HEADER = ["veve_uuid", "name", "category"] + DYN_FIELDS + ["last_snapshot"]
DYN_RETENTION_DAYS = 120             # keep ~4 months of history, prune older rows

# Unified run log (catalogue / dynamic / pseudos / chain)
LOGS_TAB = "🤖LOGS"
LOGS_HEADER = ["ts_utc", "source", "status", "details"]
LOG_RETENTION_DAYS = 7
FLOOR_COLUMN = "market_lowestOffer"

BLUE = {"red": 0.82, "green": 0.90, "blue": 1.0}
GREEN = {"red": 0.83, "green": 0.96, "blue": 0.83}
WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}
UPCOMING_DAYS = 7


def _client() -> gspread.Client:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON env var is not set.")
    creds = Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    return gspread.authorize(creds)


def _open_worksheet(sh, tab: str, cols: int = 26):
    try:
        return sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        return sh.add_worksheet(title=tab, rows=100, cols=cols)


def _now() -> str:
    return _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return _dt.datetime.utcnow().strftime("%Y-%m-%d")


def _to_num(x: Any) -> Optional[float]:
    if x in (None, ""):
        return None
    try:
        return float(str(x).replace(",", "."))
    except (ValueError, TypeError):
        return None


def _fmt_fee(x: Any) -> Any:
    """VeVe marketFee -> percentage string.

    VeVe returns the fee as a FRACTION (0.085 = 8.5% = 2.5% VeVe + 6% licensor).
    We also tolerate the legacy tenths-of-percent scale (85 -> 8.5%) so old sheet
    values don't blow up before they're re-enriched.
    """
    n = _to_num(x)
    if n is None:
        return "" if x is None else x
    if n == 0:
        return "0%"
    pct = n * 100 if n < 1 else n / 10  # fraction (0.085->8.5) vs legacy tenths (85->8.5)
    s = f"{pct:.2f}".rstrip("0").rstrip(".")
    return f"{s}%"


def _parse_dt(x: Any) -> Optional[_dt.datetime]:
    if not x:
        return None
    s = str(x).strip().replace("Z", "")
    try:
        return _dt.datetime.fromisoformat(s)
    except Exception:
        try:
            return _dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return None


def _is_upcoming(prod: Dict[str, Any], now: _dt.datetime) -> bool:
    """Any drop still in the future (highlighted until its release date passes)."""
    dt = _parse_dt(prod.get("releaseDate")) or _parse_dt(prod.get("drop_date"))
    return bool(dt and dt > now)


def _is_recent(prod: Dict[str, Any], now: _dt.datetime, days: int = 7) -> bool:
    """Released within the last `days` days (its first week of existence)."""
    dt = _parse_dt(prod.get("releaseDate")) or _parse_dt(prod.get("drop_date"))
    return bool(dt and now - _dt.timedelta(days=days) <= dt <= now)


def _catalogue_worksheets(sh) -> list:
    """Every worksheet holding catalogue rows: the split tabs + legacy if present."""
    out = []
    for tab in CATALOGUE_TABS + (LEGACY_CATALOGUE_TAB,):
        try:
            out.append(sh.worksheet(tab))
        except gspread.WorksheetNotFound:
            pass
    return out


def get_existing_ids(spreadsheet_id: str, tab: str = "") -> set:
    """All veve_uuid values already in the sheet (reads only column A -> fast)."""
    gc = _client()
    sh = gc.open_by_key(spreadsheet_id)
    ids: set = set()
    for ws in _catalogue_worksheets(sh):
        col = ws.col_values(1)  # veve_uuid is always the first column
        ids.update(c.strip() for c in col[1:] if c and c.strip())
    return ids


def get_enriched_ids(spreadsheet_id: str, tab: str = "") -> set:
    gc = _client()
    sh = gc.open_by_key(spreadsheet_id)
    out = set()
    for ws in _catalogue_worksheets(sh):
        if ws.row_count <= 1:
            continue
        for r in ws.get_all_records():
            if str(r.get("veve_enriched_at", "")).strip():
                uid = str(r.get(KEY_COLUMN, "")).strip()
                if uid:
                    out.add(uid)
    return out


# ---------------------------------------------------------------------------
# Normalisation: fold duplicate columns into the canonical veve_* / edition_type
# ---------------------------------------------------------------------------

# "This release features VeVe-Exclusive Rare & Ultra Rare covers by Jan Bazaldua..."
# Le tiret peut etre un espace, un trait d'union ou une apostrophe typographique
# selon les fiches -> on tolere tout separateur non alphabetique.
_EXCLUSIVE_RE = re.compile(r"veve[^a-z0-9]{0,3}exclusive", re.IGNORECASE)


def _is_exclusive_cover(description: Any) -> Optional[bool]:
    """TRUE / FALSE si la description annonce (ou non) une cover exclusive VeVe.

    Renvoie None quand il n'y a PAS de description : on ne sait pas, et ecrire
    FALSE ferait passer une inconnue pour une reponse. Une fiche enrichie sans le
    mot-cle, elle, est un vrai FALSE.
    """
    if description in (None, ""):
        return None
    return bool(_EXCLUSIVE_RE.search(str(description)))


def _fill_new_cold(rec: Dict[str, Any]) -> None:
    """Alimente supply / store_price_gems / mcp_priority / veve_exclusive.

    IDEMPOTENT et NON DESTRUCTIF : une valeur deja presente dans la ligne (donc
    relue du sheet) n'est jamais ecrasee par du vide. C'est indispensable ici :
    sync_catalogue relit TOUTES les lignes existantes a chaque run, et ces
    lignes-la n'ont plus les champs bruts d'enrichissement (`rarity_editions`,
    `veve_store_price`) — les recalculer donnerait "" et effacerait le backfill.
    """
    is_comic = str(rec.get("category", "")).lower() == "comic"
    if not rec.get("supply"):
        # totalIssued (GraphQL) = le supply de la SERIE pour un comic, de l'item
        # pour un collectible.
        #
        # ⚠️ PIEGE PAYE LE 13/07 : pour un COMIC, `releaseAmount` (my-nft-tracker)
        # est le supply de la RARETE de la ligne (Cheetara #2 COMMON = 400), pas
        # celui de la serie. L'utiliser en repli melangeait deux grandeurs dans la
        # meme colonne. Un comic n'a donc AUCUN repli tracker : sans enrichissement
        # GraphQL, la cellule reste vide (le backfill la remplira).
        rec["supply"] = rec.get("rarity_editions") or ""
        if not rec["supply"] and not is_comic:
            rec["supply"] = rec.get("releaseAmount") or ""
    if not rec.get("supply_rarete"):
        # Supply PAR RARETE (le VRAI tirage de la ligne, via le tracker) : c'est
        # justement le `releaseAmount` que `supply` s'interdit d'utiliser (il
        # melangerait avec le total serie). Colonne dediee -> la carte de drop
        # montre le tirage de chaque rarete, et leur SOMME = le vrai total comic.
        rec["supply_rarete"] = rec.get("releaseAmount") or ""
    if not rec.get("store_price_gems"):
        prix = rec.get("veve_store_price") or rec.get("storePrice") or ""
        # ⚠️ COMICS : VeVe melange DEUX echelles dans `storePrice`. Les vieux comics
        # etaient vendus en GEMS (10, 15, 20), les recents en FIAT et en CENTIMES
        # (699, 798, 1499). Preuve : Captain America Comics #7 = 699, et la carte
        # Discord de Preda dit « 7 gems » ; sur Cheetara #2 le tracker dit 7.98 la
        # ou GraphQL dit 798. Au-dela de 100 c'est donc des centimes — un comic n'a
        # jamais coute 100 gems. Regle IDEMPOTENTE (7,98 < 100, pas de 2e division).
        # NE VAUT PAS pour les collectibles : 1 500 gems, ça existe.
        n = _to_num(prix)
        if is_comic and n is not None and n >= 100:
            prix = round(n / 100, 2)
        rec["store_price_gems"] = prix
    if is_comic:
        excl = _is_exclusive_cover(rec.get("description"))
        if excl is not None:
            rec["veve_exclusive"] = excl
        else:
            rec.setdefault("veve_exclusive", "")


def _normalise(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Fold tracker duplicates into the canonical columns, format the fee, strip
    dropped columns. Mutates and returns `rec`."""
    rec["veve_series_name"] = rec.get("veve_series_name") or rec.get("series_name")
    rec["veve_brand"] = rec.get("veve_brand") or rec.get("brand_name")
    rec["veve_licensor"] = rec.get("veve_licensor") or rec.get("licensor_name")
    rec["edition_type"] = rec.get("edition_type") or rec.get("edition")
    if rec.get("market_fee") not in (None, ""):
        rec["market_fee"] = _fmt_fee(rec.get("market_fee"))
    rec["veve_url"] = build_veve_url(rec.get("category"), rec.get("veve_uuid"),
                                     rec.get("series_uuid"))
    # ORDRE IMPORTANT : on recopie les champs bruts AVANT que DROP_COLUMNS ne les
    # jette. C'est tout le bug qu'on repare : les donnees etaient la, on les
    # supprimait a la derniere ligne.
    _fill_new_cold(rec)
    for dc in DROP_COLUMNS:
        rec.pop(dc, None)
    return rec


# ---------------------------------------------------------------------------
# COLD catalogue sync (daily) — also (re)builds the Marques & Licences page
# ---------------------------------------------------------------------------

def sync_catalogue(products: List[Dict[str, Any]], spreadsheet_id: str,
                   tab: str = "") -> Dict[str, Any]:
    """Merge `products` (usually just the new/recent window) into the persisted
    cold catalogue tabs, rewrite them, and rebuild the Marques & Licences page.
    Rows are never deleted; existing rows are the source of truth for counts."""
    gc = _client()
    sh = gc.open_by_key(spreadsheet_id)

    existing_by_id: Dict[str, Dict[str, Any]] = {}
    for ws in _catalogue_worksheets(sh):
        if ws.row_count <= 1:
            continue
        for row in ws.get_all_records():
            rid = str(row.get(KEY_COLUMN, "")).strip()
            if rid and rid not in existing_by_id:
                existing_by_id[rid] = dict(row)

    valid = [p for p in products if str(p.get(KEY_COLUMN, "")).strip()]

    now_dt = _dt.datetime.utcnow()
    now = _now()
    added, updated = 0, 0
    new_collectibles: List[str] = []
    new_comics: List[str] = []
    merged: Dict[str, Dict[str, Any]] = dict(existing_by_id)

    for prod in valid:
        pid = str(prod.get(KEY_COLUMN, "")).strip()
        cat = str(prod.get("category", "")).lower()
        record = {k: _cell(v) for k, v in prod.items()}
        if pid in merged:
            record[FIRST_SEEN] = merged[pid].get(FIRST_SEEN) or now
            record[LAST_SEEN] = now
            for k, v in merged[pid].items():
                record.setdefault(k, v)
            merged[pid] = record
            updated += 1
        else:
            record[FIRST_SEEN] = now
            record[LAST_SEEN] = now
            merged[pid] = record
            added += 1
            if cat == "collectible":
                new_collectibles.append(str(prod.get("name", "")) or pid)
            elif cat == "comic":
                new_comics.append(str(prod.get("name", "")) or pid)

    for rec in merged.values():
        _normalise(rec)

    # TRI CHRONOLOGIQUE (demande Preda 16/07) : le DERNIER sorti EN HAUT, par
    # date de sortie (releaseDate) decroissante — vaut pour comics ET
    # collectibles. Une date vide (jamais dropee) tombe en bas. (Avant :
    # first_seen = l'ordre ou NOUS avons vu l'item, pas sa sortie VeVe.)
    ordered_recs = sorted(
        merged.values(),
        key=lambda r: (str(r.get("releaseDate", "")), str(r.get("name", ""))),
        reverse=True,
    )
    comics_recs = [r for r in ordered_recs
                   if str(r.get("category", "")).lower() == "comic"]
    collect_recs = [r for r in ordered_recs
                    if str(r.get("category", "")).lower() != "comic"]

    n_upcoming = 0
    for tab_name, recs, cols, colour in (
            (COMICS_TAB, comics_recs, COMICS_COLD + BOOKKEEPING, GREEN),
            (COLLECT_TAB, collect_recs, COLLECTIBLE_COLD + BOOKKEEPING, BLUE)):
        ws = _open_worksheet(sh, tab_name, cols=len(cols))
        grid: List[List[Any]] = [cols]
        upcoming: List[int] = []
        for i, rec in enumerate(recs):
            grid.append([rec.get(col, "") for col in cols])
            if _is_upcoming(rec, now_dt):
                upcoming.append(i + 1)
        n_upcoming += len(upcoming)
        ws.clear()
        ws.update(range_name="A1", values=grid, value_input_option="RAW")
        try:
            ws.freeze(rows=1)
        except Exception:
            pass
        _apply_formatting(sh, ws, len(grid), len(cols), upcoming, colour)

    # Migration done: drop the legacy single-tab catalogue.
    try:
        sh.del_worksheet(sh.worksheet(LEGACY_CATALOGUE_TAB))
        print(f"    legacy '{LEGACY_CATALOGUE_TAB}' tab deleted (migrated).", flush=True)
    except gspread.WorksheetNotFound:
        pass
    except Exception as e:
        print(f"    legacy tab deletion warning: {e}", flush=True)

    brand_imgs = _read_brand_images(sh)
    n_brands, n_licensors = _write_marques(sh, merged.values(), brand_imgs)

    return {
        "status": "OK",
        "total_rows": len(merged),
        "comics_rows": len(comics_recs),
        "collectibles_rows": len(collect_recs),
        "new_items": added,
        "updated_items": updated,
        "new_collectibles": len(new_collectibles),
        "new_comics": len(new_comics),
        "upcoming_drops": n_upcoming,
        "brands": n_brands,
        "licensors": n_licensors,
        "new_item_names": (new_collectibles + new_comics)[:40],
    }


# Backward-compatible alias (old callers).
sync_products = sync_catalogue


def _read_brand_images(sh) -> Dict[str, str]:
    """{cle -> image_url} depuis l'onglet cache _BrandImages.

    Deux cles par ligne : l'uuid, ET "name:<nom normalise>" en secours — les
    anciennes lignes sont clees par l'id GraphQL VeVe (≠ uuid tracker de
    🟤C-MARQUE), le fallback par nom les rattrape sans re-sonder VeVe."""
    out: Dict[str, str] = {}
    try:
        ws = sh.worksheet(BRAND_IMAGES_TAB)
    except gspread.WorksheetNotFound:
        return out
    for r in ws.get_all_records():
        u = str(r.get("uuid", "")).strip()
        n = str(r.get("name", "")).strip().lower()
        img = str(r.get("image_url", "")).strip()
        if not img:
            continue
        if u:
            out[u] = img
        if n:
            out.setdefault("name:" + n, img)
    return out


def _brand_img(brand_imgs: Dict[str, str], uuid: str, name: str) -> str:
    """Logo par uuid, sinon par nom normalise (fallback lignes legacy)."""
    return (brand_imgs.get(str(uuid).strip())
            or brand_imgs.get("name:" + str(name).strip().lower(), ""))


def _write_marques(sh, records, brand_imgs: Optional[Dict[str, str]] = None) -> tuple:
    """Build the Marques & Licences reference page from catalogue rows.
    `brand_imgs` maps brand/licensor uuid -> logo URL (from VeVe)."""
    brand_imgs = brand_imgs or {}
    brands: Dict[str, Dict[str, Any]] = {}
    licensors: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        cat = str(rec.get("category", "")).lower()
        is_comic = cat == "comic"
        b_uuid = str(rec.get("brand_uuid", "")).strip()
        b_name = str(rec.get("veve_brand", "")).strip()
        l_uuid = str(rec.get("licensor_uuid", "")).strip()
        l_name = str(rec.get("veve_licensor", "")).strip()
        if b_name or b_uuid:
            key = b_uuid or b_name
            b = brands.setdefault(key, {"name": b_name, "uuid": b_uuid,
                                        "licensor_name": l_name, "licensor_uuid": l_uuid,
                                        "n_collectibles": 0, "n_comics": 0})
            b["n_comics" if is_comic else "n_collectibles"] += 1
            if not b["licensor_name"] and l_name:
                b["licensor_name"] = l_name
                b["licensor_uuid"] = l_uuid
        if l_name or l_uuid:
            key = l_uuid or l_name
            lz = licensors.setdefault(key, {"name": l_name, "uuid": l_uuid,
                                            "n_collectibles": 0, "n_comics": 0})
            lz["n_comics" if is_comic else "n_collectibles"] += 1

    rows: List[List[Any]] = []
    for lz in sorted(licensors.values(),
                     key=lambda d: -(d["n_collectibles"] + d["n_comics"])):
        rows.append(["Licence", lz["name"], lz["uuid"], _brand_img(brand_imgs, lz["uuid"], lz["name"]),
                     "", "", lz["n_collectibles"] + lz["n_comics"],
                     lz["n_collectibles"], lz["n_comics"]])
    for b in sorted(brands.values(),
                    key=lambda d: -(d["n_collectibles"] + d["n_comics"])):
        rows.append(["Marque", b["name"], b["uuid"], _brand_img(brand_imgs, b["uuid"], b["name"]),
                     b["licensor_name"], b["licensor_uuid"],
                     b["n_collectibles"] + b["n_comics"],
                     b["n_collectibles"], b["n_comics"]])

    ws = _open_worksheet(sh, MARQUES_TAB, cols=len(MARQUES_HEADER))
    ws.clear()
    ws.update(range_name="A1", values=[MARQUES_HEADER] + rows,
              value_input_option="RAW")
    try:
        ws.freeze(rows=1)
        ws.format("1:1", {"textFormat": {"bold": True}})
    except Exception:
        pass
    return len(brands), len(licensors)


def write_brand_images(spreadsheet_id: str, rows: List[List[Any]]) -> int:
    """Merge new [uuid, kind, name, image_url] rows into the hidden _BrandImages
    tab (never overwrites an existing uuid). Returns how many were added."""
    if not rows:
        return 0
    gc = _client()
    sh = gc.open_by_key(spreadsheet_id)
    ws = _open_worksheet(sh, BRAND_IMAGES_TAB, cols=len(BRAND_IMAGES_HEADER))
    existing = set()
    if not ws.row_values(1):
        ws.update(range_name="A1", values=[BRAND_IMAGES_HEADER],
                  value_input_option="RAW")
    else:
        existing = {str(u).strip() for u in ws.col_values(1)[1:] if str(u).strip()}
    fresh = [r for r in rows if str(r[0]).strip() and str(r[0]).strip() not in existing]
    if fresh:
        ws.append_rows(fresh, value_input_option="RAW")
    try:
        ws.hide()
    except Exception:
        pass
    return len(fresh)


def get_brand_image_uuids(spreadsheet_id: str) -> set:
    """UUIDs that already have a logo recorded (to skip re-fetching)."""
    gc = _client()
    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(BRAND_IMAGES_TAB)
    except gspread.WorksheetNotFound:
        return set()
    return {str(u).strip() for u in ws.col_values(1)[1:] if str(u).strip()}


def _apply_formatting(sh, ws, n_rows: int, n_cols: int,
                      upcoming_rows: List[int], upcoming_colour: Dict) -> None:
    sid = ws.id
    reqs: List[Dict[str, Any]] = []
    if n_rows > 1:
        reqs.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": n_rows,
                      "startColumnIndex": 0, "endColumnIndex": n_cols},
            "cell": {"userEnteredFormat": {"backgroundColor": WHITE}},
            "fields": "userEnteredFormat.backgroundColor"}})
    reqs.append({"repeatCell": {
        "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                  "startColumnIndex": 0, "endColumnIndex": n_cols},
        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
        "fields": "userEnteredFormat.textFormat.bold"}})

    # Plus de surlignage de fond des nouveaux items / drops a venir (demande
    # Preda, 16/07) : tout reste sur fond BLANC — le reset ci-dessus efface les
    # anciennes couleurs vert/bleu. On garde la signature (appelant intact).
    _ = (upcoming_rows, upcoming_colour)
    # Clear any leftover conditional-format rules (old rarity colouring).
    try:
        meta = sh.fetch_sheet_metadata()
        for sheet in meta.get("sheets", []):
            if sheet.get("properties", {}).get("sheetId") == sid:
                n_cf = len(sheet.get("conditionalFormats", []) or [])
                for _ in range(n_cf):
                    reqs.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}})
                break
    except Exception:
        pass
    try:
        sh.batch_update({"requests": reqs})
    except Exception as e:
        print(f"    formatting warning: {e}", flush=True)


# ---------------------------------------------------------------------------
# DYNAMIC snapshot sync (hourly for collectibles, daily for comics)
# ---------------------------------------------------------------------------

def sync_dynamic(items: List[Dict[str, Any]], spreadsheet_id: str) -> Dict[str, Any]:
    """Append the dynamic evolution of COLLECTIBLES to the single append-only
    'Données Dynamiques' history page.

    For each item, a full-row snapshot (floor, listings, supply, editions…) is
    appended **only when at least one tracked field changed** vs the item's last
    recorded state (kept in the hidden _DynState tab). This unifies what used to
    be the snapshot + PriceHistory + EditionsHistory tabs into one time series.

    Each item is a dict with veve_uuid, name, category and any DYN_FIELDS.
    Comics : uniquement leur prix store (module comic_prices, 2026-07-08) —
    pas de floor/listings pour eux, le prix store ne change quasiment jamais
    donc le cout en lignes est minime.
    """
    gc = _client()
    sh = gc.open_by_key(spreadsheet_id)
    hist = _open_worksheet(sh, DYN_TAB, cols=len(DYN_HEADER))
    state_ws = _open_worksheet(sh, DYN_STATE_TAB, cols=len(DYN_STATE_HEADER))

    # Last-known values per uuid (for a fast diff without re-reading history).
    # LECTURE NON FORMATEE (fix 2026-07-10) : sur un Sheet en locale FR, le
    # nombre 6.99 s'affiche "6,99" et gspread.numericise le relit **699**
    # (virgule avalee comme separateur de milliers EN). La reecriture de l'etat
    # persistait cette corruption (prix comics x100 dans _DynState) et le faux
    # "changement" quotidien re-appendait ~15k lignes parasites dans 🟠H-PRIX.
    # UNFORMATTED_VALUE renvoie les vrais nombres ; l'etat corrompu se soigne
    # seul des que chaque module refournit ses champs (1 jour).
    from gspread.utils import ValueRenderOption
    state: Dict[str, Dict[str, Any]] = {}
    if state_ws.row_count > 1:
        for r in state_ws.get_all_records(
                value_render_option=ValueRenderOption.unformatted):
            rid = str(r.get(KEY_COLUMN, "")).strip()
            if rid:
                state[rid] = dict(r)

    stamp = _now()
    new_state: Dict[str, Dict[str, Any]] = {k: dict(v) for k, v in state.items()}
    new_rows: List[List[Any]] = []
    appended = 0

    for it in items:
        pid = str(it.get(KEY_COLUMN, "")).strip()
        if not pid:
            continue
        old = state.get(pid)

        # Detect change only on fields the item actually provides (non-empty),
        # so a partial refresh never records a spurious "back to empty".
        changed = old is None
        for f in DYN_FIELDS:
            v = it.get(f)
            if v in (None, ""):
                continue
            if _to_num(v) != _to_num((old or {}).get(f)):
                changed = True
                break
        if not changed:
            continue

        # Build the snapshot, keeping last-known values for fields not refreshed.
        snap = {"veve_uuid": pid, "name": it.get("name", (old or {}).get("name", "")),
                "category": it.get("category", (old or {}).get("category", ""))}
        for f in DYN_FIELDS:
            v = it.get(f)
            snap[f] = _cell(v) if v not in (None, "") else (old or {}).get(f, "")

        # snapshot_date = l'heure d'OBSERVATION si l'appelant la fournit (le pont
        # 🌉 porte l'heure ou le floor a change, pas l'heure d'ingestion), sinon
        # l'heure courante. Retro-compatible : floors/comic_prices/dynamic_run ne
        # passent rien -> `stamp` comme avant.
        sd = it.get("snapshot_date") or stamp
        row = {"snapshot_date": sd, **snap}
        new_rows.append([row.get(c, "") for c in DYN_HEADER])
        new_state[pid] = {**snap, "last_snapshot": sd}
        appended += 1

    # Append the changed rows to the history page. Make sure row 1 is the CURRENT
    # header: if the tab pre-existed with a different (old) header, rewrite it so
    # the columns line up with the data we append (fixes the misaligned header).
    if hist.row_values(1) != DYN_HEADER:
        hist.update(range_name="A1", values=[DYN_HEADER], value_input_option="RAW")
        try:
            hist.freeze(rows=1)
            hist.format("1:1", {"textFormat": {"bold": True}})
        except Exception:
            pass
    for i in range(0, len(new_rows), 20000):
        hist.append_rows(new_rows[i:i + 20000], value_input_option="RAW")

    # Rewrite the hidden state tab with the latest values.
    state_grid = [DYN_STATE_HEADER] + [[new_state[k].get(c, "") for c in DYN_STATE_HEADER]
                                       for k in new_state]
    state_ws.clear()
    for i in range(0, len(state_grid), 20000):
        if i == 0:
            state_ws.update(range_name="A1", values=state_grid[:20000],
                            value_input_option="RAW")
        else:
            state_ws.append_rows(state_grid[i:i + 20000], value_input_option="RAW")
    try:
        state_ws.hide()
    except Exception:
        pass

    pruned = _prune_history(hist)

    return {
        "status": "OK",
        "items": len(items),
        "rows_appended": appended,
        "rows_pruned": pruned,
        "tracked_collectibles": len(new_state),
    }


def _prune_history(ws) -> int:
    """Delete the leading block of history rows older than DYN_RETENTION_DAYS."""
    try:
        cutoff = (_dt.datetime.utcnow()
                  - _dt.timedelta(days=DYN_RETENTION_DAYS)).strftime("%Y-%m-%d")
        dates = ws.col_values(1)  # snapshot_date, includes header
        n_old = 0
        for d in dates[1:]:
            if d and d < cutoff:
                n_old += 1
            else:
                break
        if n_old:
            ws.delete_rows(2, 1 + n_old)
        return n_old
    except Exception as e:
        print(f"    history prune warning: {e}", flush=True)
        return 0


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

def append_log(spreadsheet_id: str, source: str, status: str,
               details: str = "") -> None:
    """One row in the unified "Logs" tab + prune entries older than
    LOG_RETENTION_DAYS. Sources: catalogue / dynamic / pseudos / chain."""
    gc = _client()
    sh = gc.open_by_key(spreadsheet_id)
    ws = _open_worksheet(sh, LOGS_TAB, cols=len(LOGS_HEADER))
    if not ws.row_values(1):
        ws.update(range_name="A1", values=[LOGS_HEADER], value_input_option="RAW")
        try:
            ws.freeze(rows=1)
            ws.format("1:1", {"textFormat": {"bold": True}})
        except Exception:
            pass
    ws.append_rows([[_now(), source, status, details[:2000]]],
                   value_input_option="RAW")
    try:
        cutoff = (_dt.datetime.utcnow()
                  - _dt.timedelta(days=LOG_RETENTION_DAYS)).strftime("%Y-%m-%d")
        stamps = ws.col_values(1)
        n_old = 0
        for s in stamps[1:]:
            if s and s < cutoff:
                n_old += 1
            else:
                break
        if n_old:
            ws.delete_rows(2, 1 + n_old)
    except Exception as e:
        print(f"    log prune warning: {e}", flush=True)


def summary_details(summary: Dict[str, Any], skip=("status",)) -> str:
    """Compact 'k=v; k=v' rendering of a run summary for the Logs tab."""
    parts = []
    for k, v in summary.items():
        if k in skip or v in (None, "", []):
            continue
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v[:15])
        parts.append(f"{k}={v}")
    return "; ".join(parts)


def append_run_log(spreadsheet_id: str, summary: Dict[str, Any],
                   duration_sec: Optional[float] = None,
                   source: str = "catalogue") -> None:
    """Run entry in the unified Logs tab (source: catalogue / dynamic)."""
    s = dict(summary)
    if duration_sec is not None:
        s["duration"] = f"{duration_sec:.0f}s"
    append_log(spreadsheet_id, source, str(summary.get("status", "")),
               summary_details(s))


def _cell(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, (str, int, float, bool)):
        return v
    try:
        return json.dumps(v, ensure_ascii=False)
    except Exception:
        return str(v)
