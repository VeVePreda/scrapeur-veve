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

try:
    from scraper.collectchain import ZERO, MARKET_ESCROW, BURN_SINK
except Exception:
    ZERO = "0x0000000000000000000000000000000000000000"
    MARKET_ESCROW = "0xb1af72a77b9065c55cda0680b86655a79b62e42c"
    BURN_SINK = "0x39e3816a8c549ec22cd1a34a8cf7034b3941d8b1"

SYSTEM = {ZERO, MARKET_ESCROW, BURN_SINK, ""}
BURN_TO = {ZERO, BURN_SINK}

WHALES_TAB = "📊A-WHALES"
CORNER_TAB = "📊A-CORNERISATION"
WHALES_HEADER = ["rank", "wallet", "pseudo", "holdings", "distinct_collectibles",
                 "acquired", "sold", "retention", "median_hold_days",
                 "collectorScore", "last_active", "activityStatus", "listed"]
CORNER_HEADER = (["veve_uuid", "name", "category", "circulating", "holders",
                  "gini"]
                 + [f"top{i}_{s}" for i in range(1, 11) for s in ("cnt", "pct")]
                 + ["pct_small", "pct_mid", "pct_whale",
                    "score_dominant", "score_dominant_pct",
                    "activity_dominant", "activity_dominant_pct"])

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


def _size_bucket(holdings: int) -> str:
    return "small" if holdings <= 10 else "mid" if holdings < 100 else "whale"


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

    # profil enrichi par wallet
    score = {}
    activity = {}
    size = {}
    for w, p in prof.items():
        score[w] = collector_score(p)
        activity[w] = activity_status(p["last"], today)
        size[w] = _size_bucket(p["holdings"])

    pseudos = _read_pseudos(sh)
    names = _read_names(sh)

    # WHALES : top par holdings
    whales = []
    ranked = sorted(((w, p["holdings"]) for w, p in prof.items() if p["holdings"] > 0),
                    key=lambda x: -x[1])[:top]
    for rank, (w, h) in enumerate(ranked, 1):
        p = prof[w]
        acq = p["mints"] + p["buys"]
        md = round(statistics.median(p["durations"]), 1) if p["durations"] else ""
        listed = sum(1 for (u, e), (hd, ls) in ledger.items() if hd == w and ls)
        whales.append([rank, w, pseudos.get(w, ""), h,
                       len({u for (u, e), (hd, _l) in ledger.items() if hd == w}),
                       acq, p["sells"], round(h / acq, 3) if acq else "",
                       md, score[w], p["last"], activity[w], listed])

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
        # ventilation par taille / score / activite (ponderee par nb d'editions)
        by_size, by_score, by_act = Counter(), Counter(), Counter()
        for w, c in counts:
            by_size[size.get(w, "small")] += c
            by_score[score.get(w, "n/a")] += c
            by_act[activity.get(w, "Ghost")] += c
        row += [round(100.0 * by_size["small"] / circ, 1) if circ else 0,
                round(100.0 * by_size["mid"] / circ, 1) if circ else 0,
                round(100.0 * by_size["whale"] / circ, 1) if circ else 0]
        sd, sp = _dominant(by_score, SCORES + ["n/a"])
        ad, ap = _dominant(by_act, ACTIVITIES)
        row += [sd, sp, ad, ap]
        corner.append(row)
    corner.sort(key=lambda r: -r[3])
    return ledger, prof, whales, corner, score, activity


def _save_ledger(ledger, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["veve_uuid", "edition", "holder", "listed"])
        for (u, e), (h, ls) in ledger.items():
            w.writerow([u, e, h, ls])


def _save_profiles(prof, score, activity, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["wallet", "holdings", "acquired", "sold", "retention",
                    "median_hold_days", "collectorScore", "last_active",
                    "activityStatus"])
        for wl, p in prof.items():
            acq = p["mints"] + p["buys"]
            md = round(statistics.median(p["durations"]), 1) if p["durations"] else ""
            w.writerow([wl, p["holdings"], acq, p["sells"],
                        round(p["holdings"] / acq, 3) if acq else "",
                        md, score[wl], p["last"], activity[wl]])


def main() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        print("ERROR: SHEET_ID requis.", file=sys.stderr)
        return 2
    folder = os.environ.get("ARCHIVE_DIR", "dl")
    top = int(os.environ.get("WHALES_TOP", "200"))
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
    ledger, prof, whales, corner, score, activity = build_all(folder, sh, top, today)

    _save_ledger(ledger, os.environ.get("LEDGER_OUT", "data/ledger.csv.gz"))
    _save_profiles(prof, score, activity,
                   os.environ.get("PROFILES_OUT", "data/wallet_profiles.csv.gz"))
    _write(sh, WHALES_TAB, WHALES_HEADER, whales)
    _write(sh, CORNER_TAB, CORNER_HEADER, corner)

    summary = {"status": "OK", "editions": len(ledger), "wallets": len(prof),
               "whales": len(whales), "collectibles": len(corner),
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
