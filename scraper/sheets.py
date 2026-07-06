"""
Google Sheets sync for the VeVe catalogue.

Tabs maintained:
1. "🟢C-COMICS" / "🔵C-COLLECTIBLE"
                    — current snapshot, one row per product UUID (dedupe by veve_uuid),
                      physically split by category. Rows are never deleted (we always
                      start from what's already there), so a tracker outage can't wipe
                      your data. Upcoming drops are highlighted (green = comics,
                      blue = collectibles). The legacy "Catalogue" tab, if present,
                      is read once (migration) then deleted.
2. "PriceHistory"   — append-only floor-price log (COLLECTIBLES only), one row per change.
3. "EditionsHistory"— append-only log of the VARIABLE fields (sold / in-circulation /
                      burned / withheld / available), one row per change, so you can
                      track and compare them over time.
4. "Logs"           — unified run log (catalogue / pseudos / chain), one row per run,
                      pruned to LOG_RETENTION_DAYS — your confirmation the jobs worked.
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

PREFERRED_ORDER = [
    "veve_uuid", "name", "category", "edition", "rarity", "releaseDate",
    "releaseAmount", "availableAmount",
    "storePrice", "market_lowestOffer", "market_totalListings",
    "allTimeLow", "allTimeHigh", "change_1d_pct", "change_7d_pct", "change_30d_pct",
    "gemsPerMcp", "noMarketListing",
    "series_name", "series_uuid",
    "brand_name", "brand_uuid", "licensor_name", "licensor_uuid",
    "veve_url", "image_url", "tracker_uuid",
    "description", "special_edition", "edition_type", "is_blindbox",
    "drop_method", "drop_date", "daily_mcp_points", "market_fee", "veve_store_price",
    "rarity_editions", "editions_in_circulation", "sold_editions", "burned_editions",
    "withheld_editions", "store_allocation", "first_available_edition",
    "veve_total_available", "start_year", "veve_comic_name", "veve_series_name",
    "veve_brand", "veve_licensor", "veve_enriched_at",
    "first_seen", "last_seen",
]

FIRST_SEEN = "first_seen"
LAST_SEEN = "last_seen"
KEY_COLUMN = "veve_uuid"

# Physical catalogue split (one tab per category) + legacy tab (migrated then deleted)
COMICS_TAB = "🟢C-COMICS"
COLLECT_TAB = "🔵C-COLLECTIBLE"
CATALOGUE_TABS = (COMICS_TAB, COLLECT_TAB)
LEGACY_CATALOGUE_TAB = "Catalogue"

# Unified run log (catalogue / pseudos / chain)
LOGS_TAB = "Logs"
LOGS_HEADER = ["ts_utc", "source", "status", "details"]
LOG_RETENTION_DAYS = 7
# Columns removed from the sheet (empty/useless)
DROP_COLUMNS = {"provider", "series_edition", "licensor_fee", "isEcl",
                "image_cloudflare", "season"}
FLOOR_COLUMN = "market_lowestOffer"

DYNAMIC_FIELDS = [
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

# Rarity background colours (hex -> rgb 0..1), white text for contrast.
def _hex(h):
    h = h.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}

RARITY_COLOURS = {
    "COMMON": _hex("1A7431"),
    "UNCOMMON": _hex("5F3072"),
    "RARE": _hex("0466C8"),
    "ULTRA_RARE": _hex("FD9E02"),
    "SECRET_RARE": _hex("A1160E"),
    "ARTIST_PROOF": _hex("D801D8"),
}


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


def _order_columns(all_keys: set) -> List[str]:
    ordered: List[str] = []
    for k in PREFERRED_ORDER:
        if k in all_keys and k not in ordered:
            ordered.append(k)
    for k in sorted(all_keys):
        if k not in ordered:
            ordered.append(k)
    for bk in (FIRST_SEEN, LAST_SEEN):
        if bk in ordered:
            ordered.remove(bk)
        ordered.append(bk)
    return ordered


def _to_num(x: Any) -> Optional[float]:
    if x in (None, ""):
        return None
    try:
        return float(x)
    except (ValueError, TypeError):
        return None


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
    """All veve_uuid values already in the sheet (reads only column A -> fast).
    `tab` is kept for backward compatibility and ignored."""
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


def sync_products(products: List[Dict[str, Any]], spreadsheet_id: str,
                  tab: str = "") -> Dict[str, Any]:
    """`tab` is kept for backward compatibility and ignored: rows are written
    into the split tabs (🟢C-COMICS / 🔵C-COLLECTIBLE)."""
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
    now = stamp = _now()
    added, updated = 0, 0
    new_collectibles: List[str] = []
    new_comics: List[str] = []
    merged: Dict[str, Dict[str, Any]] = dict(existing_by_id)
    price_rows: List[List[Any]] = []
    edition_rows: List[List[Any]] = []
    seen_comic_edit: set = set()

    for prod in valid:
        pid = str(prod.get(KEY_COLUMN, "")).strip()
        cat = str(prod.get("category", "")).lower()
        prev = existing_by_id.get(pid)

        if cat == "collectible":
            nf = _to_num(prod.get(FLOOR_COLUMN))
            if nf is not None and nf > 0:
                pf = _to_num(prev.get(FLOOR_COLUMN)) if prev else None
                if pf is None or pf != nf:
                    price_rows.append([stamp, pid, prod.get("name", ""), prod.get("category", ""),
                                       nf, prod.get("storePrice", ""),
                                       prod.get("market_totalListings", "")])

        if cat in ("collectible", "comic") and _is_recent(prod, now_dt) \
                and any(prod.get(f) not in (None, "") for f in DYNAMIC_FIELDS):
            item_id = pid if cat == "collectible" else str(prod.get("series_uuid", "")).strip()
            if item_id and not (cat == "comic" and item_id in seen_comic_edit):
                if cat == "comic":
                    seen_comic_edit.add(item_id)
                changed = False
                for fld in DYNAMIC_FIELDS:
                    newv = _to_num(prod.get(fld))
                    oldv = _to_num(prev.get(fld)) if prev else None
                    if newv is not None and newv != oldv:
                        changed = True
                        break
                if changed:
                    edition_rows.append([stamp, item_id, prod.get("name", ""), prod.get("category", "")]
                                        + [prod.get(f, "") for f in DYNAMIC_FIELDS])

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

    # Fix veve_url for every row (comics use series_uuid) + strip dead columns
    for rec in merged.values():
        for dc in DROP_COLUMNS:
            rec.pop(dc, None)
        rec["veve_url"] = build_veve_url(rec.get("category"), rec.get("veve_uuid"),
                                         rec.get("series_uuid"))

    all_keys: set = set()
    for rec in merged.values():
        all_keys.update(rec.keys())
    columns = _order_columns(all_keys)

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
    for tab_name, recs, colour in ((COMICS_TAB, comics_recs, GREEN),
                                   (COLLECT_TAB, collect_recs, BLUE)):
        ws = _open_worksheet(sh, tab_name, cols=len(columns))
        grid: List[List[Any]] = [columns]
        upcoming: List[int] = []
        for i, rec in enumerate(recs):
            grid.append([rec.get(col, "") for col in columns])
            if _is_upcoming(rec, now_dt):
                upcoming.append(i + 1)
        n_upcoming += len(upcoming)
        ws.clear()
        ws.update(range_name="A1", values=grid, value_input_option="RAW")
        try:
            ws.freeze(rows=1)
        except Exception:
            pass
        _apply_formatting(sh, ws, len(grid), len(columns), upcoming, colour)
        _apply_rarity_colours(sh, ws, columns, len(grid))

    # Migration done: drop the legacy single-tab catalogue.
    try:
        sh.del_worksheet(sh.worksheet(LEGACY_CATALOGUE_TAB))
        print(f"    legacy '{LEGACY_CATALOGUE_TAB}' tab deleted (migrated).",
              flush=True)
    except gspread.WorksheetNotFound:
        pass
    except Exception as e:
        print(f"    legacy tab deletion warning: {e}", flush=True)

    ph = _append_rows(sh, "PriceHistory", PRICE_HISTORY_HEADER, price_rows)
    eh = _append_rows(sh, "EditionsHistory", EDITIONS_HISTORY_HEADER, edition_rows)

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
        "price_history_added": ph,
        "editions_history_added": eh,
        "new_item_names": (new_collectibles + new_comics)[:40],
    }


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
    try:
        sh.batch_update({"requests": reqs})
    except Exception as e:
        print(f"    formatting warning: {e}", flush=True)


def _apply_rarity_colours(sh, ws, columns: List[str], n_rows: int) -> None:
    """Colour the `rarity` cells by rarity via persistent conditional-format rules
    (white text on the requested background). Rules are cleared & re-added each run
    so they always match the current rarity column position."""
    if "rarity" not in columns or n_rows <= 1:
        return
    sid = ws.id
    col = columns.index("rarity")
    rng = {"sheetId": sid, "startRowIndex": 1, "endRowIndex": n_rows,
           "startColumnIndex": col, "endColumnIndex": col + 1}

    # Count existing conditional-format rules on this sheet, to delete them first.
    try:
        meta = sh.fetch_sheet_metadata()
        existing = 0
        for sheet in meta.get("sheets", []):
            if sheet.get("properties", {}).get("sheetId") == sid:
                existing = len(sheet.get("conditionalFormats", []) or [])
                break
    except Exception:
        existing = 0

    reqs = []
    for _ in range(existing):
        reqs.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}})
    for rarity, colour in RARITY_COLOURS.items():
        reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [rng],
            "booleanRule": {
                "condition": {"type": "TEXT_EQ",
                              "values": [{"userEnteredValue": rarity}]},
                "format": {"backgroundColor": colour,
                           "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1},
                                          "bold": True}},
            },
        }}})
    try:
        sh.batch_update({"requests": reqs})
    except Exception as e:
        print(f"    rarity colouring warning: {e}", flush=True)


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


def append_log(spreadsheet_id: str, source: str, status: str,
               details: str = "") -> None:
    """One row in the unified "Logs" tab + prune entries older than
    LOG_RETENTION_DAYS. Sources: catalogue / pseudos / chain."""
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
    # prune: rows are appended chronologically -> drop the leading old block
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
                   duration_sec: Optional[float] = None) -> None:
    """Catalogue-run entry in the unified Logs tab."""
    s = dict(summary)
    if duration_sec is not None:
        s["duration"] = f"{duration_sec:.0f}s"
    append_log(spreadsheet_id, "catalogue", str(summary.get("status", "")),
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
