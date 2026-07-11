# -*- coding: utf-8 -*-
"""CHANTIER 7 — prix de vente REELS du marche StackR (endpoint PUBLIC).

Source (capture DevTools Preda 11/07) :
  GET stackr.world/api/trpc/publicVeve.getAllLatestSales_v2?input=<json urlencode>
  -> items[{id, price(OMI), timestamp, edition, nft_id, element_id(=veve_uuid),
     element_type(COLLECTIBLE_TYPE|COMIC_COVER), name, rarity,
     listed_by(+username), buyer(+username)}], pagination par cursor.
  GET publicVeve.getTokenPrices -> omiPrice (USD, uniswap).

Sorties :
  data/stackr_sales.csv        1 ligne/vente (dedup par id, append-only)
  _MarketRevenue (onglet cache) date_pt, sales, omi, omi_usd, usd — upsert ;
                               lu par stats_page (colonne Revenue Market).

PERIMETRE : ventes du marche StackR (OMI). Les ventes in-app VeVe (gems)
n'ont pas de source de prix connue -> Revenue Market = borne basse.
USD = OMI x cours du jour de COLLECTE (approximation assumee).

Env : SALES_TIMEFRAME (1d ; backfill : 7d/30d/1y/all selon ce que l'API
      accepte), SALES_MAX_PAGES (0=jusqu'au bout), SALES_PAUSE (0.3),
      STACKR_COOKIE (optionnel, si l'endpoint exigeait une session),
      SHEET_ID / GOOGLE_SERVICE_ACCOUNT_JSON (onglet), SALES_CSV.
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
import os
import sys
import time
import urllib.parse
from collections import defaultdict
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import requests

BASE = "https://www.stackr.world/api/trpc/"
PT = ZoneInfo("America/Los_Angeles")
SALES_CSV = os.environ.get("SALES_CSV", "data/stackr_sales.csv")
REVENUE_TAB = "_MarketRevenue"
REVENUE_HEADER = ["date", "sales", "omi", "omi_usd", "usd"]
SALES_HEADER = ["id", "ts_utc", "date_pt", "element_id", "element_type",
                "edition", "name", "rarity", "price_omi", "seller", "buyer",
                "seller_username", "buyer_username"]


def _headers() -> Dict[str, str]:
    h = {
        "accept": "application/json",
        "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/126.0.0.0 Safari/537.36"),
        "referer": "https://www.stackr.world/discover/sales",
    }
    ck = (os.environ.get("STACKR_COOKIE") or "").strip()
    if ck:
        h["cookie"] = ck
    return h


def _get(op: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = BASE + op + "?input=" + urllib.parse.quote(
        json.dumps(payload, separators=(",", ":")))
    last = None
    for attempt in range(1, 4):
        try:
            r = requests.get(url, headers=_headers(), timeout=30)
            if r.status_code == 200 and "json" in r.headers.get(
                    "content-type", ""):
                return r.json()
            last = "HTTP %s ct=%s %s" % (r.status_code,
                                         r.headers.get("content-type", ""),
                                         r.text[:120])
        except Exception as e:
            last = str(e)
        time.sleep(2 * attempt)
    raise RuntimeError("%s KO : %s" % (op, last))


def omi_usd() -> float:
    """Cours OMI en USD (uniswap via StackR)."""
    data = _get("publicVeve.getTokenPrices",
                {"json": None, "meta": {"values": ["undefined"], "v": 1}})
    return float(data["result"]["data"]["json"]["omiPrice"])


def fetch_sales(timeframe: str, max_pages: int = 0) -> List[Dict[str, Any]]:
    """Pagine getAllLatestSales_v2 (50/page, cursor 50, 100, ...)."""
    out: List[Dict[str, Any]] = []
    cursor = None
    pages = 0
    pause = float(os.environ.get("SALES_PAUSE", "0.3"))
    while True:
        j = {"limit": "50", "elementType": None, "edition": None,
             "rarity": None, "timeframe": timeframe, "sortby": "timestamp",
             "sortDirection": "desc", "direction": "forward"}
        if cursor is not None:
            j["cursor"] = cursor
        payload = {"json": j, "meta": {"values": {
            "elementType": ["undefined"], "edition": ["undefined"],
            "rarity": ["undefined"]}, "v": 1}}
        data = _get("publicVeve.getAllLatestSales_v2", payload)
        items = (((data.get("result") or {}).get("data") or {})
                 .get("json") or {}).get("items") or []
        if not items:
            break
        out.extend(items)
        pages += 1
        if len(items) < 50:
            break
        if max_pages and pages >= max_pages:
            print("    budget pages atteint (%d)." % max_pages, flush=True)
            break
        cursor = len(out)
        if pause:
            time.sleep(pause)
    print("  %d ventes recuperees (%d pages, timeframe=%s)."
          % (len(out), pages, timeframe), flush=True)
    return out


def _pt(ts: str):
    """'2026-07-11T14:56:52.560Z' -> (iso utc, date PT)."""
    try:
        dt = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (dt.strftime("%Y-%m-%d %H:%M:%S"),
                dt.astimezone(PT).strftime("%Y-%m-%d"))
    except (ValueError, TypeError):
        return "", ""


def load_existing() -> Dict[str, List]:
    rows: Dict[str, List] = {}
    if os.path.exists(SALES_CSV):
        with open(SALES_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows[r["id"]] = [r.get(c, "") for c in SALES_HEADER]
    return rows


def merge_sales(rows: Dict[str, List], items: List[Dict[str, Any]]) -> int:
    new = 0
    for it in items:
        sid = str(it.get("id") or "")
        if not sid or sid in rows:
            continue
        ts_utc, d_pt = _pt(str(it.get("timestamp") or ""))
        if not d_pt:
            continue
        try:
            omi = float(it.get("price") or 0)
        except (TypeError, ValueError):
            omi = 0.0
        rows[sid] = [sid, ts_utc, d_pt,
                     str(it.get("element_id") or "").lower(),
                     str(it.get("element_type") or ""),
                     str(it.get("edition") or ""),
                     str(it.get("name") or ""),
                     str(it.get("rarity") or ""),
                     round(omi, 2),
                     str(it.get("listed_by") or "").lower(),
                     str(it.get("buyer") or "").lower(),
                     str(it.get("listed_by_username") or ""),
                     str(it.get("buyer_username") or "")]
        new += 1
    return new


def save_csv(rows: Dict[str, List]) -> None:
    os.makedirs(os.path.dirname(SALES_CSV) or ".", exist_ok=True)
    tmp = SALES_CSV + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(SALES_HEADER)
        for sid in sorted(rows, key=lambda x: rows[x][1]):   # tri chrono
            w.writerow(rows[sid])
    os.replace(tmp, SALES_CSV)


def build_revenue_grid(rows: Dict[str, List], rate: float,
                       prev: Dict[str, List] = None) -> List[List]:
    """_MarketRevenue : agregat par jour PT. Les jours deja presents gardent
    leur taux historique ; les jours (re)calcules prennent le taux du jour."""
    agg = defaultdict(lambda: [0, 0.0])
    for v in rows.values():
        d = v[2]
        agg[d][0] += 1
        agg[d][1] += float(v[8] or 0)
    prev = prev or {}
    grid = [list(REVENUE_HEADER)]
    for d in sorted(agg):
        n, omi = agg[d]
        old = prev.get(d)
        r = float(old[3]) if old and str(old[3]).strip() else rate
        grid.append([d, int(n), round(omi, 2), r, round(omi * r, 2)])
    return grid


def write_sheet(grid: List[List]) -> str:
    sheet_id = (os.environ.get("SHEET_ID") or "").strip()
    raw = (os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") or "").strip()
    if not sheet_id or not raw:
        return "secrets absents — CSV seul."
    from scraper.sheets import _client, _open_worksheet
    sh = _client().open_by_key(sheet_id)
    prev: Dict[str, List] = {}
    try:
        ws = sh.worksheet(REVENUE_TAB)
        from gspread.utils import ValueRenderOption
        for r in ws.get_all_records(
                value_render_option=ValueRenderOption.unformatted):
            d = str(r.get("date", "")).strip()
            if d:
                prev[d] = [d, r.get("sales"), r.get("omi"),
                           r.get("omi_usd"), r.get("usd")]
    except Exception:
        pass
    # re-fusion avec les taux historiques
    for row in grid[1:]:
        old = prev.get(row[0])
        if old and str(old[3]).strip():
            row[3] = float(old[3])
            row[4] = round(float(row[2]) * row[3], 2)
    ws = _open_worksheet(sh, REVENUE_TAB, cols=len(REVENUE_HEADER))
    ws.clear()
    ws.update(range_name="A1", values=grid, value_input_option="RAW")
    try:
        ws.hide()
    except Exception:
        pass
    return "%s : %d jours." % (REVENUE_TAB, len(grid) - 1)


def main() -> int:
    t0 = time.time()
    timeframe = os.environ.get("SALES_TIMEFRAME", "1d")
    max_pages = int(os.environ.get("SALES_MAX_PAGES", "0") or 0)
    rate = omi_usd()
    print("Cours OMI : %.6f $ (uniswap/StackR)." % rate, flush=True)
    items = fetch_sales(timeframe, max_pages)
    rows = load_existing()
    before = len(rows)
    new = merge_sales(rows, items)
    save_csv(rows)
    grid = build_revenue_grid(rows, rate)
    note = write_sheet(grid)
    print("Sheet:", note, flush=True)
    days = {v[2] for v in rows.values()}
    print("Done. ventes_total=%d (+%d) jours=%d duree=%ds"
          % (len(rows), new, len(days), time.time() - t0), flush=True)
    # apercu des 3 dernieres
    for sid in sorted(rows, key=lambda x: rows[x][1])[-3:]:
        v = rows[sid]
        print("   %s | %s #%s | %s OMI (%s)" % (v[2], v[6][:32], v[5],
                                                v[8], v[12] or v[10][:10]),
              flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("stackr_sales FAILED: %s" % e, file=sys.stderr)
        try:
            from scraper.sheets import append_log
            append_log(os.environ.get("SHEET_ID", ""), "sales", "FAILED",
                       str(e)[:200])
        except Exception:
            pass
        sys.exit(1)
