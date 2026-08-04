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
import time
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
# Le nombre d'essais de LECTURE d'une page publique.
ESSAIS_PAGE = int(os.environ.get("ANNONCE_VISUEL_ESSAIS", "2"))


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


# 🔴 LES DEUX FAMILLES DE PAGES PUBLIQUES. Un comic ne vit PAS sous /series/ :
# `…/en/series/<uuid_de_comic>` rend un **404**. Confondre les deux, c'est
# perdre la couverture sans savoir pourquoi.
BASE_COMIC = os.environ.get("ANNONCE_VISUEL_BASE_COMIC",
                            "https://www.veve.me/collectibles/en/comics")


def image_publique(uuid: str, genre: str = "collectible",
                   cache: Dict[str, str] = None) -> str:
    """L'image officielle d'une serie, lue dans l'`og:image` de sa page.

    🔴 POURQUOI C'EST DEVENU LA SOURCE PRINCIPALE, ET PLUS UN COMPLEMENT :
    le run du 04/08 a montre que **le Sheet garde des references d'images
    MORTES** — `comic_cover.cd511719….4c50950d….full.jpeg` rend 403 sur toutes
    ses variantes. La page publique, elle, sert la couverture VIVANTE, et pour
    un comic c'est exactement celle de la rarete COMMON que Preda demande.
    ⭐⭐ **UNE URL STOCKEE EST UNE PHOTO DU PASSE ; UNE PAGE EST L'ETAT ACTUEL.**
    Quand les deux existent, c'est la page qui a raison.

    Rend "" si la page est illisible : l'appelant retombe sur le Sheet.
    ⚠️ Le cache est passe par l'appelant — une meme serie ne se demande jamais
    deux fois dans un run."""
    sid = (uuid or "").strip()
    if not sid:
        return ""
    cle = f"{genre}:{sid}"
    if cache is not None and cle in cache:
        return cache[cle]
    url = f"{BASE_COMIC if genre == 'comic' else BASE_SERIE}/{sid}"
    trouve = ""
    # ⚠️ DEUX ESSAIS, PAS UN. Un timeout unique coutait une tuile entiere :
    # la page repond en general, mais pas toujours du premier coup. Le
    # telechargement d'image, lui, reessayait deja 3 fois — **le maillon sans
    # reprise etait la LECTURE, celui qu'on avait ajoute en dernier.**
    derniere = None
    for essai in range(ESSAIS_PAGE):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as rep:
                html = rep.read().decode("utf-8", "ignore")
            m = re.search(r'og:image"[^>]*content="([^"]+)"', html) \
                or re.search(r'content="([^"]+)"[^>]*property="og:image"', html)
            if m:
                # &amp; dans le HTML : sinon parse_qs echoue.
                trouve = deballer(m.group(1).replace("&amp;", "&"))
            break
        except Exception as e:                              # noqa: BLE001
            derniere = e
            if essai + 1 < ESSAIS_PAGE:
                time.sleep(DELAI * (essai + 1))
    if derniere is not None and not trouve:
        print(f"annonce : page de {genre} {sid[:8]} indisponible ({derniere}) "
              f"apres {ESSAIS_PAGE} essais — on garde l'image du Sheet.",
              file=sys.stderr)
    if cache is not None:
        cache[cle] = trouve
    return trouve


def image_de_serie(series_uuid: str, cache: Dict[str, str] = None) -> str:
    """Alias historique — un collectible."""
    return image_publique(series_uuid, "collectible", cache)


# ═══════════════════════════════════════════════════════════════════════════
# 🖼️ LES BANNIERES DU CARROUSEL VeVe
# ═══════════════════════════════════════════════════════════════════════════
# La page d'accueil ne rend PAS les bannieres en HTML : elle embarque leur JSON
# dans les donnees Next.js. Chaque banniere y porte tout ce qu'il faut :
#
#   {"id":…, "position":1, "isBackup":false,
#    "startDate":"2026-07-29T…", "endDate":"2026-08-09T…",
#    "url":"https://www.veve.me/collectibles/en/series/<uuid>",
#    "desktopMedia":{"url":"https://…/marketing_window_web.<id>.<img>.full.jpeg"}}
#
# ⭐⭐⭐ LA BANNIERE EST DECORATIVE — TRANCHE PAR PREDA (04/08).
# J'avais bati un archivage quotidien du carrousel pour retrouver « la banniere
# affichee pendant le mois annonce ». Correct, et **surdimensionne** : cette
# image ne porte aucune information, elle remplit un bandeau. Preda a coupe
# court — **on prend une banniere VIVANTE qui mene vers un collectible.**
# ⭐⭐ LE COUT D'UN MECANISME SE JUGE A CE QU'IL PORTE, PAS A SON ELEGANCE : un
# historique persistant, un etat commite chaque jour et une requete quotidienne
# pour choisir un fond d'image, c'est payer un entrepot pour ranger un poster.
# ⛔ Ne pas reintroduire l'archivage sans une raison NEUVE.
#
# Le seul filtre qui reste a du sens : **la cible**. Les bannieres du carrousel
# pointent vers des series, mais aussi vers le blog ou le parrainage — celles-la
# ne montrent pas de piece, elles montrent du texte.

ACCUEIL = os.environ.get("ANNONCE_VISUEL_ACCUEIL",
                         "https://www.veve.me/collectibles/en")

# Un bloc de banniere, dans le JSON aplati de la page.
_BLOC = re.compile(
    r'\{"id":"(?P<id>[0-9a-f-]{36})","title":.*?'
    r'"position":(?P<position>\d+),"isBackup":(?P<backup>\w+),'
    r'"url":"(?P<cible>[^"]*)".*?'
    r'"desktopMedia":\{"url":"(?P<image>[^"]+)"\}', re.S)
_DATES = re.compile(r'"startDate":"([^"]*)","endDate":"([^"]*)"')


def bannieres(html: str = "") -> List[Dict[str, Any]]:
    """Les bannieres du carrousel, dans l'ordre du site.

    Rend [] si la page est illisible : l'affiche sortira avec un bandeau
    sombre, elle ne echouera pas."""
    if not html:
        try:
            req = urllib.request.Request(ACCUEIL, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as rep:
                html = rep.read().decode("utf-8", "ignore")
        except Exception as e:                              # noqa: BLE001
            print(f"annonce : carrousel VeVe illisible ({e}) — pas de "
                  f"banniere relevee ce passage.", file=sys.stderr)
            return []
    # Le JSON est echappe dans un `self.__next_f.push([1,"…"])` : on desechappe
    # une fois, sinon aucun motif ne matche.
    brut = html.replace('\\"', '"').replace("\\\\", "\\")
    dates = _DATES.findall(brut)
    out: List[Dict[str, Any]] = []
    for i, m in enumerate(_BLOC.finditer(brut)):
        debut, fin = (dates[i] if i < len(dates) else ("", ""))
        out.append({
            "id": m.group("id"),
            "position": int(m.group("position")),
            "backup": m.group("backup") == "true",
            "cible": m.group("cible"),
            "image": m.group("image"),
            "debut": debut[:10],
            "fin": fin[:10],
        })
    return out


# Les cibles qui montrent une PIECE. ⛔ Le blog et les marques n'en montrent
# pas : une banniere « programme de parrainage » est une affiche de texte.
CIBLES_PIECE = ("/series/", "/collectibles/", "/crafts/", "/artworks/")


def banniere_decorative(liste: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """UNE banniere vivante qui mene vers un collectible — la premiere du
    carrousel qui remplit cette condition.

    ⭐ Le critere tient en une phrase et se verifie a l'oeil : **elle montre une
    piece**. Pas de date, pas d'historique, pas d'etat a maintenir.
    ⛔ Les `isBackup` (la reserve de VeVe) restent ecartees : ce sont des
    bouche-trous, pas des visuels de campagne.
    Rend {} si le carrousel est illisible ou n'a que du blog — l'affiche sortira
    avec un bandeau sombre, elle n'echouera pas."""
    liste = bannieres() if liste is None else liste
    candidates = [b for b in liste
                  if not b.get("backup")
                  and any(c in (b.get("cible") or "") for c in CIBLES_PIECE)]
    if not candidates:
        return {}
    return min(candidates, key=lambda b: int(b.get("position", 99)))


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
    couverture COMMUNE · et, si l'un ou l'autre manque, l'image de l'element.

    🔴 QUAND LES TROIS SOURCES SONT VIDES, ON LE DIT AVEC LE NOM DE LA SERIE.
    Le 1er run reel a sorti « 3 case(s) en repli (banniere, comic, tuile_2) » :
    exact, mais inexploitable — on ne savait NI quelle serie NI quelle source
    avait manque. ⭐⭐ **Un compteur d'echecs sans identite ne se repare pas :
    il se contemple.** Une case vide nommee se corrige en une minute."""
    genre = "comic" if d.get("genre") == "comic" else "collectible"
    # ⭐ LA PAGE D'ABORD, LE SHEET ENSUITE. C'est l'inverse de ma 1re version :
    # le Sheet est un cache, et un cache d'URL perime en silence.
    page = image_publique(d.get("cle", ""), genre, cache)
    u = page or cover_commune(d.get("lignes")) or d.get("image", "")
    if not u:
        print(f"⚠️ visuel : aucune image pour « {d.get('nom', '?')} » "
              f"(serie {str(d.get('cle', ''))[:8]}) — ni page de serie, ni "
              f"image d'element.", file=sys.stderr)
    elif not page:
        print(f"visuel : « {d.get('nom', '?')} » retombe sur le Sheet "
              f"(page publique muette).", flush=True)
    return u
