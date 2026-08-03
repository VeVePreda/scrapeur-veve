# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/couvertures_chaine.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier depose au
# mauvais endroit ne provoque aucune erreur : il dort.

"""🖼️ LA COUVERTURE VIENT DE LA CHAINE — et seulement quand il n'y en a pas.

CE QUE CE MODULE FAIT, ET RIEN D'AUTRE
--------------------------------------
Il lit `data/elements_v3.csv` (colonne `image`, 19e, posee le 03/08/2026) et
rend, pour un `veve_uuid`, l'adresse du visuel inscrite ON-CHAIN.
`sheets._normalise` s'en sert pour remplir `image_url` **UNIQUEMENT LA OU IL
EST VIDE**.

⛔ IL N'ECRASE JAMAIS RIEN. C'est la difference de nature avec
`bascule_identite`, qui REMPLACE des valeurs et doit donc etre eteint par
defaut : ici, une valeur presente reste presente, et le pire cas est « rien ne
change ». Un interrupteur existe quand meme (`COUVERTURES_CHAINE=0`), mais il
sert a arreter, pas a autoriser.

POURQUOI CE MODULE EXISTE (mesure du 03/08/2026)
------------------------------------------------
  * 16 521 comics dans `🟢C-COMICS`, dont **11 264 sans aucun visuel** (68 %) ;
  * la requete GraphQL `publicComicType{ media }` ne rend RIEN pour 3 049 des
    4 286 series — ce n'est pas notre bug, c'est le mauvais champ ;
  * ⛔ et on ne peut pas en demander un autre : VeVe n'accepte que des textes
    de requete sur liste blanche (dix selections essayees, dix
    `Invalid request.`, introspection comprise) ;
  * la metadata on-chain, elle, porte le couple explicitement :
    `image = comic_cover.<veve_uuid>.<img>` ;
  * **11 124 des 11 264 fiches vides (98,8 %) sont dans la moisson du 28/07.**

⭐⭐ IL N'Y A DONC AUCUN APPARIEMENT A FAIRE. La chaine ne dit pas « voici des
images pour ce comic », elle dit « voici l'image DE CETTE PIECE ». Tout le
chantier d'appariement du lot 29 essayait de reconstituer, par la forme d'une
URL, un lien que cette source-ci enonce.

LES PIEGES QUI SONT DEJA PAYES ICI
----------------------------------
  * ⛔ On ne FABRIQUE aucune adresse. Le 2e identifiant de l'URL est
    imprevisible ; une adresse construite serait une adresse inventee, et un
    visuel casse est PIRE qu'un visuel absent (le visiteur conclut que le site
    se trompe, pas que la source manque).
  * ⛔ Aucun repli muet. Ce qui reste sans image est COMPTE et NOMME, pas
    comble en silence.
  * ⭐ `guid != veve_uuid` : la cle de jointure est bien le `veve_uuid`, celui
    que `_UUID_RE` extrait de l'URL elle-meme.
  * ⭐ Le fichier ABSENT n'est pas une erreur : le module devient un NO-OP
    bruyant (il le DIT) et le daily continue. Un catalogue sans couverture
    reste un catalogue.
"""

from __future__ import annotations

import csv
import os
import sys
from typing import Dict, Optional

CHEMIN = os.environ.get("ELEMENTS_V3", "data/elements_v3.csv")

# 🖼️ Prefixes ATTENDUS. Ils ne servent pas a filtrer (on recopie ce que la
# chaine dit), mais a REPERER une derive : si VeVe change de forme, le compteur
# `inattendu` le dira avant que les fiches ne se remplissent de n'importe quoi.
PREFIXES = ("collectible_type_image.", "comic_cover.", "comic_type_image.")

_MAP: Optional[Dict[str, str]] = None
_BILAN: Dict[str, int] = {"charge": 0, "vide": 0, "inattendu": 0,
                          "posees": 0, "deja": 0, "manquantes": 0}


def actif() -> bool:
    """⭐ ALLUME PAR DEFAUT, contrairement a `bascule_identite`. La raison
    tient en une phrase : ce module ne peut RIEN detruire, il ne remplit que
    du vide. Mettre `COUVERTURES_CHAINE=0` l'arrete."""
    return os.environ.get("COUVERTURES_CHAINE", "1").strip().lower() not in (
        "0", "false", "non", "off")


def charger(chemin: str = "") -> Dict[str, str]:
    """{veve_uuid: url} depuis elements_v3.csv. Lu UNE fois, garde en memoire.

    ⛔ LECTURE PAR NOM DE COLONNE, jamais par position : `image` est la 19e
    aujourd'hui, elle ne le restera pas. Un `DictReader` survit a l'insertion
    suivante ; un index `r[18]` ferait afficher la provenance a la place de
    l'adresse, sans lever la moindre erreur."""
    global _MAP
    if _MAP is not None:
        return _MAP
    _MAP = {}
    p = chemin or CHEMIN
    if not os.path.exists(p):
        print(f"  🖼️ couvertures chaine : `{p}` absent — aucune couverture "
              f"reportee. (Le catalogue reste valide, il aura juste ses trous.)",
              file=sys.stderr, flush=True)
        return _MAP
    with open(p, encoding="utf-8") as f:
        lecteur = csv.DictReader(f)
        if "image" not in (lecteur.fieldnames or []):
            print(f"  🖼️ couvertures chaine : `{p}` n'a PAS de colonne "
                  f"`image` — c'est une moisson d'AVANT le 03/08/2026. "
                  f"Rejouer `elements-v3-moisson` pour la produire.",
                  file=sys.stderr, flush=True)
            return _MAP
        for r in lecteur:
            uid = (r.get("veve_uuid") or "").strip().lower()
            url = (r.get("image") or "").strip()
            if not uid:
                continue
            if not url:
                _BILAN["vide"] += 1
                continue
            if not any(m in url for m in PREFIXES):
                _BILAN["inattendu"] += 1
            _MAP[uid] = url
    _BILAN["charge"] = len(_MAP)
    print(f"  🖼️ couvertures chaine : {len(_MAP)} adresse(s) chargee(s) "
          f"depuis {p} ({_BILAN['vide']} ligne(s) sans visuel).", flush=True)
    if _BILAN["inattendu"]:
        print(f"  ⚠️ {_BILAN['inattendu']} adresse(s) hors des formes connues "
              f"({', '.join(PREFIXES)}). VeVe a peut-etre change de forme — "
              f"a regarder AVANT de s'en servir ailleurs.",
              file=sys.stderr, flush=True)
    return _MAP


def image_pour(uuid) -> str:
    """L'adresse on-chain d'une piece, ou "" si la chaine n'en connait pas."""
    if not actif():
        return ""
    return charger().get(str(uuid or "").strip().lower(), "")


def noter(pose: bool) -> None:
    """Compte ce qui a ete rempli / ce qui l'etait deja. Appele par sheets."""
    _BILAN["posees" if pose else "deja"] += 1


def noter_manquante() -> None:
    _BILAN["manquantes"] += 1


def bilan() -> Dict[str, int]:
    return dict(_BILAN)


def resume() -> str:
    """La phrase a lire dans le log du daily. ⭐ Elle donne le RESTE, pas
    seulement le succes : c'est le reste qui decide de la suite."""
    b = _BILAN
    if not actif():
        return "🖼️ couvertures chaine : ETEINTE (COUVERTURES_CHAINE=0)."
    txt = (f"🖼️ couvertures chaine : {b['posees']} fiche(s) remplie(s), "
           f"{b['deja']} en avaient deja une, "
           f"{b['manquantes']} SANS COUVERTURE apres passage.")
    if b["manquantes"]:
        txt += ("  ⚠️ Ces dernieres ne sont pas un echec de collecte : la "
                "chaine ne leur a jamais inscrit d'image. Elles sont le "
                "chantier suivant, pas un bug de celui-ci.")
    return txt


def _reinit() -> None:
    """Uniquement pour les bancs : vide le cache et les compteurs."""
    global _MAP
    _MAP = None
    for k in _BILAN:
        _BILAN[k] = 0
