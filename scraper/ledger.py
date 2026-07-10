"""
Analytics — GRAND LIVRE + PROFILS + CORNERISATION (finalites 2/4/5/6).

Rejoue l'archive des transferts CollectChain (Release "chain-archive" du repo
astronema) pour reconstruire, par EDITION (uuid, edition), toute la chaine de
proprietaires. En derive :

  * le grand livre       -> data/ledger.csv.gz        (uuid, edition, holder, listed)
  * le profil par wallet -> data/wallet_profiles.csv.gz + onglet 📊A-WHALES
       holdings, acquis (mint+achat), ventes, retention, duree de detention
       mediane, CollectorScore (7 tiers), last_active, activityStatus (6 tiers)
  * la CORNERISATION     -> onglet 📊A-CORNERISATION (1 ligne/collectible)
       circulating, holders, Gini, top1..top10 (nb+%), % petits/moyens/gros
       portefeuilles, score dominant, activite dominante.

CollectorScore (carte blanche, retention = holdings_now / acquis) :
    Diamond-Hands >=0.95 . Serious >=0.75 . Collector >=0.50 . Trader >=0.30 .
    Flipper >=0.15 . Seasoned >=0.05 . Aggressive <0.05
    + si la duree mediane de detention des editions REVENDUES < 7 j, on descend
      d'un cran vers flipper (revend vite). Wallets avec acquis<3 = "n/a".
Escrow transparent : lister (wallet->escrow) ne compte PAS comme une vente ;
seule la vente reelle (escrow->acheteur) transfere la propriete.

ActivityStatus (jours depuis last_active on-chain, seuils Preda) :
    Active<=7 . Engaged<=30 . Dormant<=90 . Lapsed<=180 . Inactive<=365 . Ghost>365

Taille de portefeuille : small<=10 . mid 11-99 . whale>=100 (nb total detenu).

/!\ EXACT quand le scan CollectChain est TERMINE. Avant : partiel.

Env : GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID, ARCHIVE_DIR (defaut "dl"),
      WHALES_TOP (200), LEDGER_OUT (data/ledger.csv.gz),
      PROFILES_OUT (data/wallet_profiles.csv.gz), RUN_DATE (override du jour, test).
"""

from __future__ import annotations

import csv
import datetime as _dt
import glob
import gzip
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from typing import Dict, List, Tuple

from scraper.sheets import _client, _open_worksheet, append_log
from scraper import sheet_format as _fmt

try:
    from scraper.collectchain import ZERO, MARKET_ESCROW, BURN_SINK
except Exception:
    ZERO = "0x0000000000000000000000000000000000000000"
    MARKET_ESCROW = "0xb1af72a77b9065c55cda0680b86655a79b62e42c"
    BURN_SINK = "0x39e3816a8c549ec22cd1a34a8cf7034b3941d8b1"

SYSTEM = {ZERO, MARKET_ESCROW, BURN_SINK, ""}
BURN_TO = {ZERO, BURN_SINK}

WHALES_TAB = "🐋A-WHALES"
CORNER_TAB = "🎯A-CORNERISATION"
SIZE_TAB = "📈H-WALLET-SIZE"
DASH_TAB = "🏠ACCUEIL"
# Typologie whales : 3 tableaux HORIZONTAUX cote a cote (top 100 chacun),
# separes par une colonne vide. 10 colonnes par bloc.
WHALE_BLOCK_COLS = ["rank", "wallet", "pseudo", "metric", "holdings",
                    "distinct", "value_store", "value_floor", "score", "activity"]
WHALE_TYPES = [("Whale Accumulatrice", "holdings"),
               ("Whale Valeur Floor", "value_floor"),
               ("Whale Valeur Store", "value_store")]
SIZE_HEADER = ["snapshot_month", "dimension", "bucket", "wallets", "pct_wallets",
               "total", "pct_total"]
# Colonnes de profil injectees dans 🟣C-PSEUDOS (join wallet_imx).
PSEUDO_PROFILE_COLS = ["holdings", "distinct_collectibles", "acquired", "sold",
                       "retention", "median_hold_days", "collectorScore",
                       "activityStatus", "value_store", "value_floor",
                       "qty_bucket"]
CORNER_HEADER = (["veve_uuid", "name", "category", "circulating", "holders",
                  "gini"]
                 + [f"top{i}_{s}" for i in range(1, 11) for s in ("cnt", "pct")]
                 + ["qty_dominant", "qty_dominant_pct",
                    "vstore_dominant", "vstore_dominant_pct",
                    "vfloor_dominant", "vfloor_dominant_pct",
                    "score_dominant", "score_dominant_pct",
                    "activity_dominant", "activity_dominant_pct"])

# Tranches de QUANTITE (nb d'exemplaires detenus) — demande Preda.
QTY_BUCKETS = [(1, 1, "1"), (2, 10, "2-10"), (11, 50, "11-50"),
               (51, 100, "51-100"), (101, 250, "101-250"), (251, 500, "251-500"),
               (501, 1000, "501-1000"), (1001, 5000, "1001-5000"),
               (5001, float("inf"), "5001+")]
# Tranches de VALEUR (USD) — echelle log large.
VALUE_BUCKETS = [(0, 100, "<100"), (100, 500, "100-500"), (500, 1000, "500-1k"),
                 (1000, 5000, "1k-5k"), (5000, 25000, "5k-25k"),
                 (25000, 100000, "25k-100k"), (100000, 500000, "100k-500k"),
                 (500000, float("inf"), "500k+")]
QTY_ORDER = [b[2] for b in QTY_BUCKETS]
VALUE_ORDER = [b[2] for b in VALUE_BUCKETS]


def qty_bucket(h: int) -> str:
    for lo, hi, lbl in QTY_BUCKETS:
        if lo <= h <= hi:
            return lbl
    return QTY_BUCKETS[-1][2]


def value_bucket(v: float) -> str:
    for lo, hi, lbl in VALUE_BUCKETS:
        if lo <= v < hi:
            return lbl
    return VALUE_BUCKETS[-1][2]


def _num(x):
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _read_prices(sh):
    """{uuid -> (store_price, floor_price)} depuis l'onglet cache _DynState."""
    store, floor = {}, {}
    try:
        ws = sh.worksheet("_DynState")
    except Exception:
        return store, floor
    for r in ws.get_all_records():
        u = str(r.get("veve_uuid", "")).strip().lower()
        if not u:
            continue
        sp = _num(r.get("veve_store_price"))
        fp = _num(r.get("market_lowestOffer"))
        if sp is not None:
            store[u] = sp
        if fp is not None:
            floor[u] = fp
    return store, floor

SCORES = ["Diamond-Hands", "Serious Collector", "Collector", "Trader",
          "Flipper", "Seasoned Flipper", "Aggressive Flipper"]
ACTIVITIES = ["Active", "Engaged", "Dormant", "Lapsed", "Inactive", "Ghost"]


def _ts(x: str):
    x = (x or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return _dt.datetime.strptime(x[:19], fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Rejeu de l'archive : par edition, chaine chrono -> proprietaires + evenements
# ---------------------------------------------------------------------------

def _archive_files(folder: str) -> List[str]:
    files = glob.glob(os.path.join(folder, "*transfers*run*.csv.gz"))
    if not files:
        files = glob.glob(os.path.join(folder, "*.csv.gz"))
    return sorted(files)


def replay(folder: str):
    """Retourne (ledger, profiles, per_uuid, n_transfers).

    ledger    : {(uuid,edition) -> (holder, listed)}
    profiles  : {wallet -> dict(mints,buys,sells,holdings,durations[],first,last)}
    per_uuid  : {uuid -> Counter(holder -> nb editions detenues)}
    """
    # 1) collecter la sequence chrono de chaque edition
    seq: Dict[Tuple[str, str], List] = defaultdict(list)
    n = 0
    for path in _archive_files(folder):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                uid = (r.get("veve_uuid") or "").strip().lower()
                ed = (r.get("edition") or "").strip()
                if not uid or not ed:
                    continue
                ts = _ts(r.get("ts_utc"))
                if ts is None:
                    continue
                seq[(uid, ed)].append((ts, (r.get("from") or "").strip().lower(),
                                       (r.get("to") or "").strip().lower(),
                                       (r.get("date_pt") or "").strip()))
                n += 1

    ledger: Dict[Tuple[str, str], Tuple[str, int]] = {}
    prof: Dict[str, Dict] = {}
    per_uuid: Dict[str, Counter] = defaultdict(Counter)

    def P(w):
        p = prof.get(w)
        if p is None:
            p = prof[w] = {"mints": 0, "buys": 0, "sells": 0, "holdings": 0,
                           "durations": [], "first": "", "last": ""}
        return p

    for (uid, ed), trs in seq.items():
        trs.sort(key=lambda x: x[0])           # chrono ASC
        holder = None                           # proprietaire reel courant
        seg_start = None
        listed = 0
        for ts, frm, to, day in trs:
            # activite on-chain (min/max) pour les wallets reels
            for w in (frm, to):
                if w and w not in SYSTEM:
                    p = P(w)
                    if not p["first"] or day < p["first"]:
                        p["first"] = day
                    if day > p["last"]:
                        p["last"] = day
            if to == MARKET_ESCROW:
                listed = 1                       # mise en vente : proprio inchange
                continue
            listed = 0
            if holder is not None and to == holder:
                continue                         # annulation escrow->vendeur : no-op
            # cession du proprietaire courant
            if holder is not None and holder not in SYSTEM:
                p = P(holder)
                p["sells"] += 1
                if seg_start is not None:
                    p["durations"].append((ts - seg_start).total_seconds() / 86400.0)
            if to in BURN_TO:
                holder = None
                seg_start = None
                continue
            # acquisition par `to`
            if to and to not in SYSTEM:
                p = P(to)
                if holder is None and frm == ZERO:
                    p["mints"] += 1
                else:
                    p["buys"] += 1
            holder = to
            seg_start = ts
        # etat final de l'edition
        if holder and holder not in SYSTEM:
            ledger[(uid, ed)] = (holder, listed)
            P(holder)["holdings"] += 1
            per_uuid[uid][holder] += 1
        else:
            ledger[(uid, ed)] = ("", 0)          # brulee / systeme
    return ledger, prof, per_uuid, n


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def collector_score(p: Dict) -> str:
    acq = p["mints"] + p["buys"]
    if acq < 3:
        return "n/a"
    r = p["holdings"] / acq if acq else 0.0
    idx = (0 if r >= 0.95 else 1 if r >= 0.75 else 2 if r >= 0.50 else
           3 if r >= 0.30 else 4 if r >= 0.15 else 5 if r >= 0.05 else 6)
    # affinage vitesse : revend vite -> +1 cran vers flipper (borne a Flipper mini)
    if p["durations"]:
        md = statistics.median(p["durations"])
        if md < 7 and idx < 4:
            idx += 1
    return SCORES[idx]


def activity_status(last: str, today: _dt.date) -> str:
    try:
        d = _dt.date.fromisoformat(last)
    except (ValueError, TypeError):
        return "Ghost"
    days = (today - d).days
    return ("Active" if days <= 7 else "Engaged" if days <= 30 else
            "Dormant" if days <= 90 else "Lapsed" if days <= 180 else
            "Inactive" if days <= 365 else "Ghost")


def _gini(counts: List[int]) -> float:
    xs = sorted(counts)
    n = len(xs)
    s = sum(xs)
    if n == 0 or s == 0:
        return 0.0
    cum = sum((i + 1) * x for i, x in enumerate(xs))
    return round((2 * cum) / (n * s) - (n + 1) / n, 4)


# ---------------------------------------------------------------------------
# Sheet I/O
# ---------------------------------------------------------------------------

def _read_pseudos(sh) -> Dict[str, str]:
    out = {}
    try:
        ws = sh.worksheet("🟣C-PSEUDOS")
    except Exception:
        return out
    for r in ws.get_all_records():
        w = str(r.get("wallet_imx", "")).strip().lower()
        u = str(r.get("username", "")).strip()
        if w and u:
            out[w] = u
    return out


def _read_names(sh) -> Dict[str, Tuple[str, str]]:
    out = {}
    for tab, cat in (("🔵C-COLLECTIBLE", "collectible"), ("🟢C-COMICS", "comic")):
        try:
            ws = sh.worksheet(tab)
        except Exception:
            continue
        for r in ws.get_all_records():
            u = str(r.get("veve_uuid", "")).strip().lower()
            if u:
                out[u] = (str(r.get("name", "")), cat)
    return out


def _write(sh, tab, header, rows):
    ws = _open_worksheet(sh, tab, cols=len(header))
    ws.clear()
    grid = [header] + rows
    for i in range(0, len(grid), 50000):
        chunk = grid[i:i + 50000]
        if i == 0:
            ws.update(range_name="A1", values=chunk, value_input_option="RAW")
        else:
            ws.append_rows(chunk, value_input_option="RAW")
    try:
        ws.freeze(rows=1)
        ws.format("1:1", {"textFormat": {"bold": True}})
    except Exception:
        pass


def _dominant(dist: Counter, order: List[str]):
    total = sum(dist.values())
    if not total:
        return "", 0
    best = max(order, key=lambda k: dist.get(k, 0))
    return best, round(100.0 * dist.get(best, 0) / total, 1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_all(folder: str, sh, top: int, today: _dt.date):
    ledger, prof, per_uuid, n = replay(folder)
    print(f"Rejeu : {len(ledger)} editions, {len(prof)} wallets, {n} transferts.",
          flush=True)

    pseudos = _read_pseudos(sh)
    names = _read_names(sh)
    store_price, floor_price = _read_prices(sh)
    print(f"Prix : {len(store_price)} store, {len(floor_price)} floor.", flush=True)

    # valeur de chaque portefeuille (store & floor) depuis per_uuid
    value_store = Counter()
    value_floor = Counter()
    for uid, holders in per_uuid.items():
        ps = store_price.get(uid)
        pf = floor_price.get(uid)
        pf_eff = pf if pf is not None else ps      # floor sinon store
        for w, c in holders.items():
            if ps is not None:
                value_store[w] += c * ps
            if pf_eff is not None:
                value_floor[w] += c * pf_eff

    # profil enrichi par wallet
    score, activity, qbk, vsbk, vfbk = {}, {}, {}, {}, {}
    for w, p in prof.items():
        score[w] = collector_score(p)
        activity[w] = activity_status(p["last"], today)
        qbk[w] = qty_bucket(p["holdings"])
        vsbk[w] = value_bucket(value_store.get(w, 0))
        vfbk[w] = value_bucket(value_floor.get(w, 0))

    # holdings/listed/distinct par wallet (1 passe sur le grand livre)
    listed_cnt = Counter()
    distinct = defaultdict(set)
    for (u, e), (hd, ls) in ledger.items():
        if hd:
            distinct[hd].add(u)
            if ls:
                listed_cnt[hd] += 1

    # profil complet par wallet (pour 🟣C-PSEUDOS + typologie)
    profiles = {}
    for w, p in prof.items():
        if p["holdings"] <= 0:
            continue
        acq = p["mints"] + p["buys"]
        md = round(statistics.median(p["durations"]), 1) if p["durations"] else ""
        profiles[w] = {
            "holdings": p["holdings"], "distinct_collectibles": len(distinct[w]),
            "acquired": acq, "sold": p["sells"],
            "retention": round(p["holdings"] / acq, 3) if acq else "",
            "median_hold_days": md, "collectorScore": score[w],
            "activityStatus": activity[w],
            "value_store": round(value_store.get(w, 0), 2),
            "value_floor": round(value_floor.get(w, 0), 2),
            "qty_bucket": qbk[w], "pseudo": pseudos.get(w, ""),
            "last_active": p["last"], "listed": listed_cnt.get(w, 0)}

    # TYPOLOGIE des whales : 3 blocs (top `top` par critere)
    whale_blocks = []
    for title, key in WHALE_TYPES:
        ranked = sorted(profiles.items(), key=lambda kv: -kv[1][key])[:top]
        rows = [[rank, w, pr["pseudo"], pr[key], pr["holdings"],
                 pr["distinct_collectibles"], pr["value_store"], pr["value_floor"],
                 pr["collectorScore"], pr["activityStatus"]]
                for rank, (w, pr) in enumerate(ranked, 1)]
        whale_blocks.append((title, rows))

    # CORNERISATION : 1 ligne/collectible
    corner = []
    for uid, holders in per_uuid.items():
        counts = sorted(holders.items(), key=lambda x: -x[1])
        circ = sum(c for _w, c in counts)
        nm, cat = names.get(uid, ("", ""))
        row = [uid, nm, cat, circ, len(holders), _gini([c for _w, c in counts])]
        for i in range(10):
            if i < len(counts):
                cnt = counts[i][1]
                row += [cnt, round(100.0 * cnt / circ, 2) if circ else 0]
            else:
                row += ["", ""]
        # ventilation de l'offre par bucket qty / valeur / score / activite
        b_qty, b_vs, b_vf, b_sc, b_ac = (Counter(), Counter(), Counter(),
                                         Counter(), Counter())
        for w, c in counts:
            b_qty[qbk.get(w, "1")] += c
            b_vs[vsbk.get(w, "<100")] += c
            b_vf[vfbk.get(w, "<100")] += c
            b_sc[score.get(w, "n/a")] += c
            b_ac[activity.get(w, "Ghost")] += c
        for dist, order in ((b_qty, QTY_ORDER), (b_vs, VALUE_ORDER),
                            (b_vf, VALUE_ORDER), (b_sc, SCORES + ["n/a"]),
                            (b_ac, ACTIVITIES)):
            d, pct = _dominant(dist, order)
            row += [d, pct]
        corner.append(row)
    corner.sort(key=lambda r: -r[3])

    # DISTRIBUTION GLOBALE des wallets par taille (quantite + valeur)
    size_rows = _size_distribution(prof, value_store, value_floor)

    return ledger, prof, whale_blocks, corner, size_rows, profiles


def _size_distribution(prof, value_store, value_floor):
    """Reproduit la table 'wallet_size' : par bucket, nb wallets + total detenu."""
    rows = []
    # QUANTITE
    w_by, tok_by = Counter(), Counter()
    tot_w = tot_tok = 0
    for w, p in prof.items():
        h = p["holdings"]
        if h <= 0:
            continue
        b = qty_bucket(h)
        w_by[b] += 1
        tok_by[b] += h
        tot_w += 1
        tot_tok += h
    for _lo, _hi, b in QTY_BUCKETS:
        rows.append(["quantity", b, w_by.get(b, 0),
                     round(100.0 * w_by.get(b, 0) / tot_w, 2) if tot_w else 0,
                     tok_by.get(b, 0),
                     round(100.0 * tok_by.get(b, 0) / tot_tok, 2) if tot_tok else 0])
    # VALEUR (store puis floor)
    for dim, values in (("value_store", value_store), ("value_floor", value_floor)):
        w_by, val_by = Counter(), Counter()
        tot_w = tot_val = 0.0
        for w in prof:
            v = values.get(w, 0)
            if v <= 0:
                continue
            b = value_bucket(v)
            w_by[b] += 1
            val_by[b] += v
            tot_w += 1
            tot_val += v
        for _lo, _hi, b in VALUE_BUCKETS:
            rows.append([dim, b, w_by.get(b, 0),
                         round(100.0 * w_by.get(b, 0) / tot_w, 2) if tot_w else 0,
                         round(val_by.get(b, 0), 2),
                         round(100.0 * val_by.get(b, 0) / tot_val, 2) if tot_val else 0])
    return rows


def _save_ledger(ledger, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["veve_uuid", "edition", "holder", "listed"])
        for (u, e), (h, ls) in ledger.items():
            w.writerow([u, e, h, ls])


def _save_profiles(profiles, path):
    cols = ["holdings", "distinct_collectibles", "acquired", "sold", "retention",
            "median_hold_days", "collectorScore", "activityStatus", "value_store",
            "value_floor", "qty_bucket", "pseudo", "last_active", "listed"]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["wallet"] + cols)
        for wl, pr in profiles.items():
            w.writerow([wl] + [pr.get(c, "") for c in cols])


def _write_size_history(sh, size_rows, month):
    """Append-only mensuel : upsert des lignes du mois (📈H-WALLET-SIZE)."""
    ws = _open_worksheet(sh, SIZE_TAB, cols=len(SIZE_HEADER))
    existing = ws.get_all_records() if ws.row_count > 1 else []
    kept = [[r.get(c, "") for c in SIZE_HEADER] for r in existing
            if str(r.get("snapshot_month", "")) != month]
    fresh = [[month] + row for row in size_rows]
    grid = [SIZE_HEADER] + kept + fresh
    ws.clear()
    for i in range(0, len(grid), 50000):
        if i == 0:
            ws.update(range_name="A1", values=grid[:50000], value_input_option="RAW")
        else:
            ws.append_rows(grid[i:i + 50000], value_input_option="RAW")
    try:
        ws.freeze(rows=1)
        ws.format("1:1", {"textFormat": {"bold": True}})
    except Exception:
        pass


def _enrich_pseudos(sh, profiles):
    """Injecte le profil (score/activite/holdings/valeurs) dans 🟣C-PSEUDOS,
    join par wallet_imx. Enrichit TOUTE ligne presente — y compris une whale
    ajoutee manuellement sans pseudo. Preserve les colonnes StackR existantes."""
    from scraper.stackr import PSEUDOS_TAB, PSEUDOS_HEADER
    ws = _open_worksheet(sh, PSEUDOS_TAB, cols=len(PSEUDOS_HEADER))
    rows = ws.get_all_records() if ws.row_count > 1 else []
    if not rows:
        return 0
    updated = 0
    for r in rows:
        w = str(r.get("wallet_imx", "")).strip().lower()
        pr = profiles.get(w)
        if not pr:
            continue
        for c in PSEUDO_PROFILE_COLS:
            r[c] = pr.get(c, "")
        updated += 1
    grid = [PSEUDOS_HEADER] + [[r.get(c, "") for c in PSEUDOS_HEADER] for r in rows]
    ws.clear()
    for i in range(0, len(grid), 20000):
        if i == 0:
            ws.update(range_name="A1", values=grid[:20000], value_input_option="RAW")
        else:
            ws.append_rows(grid[i:i + 20000], value_input_option="RAW")
    try:
        ws.freeze(rows=1)
        ws.format("1:1", {"textFormat": {"bold": True}})
    except Exception:
        pass
    return updated


def _write_whales_horizontal(sh, blocks):
    """3 tableaux cote a cote separes d'une colonne vide (top 100 chacun).
    Ligne 1 = titres, ligne 2 = en-tetes de colonnes, puis les donnees."""
    ncol = len(WHALE_BLOCK_COLS)
    title_row, header_row = [], []
    for bi, (title, _rows) in enumerate(blocks):
        if bi > 0:
            title_row.append("")
            header_row.append("")
        title_row += [title] + [""] * (ncol - 1)
        header_row += list(WHALE_BLOCK_COLS)
    maxlen = max((len(rows) for _t, rows in blocks), default=0)
    data = []
    for i in range(maxlen):
        line = []
        for bi, (_title, rows) in enumerate(blocks):
            if bi > 0:
                line.append("")
            line += rows[i] if i < len(rows) else [""] * ncol
        data.append(line)
    grid = [title_row, header_row] + data
    ws = _open_worksheet(sh, WHALES_TAB, cols=len(title_row))
    ws.clear()
    ws.update(range_name="A1", values=grid, value_input_option="RAW")
    try:
        ws.freeze(rows=2)
        ws.format("1:2", {"textFormat": {"bold": True}})
    except Exception:
        pass


def _bar(pct, width=18):
    """Petite barre Unicode proportionnelle a un pourcentage (0-100)."""
    n = int(round((pct or 0) / 100.0 * width))
    return "█" * n + "░" * (width - n)


def _count_col_a(sh, tab):
    try:
        return max(0, len(sh.worksheet(tab).col_values(1)) - 1)
    except Exception:
        return 0


def _read_marque_counts(sh):
    marques = licences = 0
    try:
        for r in sh.worksheet("🟤C-MARQUE").get_all_records():
            k = str(r.get("kind", "")).strip().lower()
            if k.startswith("marque"):
                marques += 1
            elif k.startswith("licence"):
                licences += 1
    except Exception:
        pass
    return marques, licences


def _read_pseudo_counts(sh):
    total = named = 0
    try:
        for r in sh.worksheet("🟣C-PSEUDOS").get_all_records():
            total += 1
            if str(r.get("username", "")).strip():
                named += 1
    except Exception:
        pass
    return total, named


def _read_new_this_month(sh, today):
    """new_wallets du mois courant depuis 📅A-COHORTES (grain=month)."""
    ym = today.strftime("%Y-%m")
    try:
        for r in sh.worksheet("📅A-COHORTES").get_all_records():
            if str(r.get("grain")) == "month" and str(r.get("period")) == ym:
                return int(r.get("new_wallets") or 0)
    except Exception:
        pass
    return None


def _dist_block(title, counts, order):
    """Lignes [label, count, pct, barre] triees selon `order`."""
    total = sum(counts.values()) or 1
    rows = [[title, "", "", ""]]
    for k in order:
        c = counts.get(k, 0)
        if c == 0 and k not in counts:
            continue
        pct = round(100.0 * c / total, 1)
        rows.append([k, c, pct, _bar(pct)])
    return rows


def _write_dashboard(sh, profiles, whale_blocks, corner, today):
    from collections import Counter
    holders = len(profiles)
    score_c = Counter(p["collectorScore"] for p in profiles.values())
    act_c = Counter(p["activityStatus"] for p in profiles.values())
    qty_c = Counter(p["qty_bucket"] for p in profiles.values())

    n_coll = _count_col_a(sh, "🔵C-COLLECTIBLE")
    n_comics = _count_col_a(sh, "🟢C-COMICS")
    n_marques, n_licences = _read_marque_counts(sh)
    n_pseudo, n_named = _read_pseudo_counts(sh)
    new_month = _read_new_this_month(sh, today)

    # top 3 whales accumulatrices
    acc = whale_blocks[0][1] if whale_blocks else []
    top = []
    for row in acc[:3]:
        # row = [rank, wallet, pseudo, metric, holdings, ...]
        who = row[2] or (row[1][:10] + "...")
        top.append(f"{who} ({int(row[4]):,})".replace(",", " "))

    # item le plus cornerise (gini max)
    gi = CORNER_HEADER.index("gini")
    best = max(corner, key=lambda r: (r[gi] if isinstance(r[gi], (int, float)) else 0),
              default=None)
    corner_item = f"{best[1]} (Gini {best[gi]})" if best else "-"

    stamp = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    grid = [
        ["🏠 VeVe Tracker — Tableau de bord", "", "", f"maj : {stamp}"],
        [""],
        ["📦 CATALOGUE", "", "👥 COMMUNAUTE", ""],
        ["Collectibles", n_coll, "Holders (wallets)", holders],
        ["Comics", n_comics, "Pseudos connus", f"{n_named} / {n_pseudo}"],
        ["Marques", n_marques, "Nouveaux ce mois",
         new_month if new_month is not None else "-"],
        ["Licences", n_licences, "", ""],
        [""],
        ["🐋 TOP WHALES (accumulateurs)", "", "🎯 CONCENTRATION", ""],
        ["1. " + (top[0] if len(top) > 0 else "-"), "", "Item le + corner.", ""],
        ["2. " + (top[1] if len(top) > 1 else "-"), "", corner_item, ""],
        ["3. " + (top[2] if len(top) > 2 else "-"), "", "", ""],
        [""],
    ]
    grid += _dist_block("🧬 COLLECTOR SCORE (part des holders)", score_c,
                        SCORES + ["n/a"])
    grid += [[""]]
    grid += _dist_block("📶 STATUT D'ACTIVITE", act_c, ACTIVITIES)
    grid += [[""]]
    grid += _dist_block("💰 TAILLE DE PORTEFEUILLE (quantite)", qty_c, QTY_ORDER)

    ws = _open_worksheet(sh, DASH_TAB, cols=6)
    ws.clear()
    ws.update(range_name="A1", values=grid, value_input_option="RAW")
    try:  # placer l'accueil en 1er onglet
        sh.batch_update({"requests": [{"updateSheetProperties": {
            "properties": {"sheetId": ws.id, "index": 0},
            "fields": "index"}}]})
    except Exception:
        pass
    try:
        ws.freeze(rows=1)
        # titres de sections en gras
        bold_rows = [1] + [i + 1 for i, r in enumerate(grid)
                           if r and isinstance(r[0], str)
                           and any(r[0].startswith(e) for e in
                                   ("📦", "👥", "🐋",
                                    "🎯", "🧬", "📶",
                                    "💰"))]
        reqs = []
        for rr in bold_rows:
            reqs.append({"repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": rr - 1, "endRowIndex": rr,
                          "startColumnIndex": 0, "endColumnIndex": 6},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold"}})
        if reqs:
            sh.batch_update({"requests": reqs})
    except Exception as e:
        print(f"dashboard format warning: {e}", flush=True)
    return len(grid)


def main() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        print("ERROR: SHEET_ID requis.", file=sys.stderr)
        return 2
    folder = os.environ.get("ARCHIVE_DIR", "dl")
    top = int(os.environ.get("WHALES_TOP", "100"))
    rd = os.environ.get("RUN_DATE")
    today = _dt.date.fromisoformat(rd) if rd else _dt.date.today()

    if not _archive_files(folder):
        print(f"Aucune archive dans '{folder}'.", file=sys.stderr)
        try:
            append_log(sheet_id, "ledger", "FAILED_NO_DATA", f"no gz in {folder}")
        except Exception:
            pass
        return 1

    sh = _client().open_by_key(sheet_id)
    ledger, prof, whale_blocks, corner, size_rows, profiles = build_all(folder, sh, top, today)

    _save_ledger(ledger, os.environ.get("LEDGER_OUT", "data/ledger.csv.gz"))
    _save_profiles(profiles,
                   os.environ.get("PROFILES_OUT", "data/wallet_profiles.csv.gz"))
    _write_whales_horizontal(sh, whale_blocks)             # typologie 🐋 (3 tableaux)
    _write(sh, CORNER_TAB, CORNER_HEADER, corner)          # 🎯
    _write_size_history(sh, size_rows, today.strftime("%Y-%m"))   # 📈 historique
    enriched = _enrich_pseudos(sh, profiles)               # 🟣 profils

    # --- confort visuel : couleurs de tiers + heatmap Gini + formats nombres ---
    try:
        from scraper.stackr import PSEUDOS_HEADER
        _fmt.format_tab(sh, WHALES_TAB, WHALE_BLOCK_COLS + [""] + WHALE_BLOCK_COLS
                        + [""] + WHALE_BLOCK_COLS, header_rows=2)
        _fmt.format_tab(sh, CORNER_TAB, CORNER_HEADER, header_rows=1)
        _fmt.format_tab(sh, SIZE_TAB, SIZE_HEADER, header_rows=1)
        _fmt.format_tab(sh, "🟣C-PSEUDOS", PSEUDOS_HEADER, header_rows=1)
    except Exception as e:
        print(f"formatting warning: {e}", flush=True)

    try:
        _write_dashboard(sh, profiles, whale_blocks, corner, today)
    except Exception as e:
        print(f"dashboard warning: {e}", flush=True)

    summary = {"status": "OK", "editions": len(ledger), "wallets": len(prof),
               "whales_top": top, "collectibles": len(corner),
               "pseudos_enriched": enriched,
               "duration": f"{time.time()-t0:.0f}s"}
    try:
        append_log(sheet_id, "ledger", "OK",
                   "; ".join(f"{k}={v}" for k, v in summary.items() if k != "status"))
    except Exception as e:
        print(f"log warning: {e}", flush=True)
    print(f"Done. {summary}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
