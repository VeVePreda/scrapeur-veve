# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/repare_atl_ath.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""🔧 REPARATION DES COLONNES CHIFFREES DU CATALOGUE FROID.

   audit du 22/07/2026 (atl/ath)  ·  ELARGI le 03/08/2026 (prix) — lot 51

LE MAL, NOMME LE 03/08/2026 : `gspread.utils.numericise`
--------------------------------------------------------
    >>> numericise("9,99")  ->  999        >>> numericise("9.99")  ->  9.99
    >>> numericise("2,5")   ->   25        (la virgule y est un separateur
    >>> numericise("12,4")  ->  124         de MILLIERS, sa docstring le dit)

`get_all_records()` l'appelle sur CHAQUE cellule. Une valeur affichee « 9,99 »
revient donc en Python comme l'entier 999, puis est reecrite dans le Sheet
comme le NOMBRE 999 : une cellule numerique parfaitement propre, indiscernable
d'un vrai 999.

⭐⭐⭐ UN NOMBRE QUI TRAVERSE UNE BIBLIOTHEQUE N'EST PLUS UN NOMBRE, C'EST UNE
CHAINE QU'ELLE REINTERPRETE. On croyait lire une valeur ; on lisait son
apparence, re-parsee par les conventions de quelqu'un d'autre.

⭐⭐ IL N'Y A PAS DE BUG « ATL », IL Y A UN BUG « NOMBRE A DECIMALES ». L'atl a
des centimes, l'ath est souvent entier (11, 20, 55, 225) — rien a perdre. Le
defaut se deguisait en defaut de colonne. **Toute colonne a decimales dont le
format de cellule est `General` est exposee.** Ce qui a sauve `_WalletSize`,
c'est son suffixe `%` : un format qui rend la valeur NON numerique la protege
par accident. La colonne la plus simple est la plus exposee.

⚠️ Le pire : une paire ×100 DES DEUX COTES reste coherente (atl < ath) et passe
sous tous les garde-fous. On ne peut donc PAS reparer en divisant « ce qui a
l'air gros » : 1499 peut etre un vrai 1 499 $ ou un 14,99 corrompu.
**La seule reparation honnete est de re-demander la verite a la source.**

CE QUE LE LOT 51 AJOUTE
-----------------------
Le robinet est ferme depuis le lot 50 (`sheets._lire_lignes` lit en
UNFORMATTED). Restait le dommage deja gele, et il DEBORDE des extremes :

    colonne                    lignes   entiers   >= 100    verdict
    store_price_gems (comics)  16 426    100 %     97,9 %   🔴 corrompu a 100 %
    gemsPerMcp (comics)        16 521    99,8 %    46,7 %   🔴
    atl / ath (comics)        ~16 400    99,1 %    64-76 %  ✅ repare le 03/08
    daily_mcp_points           16 521    100 %       0 %    ✅ ENTIER PAR NATURE

⭐ `daily_mcp_points` est le TEMOIN : entier par nature, la virgule n'avait rien
a lui supprimer. S'il bouge, la reparation deborde. Une assertion l'interdit.

DEUX PIEGES PAYES A L'ECRITURE DE CE LOT
----------------------------------------
1. `store_price_gems` N'EST PAS UNE COPIE BRUTE DU TRACKER. `sheets._fill_new_cold`
   applique une regle du projet : pour un COMIC, une valeur >= 100 est en
   CENTIMES et vaut /100 (VeVe melange deux echelles ; les vieux comics etaient
   vendus en gems : 10, 15, 20). ⇒ Ce module APPELLE cette fonction au lieu d'en
   recopier la regle.
   ⭐⭐ UN REPARATEUR QUI REDEFINIT LA COLONNE QU'IL REPARE ENTRE EN GUERRE AVEC
   LE QUOTIDIEN. Deux definitions de la meme colonne ne divergent pas bruyamment :
   elles se reecrivent l'une l'autre, chaque jour, sans qu'aucune n'echoue.
2. LES COLLECTIBLES NE SONT PAS ECRITS SUR `store_price_gems`. Un prix boutique
   de collectible est un ENTIER de gems (1 500) : la virgule n'avait rien a y
   supprimer, et l'echelle du tracker n'y est PAS prouvee. On les MESURE et on
   imprime le verdict ; `REPARE_COLLECT_PRIX=1` autorise l'ecriture le jour ou
   le rapport la justifie.
   ⛔ Un ×100 UNIFORME sur toute une colonne n'est pas une virgule sautee, c'est
   une UNITE differente : la virgule produit des rapports MELANGES (×10, ×100,
   ×1 selon le nombre de decimales). Le rapport imprime cette distribution
   exactement pour permettre de trancher.

CE QUE FAIT CE MODULE
---------------------
1. Scrape le catalogue tracker COMPLET (~800 requetes de 24 — la meme empreinte
   qu'un backfill ; a lancer UNE fois, pas en cron).
2. Relit les deux onglets froids EN NON FORMATE (lecon du lot 50 : ce module
   lisait lui aussi des valeurs d'affichage), reconvertit les colonnes de date
   depuis leur numero de serie, puis recrit UNIQUEMENT ses colonnes :
     · tracker connu -> la valeur fraiche, EN NOMBRE (write RAW : jamais de
       chaine formatee, c'est le vecteur de la corruption d'origine) ;
     · tracker muet  -> la valeur actuelle re-normalisee en nombre, VIDEE
       seulement si la paire atl/ath est impossible.
   Les autres colonnes ne sont PAS touchees.
3. Un rapport qui se lit sans le code : distribution avant/apres, temoin
   immobile, et la mesure des collectibles.

MODE D'EMPLOI (regle du projet : on regle en simulation, jamais en public)
--------------------------------------------------------------------------
  REPARE_SIMULER=1 (defaut) : tout est calcule, RIEN n'est ecrit, le rapport dit
  exactement ce qui changerait. Relancer avec simuler=non pour ecrire.
  REPARE_COLONNES=tout|extremes|prix : les extremes ont ete reparees le
  03/08 — « prix » evite de rescraper pour les reecrire a l'identique.
⛔ NE RIEN LANCER EN MEME TEMPS QUE LE `daily` OU UNE MOISSON : le quota Sheets
   est PAR MINUTE et PARTAGE par tous les workflows du projet.

Env : GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID, REPARE_SIMULER, REPARE_COLONNES,
      REPARE_COLLECT_PRIX, REPARE_PAQUET.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from gspread.exceptions import APIError
from gspread.utils import ValueRenderOption, rowcol_to_a1

from scraper.sheets import (COLLECT_TAB, COLONNES_DATE, COMICS_TAB, _client,
                            _date_depuis_serie, _fill_new_cold)
from scraper.veve_scraper import scrape_catalogue

SIMULER = os.environ.get("REPARE_SIMULER", "1").strip().lower() not in (
    "0", "non", "false")
# ⛔ Ecrire `store_price_gems` sur 🔵C-COLLECTIBLE : desarme par defaut, cf. le
# piege 2 de l'en-tete. A n'armer QU'APRES lecture de la mesure imprimee.
COLLECT_PRIX = os.environ.get("REPARE_COLLECT_PRIX", "0").strip().lower() in (
    "1", "oui", "true")
GROUPE = os.environ.get("REPARE_COLONNES", "tout").strip().lower()
# Taille d'un paquet d'ecriture. ⚠️ `batch_update` est ATOMIQUE : un envoi trop
# gros echoue EN ENTIER, apres ~800 requetes de scraping. On borne la charge.
PAQUET = max(500, int(os.environ.get("REPARE_PAQUET") or 6000))

# Meme plafond d'aberration que veve_scraper : un ATH >= 1e12 est un troll.
CAP = 1e12

EXTREMES = ("atl", "atl_date", "ath", "ath_date")
PRIX = ("store_price_gems", "gemsPerMcp")
# Nombre de decimales conservees a l'ecriture. ⚠️ `gemsPerMcp` vaut
# 2,3266666666666667 : l'arrondir a 2 le detruirait aussi surement que la
# virgule sautee. Un arrondi est une perte silencieuse — il se decide par
# colonne, jamais globalement.
DECIMALES = {"atl": 2, "ath": 2, "store_price_gems": 2, "gemsPerMcp": 6}
# 🩺 LE TEMOIN. Entier par nature => indemne par nature. Il n'est jamais ecrit,
# et une assertion le prouve a chaque onglet.
TEMOIN = "daily_mcp_points"


def _colonnes(tab: str) -> Tuple[str, ...]:
    """Les colonnes ecrites pour cet onglet — la portee, en un seul endroit."""
    cols: List[str] = []
    if GROUPE in ("tout", "extremes"):
        cols += list(EXTREMES)
    if GROUPE in ("tout", "prix"):
        cols.append("gemsPerMcp")          # passe-plat du tracker, sans piege
        if tab == COMICS_TAB or COLLECT_PRIX:
            cols.append("store_price_gems")
    return tuple(cols)


def _dec(x) -> float:
    """Decimal FR-tolerant (« 8 888,88 » -> 8888.88), 0.0 si illisible."""
    try:
        return float(str(x).replace(" ", "").replace(" ", "")
                     .replace(" ", "").replace(",", ".") or 0)
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


def _nombre_ou_vide(v, nd: int = 2) -> Any:
    """Une valeur du tracker -> nombre ecrit tel quel, ou '' si absente/aberrante.
    On ecrit des FLOATS en RAW : c'est la garantie qu'aucune locale, d'aucun
    cote, ne pourra plus transformer 8888,88 en 888888."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    return round(f, nd) if 0 < f < CAP else ""


# ---------------------------------------------------------------------------
# 1. LA VERITE : le tracker
# ---------------------------------------------------------------------------

def collecter_reference() -> Dict[str, Dict[str, Any]]:
    """{veve_uuid -> {atl, atl_date, ath, ath_date, store_price_gems,
    gemsPerMcp}} depuis le tracker."""
    produits = scrape_catalogue()
    ref: Dict[str, Dict[str, Any]] = {}
    for p in produits:
        uid = str(p.get("veve_uuid") or "").strip()
        if not uid:
            continue
        # ⭐ LA REGLE DU PRIX N'EST PAS RECOPIEE ICI : on demande au pipeline
        # lui-meme ce que vaut la colonne. Une seule definition dans le projet.
        rec: Dict[str, Any] = {"category": p.get("category"),
                               "storePrice": p.get("storePrice")}
        _fill_new_cold(rec)
        ref[uid] = {
            "atl": _nombre_ou_vide(p.get("atl")),
            "atl_date": str(p.get("atl_date") or ""),
            "ath": _nombre_ou_vide(p.get("ath")),
            "ath_date": str(p.get("ath_date") or ""),
            "store_price_gems": _nombre_ou_vide(rec.get("store_price_gems"), 2),
            "gemsPerMcp": _nombre_ou_vide(p.get("gemsPerMcp"), 6),
        }
    avec_e = sum(1 for v in ref.values() if v["atl"] != "" or v["ath"] != "")
    avec_p = sum(1 for v in ref.values() if v["store_price_gems"] != "")
    avec_g = sum(1 for v in ref.values() if v["gemsPerMcp"] != "")
    print(f"  tracker : {len(ref)} produits · {avec_e} avec un ATL/ATH · "
          f"{avec_p} avec un prix boutique · {avec_g} avec un gemsPerMcp.",
          flush=True)
    return ref


# ---------------------------------------------------------------------------
# 2. LA LECTURE — en NON FORMATE (lecon du lot 50)
# ---------------------------------------------------------------------------

def _lire_valeurs(ws) -> List[List[Any]]:
    """La grille brute. ⭐ EN NON FORMATE : ce module lisait lui aussi des
    valeurs d'AFFICHAGE, exactement le trajet qu'il repare.
    ⚠️ Contrepartie connue (lot 50) : une date revient alors en NUMERO DE SERIE.
    `_reconvertir_dates` la remet en texte — sans quoi on echangerait un bug de
    prix contre un bug de dates, le meme trajet, l'autre colonne."""
    try:
        return _retry(f"lecture {ws.title}", lambda: ws.get_all_values(
            value_render_option=ValueRenderOption.unformatted))
    except TypeError:                       # gspread trop ancien : on degrade
        print(f"  ⚠️ {ws.title} : lecture NON FORMATEE indisponible "
              "(gspread ancien) — repli sur la lecture d'affichage.",
              file=sys.stderr, flush=True)
        return _retry(f"lecture {ws.title}", ws.get_all_values)


def _reconvertir_dates(vals: List[List[Any]], ent: List[str],
                       depuis: int) -> int:
    """45615 -> « 2024-11-19 » sur les colonnes de date connues. Rend le nombre
    de cellules reconverties (0 = la lecture etait deja en texte)."""
    n = 0
    idx = [ent.index(c) for c in COLONNES_DATE if c in ent]
    if not idx:
        return 0
    for ligne in vals[depuis:]:
        for j in idx:
            if j < len(ligne):
                v = _date_depuis_serie(ligne[j])
                if v != ligne[j]:
                    ligne[j] = v
                    n += 1
    return n


def _entetes(vals: List[List[Any]]) -> Optional[int]:
    for i, ligne in enumerate(vals[:40]):
        if "veve_uuid" in ligne and "atl" in ligne:
            return i
    return None


# ---------------------------------------------------------------------------
# 3. LA MESURE — repondre a « faut-il ecrire ? » AVANT d'ecrire
# ---------------------------------------------------------------------------

def _rapport_ratios(titre: str, paires: Iterable[Tuple[float, float]],
                    peut_avertir: bool) -> None:
    """Distribution des rapports Sheet/tracker.

    ⭐ LE DIAGNOSTIC EST DANS LA FORME DE LA DISTRIBUTION, PAS DANS SON AMPLEUR.
    Une virgule sautee donne des rapports MELANGES (×10 sur « 2,5 », ×100 sur
    « 9,99 », ×1 sur « 20 ») ; un rapport UNIFORME sur toute une colonne PEUT
    denoncer une UNITE differente — et la « reparer » serait la casser.

    ⚠️ `peut_avertir` : l'alerte « unite differente » ne sort QUE pour une
    colonne encore INDECISE. ⭐⭐ UN AVERTISSEMENT QUI SURVIT A SA CAUSE DEVIENT
    UN MENSONGE QUI SE CITE : `store_price_gems` des comics EST uniformement
    ×100 (des prix a deux decimales, donc un seul rapport possible), et c'est
    justement pourquoi on l'ecrit. Crier dessus a chaque run apprendrait a
    ignorer la ligne — le jour ou elle parlerait d'une vraie colonne indecise.
    Le banc de ce lot a fait sortir exactement cette fausse alerte."""
    seaux = {1: 0, 10: 0, 100: 0, 1000: 0}
    autre = total = 0
    for sheet, vrai in paires:
        if vrai <= 0:
            continue
        total += 1
        for k in (1, 10, 100, 1000):
            if abs(sheet - vrai * k) <= max(0.005, vrai * k * 1e-6):
                seaux[k] += 1
                break
        else:
            autre += 1
    if not total:
        print(f"    {titre} : aucune valeur comparable.", flush=True)
        return
    part = {k: 100.0 * v / total for k, v in seaux.items()}
    print(f"    {titre} : {total} comparables — "
          f"identique {seaux[1]} ({part[1]:.1f} %) · "
          f"x10 {seaux[10]} · x100 {seaux[100]} · x1000 {seaux[1000]} · "
          f"divergent {autre}", flush=True)
    decales = seaux[10] + seaux[100] + seaux[1000]
    if decales and seaux[10] and seaux[100]:
        print("      => rapports MELANGES : signature d'une virgule supprimee.",
              flush=True)
    elif not peut_avertir:
        return
    elif not decales:
        print("      => rien de decale : cette colonne n'a pas besoin d'etre "
              "reparee. Laisser `REPARE_COLLECT_PRIX` desarme.", flush=True)
    elif part[1] < 2.0:
        print("      => ⛔ rapport UNIFORME et quasi aucune valeur identique : "
              "cela peut etre une UNITE differente et PAS une virgule. "
              "Ne pas ecrire cette colonne sans trancher.", flush=True)


# ---------------------------------------------------------------------------
# 4. LA REPARATION
# ---------------------------------------------------------------------------

def reparer_onglet(ws, ref: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    cols = _colonnes(ws.title)
    if not cols:
        print(f"  {ws.title} : aucune colonne dans la portee — onglet saute.",
              flush=True)
        return {}

    vals = _lire_valeurs(ws)
    i_ent = _entetes(vals)
    if i_ent is None:
        print(f"  ⚠️ {ws.title} : pas d'en-tetes veve_uuid+atl — onglet saute.",
              file=sys.stderr)
        return {}
    ent = [str(c) for c in vals[i_ent]]
    n_dates = _reconvertir_dates(vals, ent, i_ent + 1)

    manquantes = [c for c in cols if c not in ent]
    if manquantes:
        print(f"  ⚠️ {ws.title} : colonnes absentes de l'onglet, ignorees : "
              f"{', '.join(manquantes)}", file=sys.stderr, flush=True)
        cols = tuple(c for c in cols if c in ent)
        if not cols:
            return {}
    idx = {c: ent.index(c) for c in cols}
    i_uid = ent.index("veve_uuid")

    # 🩺 L'ASSERTION DU TEMOIN. ⭐ Un temoin qu'on se contente de REGARDER ne
    # protege rien : il doit pouvoir ARRETER le programme. On ne verifie pas
    # apres coup que la colonne n'a pas bouge — on rend son ecriture impossible.
    if TEMOIN in ent and ent.index(TEMOIN) in set(idx.values()):
        raise SystemExit(f"⛔ {ws.title} : le temoin `{TEMOIN}` tombe dans une "
                         "plage a ecrire. Arret — la portee est fausse.")

    ecrit_extremes = all(c in idx for c in EXTREMES)
    stats = {"lignes": 0, "tracker": 0, "purgees": 0, "normalisees": 0,
             "intactes": 0, "incoherentes_avant": 0, "incoherentes_apres": 0,
             "prix_repris": 0, "prix_muets": 0,
             "gros_avant": 0, "gros_apres": 0}
    exemples: List[str] = []
    mesures: Dict[str, List[Tuple[float, float]]] = {c: [] for c in PRIX}
    sorties: Dict[str, List[List[Any]]] = {c: [] for c in cols}

    for ligne in vals[i_ent + 1:]:
        stats["lignes"] += 1

        def _cur(c, _l=ligne):
            j = ent.index(c)
            return _l[j] if j < len(_l) else ""

        uid = str(ligne[i_uid] if i_uid < len(ligne) else "").strip()
        f = ref.get(uid) or {}
        neuf: Dict[str, Any] = {}

        # ── les extremes : une PAIRE, avec sa regle de coherence ────────────
        if ecrit_extremes:
            cur_atl, cur_ath = _dec(_cur("atl")), _dec(_cur("ath"))
            incoherente = cur_atl > 0 and cur_ath > 0 and cur_atl > cur_ath
            if incoherente:
                stats["incoherentes_avant"] += 1
            if f and (f["atl"] != "" or f["ath"] != ""):
                neuf.update({c: f[c] for c in EXTREMES})
                stats["tracker"] += 1
                if incoherente and len(exemples) < 8:
                    exemples.append(
                        f"    {uid[:8]}...  atl {_cur('atl')!r} -> {f['atl']!r}"
                        f" · ath {_cur('ath')!r} -> {f['ath']!r}")
            elif incoherente:
                # paire impossible et pas de verite fraiche : on VIDE (inconnu
                # honnete) plutot que de garder un chiffre qu'on sait faux.
                neuf.update({c: "" for c in EXTREMES})
                stats["purgees"] += 1
            else:
                # on garde, mais RE-NORMALISE en nombre (« 6,99 » -> 6.99) ;
                # les dates restent telles quelles.
                neuf.update({"atl": _nombre_ou_vide(_dec(_cur("atl")) or ""),
                             "atl_date": _cur("atl_date"),
                             "ath": _nombre_ou_vide(_dec(_cur("ath")) or ""),
                             "ath_date": _cur("ath_date")})
                if (str(neuf["atl"]) != str(_cur("atl"))
                        or str(neuf["ath"]) != str(_cur("ath"))):
                    stats["normalisees"] += 1
                else:
                    stats["intactes"] += 1
            n_atl, n_ath = _dec(neuf["atl"]), _dec(neuf["ath"])
            if n_atl > 0 and n_ath > 0 and n_atl > n_ath:
                stats["incoherentes_apres"] += 1

        # ── les prix : colonne par colonne, SANS regle de coherence ─────────
        # ⛔ On ne VIDE jamais un prix : rien ne permet de dire qu'il est faux.
        # Sans verite fraiche on le laisse tel quel — abime mais COMPTE.
        for c in PRIX:
            if c not in ent:
                continue
            cur = _cur(c)
            vrai = f.get(c, "")
            if vrai != "":
                mesures[c].append((_dec(cur), float(vrai)))
            if c not in idx:
                continue
            if c == "store_price_gems" and _dec(cur) >= 100:
                stats["gros_avant"] += 1
            if vrai != "":
                neuf[c] = vrai
                stats["prix_repris"] += 1
            else:
                neuf[c] = _nombre_ou_vide(_dec(cur) or "", DECIMALES[c])
                stats["prix_muets"] += 1
            if c == "store_price_gems" and _dec(neuf[c]) >= 100:
                stats["gros_apres"] += 1

        for c in cols:
            sorties[c].append([neuf[c]])

    # ── le rapport ──────────────────────────────────────────────────────────
    print(f"  {ws.title} : {stats['lignes']} lignes · colonnes ecrites : "
          f"{', '.join(cols)}", flush=True)
    if n_dates:
        print(f"    {n_dates} cellules de date reconverties depuis leur "
              "numero de serie (lecture non formatee).", flush=True)
    if ecrit_extremes:
        print(f"    extremes : {stats['tracker']} reprises du tracker · "
              f"{stats['purgees']} paires impossibles videes · "
              f"{stats['normalisees']} re-normalisees · "
              f"{stats['intactes']} intactes.", flush=True)
        print(f"    paires impossibles : {stats['incoherentes_avant']} avant "
              f"-> {stats['incoherentes_apres']} apres.", flush=True)
        if exemples:
            print("    exemples de reparations x100 :", flush=True)
            for e in exemples:
                print(e, flush=True)
    if any(c in idx for c in PRIX):
        print(f"    prix : {stats['prix_repris']} valeurs reprises du tracker "
              f"· {stats['prix_muets']} laissees faute de verite fraiche.",
              flush=True)
        if "store_price_gems" in idx:
            print(f"    store_price_gems >= 100 : {stats['gros_avant']} avant "
                  f"-> {stats['gros_apres']} apres "
                  "(attendu sur les comics : de ~98 % a ~0).", flush=True)
    for c in PRIX:
        if mesures[c]:
            ecrite = c in idx
            etat = "ECRITE" if ecrite else "MESUREE SEULEMENT — c'est ce " \
                                          "rapport qui decide de l'ecrire"
            _rapport_ratios(f"{c} ({etat})", mesures[c], not ecrite)

    # 🩺 le temoin, imprime meme quand il ne dit rien : un controle muet ne se
    # distingue pas d'un controle absent.
    if TEMOIN in ent:
        j = ent.index(TEMOIN)
        vus = [l[j] for l in vals[i_ent + 1:] if j < len(l) and l[j] != ""]
        gros = sum(1 for v in vus if _dec(v) >= 100)
        print(f"    🩺 temoin `{TEMOIN}` : {len(vus)} valeurs, {gros} >= 100 — "
              "NON ECRIT (hors des plages envoyees).", flush=True)

    if SIMULER:
        print(f"  [SIMULATION — {ws.title} : rien n'est ecrit]", flush=True)
        return stats

    # ── l'ecriture, par paquets ─────────────────────────────────────────────
    premiere = i_ent + 2                      # 1-based, ligne apres l'en-tete
    total = len(sorties[cols[0]])
    for debut in range(0, total, PAQUET):
        fin = min(debut + PAQUET, total)
        bloc = []
        for c in cols:
            col = idx[c] + 1
            a1 = (rowcol_to_a1(premiere + debut, col) + ":"
                  + rowcol_to_a1(premiere + fin - 1, col))
            bloc.append({"range": a1, "values": sorties[c][debut:fin]})
        _retry(f"ecriture {ws.title} [{debut + 1}-{fin}]",
               lambda b=bloc: ws.batch_update(b, value_input_option="RAW"))
        print(f"    ✍️ {ws.title} : lignes {debut + 1}-{fin} ecrites.",
              flush=True)
        if fin < total:
            time.sleep(1.0)
    print(f"  ✅ {ws.title} : {', '.join(cols)} recrites (RAW, nombres).",
          flush=True)
    return stats


def main() -> int:
    sid = os.environ.get("SHEET_ID")
    if not sid:
        print("SHEET_ID manquant.", file=sys.stderr)
        return 2
    if GROUPE not in ("tout", "extremes", "prix"):
        print(f"REPARE_COLONNES={GROUPE!r} inconnu "
              "(attendu : tout | extremes | prix).", file=sys.stderr)
        return 2
    print(("🔬 SIMULATION (REPARE_SIMULER=1) : tout est calcule, rien n'est "
           "ecrit." if SIMULER else
           "✍️ ECRITURE REELLE : les colonnes vont etre recrites."), flush=True)
    print(f"   portee : {GROUPE} · store_price_gems sur 🔵C-COLLECTIBLE : "
          f"{'ECRIT' if COLLECT_PRIX else 'mesure seulement'} · "
          f"paquets de {PAQUET} lignes.", flush=True)
    ref = collecter_reference()
    if not ref:
        print("⛔ tracker vide — on ne touche a RIEN.", file=sys.stderr)
        return 3
    sh = _retry("ouverture du Sheet", lambda: _client().open_by_key(sid))
    for tab in (COMICS_TAB, COLLECT_TAB):
        reparer_onglet(sh.worksheet(tab), ref)

    # Le temoin historique : ODDY. ⚠️ Son ATH de 888 888 est REEL cote tracker
    # (un prix DEMANDE par un troll, pas une virgule sautee) — c'est le plafond
    # de vraisemblance du lot 49 qui l'ecarte a l'export, pas ce module.
    oddy = ref.get("76880cbf-8e51-4cf7-9941-a5496675198e")
    if oddy:
        print(f"  🔎 temoin ODDY : tracker dit atl={oddy['atl']} "
              f"ath={oddy['ath']} · prix={oddy['store_price_gems']}.",
              flush=True)
    print("Termine. Etapes suivantes : (1) relancer catalogue-export et lire "
          "« 0 paire incoherente » ; (2) au daily suivant, le compteur "
          "« 🩺 extremes lus dans le Sheet » doit tomber — et c'est le "
          "SURLENDEMAIN qui le prouve, pas le lendemain.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
