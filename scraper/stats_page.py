"""
📊 STATS — LA page de synthese du Sheet (remplace 🏠ACCUEIL, supprime).\nv9 (11/07) : colonne Drop apres la Date (jours d influence) ; LISTING =\nQuantite + Comptes (uniques) — les purs sortent du tableau.

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
import csv
import gzip
import io
import urllib.request
from collections import Counter, defaultdict
from typing import Any, Dict, List

from scraper.sheets import _client, _open_worksheet, append_log
from scraper import health as _health
from scraper import fiche as _fiche

STATS_TAB = os.environ.get("STATS_TAB", "📊 STATS")
OLD_HOME_TAB = "🏠ACCUEIL"          # supprime au 1er run (choix Preda 10/07)

WEEK_DAYS = int(os.environ.get("STATS_WEEK_DAYS", "7"))
TOP_SERIES = int(os.environ.get("STATS_TOP_SERIES", "8"))

# ⚠️ LES LIGNES 1 A 13 APPARTIENNENT A PREDA (13/07). Il y met son contenu.
# La page ne les ECRIT PAS, ne les EFFACE PAS, ne les FORMATE PAS. Tout le
# reste demarre en dessous. Le bandeau noir (titre + sous-titre) est SUPPRIME.
ZONE_PREDA = int(os.environ.get("STATS_ZONE_PREDA", "13"))
START_ROW = ZONE_PREDA + 1           # 14 : 1re ligne que la page s'autorise
TABLE_START_ROW = 20                 # 1re ligne de donnees du tableau quotidien
GROUP_ROW = 18                       # ligne des groupes
HEADER_ROW = 19                      # ligne des colonnes
# Le tableau occupe A..S (19 col.). La colonne T reste VIDE (demande Preda) :
# les modules de droite commencent en U, et le 2e bloc de modules recule en AH
# pour ne pas percuter le PULSE (U..AF, 12 colonnes).
MODULE_COL = "V"                     # modules de droite (apres la colonne vide U)
LISTING_TAB = "_ListingDaily"        # source du groupe LISTING (chain_run)
PULSE_TAB = "_MonthlyPulse"          # source du 📅 pulse mensuel (ledger)
PULSE_ROW = 59
YEAR_ROW = 126                       # 📅 PAR ANNÉE + 📈 PULSE annuel
NOTES_ROW = 142                      # ℹ️ notes & legendes, sous le tableau annuel (v14)
# 2e colonne de modules : AF (la colonne T est prise par les tailles (8-20),
# la sante (22-35) PUIS par le PULSE des le rang 49 -> tout bloc pose en T
# au-dela de 36 entrerait en COLLISION avec le pulse).
MODULE_COL2 = "AI"
BURNS_ROW = 18                       # 🔥 synthese burns
UNIVERS_ROW = 34                     # 🏪 univers de marche
UNIVERS_TAB = "_MarketUniverse"      # ecrit par scraper/market_universe.py

# 🐋 CLASSEMENT WHALES (13/07) : l'onglet 🐋A-WHALES est supprime, son
# classement est rendu ICI, sous les notes. Source = onglet cache _Whales
# (ecrit par le workflow ledger, comme _MonthlyPulse). Le detail par wallet
# (rangs + profil complet) vit dans 🟣C-PSEUDOS.
WHALES_TAB = "_Whales"
WHALES_ROW = int(os.environ.get("STATS_WHALES_ROW", "175"))
# 🦊 FICHE PAR ITEM (module interactif VeveFox) — sous le classement whales.
FICHE_ROW = int(os.environ.get("STATS_FICHE_ROW", "205"))
WHALES_TOP = int(os.environ.get("STATS_WHALES_TOP", "20"))
WHALE_COLS = ["Rang", "Wallet", "Pseudo", "Critère", "Exemplaires",
              "Collectibles", "Valeur store $", "Valeur floor $", "Score",
              "Activité"]
# LES EN-TETES SONT LA SEULE VERITE : l'habillage (stats_format) en deduit les
# formats. Ajouter une colonne ne peut plus decaler un format.
COLS_TABLE = ["Date", "Drop", "Global", "Mint", "Airdrop", "Market", "Burn",
              "Unique", "Nouveaux", "Anciens", "Quantité", "Comptes",
              "Total", "Drop", "Market", "Global $", "OMI→NFT", "OMI→GEM",
              "Cours OMI $", "Gems $"]
COLS_VVF = ["Mois", "Acheteurs uniques", "Vendeurs uniques",
            "Minters uniques", "Drops", "Acc. nette moy", "Net+", "Net−",
            "Rétention %", "Churn %", "OG 21-22", "OG %"]
UNIVERS_DAYS = int(os.environ.get("STATS_UNIVERS_DAYS", "15"))  # 2 semaines
# Offre OMI EN CIRCULATION (CoinGecko / ECOMI, juillet 2026 : 270 951 644 947 ;
# offre TOTALE 750 Md). Env OMI_CIRCULATING pour la reactualiser.
OMI_CIRCULATING = float(os.environ.get("OMI_CIRCULATING", "270951644947"))
BURNS_RATE_DAYS = int(os.environ.get("STATS_BURN_RATE_DAYS", "30"))
# 60 mois par defaut : l'histoire complete 2021->2026 (pulse IMX) tient
# dans la zone mensuelle (gs v6 formate jusqu'a la ligne 120).
PULSE_MONTHS = int(os.environ.get("STATS_PULSE_MONTHS", "60"))

# 💎 GEMS ACHETES (demande Preda 13/07) — AUCUNE collecte nouvelle.
# Le contrat OmiToGems brule exactement GEM_BURN_PCT de chaque conversion, et
# c'est ce que mesure deja la colonne omi_gem de 🔥H-BURNS. Donc :
#     OMI depenses en gems = omi_gem / GEM_BURN_PCT
#     gems achetes ($)     = ces OMI x le cours du jour
# Et comme 1 gem = 1 $, ce montant EST le nombre de gems achetes.
# Interet : un pic d'achat de gems la VEILLE d'un drop = signal d'anticipation.
GEM_BURN_PCT = float(os.environ.get("GEM_BURN_PCT", "0.07"))


def gems_achetes(omi_gem: dict, rates: dict) -> dict:
    """{date -> $ de gems achetes} depuis le burn de 7 % et le cours du jour."""
    if not omi_gem or GEM_BURN_PCT <= 0:
        return {}
    usd = omi_to_usd({d: v / GEM_BURN_PCT for d, v in omi_gem.items()},
                     rates or {})
    return {d: v for d, v in usd.items() if v}
# AIRDROP (seuils Preda 11/07) : (jour, uuid) avec mints >= MIN et minters
# uniques >= RATIO x mints — detecte ici depuis ChainItems (fenetre 35 j).
AIRDROP_MIN_MINTS = int(os.environ.get("AIRDROP_MIN_MINTS", "2000"))
AIRDROP_MINTER_RATIO = float(os.environ.get("AIRDROP_MINTER_RATIO", "0.9"))
# Jour du dump de migration IMX->CC : re-mints automatiques, pas des airdrops.
MIGRATION_DAY = os.environ.get("CC_MIGRATION_DAY", "2026-01-28")

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
MARKET_REV_TAB = "_MarketRevenue"     # ventes StackR reelles (stackr_sales)
VEVE_REV_TAB = "_VeveRevenue"         # v15 : flux VeVe PUBLIC (veve_tx)

# Onglets de SERVICE a MASQUER (demande Preda 15/07) — masques, pas supprimes :
# ils restent LUS par le code (🤖LOGS par health.py, 🔗A-RACCORD par
# classement.py) mais sortent de la vue. Cf. write_stats (fin).
HIDE_TABS = ("🤖LOGS", "🔗A-RACCORD")

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


def _records_pulse(sh, tries: int = 4):
    """Lecture ROBUSTE de _MonthlyPulse. _records avale les exceptions et renvoie
    [] : un simple hoquet de l'API Google effacait alors les blocs 📅 PAR MOIS/
    ANNÉE de la page (incident 16/07). On reessaie avant d'abandonner ; le vrai
    pulse compte des dizaines de lignes, [] = quasi toujours un transitoire."""
    for i in range(tries):
        recs = _records(sh, PULSE_TAB)
        if recs:
            return recs
        if i + 1 < tries:
            time.sleep(2 * (i + 1))
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
    """{date_pt -> (listings, listers)} depuis _ListingDaily.
    v9 (choix Preda 11/07) : Quantite = total des depots du jour, Comptes =
    comptes UNIQUES ayant liste au moins un item (les 'purs' sortent du
    tableau — restent stockes dans _ListingDaily si besoin un jour)."""
    out: Dict[str, tuple] = {}
    for r in _records(sh, LISTING_TAB):
        d = str(r.get("date", "")).strip()
        if d:
            out[d] = (_n(r.get("listings")), _n(r.get("listers")))
    return out


# ---------------------------------------------------------------------------
# Colonne Drop (v9, demande Preda 11/07) : le nom du drop du jour apres la
# Date, pour reperer les jours d influence. Source = catalogues froids
# (releaseDate) ; un drop = une SERIE sortie ce jour (raretes regroupees).
# ---------------------------------------------------------------------------
CATALOG_DROPS = (("🟢C-COMICS", "comic"), ("🔵C-COLLECTIBLE", "collectible"))


def _pt_date(raw) -> str:
    """releaseDate (ISO UTC ou serial Sheets) -> jour PACIFIQUE du drop."""
    sv = str(raw or "").strip()
    if not sv:
        return ""
    try:
        if sv.replace(".", "", 1).isdigit():      # serial (lecture unformatted)
            dt = (_dt.datetime(1899, 12, 30, tzinfo=_dt.timezone.utc)
                  + _dt.timedelta(days=float(sv)))
        else:
            dt = _dt.datetime.fromisoformat(sv.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_dt.timezone.utc)
    except ValueError:
        return sv[:10]
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:
        return (dt - _dt.timedelta(hours=8)).date().isoformat()


def load_drop_names(sh) -> Dict[str, List[tuple]]:
    """{date_pt -> [(nom de serie, kind), ...]} — lecture CIBLEE de 3-4
    colonnes des catalogues (pas de get_all_records : ~25 colonnes dont les
    descriptions, trop lourd)."""
    out: Dict[str, List[tuple]] = defaultdict(list)

    def _letter(idx1: int) -> str:
        s2, n = "", idx1
        while n:
            n, r = divmod(n - 1, 26)
            s2 = chr(65 + r) + s2
        return s2

    for tab, kind in CATALOG_DROPS:
        try:
            ws = sh.worksheet(tab)
            head = ws.row_values(1)
            idx = {c: head.index(c) + 1 for c in
                   ("releaseDate", "veve_series_name", "series_uuid", "name")
                   if c in head}
            if "releaseDate" not in idx:
                continue
            wanted = [c for c in ("releaseDate", "veve_series_name",
                                  "series_uuid", "name") if c in idx]
            try:
                from gspread.utils import ValueRenderOption
                blocks = ws.batch_get(
                    [f"{_letter(idx[c])}2:{_letter(idx[c])}" for c in wanted],
                    value_render_option=ValueRenderOption.unformatted)
            except TypeError:
                blocks = ws.batch_get(
                    [f"{_letter(idx[c])}2:{_letter(idx[c])}" for c in wanted])
            cols = {c: [row[0] if row else "" for row in blk]
                    for c, blk in zip(wanted, blocks)}
            n = max((len(v) for v in cols.values()), default=0)
            seen = set()
            for i in range(n):
                def _g(c):
                    v = cols.get(c, [])
                    return str(v[i]).strip() if i < len(v) else ""
                d = _pt_date(_g("releaseDate"))
                if not d:
                    continue
                name = _g("veve_series_name") or _g("name") or "(sans nom)"
                key = (d, _g("series_uuid") or name.lower())
                if key in seen:
                    continue
                seen.add(key)
                # comics du MERCREDI (PT) = parutions vevecomics silencieuses
                # (calees sur la sortie physique, jamais annoncees) — dissociees
                # des drops classiques (demande Preda 11/07).
                k = kind
                if kind == "comic":
                    try:
                        if _dt.date.fromisoformat(d).weekday() == 2:
                            k = "vevecomic"
                    except ValueError:
                        pass
                out[d].append((name, k))
        except Exception as e:
            print(f"drops {tab} warning: {e}", flush=True)
    return out


def drop_label(entries) -> str:
    """1 drop -> son nom ; plusieurs -> comptage type 2x comics + 1
    collectible (choix Preda 11/07 : reperer les jours d influence)."""
    if not entries:
        return ""
    if len(entries) == 1:
        return entries[0][0]
    c = Counter(k for _, k in entries)
    parts = []
    for kind, plural in (("comic", "comics"), ("collectible", "collectibles"),
                         ("vevecomic", "vvbd")):
        nb = c.get(kind, 0)
        if nb == 1:
            parts.append(f"1 {kind}")
        elif nb > 1:
            parts.append(f"{nb}x {plural}")
    return " + ".join(parts)


def read_market_revenue(sh):
    """(usd, rates) : {date_pt -> revenue market $} et {date_pt -> cours OMI}
    depuis _MarketRevenue (ventes StackR reelles + taux quotidiens)."""
    usd: Dict[str, float] = {}
    rates: Dict[str, float] = {}
    def _f(x):
        try:
            return float(str(x).replace(",", ".") or 0)
        except (TypeError, ValueError):
            return 0.0
    for r in _records(sh, MARKET_REV_TAB):
        d = str(r.get("date", "")).strip()
        if not d:
            continue
        v = _f(r.get("usd"))
        if v:
            usd[d] = v
        rt = _f(r.get("omi_usd"))
        if rt:
            rates[d] = rt
    return usd, rates


def omi_to_usd(omi: Dict[str, float], rates: Dict[str, float]):
    """{date -> OMI} x cours du jour (report du dernier cours connu) -> $."""
    if not rates:
        return {}
    out: Dict[str, float] = {}
    known = sorted(rates)
    last = rates[known[0]]
    ki = 0
    for d in sorted(omi):
        while ki < len(known) and known[ki] <= d:
            last = rates[known[ki]]
            ki += 1
        out[d] = omi[d] * last
    return out


def read_veve_revenue(sh):
    """v15 — (drop, market) : {date_pt -> $} depuis _VeveRevenue (flux VeVe
    PUBLIC collecte par scraper/veve_tx.py).

      * drop   = CART_FIAT + STORE_GEM = revenue drop REEL (remplace
        l'estimation mints x prix store les jours couverts) ;
      * market = MARKET_FIXED (ventes VeVe en gems) + MARKET_STACKR (ventes
        StackR) = le marche SECONDAIRE COMPLET (les ventes VeVe en gems
        manquaient jusqu'ici : c'etait la borne basse du chantier 7).
    """
    drop: Dict[str, float] = {}
    market: Dict[str, float] = {}
    def _fl(x):
        try:
            return float(str(x).replace(",", ".") or 0)
        except (TypeError, ValueError):
            return 0.0
    for r in _records(sh, VEVE_REV_TAB):
        d = str(r.get("date", "")).strip()
        if not d:
            continue
        v = _fl(r.get("drop_usd"))
        if v:
            drop[d] = v
        m = _fl(r.get("market_veve_usd")) + _fl(r.get("market_stackr_usd"))
        if m:
            market[d] = m
    return drop, market


def detect_airdrop_daily(items: List[Dict[str, Any]]) -> Dict[str, int]:
    """{date -> mints d'airdrop} depuis ChainItems : un (jour, item) avec
    mints >= AIRDROP_MIN_MINTS et minters uniques >= 90 % des mints = airdrop
    (~1 exemplaire par wallet). Separe, jamais jete (choix Preda)."""
    out: Dict[str, int] = defaultdict(int)
    for r in items:
        m = _n(r.get("mints"))
        u = _n(r.get("unique_minters"))
        d = str(r.get("date", "")).strip()
        if d == MIGRATION_DAY:
            continue           # re-mints de migration, pas des airdrops
        if d and m >= AIRDROP_MIN_MINTS and u >= AIRDROP_MINTER_RATIO * m:
            out[d] += m
    return dict(out)


def _ret_pct(c):
    """Rétention % = 100 − churn (v14 : les blocs 🔄 RÉTENTION autonomes sont
    supprimés — l'info vit dans les blocs 📈 PULSE, demande Preda 12/07)."""
    try:
        return round(100.0 - float(c), 1)
    except (TypeError, ValueError):
        return ""


def _period_tables(recs, cat, usd, nft, gem, mkt, label, titre, titre_vvf,
                   gems=None, cours=None):
    """Couple (tableau periode, pulse periode) pour un grain donne — utilise
    pour les MOIS ("YYYY-MM") et les ANNÉES ("YYYY"). Memes 18 colonnes que le
    tableau quotidien pour le tableau de gauche."""
    table: List[List] = [
        [titre],
        ["", "", "TRANSACTION", "", "", "", "", "ACTIF", "", "",
         "LISTING", "", "REVENUE", "", "", "OMI BURN", "", "", "ACHAT", ""],
        [label, "Drop", "Global", "Mint", "Airdrop", "Market", "Burn",
         "Unique", "Nouveaux", "Anciens", "Quantité", "Comptes",
         "Total", "Drop", "Market", "Global $", "OMI→NFT", "OMI→GEM",
         "Cours OMI $", "Gems $"],
    ]
    vvf: List[List] = [
        [titre_vvf],
        [""],
        [label, "Acheteurs uniques", "Vendeurs uniques", "Minters uniques",
         "Drops", "Acc. nette moy", "Net+", "Net−", "Rétention %", "Churn %",
         "OG 21-22", "OG %"],
    ]
    for r in recs:
        p = str(r.get("month", ""))
        tokens = _n(r.get("tokens_emis"))
        air = _n(r.get("tokens_airdrop"))
        trades = _n(r.get("trades"))
        burns = _n(r.get("burns"))
        nd, nv = cat.get(p, (0, 0))
        cell = f"{nd} drops" if nd else ""
        if nv:
            cell = f"{cell} (+{nv} vvbd)" if cell else f"(+{nv} vvbd)"
        u = usd.get(p)
        onft, ogem = nft.get(p), gem.get(p)
        mk = mkt.get(p)
        # REVENUE (13/07) : Drop = mints du mois x prix store (calcule par le
        # ledger, colonne revenue_drop du pulse) ; Total = Drop + Market.
        # Vide avant 2026-01 : l'archive IMX ne porte pas l'uuid de l'item,
        # donc aucun prix n'est rattachable a ces mints.
        rdrop = _n(r.get("revenue_drop"))
        rmkt = round(mk) if mk else 0
        total = (rdrop + rmkt) or ""
        table.append([p, cell,
                      tokens + trades + burns, max(0, tokens - air), air,
                      trades, burns,
                      _n(r.get("actifs")), _n(r.get("nouveaux")),
                      _n(r.get("anciens")),
                      _n(r.get("listings")), _n(r.get("listeurs")) or "",
                      total, rdrop or "", rmkt or "",
                      round(u) if u else "",
                      round(onft) if onft else "",
                      round(ogem) if ogem else "",
                      (cours or {}).get(p) or "",     # cours MOYEN de la periode
                      round((gems or {}).get(p) or 0) or ""])
        c = r.get("churn_pct", "")
        vvf.append([p, _n(r.get("acheteurs")), _n(r.get("vendeurs")),
                    _n(r.get("minters_uniques")), nd or "",
                    r.get("acc_net_moy", ""), _n(r.get("acc_net_pos")),
                    _n(r.get("acc_net_neg")), _ret_pct(c), c,
                    _n(r.get("og_actifs")) or "", r.get("og_pct", "")])
    return table, vvf


def build_pulse_section(pulse_records, omi=None, omi_nft=None, omi_gem=None,
                        market_rev=None, drops=None, rates=None):
    """v14 : retourne (mensuel, vvf_mois, annuel, vvf_annee).

    * mensuel + vvf_mois alignes ligne a ligne (ancre PULSE_ROW) ;
    * annuel + vvf_annee : MEMES colonnes, un an par ligne (ancre YEAR_ROW) ;
    * les blocs 🔄 RÉTENTION autonomes sont SUPPRIMES — Rétention % est
      desormais une colonne des blocs 📈 PULSE (demande Preda 12/07)."""
    if not pulse_records:
        return [], [], [], []
    cat_m: Dict[str, list] = defaultdict(lambda: [0, 0])
    cat_y: Dict[str, list] = defaultdict(lambda: [0, 0])
    for d, entries in (drops or {}).items():
        for _nm, k in entries:
            i = 1 if k == "vevecomic" else 0
            cat_m[d[:7]][i] += 1
            cat_y[d[:4]][i] += 1
    yearly = [r for r in pulse_records if len(str(r.get("month", ""))) == 4]
    pulse_records = [r for r in pulse_records
                     if len(str(r.get("month", ""))) == 7]

    def _moyenne(src, n):
        somme: Dict[str, float] = defaultdict(float)
        cpt: Dict[str, int] = defaultdict(int)
        for d, v in (src or {}).items():
            if v:
                somme[d[:n]] += v
                cpt[d[:n]] += 1
        return {k: somme[k] / cpt[k] for k in somme if cpt[k]}

    def _by(src, n):
        out: Dict[str, float] = defaultdict(float)
        for d, v in (src or {}).items():
            out[d[:n]] += v
        return out

    omi_usd_d = omi_to_usd(omi or {}, rates or {})
    usd_m, usd_y = _by(omi_usd_d, 7), _by(omi_usd_d, 4)
    nft_m, nft_y = _by(omi_nft, 7), _by(omi_nft, 4)
    gem_m, gem_y = _by(omi_gem, 7), _by(omi_gem, 4)
    mkt_m, mkt_y = _by(market_rev, 7), _by(market_rev, 4)
    gems_d = gems_achetes(omi_gem or {}, rates or {})
    gems_m, gems_y = _by(gems_d, 7), _by(gems_d, 4)
    # cours MOYEN de la periode. ⚠️ Il ne sert PAS a refaire le calcul : le
    # total du mois est la SOMME des jours, chacun valorise a SON cours. La
    # moyenne est la pour situer, pas pour multiplier (dit dans la legende).
    cours_m, cours_y = _moyenne(rates, 7), _moyenne(rates, 4)

    recs = sorted(pulse_records, key=lambda r: str(r.get("month", "")),
                  reverse=True)[:PULSE_MONTHS]
    monthly, vvf = _period_tables(
        recs, cat_m, usd_m, nft_m, gem_m, mkt_m, "Mois",
        "📅  PAR MOIS — mêmes colonnes que le tableau quotidien "
        "(archive on-chain, recalculé par le workflow ledger)",
        "📈  PULSE — par mois (wallets UNIQUES par colonne)",
        gems=gems_m, cours=cours_m)

    yrecs = sorted(yearly, key=lambda r: str(r.get("month", "")), reverse=True)
    annual, vvf_y = _period_tables(
        yrecs, cat_y, usd_y, nft_y, gem_y, mkt_y, "Année",
        "📅  PAR ANNÉE — mêmes colonnes que le tableau quotidien "
        "(wallets = UNIQUES sur l'année, jamais la somme des mois)",
        "📈  PULSE — par année (wallets UNIQUES par colonne)",
        gems=gems_y, cours=cours_y)
    return monthly, vvf, annual, vvf_y


def build_wallet_size_section(size_records: List[Dict[str, Any]]) -> List[List]:
    """💰 v13 : les 3 dimensions COTE A COTE (qty | store | floor), separees
    d'une colonne vide (demande Preda 12/07)."""
    if not size_records:
        return []
    months = [str(r.get("snapshot_month", "")) for r in size_records]
    last = max(m for m in months if m) if any(months) else ""
    rows = [r for r in size_records
            if str(r.get("snapshot_month", "")) == last]
    if not rows:
        return []
    dims = ("quantity", "value_store", "value_floor")
    titles = ("Par QUANTITÉ détenue", "Par VALEUR (prix store)",
              "Par VALEUR (floor)")
    cols = []
    for dim in dims:
        cols.append([(str(r.get("bucket", "")), _n(r.get("wallets")),
                      r.get("pct_wallets", ""))
                     for r in rows if str(r.get("dimension", "")) == dim])
    n = max(len(c) for c in cols)
    g: List[List] = [[f"💰  TAILLE DES PORTEFEUILLES — {last}"]]
    head = []
    for t in titles:
        head += [t, "wallets", "%", ""]
    g.append(head[:-1])
    for i in range(n):
        row = []
        for c in cols:
            if i < len(c):
                row += [c[i][0], c[i][1], c[i][2], ""]
            else:
                row += ["", "", "", ""]
        g.append(row[:-1])
    return g


def build_burns_summary(sh, rates) -> List[List]:
    """🔥 SYNTHÈSE BURNS (demande Preda 12/07) — bloc de la colonne T.

    Sources : 🔥H-BURNS (omi_burned = burns du MARCHE, 2 % de chaque vente sur
    0x821c · omi_gem = burns des conversions OMI->gems, 7 %, flux SEPARE qui
    s'AJOUTE · omi_volume_nft = volume des ventes en OMI) et le cours OMI
    quotidien (_MarketRevenue).

    Verifications faites le 12/07 : burns marche / volume = 2,006 % sur 32 j
    (= le taux annonce) et omi_nft == omi_burned au chiffre pres sur les jours
    couverts par la decompo.
    """
    rows = _records(sh, BURNS_TAB)
    if not rows:
        return []
    def _fl(x):
        try:
            return float(str(x).replace(",", ".").replace(" ", "") or 0)
        except (TypeError, ValueError):
            return 0.0
    per: Dict[str, tuple] = {}
    for r in rows:
        d = str(r.get("date", "")).strip()
        if d:
            per[d] = (_fl(r.get("omi_burned")), _fl(r.get("omi_gem")),
                      _fl(r.get("omi_volume_nft")))
    if not per:
        return []
    jours = sorted(per)
    marche = sum(v[0] for v in per.values())
    gems = sum(v[1] for v in per.values())
    total = marche + gems
    # cours : dernier connu (les burns anciens sont valorises au cours actuel —
    # c'est une VALEUR DE REMPLACEMENT, pas la valeur au jour du burn).
    cours = 0.0
    if rates:
        cours = rates[max(rates)]
    recents = jours[-BURNS_RATE_DAYS:]
    r_burn = sum(per[d][0] + per[d][1] for d in recents)
    par_jour = r_burn / max(len(recents), 1)
    par_an = par_jour * 365.0
    defl = 100.0 * par_an / OMI_CIRCULATING if OMI_CIRCULATING else 0
    rec_j = max(per, key=lambda d: per[d][0])
    vol = sum(per[d][2] for d in recents)
    taux = (100.0 * sum(per[d][0] for d in recents) / vol) if vol else 0

    def _pct(x):
        return round(x, 3)

    g: List[List] = [
        [f"🔥  SYNTHÈSE BURNS — {jours[0]} → {jours[-1]}", "", "", ""],
        ["Mesure", "Valeur", "", ""],
        ["OMI brûlés (total)", round(total), "", ""],
        ["· dont marché (2 % des ventes)", round(marche), "", ""],
        ["· dont gems (7 % des conversions)", round(gems), "", ""],
        ["Part de l'offre en circulation", _pct(100.0 * total / OMI_CIRCULATING)
         if OMI_CIRCULATING else "", "%", ""],
        ["Valeur détruite (cours du jour)", round(total * cours) if cours
         else "", "$", ""],
        [f"Rythme ({len(recents)} derniers jours)", round(par_jour), "OMI/jour",
         ""],
        ["Projection annuelle", round(par_an), "OMI/an", ""],
        ["Déflation annualisée", _pct(defl), "%/an", ""],
        ["Taux de burn vérifié (burns ÷ volume)", _pct(taux), "%", ""],
        [f"Record : {rec_j}", round(per[rec_j][0]), "OMI", ""],
        ["Offre en circulation (réf.)", round(OMI_CIRCULATING), "OMI", ""],
    ]
    return g


def build_whales(sh):
    """3 classements cote a cote (A-J | L-U | W-AF), top WHALES_TOP chacun.

    Reprend la mise en page de l'ancien onglet 🐋 (titres, en-tetes, une
    colonne vide entre les blocs) mais DANS 📊 STATS. Rien a calculer ici :
    le ledger a deja tout mis dans l'onglet cache _Whales."""
    def _val(x):
        """Nombre natif si c'en est un, sinon la valeur telle quelle (locale FR
        safe : on ne renvoie JAMAIS de chaine numerique au Sheet)."""
        try:
            f = float(str(x).replace(",", ".").replace(" ", ""))
        except (TypeError, ValueError):
            return x if x not in (None, "") else ""
        return int(f) if f.is_integer() else round(f, 2)

    rows = _records(sh, WHALES_TAB)
    if not rows:
        return []
    blocs: Dict[str, list] = {}
    for r in rows:
        blocs.setdefault(str(r.get("bloc", "")), []).append(r)
    if not blocs:
        return []
    ordre = [b for b in ("Whale Accumulatrice", "Whale Valeur Floor",
                         "Whale Valeur Store") if b in blocs]
    ordre += [b for b in blocs if b not in ordre]

    n = len(WHALE_COLS)
    banniere = ["🐋 CLASSEMENT WHALES — top " + str(WHALES_TOP) +
                " (detail complet et rangs : 🟣C-PSEUDOS)"]
    titres, entetes, corps = [], [], []
    hauteur = 0
    for i, b in enumerate(ordre):
        lignes = sorted(blocs[b],
                        key=lambda r: _n(r.get("rank")) or 9e9)[:WHALES_TOP]
        blocs[b] = lignes
        hauteur = max(hauteur, len(lignes))
        if i:
            titres.append("")
            entetes.append("")
        titres += [b] + [""] * (n - 1)
        entetes += list(WHALE_COLS)
    for k in range(hauteur):
        ligne = []
        for i, b in enumerate(ordre):
            if i:
                ligne.append("")
            src = blocs[b]
            if k < len(src):
                r = src[k]
                ligne += [_n(r.get("rank")), r.get("wallet", ""),
                          r.get("pseudo", ""), _val(r.get("metric")),
                          _n(r.get("holdings")), _n(r.get("distinct")),
                          _val(r.get("value_store")), _val(r.get("value_floor")),
                          r.get("score", ""), r.get("activity", "")]
            else:
                ligne += [""] * n
        corps.append(ligne)
    return [banniere, titres, entetes] + corps


def build_universe(sh) -> List[List]:
    """🏪 UNIVERS DE MARCHÉ (demande Preda 12/07 : « renseigne-moi cette info
    des éléments qui ont un marché, avec un historique et une note »).

    Source : onglet `_MarketUniverse` (scraper/market_universe.py, 1 ligne par
    jour). L'endpoint public getElements ne renvoie PAS tout le catalogue mais
    seulement les éléments QUI ONT UN MARCHÉ."""
    rows = _records(sh, UNIVERS_TAB)
    if not rows:
        return []
    rows = sorted(rows, key=lambda r: str(r.get("date", "")), reverse=True)
    d = rows[0]
    g: List[List] = [
        [f"🏪  UNIVERS DE MARCHÉ — {d.get('date', '')}", "", "", ""],
        ["Mesure", "Valeur", "", ""],
        ["Éléments avec un marché", _n(d.get("elements")), "", ""],
        ["· collectibles", _n(d.get("collectibles")), "", ""],
        ["· couvertures de comics", _n(d.get("comics")), "", ""],
        ["Éléments qui SE VENDENT (7 j)", _n(d.get("vendus_7j")), "", ""],
        ["· part du marché réel", d.get("pct_vendus_7j", ""), "%", ""],
        ["Échangés récemment (volume > 0)", _n(d.get("avec_volume")), "", ""],
        ["Floor médian", d.get("floor_median", ""), "gems", ""],
        ["Floor moyen", d.get("floor_moyen", ""), "gems", ""],
        ["Capitalisation du marché", _n(d.get("market_cap")), "gems", ""],
        ["Prix aberrants exclus", _n(d.get("aberrants")), "", ""],
        ["Catalogue complet", _n(d.get("catalogue")), "produits", ""],
        ["Couverture du catalogue", d.get("couverture_pct", ""), "%", ""],
        ["", "", "", ""],
        ["Historique (jour après jour)", "Éléments", "Se vendent", "%"],
    ]
    # Historique : c'est le SUIVI de la part reellement echangee qui compte
    # (demande Preda) — si elle s'effrite semaine apres semaine, le marche se
    # vide. UNIVERS_DAYS (defaut 8) permet de comparer d'une semaine a l'autre.
    for r in rows[:UNIVERS_DAYS]:
        g.append([str(r.get("date", "")), _n(r.get("elements")),
                  _n(r.get("vendus_7j")), r.get("pct_vendus_7j", "")])
    return g


def read_omi_burns(sh):
    """(total, nft, gem) : {date_pt -> OMI brules} depuis 🔥H-BURNS.
    v10 : la decompo (colonnes omi_nft / omi_gem ecrites par burns.py v6 sur
    jetonveve) remplit OMI->NFT / OMI->GEM ; les jours pas encore couverts
    par le backfill decompo restent vides."""
    def _f(x):
        try:
            return float(str(x).replace(",", ".") or 0)
        except (TypeError, ValueError):
            return 0.0
    out: Dict[str, float] = defaultdict(float)
    nft: Dict[str, float] = defaultdict(float)
    gem: Dict[str, float] = defaultdict(float)
    for r in _records(sh, BURNS_TAB):
        d = str(r.get("date", "")).strip()
        if not d:
            continue
        if str(r.get("omi_nft", "")).strip() != "":
            nft[d] += _f(r.get("omi_nft"))
        if str(r.get("omi_gem", "")).strip() != "":
            gem[d] += _f(r.get("omi_gem"))
        v = _f(r.get("omi_burned"))
        if v:
            out[d] += v
    return dict(out), dict(nft), dict(gem)


# ---------------------------------------------------------------------------
# Calculs
# ---------------------------------------------------------------------------

REVENANT_GAP_DAYS = int(os.environ.get("STATS_REVENANT_GAP", "180"))
# 👴 ANCIENS : plus deduits des REGISTRES (leur last_active est contamine par la
# fenetre — le scan deep a demarre DEDANS, l'ecart tombait a quelques jours et
# `week_anciens` restait a 0). Le LEDGER les calcule desormais sur l'archive
# complete (IMX + CC) et les depose dans cet onglet cache.
REVEIL_TAB = "_Reveils"


def read_reveils(sh) -> Dict[str, int]:
    """{date_pt -> nb de wallets revenus apres >180 j d'absence}."""
    out: Dict[str, int] = {}
    for r in _records(sh, REVEIL_TAB):
        d = str(r.get("date_pt", "")).strip()
        if d:
            out[d] = _n(r.get("anciens"))
    return out


def _days_between(d1: str, d2: str):
    try:
        return (_dt.date.fromisoformat(d2[:10])
                - _dt.date.fromisoformat(d1[:10])).days
    except (ValueError, TypeError):
        return None


def compute_daily(activity: List[Dict[str, Any]],
                  registry: Dict[str, tuple] = None,
                  reveils: Dict[str, int] = None) -> List[Dict[str, Any]]:
    """ChainActivity (date, account, compteurs) -> 1 dict par date, tri DESC.

    NOUVEAUX : deduits des registres (wallet inconnu de tous).
    ANCIENS  : NE SONT PLUS deduits des registres. Leur `last_active` est
    CONTAMINE par la fenetre (le scan deep a demarre dedans) -> l'ecart tombait
    a quelques jours et `week_anciens` restait desesperement a 0. Ils viennent
    desormais de l'onglet _Reveils, calcule par le LEDGER sur l'archive
    COMPLETE (IMX + CC) : la seule source qui connaisse l'AVANT.
    """
    registry = registry or {}
    reveils = reveils or {}
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
    for a, d in first_in_window.items():
        fs, prev = registry.get(a, ("", ""))
        # NOUVEAU = inconnu de tous les registres, OU ne CE jour-la (le
        # registre deep couvre desormais toute la fenetre : "connu" ne veut
        # plus dire "pas nouveau" — fix 11/07, les Nouveaux etaient a 0).
        if (not fs and not prev) or (fs and fs[:10] >= d):
            new_by_day[d] += 1
            continue
        # (l'ancienne heuristique par registres est REMPLACEE par _Reveils,
        #  ecrit par le ledger ; on ne garde ici que la detection des NOUVEAUX)
    out = []
    for d in sorted(per, reverse=True):
        p = per[d]
        out.append({"date": d, "mint": p["mint"], "market": p["market"],
                    "burn": p["burn"],
                    "tx": p["mint"] + p["market"] + p["burn"],
                    "uniques": len(p["accounts"]),
                    "accounts": p["accounts"],
                    "new": new_by_day.get(d, 0),
                    "old": _n(reveils.get(d, 0))})
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


def _week_bounds(daily: List[Dict[str, Any]]):
    """Bornes CALENDAIRES de la derniere semaine complete jeudi->mercredi
    (choix Preda 11/07 : fenetre fixe, comparable de semaine en semaine)."""
    if not daily:
        return "", ""
    last = _dt.date.fromisoformat(daily[0]["date"])
    # dernier MERCREDI (weekday 2) <= dernier jour termine
    end = last - _dt.timedelta(days=(last.weekday() - 2) % 7)
    start = end - _dt.timedelta(days=6)          # le jeudi precedent
    return start.isoformat(), end.isoformat()


def _week_dates(daily: List[Dict[str, Any]]) -> List[str]:
    s, e = _week_bounds(daily)
    return [d["date"] for d in daily if s <= d["date"] <= e]


def compute_week(daily, revenue, omi=None, listing=None,
                 airdrop=None) -> Dict[str, Any]:
    days = set(_week_dates(daily))
    rows = [d for d in daily if d["date"] in days]
    accounts = set()
    for d in rows:
        accounts |= d["accounts"]
    omi = omi or {}
    listing = listing or {}
    airdrop = airdrop or {}
    li = [listing.get(d["date"]) for d in rows]
    li = [x for x in li if x]
    wb_start, wb_end = _week_bounds(daily)
    return {
        "airdrop": sum(airdrop.get(d["date"], 0) for d in rows),
        "listings": sum(x[0] for x in li),
        "listers": sum(x[1] for x in li),
        "start": wb_start,
        "end": wb_end,
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

def build_table_grid(daily, revenue, week, omi, listing, airdrop, drops,
                     now_utc: str, omi_nft=None, omi_gem=None,
                     market_rev=None, omi_usd=None, gems=None,
                     rates=None) -> List[List]:
    """Grille A1:R.. : titre, bande KPI 7 jours, tableau quotidien groupe.
    Les mints d'airdrop sortent de la colonne Mint vers Airdrop (le Global
    reste complet — separer sans jeter, choix Preda)."""
    omi_nft = omi_nft or {}
    omi_gem = omi_gem or {}
    market_rev = market_rev or {}
    omi_usd = omi_usd or {}
    gems = gems or {}
    rates = rates or {}
    g: List[List] = []
    # Le bandeau noir (titre + sous-titre) est SUPPRIME (demande Preda 13/07) :
    # les 13 premieres lignes sont a lui. La grille commence donc au bandeau de
    # la semaine, et sera ecrite en A{START_ROW}.
    g.append([f"▼  SEMAINE DU JEUDI {week['start']} AU MERCREDI "
              f"{week['end']}"])
    g.append(["Revenue drop", "Transactions", "Mints", "Airdrops", "Market",
              "Burns", "Actifs uniques", "Nouveaux", "Anciens", "Qté listée",
              "Comptes listeurs", "OMI brûlés"])
    g.append([week["revenue"], week["tx"],
              max(0, week["mint"] - week["airdrop"]), week["airdrop"],
              week["market"], week["burn"], week["uniques"], week["new"],
              week["old"], week["listings"], week["listers"],
              week["omi"]])
    g.append([])
    g.append(["", "", "TRANSACTION", "", "", "", "", "ACTIF", "", "",
              "LISTING", "", "REVENUE", "", "", "OMI BURN", "", "", "ACHAT", ""])
    g.append(["Date", "Drop", "Global", "Mint", "Airdrop", "Market", "Burn",
              "Unique", "Nouveaux", "Anciens", "Quantité", "Comptes",
              "Total", "Drop", "Market",
              "Global $", "OMI→NFT", "OMI→GEM", "Cours OMI $", "Gems $"])
    for d in daily:
        drop = round(revenue.get(d["date"], 0))
        li = listing.get(d["date"])
        air = airdrop.get(d["date"], 0)
        mkt = market_rev.get(d["date"])
        g.append([d["date"], drop_label(drops.get(d["date"])),
                  d["tx"], max(0, d["mint"] - air), air,
                  d["market"], d["burn"],
                  d["uniques"], d["new"], d["old"],
                  li[0] if li else "", li[1] if li else "",
                  drop + round(mkt) if mkt else drop,     # Total = Drop + Market
                  drop,
                  round(mkt) if mkt else "",              # ventes StackR reelles
                  round(omi_usd[d["date"]]) if d["date"] in omi_usd else "",
                  round(omi_nft[d["date"]]) if d["date"] in omi_nft else "",
                  round(omi_gem[d["date"]]) if d["date"] in omi_gem else "",
                  rates.get(d["date"]) or "",          # le cours, pour VERIFIER
                  round(gems[d["date"]]) if d["date"] in gems else ""])
    return g


def build_modules_grid(sante_rows, wsize=None) -> List[List]:
    """Zone de droite (colonnes T+), alignee sur la ligne 8 — v14 (demande
    Preda 12/07) : 💰 TAILLE DES PORTEFEUILLES EN HAUT (3 blocs cote a cote),
    puis 🩺 SANTÉ DES SOURCES en dessous. Les notes & legendes descendent sous
    le tableau annuel (colonne A, NOTES_ROW)."""
    g: List[List] = []
    if wsize:
        g += [list(r) for r in wsize]
        g.append([""])
    g += [list(r) for r in sante_rows]
    return g


def build_notes_grid() -> List[List]:
    """ℹ️ NOTES & LÉGENDES — sous le tableau 📅 PAR ANNÉE (v14)."""
    g: List[List] = []
    g.append(["ℹ️  NOTES & LÉGENDES", ""])
    g.append(["• Anciens = Désinscrits/Fantômes réveillés : wallet actif ce "
              "jour dont la transaction précédente remonte à plus de 180 j "
              "(last_active des registres deep + IMX).", ""])
    g.append(["• Nouveaux = wallet inconnu de tous les registres. Précision "
              "définitive quand le scan CollectChain sera terminé.", ""])
    g.append(["• Transactions Global = mints + ventes marché + burns (lister "
              "n'est PAS une transaction — groupe LISTING à part).", ""])
    g.append(["• Airdrop = (jour, item) avec ≥ 2 000 mints ET ≥ 90 % de "
              "minters uniques (~1/wallet) — séparé de Mint, compté dans "
              "Global (jamais jeté).", ""])
    g.append(["• LISTING : Quantité = nouveaux dépôts escrow du jour · "
              "Comptes = comptes uniques ayant listé au moins un item ce "
              "jour.", ""])
    g.append(["• Drop = série(s) sortie(s) ce jour (catalogues, jour "
              "pacifique) — plusieurs le même jour : « 2x comics + "
              "1 collectible » · vevecomics = comics du MERCREDI (parutions "
              "silencieuses de la page vevecomics, calées sur la sortie "
              "physique) · par Mois : drops on-chain (+vevecomics à part).", ""])
    g.append(["• Semaine du bandeau = dernière semaine COMPLÈTE du jeudi au "
              "mercredi (fenêtre calendaire fixe).", ""])
    g.append(["• Revenue drop = prix RÉELS payés (fiat + gems, flux VeVe "
              "public) les jours couverts ; sinon estimation mints × prix "
              "store. Revenue market = ventes VeVe (gems) + ventes StackR — "
              "plus de borne basse depuis le flux public · Total = Drop + "
              "Market.", ""])
    g.append(["• OMI burn Global = 🔥H-BURNS converti en $ (cours OMI du jour, "
              "dernier cours connu si absent) · OMI→NFT = 2 % du prix de "
              "chaque vente StackR (en OMI) · OMI→GEM = conversions (100 % "
              "brûlé, en OMI) ; vide tant que le backfill décompo n'a pas "
              "couvert le jour.", ""])
    g.append(["• vvbd = comics du MERCREDI (parutions silencieuses de la page "
              "vevecomics, calées sur la sortie physique) — dissociés des "
              "drops classiques.", ""])
    g.append(["🧭 ACTIVITÉ (🟣C-PSEUDOS, 🎯) : Actif ≤7 j · Engagé ≤30 j · "
              "Somnolant ≤90 j · Inactif ≤180 j · Désinscrit ≤365 j · "
              "Fantôme au-delà (dernière transaction).", ""])
    g.append(["💎 PROFIL (retention = détenu ÷ acquis) : Diamond-Hands ≥95% · "
              "Serious ≥75% · Collector ≥50% · Trader ≥30% · Flipper ≥15% · "
              "Seasoned ≥5% · Aggressive <5% (+1 cran flipper si revente "
              "médiane <7 j).", ""])
    g.append(["🎯 AIRDROP-ONLY (🟣C-PSEUDOS) : wallet dont TOUTE l'activité "
              "est la réception d'airdrops (aucun achat/vente/burn) — son "
              "statut Actif est artificiel.", ""])
    g.append(["🔄 CHURN % = part des wallets actifs de la période précédente "
              "(mois ou année) sans AUCUNE transaction sur la période en "
              "cours · Rétention % = 100 − churn (actifs qui reviennent) — "
              "les deux vivent dans les blocs 📈 PULSE.", ""])
    g.append(["💤 ÉLÉMENTS QUI SE VENDENT : sur ~6 000 éléments ayant un "
              "floor affiché, seuls ~1 700 (≈ 29 %) ont une VRAIE vente sur "
              "7 jours. Les deux tiers du « marché » sont des vitrines sans "
              "acheteur : un floor y est un prix DEMANDÉ que personne ne paie. "
              "C'est le chiffre à surveiller — s'il s'effrite semaine après "
              "semaine, le marché se vide (indicateur bien plus honnête que "
              "le nombre de drops ou la capitalisation affichée).", ""])
    g.append(["🏪 UNIVERS DE MARCHÉ : les 6 011 « éléments » du marché ne "
              "sont PAS tout le catalogue (18 681 produits). VeVe/StackR "
              "n'exposent que les éléments QUI ONT UN MARCHÉ — collectibles "
              "ET couvertures de comics mélangés. Les items jamais listés "
              "n'y figurent pas… et ne peuvent de toute façon pas être "
              "achetés : c'est donc le bon périmètre pour les alertes de "
              "floor. Le bloc suit ce nombre jour après jour (un élément qui "
              "entre = un item qui devient échangeable).", ""])
    g.append(["🔥 BURNS : deux flux distincts qui s'ADDITIONNENT — marché "
              "(2 % de chaque vente StackR, brûlés depuis 0x821c) et gems "
              "(7 % de chaque conversion OMI→gems, depuis 19/11/2025). La "
              "valeur en $ est une valeur de REMPLACEMENT (cours du jour "
              "appliqué à tout l'historique), pas la valeur au jour du burn.",
              ""])
    g.append(["🏢 WALLETS SYSTÈME : les livraisons VeVe (drops/store envoyés "
              "depuis les wallets officiels) ne sont PLUS comptées comme des "
              "ventes de marché — le wallet receveur reste actif, mais le "
              "mouvement sort des colonnes Market/Acheteurs/Vendeurs.", ""])
    g.append(["📅 PAR ANNÉE : les compteurs sont la SOMME des mois, mais les "
              "wallets (Unique, Acheteurs, Vendeurs, Minters) sont des "
              "UNIQUES sur l'année — ils sont donc INFÉRIEURS à la somme des "
              "mois (un même wallet actif 12 mois ne compte qu'une fois).", ""])
    g.append(["💱 COURS OMI $ : le cours du jour, affiché POUR QUE TU PUISSES "
              "REFAIRE LE CALCUL À LA MAIN — Gems $ = (OMI→GEM ÷ 0,07) × ce "
              "cours, et Global $ = OMI brûlés × ce cours. Source : gate.io "
              "(CryptoCompare en secours). ⚠️ Sur le MOIS et l'ANNÉE, c'est la "
              "MOYENNE des cours quotidiens : elle situe, elle ne sert pas à "
              "multiplier — le total de la période est la SOMME des jours, "
              "chacun valorisé à SON cours.", ""])
    g.append(["💎 GEMS ACHETÉS ($) : déduit du burn, sans aucune collecte "
              "nouvelle. Le contrat OmiToGems brûle 7 % de chaque conversion "
              "— c'est la colonne OMI→GEM. Donc OMI dépensés = OMI→GEM / 0,07, "
              "convertis au cours du jour ; et comme 1 gem = 1 $, ce montant "
              "EST le nombre de gems achetés. À SURVEILLER : un pic la VEILLE "
              "d'un drop = anticipation des acheteurs. Vide avant le "
              "19/11/2025 (la conversion OMI→gems n'existait pas).", ""])
    g.append(["👴 OG 21-22 : wallets dont la 1ʳᵉ activité (toutes ères "
              "confondues) est ANTÉRIEURE à 2023, comptés parmi les actifs "
              "UNIQUES du mois. La colonne OG % dit quelle part du marché "
              "vivant est tenue par les anciens. L'ancienneté remonte "
              "désormais à l'ère GOCHAIN (1ᵉʳ wallet : mai 2019) — les "
              "adresses sont identiques sur GoChain, IMX et CollectChain. "
              "Régler OG_CUTOFF (défaut \"2023\") : \"2021\" ne garderait "
              "que les vrais pionniers d'avant la hype.", ""])
    g.append(["🔁 ENGAGEMENT (part des semaines actives depuis la 1ʳᵉ tx) : "
              "Fidèle ≥50 % · Régulier ≥25 % · Occasionnel ≥10 % · "
              "Sporadique <10 % · Unique = 1 seule semaine.", ""])
    g.append(["🐋 CLASSEMENT WHALES (bas de page) : 3 tris du même monde — "
              "exemplaires détenus, valeur au floor, valeur au prix store. "
              "Le détail wallet par wallet (rangs, score, activité, "
              "engagement) est dans 🟣C-PSEUDOS.", ""])
    g.append(["📅 REVENUE du tableau PAR MOIS : Drop = mints du mois "
              "(airdrops déduits) × prix store ACTUEL — c'est une valeur de "
              "REMPLACEMENT, pas le prix réellement payé à l'époque (même "
              "convention que les burns en $). VIDE avant 2026-01 : l'archive "
              "IMX ne porte que le token_id, jamais l'uuid de l'item, donc "
              "aucun prix n'est rattachable. Le tableau QUOTIDIEN, lui, "
              "affiche le revenue RÉEL (flux VeVe) quand il est disponible.",
              ""])
    g.append(["• Page recalculée chaque nuit par le daily · 📅 Pulse mensuel "
              "et 🐋 classement recalculés par le workflow ledger "
              "(hebdomadaire).", ""])
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


# ═══ AGRÉGAT CORNÉRISATION + FICHE 🦊 MENUS LIÉS (16/07) ═══
REL_ANALYTICS = ("https://github.com/fanablefrance/jetonveve/releases/download/"
                 "analytics-derived")
REL_CATALOGUE = ("https://github.com/fanablefrance/jetonveve/releases/download/"
                 "catalogue")
FICHE_INDEX_TAB = "_FicheIndex"
FICHE_MENU_TAB = "_FicheMenu"
GHOST_COL, GHOST_ROW0 = "AI", 48       # bloc agrégat, sous burns/univers (colonne AI)
_RAR = {"COMMON": "Common", "UNCOMMON": "Uncommon", "RARE": "Rare",
        "ULTRA_RARE": "Ultra Rare", "SECRET_RARE": "Secret Rare",
        "ARTIST_PROOF": "Artist Proof", "FE": "FE", "FA": "FA"}
_ACT_ORD = ["Actif", "Engage", "Somnolant", "Inactif", "Desinscrit",
            "Fantome", "Non classe"]
_ACT_LBL = {"Actif": "Actif ≤7j", "Engage": "Engagé ≤30j",
            "Somnolant": "Somnolant ≤90j", "Inactif": "Inactif ≤180j",
            "Desinscrit": "Désinscrit ≤365j", "Fantome": "Fantôme >365j",
            "Non classe": "Non classé"}


def _dl(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "veve-stats/1.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception:
            if i + 1 >= tries:
                raise
            time.sleep(2 * (i + 1))


def _rows_url(url):
    data = _dl(url)
    if url.endswith(".gz"):
        data = gzip.decompress(data)
    return list(csv.reader(io.StringIO(data.decode("utf-8"))))


def _retry429(fn, *a, **kw):
    """Rejoue un appel gspread si Google renvoie 429 (quota d'ecritures/min)."""
    import gspread
    for i in range(5):
        try:
            return fn(*a, **kw)
        except gspread.exceptions.APIError as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code == 429 and i < 4:
                time.sleep(15 * (i + 1))
                continue
            raise


def _gi(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def _gsp(n):
    return f"{n:,}".replace(",", " ")


def build_fiche_index(cat_rows):
    """catalogue (data, sans en-tete) -> [type, item, rarete, uuid, key] unique.
    Comic : item=serie, rarete=rarete. Collectible : item=nom (desambigue par
    serie si homonyme), pas de rarete. Dedup dur -> chaque cover selectionnable."""
    coll = {}
    for r in cat_rows:
        if len(r) >= 7 and r[1] == "Collectible":
            coll[r[2]] = coll.get(r[2], 0) + 1
    out, seen = [], {}
    for r in cat_rows:
        if len(r) < 7:
            continue
        uuid, kind, name, rar, series = r[0], r[1], r[2], r[4], r[6]
        if kind == "Comic":
            typ, item, rr = "Comic", series, _RAR.get(rar, (rar or "").title())
        elif kind == "Collectible":
            typ, rr = "Collectible", ""
            item = name if coll.get(name, 0) <= 1 else f"{name} ({series})"
        else:
            continue
        key = f"{typ}|{item}|{rr}" if typ == "Comic" else f"{typ}|{item}"
        if key in seen:
            seen[key] += 1
            item = f"{item} #{seen[key]}"
            key = f"{typ}|{item}|{rr}" if typ == "Comic" else f"{typ}|{item}"
        else:
            seen[key] = 1
        out.append([typ, item, rr, uuid, key])
    return out


def _write_fiche_helpers(sh, fiche_row):
    """Ecrit _FicheIndex (catalogue) + _FicheMenu (formules des menus lies).
    Les deux sont CACHES. A poser AVANT la fiche (ses validations les visent)."""
    cat = _rows_url(f"{REL_CATALOGUE}/catalogue.csv.gz")[1:]
    idx = build_fiche_index(cat)
    wi = _open_worksheet(sh, FICHE_INDEX_TAB, cols=5)
    try:
        existing = len(wi.col_values(1))          # 1 LECTURE (quota separe)
    except Exception:
        existing = 0
    if existing != len(idx) + 1:                  # taille changee -> reecrire (1 requete)
        wi.clear()
        grid = [["type", "item", "rarete", "uuid", "key"]] + idx
        _retry429(wi.update, range_name="A1", values=grid,
                  value_input_option="RAW")
    r1 = fiche_row + 1
    st = f"'{STATS_TAB}'"
    fi = "'" + FICHE_INDEX_TAB + "'"
    item_f = f'=IFERROR(SORT(UNIQUE(FILTER({fi}!B2:B;{fi}!A2:A={st}!$B${r1})));"")'
    rar_f = (f'=IFERROR(SORT(UNIQUE(FILTER({fi}!C2:C;'
             f'({fi}!A2:A={st}!$B${r1})*({fi}!B2:B={st}!$D${r1}))));"")')
    uuid_f = (f'=IFERROR(INDEX({fi}!D2:D;MATCH('
              f'IF({st}!$B${r1}="Comic";"Comic|"&{st}!$D${r1}&"|"&{st}!$F${r1};'
              f'"Collectible|"&{st}!$D${r1});{fi}!E2:E;0));"")')
    wm = _open_worksheet(sh, FICHE_MENU_TAB, cols=6)
    wm.clear()
    _retry429(wm.update, range_name="A1",
              values=[[item_f, "", rar_f, "", uuid_f]],
              value_input_option="USER_ENTERED")
    try:
        _retry429(sh.batch_update, {"requests": [
            {"updateSheetProperties": {
                "properties": {"sheetId": w.id, "hidden": True},
                "fields": "hidden"}} for w in (wi, wm)]})
    except Exception:
        pass
    return len(idx)


def build_ghost_block(wal_rows, sup_rows, base_row):
    """Bloc compact : chiffre supply perdue + wallets/supply par profil.
    Retourne (grid, fmts_abs a1, bolds_abs rows) — colonnes AI..AL."""
    wal = {r[0]: _gi(r[1]) for r in wal_rows if r and r[0]}
    sup = {r[0]: (_gi(r[1]), _gi(r[2])) for r in sup_rows if r and r[0]}
    tw = sum(wal.values()) or 1
    ts = sum(v[0] for v in sup.values()) or 1
    gs, gh = sup.get("Fantome", (0, 0))
    ds, _ = sup.get("Desinscrit", (0, 0))
    g, fmt, bold = [], [], []

    def row(*c):
        g.append(list(c))
        return base_row + len(g) - 1        # rang absolu de la ligne ajoutee

    bold.append(row("⚰️ SUPPLY POTENTIELLEMENT PERDUE", "", "", ""))
    bold.append(row(f"{_gsp(gs)} ex", f"{100.0 * gs / ts:.1f} % circ.",
                    f"sur {_gsp(gh)} fantômes", ""))
    row(f"+ Désinscrits : {_gsp(gs + ds)} ex", f"{100.0 * (gs + ds) / ts:.1f} % (>180j)",
        "", "")
    row("", "", "", "")
    bold.append(row("WALLETS PAR PROFIL", "Wallets", "%", ""))
    a = base_row + len(g)
    for k in _ACT_ORD:
        if k in wal:
            row(_ACT_LBL[k], wal[k], round(100.0 * wal[k] / tw, 1), "")
    b = base_row + len(g) - 1
    fmt.append((f"AJ{a}:AJ{b}", "#,##0"))
    fmt.append((f"AK{a}:AK{b}", "0.0"))
    row("", "", "", "")
    bold.append(row("SUPPLY PAR PROFIL", "Exempl.", "% circ.", "Détent."))
    a = base_row + len(g)
    for k in _ACT_ORD:
        if k in sup:
            sv, hv = sup[k]
            row(_ACT_LBL[k], sv, round(100.0 * sv / ts, 1), hv)
    b = base_row + len(g) - 1
    fmt.append((f"AJ{a}:AJ{b}", "#,##0"))
    fmt.append((f"AK{a}:AK{b}", "0.0"))
    fmt.append((f"AL{a}:AL{b}", "#,##0"))
    return g, fmt, bold


def _write_ghost_block(ws, sh):
    from gspread.utils import a1_range_to_grid_range as _gr
    wal = _rows_url(f"{REL_ANALYTICS}/wallets_par_profil.csv")[1:]
    sup = _rows_url(f"{REL_ANALYTICS}/supply_par_profil.csv")[1:]
    grid, fmt, bold = build_ghost_block(wal, sup, GHOST_ROW0)
    ws.update(range_name=f"{GHOST_COL}{GHOST_ROW0}", values=grid,
              value_input_option="RAW")
    reqs = []
    RED = {"backgroundColor": {"red": 0.82, "green": 0.18, "blue": 0.18},
           "textFormat": {"bold": True,
                          "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}
    reqs.append({"repeatCell": {"range": _gr(f"AI{GHOST_ROW0}:AL{GHOST_ROW0}", ws.id),
        "cell": {"userEnteredFormat": RED},
        "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
    for r in bold:
        reqs.append({"repeatCell": {"range": _gr(f"AI{r}:AL{r}", ws.id),
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat.bold"}})
    for a1, nf in fmt:
        reqs.append({"repeatCell": {"range": _gr(a1, ws.id),
            "cell": {"userEnteredFormat": {"numberFormat":
                     {"type": "NUMBER", "pattern": nf}}},
            "fields": "userEnteredFormat.numberFormat"}})
    try:
        _retry429(sh.batch_update, {"requests": reqs})
    except Exception as e:
        print(f"ghost block format warning: {e}", flush=True)
    return len(grid)


CIMET_TAB = "_Cimetieres"


def _gf(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def build_cimetieres(corner_rows, name_map):
    """corner_items.csv PROD (uuid,category,circ,holders,burned,stock,ghost,
    ghost_wallets,pct) + name_map -> [name, type, circ, ghost, pct] (ghost>0)."""
    out = []
    for r in corner_rows:
        if len(r) < 9:
            continue
        gs = _gi(r[6])
        if gs <= 0:
            continue
        typ = "Comic" if r[1] == "comic" else "Collectible"
        out.append([name_map.get(r[0], r[0]), typ, _gi(r[2]), gs, _gf(r[8])])
    return out


def _write_cimetieres(sh):
    ci = _rows_url(f"{REL_ANALYTICS}/corner_items.csv")[1:]
    cf = _rows_url(f"{REL_ANALYTICS}/corner_full.csv.gz")
    name_map = {r[0]: r[1] for r in cf[1:] if len(r) > 1}
    rows = build_cimetieres(ci, name_map)
    rows.sort(key=lambda x: x[3], reverse=True)
    w = _open_worksheet(sh, CIMET_TAB, cols=5)
    w.clear()
    grid = [["name", "type", "circulating", "ghost", "pct"]] + rows
    _retry429(w.update, range_name="A1", values=grid, value_input_option="RAW")
    try:
        _retry429(sh.batch_update, {"requests": [{"updateSheetProperties": {
            "properties": {"sheetId": w.id, "hidden": True},
            "fields": "hidden"}}]})
    except Exception:
        pass
    return len(rows)


def _write_tops(ws, sh, tr):
    """TOP 20 cimetieres (par supply fantome) + TOP 20 cornerises (par %, circ>=500)
    cote a cote sous les whales, avec un menu Type qui trie en direct (QUERY).
    Retourne la ligne ou poser la fiche (dessous)."""
    from gspread.utils import a1_range_to_grid_range as _gr
    _write_cimetieres(sh)
    if ws.row_count < tr + 80:
        try:
            ws.resize(rows=tr + 80)
        except Exception:
            pass
    tog = f"$B${tr}"

    def _q(order, cond):
        return (f"=IFERROR(QUERY('{CIMET_TAB}'!$A$2:$E;"
                f'"select A,B,C,D,E where {cond} "&'
                f"IF({tog}=\"Tous\";\"\";\"and B='\"&{tog}&\"' \")&"
                f'"order by {order} desc limit 20";0);"")')
    _retry429(ws.batch_update, [
        {"range": f"A{tr}", "values": [["Trier ▼", "Tous"]]},
        {"range": f"A{tr + 2}", "values": [[
            "TOP 20 — PLUS GROS CIMETIÈRES (supply fantôme)", "", "", "", "", "",
            "TOP 20 — PLUS CORNÉRISÉS PAR LES FANTÔMES (circ ≥ 500)"]]},
        {"range": f"A{tr + 3}", "values": [[
            "Item", "Type", "Circulant", "Fantôme", "% fant.", "",
            "Item", "Type", "Circulant", "Fantôme", "% fant."]]},
    ], value_input_option="RAW")
    _retry429(ws.batch_update, [
        {"range": f"A{tr + 4}", "values": [[_q("D", "D>0")]]},
        {"range": f"G{tr + 4}", "values": [[_q("E", "C>=500")]]},
    ], value_input_option="USER_ENTERED")
    reqs = [{"setDataValidation": {"range": _gr(f"B{tr}", ws.id),
        "rule": {"condition": {"type": "ONE_OF_LIST", "values": [
            {"userEnteredValue": v} for v in ("Tous", "Collectible", "Comic")]},
            "showCustomUi": True, "strict": False}}},
        {"repeatCell": {"range": _gr(f"B{tr}", ws.id),
            "cell": {"userEnteredFormat": {"backgroundColor":
                     {"red": 1.0, "green": 0.90, "blue": 0.46}}},
            "fields": "userEnteredFormat.backgroundColor"}}]
    reqs.append({"repeatCell": {"range": _gr(f"A{tr + 2}:K{tr + 2}", ws.id),
        "cell": {"userEnteredFormat": {
            "backgroundColor": {"red": 0.482, "green": 0.173, "blue": 0.749},
            "textFormat": {"bold": True,
                           "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}},
        "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
    for a1 in (f"A{tr}", f"A{tr + 3}:K{tr + 3}"):
        reqs.append({"repeatCell": {"range": _gr(a1, ws.id),
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat.bold"}})
    for a1, nf in ((f"C{tr + 4}:D{tr + 23}", "#,##0"), (f"E{tr + 4}:E{tr + 23}", "0.0"),
                   (f"I{tr + 4}:J{tr + 23}", "#,##0"), (f"K{tr + 4}:K{tr + 23}", "0.0")):
        reqs.append({"repeatCell": {"range": _gr(a1, ws.id),
            "cell": {"userEnteredFormat": {"numberFormat":
                     {"type": "NUMBER", "pattern": nf}}},
            "fields": "userEnteredFormat.numberFormat"}})
    try:
        _retry429(sh.batch_update, {"requests": reqs})
    except Exception as e:
        print(f"tops format warning: {e}", flush=True)
    return tr + 26


def write_stats(sh) -> Dict[str, Any]:
    activity = _records(sh, ACTIVITY_TAB)
    items = _records(sh, ITEMS_TAB)
    prices = read_store_prices(sh)
    active = {str(r.get("account", "")).strip().lower()
              for r in activity if str(r.get("account", "")).strip()}
    known = load_known_first_seen(active) if active else {}
    daily = compute_daily(activity, known, read_reveils(sh))
    if not daily:
        raise RuntimeError("ChainActivity vide — page 📊 STATS non touchee.")
    revenue = compute_revenue(items, prices)
    omi, omi_nft, omi_gem = read_omi_burns(sh)
    listing = read_listing_daily(sh)
    airdrop = detect_airdrop_daily(items)
    market_rev, mkt_rates = read_market_revenue(sh)
    # v15 : le flux VeVe PUBLIC (veve_tx) PRIME sur les estimations —
    # drop reel (fiat + gems) et marche secondaire COMPLET (VeVe + StackR).
    v_drop, v_market = read_veve_revenue(sh)
    n_reel = len(v_drop)
    revenue.update(v_drop)
    market_rev.update(v_market)
    week = compute_week(daily, revenue, omi, listing, airdrop)
    drops = load_drop_names(sh)
    omi_usd_daily = omi_to_usd(omi, mkt_rates)

    now_utc = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    gems_daily = gems_achetes(omi_gem, mkt_rates)
    table = build_table_grid(daily, revenue, week, omi, listing, airdrop,
                             drops, now_utc, omi_nft, omi_gem, market_rev,
                             omi_usd_daily, gems_daily, mkt_rates)
    try:
        sante_rows = _health.build_rows(sh)
    except Exception as e:
        print(f"health warning: {e}", flush=True)
        sante_rows = [["🩺 SANTE DES SOURCES", "", "", ""],
                      ["indisponible", "", "", ""]] + [[""]] * 12
    # v14 (demande Preda 12/07) : 💰 TAILLES en haut a droite, 🩺 SANTÉ en
    # dessous, ℹ️ NOTES sous le tableau annuel.
    wsize = build_wallet_size_section(_records(sh, "_WalletSize"))
    modules = build_modules_grid(sante_rows, wsize)
    sante_off = (len(wsize) + 1) if wsize else 0      # lignes avant la santé
    notes = build_notes_grid()

    ws = _open_worksheet(sh, STATS_TAB, cols=44)   # AI..AL = 2e colonne modules
    # ⚠️ PAS de ws.clear() : il effacerait les 13 lignes de Preda.
    # On ne nettoie QUE la zone qui nous appartient.
    # 📅 PULSE : lecture ROBUSTE (retries) AVANT le batch_clear. Un hoquet de
    # l'API Google renvoyait [] -> build_pulse vide -> les blocs mois/annee
    # etaient EFFACES puis PAS repeints (incident 16/07).
    monthly_g, vvf_g, annual_g, vvfy_g = build_pulse_section(
        _records_pulse(sh), omi, omi_nft, omi_gem, market_rev, drops, mkt_rates)
    # GARDE-FOU "on ne detruit pas ce qu'on ne peut pas remplacer" : si le pulse
    # est introuvable (lecture vide meme apres retries), le batch_clear EPARGNE
    # les rangs mois+annee (PULSE_ROW..NOTES_ROW-1) -> ils restent affiches.
    if monthly_g:
        ws.batch_clear([f"A{START_ROW}:AZ{ws.row_count}"])
    else:
        ws.batch_clear([f"A{START_ROW}:AZ{PULSE_ROW - 1}",
                        f"A{NOTES_ROW}:AZ{ws.row_count}"])
        print("⚠️ pulse _MonthlyPulse illisible — blocs 📅 PAR MOIS/ANNÉE "
              "PRESERVES (non effaces).", flush=True)
    ws.update(range_name=f"A{START_ROW}", values=table,
              value_input_option="RAW")
    ws.update(range_name=f"{MODULE_COL}{GROUP_ROW}", values=modules,
              value_input_option="RAW")
    ws.update(range_name=f"A{NOTES_ROW}", values=notes,
              value_input_option="RAW")
    # ---- sections v14 : alignees par periode ----
    VIOLET = {"backgroundColor": {"red": 0.482, "green": 0.173, "blue": 0.749},
              "textFormat": {"bold": True, "foregroundColor":
                             {"red": 1, "green": 1, "blue": 1}}}
    BOLD = {"textFormat": {"bold": True}}
    if monthly_g:
        ws.update(range_name=f"A{PULSE_ROW}", values=monthly_g,
                  value_input_option="RAW")
        ws.update(range_name=f"{MODULE_COL}{PULSE_ROW}", values=vvf_g,
                  value_input_option="RAW")
        ws.update(range_name=f"A{YEAR_ROW}", values=annual_g,
                  value_input_option="RAW")
        ws.update(range_name=f"{MODULE_COL}{YEAR_ROW}", values=vvfy_g,
                  value_input_option="RAW")
        try:
            for row in (PULSE_ROW, YEAR_ROW):
                ws.format(f"A{row}:S{row}", VIOLET)
                ws.format(f"V{row}:AG{row}", VIOLET)
                ws.format(f"{row + 2}:{row + 2}", BOLD)
        except Exception:
            pass
    # 🔥 SYNTHÈSE BURNS (colonne T, sous la sante)
    burns_g = build_burns_summary(sh, mkt_rates)
    if burns_g:
        ws.update(range_name=f"{MODULE_COL2}{BURNS_ROW}", values=burns_g,
                  value_input_option="RAW")
        try:
            ws.format(f"AI{BURNS_ROW}:AL{BURNS_ROW}", VIOLET)
            ws.format(f"AI{BURNS_ROW + 1}:AL{BURNS_ROW + 1}", BOLD)
        except Exception:
            pass

    # 🏪 UNIVERS DE MARCHÉ (colonne T, sous les burns)
    univ_g = build_universe(sh)
    if univ_g:
        ws.update(range_name=f"{MODULE_COL2}{UNIVERS_ROW}", values=univ_g,
                  value_input_option="RAW")
        try:
            ws.format(f"AI{UNIVERS_ROW}:AL{UNIVERS_ROW}", VIOLET)
            ws.format(f"AI{UNIVERS_ROW + 1}:AL{UNIVERS_ROW + 1}", BOLD)
            ws.format(f"AI{UNIVERS_ROW + 12}:AL{UNIVERS_ROW + 12}", BOLD)
        except Exception:
            pass

    # 🐋 CLASSEMENT WHALES (sous les notes, pleine largeur A-AF)
    whales_g = build_whales(sh)
    if whales_g:
        ws.update(range_name=f"A{WHALES_ROW}", values=whales_g,
                  value_input_option="RAW")
        try:
            ws.format(f"A{WHALES_ROW}:AF{WHALES_ROW}", VIOLET)
            ws.format(f"{WHALES_ROW + 1}:{WHALES_ROW + 2}", BOLD)
        except Exception:
            pass

    # ⚰️ TOP 20 CIMETIÈRES + CORNÉRISÉS (sous les whales) + menu de tri Type
    fiche_row = FICHE_ROW
    try:
        fiche_row = _write_tops(ws, sh, WHALES_ROW + (len(whales_g) or 24) + 2)
    except Exception as e:
        print(f"tops warning: {e}", flush=True)

    # bannieres des modules de droite (💰 en T8, 🩺 juste en dessous)
    try:
        if wsize:
            ws.format(f"V{GROUP_ROW}:AF{GROUP_ROW}", VIOLET)
            ws.format(f"V{GROUP_ROW + 1}:AF{GROUP_ROW + 1}", BOLD)
        ws.format(f"A{NOTES_ROW}:S{NOTES_ROW}", VIOLET)
    except Exception:
        pass

    # ── HABILLAGE (13/07) : en Python, PAR NOM DE COLONNE.
    # L'Apps Script stats_format.gs formatait par POSITION ('A10:R46', pulse en
    # T:AC...). En inserant 💎 Gems en S et les 2 colonnes OG dans le pulse,
    # tout avait glisse : Gems $ s'affichait "15636,0%" et le NOMBRE d'OG
    # "2898,0%". -> SUPPRIMER l'Apps Script, il est devenu nuisible.
    try:
        from scraper import stats_format as _sf
        n_req = _sf.habiller(
            sh, ws, COLS_TABLE, len(daily), COLS_TABLE,
            max(0, len(monthly_g) - 3), max(0, len(annual_g) - 3), COLS_VVF,
            WHALE_COLS, max(0, len(whales_g) - 3), NOTES_ROW, len(notes),
            {"mois": PULSE_ROW, "annee": YEAR_ROW, "whales": WHALES_ROW,
             "depart": START_ROW, "entete": HEADER_ROW},
            bandeaux=[
                (GROUP_ROW, 22, 32, "vert"),            # 💰 V..AF
                (GROUP_ROW + sante_off, 22, 25, "vert"),  # 🩺 V..Y
                (BURNS_ROW, 35, 38, "orange"),          # 🔥 AI..AL
                (UNIVERS_ROW, 35, 38, "orange"),        # 🏪 AI..AL
            ])
        print(f"Habillage : {n_req} requetes (formats deduits des EN-TETES).",
              flush=True)
    except Exception as e:
        print(f"habillage warning: {e}", flush=True)

    # 🦊 FICHE PAR ITEM (module interactif VeveFox) — menu deroulant + tables +
    # heatmaps, tout en FORMULES qui lisent 🎯A-CORNERISATION (ecrit apres
    # l'habillage : ses formats lui sont propres, l'habillage ne le touche pas).
    try:
        try:
            _write_fiche_helpers(sh, fiche_row)
        except Exception as e:
            print(f"fiche index warning: {e}", flush=True)
        _fiche.write(sh, ws, fiche_row)
    except Exception as e:
        print(f"fiche warning: {e}", flush=True)
    try:
        _write_ghost_block(ws, sh)
    except Exception as e:
        print(f"ghost block warning: {e}", flush=True)

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

    # MASQUER les onglets de SERVICE (demande Preda 15/07) — pas supprimer :
    #   * 🤖LOGS reste LU par 🩺 SANTE (health.py) ;
    #   * 🔗A-RACCORD reste LU par classement.py (amorce des 449 notes).
    # Un onglet MASQUE reste parfaitement lisible par l'API : on ne fait que le
    # sortir de la vue de Preda. Idempotent (masquer un onglet deja masque = rien).
    for tab in HIDE_TABS:
        try:
            w = sh.worksheet(tab)
            sh.batch_update({"requests": [{"updateSheetProperties": {
                "properties": {"sheetId": w.id, "hidden": True},
                "fields": "hidden"}}]})
        except Exception:
            pass

    return {"days": len(daily), "drop_days": len(drops),
            "week_tx": week["tx"],
            "week_revenue": week["revenue"], "week_anciens": week["old"],
            "annees": max(0, len(annual_g) - 3),
            "jours_revenue_reel": n_reel,
            "burns_synthese": len(burns_g), "gems_jours": len(gems_daily),
            "univers": len(univ_g), "whales": max(0, len(whales_g) - 3),
            "sante_row": GROUP_ROW + sante_off,
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

# FIN stats_page.py v14
