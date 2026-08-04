# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve · CHEMIN : scraper/annonce_images.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""🖼️ LES BONNES IMAGES DE L'AFFICHE — trois corrections de Preda (04/08).

1. **UNE TUILE MONTRE LA SERIE, PAS L'ELEMENT.** `image_url` du Sheet est le
   rendu du PRODUIT (le Yoda 3D detoure sur blanc). Ce que Preda pose dans sa
   mosaique, c'est l'**illustration de SERIE** — le visuel large avec le logo
   de la licence. Deux images tres differentes pour le meme objet.
   👉 `series_image.<series_uuid>.<image_uuid>.webpFull.webp`

   ⚠️ **L'`image_uuid` NE SE DEVINE PAS.** On lit donc l'`og:image` de la page
   publique de la serie — une requete par serie citee, soit **5 par mois**.
   ⭐ C'est la charge la plus faible possible : on ne balaye rien, on demande
   exactement les 5 pages qu'on va montrer.

2. **UN COMIC SE MONTRE EN RARETE COMMUNE.** Les 5 raretes d'un comic ont des
   couvertures differentes (variantes) ; celle qui represente la serie est la
   **COMMON**. Prendre « la premiere ligne venue » donnait une variante au
   hasard, differente d'un mois a l'autre — un bug qui a l'air de marcher.

3. **LES URL DE veve.me SONT EMBALLEES.** Le site sert ses images via
   `/_next/image?url=<CDN encode>&w=1200&q=85` : c'est un REDIMENSIONNEUR.
   On deballe pour taper le CDN en direct — sinon on recupere une image bridee
   a 1 200 px de large, et l'affiche fait 1 920.

⛔ AUCUNE DE CES TROIS ETAPES NE PEUT FAIRE ECHOUER L'AFFICHE : chacune rend ""
en cas de pepin, et l'appelant retombe sur l'image de l'element. Meme doctrine
que partout ailleurs — une case moins jolie vaut mieux qu'un visuel jamais
produit.
"""

from __future__ import annotations

import os
import re
import sys
import urllib.parse
import urllib.request
from typing import Any, Dict, List

# Le meme User-Agent explicite que le calendrier : le defaut d'urllib
# (`Python-urllib/3.x`) se fait renvoyer 403 par certains fronts.
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36 ScrapeurVeVe-annonce/1.0")

BASE_SERIE = os.environ.get("ANNONCE_VISUEL_BASE_SERIE",
                            "https://www.veve.me/collectibles/en/series")
DELAI = float(os.environ.get("ANNONCE_VISUEL_DELAI", "1.0"))


def deballer(url: str) -> str:
    """`/_next/image?url=<encode>&w=1200` -> l'URL CDN en direct.

    ⭐ Ce n'est pas de la cosmetique : `w=1200` **bride la largeur**. L'affiche
    fait 1 920 px de large ; une banniere recuperee a 1 200 y serait etiree."""
    if not url:
        return ""
    if "/_next/image" not in url:
        return url
    try:
        q = urllib.parse.urlparse(url).query
        vrai = urllib.parse.parse_qs(q).get("url", [""])[0]
        return vrai or url
    except Exception:                                       # noqa: BLE001
        return url


def image_de_serie(series_uuid: str, cache: Dict[str, str] = None) -> str:
    """L'illustration de SERIE, lue dans l'`og:image` de sa page publique.

    Rend "" si la page est illisible : l'appelant garde l'image de l'element.
    ⚠️ Le cache est passe par l'appelant — une meme serie ne se demande jamais
    deux fois dans un run."""
    sid = (series_uuid or "").strip()
    if not sid:
        return ""
    if cache is not None and sid in cache:
        return cache[sid]
    url = f"{BASE_SERIE}/{sid}"
    trouve = ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as rep:
            html = rep.read().decode("utf-8", "ignore")
        m = re.search(r'og:image"[^>]*content="([^"]+)"', html) \
            or re.search(r'content="([^"]+)"[^>]*property="og:image"', html)
        if m:
            # &amp; dans le HTML : sans ce remplacement, parse_qs echoue.
            trouve = deballer(m.group(1).replace("&amp;", "&"))
    except Exception as e:                                  # noqa: BLE001
        print(f"annonce : image de serie {sid[:8]} indisponible ({e}) — on "
              f"garde celle de l'element.", file=sys.stderr)
    if cache is not None:
        cache[sid] = trouve
    return trouve


def cover_commune(lignes: List[Dict[str, Any]]) -> str:
    """La couverture de la rarete COMMON d'un comic.

    ⚠️ Les 5 raretes d'un comic portent des couvertures DIFFERENTES (les
    variantes). Prendre « la premiere ligne venue » donnait une variante au
    hasard, qui changeait d'un mois a l'autre sans raison visible — le pire des
    bugs, celui qui a l'air de marcher. Repli : la 1re ligne qui porte une
    image, mieux que rien."""
    for l in lignes or []:
        if str(l.get("rarete") or "").upper() == "COMMON" and l.get("image"):
            return str(l["image"])
    for l in lignes or []:
        if l.get("image"):
            return str(l["image"])
    return ""


def visuel_de_tuile(d: Dict[str, Any], cache: Dict[str, str] = None) -> str:
    """L'image a poser dans une tuile de la mosaique.

    COLLECTIBLE -> l'illustration de SERIE (demande de Preda) · COMIC -> la
    couverture COMMUNE · et, si l'un ou l'autre manque, l'image de l'element."""
    if d.get("genre") == "comic":
        return cover_commune(d.get("lignes")) or d.get("image", "")
    return (image_de_serie(d.get("cle", ""), cache)
            or cover_commune(d.get("lignes"))
            or d.get("image", ""))
