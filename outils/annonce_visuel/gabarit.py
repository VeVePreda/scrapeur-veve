# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : outils/annonce_visuel/gabarit.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""📐 OU VA QUOI — les zones de l'affiche « RETOUR SUR <MOIS> ».

⭐⭐ LES ZONES SONT EN FRACTIONS DU CADRE, JAMAIS EN PIXELS. Le fond de Preda
fait 1920x1080 aujourd'hui ; s'il l'exporte un jour en 2560 ou en 4K, rien ici
ne bouge. **Un gabarit ecrit en pixels est un gabarit qui meurt au premier
re-export.**

⭐⭐ ET ELLES SONT SURCHARGEABLES SANS TOUCHER AU CODE. `data/annonce_gabarit.json`
(meme forme, fractions) ecrase zone par zone. Preda peut donc recadrer une case
de 2 % sans attendre un lot — et je n'ai pas a deviner ses coordonnees au pixel
pres depuis une capture d'ecran.

🔴 CES CHIFFRES SONT MESURES SUR UNE CAPTURE, PAS SUR LE FICHIER SOURCE. Ils
sont donc **approximatifs par construction**. C'est exactement pour ca que
`rendu.grille()` existe : il dessine les zones sur le fond, on regarde, on
corrige le JSON. ⭐ Une mesure prise sur une image redimensionnee ne se verifie
pas en la relisant — elle se verifie en la SUPERPOSANT.

Repere : (0,0) en haut a gauche, (1,1) en bas a droite. Une zone = (x, y, l, h).
"""

from __future__ import annotations

import json
import os
from typing import Dict, Tuple

CHEMIN_SURCHARGE = os.environ.get("ANNONCE_VISUEL_GABARIT",
                                  os.path.join("data", "annonce_gabarit.json"))

# Reference : la capture du visuel de mai (1920 x 1080).
ZONES: Dict[str, Tuple[float, float, float, float]] = {
    # Le coeur VeVe France, en filigrane derriere le titre. Vide par defaut :
    # le decor de Preda le porte deja, on ne le repose pas par-dessus.
    "logo": (0.075, 0.040, 0.170, 0.360),
    # Le titre « RETOUR SUR » + le mois, en haut a gauche.
    "titre": (0.030, 0.160, 0.250, 0.130),
    # 🖼️ LA BANNIERE VeVe — elle passe SOUS le decor.
    # ⭐⭐ ELLE COUVRE TOUT LE BANDEAU, ET C'EST VOULU : Preda a laisse un TROU
    # TRANSPARENT dans son PNG. **Le decor est un MASQUE** — inutile de mesurer
    # la forme du trou au pixel pres, il suffit de peindre large dessous et de
    # laisser le decor decider de ce qui se voit. Une forme decoupee a la main
    # se serait desynchronisee au premier re-export ; un masque, jamais.
    "banniere": (0.000, 0.000, 1.000, 0.468),
    # La carte du comic : la couverture, puis le bloc de texte a sa droite.
    # ⚠️ RETRECIE apres le rendu reel : a 0.120 x 0.322 la couverture touchait
    # les bords de son cadre. Une image qui affleure son cadre a l'air d'un
    # debordement, meme quand elle est dedans.
    "comic_couverture": (0.664, 0.080, 0.106, 0.285),
    "comic_texte": (0.790, 0.090, 0.185, 0.270),
    # La mosaique du bas : une grande case, puis quatre petites.
    "tuile_1": (0.018, 0.497, 0.482, 0.473),
    "tuile_2": (0.510, 0.497, 0.228, 0.231),
    "tuile_3": (0.755, 0.497, 0.228, 0.231),
    "tuile_4": (0.510, 0.739, 0.228, 0.231),
    "tuile_5": (0.755, 0.739, 0.228, 0.231),
}

# L'ordre dans lequel les pieces remplissent la mosaique.
TUILES = ("tuile_1", "tuile_2", "tuile_3", "tuile_4", "tuile_5")

# Le rayon des coins arrondis des tuiles, en fraction de la LARGEUR du cadre.
RAYON_TUILE = 0.009

# ═══ LES POLICES DE PREDA — FOURNIES LE 04/08, elles vivent dans ttf/ ═══
#   « RETOUR SUR »   ->  Horizon Bold        (Horizon.otf)
#   « <MOIS> »       ->  Horizon OUTLINED    (Horizon_Outlined.otf)
#   la carte comic   ->  Nourd Bold          (Nourd.ttf)
# ⭐ TROIS FONTES, TROIS REGLAGES : le titre, le mois et la carte n'ont aucune
# raison de partager une fonte — les melanger obligerait a en sacrifier une.
# ⚠️ Ce sont des **.otf** : Pillow les lit sans probleme, mais un `_premier_existant`
# qui ne chercherait que du `.ttf` les ignorerait en silence.
# Repli si un fichier manque : Inter-Bold (livre pour le calendrier).
DOSSIER_TTF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ttf")
TTF_DEFAUT = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "calendrier", "ttf", "Inter-Bold.ttf")


def _premier_existant(*chemins) -> str:
    for c in chemins:
        if c and os.path.exists(c):
            return c
    return TTF_DEFAUT

BLANC = (255, 255, 255, 255)
# Un aplat sombre pour une case sans image : le visuel sort quand meme.
REPLI = (24, 26, 32, 255)

# ═══ LE TITRE TRICOLORE ═══
# ⭐⭐ MESURE AU PIXEL SUR SON VISUEL DE MAI, pas choisie « au bleu qui va bien » :
# « RET » bleu, « OUR » blanc, « SUR » rouge — le drapeau. Une charte qu'on
# devine a l'oeil derive d'un mois a l'autre ; une charte relevee sur la source
# ne derive jamais.
TITRE_HAUT = (("RET", (1, 130, 248, 255)),      # releve : (1,130,248)
              ("OUR", (255, 255, 255, 255)),
              ("SUR", (196, 26, 32, 255)))
# Un espace fin entre « RETOUR » et « SUR » (fraction de la taille de police).
TITRE_ESPACE = 0.32
# L'interlettrage du mois — il est LARGE chez lui.
MOIS_CHASSE = 0.22
# ⚠️ LE MOIS EST EN CONTOUR, PAS EN PLEIN (verifie en zoomant sa capture) :
# c'est ce detail-la qui fait « son » visuel. L'epaisseur suit la taille.
MOIS_TRAIT = 0.045
# 🔴 HALO DERRIERE LE MOIS — A ZERO, ET C'EST UNE LECON.
# J'avais ajoute un halo sombre pour rattraper la finesse d'Horizon Outlined sur
# une banniere claire. Erreur : **un contour de trace applique a une fonte
# AJOUREE remplit l'interieur des lettres**. Le glyphe est un ANNEAU ; strocker
# un anneau bouche son trou. Resultat : des lettres creuses posees sur du noir
# au lieu de lettres a travers lesquelles on voit le fond — exactement ce que
# Preda a vu et signale.
# ⭐⭐ UN EFFET QUI MARCHE SUR UNE FONTE PLEINE PEUT DETRUIRE UNE FONTE AJOUREE :
# ce n'est pas une question de reglage, c'est une question de forme.
# Laisse a 0. La lisibilite se regle par le VOILE (qui, lui, est derriere tout).
MOIS_HALO = float(os.environ.get("ANNONCE_VISUEL_MOIS_HALO", "0"))
# ⭐ CE QUI REMPLACE LE HALO : on epaissit l'ANNEAU LUI-MEME, en BLANC.
# Un contour blanc grossit le trait vers l'exterieur ET vers l'interieur ; tant
# qu'il reste petit devant la contre-forme, **le trou survit** et on voit
# toujours le fond a travers la lettre. C'est la difference avec le halo
# sombre : celui-ci envahissait le trou et le bouchait a l'oeil.
# Fraction de la taille de police. 0 = le trait nu de la fonte.
# ⚠️ 0.022 EST UN MAXIMUM UTILE, PAS UN CURSEUR A POUSSER : essaye a 0.032 et
# la contre-forme du « A » se referme. **Epaissir un anneau finit toujours par
# le boucher** — c'est la meme cause que le halo, en plus lent.
MOIS_GRAS = float(os.environ.get("ANNONCE_VISUEL_MOIS_GRAS", "0.022"))

# Le coeur VeVe France, livre avec le module. ⛔ VIDE PAR DEFAUT : le decor de
# Preda le porte deja. On ne le pose que si `ANNONCE_VISUEL_LOGO` le demande —
# ⭐ **reposer un element que le fond porte deja ne se voit pas au code, ca se
# voit sur le visuel publie, en double.**
LOGO_LIVRE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "logo", "vevefrance.png")
# L'opacite du filigrane quand il est demande (0-255).
LOGO_OPACITE = int(os.environ.get("ANNONCE_VISUEL_LOGO_OPACITE", "70"))


def logo() -> str:
    """Le chemin du logo a poser, ou "" (le cas normal).
    `ANNONCE_VISUEL_LOGO=1` prend celui du depot ; un chemin prend le sien."""
    v = os.environ.get("ANNONCE_VISUEL_LOGO", "").strip()
    if not v:
        return ""
    return LOGO_LIVRE if v in ("1", "true", "oui") else v


def voile() -> int:
    """L'opacite du voile sombre sous le titre (0-255 ; 0 = aucun).
    ⚠️ Le coeur du decor est SEMI-TRANSPARENT : sans voile, une banniere claire
    rend le titre illisible."""
    return int(os.environ.get("ANNONCE_VISUEL_VOILE", "180"))


def ttf() -> str:
    """La police du TITRE — **Horizon Bold**, fournie par Preda (04/08)."""
    return _premier_existant(os.environ.get("ANNONCE_VISUEL_TTF", "").strip(),
                             os.path.join(DOSSIER_TTF, "Horizon.otf"),
                             os.path.join(DOSSIER_TTF, "Horizon.ttf"))


def ttf_mois() -> str:
    """La police du MOIS — **Horizon Outlined**.

    ⭐⭐ PREDA A FOURNI LA VARIANTE AJOUREE DE SA FONTE, et c'est une meilleure
    reponse que la mienne : je simulais le contour avec un contour de trace
    (`stroke_width`), ce qui epaissit les jambages et ferme les contre-formes.
    **Une fonte ajouree n'est pas un contour applique a une fonte pleine** —
    le dessin des lettres n'est pas le meme. Quand la vraie existe, on la prend
    et on n'ajoute plus rien.
    Repli : la fonte pleine + le contour simule (`MOIS_TRAIT`)."""
    return _premier_existant(
        os.environ.get("ANNONCE_VISUEL_TTF_MOIS", "").strip(),
        os.path.join(DOSSIER_TTF, "Horizon_Outlined.otf"),
        os.path.join(DOSSIER_TTF, "Horizon-Outlined.otf"))


def mois_deja_ajoure() -> bool:
    """Vrai si la fonte du mois EST deja ajouree : alors on la remplit en blanc
    au lieu de lui appliquer un contour par-dessus (qui ferait un double trait)."""
    return os.path.basename(ttf_mois()).lower().startswith(("horizon_outlined",
                                                            "horizon-outlined"))


def ttf_carte() -> str:
    """La police de la CARTE DU COMIC — **Nourd Bold**, fournie par Preda."""
    return _premier_existant(
        os.environ.get("ANNONCE_VISUEL_TTF_CARTE", "").strip(),
        os.path.join(DOSSIER_TTF, "Nourd.ttf"),
        os.path.join(DOSSIER_TTF, "nourd-bold.ttf"))


def _valide(z) -> bool:
    return (isinstance(z, (list, tuple)) and len(z) == 4
            and all(isinstance(v, (int, float)) for v in z))


def zones(chemin: str = "") -> Dict[str, Tuple[float, float, float, float]]:
    """Les zones, surchargees par le JSON s'il existe.

    ⭐ UNE SURCHARGE ILLISIBLE NE DOIT PAS CASSER LE VISUEL, MAIS ELLE DOIT SE
    DIRE. Un JSON absent = le defaut, en silence (c'est le cas normal). Un JSON
    present mais bancal = le defaut, **et un message** : sinon Preda corrigerait
    des coordonnees qui ne sont jamais lues.
    """
    out = dict(ZONES)
    chemin = chemin or CHEMIN_SURCHARGE
    if not os.path.exists(chemin):
        return out
    try:
        with open(chemin, encoding="utf-8") as f:
            perso = json.load(f)
    except Exception as e:                                  # noqa: BLE001
        print(f"⚠️ gabarit : {chemin} illisible ({e}) — zones par defaut.",
              flush=True)
        return out
    for nom, z in (perso or {}).items():
        if nom not in out:
            print(f"⚠️ gabarit : zone inconnue « {nom} » ignoree "
                  f"(connues : {', '.join(sorted(out))}).", flush=True)
            continue
        if not _valide(z):
            print(f"⚠️ gabarit : zone « {nom} » mal formee ({z!r}) — on garde "
                  f"la valeur par defaut.", flush=True)
            continue
        out[nom] = tuple(float(v) for v in z)               # type: ignore
    return out


def boite(zone, largeur: int, hauteur: int) -> Tuple[int, int, int, int]:
    """Une zone en fractions -> (gauche, haut, droite, bas) en pixels."""
    x, y, l, h = zone
    g, ht = round(x * largeur), round(y * hauteur)
    return g, ht, g + max(1, round(l * largeur)), ht + max(1, round(h * hauteur))
