# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : outils/calendrier/visuels.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""🖼️ LES VISUELS DE SERIE : telechargement, cache disque, encodage pour le SVG.

CE QUE CE MODULE PROTEGE
------------------------
1. **La source.** Les visuels sont sur le CDN CloudFront de VeVe. Un run de
   calendrier ne doit pas retelecharger 150 images : **tout passe par un cache
   disque** (`data/calendrier_visuels/`), la cle est le SHA-1 de l'URL. Un
   deuxieme run le meme jour ne fait aucune requete.
2. **Le run.** Une image manquante (404, coupure, URL vide) ne fait JAMAIS
   echouer le calendrier : la vignette tombe sur un aplat de repli et le module
   le DIT dans le journal. Un calendrier a une case grise vaut mieux qu'un
   calendrier jamais produit.
3. ⚠️ **Le User-Agent.** Lecon deja payee sur GoChain : un `User-Agent` Python
   par defaut se fait renvoyer 403 par certains fronts. On en pose un explicite.

⚠️ WEBP → PNG, OBLIGATOIRE
--------------------------
VeVe sert du `.webp`. **cairosvg ne sait pas decoder le webp** : une image webp
collee dans le SVG donne une case VIDE, sans erreur — exactement le genre de
repli silencieux qui passe la relecture. On decode donc avec Pillow et on
reencode en PNG avant de l'incruster.
"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import time
import urllib.error
import urllib.request
from typing import Optional, Tuple

from PIL import Image

# Le cache vit a cote des autres etats du depot.
CACHE_DEFAUT = os.path.join("data", "calendrier_visuels")

# ⚠️ Un User-Agent explicite : le defaut de urllib (`Python-urllib/3.x`) est
# refuse par certains fronts (403). Voir [[scrapeur-veve-gochain]].
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36 ScrapeurVeVe-calendrier/1.0")

# Cote max stocke en cache. Une vignette fait ~150 px sur le rendu 1080 ;
# 480 px laisse de la marge pour un rendu 2x sans garder des images de 1 Mo.
COTE_CACHE = 480


class Journal:
    """Compteur de ce qui s'est passe — pour que le run le DISE a la fin."""

    def __init__(self) -> None:
        self.caches = 0
        self.telecharges = 0
        self.echecs: list = []

    def resume(self) -> str:
        txt = "visuels : %d en cache, %d telecharges" % (self.caches, self.telecharges)
        if self.echecs:
            txt += ", %d ECHECS (%s)" % (
                len(self.echecs), ", ".join(u[:60] for u in self.echecs[:3]))
        return txt


def _chemin_cache(url: str, cache: str) -> str:
    return os.path.join(cache, hashlib.sha1(url.encode("utf-8")).hexdigest() + ".png")


def _telecharger(url: str, essais: int = 3, pause: float = 1.5) -> bytes:
    """GET avec backoff. Leve la derniere erreur si les essais sont epuises."""
    derniere: Optional[Exception] = None
    for tentative in range(essais):
        try:
            requete = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(requete, timeout=25) as reponse:
                return reponse.read()
        except (urllib.error.URLError, OSError) as err:      # reseau, 4xx, 5xx
            derniere = err
            if tentative + 1 < essais:
                time.sleep(pause * (tentative + 1))
    raise derniere if derniere else RuntimeError("telechargement impossible")


def charger(url: str, cache: str = CACHE_DEFAUT,
            journal: Optional[Journal] = None) -> Optional[Image.Image]:
    """L'image d'une URL, depuis le cache ou le reseau. `None` si indisponible.

    Ne leve jamais : un visuel manquant est un incident de rendu, pas un echec
    de run (cf. l'en-tete du module).
    """
    if not url:
        return None
    os.makedirs(cache, exist_ok=True)
    chemin = _chemin_cache(url, cache)
    if os.path.exists(chemin):
        if journal:
            journal.caches += 1
        try:
            return Image.open(chemin).convert("RGBA")
        except Exception:
            os.remove(chemin)                 # cache corrompu : on refait
    try:
        brut = _telecharger(url)
        image = Image.open(io.BytesIO(brut)).convert("RGBA")
        image.thumbnail((COTE_CACHE, COTE_CACHE), Image.LANCZOS)
        image.save(chemin, "PNG")             # ⚠️ webp → PNG : cairosvg exige PNG
        if journal:
            journal.telecharges += 1
        return image
    except Exception:
        if journal:
            journal.echecs.append(url)
        return None


# ------------------------------------------------------------------ geometrie

def recadrer(image: Image.Image, largeur: int, hauteur: int) -> Image.Image:
    """Recadrage « couvrir » : remplit la boite, deborde, centre.

    ⚠️ Fait ici et pas via `preserveAspectRatio="… slice"` : le comportement du
    slice varie d'un moteur SVG a l'autre, un recadrage Pillow est le meme
    partout et donne un resultat identique a chaque run.
    """
    largeur, hauteur = max(1, int(largeur)), max(1, int(hauteur))
    facteur = max(largeur / image.width, hauteur / image.height)
    inter = image.resize((max(1, round(image.width * facteur)),
                          max(1, round(image.height * facteur))), Image.LANCZOS)
    gauche = (inter.width - largeur) // 2
    haut = (inter.height - hauteur) // 2
    return inter.crop((gauche, haut, gauche + largeur, haut + hauteur))


def tenir_dans(image: Image.Image, largeur: int, hauteur: int) -> Image.Image:
    """Redimensionnement « contenir » : l'image entiere tient dans la boite."""
    copie = image.copy()
    copie.thumbnail((max(1, int(largeur)), max(1, int(hauteur))), Image.LANCZOS)
    return copie


def uri(image: Image.Image) -> str:
    """`data:image/png;base64,…` — le SVG produit est un fichier autonome.

    Un SVG qui pointerait vers des fichiers voisins se briserait des qu'on le
    deplace ; ici tout voyage dans le fichier.
    """
    tampon = io.BytesIO()
    image.save(tampon, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(tampon.getvalue()).decode("ascii")


def teinte_dominante(image: Image.Image) -> Tuple[int, int, int]:
    """La couleur moyenne, un peu saturee — sert de fond derriere une vignette.

    Une couverture de comic posee sur un aplat tire de l'image elle-meme s'y
    fond mieux que sur un gris fixe, et chaque case garde son ambiance.
    """
    petite = image.convert("RGB").resize((16, 16), Image.LANCZOS)
    pixels = list(petite.getdata())
    n = len(pixels)
    moyenne = [sum(p[i] for p in pixels) / n for i in range(3)]
    # On assombrit : le fond doit rester un fond, jamais concurrencer l'image.
    return tuple(max(0, min(255, int(c * 0.55))) for c in moyenne)  # type: ignore
