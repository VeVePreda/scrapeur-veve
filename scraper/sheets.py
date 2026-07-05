"""
Google Sheets sync for the VeVe catalogue.

Two tabs are maintained:

1. "Catalogue" — one row per product UUID (the current snapshot). The column set is
   dynamic (union of all fields seen), deduped by `veve_uuid`. `first_seen` / `last_seen`
   timestamps let you spot new drops (rows are sorted newest-first_seen on top).

2. "PriceHistory" — an append-only floor-price log. Each run, for every product that
   has a market floor, we append a row ONLY IF the floor changed versus the previous
   run (or it's the first time we see a floor for it). This traces the floor over time
   without exploding the sheet with unchanged values.
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
    "veve_uuid",
    "name",
    "category",
    "edition",
    "rarity",
    "releaseDate",
    "releaseAmount",
    "availableAmount",
    "isEcl",
    "storePrice",
    "market_lowestOffer",
    "market_totalListings",
    "allTimeLow",
    "allTimeHigh",
    "change_1d_pct",
    "change_7d_pct",
    "change_30d_pct",
    "gemsPerMcp",
    "noMarketListing",
    "series_name",
    "series_edition",
    "series_uuid",
    "brand_name",
    "brand_uuid",
    "licensor_name",
    "licensor_fee",
    "licensor_uuid",
    "provider",
    "veve_url",
    "image_url",
    "image_cloudflare",
    "tracker_uuid",
    # --- VeVe enrichment (collectibles) ---
    "description",
    "special_edition",
    "edition_type",
    "is_blindbox",
    "season",
    "drop_method",
    "drop_date",
    "daily_mcp_points",
    "market_fee",
    "veve_store_price",
    "rarity_editions",
    "editions_in_circulation",
    "sold_editions",
    "burned_editions",
    "withheld_editions",
    "store_allocation",
    "first_available_edition",
    "veve_total_available",
    "start_year",
    "veve_comic_name",
    "veve_series_name",
    "veve_brand",
    "veve_licensor",
    "veve_enriched_at",
    "first_seen",
    "last_seen",
]

FIRST_SEEN = "first_seen"
LAST_SEEN = "last_seen"

# Dedupe key for the catalogue, and the column holding the market floor price.
KEY_COLUMN = "veve_uuid"
FLOOR_COLUMN = "market_lowestOffer"

HISTORY_HEADER = [
    "snapshot_date",
    "veve_uuid",
    "name",
    "category",
    "floor",
    "storePrice",
    "totalListings",
]


def _client() -> gspread.Client:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON env var is not set.")
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
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


def get_enriched_ids(spreadsheet_id: str, tab: str = "Catalogue") -> set:
    """Return the set of veve_uuid values already enriched (have a veve_enriched_at)."""
    gc = _client()
    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        return set()
    if ws.row_count <= 1:
        return set()
    rows = ws.get_all_records()
    out = set()
    for r in rows:
        if str(r.get("veve_enriched_at", "")).strip():
            uid = str(r.get(KEY_COLUMN, "")).strip()
            if uid:
                out.add(uid)
    return out


def sync_products(
    products: List[Dict[str, Any]],
    spreadsheet_id: str,
    tab: str = "Catalogue",
    history_tab: str = "PriceHistory",
) -> Dict[str, int]:
    """Upsert the catalogue and append changed floors to the price-history tab."""
    gc = _client()
    sh = gc.open_by_key(spreadsheet_id)
    ws = _open_worksheet(sh, tab)

    # ---- Read existing catalogue (previous snapshot) ----
    existing_rows = ws.get_all_records() if ws.row_count > 1 else []
    existing_by_id: Dict[str, Dict[str, Any]] = {}
    for row in existing_rows:
        rid = str(row.get(KEY_COLUMN, "")).strip()
        if rid:
            existing_by_id[rid] = dict(row)

    now = _now()
    today = _today()
    added, updated = 0, 0
    merged: Dict[str, Dict[str, Any]] = dict(existing_by_id)
    history_rows: List[List[Any]] = []

    for prod in products:
        pid = str(prod.get(KEY_COLUMN, "")).strip()
        if not pid:
            continue

        # ---- price-history: append only when the floor changed ----
        new_floor = _to_num(prod.get(FLOOR_COLUMN))
        if new_floor is not None and new_floor > 0:
            prev = existing_by_id.get(pid)
            prev_floor = _to_num(prev.get(FLOOR_COLUMN)) if prev else None
            if prev_floor is None or prev_floor != new_floor:
                history_rows.append([
                    today,
                    pid,
                    prod.get("name", ""),
                    prod.get("category", ""),
                    new_floor,
                    prod.get("storePrice", ""),
                    prod.get("market_totalListings", ""),
                ])

        # ---- catalogue upsert ----
        record = {k: _cell(v) for k, v in prod.items()}
        if pid in merged:
            prev = merged[pid]
            record[FIRST_SEEN] = prev.get(FIRST_SEEN) or now
            record[LAST_SEEN] = now
            for k, v in prev.items():
                record.setdefault(k, v)
            merged[pid] = record
            updated += 1
        else:
            record[FIRST_SEEN] = now
            record[LAST_SEEN] = now
            merged[pid] = record
            added += 1

    # ---- Build & write the catalogue grid ----
    all_keys: set = set()
    for rec in merged.values():
        all_keys.update(rec.keys())
    columns = _order_columns(all_keys)

    grid: List[List[Any]] = [columns]
    for rec in sorted(
        merged.values(),
        key=lambda r: (str(r.get(FIRST_SEEN, "")), str(r.get("name", ""))),
        reverse=True,
    ):
        grid.append([rec.get(col, "") for col in columns])

    ws.clear()
    ws.update(range_name="A1", values=grid, value_input_option="RAW")
    try:
        ws.freeze(rows=1)
        ws.format("1:1", {"textFormat": {"bold": True}})
    except Exception:
        pass

    # ---- Append price history ----
    hist_appended = _append_history(sh, history_tab, history_rows)

    return {
        "added": added,
        "updated": updated,
        "total": len(merged),
        "history_added": hist_appended,
    }


def _append_history(sh, history_tab: str, rows: List[List[Any]]) -> int:
    hw = _open_worksheet(sh, history_tab, cols=len(HISTORY_HEADER))
    # Ensure a header row exists.
    first_row = hw.row_values(1)
    if not first_row:
        hw.update(range_name="A1", values=[HISTORY_HEADER], value_input_option="RAW")
        try:
            hw.freeze(rows=1)
            hw.format("1:1", {"textFormat": {"bold": True}})
        except Exception:
            pass
    if rows:
        hw.append_rows(rows, value_input_option="RAW")
    return len(rows)


def _cell(v: Any) -> Any:
    """Coerce a value to something a sheet cell accepts."""
    if v is None:
        return ""
    if isinstance(v, (str, int, float, bool)):
        return v
    try:
        return json.dumps(v, ensure_ascii=False)
    except Exception:
        return str(v)
