"""
Google Sheets sync for the CollectChain activity tracker.

Tabs maintained (same spreadsheet as the catalogue):

1. "ChainActivity"    — append-only, one row per (day, account) per run with
                        mint / market-in / market-out / burn counters split by
                        collectible vs comic. Duplicate (day, account) pairs
                        across runs are fine: counters simply sum when the
                        stats are recomputed. Rows older than RETENTION_DAYS
                        are pruned from the top (keeps the tab ~30 days deep).
2. "ChainStats"       — rewritten each run: 24h / 7j / 30j windows x
                        (all / mints / market) x (all / collectible / comic):
                        NFT transfers, unique active accounts, tx per account.
3. "ChainTopAccounts" — rewritten each run: top 20 most active wallets per
                        window, with a direct collectscan link.
4. "ChainMeta"        — checkpoint (newest processed block/log index) so daily
                        runs only fetch what's new + global chain totals.
5. "ChainRunLog"      — one line per run: your confirmation it worked.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional, Tuple

from scraper.collectchain import ACTIVITY_FIELDS
from scraper.sheets import _client, _open_worksheet, _now

RETENTION_DAYS = 35  # keep a little more than the 30-day window

ACTIVITY_TAB = "ChainActivity"
ITEMS_TAB = "ChainItems"
STATS_TAB = "ChainStats"
TOP_TAB = "ChainTopAccounts"
REVENUE_TAB = "DropRevenue"
REVENUE_SUMMARY_TAB = "RevenueSummary"
META_TAB = "ChainMeta"
RUNLOG_TAB = "ChainRunLog"

ACTIVITY_HEADER = ["date", "account"] + ACTIVITY_FIELDS + ["total"]
ITEMS_HEADER = ["date", "category", "veve_uuid", "name", "rarity", "series",
                "comic_number", "start_year", "total_editions",
                "mints", "market", "burns",
                "unique_minters", "unique_buyers", "unique_sellers"]
REVENUE_HEADER = ["category", "name", "rarity", "series", "veve_uuid",
                  "store_price", "mints_24h", "mints_7j", "mints_30j",
                  "revenue_24h", "revenue_7j", "revenue_30j",
                  "market_24h", "market_7j", "market_30j",
                  "total_editions", "release_amount", "release_date",
                  "veve_url", "match"]
REVENUE_SUMMARY_HEADER = ["window", "category", "mints", "est_revenue",
                          "items_matched", "items_unmatched", "computed_at"]
STATS_HEADER = ["window", "scope", "category", "nft_transfers",
                "unique_accounts", "tx_per_account", "computed_at"]
TOP_HEADER = ["window", "rank", "account", "total", "mints", "market_in",
              "market_out", "collectibles", "comics", "explorer_url"]
RUNLOG_HEADER = ["run_at_utc", "mode", "status", "transfers_fetched", "pages",
                 "activity_rows_added", "rows_pruned", "unique_accounts_24h",
                 "note"]

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


def read_catalogue(spreadsheet_id: str, tab: str = "Catalogue") \
        -> List[Dict[str, Any]]:
    """Catalogue rows (only the columns the revenue join needs)."""
    wanted = {"veve_uuid", "name", "category", "rarity", "storePrice",
              "series_uuid", "image_url", "releaseDate", "releaseAmount",
              "veve_url"}
    sh = _sheet(spreadsheet_id)
    try:
        ws = sh.worksheet(tab)
    except Exception:
        return []
    values = ws.get_all_values()
    if len(values) < 2:
        return []
    header = values[0]
    keep = [i for i, h in enumerate(header) if h in wanted]
    out = []
    for raw in values[1:]:
        out.append({header[i]: (raw[i] if i < len(raw) else "") for i in keep})
    return out


# ---------------------------------------------------------------------------
# DropRevenue / RevenueSummary (rewritten each run)
# ---------------------------------------------------------------------------

def write_revenue(spreadsheet_id: str, rev_rows: List[Dict[str, Any]],
                  summary_rows: List[Dict[str, Any]]) -> None:
    sh = _sheet(spreadsheet_id)
    stamp = _now()

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

    ws2 = _open_worksheet(sh, REVENUE_SUMMARY_TAB,
                          cols=len(REVENUE_SUMMARY_HEADER))
    grid2 = [REVENUE_SUMMARY_HEADER] + [
        [s["window"], s["category"], s["mints"], s["est_revenue"],
         s["items_matched"], s["items_unmatched"], stamp]
        for s in summary_rows
    ]
    ws2.clear()
    ws2.update(range_name="A1", values=grid2, value_input_option="RAW")
    try:
        ws2.freeze(rows=1)
        ws2.format("1:1", {"textFormat": {"bold": True}})
    except Exception:
        pass


# ---------------------------------------------------------------------------
# ChainStats / ChainTopAccounts (rewritten each run)
# ---------------------------------------------------------------------------

def write_stats(spreadsheet_id: str, stats: List[Dict[str, Any]],
                top: List[Dict[str, Any]]) -> None:
    sh = _sheet(spreadsheet_id)
    stamp = _now()

    ws = _open_worksheet(sh, STATS_TAB, cols=len(STATS_HEADER))
    grid = [STATS_HEADER] + [
        [s["window"], s["scope"], s["category"], s["nft_transfers"],
         s["unique_accounts"], s["tx_per_account"], stamp]
        for s in stats
    ]
    ws.clear()
    ws.update(range_name="A1", values=grid, value_input_option="RAW")
    try:
        ws.freeze(rows=1)
        ws.format("1:1", {"textFormat": {"bold": True}})
    except Exception:
        pass

    ws2 = _open_worksheet(sh, TOP_TAB, cols=len(TOP_HEADER))
    grid2 = [TOP_HEADER] + [[t.get(c, "") for c in TOP_HEADER] for t in top]
    ws2.clear()
    ws2.update(range_name="A1", values=grid2, value_input_option="RAW")
    try:
        ws2.freeze(rows=1)
        ws2.format("1:1", {"textFormat": {"bold": True}})
    except Exception:
        pass


def append_chain_runlog(spreadsheet_id: str, summary: Dict[str, Any]) -> None:
    sh = _sheet(spreadsheet_id)
    ws = _open_worksheet(sh, RUNLOG_TAB, cols=len(RUNLOG_HEADER))
    _ensure_header(ws, RUNLOG_HEADER)
    ws.append_rows([[
        _now(), summary.get("mode", ""), summary.get("status", ""),
        summary.get("transfers_fetched", ""), summary.get("pages", ""),
        summary.get("activity_rows_added", ""), summary.get("rows_pruned", ""),
        summary.get("unique_accounts_24h", ""), summary.get("note", ""),
    ]], value_input_option="RAW")
