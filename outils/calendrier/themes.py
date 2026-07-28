# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : outils/calendrier/themes.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""🎨 UN THEME = UNE MARQUE. Le moteur est commun, l'apparence ne l'est jamais.

⭐⭐ LES PALETTES VIENNENT DES NEWSLETTERS, PAS DE MON GOUT
----------------------------------------------------------
Chaque marque a deja une identite arretee dans `newsletters-v4/` : le calendrier
la REPREND telle quelle, variable CSS par variable CSS. Un visuel qui invente sa
propre palette casse l'harmonie au lieu de la servir — et c'est le meme lecteur
qui verra la newsletter et le post du samedi.

  VeVe France    → `newsletters-v4/vevefrance/build_vf.py`      :root
                   Baloo 2 + Nunito · bleu #2b6fff / rouge #ef4135 / or #ffd23f
  VeVe Insights  → `newsletters-v4/veveinsights/build_insights.py` :root
                   Bricolage Grotesque + Inter · rose #ff6fb3 / lavande #b58bf0

⚠️ Si une palette de newsletter bouge, elle bouge ICI aussi. Les deux fichiers
doivent rester d'accord, sinon l'harmonie se defait sans que rien n'echoue.

⭐⭐ LA CONTRAINTE QUI COMMANDE LE RESTE (regle Preda)
-----------------------------------------------------
« Chaque marque devra avoir une presentation differente pour qu'on ne puisse pas
penser a un lien entre elles. » Un theme ne porte donc pas que des couleurs : il
porte `entete`, `position_jour`, `rayon`, `gap` — de quoi changer la SILHOUETTE.

**VeVe France et VeVe Insights font exception** : `newsletters-v4/README.md` les
declare « jumeaux stricts » (l'un est la version anglaise de l'autre), et Preda
l'a confirme. Elles partagent donc la mise en page et ne divergent que par la
palette, les polices et la langue. Toute AUTRE marque devra, elle, changer aussi
de silhouette — un test le verifie (`tests/test_calendrier.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class Theme:
    cle: str
    marque: str                     # nom affiche ("VeVe France")
    logo: str                       # fichier dans outils/calendrier/logos/
    site: str                       # pied de page, gauche
    discord: str                    # pied de page, droite
    titre: str                      # titre principal
    mention: str                    # mention legale, petite

    # palette — reprise des :root des newsletters
    fond: str                       # --plane
    fond_case: str                  # --card   (case sans drop)
    fond_case2: str                 # --card2
    ligne: str                      # --line   (contour des cases)
    encre: str                      # --ink
    encre_faible: str               # --ink2
    accent: str                     # couleur de marque n°1
    accent2: str                    # couleur de marque n°2
    accent3: str                    # touche claire (degrade d'entete)
    or_: str                        # --gold

    # typographie
    police_titre: str
    police_texte: str
    largeur_glyphe: float = 0.50    # largeur moyenne d'un caractere, en em

    # silhouette
    entete: str = "montage"         # "montage" | "trame" | "aplat"
    position_jour: str = "haut-droite"   # | "bas-gauche" | "haut-gauche"
    rayon: float = 14.0             # arrondi des cases
    gap: float = 7.0                # espace entre cases
    lettrage_titre: float = 0.0
    cousin_de: Optional[str] = None

    def familles(self) -> List[str]:
        return sorted({self.police_titre, self.police_texte})


VEVE_FRANCE = Theme(
    cle="vevefrance",
    marque="VeVe France",
    logo="vevefrance.png",
    site="vevefrance.fr",
    discord="discord.gg/vevefrance",
    titre="LE CALENDRIER DES DROPS",
    mention="Informations fournies à des fins de divertissement, jamais de conseil financier.",
    fond="#0b1120",
    fond_case="#141b2e",
    fond_case2="#1b2440",
    ligne="#2b3654",
    encre="#eef2fb",
    encre_faible="#a7b6d6",
    accent="#ef4135",              # rouge
    accent2="#2b6fff",             # bleu
    accent3="#cdd8f2",             # blanc bleute — le 3e ton du degrade VF
    or_="#ffd23f",
    police_titre="Baloo 2",
    police_texte="Nunito",
    largeur_glyphe=0.50,
    entete="montage",
    position_jour="haut-droite",
    rayon=14.0,
    gap=7.0,
)

VEVE_INSIGHTS = Theme(
    cle="veveinsights",
    marque="VeVe Insights",
    logo="veveinsights.png",
    site="veveinsights.com",
    discord="discord.gg/veveinsights",
    titre="THE DROP CALENDAR",
    mention="For entertainment purposes only — never financial advice.",
    fond="#160a1e",
    fond_case="#22132e",
    fond_case2="#2c1a3a",
    ligne="#3d2850",
    encre="#fdeef7",
    encre_faible="#d6bcd6",
    accent="#ff6fb3",              # rose
    accent2="#b58bf0",             # lavande
    accent3="#ffd6ea",
    or_="#ffcf6b",
    police_titre="Bricolage Grotesque",
    police_texte="Inter",
    largeur_glyphe=0.50,
    entete="montage",              # jumeau strict de VeVe France (cf. en-tete)
    position_jour="haut-droite",
    rayon=14.0,
    gap=7.0,
    cousin_de="vevefrance",
)

THEMES: Dict[str, Theme] = {t.cle: t for t in (VEVE_FRANCE, VEVE_INSIGHTS)}


def theme(cle: str) -> Theme:
    if cle not in THEMES:
        raise SystemExit("thème inconnu : %r — connus : %s"
                         % (cle, ", ".join(sorted(THEMES))))
    return THEMES[cle]


# ------------------------------------------------------- langue de l'habillage
# VeVe Insights parle anglais, VeVe France francais. Jours et mois suivent donc
# le THEME, jamais la locale de la machine.

JOURS = {
    "fr": ("LUN", "MAR", "MER", "JEU", "VEN", "SAM", "DIM"),
    "en": ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"),
}
MOIS_COURT = {
    "fr": ("JANV.", "FÉVR.", "MARS", "AVR.", "MAI", "JUIN", "JUIL.",
           "AOÛT", "SEPT.", "OCT.", "NOV.", "DÉC."),
    "en": ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL",
           "AUG", "SEP", "OCT", "NOV", "DEC"),
}
MOIS_LONG = {
    "fr": ("JANVIER", "FÉVRIER", "MARS", "AVRIL", "MAI", "JUIN", "JUILLET",
           "AOÛT", "SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DÉCEMBRE"),
    "en": ("JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
           "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"),
}
MOTS = {
    "fr": {"drops": "DROPS", "comic_day": "COMIC DAY", "vers": " » "},
    "en": {"drops": "DROPS", "comic_day": "COMIC DAY", "vers": " » "},
}

LANGUE = {"vevefrance": "fr", "veveinsights": "en"}


def langue_de(t: Theme) -> str:
    return LANGUE.get(t.cle, "fr")
