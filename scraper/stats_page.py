"""
📊 STATS — LA page de synthese du Sheet (remplace 🏠ACCUEIL, supprime).

Refonte demandee par Preda (2026-07-10) :
  * une SEULE page de synthese (l'onglet 🏠ACCUEIL est supprime au 1er run) ;
  * bande KPI = totaux des 7 DERNIERS JOURS TERMINES (plus "dernier jour") ;
  * tableau quotidien avec EN-TETE GROUPE sur 2 lignes (ligne 8 = groupes,
    ligne 9 = colonnes) :
        TRANSACTION : Global | Mint | Market | Burn   (Global = M+M+B)
        ACTIF       : Unique | Nouveaux | Anciens     (Anciens v2, precision
                      Preda 11/07 : wallets de type DESINSCRIT ou FANTOME qui
                      redeviennent actifs = transaction PRECEDENTE > 180 j
                      avant le jour J, d'apres le last_active des registres
                      deep + IMX — le scan etant newest-first, le last_active
                      d'un wallet present au registre est sa vraie derniere
                      activite pre-fenetre. Un wallet connu qui revient apres
                      un trou <= 180 j n'est NI nouveau NI ancien.)
        REVENUE     : Total | Drop | Market
        OMI BURN    : Global | OMI→NFT | OMI→GEM      (ajout Preda 10/07)
    (exit Panier moyen, % nouveaux, tx/actif) ;
  * Revenue Market = colonne PRESENTE mais VIDE tant que les prix de vente
    reels ne sont pas collectes (chantier 7) -> Total = Drop pour l'instant ;
  * OMI BURN Global = omi_burned du jour depuis 🔥H-BURNS (dates PT aussi) ;
    OMI→NFT / OMI→GEM = colonnes VIDES en attendant la decomposition des
    burns (analyse de l'amont 0x61E7C72569, chantier burns) ;
  * zone de droite VISIBLE SANS SCROLL (demande Preda 10/07) : 🩺 sante des
    sources EN HAUT (le 🏆 top series a ete supprime — ne l'interessait pas),
    puis 📦 repartition 7 jours, puis ℹ️ notes + LEGENDES (bareme d'activite
    Actif/Engagé/Somnolant/Inactif/Désinscrit/Fantôme et profils Diamond-Hands
    etc. — rappels demandes par Preda).

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
MODULE_COL = "S"                     # colonne des modules de droite (tableau A:Q)
LISTING_TAB = "_ListingDaily"        # source du groupe LISTING (chain_run)
PULSE_TAB = "_MonthlyPulse"          # source du 📅 pulse mensuel (ledger)
PULSE_ROW = 49                       # ancre de la section pulse (sous le tableau)
PULSE_MONTHS = int(os.environ.get("STATS_PULSE_MONTHS", "13"))

# Registres wallet -> first_seen, pour distinguer Nouveaux et Anciens
# (revenants). Local = commite par le daily ; raws publics = scans profonds.
LOCAL_REGISTRY = os.environ.get("STATS_LOCAL_REGISTRY",
                                "data/wallet_registry_daily.csv")
REGISTRY_URLS = [u.strip() for u in (os.environ.get("STATS_REGISTRY_URLS") or
    "https://raw.githubusercontent.com/astronemagame-maker/astronema/main/data/wallet_registry_deep.csv,"
    "https://raw.githubusercontent.com/lepaolo/paolo/main/data/wallet_registry_imx.csv"
).split(",") if u.strip()]

ACTIVITY_TAB = "ChainActivity"
ITEMS_TAB = "ChainItems"
DYN_STATE_TAB = "_DynState"
BURNS_TAB = "🔥H-BURNS"

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
    """Lecture NON FORMATEE : en locale FR, "6,99" relu via numericise
    devenait 699 (virgule avalee comme separateur de milliers)."""
    try:
        ws = sh.worksheet(tab)
    except Exception:
        return []
    try:
        from gspread.utils import ValueRenderOption
        return ws.get_all_records(
            value_render_option=ValueRenderOption.unformatted)
    except TypeError:
        return ws.get_all_records()
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


def read_listing_daily(sh) -> Dict[str, tuple]:
    """{date_pt -> (listings, purs, listings_purs)} depuis _ListingDaily.
    Groupe LISTING a part entiere (Preda 11/07) — donnees collectees par
    chain_run a partir du 11/07 (les jours anterieurs restent vides ; un
    'CollectChain backfill' 31 j les remplit)."""
    out: Dict[str, tuple] = {}
    for r in _records(sh, LISTING_TAB):
        d = str(r.get("date", "")).strip()
        if d:
            out[d] = (_n(r.get("listings")), _n(r.get("pure_listers")),
                      _n(r.get("pure_listings")))
    return out


def build_pulse_section(pulse_records: List[Dict[str, Any]]) -> List[List]:
    """Section 📅 PULSE MENSUEL (facon VeveFox) : 13 derniers mois DESC avec
    variations M/M sur actifs / trades / tokens emis. Source = _MonthlyPulse
    (ecrit par le workflow ledger depuis l'archive complete)."""
    if not pulse_records:
        return []
    recs = sorted(pulse_records, key=lambda r: str(r.get("month", "")))

    def pct(cur, prev):
        try:
            cur, prev = float(cur), float(prev)
            return round(100.0 * (cur - prev) / prev, 1) if prev else ""
        except (TypeError, ValueError):
            return ""

    rows = []
    for i, r in enumerate(recs):
        prev = recs[i - 1] if i else {}
        rows.append([
            str(r.get("month", "")), _n(r.get("actifs")),
            pct(r.get("actifs"), prev.get("actifs")),
            _n(r.get("nouveaux")), _n(r.get("trades")),
            pct(r.get("trades"), prev.get("trades")),
            _n(r.get("acheteurs")), _n(r.get("vendeurs")),
            _n(r.get("tokens_emis")),
            pct(r.get("tokens_emis"), prev.get("tokens_emis")),
            _n(r.get("minters_uniques")), _n(r.get("drops")),
            _n(r.get("burns")), _n(r.get("listings")),
            r.get("acc_net_moy", ""), _n(r.get("acc_net_pos")),
            _n(r.get("acc_net_neg")), r.get("churn_pct", "")])
    rows = rows[-PULSE_MONTHS:][::-1]          # 13 derniers mois, DESC
    g: List[List] = [
        ["📅  PULSE MENSUEL — depuis la genèse (archive on-chain, recalculé "
         "par le workflow ledger)"],
        ["Mois", "Actifs", "Δ%", "Nouveaux", "Trades", "Δ%", "Acheteurs",
         "Vendeurs", "Tokens émis", "Δ%", "Minters", "Drops", "Burns",
         "Listings", "Acc. nette moy", "Net+", "Net−", "Churn %"],
    ] + rows
    return g


def read_omi_burns(sh) -> Dict[str, float]:
    """{date_pt -> OMI brules ce jour} depuis 🔥H-BURNS (toutes sources)."""
    out: Dict[str, float] = defaultdict(float)
    for r in _records(sh, BURNS_TAB):
        d = str(r.get("date", "")).strip()
        try:
            v = float(str(r.get("omi_burned", "")).replace(",", ".") or 0)
        except (TypeError, ValueError):
            v = 0.0
        if d and v:
            out[d] += v
    return dict(out)


# ---------------------------------------------------------------------------
# Calculs
# ---------------------------------------------------------------------------

REVENANT_GAP_DAYS = int(os.environ.get("STATS_REVENANT_GAP", "180"))


def _days_between(d1: str, d2: str):
    try:
        return (_dt.date.fromisoformat(d2[:10])
                - _dt.date.fromisoformat(d1[:10])).days
    except (ValueError, TypeError):
        return None


def compute_daily(activity: List[Dict[str, Any]],
                  registry: Dict[str, tuple] = None) -> List[Dict[str, Any]]:
    """ChainActivity (date, account, compteurs) -> 1 dict par date, tri DESC.

    registry : {wallet -> (first_seen, prev_last_active)} — prev_last_active
    vient des registres deep/IMX (activite PRE-fenetre uniquement).
    La 1re apparition d'un wallet DANS LA FENETRE est classee :
      * ANCIEN = un Désinscrit/Fantôme reveille : sa transaction precedente
        (prev_last_active) remonte a PLUS de REVENANT_GAP_DAYS (180 j) ;
      * NOUVEAU = wallet inconnu de tous les registres ;
      * ni l'un ni l'autre = wallet connu revenu apres un trou <= 180 j
        (somnolant/inactif qui se reveille — pas compte).
    """
    registry = registry or {}
    per: Dict[str, Dict[str, Any]] = {}
    first_in_window: Dict[str, str] = {}
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
        if a not in first_in_window or d < first_in_window[a]:
            first_in_window[a] = d
    new_by_day: Counter = Counter()
    old_by_day: Counter = Counter()
    for a, d in first_in_window.items():
        fs, prev = registry.get(a, ("", ""))
        if not fs and not prev:
            new_by_day[d] += 1              # inconnu de tous les registres
            continue
        gap = _days_between(prev, d) if prev else None
        if gap is not None and gap > REVENANT_GAP_DAYS:
            old_by_day[d] += 1              # Désinscrit/Fantôme reveille
    out = []
    for d in sorted(per, reverse=True):
        p = per[d]
        out.append({"date": d, "mint": p["mint"], "market": p["market"],
                    "burn": p["burn"],
                    "tx": p["mint"] + p["market"] + p["burn"],
                    "uniques": len(p["accounts"]),
                    "accounts": p["accounts"],
                    "new": new_by_day.get(d, 0),
                    "old": old_by_day.get(d, 0)})
    return out


def load_known_first_seen(wallets: set) -> Dict[str, tuple]:
    """{wallet -> (first_seen min, prev_last_active max)} depuis les registres,
    restreint aux wallets actifs de la fenetre (memoire legere).

    prev_last_active = SEULEMENT les registres deep/IMX (activite PRE-fenetre :
    le scan deep etant newest-first, le last_active d'un wallet present est sa
    vraie derniere activite avant le debut du scan). Le registre daily LOCAL
    est exclu du prev_last_active : il est mis a jour par chain_run AVANT cette
    page, donc contamine par la fenetre — il ne sert qu'au first_seen.
    Tolerant : chaque source peut manquer."""
    import csv as _csv
    import io as _io
    first: Dict[str, str] = {}
    prev: Dict[str, str] = {}

    def feed(lines, label, with_last):
        n = 0
        for row in _csv.DictReader(lines):
            w = str(row.get("wallet") or "").strip().lower()
            if w in wallets:
                fs = str(row.get("first_seen") or "").strip()
                if fs and (w not in first or fs < first[w]):
                    first[w] = fs
                if with_last:
                    la = str(row.get("last_active") or "").strip()
                    if la and (w not in prev or la > prev[w]):
                        prev[w] = la
                n += 1
        print(f"    registre {label} : {n} wallets actifs reconnus.", flush=True)

    try:
        with open(LOCAL_REGISTRY, encoding="utf-8") as f:
            feed(f, "daily(local)", with_last=False)
    except Exception as e:
        print(f"    registre local indisponible : {e}", flush=True)
    try:
        import requests
        for url in REGISTRY_URLS:
            label = url.rsplit("/", 1)[-1]
            try:
                resp = requests.get(url, timeout=180)
                resp.raise_for_status()
                feed(_io.StringIO(resp.text), label, with_last=True)
            except Exception as e:
                print(f"    registre {label} indisponible : {e}", flush=True)
    except Exception:
        pass
    return {w: (first.get(w, ""), prev.get(w, ""))
            for w in set(first) | set(prev)}


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


def compute_week(daily, revenue, omi=None, listing=None) -> Dict[str, Any]:
    days = set(_week_dates(daily))
    rows = [d for d in daily if d["date"] in days]
    accounts = set()
    for d in rows:
        accounts |= d["accounts"]
    omi = omi or {}
    listing = listing or {}
    li = [listing.get(d["date"]) for d in rows]
    li = [x for x in li if x]
    return {
        "listings": sum(x[0] for x in li),
        "pure_listers": sum(x[1] for x in li),
        "pure_listings": sum(x[2] for x in li),
        "start": min(days) if days else "",
        "end": max(days) if days else "",
        "revenue": round(sum(revenue.get(d["date"], 0) for d in rows)),
        "tx": sum(d["tx"] for d in rows),
        "mint": sum(d["mint"] for d in rows),
        "market": sum(d["market"] for d in rows),
        "burn": sum(d["burn"] for d in rows),
        "uniques": len(accounts),
        "new": sum(d["new"] for d in rows),
        "old": sum(d["old"] for d in rows),
        "omi": round(sum(omi.get(d["date"], 0) for d in rows)),
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

def build_table_grid(daily, revenue, week, omi, listing,
                     now_utc: str) -> List[List]:
    """Grille A1:Q.. : titre, bande KPI 7 jours, tableau quotidien groupe."""
    g: List[List] = []
    g.append(["📊  STATS VEVE — ACTIVITÉ ON-CHAIN", "", "", "", "", "", "",
              "", "", "", "", "", "", "", "", "", "", "",
              f"maj : {now_utc}"])
    g.append(["Jours pacifiques terminés uniquement · Revenue drop = mints × "
              "prix store · Revenue market et OMI→NFT/GEM : en attente "
              "(chantiers prix & décompo burns)"])
    g.append([])
    g.append([f"▼  7 DERNIERS JOURS TERMINÉS — du {week['start']} au "
              f"{week['end']}"])
    g.append(["Revenue drop", "Transactions", "Mints", "Market", "Burns",
              "Actifs uniques", "Nouveaux", "Anciens", "Listings",
              "Listeurs purs", "OMI brûlés"])
    g.append([week["revenue"], week["tx"], week["mint"], week["market"],
              week["burn"], week["uniques"], week["new"], week["old"],
              week["listings"], week["pure_listers"], week["omi"]])
    g.append([])
    g.append(["", "TRANSACTION", "", "", "", "ACTIF", "", "", "LISTING", "",
              "", "REVENUE", "", "", "OMI BURN", "", ""])
    g.append(["Date", "Global", "Mint", "Market", "Burn", "Unique",
              "Nouveaux", "Anciens", "Listings", "Purs", "Listings purs",
              "Total", "Drop", "Market", "Global", "OMI→NFT", "OMI→GEM"])
    for d in daily:
        drop = round(revenue.get(d["date"], 0))
        o = omi.get(d["date"])
        li = listing.get(d["date"])
        g.append([d["date"], d["tx"], d["mint"], d["market"], d["burn"],
                  d["uniques"], d["new"], d["old"],
                  li[0] if li else "", li[1] if li else "",
                  li[2] if li else "",
                  drop,           # Total = Drop tant que Market est vide
                  drop,
                  "",             # Revenue Market : chantier 7
                  round(o) if o is not None else "",
                  "",             # OMI→NFT : decompo a venir
                  ""])            # OMI→GEM : decompo a venir
    return g


def build_modules_grid(sante_rows, split) -> List[List]:
    """Zone de droite (colonnes P+), alignee sur la ligne 8, VISIBLE sans
    scroll : 🩺 sante (14 lignes, 4 colonnes), 📦 repartition, ℹ️ notes +
    legendes des classements (rappels demandes par Preda)."""
    g: List[List] = list(sante_rows)              # P8..P21 (titre+entete+12)
    g.append([""])
    g.append(["📦  RÉPARTITION — 7 JOURS", ""])   # P23
    g.append(["Collectibles — mints", split.get("mints_collectible", 0)])
    g.append(["Comics — mints", split.get("mints_comic", 0)])
    g.append(["Collectibles — marché", split.get("market_collectible", 0)])
    g.append(["Comics — marché", split.get("market_comic", 0)])
    g.append(["Burns", split.get("burns", 0)])
    g.append([""])
    g.append(["ℹ️  NOTES & LÉGENDES", ""])        # P30
    g.append(["• Anciens = Désinscrits/Fantômes réveillés : wallet actif ce "
              "jour dont la transaction précédente remonte à plus de 180 j "
              "(last_active des registres deep + IMX).", ""])
    g.append(["• Nouveaux = wallet inconnu de tous les registres. Précision "
              "définitive quand le scan CollectChain sera terminé.", ""])
    g.append(["• Transactions Global = mints + ventes marché + burns (lister "
              "n'est PAS une transaction — groupe LISTING à part).", ""])
    g.append(["• LISTING : Listings = nouveaux dépôts escrow du jour · Purs = "
              "comptes ayant listé sans mint/achat/vente ce jour · Listings "
              "purs = dépôts faits par ces comptes. Données depuis le 11/07 "
              "(un backfill 31 j remplit l'historique).", ""])
    g.append(["• Revenue drop = mints × prix store · Revenue market : vide en "
              "attendant les prix réels (chantier 7).", ""])
    g.append(["• OMI burn = 🔥H-BURNS (jours PT) ; OMI→NFT / OMI→GEM : décompo "
              "à venir ; le dernier jour se complète au run suivant.", ""])
    g.append(["🧭 ACTIVITÉ (🟣C-PSEUDOS, 🎯) : Actif ≤7 j · Engagé ≤30 j · "
              "Somnolant ≤90 j · Inactif ≤180 j · Désinscrit ≤365 j · "
              "Fantôme au-delà (dernière transaction).", ""])
    g.append(["💎 PROFIL (retention = détenu ÷ acquis) : Diamond-Hands ≥95% · "
              "Serious ≥75% · Collector ≥50% · Trader ≥30% · Flipper ≥15% · "
              "Seasoned ≥5% · Aggressive <5% (+1 cran flipper si revente "
              "médiane <7 j).", ""])
    g.append(["🔁 ENGAGEMENT (part des semaines actives depuis la 1ʳᵉ tx) : "
              "Fidèle ≥50 % · Régulier ≥25 % · Occasionnel ≥10 % · "
              "Sporadique <10 % · Unique = 1 seule semaine.", ""])
    g.append(["• Page recalculée chaque nuit par le daily · 📅 Pulse mensuel "
              "recalculé par le workflow ledger.", ""])
    return g


def _fmt_requests(ws_id: int, n_daily: int) -> List[Dict]:
    """[INUTILISE depuis v3] L'habillage est pose par l'Apps Script
    stats_format.gs (formatStatsPage) — fonction conservee uniquement comme
    REFERENCE des plages du layout. Ne pas re-cabler sans retirer le reset
    de l'Apps Script (le batch atomique echouait contre les fusions v1)."""
    def rng(r1, r2, c1, c2):
        return {"sheetId": ws_id, "startRowIndex": r1, "endRowIndex": r2,
                "startColumnIndex": c1, "endColumnIndex": c2}

    def bg(r, g_, b):
        return {"red": r / 255.0, "green": g_ / 255.0, "blue": b / 255.0}

    last = TABLE_START_ROW - 1 + max(n_daily, 1)
    reqs: List[Dict] = [
        {"unmergeCells": {"range": rng(0, 60, 0, 18)}},
        {"mergeCells": {"range": rng(0, 1, 0, 13), "mergeType": "MERGE_ALL"}},
        {"mergeCells": {"range": rng(1, 2, 0, 13), "mergeType": "MERGE_ALL"}},
        {"mergeCells": {"range": rng(3, 4, 0, 13), "mergeType": "MERGE_ALL"}},
        {"mergeCells": {"range": rng(7, 8, 1, 5), "mergeType": "MERGE_ALL"}},
        {"mergeCells": {"range": rng(7, 8, 5, 7), "mergeType": "MERGE_ALL"}},
        {"mergeCells": {"range": rng(7, 8, 7, 10), "mergeType": "MERGE_ALL"}},
        {"mergeCells": {"range": rng(7, 8, 10, 13), "mergeType": "MERGE_ALL"}},
        {"mergeCells": {"range": rng(7, 8, 14, 16), "mergeType": "MERGE_ALL"}},
        # titre + bande semaine
        {"repeatCell": {"range": rng(0, 1, 0, 13),
                        "cell": {"userEnteredFormat": {"textFormat": {
                            "bold": True, "fontSize": 14}}},
                        "fields": "userEnteredFormat.textFormat"}},
        {"repeatCell": {"range": rng(3, 4, 0, 13),
                        "cell": {"userEnteredFormat": {
                            "backgroundColor": bg(232, 240, 254),
                            "textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat(backgroundColor,textFormat)"}},
        {"repeatCell": {"range": rng(4, 5, 0, 8),
                        "cell": {"userEnteredFormat": {"textFormat": {
                            "bold": True, "foregroundColor": bg(102, 102, 102)}}},
                        "fields": "userEnteredFormat.textFormat"}},
        {"repeatCell": {"range": rng(5, 6, 0, 8),
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
        # groupe OMI BURN (rouge clair)
        {"repeatCell": {"range": rng(7, 8, 10, 13),
                        "cell": {"userEnteredFormat": {
                            "backgroundColor": bg(244, 204, 204),
                            "horizontalAlignment": "CENTER",
                            "textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat(backgroundColor,"
                                  "horizontalAlignment,textFormat)"}},
        # ligne 9 : en-tetes de colonnes
        {"repeatCell": {"range": rng(8, 9, 0, 13),
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
        {"repeatCell": {"range": rng(TABLE_START_ROW - 1, last, 10, 13),
                        "cell": {"userEnteredFormat": {"numberFormat": {
                            "type": "NUMBER", "pattern": "#,##0"}}},
                        "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": rng(5, 6, 0, 1),
                        "cell": {"userEnteredFormat": {"numberFormat": {
                            "type": "NUMBER", "pattern": "#,##0 $"}}},
                        "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": rng(5, 6, 1, 8),
                        "cell": {"userEnteredFormat": {"numberFormat": {
                            "type": "NUMBER", "pattern": "#,##0"}}},
                        "fields": "userEnteredFormat.numberFormat"}},
        # largeur de la colonne des modules
        {"updateDimensionProperties": {
            "range": {"sheetId": ws_id, "dimension": "COLUMNS",
                      "startIndex": 14, "endIndex": 15},
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
    active = {str(r.get("account", "")).strip().lower()
              for r in activity if str(r.get("account", "")).strip()}
    known = load_known_first_seen(active) if active else {}
    daily = compute_daily(activity, known)
    if not daily:
        raise RuntimeError("ChainActivity vide — page 📊 STATS non touchee.")
    revenue = compute_revenue(items, prices)
    omi = read_omi_burns(sh)
    listing = read_listing_daily(sh)
    week = compute_week(daily, revenue, omi, listing)
    wdays = set(_week_dates(daily))
    split = compute_split(items, wdays)

    now_utc = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    table = build_table_grid(daily, revenue, week, omi, listing, now_utc)
    try:
        sante_rows = _health.build_rows(sh)
    except Exception as e:
        print(f"health warning: {e}", flush=True)
        sante_rows = [["🩺 SANTE DES SOURCES", "", "", ""],
                      ["indisponible", "", "", ""]] + [[""]] * 12
    modules = build_modules_grid(sante_rows, split)

    ws = _open_worksheet(sh, STATS_TAB, cols=23)
    ws.clear()
    ws.update(range_name="A1", values=table, value_input_option="RAW")
    ws.update(range_name=f"{MODULE_COL}{GROUP_ROW}", values=modules,
              value_input_option="RAW")
    # 📅 PULSE MENSUEL (sous le tableau quotidien), si le ledger l'a produit
    pulse = build_pulse_section(_records(sh, PULSE_TAB))
    if pulse:
        ws.update(range_name=f"A{PULSE_ROW}", values=pulse,
                  value_input_option="RAW")
        try:
            ws.format(f"{PULSE_ROW}:{PULSE_ROW + 1}",
                      {"textFormat": {"bold": True}})
        except Exception:
            pass
    # PRESENTATION : AUCUNE mise en forme ici (choix Preda 10/07 apres l'echec
    # du batch atomique contre les fusions de l'ancienne page). L'habillage est
    # pose UNE FOIS par l'Apps Script stats_format.gs (formatStatsPage) et
    # survit aux reecritures : clear()/update() ne touchent que les VALEURS.

    # (v4) le bloc 🩺 sante est desormais INTEGRE a la zone de droite (P8),
    # visible sans scroll — plus d'ecriture separee en bas de page.

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
            "week_revenue": week["revenue"], "week_anciens": week["old"],
            "registres_wallets": len(known)}


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
