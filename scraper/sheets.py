"""
Google Sheets sync for the VeVe catalogue.

- Authenticates with a service account (JSON provided via env var GOOGLE_SERVICE_ACCOUNT_JSON).
- Maintains one worksheet that holds the full catalogue, one row per product UUID.
- The column set is dynamic: it's the union of every field seen across products,
  so when VeVe exposes new fields they appear automatically as new columns.
- Deduping is by the `id` column. Existing rows are updated in place; genuinely new
  products are appended. A "first_seen" timestamp is stamped on first insert and
  "last_seen" is refreshed every run, so new drops are easy to spot/sort.

The sheet is written in a single batch update for speed (5000+ rows).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Any, Dict, List

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Columns we always want first, in this order, when present.
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
    "first_seen",
    "last_seen",
]

FIRST_SEEN = "first_seen"
LAST_SEEN = "last_seen"

# The column used to uniquely identify a product across runs (dedupe key).
KEY_COLUMN = "veve_uuid"


def _client() -> gspread.Client:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON env var is not set.")
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)


def _open_worksheet(gc: gspread.Client, spreadsheet_id: str, tab: str):
    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab, rows=100, cols=26)
    return ws


def _now() -> str:
    return _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _order_columns(all_keys: set) -> List[str]:
    ordered: List[str] = []
    for k in PREFERRED_ORDER:
        if k in all_keys and k not in ordered:
            ordered.append(k)
    for k in sorted(all_keys):
        if k not in ordered:
            ordered.append(k)
    # Ensure bookkeeping columns exist and sit at the end.
    for bk in (FIRST_SEEN, LAST_SEEN):
        if bk in ordered:
            ordered.remove(bk)
        ordered.append(bk)
    return ordered


def sync_products(
    products: List[Dict[str, Any]],
    spreadsheet_id: str,
    tab: str = "Catalogue",
) -> Dict[str, int]:
    """Upsert products into the sheet. Returns {'added': n, 'updated': m, 'total': t}."""
    gc = _client()
    ws = _open_worksheet(gc, spreadsheet_id, tab)

    # ---- Read existing rows ----
    existing_rows = ws.get_all_records() if ws.row_count > 1 else []
    existing_by_id: Dict[str, Dict[str, Any]] = {}
    for row in existing_rows:
        rid = str(row.get(KEY_COLUMN, "")).strip()
        if rid:
            existing_by_id[rid] = dict(row)

    now = _now()
    added, updated = 0, 0

    merged: Dict[str, Dict[str, Any]] = dict(existing_by_id)

    for prod in products:
        pid = str(prod.get(KEY_COLUMN, "")).strip()
        if not pid:
            continue
        record = {k: _cell(v) for k, v in prod.items()}
        if pid in merged:
            prev = merged[pid]
            record[FIRST_SEEN] = prev.get(FIRST_SEEN) or now
            record[LAST_SEEN] = now
            # keep any prior columns not present this run
            for k, v in prev.items():
                record.setdefault(k, v)
            merged[pid] = record
            updated += 1
        else:
            record[FIRST_SEEN] = now
            record[LAST_SEEN] = now
            merged[pid] = record
            added += 1

    # ---- Build the full grid ----
    all_keys: set = set()
    for rec in merged.values():
        all_keys.update(rec.keys())
    columns = _order_columns(all_keys)

    header = columns
    grid: List[List[Any]] = [header]
    # Stable-ish ordering: newest first_seen on top helps spot new drops.
    for rec in sorted(
        merged.values(),
        key=lambda r: (str(r.get(FIRST_SEEN, "")), str(r.get("name", ""))),
        reverse=True,
    ):
        grid.append([rec.get(col, "") for col in columns])

    # ---- Write in one shot ----
    ws.clear()
    ws.update(
        range_name="A1",
        values=grid,
        value_input_option="RAW",
    )
    # Freeze header + bold it.
    try:
        ws.freeze(rows=1)
        ws.format("1:1", {"textFormat": {"bold": True}})
    except Exception:
        pass

    return {"added": added, "updated": updated, "total": len(merged)}


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
