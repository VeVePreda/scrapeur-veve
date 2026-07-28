# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : outils/calendrier/rendu.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""🖌️ LE SVG DU CALENDRIER : entete, grille 7 × N, pied promotionnel.

CE QUE LE VISUEL DOIT FAIRE (cahier des charges Preda)
------------------------------------------------------
Ce n'est pas un tableau de bord, c'est un **outil promotionnel** : il sera
telecharge et repartage. Trois consequences tenues ici :
  * le SITE et le DISCORD sont sur le visuel, en clair, lisibles meme
    recompresses par un reseau social ;
  * il se lit **sans legende** — une case = un jour = les visuels de serie ;
  * **un seul format : le carre 1080** (decision du 28/07). Le meme fichier sert
    au post du samedi et a la newsletter.

L'HARMONIE AVEC LES NEWSLETTERS
-------------------------------
La grille reprend le vocabulaire visuel de `newsletters-v4/` : cartes a coins
arrondis **cernees d'un filet `--line`**, fonds `--card`, degrade de marque en
entete. C'est ce filet, plus que la couleur, qui fait « meme maison ».

LES CHOIX DE MISE EN PAGE, ET POURQUOI
--------------------------------------
1. **Un mercredi porte 20 a 33 series** (le Comic Day). Les afficher toutes est
   impossible ; n'en montrer qu'une serait mentir. D'ou l'**eventail de 4
   couvertures + le compteur `×24`**.
2. **Le fond d'une case est tire de son image** (teinte moyenne assombrie) : une
   couverture verticale dans une case carree laisse des bords ; les remplir d'un
   gris fixe fait 35 cases mortes.
3. **Aucun nom de serie dans les cases illustrees.** A 145 px de large, un titre
   de comic est illisible et fait du bruit. La case montre, elle ne raconte pas.
4. **Le mois occupe la pastille en haut a droite** (a la place du bouton Discord,
   qui reste en pied) : c'est l'information de reperage, pas un appel a l'action.

⚠️ PAS DE FILTRE SVG ICI
------------------------
`feDropShadow` & co. sont mal ou pas rendus par cairosvg selon les versions — et
quand un filtre n'est pas rendu, **il ne casse rien, il disparait**. Les ombres
sont donc des rectangles decales, qui, eux, sont rendus partout.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import math
import os
from typing import Dict, List, Optional, Tuple

from . import donnees as D
from . import themes as T
from . import visuels as V

DOSSIER_LOGOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logos")

# ⭐ Tout texte dessine est enregistre ici (famille, contenu) pour que
# `polices.verifier_glyphes` puisse refuser un visuel contenant un caractere que
# la police ne sait pas tracer. Voir l'histoire de la fleche U+2192.
GLYPHES_VUS: List[Tuple[str, str]] = []


# --------------------------------------------------------------------- outils

def echapper(txt: str) -> str:
    return (str(txt).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def texte(x, y, contenu, *, police, taille, couleur, poids="normal",
          ancre="start", lettrage=0.0, opacite=1.0) -> str:
    GLYPHES_VUS.append((police, str(contenu)))
    extra = ""
    if lettrage:
        extra += ' letter-spacing="%.2f"' % lettrage
    if opacite != 1.0:
        extra += ' opacity="%.3f"' % opacite
    return ('<text x="%.2f" y="%.2f" font-family="%s" font-size="%.2f" '
            'font-weight="%s" fill="%s" text-anchor="%s"%s>%s</text>'
            % (x, y, police, taille, poids, couleur, ancre, extra, echapper(contenu)))


def rect(x, y, w, h, fill, rayon=0.0, opacite=1.0, contour=None, epaisseur=0.0) -> str:
    extra = ""
    if opacite != 1.0:
        extra += ' opacity="%.3f"' % opacite
    if contour:
        extra += ' stroke="%s" stroke-width="%.2f"' % (contour, epaisseur)
    return ('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="%.2f" '
            'ry="%.2f" fill="%s"%s/>' % (x, y, w, h, rayon, rayon, fill, extra))


def image(x, y, w, h, uri, clip=None, transform=None, opacite=1.0) -> str:
    extra = ""
    if clip:
        extra += ' clip-path="url(#%s)"' % clip
    if transform:
        extra += ' transform="%s"' % transform
    if opacite != 1.0:
        extra += ' opacity="%.3f"' % opacite
    return ('<image x="%.2f" y="%.2f" width="%.2f" height="%.2f" '
            'xlink:href="%s" href="%s"%s/>' % (x, y, w, h, uri, uri, extra))


def hexa(rvb: Tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rvb


def logo(th: T.Theme):
    """Le logo de la marque, ou None s'il n'a pas ete livre.

    Sans logo, l'entete tombe sur une pastille monogramme : degrade, pas trou.
    """
    chemin = os.path.join(DOSSIER_LOGOS, th.logo)
    if not os.path.exists(chemin):
        return None
    from PIL import Image
    return Image.open(chemin).convert("RGBA")


# ------------------------------------------------------------------ geometrie

class Gabarit:
    """Toutes les cotes du visuel, calculees une fois pour la taille demandee."""

    def __init__(self, cote: int, lignes: int, th: T.Theme):
        self.W = self.H = cote
        self.k = cote / 1080.0                                # facteur d'echelle
        self.lignes = lignes
        self.marge = 20 * self.k
        self.h_entete = 196 * self.k
        self.h_barre = 44 * self.k
        self.h_pied = 50 * self.k
        self.gap = th.gap * self.k
        self.grille_y = self.h_entete + self.h_barre + 10 * self.k
        bas = self.H - self.h_pied - 10 * self.k
        self.grille_h = bas - self.grille_y
        self.grille_x = self.marge
        self.grille_w = self.W - 2 * self.marge
        self.case_w = (self.grille_w - 6 * self.gap) / 7.0
        self.case_h = (self.grille_h - (lignes - 1) * self.gap) / lignes

    def case(self, colonne: int, ligne: int) -> Tuple[float, float]:
        return (self.grille_x + colonne * (self.case_w + self.gap),
                self.grille_y + ligne * (self.case_h + self.gap))


# --------------------------------------------------------------------- entete

def _fond_entete(g: Gabarit, th: T.Theme, vignettes: List) -> str:
    h = g.h_entete
    morceaux = [rect(0, 0, g.W, h, th.accent2),
                '<rect x="0" y="0" width="%.2f" height="%.2f" fill="url(#marque)"/>'
                % (g.W, h)]
    if th.entete == "montage" and vignettes:
        largeur = (g.W + 40) / max(1, len(vignettes))
        for i, img in enumerate(vignettes):
            decoupe = V.recadrer(img, int(largeur) + 2, int(h))
            # 0.22 et pas davantage : au-dela, les titres des couvertures se
            # mettent a concurrencer le titre du calendrier. C'est une TEXTURE.
            morceaux.append(image(i * largeur - 20, 0, largeur + 2, h,
                                  V.uri(decoupe), clip="clip_entete", opacite=0.22))
    elif th.entete == "trame":
        pas, lignes = 30 * g.k, []
        x = 0.0
        while x < g.W:
            lignes.append('<line x1="%.1f" y1="0" x2="%.1f" y2="%.1f"/>' % (x, x, h))
            x += pas
        y = 0.0
        while y < h:
            lignes.append('<line x1="0" y1="%.1f" x2="%.1f" y2="%.1f"/>' % (y, g.W, y))
            y += pas
        morceaux.append('<g stroke="%s" stroke-width="1" opacity="0.14">%s</g>'
                        % (th.accent3, "".join(lignes)))
    # voile bas : le titre doit poser sur du sombre, quelles que soient les images
    morceaux.append('<rect x="0" y="0" width="%.2f" height="%.2f" fill="url(#voile_entete)"/>'
                    % (g.W, h))
    return "".join(morceaux)


def entete(g: Gabarit, th: T.Theme, periode: str, vignettes: List) -> str:
    morceaux = [_fond_entete(g, th, vignettes)]
    gx = g.marge + 8 * g.k

    # --- bloc marque : logo + nom + site
    cote = 76 * g.k
    ly = 20 * g.k
    marque = logo(th)
    if marque is not None:
        morceaux.append('<clipPath id="clip_logo"><rect x="%.2f" y="%.2f" '
                        'width="%.2f" height="%.2f" rx="%.2f" ry="%.2f"/></clipPath>'
                        % (gx, ly, cote, cote, 20 * g.k, 20 * g.k))
        morceaux.append(image(gx, ly, cote, cote,
                              V.uri(V.recadrer(marque, int(cote * 2), int(cote * 2))),
                              clip="clip_logo"))
    else:
        morceaux.append(rect(gx, ly, cote, cote, th.accent, rayon=20 * g.k))
    morceaux.append(rect(gx, ly, cote, cote, "none", rayon=20 * g.k,
                         contour="#ffffff", epaisseur=2 * g.k, opacite=0.22))

    morceaux.append(texte(gx + cote + 16 * g.k, ly + 34 * g.k, th.marque.upper(),
                          police=th.police_titre, taille=30 * g.k, couleur=th.encre,
                          poids="bold", lettrage=0.5 * g.k))
    morceaux.append(texte(gx + cote + 16 * g.k, ly + 60 * g.k, th.site,
                          police=th.police_texte, taille=17 * g.k,
                          couleur=th.encre, poids="bold", opacite=0.72))

    # mention legale : petite, tout en haut a droite, hors du chemin du titre
    morceaux.append(texte(g.W - g.marge - 8 * g.k, ly + 16 * g.k, th.mention,
                          police=th.police_texte, taille=12 * g.k,
                          couleur=th.encre, ancre="end", opacite=0.62))

    # --- titre + periode, sur la meme ligne de base : le titre pousse a gauche,
    # la periode tient la droite. L'entete respire au lieu d'empiler 4 lignes.
    y_titre = g.h_entete - 34 * g.k
    morceaux.append(texte(gx, y_titre, th.titre, police=th.police_titre,
                          taille=50 * g.k, couleur=th.encre, poids="bold",
                          lettrage=th.lettrage_titre * g.k))
    morceaux.append(texte(g.W - g.marge - 8 * g.k, y_titre - 2 * g.k, periode,
                          police=th.police_texte, taille=22 * g.k,
                          couleur=th.accent3, poids="bold", ancre="end"))

    # filet degrade : la couture entre l'entete et la grille
    morceaux.append('<rect x="0" y="%.2f" width="%.2f" height="%.2f" '
                    'fill="url(#marque)"/>' % (g.h_entete - 4 * g.k, g.W, 4 * g.k))
    return "".join(morceaux)


def barre(g: Gabarit, th: T.Theme, total: int, mois: str) -> str:
    """Compteur a gauche, MOIS a droite.

    ⚠️ La pastille de droite portait le lien Discord ; Preda l'a rendue au mois
    (28/07) — le Discord reste en pied, ou il ne concurrence pas le reperage.
    """
    lg = T.langue_de(th)
    y = g.h_entete
    cy = y + g.h_barre * 0.66
    morceaux = [rect(0, y, g.W, g.h_barre, th.fond)]
    morceaux.append(texte(g.marge + 8 * g.k, cy, "%d" % total,
                          police=th.police_titre, taille=26 * g.k,
                          couleur=th.accent, poids="bold"))
    decalage = (10 + 15 * len(str(total))) * g.k
    morceaux.append(texte(g.marge + 8 * g.k + decalage, cy - 1 * g.k,
                          T.MOTS[lg]["drops"], police=th.police_texte,
                          taille=17 * g.k, couleur=th.encre_faible, poids="bold",
                          lettrage=1.6 * g.k))

    larg = (46 + 13.5 * len(mois)) * g.k
    px = g.W - g.marge - 8 * g.k - larg
    hp = g.h_barre * 0.66
    morceaux.append(rect(px, y + (g.h_barre - hp) / 2, larg, hp, th.accent2,
                         rayon=hp / 2))
    morceaux.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="%.2f" '
                    'ry="%.2f" fill="url(#marque)" opacity="0.9"/>'
                    % (px, y + (g.h_barre - hp) / 2, larg, hp, hp / 2, hp / 2))
    morceaux.append(texte(px + larg / 2, cy + 1 * g.k, mois,
                          police=th.police_titre, taille=21 * g.k,
                          couleur="#ffffff", poids="bold", ancre="middle",
                          lettrage=1.2 * g.k))
    return "".join(morceaux)


# ---------------------------------------------------------------------- cases

def _couleur_serie(cle: str) -> str:
    """Une couleur sombre stable, tiree du nom de la serie.

    Deux runs donnent la meme couleur pour la meme serie : la case ne
    « clignote » pas d'une semaine a l'autre.
    """
    import colorsys
    teinte = (int(hashlib.sha1(cle.encode("utf-8")).hexdigest()[:6], 16) % 360) / 360.0
    r, v, b = colorsys.hls_to_rgb(teinte, 0.24, 0.42)
    return "#%02x%02x%02x" % (int(r * 255), int(v * 255), int(b * 255))


def _couper(titre: str, largeur_px: float, taille: float, max_lignes: int,
            largeur_glyphe: float) -> List[str]:
    """Decoupe d'un titre en lignes.

    ⚠️ `largeur_glyphe` vient du THEME : une condensee tient en ~0,42 em par
    caractere, une monospace en ~0,62. Avec une valeur unique, le titre debordait
    de la case — et un debordement, dans un `clip-path`, se voit comme une phrase
    coupee net, pas comme une erreur.
    """
    par_ligne = max(5, int(largeur_px / (taille * largeur_glyphe)))
    lignes: List[str] = []
    courante = ""
    for mot in titre.split():
        while len(mot) > par_ligne:                 # mot plus long que la case
            if courante:
                lignes.append(courante)
                courante = ""
            lignes.append(mot[:par_ligne - 1] + "-")
            mot = mot[par_ligne - 1:]
            if len(lignes) >= max_lignes:
                return lignes[:max_lignes]
        essai = (courante + " " + mot).strip()
        if len(essai) <= par_ligne:
            courante = essai
        else:
            if courante:
                lignes.append(courante)
            courante = mot
            if len(lignes) >= max_lignes:
                return lignes[:max_lignes]
    if courante and len(lignes) < max_lignes:
        lignes.append(courante)
    return lignes[:max_lignes]


def carte_texte(g: Gabarit, th: T.Theme, x, y, w, h, serie, rayon: float,
                avec_pastille: bool) -> str:
    """La vignette de repli quand la SERIE N'A PAS DE VISUEL.

    ⚠️ Ce n'est pas un cas rare : **9 834 comics de mercredi sur 11 870 n'ont
    aucun `image_url`** dans le Sheet (l'enrichissement ne remplit plus la
    couverture des drops `RESERVATION` depuis 2025). Sans ce repli, un mercredi
    de Comic Day devient un trou noir — et un trou noir, sur un visuel
    promotionnel, se voit plus qu'une case moche.

    La carte affiche donc ce qu'on SAIT : le nom de la serie et son licencieur.
    """
    couleur = _couleur_serie(serie.cle or serie.nom)
    morceaux = [rect(x, y, w, h, couleur, rayon=rayon),
                rect(x, y, w, 4 * g.k, th.accent, opacite=0.8)]

    # ⚠️ Le texte doit eviter les DEUX coins deja occupes : le chiffre du jour
    # d'un cote, la pastille de comptage de l'autre.
    haut_pris = 64 * g.k if th.position_jour.startswith("haut") else 36 * g.k
    bas_pris = 64 * g.k if th.position_jour.startswith("bas") else 36 * g.k
    zone_y, zone_h = y + haut_pris, h - haut_pris - bas_pris

    taille = min(15 * g.k, max(10 * g.k, w / 10.0))
    lignes = _couper(serie.nom or "?", w - 18 * g.k, taille, 3, th.largeur_glyphe)
    depart = zone_y + zone_h / 2 - (len(lignes) - 1) * taille * 0.58 + taille * 0.10
    for i, ligne in enumerate(lignes):
        morceaux.append(texte(x + w / 2, depart + i * taille * 1.16, ligne,
                              police=th.police_texte, taille=taille,
                              couleur="#ffffff", poids="bold", ancre="middle"))
    # ⚠️ Le licencieur ne s'affiche QUE s'il reste de la place : quand la case
    # porte deja une pastille de comptage (un Comic Day), il venait se coller
    # dessous et les deux se marchaient dessus.
    if serie.licensor and not avec_pastille:
        largeur_max = int((w - 20 * g.k) / (11 * g.k * (th.largeur_glyphe + 0.08)))
        morceaux.append(texte(x + w / 2, zone_y + zone_h - 2 * g.k,
                              serie.licensor.upper()[:largeur_max],
                              police=th.police_texte, taille=11 * g.k,
                              couleur="#ffffff", ancre="middle", opacite=0.62))
    return "".join(morceaux)


def _eventail(g: Gabarit, th: T.Theme, x, y, w, h, images: List) -> str:
    """2 a 4 couvertures en eventail — la reponse au Comic Day.

    Dessinees du bord vers le centre pour que la couverture centrale soit
    AU-DESSUS : c'est elle qu'on lit en premier.
    """
    n = len(images)
    angles = {2: (-7, 7), 3: (-10, 0, 10), 4: (-13, -4.5, 4.5, 13)}[n]
    ecarts = {2: (-0.115, 0.115), 3: (-0.155, 0.0, 0.155),
              4: (-0.20, -0.068, 0.068, 0.20)}[n]
    boite_w, boite_h = w * 0.56, h * 0.64
    cx, cy = x + w / 2, y + h / 2 + h * 0.03
    ordre = sorted(range(n), key=lambda i: -abs(ecarts[i]))   # bords d'abord
    morceaux = []
    for i in ordre:
        img = V.tenir_dans(images[i], int(boite_w), int(boite_h))
        iw, ih = img.width, img.height
        px, py = cx + ecarts[i] * w - iw / 2, cy - ih / 2
        rot = 'rotate(%.2f %.2f %.2f)' % (angles[i], cx + ecarts[i] * w, cy)
        morceaux.append('<g transform="%s">' % rot)
        morceaux.append(rect(px + 2.5 * g.k, py + 3 * g.k, iw, ih, "#000000",
                             rayon=2 * g.k, opacite=0.45))     # ombre portee
        morceaux.append(image(px, py, iw, ih, V.uri(img)))
        morceaux.append(rect(px, py, iw, ih, "none", contour="#ffffff",
                             epaisseur=1.2 * g.k, opacite=0.5))
        morceaux.append("</g>")
    return "".join(morceaux)


def case(g: Gabarit, th: T.Theme, x, y, jour: D.Jour, imgs: Dict[str, object],
         aujourdhui: _dt.date, indice: int) -> str:
    lg = T.langue_de(th)
    w, h, r = g.case_w, g.case_h, th.rayon * g.k
    cid = "case%d" % indice
    morceaux = ['<clipPath id="%s"><rect x="%.2f" y="%.2f" width="%.2f" '
                'height="%.2f" rx="%.2f" ry="%.2f"/></clipPath>'
                % (cid, x, y, w, h, r, r)]

    disponibles = [imgs[s.cle] for s in jour.series if imgs.get(s.cle) is not None]
    sans_image = [s for s in jour.series if imgs.get(s.cle) is None]

    # fond : teinte de la 1re image si on en a une, sinon la case vide du theme
    fond = hexa(V.teinte_dominante(disponibles[0])) if disponibles else th.fond_case
    morceaux.append(rect(x, y, w, h, fond, rayon=r))

    morceaux.append('<g clip-path="url(#%s)">' % cid)
    if len(disponibles) >= 2:
        morceaux.append(_eventail(g, th, x, y, w, h, disponibles[:4]))
    elif len(disponibles) == 1:
        decoupe = V.recadrer(disponibles[0], int(w) + 2, int(h) + 2)  # type: ignore[arg-type]
        morceaux.append(image(x, y, w + 2, h + 2, V.uri(decoupe)))
    elif sans_image:
        morceaux.append(carte_texte(g, th, x, y, w, h, sans_image[0], r,
                                    avec_pastille=jour.nb >= 2))

    morceaux.append("</g>")

    # ⭐ le filet : c'est lui qui fait « meme maison » que les newsletters.
    # Pose APRES l'image, sinon l'image le recouvre.
    morceaux.append(rect(x + 0.75 * g.k, y + 0.75 * g.k, w - 1.5 * g.k,
                         h - 1.5 * g.k, "none", rayon=r, contour=th.ligne,
                         epaisseur=1.5 * g.k, opacite=0.9 if jour.vide else 0.55))

    # --- chiffre du jour, dans une PASTILLE
    # ⚠️ Le chiffre etait pose a meme la couverture, avec un simple voile en
    # degrade : sur une case chargee (un titre de comic, du texte blanc), il
    # devenait illisible sans qu'aucun contrôle ne puisse s'en apercevoir. La
    # pastille opaque est la seule facon d'avoir toujours le meme contraste.
    nom_jour = T.JOURS[lg][jour.date.weekday()]
    pw, ph = 54 * g.k, 50 * g.k
    if th.position_jour == "bas-gauche":
        px, py = x + 8 * g.k, y + h - 8 * g.k - ph
    elif th.position_jour == "haut-gauche":
        px, py = x + 8 * g.k, y + 8 * g.k
    else:                                                     # haut-droite
        px, py = x + w - 8 * g.k - pw, y + 8 * g.k
    if not jour.vide:
        morceaux.append(rect(px, py, pw, ph, th.fond, rayon=r * 0.62, opacite=0.82))
        morceaux.append(rect(px, py, pw, ph, "none", rayon=r * 0.62,
                             contour=th.encre, epaisseur=1 * g.k, opacite=0.22))
    pale = th.encre if not jour.vide else th.encre_faible
    morceaux.append(texte(px + pw / 2, py + 17 * g.k, nom_jour,
                          police=th.police_texte, taille=13 * g.k, couleur=pale,
                          poids="bold", ancre="middle", lettrage=1.0 * g.k,
                          opacite=0.85))
    morceaux.append(texte(px + pw / 2, py + 43 * g.k, "%02d" % jour.date.day,
                          police=th.police_titre, taille=30 * g.k, couleur=pale,
                          poids="bold", ancre="middle"))

    # --- compteur (Comic Day compris), a l'oppose du chiffre du jour
    if jour.nb >= 2:
        libelle = ("%s ×%d" % (T.MOTS[lg]["comic_day"], jour.nb) if jour.nb >= 8
                   else "×%d" % jour.nb)
        larg = (14 + 7.4 * len(libelle)) * g.k
        bx = x + 9 * g.k
        by = (y + h - 29 * g.k) if th.position_jour.startswith("haut") else (y + 9 * g.k)
        morceaux.append(rect(bx, by, larg, 21 * g.k, th.accent, rayon=10.5 * g.k))
        morceaux.append(texte(bx + larg / 2, by + 15 * g.k, libelle,
                              police=th.police_texte, taille=13 * g.k,
                              couleur="#ffffff", poids="bold", ancre="middle"))

    # --- le jour meme : un contour, pas un aplat (l'image doit rester lisible)
    if jour.date == aujourdhui:
        morceaux.append(rect(x + 1.5 * g.k, y + 1.5 * g.k, w - 3 * g.k, h - 3 * g.k,
                             "none", rayon=r, contour=th.or_, epaisseur=3 * g.k))
    return "".join(morceaux)


# ----------------------------------------------------------------------- pied

def pied(g: Gabarit, th: T.Theme) -> str:
    """Site a gauche, Discord a droite. RIEN au centre.

    ⚠️ La date de generation y figurait ; Preda l'a retiree (28/07). Sur un
    visuel qu'on repartage, elle datait le fichier sans rien apporter au lecteur.
    """
    y = g.H - g.h_pied
    cy = y + g.h_pied * 0.64
    return "".join([
        rect(0, y, g.W, g.h_pied, th.fond),
        '<rect x="0" y="%.2f" width="%.2f" height="%.2f" fill="url(#marque)"/>'
        % (y, g.W, 3 * g.k),
        texte(g.marge + 8 * g.k, cy, th.site.upper(), police=th.police_titre,
              taille=23 * g.k, couleur=th.encre, poids="bold", lettrage=1.0 * g.k),
        texte(g.W - g.marge - 8 * g.k, cy, th.discord.upper(),
              police=th.police_titre, taille=23 * g.k, couleur=th.accent,
              poids="bold", ancre="end", lettrage=1.0 * g.k)])


# ------------------------------------------------------------------ assemblage

def defs(g: Gabarit, th: T.Theme) -> str:
    return (
        '<defs>'
        # le degrade de marque : entete, filets, pastille du mois
        '<linearGradient id="marque" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="%s"/><stop offset="0.55" stop-color="%s"/>'
        '<stop offset="1" stop-color="%s"/></linearGradient>'
        # ⚠️ 0.50 en haut, pas 0.18 : le nom de la marque se posait sur des
        # couvertures trop lisibles et devenait illisible a son tour.
        '<linearGradient id="voile_entete" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="%s" stop-opacity="0.50"/>'
        '<stop offset="0.55" stop-color="%s" stop-opacity="0.72"/>'
        '<stop offset="1" stop-color="%s" stop-opacity="0.94"/></linearGradient>'
        '<clipPath id="clip_entete"><rect x="0" y="0" width="%.2f" height="%.2f"/>'
        '</clipPath></defs>'
        % (th.accent2, th.accent, th.accent3, th.fond, th.fond, th.fond,
           g.W, g.h_entete))


def construire(calendrier: Dict[_dt.date, D.Jour], th: T.Theme, *,
               aujourdhui: _dt.date, cote: int = 1080,
               cache: str = V.CACHE_DEFAUT,
               journal: Optional[V.Journal] = None,
               controler_glyphes: bool = True) -> str:
    """Le SVG complet, images incrustees : un fichier autonome."""
    del GLYPHES_VUS[:]
    jours = sorted(calendrier)
    lignes = max(1, math.ceil(len(jours) / 7))
    g = Gabarit(cote, lignes, th)

    # Un seul telechargement par serie, meme si elle revient (cache memoire).
    imgs: Dict[str, object] = {}
    for j in jours:
        for s in calendrier[j].series[:4]:
            if s.cle not in imgs:
                imgs[s.cle] = V.charger(s.image_url, cache=cache, journal=journal)

    # Bandeau : les couvertures les plus recentes de la fenetre.
    vignettes: List = []
    for j in reversed(jours):
        for s in calendrier[j].series:
            img = imgs.get(s.cle)
            if img is not None and len(vignettes) < 10:
                vignettes.append(img)

    lg = T.langue_de(th)
    total = sum(calendrier[j].nb for j in jours)
    # ⚠️ « → » (U+2192) n'existe pas dans Nunito : le separateur est un chevron.
    # Le controle de glyphes, en fin de fonction, empeche ce genre d'oubli de
    # repartir en production.
    periode = D.libelle_periode(jours[0], jours[-1], mois=T.MOIS_COURT[lg],
                                lien=T.MOTS[lg]["vers"])
    dominant = _mois_dominant(jours)
    mois = "%s %d" % (T.MOIS_LONG[lg][dominant % 100 - 1], dominant // 100)

    corps = [defs(g, th), rect(0, 0, g.W, g.H, th.fond),
             entete(g, th, periode, vignettes), barre(g, th, total, mois)]
    for i, j in enumerate(jours):
        x, y = g.case(i % 7, i // 7)
        corps.append(case(g, th, x, y, calendrier[j], imgs, aujourdhui, i))
    corps.append(pied(g, th))

    if controler_glyphes:
        from . import polices as P
        P.verifier_glyphes(GLYPHES_VUS, strict=True)

    return ('<svg xmlns="http://www.w3.org/2000/svg" '
            'xmlns:xlink="http://www.w3.org/1999/xlink" width="%d" height="%d" '
            'viewBox="0 0 %d %d">%s</svg>' % (cote, cote, cote, cote, "".join(corps)))


def _mois_dominant(jours: List[_dt.date]) -> int:
    compte: Dict[int, int] = {}
    for j in jours:
        cle = j.year * 100 + j.month
        compte[cle] = compte.get(cle, 0) + 1
    return max(compte.items(), key=lambda kv: (kv[1], kv[0]))[0]


def en_png(svg: str, chemin: str, echelle: float = 1.0) -> str:
    """SVG → PNG. cairosvg est la seule dependance de rendu."""
    import cairosvg
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=chemin, scale=echelle)
    return chemin
