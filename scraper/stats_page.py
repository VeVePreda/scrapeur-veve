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
MODULE_COL = "T"                     # colonne des modules de droite (tableau A:R)
LISTING_TAB = "_ListingDaily"        # source du groupe LISTING (chain_run)
PULSE_TAB = "_MonthlyPulse"          # source du 📅 pulse mensuel (ledger)
PULSE_ROW = 49
YEAR_ROW = 116                       # 📅 PAR ANNÉE + 📈 PULSE annuel (sous les 60 mois)
NOTES_ROW = 132                      # ℹ️ notes & legendes, sous le tableau annuel (v14)
# 60 mois par defaut : l'histoire complete 2021->2026 (pulse IMX) tient
# dans la zone mensuelle (gs v6 formate jusqu'a la ligne 120).
PULSE_MONTHS = int(os.environ.get("STATS_PULSE_MONTHS", "60"))
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


def _period_tables(recs, cat, usd, nft, gem, mkt, label, titre, titre_vvf):
    """Couple (tableau periode, pulse periode) pour un grain donne — utilise
    pour les MOIS ("YYYY-MM") et les ANNÉES ("YYYY"). Memes 18 colonnes que le
    tableau quotidien pour le tableau de gauche."""
    table: List[List] = [
        [titre],
        ["", "", "TRANSACTION", "", "", "", "", "ACTIF", "", "",
         "LISTING", "", "REVENUE", "", "", "OMI BURN", "", ""],
        [label, "Drop", "Global", "Mint", "Airdrop", "Market", "Burn",
         "Unique", "Nouveaux", "Anciens", "Quantité", "Comptes",
         "Total", "Drop", "Market", "Global $", "OMI→NFT", "OMI→GEM"],
    ]
    vvf: List[List] = [
        [titre_vvf],
        [""],
        [label, "Acheteurs uniques", "Vendeurs uniques", "Minters uniques",
         "Drops", "Acc. nette moy", "Net+", "Net−", "Rétention %", "Churn %"],
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
        table.append([p, cell,
                      tokens + trades + burns, max(0, tokens - air), air,
                      trades, burns,
                      _n(r.get("actifs")), _n(r.get("nouveaux")),
                      _n(r.get("anciens")),
                      _n(r.get("listings")), "",
                      "", "", round(mk) if mk else "",
                      round(u) if u else "",
                      round(onft) if onft else "",
                      round(ogem) if ogem else ""])
        c = r.get("churn_pct", "")
        vvf.append([p, _n(r.get("acheteurs")), _n(r.get("vendeurs")),
                    _n(r.get("minters_uniques")), nd or "",
                    r.get("acc_net_moy", ""), _n(r.get("acc_net_pos")),
                    _n(r.get("acc_net_neg")), _ret_pct(c), c])
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

    recs = sorted(pulse_records, key=lambda r: str(r.get("month", "")),
                  reverse=True)[:PULSE_MONTHS]
    monthly, vvf = _period_tables(
        recs, cat_m, usd_m, nft_m, gem_m, mkt_m, "Mois",
        "📅  PAR MOIS — mêmes colonnes que le tableau quotidien "
        "(archive on-chain, recalculé par le workflow ledger)",
        "📈  PULSE VEVEFOX — par mois (wallets UNIQUES par colonne)")

    yrecs = sorted(yearly, key=lambda r: str(r.get("month", "")), reverse=True)
    annual, vvf_y = _period_tables(
        yrecs, cat_y, usd_y, nft_y, gem_y, mkt_y, "Année",
        "📅  PAR ANNÉE — mêmes colonnes que le tableau quotidien "
        "(wallets = UNIQUES sur l'année, jamais la somme des mois)",
        "📈  PULSE VEVEFOX — par année (wallets UNIQUES par colonne)")
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
        # NOUVEAU = inconnu de tous les registres, OU ne CE jour-la (le
        # registre deep couvre desormais toute la fenetre : "connu" ne veut
        # plus dire "pas nouveau" — fix 11/07, les Nouveaux etaient a 0).
        if (not fs and not prev) or (fs and fs[:10] >= d):
            new_by_day[d] += 1
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
                     market_rev=None, omi_usd=None) -> List[List]:
    """Grille A1:R.. : titre, bande KPI 7 jours, tableau quotidien groupe.
    Les mints d'airdrop sortent de la colonne Mint vers Airdrop (le Global
    reste complet — separer sans jeter, choix Preda)."""
    omi_nft = omi_nft or {}
    omi_gem = omi_gem or {}
    market_rev = market_rev or {}
    omi_usd = omi_usd or {}
    g: List[List] = []
    g.append(["📊  STATS VEVE — ACTIVITÉ ON-CHAIN", "", "", "", "", "", "",
              "", "", "", "", "", "", "", "", "", "", "", "",
              f"maj : {now_utc}"])
    g.append(["Jours pacifiques terminés uniquement · Revenue drop = mints × "
              "prix store · Revenue market = ventes StackR réelles ($) · "
              "OMI→NFT/GEM : décompo burns (se remplit avec le backfill)"])
    g.append([])
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
              "LISTING", "", "REVENUE", "", "", "OMI BURN", "", ""])
    g.append(["Date", "Drop", "Global", "Mint", "Airdrop", "Market", "Burn",
              "Unique", "Nouveaux", "Anciens", "Quantité", "Comptes",
              "Total", "Drop", "Market",
              "Global $", "OMI→NFT", "OMI→GEM"])
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
                  round(omi_gem[d["date"]]) if d["date"] in omi_gem else ""])
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
    g.append(["• Revenue drop = mints × prix store · Revenue market = ventes "
              "RÉELLES du marché StackR (prix OMI → $ au cours du jour de "
              "collecte) ; les ventes in-app VeVe (gems) n'ont pas de source "
              "de prix → borne basse · Total = Drop + Market.", ""])
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
    g.append(["🏢 WALLETS SYSTÈME : les livraisons VeVe (drops/store envoyés "
              "depuis les wallets officiels) ne sont PLUS comptées comme des "
              "ventes de marché — le wallet receveur reste actif, mais le "
              "mouvement sort des colonnes Market/Acheteurs/Vendeurs.", ""])
    g.append(["📅 PAR ANNÉE : les compteurs sont la SOMME des mois, mais les "
              "wallets (Unique, Acheteurs, Vendeurs, Minters) sont des "
              "UNIQUES sur l'année — ils sont donc INFÉRIEURS à la somme des "
              "mois (un même wallet actif 12 mois ne compte qu'une fois).", ""])
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
    omi, omi_nft, omi_gem = read_omi_burns(sh)
    listing = read_listing_daily(sh)
    airdrop = detect_airdrop_daily(items)
    market_rev, mkt_rates = read_market_revenue(sh)
    week = compute_week(daily, revenue, omi, listing, airdrop)
    drops = load_drop_names(sh)
    omi_usd_daily = omi_to_usd(omi, mkt_rates)

    now_utc = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    table = build_table_grid(daily, revenue, week, omi, listing, airdrop,
                             drops, now_utc, omi_nft, omi_gem, market_rev,
                             omi_usd_daily)
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

    ws = _open_worksheet(sh, STATS_TAB, cols=34)
    ws.clear()
    ws.update(range_name="A1", values=table, value_input_option="RAW")
    ws.update(range_name=f"{MODULE_COL}{GROUP_ROW}", values=modules,
              value_input_option="RAW")
    ws.update(range_name=f"A{NOTES_ROW}", values=notes,
              value_input_option="RAW")
    # ---- sections v14 : alignees par periode ----
    # rangée PULSE_ROW : 📅 PAR MOIS (A-R)   | 📈 PULSE mois  (T-AC)
    # rangée YEAR_ROW  : 📅 PAR ANNÉE (A-R)  | 📈 PULSE année (T-AC)
    VIOLET = {"backgroundColor": {"red": 0.482, "green": 0.173, "blue": 0.749},
              "textFormat": {"bold": True, "foregroundColor":
                             {"red": 1, "green": 1, "blue": 1}}}
    BOLD = {"textFormat": {"bold": True}}
    monthly_g, vvf_g, annual_g, vvfy_g = build_pulse_section(
        _records(sh, PULSE_TAB), omi, omi_nft, omi_gem, market_rev, drops,
        mkt_rates)
    if monthly_g:
        ws.update(range_name=f"A{PULSE_ROW}", values=monthly_g,
                  value_input_option="RAW")
        ws.update(range_name=f"T{PULSE_ROW}", values=vvf_g,
                  value_input_option="RAW")
        ws.update(range_name=f"A{YEAR_ROW}", values=annual_g,
                  value_input_option="RAW")
        ws.update(range_name=f"T{YEAR_ROW}", values=vvfy_g,
                  value_input_option="RAW")
        try:
            for row in (PULSE_ROW, YEAR_ROW):
                ws.format(f"A{row}:R{row}", VIOLET)
                ws.format(f"T{row}:AC{row}", VIOLET)
                ws.format(f"{row + 2}:{row + 2}", BOLD)
        except Exception:
            pass
    # bannieres des modules de droite (💰 en T8, 🩺 juste en dessous)
    try:
        if wsize:
            ws.format(f"T{GROUP_ROW}:AD{GROUP_ROW}", VIOLET)
            ws.format(f"T{GROUP_ROW + 1}:AD{GROUP_ROW + 1}", BOLD)
        ws.format(f"A{NOTES_ROW}:R{NOTES_ROW}", VIOLET)
    except Exception:
        pass

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

    return {"days": len(daily), "drop_days": len(drops),
            "week_tx": week["tx"],
            "week_revenue": week["revenue"], "week_anciens": week["old"],
            "annees": max(0, len(annual_g) - 3),
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
