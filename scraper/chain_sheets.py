"""
Google Sheets sync for the CollectChain activity tracker.

Tabs maintained (same spreadsheet as the catalogue):

1. "ChainActivity"    — append-only, one row per (day, account) per run with
                        mint / market-in / market-out / burn counters split by
                        collectible vs comic. Duplicate (day, account) pairs
                        across runs are fine: counters simply sum when the
                        stats are recomputed. Rows older than RETENTION_DAYS
                        are pruned from the top (keeps the tab ~30 days deep).
2. "ChainItems"       — same, per (day, item): raw source of DropRevenue.
3. "DropRevenue"      — rewritten each run: per-item mints / est. revenue /
                        market moves per window (24h/48h/7j/30j/total).
4. "ChainMeta"        — checkpoint (newest processed block/log index) so daily
                        runs only fetch what's new + global chain totals.
                        Kept HIDDEN (technical bookmark, not a page).
5. Unified "Logs" tab — one line per run (see scraper.sheets.append_log).
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional, Tuple

from scraper.collectchain import ACTIVITY_FIELDS, WINDOWS
from scraper.sheets import (_client, _open_worksheet, _now, append_log,
                            summary_details, CATALOGUE_TABS,
                            LEGACY_CATALOGUE_TAB, DYN_STATE_TAB)

RETENTION_DAYS = 35  # keep a little more than the 30-day window

ACTIVITY_TAB = "ChainActivity"
ITEMS_TAB = "ChainItems"
REVENUE_TAB = "DropRevenue"
META_TAB = "ChainMeta"
ESCROW_TAB = "_EscrowListings"  # hidden: (veve_uuid, edition) -> seller wallet
ESCROW_HEADER = ["veve_uuid", "edition", "seller_wallet", "ts"]

ACTIVITY_HEADER = ["date", "account"] + ACTIVITY_FIELDS + ["total"]
ITEMS_HEADER = ["date", "category", "veve_uuid", "name", "rarity", "series",
                "comic_number", "start_year", "total_editions",
                "mints", "market", "burns",
                "unique_minters", "unique_buyers", "unique_sellers"]
REVENUE_HEADER = (["category", "name", "rarity", "series", "veve_uuid",
                   "store_price"]
                  + [f"mints_{l}" for l, _ in WINDOWS]
                  + [f"revenue_{l}" for l, _ in WINDOWS]
                  + [f"market_{l}" for l, _ in WINDOWS]
                  + ["total_editions", "release_amount", "release_date",
                     "veve_url", "match"])

CHUNK = 20000  # rows per write request


def _sheet(spreadsheet_id: str):
    return _client().open_by_key(spreadsheet_id)


def _ensure_header(ws, header: List[str]) -> None:
    if not ws.row_values(1):
        ws.update(range_name="A1", values=[header], value_input_option="RAW")
        try:
            ws.freeze(rows=1)
            ws.format("1:1", {"textFormat": {"bold": True}})
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Checkpoint (ChainMeta)
# ---------------------------------------------------------------------------

def read_checkpoint(spreadsheet_id: str) -> Optional[Tuple[int, int]]:
    """(block_number, log_index) of the newest transfer already processed."""
    sh = _sheet(spreadsheet_id)
    try:
        ws = sh.worksheet(META_TAB)
    except Exception:
        return None
    vals = {r[0]: (r[1] if len(r) > 1 else "") for r in ws.get_all_values() if r}
    try:
        return int(vals["newest_block"]), int(vals.get("newest_log_index", 0) or 0)
    except (KeyError, ValueError):
        return None


def write_meta(spreadsheet_id: str, meta: Dict[str, Any],
               totals: Optional[Dict[str, Any]] = None) -> None:
    sh = _sheet(spreadsheet_id)
    ws = _open_worksheet(sh, META_TAB, cols=2)
    rows = [["key", "value"],
            ["newest_block", meta.get("newest_block") or ""],
            ["newest_log_index", meta.get("newest_log_index") or 0],
            ["newest_ts", meta.get("newest_ts") or ""],
            ["last_run_utc", _now()]]
    for k in ("total_addresses", "total_transactions", "transactions_today"):
        if totals and totals.get(k) is not None:
            rows.append([k, totals[k]])
    ws.clear()
    ws.update(range_name="A1", values=rows, value_input_option="RAW")
    # Technical bookmark, not a page: keep it out of sight.
    try:
        ws.hide()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# ChainActivity (append + prune + full read)
# ---------------------------------------------------------------------------

def append_activity(spreadsheet_id: str, rows: List[Dict[str, Any]],
                    replace: bool = False) -> int:
    sh = _sheet(spreadsheet_id)
    ws = _open_worksheet(sh, ACTIVITY_TAB, cols=len(ACTIVITY_HEADER))
    if replace:
        ws.clear()
    _ensure_header(ws, ACTIVITY_HEADER)
    grid = [[r.get(c, "") for c in ACTIVITY_HEADER] for r in rows]
    for i in range(0, len(grid), CHUNK):
        ws.append_rows(grid[i:i + CHUNK], value_input_option="RAW")
    return len(grid)


def prune_activity(spreadsheet_id: str) -> int:
    """Delete the leading block of rows older than RETENTION_DAYS."""
    cutoff = (_dt.datetime.utcnow() - _dt.timedelta(days=RETENTION_DAYS)) \
        .strftime("%Y-%m-%d")
    sh = _sheet(spreadsheet_id)
    try:
        ws = sh.worksheet(ACTIVITY_TAB)
    except Exception:
        return 0
    dates = ws.col_values(1)  # includes header
    n_old = 0
    for d in dates[1:]:
        if d and d < cutoff:
            n_old += 1
        else:
            break
    if n_old:
        ws.delete_rows(2, 1 + n_old)
    return n_old


def read_activity(spreadsheet_id: str) -> List[Dict[str, Any]]:
    sh = _sheet(spreadsheet_id)
    try:
        ws = sh.worksheet(ACTIVITY_TAB)
    except Exception:
        return []
    values = ws.get_all_values()
    if len(values) < 2:
        return []
    header = values[0]
    out: List[Dict[str, Any]] = []
    for raw in values[1:]:
        row = dict(zip(header, raw))
        for f in ACTIVITY_FIELDS + ["total"]:
            try:
                row[f] = int(row.get(f) or 0)
            except ValueError:
                row[f] = 0
        if row.get("account"):
            out.append(row)
    return out


# ---------------------------------------------------------------------------
# ChainItems (append + prune + full read) — per-item daily counters
# ---------------------------------------------------------------------------

def append_items(spreadsheet_id: str, rows: List[Dict[str, Any]],
                 replace: bool = False) -> int:
    sh = _sheet(spreadsheet_id)
    ws = _open_worksheet(sh, ITEMS_TAB, cols=len(ITEMS_HEADER))
    if replace:
        ws.clear()
    _ensure_header(ws, ITEMS_HEADER)
    grid = [[r.get(c, "") for c in ITEMS_HEADER] for r in rows]
    for i in range(0, len(grid), CHUNK):
        ws.append_rows(grid[i:i + CHUNK], value_input_option="RAW")
    # Backing store for DropRevenue — kept but hidden (not a page to read).
    try:
        ws.hide()
    except Exception:
        pass
    return len(grid)


def prune_items(spreadsheet_id: str) -> int:
    cutoff = (_dt.datetime.utcnow() - _dt.timedelta(days=RETENTION_DAYS)) \
        .strftime("%Y-%m-%d")
    sh = _sheet(spreadsheet_id)
    try:
        ws = sh.worksheet(ITEMS_TAB)
    except Exception:
        return 0
    dates = ws.col_values(1)
    n_old = 0
    for d in dates[1:]:
        if d and d < cutoff:
            n_old += 1
        else:
            break
    if n_old:
        ws.delete_rows(2, 1 + n_old)
    return n_old


def read_items(spreadsheet_id: str) -> List[Dict[str, Any]]:
    sh = _sheet(spreadsheet_id)
    try:
        ws = sh.worksheet(ITEMS_TAB)
    except Exception:
        return []
    values = ws.get_all_values()
    if len(values) < 2:
        return []
    header = values[0]
    out = []
    for raw in values[1:]:
        row = dict(zip(header, raw))
        for f in ("mints", "market", "burns",
                  "unique_minters", "unique_buyers", "unique_sellers"):
            try:
                row[f] = int(row.get(f) or 0)
            except ValueError:
                row[f] = 0
        if row.get("name") or row.get("veve_uuid"):
            out.append(row)
    return out


def read_catalogue(spreadsheet_id: str, tab: str = "") \
        -> List[Dict[str, Any]]:
    """Catalogue rows from the split tabs (+ legacy tab as fallback), only the
    columns the revenue join needs. Since v5 the store price / release amount
    live on the dynamic history, so we merge the latest values per collectible
    from the hidden _DynState tab (comics have no dynamic data -> no price)."""
    wanted = {"veve_uuid", "name", "category", "rarity", "storePrice",
              "veve_store_price", "series_uuid", "image_url", "releaseDate",
              "releaseAmount", "veve_url"}
    sh = _sheet(spreadsheet_id)

    # Latest dynamic values per collectible uuid (store price / release amount).
    dyn: Dict[str, Dict[str, Any]] = {}
    try:
        ws = sh.worksheet(DYN_STATE_TAB)
        for r in ws.get_all_records():
            uid = str(r.get("veve_uuid", "")).strip().lower()
            if uid:
                dyn[uid] = {"veve_store_price": r.get("veve_store_price", ""),
                            "releaseAmount": r.get("releaseAmount", "")}
    except Exception:
        pass

    out: List[Dict[str, Any]] = []
    for tab_name in CATALOGUE_TABS + (LEGACY_CATALOGUE_TAB,):
        try:
            ws = sh.worksheet(tab_name)
        except Exception:
            continue
        values = ws.get_all_values()
        if len(values) < 2:
            continue
        header = values[0]
        keep = [i for i, h in enumerate(header) if h in wanted]
        for raw in values[1:]:
            row = {header[i]: (raw[i] if i < len(raw) else "") for i in keep}
            d = dyn.get(str(row.get("veve_uuid", "")).strip().lower())
            if d:
                if not row.get("veve_store_price"):
                    row["veve_store_price"] = d["veve_store_price"]
                if not row.get("releaseAmount"):
                    row["releaseAmount"] = d["releaseAmount"]
            out.append(row)
    return out


# ---------------------------------------------------------------------------
# DropRevenue (rewritten each run) — per-item detail
# ---------------------------------------------------------------------------

def write_revenue(spreadsheet_id: str, rev_rows: List[Dict[str, Any]]) -> None:
    sh = _sheet(spreadsheet_id)
    ws = _open_worksheet(sh, REVENUE_TAB, cols=len(REVENUE_HEADER))
    grid = [REVENUE_HEADER] + [[r.get(c, "") for c in REVENUE_HEADER]
                               for r in rev_rows]
    ws.clear()
    for i in range(0, len(grid), CHUNK):
        if i == 0:
            ws.update(range_name="A1", values=grid[:CHUNK],
                      value_input_option="RAW")
        else:
            ws.append_rows(grid[i:i + CHUNK], value_input_option="RAW")
    try:
        ws.freeze(rows=1)
        ws.format("1:1", {"textFormat": {"bold": True}})
    except Exception:
        pass


LISTING_TAB = "_ListingDaily"
LISTING_HEADER = ["date", "listings", "listers", "pure_listers",
                  "pure_listings"]


def _int(x) -> int:
    try:
        return int(float(str(x).replace(",", ".").replace(" ", "") or 0))
    except (TypeError, ValueError):
        return 0


def merge_listing_daily(spreadsheet_id: str, rows: List[Dict[str, Any]],
                        replace: bool = False) -> int:
    """Upsert par date dans l'onglet cache _ListingDaily (source du groupe
    LISTING de 📊 STATS — demande Preda 11/07). replace=True (backfill)
    reecrit tout ; retention RETENTION_DAYS comme ChainActivity. Valeurs
    entieres ecrites en RAW (aucun decimal -> insensible a la locale FR)."""
    sh = _sheet(spreadsheet_id)
    ws = _open_worksheet(sh, LISTING_TAB, cols=len(LISTING_HEADER))
    existing: Dict[str, List[int]] = {}
    if not replace and ws.row_count > 1:
        for r in ws.get_all_records():
            d = str(r.get("date", "")).strip()
            if d:
                existing[d] = [_int(r.get(c)) for c in LISTING_HEADER[1:]]
    for r in rows:
        existing[str(r["date"])] = [_int(r.get("listings")),
                                    _int(r.get("listers")),
                                    _int(r.get("pure_listers")),
                                    _int(r.get("pure_listings"))]
    cutoff = (_dt.datetime.utcnow()
              - _dt.timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%d")
    grid = [list(LISTING_HEADER)] + [[d] + existing[d]
                                     for d in sorted(existing) if d >= cutoff]
    ws.clear()
    ws.update(range_name="A1", values=grid, value_input_option="RAW")
    try:
        ws.hide()
    except Exception:
        pass
    return len(grid) - 1


def merge_escrow(spreadsheet_id: str, deposits: List[Dict[str, Any]]) -> int:
    """Merge escrow deposits into the hidden _EscrowListings tab, keeping the
    latest seller wallet per (veve_uuid, edition). Returns count of NEW keys."""
    if not deposits:
        return 0
    sh = _sheet(spreadsheet_id)
    ws = _open_worksheet(sh, ESCROW_TAB, cols=len(ESCROW_HEADER))
    existing: Dict[Tuple[str, str], Dict[str, Any]] = {}
    if ws.row_count > 1:
        for r in ws.get_all_records():
            k = (str(r.get("veve_uuid", "")).strip(), str(r.get("edition", "")).strip())
            if k[0]:
                existing[k] = dict(r)
    added = 0
    for d in deposits:
        k = (str(d["veve_uuid"]).strip(), str(d["edition"]).strip())
        cur = existing.get(k)
        if cur is None:
            added += 1
        if cur is None or str(d["ts"]) > str(cur.get("ts", "")):
            existing[k] = {"veve_uuid": d["veve_uuid"], "edition": d["edition"],
                           "seller_wallet": d["seller_wallet"], "ts": d["ts"]}
    grid = [ESCROW_HEADER] + [[existing[k].get(c, "") for c in ESCROW_HEADER]
                              for k in existing]
    ws.clear()
    for i in range(0, len(grid), CHUNK):
        if i == 0:
            ws.update(range_name="A1", values=grid[:CHUNK], value_input_option="RAW")
        else:
            ws.append_rows(grid[i:i + CHUNK], value_input_option="RAW")
    try:
        ws.hide()
    except Exception:
        pass
    return added


def append_chain_runlog(spreadsheet_id: str, summary: Dict[str, Any]) -> None:
    """Chain-run entry in the unified Logs tab."""
    append_log(spreadsheet_id, "chain", str(summary.get("status", "")),
               summary_details(summary))
