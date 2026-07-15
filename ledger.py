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
try:
    from scraper.collectchain import DISTRIB_WALLETS
except Exception:
    # Distributeurs VeVe (v-sys 12/07) : officiel "VeveCollection" (hub
    # d'emission, 1,64 M mints de stock + 611k livraisons), admin livraisons
    # ("Admin Collectible Transfer" StackR), identite VeveStore.
    DISTRIB_WALLETS = {"0x7be178ba43a9828c22997a3ec3640497d88d2fd3",
                       "0xdb721de5f825fcb3d2dbe3a4778e34e43ae7c095",
                       "0xc4817870a6a75704985be4f9933643a27739afc1"}

SYSTEM = {ZERO, MARKET_ESCROW, BURN_SINK, ""} | DISTRIB_WALLETS
BURN_TO = {ZERO, BURN_SINK}

# 13/07 : l'onglet visible 🐋A-WHALES est SUPPRIME. Le classement part dans
# 📊 STATS (via cet onglet cache, meme patron que _MonthlyPulse / _WalletSize)
# et le detail par wallet vit dans 🟣C-PSEUDOS (rangs + profil).
WHALES_TAB = "_Whales"
OLD_WHALES_TAB = "🐋A-WHALES"
CORNER_TAB = "🎯A-CORNERISATION"
# Historique wallet-size CACHE depuis le 11/07 (fusion dans 📊 STATS, choix
# Preda) — l'ancien onglet visible 📈H-WALLET-SIZE est supprime au 1er run.
SIZE_TAB = "_WalletSize"
OLD_SIZE_TAB = "📈H-WALLET-SIZE"
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
                       "value_floor", "qty_bucket", "airdropOnly",
                       "rang_qty", "rang_floor", "rang_store"]
# rang_* <- position dans les 3 classements de WHALE_TYPES (vide si hors top)
RANK_COLS = {"holdings": "rang_qty", "value_floor": "rang_floor",
             "value_store": "rang_store"}
_CORNER_BASE = (["veve_uuid", "name", "category", "circulating", "holders",
                 "gini"]
                + [f"top{i}_{s}" for i in range(1, 11) for s in ("cnt", "pct")]
                + ["qty_dominant", "qty_dominant_pct",
                   "vstore_dominant", "vstore_dominant_pct",
                   "vfloor_dominant", "vfloor_dominant_pct",
                   "score_dominant", "score_dominant_pct",
                   "activity_dominant", "activity_dominant_pct",
                   "engagement_dominant", "engagement_dominant_pct"])
# CORNER_HEADER complet (base + fiche VeveFox) defini plus bas, une fois
# SCORES / ACTIVITIES / QTY_ORDER / HOLD_ORDER connus.

# Tranches de QUANTITE (nb d'exemplaires detenus) — demande Preda.
# Echelles v3 = SPECIFICATION EXACTE de Preda (12/07).
QTY_BUCKETS = [(1, 1, "1"), (2, 10, "2-10"), (11, 50, "11-50"),
               (51, 100, "51-100"), (101, 500, "101-500"),
               (501, 1000, "501-1k"), (1001, 5000, "1001-5k"),
               (5001, 10000, "5001-10k"), (10001, 50000, "10001-50k"),
               (50001, 100000, "50001-100k"),
               (100001, float("inf"), "100k+")]
# Tranches de VALEUR (USD), store ET floor.
VALUE_BUCKETS = [(0, 20, "≤20"), (20, 100, "21-100"), (100, 500, "101-500"),
                 (500, 1000, "501-1k"), (1000, 5000, "1001-5k"),
                 (5000, 10000, "5001-10k"), (10000, 50000, "10001-50k"),
                 (50000, 100000, "50001-100k"),
                 (100000, 500000, "100001-500k"),
                 (500000, 1000000, "500001-1M"),
                 (1000000, float("inf"), "1M+")]
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


# ⚠️ FLOOR ABERRANT (13/07) : le classement 🐋 par "valeur floor" affichait des
# portefeuilles a 1E+15 et 1,9E+16. Ce ne sont pas des milliardaires : c'est UN
# item au floor delirant (quelqu'un liste a un prix absurde, comme le Golden MYO
# a 111 milliards de $ du flux VeVe) qui contamine toute la valorisation d'un
# wallet. Un floor est un prix DEMANDE : n'importe qui peut demander n'importe
# quoi. Au-dela du seuil, on IGNORE le floor et on retombe sur le prix store —
# et on DIT combien on en a ecarte (jamais en silence).
# Seuil floor ABERRANT (demande Preda 15/07 : « au-dessus de 50 000 plutôt que
# 1M ») — un floor est un prix DEMANDE, n'importe qui peut lister n'importe quoi.
# Au-dela, on ignore ce floor et le prix store prend le relais (les prix store,
# eux, restent tres bas : ce plafond ne les ecarte jamais). Tunable via PRIX_MAX.
PRIX_MAX = float(os.environ.get("PRIX_MAX", "50000"))


def _read_prices(sh):
    """{uuid -> (store_price, floor_price)} depuis l'onglet cache _DynState.
    Lecture NON FORMATEE : en locale FR, "6,99" relu via numericise devenait
    699 (virgule avalee) — UNFORMATTED_VALUE renvoie les vrais nombres."""
    store, floor = {}, {}
    aberrants: List[Tuple[str, float]] = []
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
        if sp is not None and 0 < sp <= PRIX_MAX:
            store[u] = sp
        if fp is not None:
            if 0 < fp <= PRIX_MAX:
                floor[u] = fp
            elif fp > PRIX_MAX:
                aberrants.append((u, fp))
    if aberrants:
        aberrants.sort(key=lambda x: -x[1])
        print(f"    ⚠️ {len(aberrants)} floor(s) aberrant(s) ignore(s) "
              f"(> {PRIX_MAX:,.0f}) — le prix store prend le relais. "
              f"Le pire : {aberrants[0][0][:8]}… a {aberrants[0][1]:,.0f}."
              .replace(",", " "), flush=True)
    return store, floor

SCORES = ["Diamond-Hands", "Serious Collector", "Collector", "Trader",
          "Flipper", "Seasoned Flipper", "Aggressive Flipper"]
# Engagement (VeveFox "Engagement Level", seuils valides par Preda 11/07) :
# part des SEMAINES ACTIVES depuis la 1re transaction du wallet.
ENGAGEMENTS = ["Fidèle", "Régulier", "Occasionnel", "Sporadique", "Unique"]
# Pulse mensuel (VeveFox "Monthly Market Pulse") — onglet cache lu par 📊 STATS.
# ── 👴 ANCIENS AU JOUR LE JOUR (13/07) ───────────────────────────────────────
# `week_anciens` restait a 0 sur 📊 STATS. Diagnostic : stats_page deduisait le
# "reveil" des REGISTRES wallets, dont le `last_active` est CONTAMINE par la
# fenetre (le scan deep a demarre le 09/07, soit DEDANS) -> l'ecart tombait a
# quelques jours et plus personne ne pouvait depasser les 180. Et on ne peut
# pas simplement ecarter les dates de la fenetre : le registre ne garde QU'UNE
# last_active par wallet ; en la jetant, on retomberait sur la date IMX et on
# INVENTERAIT des reveils pour des wallets actifs en mars.
# La bonne source, c'est ICI : le ledger a l'archive COMPLETE (IMX + CC) et
# calcule deja les anciens MENSUELS. Il les calcule desormais aussi au JOUR.
REVEIL_GAP = int(os.environ.get("REVEIL_GAP_DAYS", "180"))    # >6 mois
REVEIL_FENETRE = int(os.environ.get("REVEIL_FENETRE_JOURS", "60"))
REVEIL_TAB = "_Reveils"           # onglet cache, lu par 📊 STATS
REVEIL_HEADER = ["date_pt", "anciens"]

PULSE_TAB = "_MonthlyPulse"
PULSE_HEADER = ["month", "actifs", "nouveaux", "trades", "acheteurs",
                "vendeurs", "tokens_emis", "tokens_airdrop",
                "minters_uniques", "drops", "burns", "listings",
                "acc_net_moy", "acc_net_pos", "acc_net_neg", "churn_pct",
                "drops_vevecomics", "anciens",
                # 13/07 : les 3 colonnes VIDES du tableau mensuel de 📊 STATS
                "og_actifs",      # actifs du mois arrives AVANT OG_CUTOFF
                "og_pct",         # ... en % des actifs uniques du mois
                "listeurs",       # comptes UNIQUES ayant liste -> col. Comptes
                "revenue_drop"]   # mints (hors airdrop) x prix store -> Drop
# /!\ revenue_drop : ere CollectChain SEULEMENT. L'archive IMX ne porte que le
# token_id, jamais l'uuid de l'item -> aucun prix rattachable avant 2026-01.
# AIRDROP (seuils valides par Preda 11/07) : un (jour, uuid) est un airdrop si
# mints >= MIN_MINTS ET minters uniques >= RATIO x mints (~1 exemplaire par
# wallet, ex. Black Pink Heart, Happy New Year Tier1 Gini 0.008). Les mints
# d'airdrop sont SEPARES (jamais jetes) : tokens_airdrop au pulse, colonne
# Airdrop sur 📊 STATS.
AIRDROP_MIN_MINTS = int(os.environ.get("AIRDROP_MIN_MINTS", "2000"))
AIRDROP_MINTER_RATIO = float(os.environ.get("AIRDROP_MINTER_RATIO", "0.9"))
# Jour du DUMP de migration IMX->CollectChain : des re-mints automatiques
# (1 par proprietaire) qui matchent la regle airdrop par accident (12 faux
# positifs constates au run du 11/07) et gonflent le pulse. EXCLU de la
# detection airdrop ET des compteurs mint du pulse (le grand livre, lui,
# garde ces mints : ils fondent la propriete).
MIGRATION_DAY = os.environ.get("CC_MIGRATION_DAY", "2026-01-28")
# OG (demande Preda 13/07) : un wallet est OG si son PREMIER mois d'activite,
# toutes eres confondues (first_month fusionne IMX + CollectChain), est
# ANTERIEUR a OG_CUTOFF. Defaut "2023" -> OG = arrive en 2021 ou 2022.
# NB : la genese IMX est le 14/12/2021 ; l'ere GoChain (avant) n'est pas encore
# collectee, donc les tout premiers OG sont dates de 2021-12 par defaut.
OG_CUTOFF = os.environ.get("OG_CUTOFF", "2023")
# ── ANTERIORITE GOCHAIN (13/07) ──────────────────────────────────────────────
# L'ere d'AVANT IMX est enfin collectee (repo jetonveve, CSV public). Les
# adresses sont les MEMES sur GoChain / IMX / CollectChain — verifie. Sans ce
# raccord, TOUS les anciens sont dates du 2021-12 (genese IMX) et on ne peut
# pas distinguer un pionnier de 2019 d'un arrivant de la hype de decembre.
# On fusionne par le MINIMUM : GoChain ne peut que RECULER une anteriorite,
# jamais l'avancer.
GOCHAIN_URL = os.environ.get(
    "GOCHAIN_URL",
    "https://raw.githubusercontent.com/fanablefrance/jetonveve/main/"
    "data/gochain_wallets.csv")
# Bareme d'activite en FRANCAIS (Preda 2026-07-10) — remplace
# Active/Engaged/Dormant/Lapsed/Inactive/Ghost.
ACTIVITIES = ["Actif", "Engagé", "Somnolant", "Inactif", "Désinscrit", "Fantôme"]

# ── 🦊 FICHE PAR ITEM (style VeveFox, demande Preda 15/07) ────────────────────
# La fiche complete par item vit dans 🎯A-CORNERISATION (colonnes ajoutees, cf.
# CORNER_HEADER plus bas) : pour chaque activite et profil, le nb de PERSONNES
# ET la SUPPLY ; + taille de wallet, quantite detenue, scores moyens ; et les 3
# heatmaps croisees ENCODEES en chaines (";" cellules, "|" lignes) — les grilles
# de la page 5. Le module interactif de 📊 STATS re-explose ces chaines par SPLIT
# selon l'item choisi dans le menu deroulant.
PROFILE_ORDER = SCORES + ["Unclassified"]       # 8 : le "n/a" du score = Unclassified
ACTIVITY_ORDER = ACTIVITIES + ["Non classé"]    # 7 : activite inconnue (snapshot seul)
# Score 0-100 par palier (facon VeveFox) -> un score MOYEN par item. Les
# non-classes (Unclassified / Non classé) sont EXCLUS de la moyenne, jamais
# comptes comme 0 (sinon un catalogue mal scanne afficherait un faux score bas).
SCORE_MID = {"Diamond-Hands": 97.5, "Serious Collector": 87.5, "Collector": 70.0,
             "Trader": 50.0, "Flipper": 30.0, "Seasoned Flipper": 12.5,
             "Aggressive Flipper": 2.5}
ACTIVITY_MID = {"Actif": 95.0, "Engagé": 80.0, "Somnolant": 60.0,
                "Inactif": 40.0, "Désinscrit": 20.0, "Fantôme": 5.0}
# Tranches de QUANTITE DETENUE DE L'ITEM par un wallet (holding amount VeveFox).
HOLD_BUCKETS = [(1, 1, "1"), (2, 5, "2-5"), (6, 10, "6-10"), (11, 20, "11-20"),
                (21, 50, "21-50"), (51, 100, "51-100"), (101, 500, "101-500"),
                (501, float("inf"), "500+")]
HOLD_ORDER = [b[2] for b in HOLD_BUCKETS]
# 🎯A-CORNERISATION porte la fiche COMPLETE par item (demande Preda 15/07 :
# "ajoute les colonnes ici, les modules STATS tirent de là"). Pour CHAQUE
# categorie d'activite et de profil : le nb de PERSONNES (wallets) ET la SUPPLY
# (exemplaires) — les deux, comme le PDF VeveFox. Puis taille de wallet et
# quantite detenue (pers + supply), scores moyens, et les 3 heatmaps croisees
# ENCODEES (";" cellules, "|" lignes) = les grilles roses de la page 5, rangees
# en technique pour le module (pas faites pour etre lues a l'oeil).
CORNER_HEADER = (
    _CORNER_BASE + ["avg_collector", "avg_activity"]
    + [f"act_pers_{s}" for s in ACTIVITY_ORDER]
    + [f"act_sup_{s}" for s in ACTIVITY_ORDER]
    + [f"prof_pers_{s}" for s in PROFILE_ORDER]
    + [f"prof_sup_{s}" for s in PROFILE_ORDER]
    + [f"ws_pers_{s}" for s in QTY_ORDER]
    + [f"ws_sup_{s}" for s in QTY_ORDER]
    + [f"hold_pers_{s}" for s in HOLD_ORDER]
    + [f"hold_sup_{s}" for s in HOLD_ORDER]
    + ["hm_prof_act", "hm_prof_ws", "hm_act_ws"])


def hold_bucket(c: int) -> str:
    for lo, hi, lbl in HOLD_BUCKETS:
        if lo <= c <= hi:
            return lbl
    return HOLD_ORDER[-1]


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


# Contrat NFT VeVe sur Immutable X (ere 2021 -> migration 2026-01-28).
IMX_CONTRACT = "0xa7aefead2f25972d80516628417ac46b3f2604af"


def _imx_files(folder: str) -> List[str]:
    """Tranches du scan IMX de paolo (imx_transfers_runNNN.csv.gz)."""
    if not folder:
        return []
    files = glob.glob(os.path.join(folder, "*imx*run*.csv.gz"))
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
    # MEMOIRE (fix OOM 11/07, 12,4M lignes sur runner prive 7 Go) :
    # sys.intern partage les chaines repetees (18k uuids, ~700k wallets au
    # lieu de 12,4M copies) et by_token est CONSOMME (popitem) en construisant
    # snap au lieu de coexister avec lui.
    intern = sys.intern
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
                by_token[tid] = (intern(uid), intern(ed),
                                 intern((r.get("owner") or "").strip().lower()))
                if uid not in snap_names and (r.get("name") or "").strip():
                    snap_names[uid] = ((r.get("name") or "").strip(),
                                       (r.get("category") or "").strip())
    snap: Dict[Tuple[str, str], str] = {}
    while by_token:
        _tid, (uid, ed, owner) = by_token.popitem()
        snap.setdefault((uid, ed), owner)   # popitem = LIFO : le plus recent
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
    # fix OOM 11/07 : fusion EN PLACE dans le rejeu (pas de 3e dict de 11,7M
    # cles) et le snapshot est CONSOMME au fil de l eau.
    merged = replay_ledger
    stats: Counter = Counter()
    while snap:
        key, owner = snap.popitem()
        if not owner or owner in BURN_TO:
            merged[key] = ("", 0)
            stats["burned"] += 1
        elif owner in DISTRIB_WALLETS:
            # stock VeVe (officiel/admin/store) : pas un detenteur collectionneur
            merged[key] = ("", 0)
            stats["system_stock"] += 1
        elif owner == MARKET_ESCROW:
            holder = (merged.get(key) or ("", 0))[0]
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


def replay(folder: str, imx_folder: str = ""):
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
    uuid_first_mint: Dict[str, str] = {}   # uuid -> 1er JOUR de mint (v10)
    uuid_cat: Dict[str, str] = {}          # uuid -> category (comic/collectible)
    mint_day_uuid: Counter = Counter()   # candidats airdrop (compteur leger)
    mint_month_uuid: Counter = Counter()  # (mois, uuid) -> mints : REVENUE
    # 👴 reveils : derniere activite AVANT la fenetre, 1re activite DEDANS
    debut_f = (_dt.date.today()
               - _dt.timedelta(days=REVEIL_FENETRE)).isoformat()
    avant: Dict[str, str] = {}
    dedans: Dict[str, str] = {}

    def _voir(w: str, jour: str) -> None:
        if not w or not jour or w in SYSTEM:
            return
        if jour < debut_f:
            if jour > avant.get(w, ""):
                avant[w] = jour
        elif jour < dedans.get(w, "9999"):
            dedans[w] = jour
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
                frm = sys.intern((r.get("from") or "").strip().lower())
                to = sys.intern((r.get("to") or "").strip().lower())
                day = sys.intern((r.get("date_pt") or "").strip())
                _voir(frm, day)
                _voir(to, day)
                seq[(sys.intern(uid), sys.intern(ed))].append(
                    (ts, frm, to, day, key))
                n += 1
                # ---- pulse mensuel ----
                m = day[:7]
                if not m:
                    continue
                kind = (r.get("kind") or "").strip()
                if kind in ("market", "system_transfer") and \
                        (frm in DISTRIB_WALLETS or to in DISTRIB_WALLETS):
                    # livraisons/retours VeVe archives en "market" avant le
                    # fix v-sys : reclasses a la volee au rejeu.
                    kind = "system_transfer"
                mo = monthly.setdefault(m, {
                    "mints": 0, "market": 0, "burns": 0, "listings": 0,
                    "actives": set(), "minters": set(), "buyers": set(),
                    "sellers": set(), "net": Counter(),
                    "listers": set()})
                if kind == "mint":
                    if day == MIGRATION_DAY:
                        continue   # re-mints de migration : pas de l'activite
                    if to and to not in SYSTEM:
                        mo["mints"] += 1
                        mo["minters"].add(to)
                        mo["actives"].add(to)
                        mo["net"][to] += 1
                        mint_day_uuid[(day, uid)] += 1
                        mint_month_uuid[(m, uid)] += 1
                        if m < first_month.get(to, "9999"):
                            first_month[to] = m
                    if day < uuid_first_mint.get(uid, "9999"):
                        uuid_first_mint[uid] = day
                        uuid_cat[uid] = (r.get("category") or "").strip()
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
                    if frm and frm not in SYSTEM:
                        mo["listers"].add(frm)      # -> colonne Comptes
                elif kind == "system_transfer":
                    # livraison VeVe : le cote utilisateur reste actif
                    # (acquisition/retour) mais PAS une vente market.
                    for w, delta in ((to, 1), (frm, -1)):
                        if w and w not in SYSTEM:
                            mo["actives"].add(w)
                            mo["net"][w] += delta
                            if m < first_month.get(w, "9999"):
                                first_month[w] = m
                # vault_mint : mouvement systeme, hors pulse.

    seen_keys.clear()          # dedup finie : libere ~0,5-1 Go avant la suite
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
    airdrops, air_wallets = _detect_airdrops(folder, mint_day_uuid)
    # flag 🎯 (demande Preda 11/07) : memorise par wallet le nb de mints recus
    # via des airdrops detectes -> build_all classe "airdrop-only".
    for w, c in air_wallets.items():
        if w in prof:
            prof[w]["airdrop_mints"] = c
    # un AIRDROP n'est pas une vente : ses mints sortent du revenue mensuel.
    for (day, uid), cnt in airdrops.items():
        k = (day[:7], uid)
        if k in mint_month_uuid:
            mint_month_uuid[k] = max(0, mint_month_uuid[k] - cnt)
    seq.clear()                     # libere la RAM avant l'ere IMX (runner 7 Go)
    n_imx = _ingest_imx(imx_folder, monthly, first_month, voir=_voir)
    g_lus, g_rec = _ingest_gochain(first_month)
    if g_lus:
        print(f"GoChain : {g_lus} wallets lus, {g_rec} anteriorites RECULEES "
              f"(l'ere d'avant IMX : 2019 -> 2021).", flush=True)
    if n_imx:
        print(f"Pulse IMX : {n_imx} transferts 2021->{MIGRATION_DAY} integres "
              f"({len(monthly)} mois au pulse).", flush=True)
    # 👴 REVEILS : 1re activite DANS la fenetre apres une absence de plus de
    # REVEIL_GAP jours. Calcule sur l'archive COMPLETE (IMX + CC) — la seule
    # source qui connaisse l'AVANT.
    reveils: Counter = Counter()
    for w, jour in dedans.items():
        veille = avant.get(w)
        if not veille:
            continue                      # jamais vu avant : c'est un NOUVEAU
        try:
            ecart = (_dt.date.fromisoformat(jour)
                     - _dt.date.fromisoformat(veille)).days
        except ValueError:
            continue
        if ecart > REVEIL_GAP:
            reveils[jour] += 1
    print(f"Reveils : {sum(reveils.values())} wallet(s) revenus apres plus de "
          f"{REVEIL_GAP} j d'absence (fenetre de {REVEIL_FENETRE} j).",
          flush=True)
    return (ledger, prof, n,
            _build_pulse(monthly, first_month, uuid_first_mint, uuid_cat,
                         airdrops),
            mint_month_uuid, reveils)


def _ingest_imx(folder: str, monthly: Dict, first_month: Dict,
                voir=None) -> int:
    """PULSE IMX 2021->2026 (demande Preda : « l'histoire complete »).

    Fusionne l'archive IMX de paolo (imx_transfers_runNNN.csv.gz : txn_id,
    txn_time_ms, date_pt, txn_type, from, to, token_id, token_address) dans
    les MEMES agregats mensuels que CollectChain. Regles :
      * dedup par txn_id (le 14/12/2021 a ete re-scanne en boucle) ;
      * filtre contrat VeVe (IMX_CONTRACT) ;
      * date_pt >= MIGRATION_DAY ignoree (dump de migration + ere CC deja
        couverte par chain-archive) -> janvier 2026 = IMX 1-27 + CC des le 28 ;
      * kind par adresses : from 0x0 (ou txn_type mint) = mint · to 0x0/coffre
        = burn · to escrow = listing · from escrow = vente (vendeur retrouve
        via le DERNIER deposant du token_id ; escrow->deposant = annulation,
        no-op) · sinon transfert direct compte comme market ;
      * drops / airdrops : vides pour l'ere IMX (pas d'uuid dans l'archive) ;
      * PULSE UNIQUEMENT : grand livre, profils et scores restent CollectChain
        (pas d'uuid/edition cote IMX ; l'anciennete des veterans vit deja dans
        wallet_registry_imx).
    Memoire : wallets internes (1 objet str par wallet), a executer APRES
    seq.clear() (runner prive 7 Go)."""
    files = _imx_files(folder)
    if not files:
        return 0
    seen: set = set()
    canon: Dict[str, str] = {}

    def W(a) -> str:
        a = (a or "").strip().lower()
        return canon.setdefault(a, a)

    def touch(mo, m, w, delta):
        mo["actives"].add(w)
        mo["net"][w] += delta
        if m < first_month.get(w, "9999"):
            first_month[w] = m

    lister: Dict[str, str] = {}      # token_id -> dernier deposant escrow
    n = 0
    for path in files:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                ca = (r.get("token_address") or "").strip().lower()
                if ca and ca != IMX_CONTRACT:
                    continue
                day = (r.get("date_pt") or "").strip()
                if not day or day >= MIGRATION_DAY:
                    continue
                if voir is not None:      # l'IMX date les DORMANTS d'avant 2026
                    voir((r.get("from") or "").strip().lower(), day)
                    voir((r.get("to") or "").strip().lower(), day)
                tid = (r.get("txn_id") or "").strip()
                if tid:
                    try:
                        tkey = int(tid)
                    except ValueError:
                        tkey = tid
                    if tkey in seen:
                        continue
                    seen.add(tkey)
                frm, to = W(r.get("from")), W(r.get("to"))
                m = day[:7]
                mo = monthly.setdefault(m, {
                    "mints": 0, "market": 0, "burns": 0, "listings": 0,
                    "actives": set(), "minters": set(), "buyers": set(),
                    "sellers": set(), "net": Counter(),
                    "listers": set()})
                tok = (r.get("token_id") or "").strip()
                n += 1
                if (r.get("txn_type") or "").strip() == "mint" or frm == ZERO:
                    if to and to not in SYSTEM:
                        mo["mints"] += 1
                        mo["minters"].add(to)
                        touch(mo, m, to, 1)
                elif to in BURN_TO:
                    mo["burns"] += 1
                    if frm and frm not in SYSTEM:
                        touch(mo, m, frm, -1)
                elif to == MARKET_ESCROW:
                    mo["listings"] += 1
                    if tok and frm and frm not in SYSTEM:
                        lister[tok] = frm
                elif frm == MARKET_ESCROW:
                    seller = lister.pop(tok, "") if tok else ""
                    if seller and seller == to:
                        continue                 # annulation : retour au deposant
                    if to and to not in SYSTEM:
                        mo["market"] += 1
                        mo["buyers"].add(to)
                        touch(mo, m, to, 1)
                        if seller:
                            mo["sellers"].add(seller)
                            touch(mo, m, seller, -1)
                elif frm in DISTRIB_WALLETS or to in DISTRIB_WALLETS:
                    # livraison/retour VeVe (officiel/admin) : actif, pas vente
                    if to and to not in SYSTEM:
                        touch(mo, m, to, 1)
                    if frm and frm not in SYSTEM:
                        touch(mo, m, frm, -1)
                else:                            # transfert direct wallet->wallet
                    mo["market"] += 1
                    if to and to not in SYSTEM:
                        mo["buyers"].add(to)
                        touch(mo, m, to, 1)
                    if frm and frm not in SYSTEM:
                        mo["sellers"].add(frm)
                        touch(mo, m, frm, -1)
    return n


def _ingest_gochain(first_month: Dict[str, str]) -> tuple:
    """Recule le first_month des wallets vus sur GoChain (2019 -> 2021).

    Retourne (lus, recules). Tolerant : si le CSV est injoignable, le ledger
    continue — on perd la granularite, pas le run.
    NB l'User-Agent : Python-urllib se fait refuser par pas mal de WAF (lecon
    du 403 GoChain). On se presente proprement."""
    import csv as _csv
    import io
    import urllib.request
    if not GOCHAIN_URL:
        return 0, 0
    try:
        req = urllib.request.Request(
            GOCHAIN_URL, headers={"User-Agent": "veve-ledger/1.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            txt = r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"GoChain : CSV injoignable ({e}) — anteriorite non fusionnee "
              f"(les anciens resteront dates du 2021-12).", flush=True)
        return 0, 0
    lus = recules = 0
    for row in _csv.DictReader(io.StringIO(txt)):
        w = (row.get("wallet") or "").strip().lower()
        fs = (row.get("first_seen") or "").strip()[:7]      # YYYY-MM
        if not w or len(fs) != 7:
            continue
        lus += 1
        if fs < first_month.get(w, "9999"):
            first_month[w] = fs
            recules += 1
    return lus, recules


def _detect_airdrops(folder: str, mint_day_uuid: Counter) -> Dict:
    """{(day, uuid) -> mints} des AIRDROPS detectes.

    1re passe (deja faite) : compteur leger de mints par (jour, uuid).
    2e passe CIBLEE : pour les seuls candidats >= AIRDROP_MIN_MINTS, compter
    les minters DISTINCTS (trop couteux en memoire pour 12M+ mints en 1 passe).
    Airdrop si minters >= AIRDROP_MINTER_RATIO x mints (~1 par wallet)."""
    candidates = {k for k, v in mint_day_uuid.items()
                  if v >= AIRDROP_MIN_MINTS}
    if not candidates:
        return {}, Counter()
    minters: Dict[Tuple[str, str], Counter] = {k: Counter() for k in candidates}
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
                        minters[k][to] += 1
    out = {}
    air_wallets: Counter = Counter()   # wallet -> mints recus via airdrops
    for k in candidates:
        m = mint_day_uuid[k]
        if len(minters[k]) >= AIRDROP_MINTER_RATIO * m:
            out[k] = m
            for w, c in minters[k].items():
                air_wallets[w] += c
            print(f"    AIRDROP detecte : {k[0]} {k[1][:8]}… "
                  f"{m} mints / {len(minters[k])} wallets.", flush=True)
    return out, air_wallets


def _build_pulse(monthly, first_month, uuid_first_mint, uuid_cat=None,
                 airdrops=None) -> List[List]:
    """Lignes du pulse mensuel (chronologique ASC) pour _MonthlyPulse.

    Drops v10 (demande Preda 11/07) : les COMICS sortis un MERCREDI (jour PT)
    sont les parutions silencieuses de la page vevecomics (jamais annoncees,
    calees sur la sortie physique) -> comptes A PART (drops_vevecomics), les
    drops classiques restent dans `drops`."""
    new_by_m = Counter(first_month.values())
    uuid_cat = uuid_cat or {}
    drops_by_m: Counter = Counter()
    wed_by_m: Counter = Counter()
    for uid, day in uuid_first_mint.items():
        try:
            wed = _dt.date.fromisoformat(day[:10]).weekday() == 2
        except (ValueError, TypeError):
            wed = False
        m_key = day[:7]
        if wed and uuid_cat.get(uid) == "comic":
            wed_by_m[m_key] += 1
        else:
            drops_by_m[m_key] += 1
    air_by_m: Counter = Counter()
    for (day, _uid), cnt in (airdrops or {}).items():
        air_by_m[day[:7]] += cnt
    rows: List[List] = []
    prev_actives = None
    # ANCIENS mensuels (v13, demande Preda) : wallet actif ce mois dont la
    # derniere activite remonte a PLUS de 6 mois (desinscrit/fantome reveille).
    months_sorted = sorted(monthly)
    m_index = {m: i for i, m in enumerate(months_sorted)}
    last_seen: Dict[str, int] = {}
    anciens_by_m: Counter = Counter()
    anciens_y: Dict[str, set] = {}       # wallets reveilles, DEDUPLIQUES / an
    for m in months_sorted:
        i = m_index[m]
        for w in monthly[m]["actives"]:
            prev = last_seen.get(w)
            if prev is not None and i - prev > 6:
                anciens_by_m[m] += 1
                anciens_y.setdefault(m[:4], set()).add(w)
            last_seen[w] = i
    last_seen = None
    anciens_by_y = {y: len(s) for y, s in anciens_y.items()}
    anciens_y = None
    for m in sorted(monthly):
        mo = monthly[m]
        act = mo["actives"]
        churn = ""
        if prev_actives:
            gone = sum(1 for w in prev_actives if w not in act)
            churn = round(100.0 * gone / len(prev_actives), 1)
        # part des OG (arrives avant OG_CUTOFF) parmi les actifs UNIQUES du mois
        og = sum(1 for w in act if first_month.get(w, "9999") < OG_CUTOFF)
        og_pct = round(100.0 * og / len(act), 1) if act else ""
        net = mo["net"]
        pos = sum(1 for v in net.values() if v > 0)
        neg = sum(1 for v in net.values() if v < 0)
        avg = round(sum(net.values()) / len(net), 2) if net else 0
        rows.append([m, len(act), new_by_m.get(m, 0), mo["market"],
                     len(mo["buyers"]), len(mo["sellers"]),
                     mo["mints"], air_by_m.get(m, 0),
                     len(mo["minters"]), drops_by_m.get(m, 0),
                     mo["burns"], mo["listings"], avg, pos, neg, churn,
                     wed_by_m.get(m, 0), anciens_by_m.get(m, 0),
                     og, og_pct,
                     len(mo.get("listers") or ()), ""])
        prev_actives = act
    # lignes ANNUELLES (v14, demande Preda 12/07) : month = "YYYY" (4 car.),
    # filtrees par stats_page -> tableau PAR ANNEE + PULSE par annee. TOUTES
    # les colonnes sont remplies :
    #   * compteurs (trades, mints, burns, listings, drops...) = SOMME des mois ;
    #   * wallets (actifs, acheteurs, vendeurs, minters) = UNION des mois (on ne
    #     peut pas sommer des uniques) ;
    #   * acc_net_moy/pos/neg = net cumule sur l'annee, par wallet ;
    #   * churn = % des actifs de l'annee precedente sans AUCUNE activite cette
    #     annee ; anciens = wallets reveilles (>6 mois), dedupliques.
    # Memoire : les unions sont construites UNE ANNEE A LA FOIS puis liberees.
    months_by_y: Dict[str, List[str]] = {}
    for m in months_sorted:
        months_by_y.setdefault(m[:4], []).append(m)
    new_by_y = Counter(v[:4] for v in first_month.values())
    prev_y = None
    for y in sorted(months_by_y):
        act: set = set()
        buyers: set = set()
        sellers: set = set()
        minters: set = set()
        net_y: Counter = Counter()
        trades = mints = burns = listings = air = drp = wed = 0
        listers: set = set()
        for m in months_by_y[y]:
            mo = monthly[m]
            listers |= (mo.get("listers") or set())
            act |= mo["actives"]
            buyers |= mo["buyers"]
            sellers |= mo["sellers"]
            minters |= mo["minters"]
            net_y.update(mo["net"])
            trades += mo["market"]
            mints += mo["mints"]
            burns += mo["burns"]
            listings += mo["listings"]
            air += air_by_m.get(m, 0)
            drp += drops_by_m.get(m, 0)
            wed += wed_by_m.get(m, 0)
        churn = ""
        if prev_y:
            gone = sum(1 for w in prev_y if w not in act)
            churn = round(100.0 * gone / len(prev_y), 1)
        pos = sum(1 for v in net_y.values() if v > 0)
        neg = sum(1 for v in net_y.values() if v < 0)
        avg = round(sum(net_y.values()) / len(net_y), 2) if net_y else 0
        og = sum(1 for w in act if first_month.get(w, "9999") < OG_CUTOFF)
        og_pct = round(100.0 * og / len(act), 1) if act else ""
        rows.append([y, len(act), new_by_y.get(y, 0), trades,
                     len(buyers), len(sellers), mints, air, len(minters),
                     drp, burns, listings, avg, pos, neg, churn, wed,
                     anciens_by_y.get(y, 0), og, og_pct, len(listers), ""])
        prev_y = act
        buyers = sellers = minters = net_y = None
    return rows


def _fill_pulse_revenue(rows, mint_month_uuid, store_price) -> int:
    """Remplit la colonne `revenue_drop` du pulse (mois ET annees).

    Le calcul ne peut pas se faire dans replay() : il faut les prix, qui sont
    lus dans le Sheet APRES le rejeu. On patche donc les lignes deja bâties."""
    i = PULSE_HEADER.index("revenue_drop")
    par_mois: Dict[str, float] = defaultdict(float)
    sans_prix = 0
    for (m, uid), cnt in mint_month_uuid.items():
        p = store_price.get(uid)
        if p:
            par_mois[m] += cnt * p
        else:
            sans_prix += cnt
    par_an: Dict[str, float] = defaultdict(float)
    for m, v in par_mois.items():
        par_an[m[:4]] += v
    remplis = 0
    for r in rows:
        cle = str(r[0])
        v = par_an.get(cle) if len(cle) == 4 else par_mois.get(cle)
        if v:
            r[i] = round(v)
            remplis += 1
    print(f"    revenue mensuel : {remplis} periode(s) valorisee(s) "
          f"({sans_prix} mints sans prix connu — ere IMX ou item retire du "
          f"store).", flush=True)
    return remplis


def _write_reveils(sh, reveils) -> int:
    """Onglet CACHE _Reveils (date_pt, anciens), lu par 📊 STATS.
    Meme patron que _MonthlyPulse : le ledger calcule, stats_page affiche."""
    ws = _open_worksheet(sh, REVEIL_TAB, cols=len(REVEIL_HEADER))
    ws.clear()
    grid = [list(REVEIL_HEADER)] + [[j, reveils[j]] for j in sorted(reveils)]
    ws.update(range_name="A1", values=grid, value_input_option="RAW")
    try:
        ws.freeze(rows=1)
        ws.hide()
    except Exception:
        pass
    return len(grid) - 1


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
    # Chunk par CELLULES (~200k/appel), pas par lignes : 🎯A-CORNERISATION est
    # devenu large (~110 colonnes avec la fiche VeveFox) -> un seul update de
    # 8 600 lignes x 110 col frolerait le 400 "request too large".
    step = max(1, 200000 // max(1, len(header)))
    for i in range(0, len(grid), step):
        chunk = grid[i:i + step]
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


def build_all(folder: str, snap_folder: str, sh, top: int, today: _dt.date,
              imx_folder: str = ""):
    (ledger_replay, prof, n, pulse_rows,
     mint_month_uuid, reveils) = replay(folder, imx_folder)
    print(f"Rejeu : {len(ledger_replay)} editions, {len(prof)} wallets, "
          f"{n} transferts.", flush=True)

    snap, snap_names, skipped = load_snapshot(snap_folder)
    n_snap = len(snap)          # merge_state CONSOMME snap (fix OOM 11/07)
    if snap:
        ledger, sstats = merge_state(ledger_replay, snap)
        print(f"Snapshot holders : {n_snap} editions — etat PRESENT prioritaire "
              f"(owned={sstats.get('owned', 0)}, burned={sstats.get('burned', 0)}, "
              f"escrow_resolu={sstats.get('escrow_resolved', 0)}, "
              f"escrow_inconnu={sstats.get('escrow_unresolved', 0)}, "
              f"stock_veve={sstats.get('system_stock', 0)}, "
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

    # REVENUE DROP mensuel (colonne Drop du tableau 📅 PAR MOIS) : les mints du
    # mois, airdrops deduits, valorises au prix store ACTUEL. Valeur de
    # REMPLACEMENT (meme convention que les burns en $) : on n'a pas les prix
    # historiques. Ere CollectChain seulement (l'IMX n'a pas d'uuid).
    _fill_pulse_revenue(pulse_rows, mint_month_uuid, store_price)

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
            "last_active": p["last"], "listed": listed_cnt.get(w, 0),
            # 🎯 airdrop-only : TOUTE son activite = recevoir des airdrops
            # (aucun achat/vente/burn, tous ses mints viennent d'airdrops
            # detectes) -> son statut "Actif" est artificiel.
            "airdropOnly": ("🎯" if (p["mints"] > 0 and p["buys"] == 0
                                     and p["sells"] == 0
                                     and p.get("airdrop_mints", 0) >= p["mints"])
                            else "")}

    # TYPOLOGIE des whales : 3 blocs (top `top` par critere).
    # Les rangs sont RECOPIES dans le profil -> 🟣C-PSEUDOS les porte, donc
    # l'onglet 🐋 n'a plus de raison d'exister.
    whale_blocks = []
    for title, key in WHALE_TYPES:
        ranked = sorted(profiles.items(), key=lambda kv: -kv[1][key])[:top]
        rows = []
        for rank, (w, pr) in enumerate(ranked, 1):
            pr[RANK_COLS[key]] = rank
            rows.append([rank, w, pr["pseudo"], pr[key], pr["holdings"],
                         pr["distinct_collectibles"], pr["value_store"],
                         pr["value_floor"], pr["collectorScore"],
                         pr["activityStatus"]])
        whale_blocks.append((title, rows))

    # CORNERISATION : 1 ligne/item, ENRICHIE de la fiche complete (demande Preda
    # 15/07) — les modules VeveFox de 📊 STATS tirent tout de cet onglet.
    corner = []
    for uid, holders in per_uuid.items():
        counts = sorted(holders.items(), key=lambda x: -x[1])
        circ = sum(c for _w, c in counts)
        nm, cat = names.get(uid) or snap_names.get(uid) or ("", "")
        gini_v = _gini([c for _w, c in counts])
        row = [uid, nm, cat, circ, len(holders), gini_v]
        for i in range(10):
            if i < len(counts):
                cnt = counts[i][1]
                row += [cnt, round(100.0 * cnt / circ, 2) if circ else 0]
            else:
                row += ["", ""]
        # ventilation de l'offre par bucket qty / valeur / score / activite
        b_qty, b_vs, b_vf, b_sc, b_ac, b_en = (Counter(), Counter(), Counter(),
                                               Counter(), Counter(), Counter())
        # PERSONNES (wallets) par activite / profil / taille, quantite detenue
        # (pers + supply), heatmaps croisees, scores moyens ponderes.
        pers_ac, pers_sc, ws_w = Counter(), Counter(), Counter()
        hold_w, hold_t = Counter(), Counter()
        hm_pa, hm_pw, hm_aw = Counter(), Counter(), Counter()
        sum_c = wt_c = sum_a = wt_a = 0.0
        for w, c in counts:
            qb = qbk.get(w, "1")
            sc = score.get(w, "n/a")
            ac = activity.get(w, "")
            b_qty[qb] += c
            b_vs[vsbk.get(w, "<100")] += c
            b_vf[vfbk.get(w, "<100")] += c
            b_sc[sc] += c
            b_ac[ac] += c
            b_en[engage.get(w, "n/a")] += c
            pers_sc[sc] += 1
            pers_ac[ac] += 1
            ws_w[qb] += 1
            hb = hold_bucket(c)
            hold_w[hb] += 1
            hold_t[hb] += c
            pk = "Unclassified" if sc == "n/a" else sc
            akk = "Non classé" if ac == "" else ac
            hm_pa[(pk, akk)] += c
            hm_pw[(pk, qb)] += c
            hm_aw[(akk, qb)] += c
            if sc in SCORE_MID:
                sum_c += SCORE_MID[sc] * c
                wt_c += c
            if ac in ACTIVITY_MID:
                sum_a += ACTIVITY_MID[ac] * c
                wt_a += c
        for dist, order in ((b_qty, QTY_ORDER), (b_vs, VALUE_ORDER),
                            (b_vf, VALUE_ORDER), (b_sc, SCORES + ["n/a"]),
                            (b_ac, ACTIVITIES),
                            (b_en, ENGAGEMENTS + ["n/a"])):
            d, pct = _dominant(dist, order)
            row += [d, pct]
        # --- FICHE COMPLETE (meme ordre que CORNER_HEADER) ---
        # cles internes : activite "" = "Non classé", score "n/a" = "Unclassified".
        ac_keys = ACTIVITIES + [""]          # aligne sur ACTIVITY_ORDER
        sc_keys = SCORES + ["n/a"]           # aligne sur PROFILE_ORDER
        row += [round(sum_c / wt_c, 1) if wt_c else "",
                round(sum_a / wt_a, 1) if wt_a else ""]
        row += [pers_ac.get(k, 0) for k in ac_keys]        # act_pers_*
        row += [b_ac.get(k, 0) for k in ac_keys]           # act_sup_*
        row += [pers_sc.get(k, 0) for k in sc_keys]        # prof_pers_*
        row += [b_sc.get(k, 0) for k in sc_keys]           # prof_sup_*
        row += [ws_w.get(k, 0) for k in QTY_ORDER]         # ws_pers_*
        row += [b_qty.get(k, 0) for k in QTY_ORDER]        # ws_sup_*
        row += [hold_w.get(k, 0) for k in HOLD_ORDER]      # hold_pers_*
        row += [hold_t.get(k, 0) for k in HOLD_ORDER]      # hold_sup_*
        row += [
            "|".join(";".join(str(hm_pa.get((p, a), 0)) for a in ACTIVITY_ORDER)
                     for p in PROFILE_ORDER),
            "|".join(";".join(str(hm_pw.get((p, q), 0)) for q in QTY_ORDER)
                     for p in PROFILE_ORDER),
            "|".join(";".join(str(hm_aw.get((a, q), 0)) for q in QTY_ORDER)
                     for a in ACTIVITY_ORDER)]
        corner.append(row)
    corner.sort(key=lambda r: -r[3])

    # DISTRIBUTION GLOBALE des wallets par taille (quantite + valeur)
    size_rows = _size_distribution(profiles, value_store, value_floor)

    return (ledger, prof, whale_blocks, corner, size_rows, profiles,
            pulse_rows, reveils)


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
            "airdropOnly", "pseudo", "last_active", "listed"]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["wallet"] + cols)
        for wl, pr in profiles.items():
            w.writerow([wl] + [pr.get(c, "") for c in cols])


def _write_size_history(sh, size_rows, month):
    """Append-only mensuel : upsert des lignes du mois dans l'onglet CACHE
    _WalletSize (rendu sur 📊 STATS). Migration : au 1er passage, reprend
    l'historique de l'ancien onglet visible 📈H-WALLET-SIZE puis le SUPPRIME
    (fusion des pages, choix Preda 11/07)."""
    ws = _open_worksheet(sh, SIZE_TAB, cols=len(SIZE_HEADER))
    existing = ws.get_all_records() if ws.row_count > 1 else []
    if not existing:
        try:
            existing = sh.worksheet(OLD_SIZE_TAB).get_all_records()
            print(f"    migration : historique repris de {OLD_SIZE_TAB} "
                  f"({len(existing)} lignes).", flush=True)
        except Exception:
            pass
    kept = [[r.get(c, "") for c in SIZE_HEADER] for r in existing
            if str(r.get("snapshot_month", "")) != month]
    fresh = [[month] + row for row in size_rows]
    grid = [list(SIZE_HEADER)] + kept + fresh
    ws.clear()
    for i in range(0, len(grid), 50000):
        if i == 0:
            ws.update(range_name="A1", values=grid[:50000], value_input_option="RAW")
        else:
            ws.append_rows(grid[i:i + 50000], value_input_option="RAW")
    try:
        ws.freeze(rows=1)
        ws.format("1:1", {"textFormat": {"bold": True}})
        ws.hide()
    except Exception:
        pass
    try:
        sh.del_worksheet(sh.worksheet(OLD_SIZE_TAB))
        print(f"    onglet {OLD_SIZE_TAB} supprime (fusionne dans 📊 STATS).",
              flush=True)
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
    connus = set()
    for r in rows:
        w = str(r.get("wallet_imx", "")).strip().lower()
        if w:
            connus.add(w)
        pr = profiles.get(w)
        if not pr:
            continue
        for c in PSEUDO_PROFILE_COLS:
            r[c] = pr.get(c, "")
        updated += 1

    # Les whales ABSENTES de l'onglet y sont AJOUTEES (le trou de l'ancienne
    # version : _enrich_pseudos n'enrichissait que les lignes existantes, donc
    # une whale sans pseudo connu n'apparaissait nulle part hors de 🐋).
    ajoutes = 0
    for w in sorted(w for w, pr in profiles.items()
                    if any(pr.get(c) for c in RANK_COLS.values())):
        if w in connus:
            continue
        pr = profiles[w]
        r = {c: "" for c in PSEUDOS_HEADER}
        r["wallet_imx"] = w
        r["username"] = pr.get("pseudo", "")
        r["source"] = "ledger"
        r["status"] = "whale"
        for c in PSEUDO_PROFILE_COLS:
            r[c] = pr.get(c, "")
        rows.append(r)
        ajoutes += 1
    if ajoutes:
        print(f"    🟣C-PSEUDOS : {ajoutes} whale(s) ajoutee(s) "
              f"(absentes de l'annuaire).", flush=True)
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


def _write_whales_flat(sh, blocks) -> int:
    """Onglet CACHE _Whales : source du classement 🐋 rendu sur 📊 STATS.

    Une ligne par (bloc, rang) — meme patron que _MonthlyPulse / _WalletSize :
    le ledger calcule, stats_page affiche. L'onglet visible 🐋A-WHALES est
    supprime (choix Preda 13/07) : son detail vit desormais dans 🟣C-PSEUDOS
    (colonnes rang_qty / rang_floor / rang_store + tout le profil)."""
    header = ["bloc"] + list(WHALE_BLOCK_COLS)
    grid = [header]
    for title, rows in blocks:
        for r in rows:
            grid.append([title] + list(r))
    ws = _open_worksheet(sh, WHALES_TAB, cols=len(header))
    ws.clear()
    ws.update(range_name="A1", values=grid, value_input_option="RAW")
    try:
        ws.freeze(rows=1)
        ws.format("1:1", {"textFormat": {"bold": True}})
        ws.hide()
    except Exception:
        pass
    try:
        sh.del_worksheet(sh.worksheet(OLD_WHALES_TAB))
        print(f"    onglet {OLD_WHALES_TAB} supprime (classement -> 📊 STATS, "
              f"detail -> 🟣C-PSEUDOS).", flush=True)
    except Exception:
        pass
    return len(grid) - 1


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


def _open_with_retry(sheet_id):
    """Ouvre le Sheet en encaissant un 429 (quota de LECTURE par minute) — le
    ledger peut tomber juste apres un autre gros job (demande Preda 15/07 :
    « faudra lui mettre a l'occasion »). Backoff genereux ; les autres lectures
    du ledger degradent deja proprement (try/except -> vide), le seul point qui
    PLANTE est l'ouverture."""
    from gspread.exceptions import APIError
    for i, d in enumerate((0, 15, 30, 45, 60, 60)):
        if d:
            print(f"  ouverture du Sheet : quota atteint, pause {d}s...",
                  flush=True)
            time.sleep(d)
        try:
            return _client().open_by_key(sheet_id)
        except APIError as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code not in (429, 503) or i == 5:
                raise
    return _client().open_by_key(sheet_id)


def main() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        print("ERROR: SHEET_ID requis.", file=sys.stderr)
        return 2
    folder = os.environ.get("ARCHIVE_DIR", "dl")
    snap_folder = os.environ.get("SNAPSHOT_DIR", "dl_snap")
    imx_folder = os.environ.get("IMX_DIR", "dl_imx")
    top = int(os.environ.get("WHALES_TOP", "100"))
    rd = os.environ.get("RUN_DATE")
    today = _dt.date.fromisoformat(rd) if rd else _dt.date.today()

    have_archive = bool(_archive_files(folder))
    have_snap = bool(_snapshot_files(snap_folder))
    have_imx = bool(_imx_files(imx_folder))
    print(f"Sources : archive transferts={'OUI' if have_archive else 'non'} "
          f"({folder}), snapshot holders={'OUI' if have_snap else 'non'} "
          f"({snap_folder}), archive IMX={'OUI' if have_imx else 'non'} "
          f"({imx_folder}).", flush=True)
    if not have_archive and not have_snap:
        print(f"Aucune source : ni archive dans '{folder}' ni snapshot dans "
              f"'{snap_folder}'.", file=sys.stderr)
        try:
            append_log(sheet_id, "ledger", "FAILED_NO_DATA",
                       f"no gz in {folder} nor {snap_folder}")
        except Exception:
            pass
        return 1

    # Etapes ciblables a la main (meme patron que daily.yml) :
    #   all | whales | size | pseudos | pulse | corner
    # Le rejeu de l'archive est toujours fait (c'est lui qui produit tout) ;
    # les gates evitent de REECRIRE les onglets qu'on ne veut pas toucher.
    steps = os.environ.get("LEDGER_STEPS", "all").lower()

    def do(step: str) -> bool:
        return "all" in steps or step in steps

    sh = _open_with_retry(sheet_id)
    (ledger, prof, whale_blocks, corner, size_rows, profiles,
     pulse_rows, reveils) = build_all(folder, snap_folder, sh, top, today,
                                      imx_folder)

    _save_ledger(ledger, os.environ.get("LEDGER_OUT", "data/ledger.csv.gz"))
    _save_profiles(profiles,
                   os.environ.get("PROFILES_OUT", "data/wallet_profiles.csv.gz"))
    enriched = 0
    if do("whales"):
        _write_whales_flat(sh, whale_blocks)               # 🐋 -> _Whales (cache)
    if do("corner"):
        _write(sh, CORNER_TAB, CORNER_HEADER, corner)      # 🎯 (fiche complete)
    if do("size"):
        _write_size_history(sh, size_rows, today.strftime("%Y-%m"))   # 📈
    if do("pseudos"):
        enriched = _enrich_pseudos(sh, profiles)           # 🟣 profils
    if do("pulse"):
        try:
            _write_pulse(sh, pulse_rows)                   # 📅 pulse (cache)
            _write_reveils(sh, reveils)                    # 👴 anciens / jour
        except Exception as e:
            print(f"pulse warning: {e}", flush=True)

    # --- confort visuel : couleurs de tiers + heatmap Gini + formats nombres ---
    try:
        from scraper.stackr import PSEUDOS_HEADER
        _fmt.format_tab(sh, CORNER_TAB, CORNER_HEADER, header_rows=1)
        _fmt.format_tab(sh, SIZE_TAB, SIZE_HEADER, header_rows=1)
        _fmt.format_tab(sh, "🟣C-PSEUDOS", PSEUDOS_HEADER, header_rows=1)
    except Exception as e:
        print(f"formatting warning: {e}", flush=True)

    # 🏠ACCUEIL supprime (10/07, choix Preda) : la synthese vit sur 📊 STATS
    # (module stats_page, daily step 7). _write_dashboard n'est plus appele.

    n_air = sum(1 for pr in profiles.values() if pr.get("airdropOnly"))
    summary = {"status": "OK", "airdrop_only": n_air, "editions": len(ledger),
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
