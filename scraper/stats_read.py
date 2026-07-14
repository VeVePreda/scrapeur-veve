"""📖 LECTEUR DE LA PAGE 📊 STATS — par ANCRES, jamais par plages en dur.

POURQUOI CE MODULE EXISTE (bug trouve le 14/07)
-----------------------------------------------
`digest.py` lisait la page avec une plage FIGEE : `A10:R60`. L'habillage du
13/07 a insere la zone de Preda (13 lignes) et le bandeau de la semaine : le
tableau quotidien commence maintenant en ligne **20**, plus en 10. Le digest
lisait donc la ligne « ▼ SEMAINE DU JEUDI … » comme si c'etait un JOUR, et
postait une carte pleine de zeros — sans jamais se plaindre.

LA LECON (elle vaut pour tout le pipeline) : **une plage en dur est une bombe a
retardement ; on ANCRE sur le contenu.** Ici on cherche la ligne d'en-tetes
(colonne A = « Date », « Mois » ou « Année ») et on VERIFIE que les colonnes
attendues sont bien la. Si la page a change de forme, on ne devine pas : on
refuse de rendre quoi que ce soit et on le DIT (mieux vaut pas de message
qu'un message faux).

Les trois tableaux de 📊 STATS portent les MEMES 20 colonnes (stats_page
`_period_tables`) :
  Date/Mois/Année · Drop · Global · Mint · Airdrop · Market · Burn · Unique ·
  Nouveaux · Anciens · Quantité · Comptes · Total · Drop · Market · Global $ ·
  OMI→NFT · OMI→GEM · Cours OMI $ · Gems $
(les noms « Drop » et « Market » apparaissent DEUX fois — d'ou des cles
positionnelles ici, et surtout pas un dict par en-tete.)
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

STATS_TAB = os.environ.get("STATS_TAB", "📊 STATS")

# Cles positionnelles (uniques, contrairement aux en-tetes du Sheet).
COLS = ["periode", "drop", "tx", "mint", "airdrop", "market", "burn",
        "actifs", "nouveaux", "anciens", "qte", "comptes",
        "revenue", "rev_drop", "rev_market",
        "burn_usd", "omi_nft", "omi_gem", "cours_omi", "gems_usd"]

# Colonnes temoins : si elles ne sont PAS a leur place, la page a bouge et on
# arrete tout (index 0-based -> en-tete attendu).
TEMOINS = {2: "Global", 7: "Unique", 12: "Total"}

ANCRES = {"jours": "Date", "mois": "Mois", "annees": "Année"}

# Assez large pour couvrir jours (l. 20+), mois (l. 62+) et annees (l. 129+).
PLAGE = os.environ.get("STATS_READ_RANGE", "A1:T220")


def _norm(x) -> str:
    return str(x or "").strip()


def nombre(x) -> int:
    """Un nombre du Sheet -> int (tolere « 12 345 », « 1,5 », « 45 $ », vide)."""
    s = _norm(x).replace(" ", "").replace("\xa0", "").replace(" ", "")
    s = s.replace("$", "").replace("~", "").replace(",", ".")
    if not s:
        return 0
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return 0


def _valide(entetes: List[str]) -> bool:
    for i, nom in TEMOINS.items():
        if i >= len(entetes) or _norm(entetes[i]) != nom:
            return False
    return True


def _bloc(vals: List[List], ancre: str) -> List[Dict[str, Any]]:
    """Le tableau dont la ligne d'en-tetes porte `ancre` en colonne A."""
    for i, row in enumerate(vals):
        if not row or _norm(row[0]) != ancre:
            continue
        if not _valide([_norm(c) for c in row]):
            # Ce n'est peut-etre pas la bonne ligne (une cellule « Date » dans
            # la zone de Preda, par exemple) : on continue de chercher.
            continue
        out: List[Dict[str, Any]] = []
        for r in vals[i + 1:]:
            if not r or not _norm(r[0]):
                break                      # ligne vide = fin du tableau
            cells = list(r) + [""] * (len(COLS) - len(r))
            out.append(dict(zip(COLS, cells[:len(COLS)])))
        return out
    print(f"📊 STATS : aucun tableau « {ancre} » valide dans {PLAGE} — la page "
          f"a change de forme, je ne devine RIEN.", file=sys.stderr)
    return []


def lire_valeurs(sh, tab: str = None) -> List[List]:
    ws = sh.worksheet(tab or STATS_TAB)
    try:      # valeurs BRUTES : « 12 345 » formate n'est pas un nombre
        from gspread.utils import ValueRenderOption
        return ws.get_values(
            PLAGE, value_render_option=ValueRenderOption.unformatted)
    except ImportError:                       # hors CI (tests hors-ligne)
        return ws.get_values(PLAGE)


def lire(sh, tab: str = None) -> Dict[str, List[Dict[str, Any]]]:
    """{"jours": [...], "mois": [...], "annees": [...]} — chaque liste triee du
    plus RECENT au plus ancien (c'est l'ordre d'ecriture de stats_page)."""
    try:
        vals = lire_valeurs(sh, tab)
    except Exception as e:                                  # noqa: BLE001
        print(f"lecture de 📊 STATS impossible : {e}", file=sys.stderr)
        return {k: [] for k in ANCRES}
    return {cle: _bloc(vals, ancre) for cle, ancre in ANCRES.items()}


def semaine(jours: List[Dict[str, Any]], n: int = 7) -> Optional[Dict]:
    """Le cumul des `n` derniers jours du tableau (la veille + 6, demande de
    Preda). ⚠️ Les wallets ne s'additionnent PAS honnetement (l'actif de lundi
    peut etre celui de mardi) : on somme quand meme, et la legende le dit —
    c'est deja la convention du « point de la semaine » du digest."""
    sept = [j for j in jours[:n] if _norm(j.get("periode"))]
    if not sept:
        return None
    som: Dict[str, Any] = {
        c: sum(nombre(j.get(c)) for j in sept)
        for c in COLS if c not in ("periode", "drop", "cours_omi")
    }
    som["debut"] = _norm(sept[-1]["periode"])
    som["fin"] = _norm(sept[0]["periode"])
    som["drops"] = sum(1 for j in sept if _norm(j.get("drop")))
    som["jours"] = len(sept)
    return som


# FIN stats_read.py — on ancre, on valide, et on se tait plutot que de mentir.
