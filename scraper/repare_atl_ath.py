# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/repare_atl_ath.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""🔧 REPARATION DES COLONNES ATL/ATH DU CATALOGUE FROID (audit du 22/07/2026).

LE MAL, prouve sur piece
------------------------
Les onglets 🔵C-COLLECTIBLE / 🟢C-COMICS portent des atl/ath **corrompus
×100** : des decimales FR dont la virgule a saute, gelees dans les cellules.
Preuves : l'ATH exporte de ODDY vaut 888888 quand l'alerte a OBSERVE 8888,88
en direct ; 16,9 % des paires du pont (3 172 / 18 801) sont IMPOSSIBLES
(atl > ath) ; et sur les cartes Discord ca donnait « Plus-bas historique :
369,00 $ » sous un floor a 8,64 $ (369 = 3,69).

⚠️ Le pire : une paire ×100 DES DEUX COTES reste coherente (atl < ath) et
passe sous tous les garde-fous d'incoherence. On ne peut donc PAS reparer en
divisant « ce qui a l'air gros » : 1499 peut etre un vrai 1 499 $ ou un 14,99
corrompu. **La seule reparation honnete est de re-demander la verite a la
source** : le tracker fournit allTimeLowest/Highest pour chaque produit, deja
mappes par `veve_scraper._flatten_product` (cles atl/atl_date/ath/ath_date).

POURQUOI le quotidien ne s'auto-repare pas : le daily (ENRICH_MODE=new) ne
re-scrape que la FENETRE recente — les lignes existantes font l'aller-retour
lecture-formatee -> reecriture RAW sans jamais revoir le tracker. Les valeurs
corrompues sont donc immortelles sans une passe dediee.

CE QUE FAIT CE MODULE
---------------------
1. Scrape le catalogue tracker COMPLET (~790 pages de 24, pause 0,25 s —
   la meme empreinte qu'un backfill existant ; a lancer UNE fois, pas en cron).
2. Pour chaque ligne des deux onglets froids, recrit UNIQUEMENT les 4 colonnes
   atl / atl_date / ath / ath_date :
     · tracker connu   -> la valeur fraiche, EN NOMBRE (write RAW : jamais de
       chaine formatee, c'est le vecteur de la corruption d'origine) ;
     · tracker muet    -> la valeur actuelle si sa paire est coherente
       (re-normalisee en nombre), VIDEE si la paire est impossible ;
   Les autres colonnes ne sont PAS touchees.
3. Deux controles imprimes : la distribution avant/apres des paires
   incoherentes (attendu : -> 0 sur les lignes tracker), et le temoin ODDY
   (76880cbf… : ath attendu 8888,88, pas 888888).

MODE D'EMPLOI (règle du projet : on regle en simulation, jamais en public)
--------------------------------------------------------------------------
  REPARE_SIMULER=1 (defaut via le workflow) : tout calcule, RIEN n'est ecrit,
  le rapport dit exactement ce qui changerait. Relancer avec simuler=non pour
  ecrire.

Env : GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID, REPARE_SIMULER.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, List, Optional

from gspread.exceptions import APIError
from gspread.utils import rowcol_to_a1

from scraper.sheets import COLLECT_TAB, COMICS_TAB, _client
from scraper.veve_scraper import scrape_catalogue

SIMULER = os.environ.get("REPARE_SIMULER", "1").strip().lower() not in (
    "0", "non", "false")
# Meme plafond d'aberration que veve_scraper : un ATH >= 1e12 est un troll.
CAP = 1e12
COLS = ("atl", "atl_date", "ath", "ath_date")


def _dec(x) -> float:
    """Decimal FR-tolerant (« 8 888,88 » -> 8888.88), 0.0 si illisible."""
    try:
        return float(str(x).replace(" ", "").replace(" ", "")
                     .replace(" ", "").replace(",", ".") or 0)
    except (TypeError, ValueError):
        return 0.0


def _retry(desc: str, fn):
    """Rejoue une operation Sheets sur 429/503 (quota par minute)."""
    for i, d in enumerate((0, 15, 30, 45, 60, 60)):
        if d:
            print(f"  {desc} : quota Sheets, pause {d}s (essai {i}/5)...",
                  flush=True)
            time.sleep(d)
        try:
            return fn()
        except APIError as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code not in (429, 503) or i == 5:
                raise
    return fn()


def _nombre_ou_vide(v) -> Any:
    """Un prix du tracker -> nombre ecrit tel quel, ou '' si absent/aberrant.
    On ecrit des FLOATS en RAW : c'est la garantie qu'aucune locale, d'aucun
    cote, ne pourra plus transformer 8888,88 en 888888."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    return round(f, 2) if 0 < f < CAP else ""


def collecter_reference() -> Dict[str, Dict[str, Any]]:
    """{veve_uuid -> {atl, atl_date, ath, ath_date}} depuis le tracker."""
    produits = scrape_catalogue()
    ref: Dict[str, Dict[str, Any]] = {}
    for p in produits:
        uid = str(p.get("veve_uuid") or "").strip()
        if not uid:
            continue
        ref[uid] = {
            "atl": _nombre_ou_vide(p.get("atl")),
            "atl_date": str(p.get("atl_date") or ""),
            "ath": _nombre_ou_vide(p.get("ath")),
            "ath_date": str(p.get("ath_date") or ""),
        }
    avec = sum(1 for v in ref.values() if v["atl"] != "" or v["ath"] != "")
    print(f"  tracker : {len(ref)} produits, {avec} avec un ATL/ATH.",
          flush=True)
    return ref


def _entetes(vals: List[List[str]]) -> Optional[int]:
    for i, ligne in enumerate(vals[:40]):
        if "veve_uuid" in ligne and "atl" in ligne:
            return i
    return None


def reparer_onglet(ws, ref: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    vals = _retry(f"lecture {ws.title}", ws.get_all_values)
    i_ent = _entetes(vals)
    if i_ent is None:
        print(f"  ⚠️ {ws.title} : pas d'en-tetes veve_uuid+atl — onglet saute.",
              file=sys.stderr)
        return {}
    ent = vals[i_ent]
    idx = {c: ent.index(c) for c in COLS}
    i_uid = ent.index("veve_uuid")

    stats = {"lignes": 0, "tracker": 0, "purgees": 0, "normalisees": 0,
             "intactes": 0, "incoherentes_avant": 0, "incoherentes_apres": 0}
    exemples: List[str] = []
    # une colonne de sortie par champ, alignee sur TOUTES les lignes de donnees
    sorties: Dict[str, List[List[Any]]] = {c: [] for c in COLS}

    for ligne in vals[i_ent + 1:]:
        stats["lignes"] += 1

        def _cur(c):
            j = idx[c]
            return ligne[j] if j < len(ligne) else ""

        uid = (ligne[i_uid] if i_uid < len(ligne) else "").strip()
        cur_atl, cur_ath = _dec(_cur("atl")), _dec(_cur("ath"))
        incoherente = cur_atl > 0 and cur_ath > 0 and cur_atl > cur_ath
        if incoherente:
            stats["incoherentes_avant"] += 1

        f = ref.get(uid)
        if f and (f["atl"] != "" or f["ath"] != ""):
            neuf = f
            stats["tracker"] += 1
            if incoherente and len(exemples) < 8:
                exemples.append(f"    {uid[:8]}…  atl {_cur('atl')!r} -> "
                                f"{f['atl']!r} · ath {_cur('ath')!r} -> "
                                f"{f['ath']!r}")
        elif incoherente:
            # paire impossible et pas de verite fraiche : on VIDE (inconnu
            # honnete) plutot que de garder un chiffre qu'on sait faux.
            neuf = {c: "" for c in COLS}
            stats["purgees"] += 1
        else:
            # on garde, mais RE-NORMALISE en nombre (« 6,99 » texte -> 6.99) ;
            # les dates restent telles quelles.
            neuf = {"atl": _nombre_ou_vide(_dec(_cur("atl")) or ""),
                    "atl_date": _cur("atl_date"),
                    "ath": _nombre_ou_vide(_dec(_cur("ath")) or ""),
                    "ath_date": _cur("ath_date")}
            if (str(neuf["atl"]) != str(_cur("atl"))
                    or str(neuf["ath"]) != str(_cur("ath"))):
                stats["normalisees"] += 1
            else:
                stats["intactes"] += 1
        n_atl, n_ath = _dec(neuf["atl"]), _dec(neuf["ath"])
        if n_atl > 0 and n_ath > 0 and n_atl > n_ath:
            stats["incoherentes_apres"] += 1
        for c in COLS:
            sorties[c].append([neuf[c]])

    print(f"  {ws.title} : {stats['lignes']} lignes · "
          f"{stats['tracker']} reprises du tracker · "
          f"{stats['purgees']} paires impossibles videes · "
          f"{stats['normalisees']} re-normalisees en nombre · "
          f"{stats['intactes']} intactes.", flush=True)
    print(f"    paires impossibles : {stats['incoherentes_avant']} avant -> "
          f"{stats['incoherentes_apres']} apres.", flush=True)
    if exemples:
        print("    exemples de reparations ×100 :", flush=True)
        for e in exemples:
            print(e, flush=True)

    if SIMULER:
        print(f"  [SIMULATION — {ws.title} : rien n'est ecrit]", flush=True)
        return stats

    # 4 plages mono-colonne, un seul batch_update par onglet (quota minimal).
    premiere = i_ent + 2                      # 1-based, ligne apres l'en-tete
    data = []
    for c in COLS:
        col = idx[c] + 1
        a1 = (rowcol_to_a1(premiere, col) + ":"
              + rowcol_to_a1(premiere + len(sorties[c]) - 1, col))
        data.append({"range": a1, "values": sorties[c]})
    _retry(f"ecriture {ws.title}",
           lambda: ws.batch_update(data, value_input_option="RAW"))
    print(f"  ✅ {ws.title} : colonnes atl/atl_date/ath/ath_date recrites "
          f"(RAW, nombres).", flush=True)
    return stats


def main() -> int:
    sid = os.environ.get("SHEET_ID")
    if not sid:
        print("SHEET_ID manquant.", file=sys.stderr)
        return 2
    print(("🔬 SIMULATION (REPARE_SIMULER=1) : tout est calcule, rien n'est "
           "ecrit." if SIMULER else
           "✍️ ECRITURE REELLE : les 4 colonnes atl/ath vont etre recrites."),
          flush=True)
    ref = collecter_reference()
    if not ref:
        print("⛔ tracker vide — on ne touche a RIEN.", file=sys.stderr)
        return 3
    sh = _retry("ouverture du Sheet", lambda: _client().open_by_key(sid))
    for tab in (COMICS_TAB, COLLECT_TAB):
        reparer_onglet(sh.worksheet(tab), ref)

    # Le temoin : ODDY. Sa corruption est PROUVEE (888888 en cellule contre
    # 8888,88 observe en direct par les alertes) — s'il ne change pas, la
    # reparation n'a pas fait son travail.
    oddy = ref.get("76880cbf-8e51-4cf7-9941-a5496675198e")
    if oddy:
        print(f"  🔎 temoin ODDY : tracker dit atl={oddy['atl']} "
              f"ath={oddy['ath']} (en cellule on avait 1499 / 888888).",
              flush=True)
    print("Termine. Etape suivante : relancer l'export du pont "
          "(export_elements) et verifier « 0 paire incoherente » dans son log.",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
