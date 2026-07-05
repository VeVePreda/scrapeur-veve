"""
Google Sheets sync for the VeVe catalogue.

Tabs maintained:
1. "Catalogue"      — current snapshot, one row per product UUID (dedupe by veve_uuid).
                      Rows are never deleted (we always start from what's already there),
                      so a tracker outage can't wipe your data. Upcoming drops (next 7
                      days) are highlighted: light blue = collectibles, light green = comics.
2. "PriceHistory"   — append-only floor-price log (COLLECTIBLES only), one row per change.
3. "EditionsHistory"— append-only log of the VARIABLE fields (sold / in-circulation /
                      burned / withheld / available), one row per change, so you can
                      track and compare them over time.
4. "RunLog"         — one row per run: when, status, totals, and how many new items were
                      found — your confirmation that the daily job worked.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Any, Dict, List, Optional

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

PREFERRED_ORDER = [
    "veve_uuid", "name", "category", "edition", "rarity", "releaseDate",
    "releaseAmount", "availableAmount", "isEcl",
    "storePrice", "market_lowestOffer", "market_totalListings",
    "allTimeLow", "allTimeHigh", "change_1d_pct", "change_7d_pct", "change_30d_pct",
    "gemsPerMcp", "noMarketListing",
    "series_name", "series_edition", "series_uuid",
    "brand_name", "brand_uuid", "licensor_name", "licensor_fee", "licensor_uuid",
    "provider", "veve_url", "image_url", "image_cloudflare", "tracker_uuid",
    "description", "special_edition", "edition_type", "is_blindbox", "season",
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
RUNLOG_HEADER = ["run_at_utc", "status", "total_rows", "new_items", "updated_items",
                 "new_collectibles", "new_comics", "upcoming_drops",
                 "price_history_added", "editions_history_added", "new_item_names"]

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


def get_existing_ids(spreadsheet_id: str, tab: str = "Catalogue") -> set:
    """All veve_uuid values already in the sheet (reads only column A -> fast)."""
    gc = _client()
    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        return set()
    col = ws.col_values(1)  # veve_uuid is always the first column
    return {c.strip() for c in col[1:] if c and c.strip()}


def get_enriched_ids(spreadsheet_id: str, tab: str = "Catalogue") -> set:
    gc = _client()
    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        return set()
    if ws.row_count <= 1:
        return set()
    out = set()
    for r in ws.get_all_records():
        if str(r.get("veve_enriched_at", "")).strip():
            uid = str(r.get(KEY_COLUMN, "")).strip()
            if uid:
                out.add(uid)
    return out


def sync_products(products: List[Dict[str, Any]], spreadsheet_id: str,
                  tab: str = "Catalogue") -> Dict[str, Any]:
    gc = _client()
    sh = gc.open_by_key(spreadsheet_id)
    ws = _open_worksheet(sh, tab)

    existing_rows = ws.get_all_records() if ws.row_count > 1 else []
    existing_by_id: Dict[str, Dict[str, Any]] = {}
    for row in existing_rows:
        rid = str(row.get(KEY_COLUMN, "")).strip()
        if rid:
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

    all_keys: set = set()
    for rec in merged.values():
        all_keys.update(rec.keys())
    columns = _order_columns(all_keys)

    ordered_recs = sorted(
        merged.values(),
        key=lambda r: (str(r.get(FIRST_SEEN, "")), str(r.get("name", ""))),
        reverse=True,
    )
    grid: List[List[Any]] = [columns]
    upcoming_blue: List[int] = []
    upcoming_green: List[int] = []
    for i, rec in enumerate(ordered_recs):
        grid.append([rec.get(col, "") for col in columns])
        if _is_upcoming(rec, now_dt):
            c = str(rec.get("category", "")).lower()
            if c == "collectible":
                upcoming_blue.append(i + 1)
            elif c == "comic":
                upcoming_green.append(i + 1)

    ws.clear()
    ws.update(range_name="A1", values=grid, value_input_option="RAW")
    try:
        ws.freeze(rows=1)
    except Exception:
        pass

    _apply_formatting(sh, ws, len(grid), len(columns), upcoming_blue, upcoming_green)

    ph = _append_rows(sh, "PriceHistory", PRICE_HISTORY_HEADER, price_rows)
    eh = _append_rows(sh, "EditionsHistory", EDITIONS_HISTORY_HEADER, edition_rows)

    return {
        "status": "OK",
        "total_rows": len(merged),
        "new_items": added,
        "updated_items": updated,
        "new_collectibles": len(new_collectibles),
        "new_comics": len(new_comics),
        "upcoming_drops": len(upcoming_blue) + len(upcoming_green),
        "price_history_added": ph,
        "editions_history_added": eh,
        "new_item_names": (new_collectibles + new_comics)[:40],
    }


def _apply_formatting(sh, ws, n_rows: int, n_cols: int,
                      blue_rows: List[int], green_rows: List[int]) -> None:
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

    def colour_reqs(rows, colour):
        for r in rows[:2000]:
            yield {"repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": r, "endRowIndex": r + 1,
                          "startColumnIndex": 0, "endColumnIndex": n_cols},
                "cell": {"userEnteredFormat": {"backgroundColor": colour}},
                "fields": "userEnteredFormat.backgroundColor"}}

    reqs.extend(colour_reqs(blue_rows, BLUE))
    reqs.extend(colour_reqs(green_rows, GREEN))
    try:
        sh.batch_update({"requests": reqs})
    except Exception as e:
        print(f"    formatting warning: {e}", flush=True)


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


def append_run_log(spreadsheet_id: str, summary: Dict[str, Any],
                   duration_sec: Optional[float] = None) -> None:
    gc = _client()
    sh = gc.open_by_key(spreadsheet_id)
    ws = _open_worksheet(sh, "RunLog", cols=len(RUNLOG_HEADER))
    if not ws.row_values(1):
        ws.update(range_name="A1", values=[RUNLOG_HEADER], value_input_option="RAW")
        try:
            ws.freeze(rows=1)
            ws.format("1:1", {"textFormat": {"bold": True}})
        except Exception:
            pass
    names = summary.get("new_item_names", [])
    names_str = ", ".join(names) if names else ""
    if summary.get("note"):
        names_str = (summary["note"] + " | " + names_str).strip(" |")
    row = [
        _now(), summary.get("status", ""), summary.get("total_rows", ""),
        summary.get("new_items", ""), summary.get("updated_items", ""),
        summary.get("new_collectibles", ""), summary.get("new_comics", ""),
        summary.get("upcoming_drops", ""), summary.get("price_history_added", ""),
        summary.get("editions_history_added", ""), names_str,
    ]
    ws.append_rows([row], value_input_option="RAW")


def _cell(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, (str, int, float, bool)):
        return v
    try:
        return json.dumps(v, ensure_ascii=False)
    except Exception:
        return str(v)
