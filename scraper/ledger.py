"""
Analytics — GRAND LIVRE + PROFILS + CORNERISATION (finalites 2/4/5/6).

DEUX sources complementaires :

  1. SNAPSHOT HOLDERS (Release "holders-snapshot" du repo paolo, holders_scan)
     = l'etat PRESENT exact : pour chaque token, son proprietaire ACTUEL.
     PRIORITAIRE pour tout ce qui est "etat courant" (holdings, cornerisation,
     wallet-size, whales par holdings). Exact des que le scan holders est fini
     — sans attendre le scan des transferts.
  2. ARCHIVE TRANSFERTS (Release "chain-archive" du repo astronema, wallet_scan)
     = l'HISTORIQUE : rejouee par EDITION (uuid, edition) pour le COMPORTEMENT
     (mints/achats/ventes, durees de detention -> CollectorScore, last_active
     -> activityStatus) et pour resoudre le VENDEUR des tokens en escrow.

Fusion : le snapshot prime sur le rejeu pour le detenteur courant ; les cles
absentes du snapshot gardent la valeur du rejeu (snapshot partiel tolere ;
sans snapshot, comportement identique a l'ancien rejeu seul). Un wallet vu au
snapshot mais pas encore dans l'archive a un profil "etat seul" :
collectorScore=n/a, activityStatus="" (comportement inconnu, PAS Ghost).

En derive :

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

ActivityStatus (jours depuis last_active on-chain, bareme FRANCAIS fixe par
Preda le 2026-07-10) :
    Actif<=7 . Engagé<=30 . Somnolant<=90 . Inactif<=180 . Désinscrit<=365 .
    Fantôme au-dela (12-24 mois et plus).

Taille de portefeuille : small<=10 . mid 11-99 . whale>=100 (nb total detenu).

/!\\ Etat courant EXACT quand le snapshot holders est TERMINE (ou, a defaut,
    quand le scan des transferts l'est). Comportement (scores, durees) exact
    seulement quand le scan des transferts est termine.

Env : GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID, ARCHIVE_DIR (defaut "dl"),
      SNAPSHOT_DIR (defaut "dl_snap"), WHALES_TOP (200),
      LEDGER_OUT (data/ledger.csv.gz), PROFILES_OUT (data/wallet_profiles.csv.gz),
      RUN_DATE (override du jour, test).
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
                       "activityStatus", "engagementLevel", "value_store",
                       "value_floor", "qty_bucket"]
CORNER_HEADER = (["veve_uuid", "name", "category", "circulating", "holders",
                  "gini"]
                 + [f"top{i}_{s}" for i in range(1, 11) for s in ("cnt", "pct")]
                 + ["qty_dominant", "qty_dominant_pct",
                    "vstore_dominant", "vstore_dominant_pct",
                    "vfloor_dominant", "vfloor_dominant_pct",
                    "score_dominant", "score_dominant_pct",
                    "activity_dominant", "activity_dominant_pct",
                    "engagement_dominant", "engagement_dominant_pct"])

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
    """{uuid -> (store_price, floor_price)} depuis l'onglet cache _DynState.
    Lecture NON FORMATEE : en locale FR, "6,99" relu via numericise devenait
    699 (virgule avalee) — UNFORMATTED_VALUE renvoie les vrais nombres."""
    store, floor = {}, {}
    try:
        ws = sh.worksheet("_DynState")
    except Exception:
        return store, floor
    try:
        from gspread.utils import ValueRenderOption
        rows = ws.get_all_records(
            value_render_option=ValueRenderOption.unformatted)
    except TypeError:
        rows = ws.get_all_records()
    for r in rows:
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
# Engagement (VeveFox "Engagement Level", seuils valides par Preda 11/07) :
# part des SEMAINES ACTIVES depuis la 1re transaction du wallet.
ENGAGEMENTS = ["Fidèle", "Régulier", "Occasionnel", "Sporadique", "Unique"]
# Pulse mensuel (VeveFox "Monthly Market Pulse") — onglet cache lu par 📊 STATS.
PULSE_TAB = "_MonthlyPulse"
PULSE_HEADER = ["month", "actifs", "nouveaux", "trades", "acheteurs",
                "vendeurs", "tokens_emis", "tokens_airdrop",
                "minters_uniques", "drops", "burns", "listings",
                "acc_net_moy", "acc_net_pos", "acc_net_neg", "churn_pct"]
# AIRDROP (seuils valides par Preda 11/07) : un (jour, uuid) est un airdrop si
# mints >= MIN_MINTS ET minters uniques >= RATIO x mints (~1 exemplaire par
# wallet, ex. Black Pink Heart, Happy New Year Tier1 Gini 0.008). Les mints
# d'airdrop sont SEPARES (jamais jetes) : tokens_airdrop au pulse, colonne
# Airdrop sur 📊 STATS.
AIRDROP_MIN_MINTS = int(os.environ.get("AIRDROP_MIN_MINTS", "2000"))
AIRDROP_MINTER_RATIO = float(os.environ.get("AIRDROP_MINTER_RATIO", "0.9"))
# Bareme d'activite en FRANCAIS (Preda 2026-07-10) — remplace
# Active/Engaged/Dormant/Lapsed/Inactive/Ghost.
ACTIVITIES = ["Actif", "Engagé", "Somnolant", "Inactif", "Désinscrit", "Fantôme"]


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
    """Tranches du scan profond (*run*) + continuite quotidienne (*daily*).
    Les chevauchements entre les deux sont deduplique par (block, log_index)
    dans replay()."""
    files = (glob.glob(os.path.join(folder, "*transfers*run*.csv.gz"))
             + glob.glob(os.path.join(folder, "*transfers*daily*.csv.gz")))
    if not files:
        files = glob.glob(os.path.join(folder, "*.csv.gz"))
    return sorted(set(files))


def _snapshot_files(folder: str) -> List[str]:
    files = glob.glob(os.path.join(folder, "*holders*run*.csv.gz"))
    if not files:
        files = glob.glob(os.path.join(folder, "*.csv.gz"))
    return sorted(files)


def load_snapshot(folder: str):
    """Charge le snapshot des detenteurs ACTUELS (archive holders_scan).

    Retourne (snap, snap_names, skipped) :
      snap       : {(uuid, edition) -> owner}  (owner minuscule, brut : peut
                   etre l'escrow, le coffre ou 0x0 — interprete par merge_state)
      snap_names : {uuid -> (name, category)}  fallback noms pour la cornerisation
      skipped    : lignes sans uuid/edition/token_id (non cle-ables)
    Dedup par token_id : le fichier le plus recent (runNNN croissant) gagne.
    """
    by_token: Dict[str, Tuple[str, str, str]] = {}
    snap_names: Dict[str, Tuple[str, str]] = {}
    skipped = 0
    for path in _snapshot_files(folder):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                uid = (r.get("veve_uuid") or "").strip().lower()
                ed = (r.get("edition") or "").strip()
                tid = (r.get("token_id") or "").strip()
                if not uid or not ed or not tid:
                    skipped += 1
                    continue
                by_token[tid] = (uid, ed, (r.get("owner") or "").strip().lower())
                if uid not in snap_names and (r.get("name") or "").strip():
                    snap_names[uid] = ((r.get("name") or "").strip(),
                                       (r.get("category") or "").strip())
    snap: Dict[Tuple[str, str], str] = {}
    for uid, ed, owner in by_token.values():
        snap[(uid, ed)] = owner
    return snap, snap_names, skipped


def merge_state(replay_ledger, snap):
    """Fusionne rejeu + snapshot : le snapshot (etat PRESENT) prime.

    - owner normal          -> detenteur = owner, listed=0
    - owner escrow          -> token EN VENTE ; vendeur resolu via le rejeu
                               (depot vu dans l'archive) sinon inconnu ("")
    - owner coffre/0x0/vide -> brulee
    Les cles absentes du snapshot gardent la valeur du rejeu (snapshot partiel
    tolere ; sans snapshot, merged == rejeu).
    """
    merged = dict(replay_ledger)
    stats: Counter = Counter()
    for key, owner in snap.items():
        if not owner or owner in BURN_TO:
            merged[key] = ("", 0)
            stats["burned"] += 1
        elif owner == MARKET_ESCROW:
            holder = (replay_ledger.get(key) or ("", 0))[0]
            merged[key] = (holder, 1)
            stats["escrow_resolved" if holder else "escrow_unresolved"] += 1
        else:
            merged[key] = (owner, 0)
            stats["owned"] += 1
    return merged, stats


def _blkey(r) -> Tuple[int, int] | None:
    """Identite on-chain d'un transfert : (block, log_index) — unique sur la
    chaine. Sert a dedupliquer les archives chevauchantes (scan profond vs
    continuite quotidienne) et a ordonner les evenements d'une meme seconde."""
    b = str(r.get("block") or "").strip()
    if not b:
        return None
    try:
        return (int(b), int(str(r.get("log_index") or "0").strip() or 0))
    except ValueError:
        return None


def _week_key(day: str):
    try:
        y, w, _ = _dt.date.fromisoformat(day[:10]).isocalendar()
        return y * 100 + w
    except (ValueError, TypeError):
        return None


def replay(folder: str):
    """Retourne (ledger, prof, n_transfers, pulse_rows).

    ledger : {(uuid,edition) -> (holder, listed)}   etat final vu par l'ARCHIVE
    prof   : {wallet -> dict(mints,buys,sells,durations[],weeks,first,last)}
             = COMPORTEMENT seul ; les holdings courants sont derives ensuite
             du grand livre fusionne (rejeu + snapshot).
    pulse_rows : PULSE MENSUEL (facon VeveFox) agrege pendant la lecture —
             actifs, nouveaux, trades, acheteurs/vendeurs, tokens emis,
             minters uniques, drops, burns, listings, accumulation nette
             (moyenne + comptes net+/net-), churn — depuis la genese.
    Les lignes en double entre archives (meme block+log_index) sont dedupliquees
    par cle AVANT toute agregation.
    """
    # 1) collecter la sequence chrono de chaque edition + agregats mensuels
    seq: Dict[Tuple[str, str], List] = defaultdict(list)
    n = 0
    seen_keys = set()
    monthly: Dict[str, Dict] = {}
    first_month: Dict[str, str] = {}
    uuid_first_mint: Dict[str, str] = {}
    mint_day_uuid: Counter = Counter()   # candidats airdrop (compteur leger)
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
                key = _blkey(r)
                if key is not None:
                    packed = key[0] * 1000000 + key[1]   # int compact (~14M a terme)
                    if packed in seen_keys:
                        continue            # doublon inter-archives
                    seen_keys.add(packed)
                frm = (r.get("from") or "").strip().lower()
                to = (r.get("to") or "").strip().lower()
                day = (r.get("date_pt") or "").strip()
                seq[(uid, ed)].append((ts, frm, to, day, key))
                n += 1
                # ---- pulse mensuel ----
                m = day[:7]
                if not m:
                    continue
                kind = (r.get("kind") or "").strip()
                mo = monthly.setdefault(m, {
                    "mints": 0, "market": 0, "burns": 0, "listings": 0,
                    "actives": set(), "minters": set(), "buyers": set(),
                    "sellers": set(), "net": Counter()})
                if kind == "mint":
                    if to and to not in SYSTEM:
                        mo["mints"] += 1
                        mo["minters"].add(to)
                        mo["actives"].add(to)
                        mo["net"][to] += 1
                        mint_day_uuid[(day, uid)] += 1
                        if m < first_month.get(to, "9999"):
                            first_month[to] = m
                    if m < uuid_first_mint.get(uid, "9999"):
                        uuid_first_mint[uid] = m
                elif kind == "market":
                    mo["market"] += 1
                    for w, delta, grp in ((to, 1, "buyers"),
                                          (frm, -1, "sellers")):
                        if w and w not in SYSTEM:
                            mo[grp].add(w)
                            mo["actives"].add(w)
                            mo["net"][w] += delta
                            if m < first_month.get(w, "9999"):
                                first_month[w] = m
                elif kind == "burn":
                    mo["burns"] += 1
                    if frm and frm not in SYSTEM:
                        mo["actives"].add(frm)
                        mo["net"][frm] -= 1
                        if m < first_month.get(frm, "9999"):
                            first_month[frm] = m
                elif kind == "listing":
                    mo["listings"] += 1
                # vault_mint : mouvement systeme, hors pulse.

    ledger: Dict[Tuple[str, str], Tuple[str, int]] = {}
    prof: Dict[str, Dict] = {}

    def P(w):
        p = prof.get(w)
        if p is None:
            p = prof[w] = {"mints": 0, "buys": 0, "sells": 0,
                           "durations": [], "weeks": set(),
                           "first": "", "last": ""}
        return p

    dups = 0
    for (uid, ed), trs in seq.items():
        # chrono ASC ; a la meme seconde, ordre on-chain (block, log_index) —
        # important pour le dump de migration (des milliers de tx/seconde).
        trs.sort(key=lambda x: (x[0], x[4] or (0, 0)))
        holder = None                           # proprietaire reel courant
        seg_start = None
        listed = 0
        prev_key = None
        for ts, frm, to, day, key in trs:
            if key is not None and key == prev_key:
                dups += 1                        # doublon d'archives chevauchantes
                continue
            prev_key = key
            # activite on-chain (min/max + semaines actives) pour les reels
            wk = _week_key(day)
            for w in (frm, to):
                if w and w not in SYSTEM:
                    p = P(w)
                    if not p["first"] or day < p["first"]:
                        p["first"] = day
                    if day > p["last"]:
                        p["last"] = day
                    if wk is not None:
                        p["weeks"].add(wk)
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
        else:
            ledger[(uid, ed)] = ("", 0)          # brulee / systeme
    if dups:
        print(f"Rejeu : {dups} doublons d'archives ignores (chevauchement "
              f"scan profond / continuite quotidienne).", flush=True)
    airdrops = _detect_airdrops(folder, mint_day_uuid)
    return ledger, prof, n, _build_pulse(monthly, first_month,
                                         uuid_first_mint, airdrops)


def _detect_airdrops(folder: str, mint_day_uuid: Counter) -> Dict:
    """{(day, uuid) -> mints} des AIRDROPS detectes.

    1re passe (deja faite) : compteur leger de mints par (jour, uuid).
    2e passe CIBLEE : pour les seuls candidats >= AIRDROP_MIN_MINTS, compter
    les minters DISTINCTS (trop couteux en memoire pour 12M+ mints en 1 passe).
    Airdrop si minters >= AIRDROP_MINTER_RATIO x mints (~1 par wallet)."""
    candidates = {k for k, v in mint_day_uuid.items()
                  if v >= AIRDROP_MIN_MINTS}
    if not candidates:
        return {}
    minters: Dict[Tuple[str, str], set] = {k: set() for k in candidates}
    for path in _archive_files(folder):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if (r.get("kind") or "").strip() != "mint":
                    continue
                day = (r.get("date_pt") or "").strip()
                uid = (r.get("veve_uuid") or "").strip().lower()
                k = (day, uid)
                if k in minters:
                    to = (r.get("to") or "").strip().lower()
                    if to and to not in SYSTEM:
                        minters[k].add(to)
    out = {}
    for k in candidates:
        m = mint_day_uuid[k]
        if len(minters[k]) >= AIRDROP_MINTER_RATIO * m:
            out[k] = m
            print(f"    AIRDROP detecte : {k[0]} {k[1][:8]}… "
                  f"{m} mints / {len(minters[k])} wallets.", flush=True)
    return out


def _build_pulse(monthly, first_month, uuid_first_mint,
                 airdrops=None) -> List[List]:
    """Lignes du pulse mensuel (chronologique ASC) pour _MonthlyPulse."""
    new_by_m = Counter(first_month.values())
    drops_by_m = Counter(uuid_first_mint.values())
    air_by_m: Counter = Counter()
    for (day, _uid), cnt in (airdrops or {}).items():
        air_by_m[day[:7]] += cnt
    rows: List[List] = []
    prev_actives = None
    for m in sorted(monthly):
        mo = monthly[m]
        act = mo["actives"]
        churn = ""
        if prev_actives:
            gone = sum(1 for w in prev_actives if w not in act)
            churn = round(100.0 * gone / len(prev_actives), 1)
        net = mo["net"]
        pos = sum(1 for v in net.values() if v > 0)
        neg = sum(1 for v in net.values() if v < 0)
        avg = round(sum(net.values()) / len(net), 2) if net else 0
        rows.append([m, len(act), new_by_m.get(m, 0), mo["market"],
                     len(mo["buyers"]), len(mo["sellers"]),
                     mo["mints"], air_by_m.get(m, 0),
                     len(mo["minters"]), drops_by_m.get(m, 0),
                     mo["burns"], mo["listings"], avg, pos, neg, churn])
        prev_actives = act
    return rows


def _write_pulse(sh, rows) -> int:
    """Ecrit le pulse mensuel dans l'onglet cache _MonthlyPulse (lu par la
    section 📅 de 📊 STATS). Nombres natifs RAW (locale FR safe)."""
    ws = _open_worksheet(sh, PULSE_TAB, cols=len(PULSE_HEADER))
    ws.clear()
    ws.update(range_name="A1", values=[list(PULSE_HEADER)] + rows,
              value_input_option="RAW")
    try:
        ws.hide()
    except Exception:
        pass
    return len(rows)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def collector_score(p: Dict, holdings: int) -> str:
    """Score depuis le comportement `p` + les holdings COURANTS (fusionnes).
    NB : tant que l'archive est partielle, acquis peut etre sous-estime
    (retention>1 possible) — se resorbe quand le scan des transferts avance."""
    acq = p["mints"] + p["buys"]
    if acq < 3:
        return "n/a"
    r = holdings / acq if acq else 0.0
    idx = (0 if r >= 0.95 else 1 if r >= 0.75 else 2 if r >= 0.50 else
           3 if r >= 0.30 else 4 if r >= 0.15 else 5 if r >= 0.05 else 6)
    # affinage vitesse : revend vite -> +1 cran vers flipper (borne a Flipper mini)
    if p["durations"]:
        md = statistics.median(p["durations"])
        if md < 7 and idx < 4:
            idx += 1
    return SCORES[idx]


def engagement_level(p: Dict, today: _dt.date) -> str:
    """Engagement (VeveFox) : part des SEMAINES ACTIVES depuis la 1re
    transaction. Fidèle>=50% . Régulier>=25% . Occasionnel>=10% .
    Sporadique<10% . Unique = une seule semaine active. n/a sans comportement.
    Legende affichee dans les notes de 📊 STATS uniquement (choix Preda)."""
    weeks = p.get("weeks") or set()
    if not weeks:
        return "n/a"
    if len(weeks) == 1:
        return "Unique"
    try:
        first = _dt.date.fromisoformat(str(p.get("first", ""))[:10])
    except (ValueError, TypeError):
        return "n/a"
    span = max(1, (today - first).days // 7 + 1)
    r = len(weeks) / span
    return ("Fidèle" if r >= 0.5 else "Régulier" if r >= 0.25 else
            "Occasionnel" if r >= 0.10 else "Sporadique")


def activity_status(last: str, today: _dt.date) -> str:
    try:
        d = _dt.date.fromisoformat(last)
    except (ValueError, TypeError):
        return "Fantôme"
    days = (today - d).days
    return ("Actif" if days <= 7 else "Engagé" if days <= 30 else
            "Somnolant" if days <= 90 else "Inactif" if days <= 180 else
            "Désinscrit" if days <= 365 else "Fantôme")


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

NO_BEHAVIOR = {"mints": 0, "buys": 0, "sells": 0, "durations": [],
               "first": "", "last": ""}


def build_all(folder: str, snap_folder: str, sh, top: int, today: _dt.date):
    ledger_replay, prof, n, pulse_rows = replay(folder)
    print(f"Rejeu : {len(ledger_replay)} editions, {len(prof)} wallets, "
          f"{n} transferts.", flush=True)

    snap, snap_names, skipped = load_snapshot(snap_folder)
    if snap:
        ledger, sstats = merge_state(ledger_replay, snap)
        print(f"Snapshot holders : {len(snap)} editions — etat PRESENT prioritaire "
              f"(owned={sstats.get('owned', 0)}, burned={sstats.get('burned', 0)}, "
              f"escrow_resolu={sstats.get('escrow_resolved', 0)}, "
              f"escrow_inconnu={sstats.get('escrow_unresolved', 0)}, "
              f"ignorees={skipped}).", flush=True)
    else:
        ledger = ledger_replay
        print("Pas de snapshot holders — etat courant = rejeu seul.", flush=True)

    # etat courant PAR WALLET, derive du grand livre FUSIONNE
    per_uuid: Dict[str, Counter] = defaultdict(Counter)
    holdings_cnt: Counter = Counter()
    listed_cnt: Counter = Counter()
    distinct = defaultdict(set)
    for (u, _e), (hd, ls) in ledger.items():
        if not hd:
            continue
        per_uuid[u][hd] += 1
        holdings_cnt[hd] += 1
        distinct[hd].add(u)
        if ls:
            listed_cnt[hd] += 1

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

    # profil enrichi par wallet : HOLDERS actuels (fusionnes), comportement si
    # l'archive l'a vu ; sinon "etat seul" (score n/a, activite inconnue "")
    score, activity, engage, qbk, vsbk, vfbk = {}, {}, {}, {}, {}, {}
    for w, h in holdings_cnt.items():
        p = prof.get(w, NO_BEHAVIOR)
        score[w] = collector_score(p, h)
        activity[w] = activity_status(p["last"], today) if p["last"] else ""
        engage[w] = engagement_level(p, today)
        qbk[w] = qty_bucket(h)
        vsbk[w] = value_bucket(value_store.get(w, 0))
        vfbk[w] = value_bucket(value_floor.get(w, 0))

    # profil complet par wallet (pour 🟣C-PSEUDOS + typologie)
    profiles = {}
    for w, h in holdings_cnt.items():
        if h <= 0:
            continue
        p = prof.get(w, NO_BEHAVIOR)
        acq = p["mints"] + p["buys"]
        md = round(statistics.median(p["durations"]), 1) if p["durations"] else ""
        profiles[w] = {
            "holdings": h, "distinct_collectibles": len(distinct[w]),
            "acquired": acq, "sold": p["sells"],
            "retention": round(h / acq, 3) if acq else "",
            "median_hold_days": md, "collectorScore": score[w],
            "activityStatus": activity[w], "engagementLevel": engage[w],
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
        nm, cat = names.get(uid) or snap_names.get(uid) or ("", "")
        row = [uid, nm, cat, circ, len(holders), _gini([c for _w, c in counts])]
        for i in range(10):
            if i < len(counts):
                cnt = counts[i][1]
                row += [cnt, round(100.0 * cnt / circ, 2) if circ else 0]
            else:
                row += ["", ""]
        # ventilation de l'offre par bucket qty / valeur / score / activite
        b_qty, b_vs, b_vf, b_sc, b_ac, b_en = (Counter(), Counter(), Counter(),
                                               Counter(), Counter(), Counter())
        for w, c in counts:
            b_qty[qbk.get(w, "1")] += c
            b_vs[vsbk.get(w, "<100")] += c
            b_vf[vfbk.get(w, "<100")] += c
            b_sc[score.get(w, "n/a")] += c
            b_ac[activity.get(w, "")] += c
            b_en[engage.get(w, "n/a")] += c
        for dist, order in ((b_qty, QTY_ORDER), (b_vs, VALUE_ORDER),
                            (b_vf, VALUE_ORDER), (b_sc, SCORES + ["n/a"]),
                            (b_ac, ACTIVITIES),
                            (b_en, ENGAGEMENTS + ["n/a"])):
            d, pct = _dominant(dist, order)
            row += [d, pct]
        corner.append(row)
    corner.sort(key=lambda r: -r[3])

    # DISTRIBUTION GLOBALE des wallets par taille (quantite + valeur)
    size_rows = _size_distribution(profiles, value_store, value_floor)

    return (ledger, prof, whale_blocks, corner, size_rows, profiles,
            pulse_rows)


def _size_distribution(profiles, value_store, value_floor):
    """Reproduit la table 'wallet_size' : par bucket, nb wallets + total detenu.
    Base = les HOLDERS actuels (profiles, issus du grand livre fusionne)."""
    rows = []
    # QUANTITE
    w_by, tok_by = Counter(), Counter()
    tot_w = tot_tok = 0
    for w, pr in profiles.items():
        h = pr["holdings"]
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
        for w in profiles:
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
            "median_hold_days", "collectorScore", "activityStatus",
            "engagementLevel", "value_store", "value_floor", "qty_bucket",
            "pseudo", "last_active", "listed"]
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
    snap_folder = os.environ.get("SNAPSHOT_DIR", "dl_snap")
    top = int(os.environ.get("WHALES_TOP", "100"))
    rd = os.environ.get("RUN_DATE")
    today = _dt.date.fromisoformat(rd) if rd else _dt.date.today()

    have_archive = bool(_archive_files(folder))
    have_snap = bool(_snapshot_files(snap_folder))
    print(f"Sources : archive transferts={'OUI' if have_archive else 'non'} "
          f"({folder}), snapshot holders={'OUI' if have_snap else 'non'} "
          f"({snap_folder}).", flush=True)
    if not have_archive and not have_snap:
        print(f"Aucune source : ni archive dans '{folder}' ni snapshot dans "
              f"'{snap_folder}'.", file=sys.stderr)
        try:
            append_log(sheet_id, "ledger", "FAILED_NO_DATA",
                       f"no gz in {folder} nor {snap_folder}")
        except Exception:
            pass
        return 1

    sh = _client().open_by_key(sheet_id)
    (ledger, prof, whale_blocks, corner, size_rows, profiles,
     pulse_rows) = build_all(folder, snap_folder, sh, top, today)

    _save_ledger(ledger, os.environ.get("LEDGER_OUT", "data/ledger.csv.gz"))
    _save_profiles(profiles,
                   os.environ.get("PROFILES_OUT", "data/wallet_profiles.csv.gz"))
    _write_whales_horizontal(sh, whale_blocks)             # typologie 🐋 (3 tableaux)
    _write(sh, CORNER_TAB, CORNER_HEADER, corner)          # 🎯
    _write_size_history(sh, size_rows, today.strftime("%Y-%m"))   # 📈 historique
    enriched = _enrich_pseudos(sh, profiles)               # 🟣 profils
    try:
        _write_pulse(sh, pulse_rows)                       # 📅 pulse (cache)
    except Exception as e:
        print(f"pulse warning: {e}", flush=True)

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

    # 🏠ACCUEIL supprime (10/07, choix Preda) : la synthese vit sur 📊 STATS
    # (module stats_page, daily step 7). _write_dashboard n'est plus appele.

    summary = {"status": "OK", "editions": len(ledger),
               "holders": len(profiles), "wallets_behavior": len(prof),
               "snapshot": "yes" if have_snap else "no",
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
