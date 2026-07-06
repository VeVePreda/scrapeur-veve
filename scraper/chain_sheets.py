"""
Google Sheets sync for the CollectChain activity tracker.

Tabs maintained (same spreadsheet as the catalogue):

1. "ChainActivity"    — append-only, one row per (day, account) per run with
                        mint / market-in / market-out / burn counters split by
                        collectible vs comic. Duplicate (day, account) pairs
                        across runs are fine: counters simply sum when the
                        stats are recomputed. Rows older than RETENTION_DAYS
                        are pruned from the top (keeps the tab ~30 days deep).
2. "ChainItems"       — same, per (day, item): raw source of Stats/DropRevenue.
3. "Stats"            — rewritten each run: human-readable page combining the
                        estimated drop revenue and the on-chain activity per
                        window (24h/48h/7j/30j/total) x category.
4. "DropRevenue"      — rewritten each run: per-item mints / est. revenue.
5. "ChainMeta"        — checkpoint (newest processed block/log index) so daily
                        runs only fetch what's new + global chain totals.
                        Kept HIDDEN (technical bookmark, not a page).
6. Unified "Logs" tab — one line per run (see scraper.sheets.append_log).
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional, Tuple

from scraper.collectchain import ACTIVITY_FIELDS, WINDOWS
from scraper.sheets import (_client, _open_worksheet, _now, append_log,
                            summary_details, CATALOGUE_TABS,
                            LEGACY_CATALOGUE_TAB)

RETENTION_DAYS = 35  # keep a little more than the 30-day window

ACTIVITY_TAB = "ChainActivity"
ITEMS_TAB = "ChainItems"
STATS_TAB = "Stats"
REVENUE_TAB = "DropRevenue"
META_TAB = "ChainMeta"

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
    """Catalogue rows from the split tabs (+ legacy tab as fallback),
    only the columns the revenue join needs."""
    wanted = {"veve_uuid", "name", "category", "rarity", "storePrice",
              "series_uuid", "image_url", "releaseDate", "releaseAmount",
              "veve_url"}
    sh = _sheet(spreadsheet_id)
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
            out.append({header[i]: (raw[i] if i < len(raw) else "")
                        for i in keep})
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


# ---------------------------------------------------------------------------
# Stats (rewritten each run) — single human-readable page:
# estimated revenue + on-chain activity per window x category
# ---------------------------------------------------------------------------

_WINDOW_LABELS = {"total": "Total"}
_CATS = ("all", "collectible", "comic")


def write_stats_page(spreadsheet_id: str, stats: List[Dict[str, Any]],
                     rev_summary: List[Dict[str, Any]]) -> None:
    sh = _sheet(spreadsheet_id)
    stamp = _now()

    # -- bloc 1 : revenus estimés (depuis summarize_revenue) --
    rows1 = [["Fenêtre", "Catégorie", "Mints", "Revenu estimé $",
              "Produits matchés", "Produits non matchés"]]
    by_wc = {(s["window"], s["category"]): s for s in rev_summary}
    for lbl, _d in WINDOWS:
        for cat in _CATS:
            s = by_wc.get((lbl, cat))
            if s:
                rows1.append([_WINDOW_LABELS.get(lbl, lbl), cat, s["mints"],
                              s["est_revenue"], s["items_matched"],
                              s["items_unmatched"]])

    # -- bloc 2 : activité on-chain (depuis compute_window_stats) --
    rows2 = [["Fenêtre", "Catégorie", "Transferts", "Mints", "Market",
              "Burns", "Comptes uniques", "Tx/compte"]]
    by_wsc = {(s["window"], s["scope"], s["category"]): s for s in stats}
    for lbl, _d in WINDOWS:
        for cat in _CATS:
            s_all = by_wsc.get((lbl, "all", cat))
            if not s_all:
                continue
            s_mint = by_wsc.get((lbl, "mints", cat), {})
            s_mkt = by_wsc.get((lbl, "market", cat), {})
            t_all = s_all["nft_transfers"]
            t_mint = s_mint.get("nft_transfers", 0)
            t_mkt = s_mkt.get("nft_transfers", 0)
            rows2.append([_WINDOW_LABELS.get(lbl, lbl), cat, t_all, t_mint,
                          t_mkt, t_all - t_mint - t_mkt,
                          s_all["unique_accounts"], s_all["tx_per_account"]])

    grid: List[List[Any]] = [
        ["📊 STATS"],
        [f"Mis à jour {stamp} UTC — fenêtres glissantes ; "
         f"Total = historique conservé ({RETENTION_DAYS} j max). "
         "Revenu estimé = mints on-chain × prix boutique."],
        [],
        ["💰 Revenus estimés"],
        *rows1,
        [],
        ["🔗 Activité on-chain"],
        *rows2,
    ]
    ws = _open_worksheet(sh, STATS_TAB, cols=10)
    ws.clear()
    ws.update(range_name="A1", values=grid, value_input_option="RAW")

    h1 = 5                    # ligne d'en-tête du bloc 1
    h2 = 5 + len(rows1) + 2   # ligne d'en-tête du bloc 2
    try:
        ws.format("A1", {"textFormat": {"bold": True, "fontSize": 16}})
        ws.format("A2", {"textFormat": {"foregroundColor":
                                        {"red": .4, "green": .4, "blue": .4}}})
        ws.format("A4", {"textFormat": {"bold": True, "fontSize": 12}})
        ws.format(f"A{h2 - 1}", {"textFormat": {"bold": True, "fontSize": 12}})
        for rng, col in ((f"A{h1}:F{h1}", {"red": .71, "green": .33, "blue": .04}),
                         (f"A{h2}:H{h2}", {"red": .10, "green": .14, "blue": .49})):
            ws.format(rng, {"textFormat": {"bold": True, "foregroundColor":
                                           {"red": 1, "green": 1, "blue": 1}},
                            "backgroundColor": col})
    except Exception as e:
        print(f"    stats formatting warning: {e}", flush=True)


def append_chain_runlog(spreadsheet_id: str, summary: Dict[str, Any]) -> None:
    """Chain-run entry in the unified Logs tab."""
    append_log(spreadsheet_id, "chain", str(summary.get("status", "")),
               summary_details(summary))
