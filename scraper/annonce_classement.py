# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve · CHEMIN : scraper/annonce_classement.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""🏆 LIRE 🏆A-CLASSEMENT EN ENTIER — pour la carte comic de l'affiche.

La carte du visuel de Preda porte cinq chiffres :

    INCREDIBLE HULK #340
    DISPO DEPUIS LE 14/05/26        <- date_drop
    COMICS DE 1962                  <- start_year
    ESTIMATION IRL 1258             <- valeur_irl_98  (le prix d'une 9.8 papier)
    FIRST APPARENCE -/-             <- fa_key
    SUPPLY 2 000                    <- supply

**Ils sont TOUS deja dans 🏆A-CLASSEMENT** — la page que Preda tient a la main.
Rien a collecter, rien a estimer : on lit sa colonne.

⚠️ LES DEUX PIEGES DE CETTE PAGE, DEJA PAYES SUR UN RUN REEL
------------------------------------------------------------
1. `get_all_records()` EXPLOSE si deux colonnes portent le meme nom — la page
   en a. On lit donc en valeurs brutes.
2. **LES EN-TETES NE SONT PAS EN LIGNE 1** : la page commence par une banniere
   (« 🆕 À NOTER — COMICS : 3 … »). Chercher les colonnes en ligne 1 revient a
   lire un titre et a conclure qu'il n'y a pas de donnees.
→ On ANCRE : on balaie les premieres lignes jusqu'a en trouver une qui porte une
CLE. ⭐ **On cherche la donnee, on ne suppose pas ou elle est.**

⚠️⚠️ CE FICHIER A UN JUMEAU : `discord_retour.notes_de_classement`, qui fait le
meme ancrage mais ne rend que la colonne `note`. Je ne l'ai pas refactorise —
toucher un module quotidien pour une affiche mensuelle est un mauvais echange.
**Mais deux lecteurs de la meme page finissent toujours par diverger**, alors
`tests/test_annonce_visuel.py` les fait lire le MEME faux Sheet et exige le meme
resultat. Le jour ou l'un des deux bougera, le banc le dira.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List

TAB = os.environ.get("DISCORD_ANNONCE_CLASSEMENT_TAB", "🏆A-CLASSEMENT")

# Les colonnes qui peuvent servir de cle, par ordre de preference.
CLES = ("uuid", "series_uuid", "veve_uuid")


def lignes(sh, tab: str = "") -> List[Dict[str, Any]]:
    """Toutes les lignes de 🏆A-CLASSEMENT, en dictionnaires.

    Rend [] si la page est illisible ou si aucune ligne d'en-tetes n'est
    trouvee : **l'affiche perdra sa carte, personne ne plantera.**"""
    tab = tab or TAB
    try:
        vals = sh.worksheet(tab).get_all_values()
    except Exception as e:                                  # noqa: BLE001
        print(f"lecture de {tab} impossible : {e}", file=sys.stderr)
        return []

    for i, ligne in enumerate(vals[:40]):
        noms = [str(c).strip() for c in ligne]
        bas = [n.lower() for n in noms]
        cle = next((c for c in CLES if c in bas), "")
        if not cle:
            continue
        out = []
        for r in vals[i + 1:]:
            if not any(str(c).strip() for c in r):
                continue
            out.append({noms[j]: (r[j] if j < len(r) else "")
                        for j in range(len(noms)) if noms[j]})
        print(f"{tab} : en-tetes trouves en ligne {i + 1} ({len(out)} lignes).",
              flush=True)
        return out

    print(f"{tab} : aucune ligne d'en-tetes portant une cle "
          f"({'/'.join(CLES)}) dans les 40 premieres lignes — la carte du "
          f"comic ne sera pas remplie.", file=sys.stderr)
    return []


def par_cle(sh, tab: str = "") -> Dict[str, Dict[str, Any]]:
    """{uuid: ligne}. La 1re occurrence gagne, comme pour les notes."""
    out: Dict[str, Dict[str, Any]] = {}
    for l in lignes(sh, tab):
        for c in CLES:
            k = ""
            for nom, v in l.items():
                if nom.lower() == c:
                    k = str(v).strip()
                    break
            if k and k not in out:
                out[k] = l
                break
    return out


def carte(fiche: Dict[str, Any], nom_repli: str = "",
          image_repli: str = "", tirage: int = 0,
          tirage_emis: int = 0) -> Dict[str, Any]:
    """La ligne du classement -> les six champs de la carte du visuel.

    🔴 `tirage` EST LE CHIFFRE QUI FAIT AUTORITE (05/08/2026). Le 1er vrai run
    a publie **un seul visuel portant DEUX tirages** : la carte disait
    « SUPPLY 10 000 » (colonne `supply` de 🏆A-CLASSEMENT) pendant que le
    message ecrivait « 9 625 vendus sur 6 000 » (`dr.total_serie`, alors
    fausse). ⭐⭐⭐ **DEUX LECTEURS DE LA MEME GRANDEUR FINISSENT TOUJOURS PAR
    DIVERGER — ET C'EST LE VISUEL QUI PORTE LA CONTRADICTION, PAS LE CODE.**
    La carte cite donc desormais le tirage CALCULE par le module, le meme que
    le texte. La colonne du classement ne sert plus que de repli, et tout
    desaccord est ecrit sur stderr avec le nom de la serie.

    ⚠️⚠️ `tirage` ET `tirage_emis` NE SONT PAS LA MEME GRANDEUR (lot 62) :
    `tirage` est ce qu'on AFFICHE (les editions en circulation, 9 625) et
    `tirage_emis` ce qu'on COMPARE au classement (les editions emises, 10 000,
    qui est ce que porte 🏆A-CLASSEMENT). Les confondre rendait l'alerte
    **systematique** : tout comic a editions retenues serait sorti « discordant »
    alors que les deux nombres sont simplement deux choses differentes.
    ⭐⭐⭐ **UN AVERTISSEMENT QUI SE DECLENCHE SUR LE CAS NORMAL N'EST PLUS UN
    AVERTISSEMENT, C'EST DU BRUIT** — et le bruit se lit comme du silence.

    ⭐ LA CARTE SE FABRIQUE MEME SANS FICHE : nom et couverture viennent alors
    du catalogue, et les trois chiffres du classement s'ecrivent « -/- ». Une
    carte incomplete reste une carte ; une carte absente change la composition
    du visuel."""
    fiche = fiche or {}

    def champ(*noms):
        for n in noms:
            for cle, v in fiche.items():
                if cle.lower() == n and str(v).strip():
                    return str(v).strip()
        return ""

    date = champ("date_drop")
    supply_classement = champ("supply")
    supply = supply_classement
    # ⛔ On compare au tirage EMIS (ce que porte le classement), on AFFICHE la
    # circulation. Sans `tirage_emis`, on retombe sur l'ancien comportement.
    attendu = tirage_emis or tirage
    if tirage:
        # ⚠️ On compare des NOMBRES, pas des chaines : « 10 000 », « 10000 » et
        # « 10,000 » sont le meme tirage et ne doivent pas crier.
        try:
            brut = int("".join(c for c in supply_classement if c.isdigit()) or 0)
        except ValueError:                                  # pragma: no cover
            brut = 0
        if brut and brut != attendu:
            print(f"tirage discordant pour « {champ('nom', 'name') or nom_repli} "
                  f"» : 🏆A-CLASSEMENT dit {brut}, le module a emis {attendu} "
                  f"— la carte affiche {tirage}, comme le texte. Un seul visuel "
                  f"ne peut pas porter deux tirages.", file=sys.stderr, flush=True)
        supply = str(tirage)
    return {
        "nom": champ("nom", "name") or nom_repli,
        "dispo": _jj_mm_aa(date),
        "annee": champ("start_year", "annee"),
        "estimation": champ("valeur_irl_98", "valeur"),
        "premiere_app": champ("fa_key", "premiere_app"),
        "supply": supply,
        "image": champ("image_url") or image_repli,
    }


def _jj_mm_aa(brut: str) -> str:
    """« 2026-05-14 » ou « 14/05/2026 15:00 » -> « 14/05/26 », le format de
    Preda. Illisible -> vide : la ligne dira « -/- » plutot qu'une fausse date."""
    s = (brut or "").strip()
    if not s:
        return ""
    import datetime as _dt
    for fmt, n in (("%Y-%m-%d", 10), ("%d/%m/%Y", 10),
                   ("%Y-%m-%d %H:%M:%S", 19), ("%d/%m/%Y %H:%M:%S", 19),
                   ("%d/%m/%Y %H:%M", 16)):
        try:
            return _dt.datetime.strptime(s.replace("T", " ")[:n],
                                         fmt).strftime("%d/%m/%y")
        except ValueError:
            continue
    return ""
