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
          what's already there), so a source outage can't wipe your data. Upcoming
          drops are highlighted (green = comics, blue = collectibles).
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
    "market_fee", "first_available_edition", "is_blindbox", "drop_method",
]
COMICS_COLD = [
    "veve_uuid", "name", "category", "edition_type", "rarity", "releaseDate",
    "daily_mcp_points", "noMarketListing", "gemsPerMcp", "veve_series_name",
    "series_uuid", "veve_brand", "brand_uuid", "veve_licensor", "licensor_uuid",
    "veve_url", "image_url", "tracker_uuid", "description", "drop_method",
    "market_fee", "first_available_edition", "start_year",
]
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

MARQUES_TAB = "Marques & Licences"
MARQUES_HEADER = ["kind", "name", "uuid", "licensor_name", "licensor_uuid",
                  "n_total", "n_collectibles", "n_comics"]

# Combined dynamic snapshot page.
DYNAMIC_TAB = "Données Dynamiques"
DYNAMIC_HEADER = [
    "veve_uuid", "name", "category",
    "market_lowestOffer", "market_totalListings", "releaseAmount",
    "veve_total_available", "veve_store_price",
    "sold_editions", "editions_in_circulation", "burned_editions",
    "withheld_editions", "store_allocation", "updated_at",
]
# Dynamic fields we actually write (everything except identity + updated_at).
DYNAMIC_VALUE_FIELDS = DYNAMIC_HEADER[3:-1]

# Unified run log (catalogue / dynamic / pseudos / chain)
LOGS_TAB = "Logs"
LOGS_HEADER = ["ts_utc", "source", "status", "details"]
LOG_RETENTION_DAYS = 7
FLOOR_COLUMN = "market_lowestOffer"

# Edition counters watched for the EditionsHistory log.
EDITION_FIELDS = [
    "sold_editions", "editions_in_circulation", "burned_editions",
    "withheld_editions", "veve_total_available",
]

PRICE_HISTORY_HEADER = ["snapshot_date", "veve_uuid", "name", "category",
                        "floor", "storePrice", "totalListings"]
EDITIONS_HISTORY_HEADER = ["snapshot_date", "item_id", "name", "category",
                           "sold_editions", "editions_in_circulation",
                           "burned_editions", "withheld_editions", "veve_total_available"]
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
    """VeVe marketFee (tenths of a percent) -> percentage string, e.g. 85 -> '8.5%'."""
    n = _to_num(x)
    if n is None:
        return x if x not in (None,) else ""
    pct = n / FEE_DIVISOR
    s = f"{pct:.1f}".rstrip("0").rstrip(".")
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

    ordered_recs = sorted(
        merged.values(),
        key=lambda r: (str(r.get(FIRST_SEEN, "")), str(r.get("name", ""))),
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

    n_brands, n_licensors = _write_marques(sh, merged.values())

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


def _write_marques(sh, records) -> tuple:
    """Build the Marques & Licences reference page from catalogue rows."""
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
        rows.append(["Licence", lz["name"], lz["uuid"], "", "",
                     lz["n_collectibles"] + lz["n_comics"],
                     lz["n_collectibles"], lz["n_comics"]])
    for b in sorted(brands.values(),
                    key=lambda d: -(d["n_collectibles"] + d["n_comics"])):
        rows.append(["Marque", b["name"], b["uuid"], b["licensor_name"],
                     b["licensor_uuid"], b["n_collectibles"] + b["n_comics"],
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

    for r in upcoming_rows[:2000]:
        reqs.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": r, "endRowIndex": r + 1,
                      "startColumnIndex": 0, "endColumnIndex": n_cols},
            "cell": {"userEnteredFormat": {"backgroundColor": upcoming_colour}},
            "fields": "userEnteredFormat.backgroundColor"}})
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
    """Merge dynamic values for `items` into the combined 'Données Dynamiques'
    page (field-level merge, keeps previously known values for fields absent from
    an item), and append PriceHistory / EditionsHistory rows on change.

    Each item is a dict with at least veve_uuid, name, category and any of the
    DYNAMIC_VALUE_FIELDS. Floor changes (collectibles) are logged to PriceHistory.
    """
    gc = _client()
    sh = gc.open_by_key(spreadsheet_id)
    ws = _open_worksheet(sh, DYNAMIC_TAB, cols=len(DYNAMIC_HEADER))

    prev: Dict[str, Dict[str, Any]] = {}
    if ws.row_count > 1:
        for r in ws.get_all_records():
            rid = str(r.get(KEY_COLUMN, "")).strip()
            if rid:
                prev[rid] = dict(r)

    stamp = _now()
    merged: Dict[str, Dict[str, Any]] = {k: dict(v) for k, v in prev.items()}
    price_rows: List[List[Any]] = []
    edition_rows: List[List[Any]] = []
    changed = 0

    for it in items:
        pid = str(it.get(KEY_COLUMN, "")).strip()
        if not pid:
            continue
        cat = str(it.get("category", "")).lower()
        old = prev.get(pid, {})
        row = merged.setdefault(pid, {})
        row["veve_uuid"] = pid
        row["name"] = it.get("name", row.get("name", ""))
        row["category"] = it.get("category", row.get("category", ""))

        # Floor history (collectibles only, on change).
        if cat == "collectible":
            nf = _to_num(it.get(FLOOR_COLUMN))
            if nf is not None and nf > 0:
                of = _to_num(old.get(FLOOR_COLUMN))
                if of is None or of != nf:
                    price_rows.append([stamp, pid, it.get("name", ""),
                                       it.get("category", ""), nf,
                                       it.get("veve_store_price", ""),
                                       it.get("market_totalListings", "")])

        # Editions history (on change).
        ed_changed = False
        for fld in EDITION_FIELDS:
            nv = _to_num(it.get(fld))
            ov = _to_num(old.get(fld))
            if nv is not None and nv != ov:
                ed_changed = True
                break
        if ed_changed:
            edition_rows.append([stamp, pid, it.get("name", ""), it.get("category", "")]
                                + [it.get(f, old.get(f, "")) for f in EDITION_FIELDS])

        # Field-level merge: only overwrite when the item provides a value.
        any_change = False
        for fld in DYNAMIC_VALUE_FIELDS:
            v = it.get(fld)
            if v not in (None, ""):
                if str(row.get(fld, "")) != str(v):
                    any_change = True
                row[fld] = _cell(v)
        if any_change or pid not in prev:
            changed += 1
        row["updated_at"] = stamp

    ordered = sorted(merged.values(),
                     key=lambda r: (str(r.get("category", "")), str(r.get("name", ""))))
    grid = [DYNAMIC_HEADER] + [[r.get(c, "") for c in DYNAMIC_HEADER] for r in ordered]
    ws.clear()
    for i in range(0, len(grid), 20000):
        if i == 0:
            ws.update(range_name="A1", values=grid[:20000], value_input_option="RAW")
        else:
            ws.append_rows(grid[i:i + 20000], value_input_option="RAW")
    try:
        ws.freeze(rows=1)
        ws.format("1:1", {"textFormat": {"bold": True}})
    except Exception:
        pass

    ph = _append_rows(sh, "PriceHistory", PRICE_HISTORY_HEADER, price_rows)
    eh = _append_rows(sh, "EditionsHistory", EDITIONS_HISTORY_HEADER, edition_rows)

    return {
        "status": "OK",
        "items": len(items),
        "rows_total": len(merged),
        "rows_changed": changed,
        "price_history_added": ph,
        "editions_history_added": eh,
    }


def _append_rows(sh, tab: str, header: List[str], rows: List[List[Any]]) -> int:
    ws = _open_worksheet(sh, tab, cols=len(header))
    if not ws.row_values(1):
        ws.update(range_name="A1", values=[header], value_input_option="RAW")
        try:
            ws.freeze(rows=1)
            ws.format("1:1", {"textFormat": {"bold": True}})
        except Exception:
            pass
    if rows:
        ws.append_rows(rows, value_input_option="RAW")
    return len(rows)


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
