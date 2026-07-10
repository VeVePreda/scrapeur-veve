"""
📊 STATS — LA page de synthese du Sheet (remplace 🏠ACCUEIL, supprime).

Refonte demandee par Preda (2026-07-10) :
  * une SEULE page de synthese (l'onglet 🏠ACCUEIL est supprime au 1er run) ;
  * bande KPI = totaux des 7 DERNIERS JOURS TERMINES (plus "dernier jour") ;
  * tableau quotidien avec EN-TETE GROUPE sur 2 lignes (ligne 8 = groupes,
    ligne 9 = colonnes) :
        TRANSACTION : Global | Mint | Market | Burn   (Global = M+M+B)
        ACTIF       : Unique | Nouveaux
        REVENUE     : Total | Drop | Market
    (exit Panier moyen, % nouveaux, tx/actif) ;
  * Revenue Market = colonne PRESENTE mais VIDE tant que les prix de vente
    reels ne sont pas collectes (chantier 7) -> Total = Drop pour l'instant ;
  * modules de droite en donnees 7 JOURS (🏆 top series mints, 📦 repartition) ;
  * bloc 🩺 sante des sources en bas de page (module health).

Contrairement a l'ancienne page en formules (#ERROR! fragiles), tout est
calcule ICI en python depuis ChainActivity / ChainItems / _DynState et ecrit
en VALEURS + formats — recalcule a chaque daily (step 7), teste sur mocks.

Definitions :
  * jour = journee PACIFIQUE terminee (ce que collecte chain_run) ;
  * Transactions Global = mints + ventes marche + burns (une vente = 1 mouvement) ;
  * Actifs Unique = wallets distincts actifs dans la journee (hors systeme) ;
  * Nouveaux = wallet jamais vu plus tot DANS LA FENETRE ChainActivity (~35 j) ;
  * Revenue Drop = mints x prix store (_DynState ; collectibles ET comics
    quand le prix est connu).

Env : SHEET_ID, STATS_TAB (defaut "📊 STATS"), STATS_WEEK_DAYS (7),
      STATS_TOP_SERIES (8).
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
import time
from collections import Counter, defaultdict
from typing import Any, Dict, List

from scraper.sheets import _client, _open_worksheet, append_log
from scraper import health as _health

STATS_TAB = os.environ.get("STATS_TAB", "📊 STATS")
OLD_HOME_TAB = "🏠ACCUEIL"          # supprime au 1er run (choix Preda 10/07)

WEEK_DAYS = int(os.environ.get("STATS_WEEK_DAYS", "7"))
TOP_SERIES = int(os.environ.get("STATS_TOP_SERIES", "8"))

TABLE_START_ROW = 10                 # 1re ligne de donnees du tableau quotidien
GROUP_ROW = 8                        # ligne des groupes (fusionnee)
HEADER_ROW = 9                       # ligne des colonnes
MODULE_COL = "L"                     # colonne des modules de droite

ACTIVITY_TAB = "ChainActivity"
ITEMS_TAB = "ChainItems"
DYN_STATE_TAB = "_DynState"

MINT_F = ["mint_collectible", "mint_comic"]
MARKET_F = ["market_in_collectible", "market_in_comic"]   # 1 vente = 1 in
BURN_F = ["burn_collectible", "burn_comic"]


def _n(x) -> int:
    try:
        return int(float(str(x).replace(",", ".").replace(" ", "") or 0))
    except (TypeError, ValueError):
        return 0


def _price(x):
    try:
        v = float(str(x).replace(",", "."))
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Lectures
# ---------------------------------------------------------------------------

def _records(sh, tab) -> List[Dict[str, Any]]:
    try:
        return sh.worksheet(tab).get_all_records()
    except Exception:
        return []


def read_store_prices(sh) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for r in _records(sh, DYN_STATE_TAB):
        u = str(r.get("veve_uuid", "")).strip().lower()
        p = _price(r.get("veve_store_price"))
        if u and p is not None:
            out[u] = p
    return out


# ---------------------------------------------------------------------------
# Calculs
# ---------------------------------------------------------------------------

def compute_daily(activity: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """ChainActivity (date, account, compteurs) -> 1 dict par date, tri DESC.

    nouveaux = comptes dont la 1re apparition dans la fenetre est ce jour-la.
    """
    per: Dict[str, Dict[str, Any]] = {}
    first_seen: Dict[str, str] = {}
    for r in activity:
        d = str(r.get("date", "")).strip()
        a = str(r.get("account", "")).strip().lower()
        if not d or not a:
            continue
        p = per.setdefault(d, {"mint": 0, "market": 0, "burn": 0,
                               "accounts": set()})
        p["mint"] += sum(_n(r.get(f)) for f in MINT_F)
        p["market"] += sum(_n(r.get(f)) for f in MARKET_F)
        p["burn"] += sum(_n(r.get(f)) for f in BURN_F)
        p["accounts"].add(a)
        if a not in first_seen or d < first_seen[a]:
            first_seen[a] = d
    new_by_day = Counter(first_seen.values())
    out = []
    for d in sorted(per, reverse=True):
        p = per[d]
        out.append({"date": d, "mint": p["mint"], "market": p["market"],
                    "burn": p["burn"],
                    "tx": p["mint"] + p["market"] + p["burn"],
                    "uniques": len(p["accounts"]),
                    "accounts": p["accounts"],
                    "new": new_by_day.get(d, 0)})
    return out


def compute_revenue(items: List[Dict[str, Any]],
                    prices: Dict[str, float]) -> Dict[str, float]:
    """{date -> revenue drop} = mints x prix store quand le prix est connu."""
    rev: Dict[str, float] = defaultdict(float)
    for r in items:
        d = str(r.get("date", "")).strip()
        u = str(r.get("veve_uuid", "")).strip().lower()
        m = _n(r.get("mints"))
        p = prices.get(u)
        if d and m and p is not None:
            rev[d] += m * p
    return dict(rev)


def _week_dates(daily: List[Dict[str, Any]]) -> List[str]:
    """Les WEEK_DAYS derniers jours termines presents dans les donnees."""
    if not daily:
        return []
    last = _dt.date.fromisoformat(daily[0]["date"])
    start = (last - _dt.timedelta(days=WEEK_DAYS - 1)).isoformat()
    return [d["date"] for d in daily if d["date"] >= start]


def compute_week(daily, revenue) -> Dict[str, Any]:
    days = set(_week_dates(daily))
    rows = [d for d in daily if d["date"] in days]
    accounts = set()
    for d in rows:
        accounts |= d["accounts"]
    return {
        "start": min(days) if days else "",
        "end": max(days) if days else "",
        "revenue": round(sum(revenue.get(d["date"], 0) for d in rows)),
        "tx": sum(d["tx"] for d in rows),
        "mint": sum(d["mint"] for d in rows),
        "market": sum(d["market"] for d in rows),
        "burn": sum(d["burn"] for d in rows),
        "uniques": len(accounts),
        "new": sum(d["new"] for d in rows),
    }


def compute_top_series(items, week_days: set, top: int = TOP_SERIES):
    """Top series par MINTS sur la semaine (fallback nom d'item)."""
    agg = Counter()
    for r in items:
        if str(r.get("date", "")).strip() not in week_days:
            continue
        m = _n(r.get("mints"))
        if not m:
            continue
        label = str(r.get("series") or "").strip() or \
            str(r.get("name") or "").strip() or "(sans nom)"
        agg[label] += m
    return agg.most_common(top)


def compute_split(items, week_days: set) -> Dict[str, int]:
    """Repartition mints/marche par categorie sur la semaine (+ burns)."""
    out = Counter()
    for r in items:
        if str(r.get("date", "")).strip() not in week_days:
            continue
        cat = "comic" if str(r.get("category", "")) == "comic" else "collectible"
        out[f"mints_{cat}"] += _n(r.get("mints"))
        out[f"market_{cat}"] += _n(r.get("market"))
        out["burns"] += _n(r.get("burns"))
    return dict(out)


# ---------------------------------------------------------------------------
# Construction de la page
# ---------------------------------------------------------------------------

def build_table_grid(daily, revenue, week, now_utc: str) -> List[List]:
    """Grille A1:J.. : titre, bande KPI 7 jours, tableau quotidien groupe."""
    g: List[List] = []
    g.append(["📊  STATS VEVE — ACTIVITÉ ON-CHAIN", "", "", "", "", "", "",
              "", "", "", "", f"maj : {now_utc}"])
    g.append(["Jours pacifiques terminés uniquement · Revenue drop = mints × "
              "prix store · Revenue market : en attente des prix réels "
              "(chantier 7)"])
    g.append([])
    g.append([f"▼  7 DERNIERS JOURS TERMINÉS — du {week['start']} au "
              f"{week['end']}"])
    g.append(["Revenue drop", "Transactions", "Mints", "Market", "Burns",
              "Actifs uniques", "Nouveaux"])
    g.append([week["revenue"], week["tx"], week["mint"], week["market"],
              week["burn"], week["uniques"], week["new"]])
    g.append([])
    g.append(["", "TRANSACTION", "", "", "", "ACTIF", "", "REVENUE", "", ""])
    g.append(["Date", "Global", "Mint", "Market", "Burn", "Unique",
              "Nouveaux", "Total", "Drop", "Market"])
    for d in daily:
        drop = round(revenue.get(d["date"], 0))
        g.append([d["date"], d["tx"], d["mint"], d["market"], d["burn"],
                  d["uniques"], d["new"],
                  drop,           # Total = Drop tant que Market est vide
                  drop,
                  ""])            # Revenue Market : chantier 7
    return g


def build_modules_grid(top_series, split, week) -> List[List]:
    """Grille des modules de droite (colonnes L:M), alignee sur la ligne 8."""
    g: List[List] = []
    g.append(["🏆  TOP SÉRIES — 7 JOURS (mints)", ""])
    g.append(["Série", "Mints"])
    for label, m in top_series:
        g.append([label, m])
    for _ in range(TOP_SERIES - len(top_series)):
        g.append(["", ""])
    g.append(["", ""])
    g.append(["📦  RÉPARTITION — 7 JOURS", ""])
    g.append(["Collectibles — mints", split.get("mints_collectible", 0)])
    g.append(["Comics — mints", split.get("mints_comic", 0)])
    g.append(["Collectibles — marché", split.get("market_collectible", 0)])
    g.append(["Comics — marché", split.get("market_comic", 0)])
    g.append(["Burns", split.get("burns", 0)])
    g.append(["", ""])
    g.append(["ℹ️  NOTES", ""])
    g.append(["• Transactions Global = mints + ventes marché + burns.", ""])
    g.append(["• Revenue drop = mints × prix store (collectibles ET comics "
              "quand le prix est connu).", ""])
    g.append(["• Revenue market : vide en attendant les prix de vente réels "
              "(chantier 7).", ""])
    g.append(["• Nouveaux = wallet jamais vu plus tôt dans la fenêtre "
              "on-chain (~35 j).", ""])
    g.append(["• Page recalculée chaque nuit par le daily (plus de formules).",
              ""])
    return g


def _fmt_requests(ws_id: int, n_daily: int) -> List[Dict]:
    """Mises en forme : fusions, groupes colores, formats de nombres, gel."""
    def rng(r1, r2, c1, c2):
        return {"sheetId": ws_id, "startRowIndex": r1, "endRowIndex": r2,
                "startColumnIndex": c1, "endColumnIndex": c2}

    def bg(r, g_, b):
        return {"red": r / 255.0, "green": g_ / 255.0, "blue": b / 255.0}

    last = TABLE_START_ROW - 1 + max(n_daily, 1)
    reqs: List[Dict] = [
        {"unmergeCells": {"range": rng(0, 60, 0, 14)}},
        {"mergeCells": {"range": rng(0, 1, 0, 10), "mergeType": "MERGE_ALL"}},
        {"mergeCells": {"range": rng(1, 2, 0, 10), "mergeType": "MERGE_ALL"}},
        {"mergeCells": {"range": rng(3, 4, 0, 10), "mergeType": "MERGE_ALL"}},
        {"mergeCells": {"range": rng(7, 8, 1, 5), "mergeType": "MERGE_ALL"}},
        {"mergeCells": {"range": rng(7, 8, 5, 7), "mergeType": "MERGE_ALL"}},
        {"mergeCells": {"range": rng(7, 8, 7, 10), "mergeType": "MERGE_ALL"}},
        {"mergeCells": {"range": rng(7, 8, 11, 13), "mergeType": "MERGE_ALL"}},
        # titre + bande semaine
        {"repeatCell": {"range": rng(0, 1, 0, 10),
                        "cell": {"userEnteredFormat": {"textFormat": {
                            "bold": True, "fontSize": 14}}},
                        "fields": "userEnteredFormat.textFormat"}},
        {"repeatCell": {"range": rng(3, 4, 0, 10),
                        "cell": {"userEnteredFormat": {
                            "backgroundColor": bg(232, 240, 254),
                            "textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat(backgroundColor,textFormat)"}},
        {"repeatCell": {"range": rng(4, 5, 0, 7),
                        "cell": {"userEnteredFormat": {"textFormat": {
                            "bold": True, "foregroundColor": bg(102, 102, 102)}}},
                        "fields": "userEnteredFormat.textFormat"}},
        {"repeatCell": {"range": rng(5, 6, 0, 7),
                        "cell": {"userEnteredFormat": {"textFormat": {
                            "bold": True, "fontSize": 12}}},
                        "fields": "userEnteredFormat.textFormat"}},
        # groupes ligne 8 : bleu / vert / jaune (+ module titre gris)
        {"repeatCell": {"range": rng(7, 8, 1, 5),
                        "cell": {"userEnteredFormat": {
                            "backgroundColor": bg(207, 226, 243),
                            "horizontalAlignment": "CENTER",
                            "textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat(backgroundColor,"
                                  "horizontalAlignment,textFormat)"}},
        {"repeatCell": {"range": rng(7, 8, 5, 7),
                        "cell": {"userEnteredFormat": {
                            "backgroundColor": bg(217, 234, 211),
                            "horizontalAlignment": "CENTER",
                            "textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat(backgroundColor,"
                                  "horizontalAlignment,textFormat)"}},
        {"repeatCell": {"range": rng(7, 8, 7, 10),
                        "cell": {"userEnteredFormat": {
                            "backgroundColor": bg(255, 242, 204),
                            "horizontalAlignment": "CENTER",
                            "textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat(backgroundColor,"
                                  "horizontalAlignment,textFormat)"}},
        # ligne 9 : en-tetes de colonnes
        {"repeatCell": {"range": rng(8, 9, 0, 10),
                        "cell": {"userEnteredFormat": {
                            "backgroundColor": bg(243, 243, 243),
                            "textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat(backgroundColor,textFormat)"}},
        # formats de nombres : compteurs + revenus
        {"repeatCell": {"range": rng(TABLE_START_ROW - 1, last, 1, 7),
                        "cell": {"userEnteredFormat": {"numberFormat": {
                            "type": "NUMBER", "pattern": "#,##0"}}},
                        "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": rng(TABLE_START_ROW - 1, last, 7, 9),
                        "cell": {"userEnteredFormat": {"numberFormat": {
                            "type": "NUMBER", "pattern": "#,##0 $"}}},
                        "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": rng(5, 6, 0, 1),
                        "cell": {"userEnteredFormat": {"numberFormat": {
                            "type": "NUMBER", "pattern": "#,##0 $"}}},
                        "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": rng(5, 6, 1, 7),
                        "cell": {"userEnteredFormat": {"numberFormat": {
                            "type": "NUMBER", "pattern": "#,##0"}}},
                        "fields": "userEnteredFormat.numberFormat"}},
        # largeur de la colonne des modules
        {"updateDimensionProperties": {
            "range": {"sheetId": ws_id, "dimension": "COLUMNS",
                      "startIndex": 11, "endIndex": 12},
            "properties": {"pixelSize": 330}, "fields": "pixelSize"}},
        # gel des 9 premieres lignes
        {"updateSheetProperties": {
            "properties": {"sheetId": ws_id,
                           "gridProperties": {"frozenRowCount": 9}},
            "fields": "gridProperties.frozenRowCount"}},
    ]
    return reqs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def write_stats(sh) -> Dict[str, Any]:
    activity = _records(sh, ACTIVITY_TAB)
    items = _records(sh, ITEMS_TAB)
    prices = read_store_prices(sh)
    daily = compute_daily(activity)
    if not daily:
        raise RuntimeError("ChainActivity vide — page 📊 STATS non touchee.")
    revenue = compute_revenue(items, prices)
    week = compute_week(daily, revenue)
    wdays = set(_week_dates(daily))
    top_series = compute_top_series(items, wdays)
    split = compute_split(items, wdays)

    now_utc = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    table = build_table_grid(daily, revenue, week, now_utc)
    modules = build_modules_grid(top_series, split, week)

    ws = _open_worksheet(sh, STATS_TAB, cols=14)
    ws.clear()
    ws.update(range_name="A1", values=table, value_input_option="RAW")
    ws.update(range_name=f"{MODULE_COL}{GROUP_ROW}", values=modules,
              value_input_option="RAW")
    try:
        sh.batch_update({"requests": _fmt_requests(ws.id, len(daily))})
    except Exception as e:
        print(f"stats format warning: {e}", flush=True)

    # bloc 🩺 sante des sources, sous le tableau (module health)
    anchor = max(_health.ANCHOR_ROW, TABLE_START_ROW + len(daily) + 2)
    try:
        _health.write_health(sh, anchor_row=anchor)
    except Exception as e:
        print(f"health warning: {e}", flush=True)

    # placer 📊 STATS en 1er onglet + supprimer l'ancien 🏠ACCUEIL (choix Preda)
    try:
        sh.batch_update({"requests": [{"updateSheetProperties": {
            "properties": {"sheetId": ws.id, "index": 0},
            "fields": "index"}}]})
    except Exception:
        pass
    try:
        old = sh.worksheet(OLD_HOME_TAB)
        sh.del_worksheet(old)
        print(f"Onglet {OLD_HOME_TAB} supprime (remplace par {STATS_TAB}).",
              flush=True)
    except Exception:
        pass

    return {"days": len(daily), "week_tx": week["tx"],
            "week_revenue": week["revenue"], "top_series": len(top_series)}


def main() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID", "").strip()
    if not sheet_id:
        print("SHEET_ID env var is not set.", file=sys.stderr)
        return 2
    sh = _client().open_by_key(sheet_id)
    try:
        summary = write_stats(sh)
    except Exception as e:
        print(f"stats page FAILED: {e}", file=sys.stderr)
        try:
            append_log(sheet_id, "stats", "FAILED", str(e)[:200])
        except Exception:
            pass
        return 1
    summary["duration"] = f"{time.time() - t0:.0f}s"
    try:
        append_log(sheet_id, "stats", "OK",
                   "; ".join(f"{k}={v}" for k, v in summary.items()))
    except Exception as e:
        print(f"log warning: {e}", flush=True)
    print(f"Page {STATS_TAB} ecrite : {summary}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
