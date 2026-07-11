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

HISTORIQUE (12/07) : le feed est plafonne a ~750 ventes (mur serveur), mais
la DECOMPO BURNS de jetonveve (data/burns_split_daily.csv, public) donne le
volume OMI exact des ventes NFT par jour depuis la genese StackR. On la
recupere a chaque run et on convertit avec le COURS OMI HISTORIQUE quotidien
(CryptoCompare histoday, repli gate.io OMI_USDT). Les jours couverts par le
feed gardent leurs chiffres exacts ; les autres viennent de la decompo
(source='burns') et se remplissent au fil du backfill decompo. Desactiver :
SALES_HISTORY=false.

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
REVENUE_HEADER = ["date", "sales", "omi", "omi_usd", "usd", "source"]
SPLIT_URL = os.environ.get("SALES_SPLIT_URL",
    "https://raw.githubusercontent.com/fanablefrance/jetonveve/main/"
    "data/burns_split_daily.csv")
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
    """Les timeframes larges (30d+) sont LOURDS cote serveur (tri de toutes
    les ventes) : timeout genereux (SALES_TIMEOUT, 90 s) + 4 tentatives."""
    url = BASE + op + "?input=" + urllib.parse.quote(
        json.dumps(payload, separators=(",", ":")))
    tmo = float(os.environ.get("SALES_TIMEOUT", "90"))
    last = None
    for attempt in range(1, 5):
        t_req = time.time()
        try:
            r = requests.get(url, headers=_headers(), timeout=tmo)
            if r.status_code == 200 and "json" in r.headers.get(
                    "content-type", ""):
                return r.json()
            last = "HTTP %s ct=%s %s" % (r.status_code,
                                         r.headers.get("content-type", ""),
                                         r.text[:120])
        except Exception as e:
            last = "%s (apres %.0fs)" % (type(e).__name__, time.time() - t_req)
        print("    %s tentative %d/4 KO : %s — nouvel essai dans %ds..."
              % (op.split(".")[-1], attempt, last, 5 * attempt), flush=True)
        time.sleep(5 * attempt)
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
    t0 = time.time()
    pause = float(os.environ.get("SALES_PAUSE", "0.3"))
    print("Collecte des ventes : timeframe=%s, 50/page, timeout=%ss "
          "(les fenetres larges mettent du temps a repondre cote StackR "
          "sur la 1re page — c'est normal, on patiente)..."
          % (timeframe, os.environ.get("SALES_TIMEOUT", "90")), flush=True)
    while True:
        j = {"limit": "50", "elementType": None, "edition": None,
             "rarity": None, "timeframe": timeframe, "sortby": "timestamp",
             "sortDirection": "desc", "direction": "forward"}
        if cursor is not None:
            j["cursor"] = cursor
        payload = {"json": j, "meta": {"values": {
            "elementType": ["undefined"], "edition": ["undefined"],
            "rarity": ["undefined"]}, "v": 1}}
        try:
            data = _get("publicVeve.getAllLatestSales_v2", payload)
        except RuntimeError as e:
            # MUR SERVEUR constate le 11/07 : HTTP 500 systematique vers le
            # curseur ~750 (pagination profonde cassee cote StackR, toutes
            # fenetres). On GARDE la recolte partielle : le quotidien 1d
            # (~300 ventes) ne touche jamais ce mur ; l'historique lointain
            # viendra de la decompo burns (volume OMI par settle).
            print("    MUR au curseur %s : %s — on garde les %d ventes "
                  "recoltees." % (cursor, str(e)[:90], len(out)), flush=True)
            break
        items = (((data.get("result") or {}).get("data") or {})
                 .get("json") or {}).get("items") or []
        if not items:
            print("    page %d vide — fin de l'historique." % (pages + 1),
                  flush=True)
            break
        out.extend(items)
        pages += 1
        oldest = str(items[-1].get("timestamp") or "")[:16]
        print("    page %3d : +%d ventes (cumul %d), on est remonte au %s "
              "(%.0fs)" % (pages, len(items), len(out), oldest or "?",
                           time.time() - t0), flush=True)
        if len(items) < 50:
            print("    page incomplete — fin de l'historique.", flush=True)
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


def fetch_split_days() -> Dict[str, tuple]:
    """{date_pt -> (nft_sales, omi_volume)} depuis la decompo burns de
    jetonveve (couverture = progression du backfill decompo)."""
    try:
        r = requests.get(SPLIT_URL, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print("  decompo burns indisponible (%s) — historique saute." % e,
              flush=True)
        return {}
    import io as _io
    out: Dict[str, tuple] = {}
    for row in csv.DictReader(_io.StringIO(r.text)):
        d = (row.get("date") or "").strip()
        try:
            n = int(float(row.get("nft_sales") or 0))
            vol = float(row.get("omi_volume") or 0)
        except (TypeError, ValueError):
            continue
        if d and vol > 0:
            out[d] = (n, vol)
    print("  decompo burns : %d jours de volume ventes." % len(out),
          flush=True)
    return out


def fetch_omi_history() -> Dict[str, float]:
    """{date -> cours OMI USD (cloture)} : CryptoCompare puis gate.io."""
    try:
        r = requests.get("https://min-api.cryptocompare.com/data/v2/histoday",
                         params={"fsym": "OMI", "tsym": "USD",
                                 "allData": "true"}, timeout=30)
        data = (r.json().get("Data") or {}).get("Data") or []
        out = {}
        for c in data:
            if c.get("close"):
                d = _dt.datetime.fromtimestamp(
                    int(c["time"]), _dt.timezone.utc).strftime("%Y-%m-%d")
                out[d] = float(c["close"])
        if len(out) > 200:
            print("  cours historiques : %d jours (cryptocompare)."
                  % len(out), flush=True)
            return out
    except Exception as e:
        print("  cryptocompare KO (%s), repli gate.io..." % e, flush=True)
    try:
        r = requests.get("https://api.gateio.ws/api/v4/spot/candlesticks",
                         params={"currency_pair": "OMI_USDT", "interval": "1d",
                                 "limit": "1000"}, timeout=30)
        out = {}
        for c in r.json():          # [ts, vol_quote, close, high, low, open,..]
            d = _dt.datetime.fromtimestamp(
                int(c[0]), _dt.timezone.utc).strftime("%Y-%m-%d")
            out[d] = float(c[2])
        print("  cours historiques : %d jours (gate.io)." % len(out),
              flush=True)
        return out
    except Exception as e:
        print("  gate.io KO aussi (%s) — historique sans conversion." % e,
              flush=True)
        return {}


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
                       split_days: Dict[str, tuple] = None,
                       hist_rates: Dict[str, float] = None) -> List[List]:
    """_MarketRevenue : agregat par jour PT.
    Priorite : jours couverts par le FEED (exacts, source=feed) ; les autres
    viennent de la decompo burns (source=burns, cours historique du jour,
    repli cours actuel)."""
    agg = defaultdict(lambda: [0, 0.0])
    for v in rows.values():
        d = v[2]
        agg[d][0] += 1
        agg[d][1] += float(v[8] or 0)
    split_days = split_days or {}
    hist_rates = hist_rates or {}
    grid = [list(REVENUE_HEADER)]
    days = sorted(set(agg) | set(split_days))
    for d in days:
        if d in agg:
            n, omi = agg[d]
            r = hist_rates.get(d, rate)
            grid.append([d, int(n), round(omi, 2), r, round(omi * r, 2),
                         "feed"])
        else:
            n, omi = split_days[d]
            r = hist_rates.get(d, rate)
            grid.append([d, int(n), round(omi, 2), r, round(omi * r, 2),
                         "burns"])
    return grid


def write_sheet(grid: List[List]) -> str:
    sheet_id = (os.environ.get("SHEET_ID") or "").strip()
    raw = (os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") or "").strip()
    if not sheet_id or not raw:
        return "secrets absents — CSV seul."
    from scraper.sheets import _client, _open_worksheet
    sh = _client().open_by_key(sheet_id)
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
    split_days, hist_rates = {}, {}
    if os.environ.get("SALES_HISTORY", "true").lower() != "false":
        print("Historique via decompo burns + cours OMI quotidiens :",
              flush=True)
        split_days = fetch_split_days()
        if split_days:
            hist_rates = fetch_omi_history()
    grid = build_revenue_grid(rows, rate, split_days, hist_rates)
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
