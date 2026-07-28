# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : outils/calendrier/polices.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""🔤 LES POLICES DU CALENDRIER — embarquees, installees, puis **VERIFIEES**.

⭐⭐ POURQUOI CE MODULE EXISTE
-----------------------------
Une police absente ne fait echouer AUCUN rendu : cairo prend silencieusement
DejaVu Sans a la place, le PNG sort, il est juste **moche** — et personne ne le
voit avant qu'il soit publie. C'est exactement le « defaut par REPLI » deja paye
sur vevewiki : un defaut grave qui ne fait echouer aucun build.

D'ou les deux gestes de ce module, dans cet ordre :
  1. `installer()` copie les .ttf **livres dans le zip** vers un dossier de
     polices utilisateur et rafraichit le cache fontconfig ;
  2. `verifier()` demande a fontconfig ce qu'il resoudrait VRAIMENT pour chaque
     famille, et **leve** si ce n'est pas la bonne. Le run s'arrete bruyamment
     plutot que de produire un visuel de repli.

⭐ UN LIVRABLE EMBARQUE SES DONNEES : les .ttf sont dans `outils/calendrier/ttf/`,
livres avec le module. Aucun telechargement au moment du rendu.

Sous Windows : `fc-match` n'existe pas, la verification est alors SAUTEE et le
module le dit. Le rendu de reference se fait sous Linux (bac a sable et GitHub
Actions), c'est la que le garde-fou compte.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Dict, Iterable, List

DOSSIER_TTF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ttf")

# ⭐ Les familles sont celles des NEWSLETTERS (`newsletters-v4/`) : Baloo 2 +
# Nunito pour VeVe France, Bricolage Grotesque + Inter pour VeVe Insights. Les
# .ttf livres sont des instances statiques (Bold / Regular) sous-ensemblees au
# latin — d'ou leur petite taille.
FICHIERS = ("Baloo2-Bold.ttf", "Baloo2-Regular.ttf",
            "Nunito-Bold.ttf", "Nunito-Regular.ttf",
            "BricolageGrotesque-Bold.ttf", "BricolageGrotesque-Regular.ttf",
            "Inter-Bold.ttf", "Inter-Regular.ttf")


def dossier_utilisateur() -> str:
    return os.path.join(os.path.expanduser("~"), ".local", "share", "fonts",
                        "scrapeur-veve-calendrier")


def installer(verbeux: bool = True) -> str:
    """Copie les .ttf livres dans le dossier de polices utilisateur + fc-cache."""
    if not os.path.isdir(DOSSIER_TTF):
        raise FileNotFoundError(
            "polices introuvables : %s\n"
            "→ le zip doit contenir outils/calendrier/ttf/*.ttf ; sans elles le "
            "rendu tomberait silencieusement sur DejaVu Sans." % DOSSIER_TTF)
    cible = dossier_utilisateur()
    os.makedirs(cible, exist_ok=True)
    poses = 0
    for nom in FICHIERS:
        source = os.path.join(DOSSIER_TTF, nom)
        if not os.path.exists(source):
            continue
        destination = os.path.join(cible, nom)
        if (not os.path.exists(destination)
                or os.path.getsize(destination) != os.path.getsize(source)):
            shutil.copyfile(source, destination)
            poses += 1
    if shutil.which("fc-cache"):
        subprocess.run(["fc-cache", "-f", cible], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if verbeux:
        print("polices : %d fichier(s) (re)pose(s) dans %s" % (poses, cible))
    return cible


def resolue(famille: str) -> str:
    """Ce que fontconfig servirait REELLEMENT pour cette famille ("" si inconnu)."""
    if not shutil.which("fc-match"):
        return ""
    sortie = subprocess.run(["fc-match", "-f", "%{family}", famille],
                            capture_output=True, text=True, check=False)
    return (sortie.stdout or "").strip()


def verifier(familles: Iterable[str], strict: bool = True) -> List[str]:
    """Leve si une famille demandee n'est pas celle que fontconfig servirait.

    Retourne la liste des familles fautives (vide = tout va bien). Avec
    `strict=False`, on se contente d'avertir — utile pour deboguer, jamais pour
    produire un visuel destine a etre publie.
    """
    if not shutil.which("fc-match"):
        print("⚠️ fc-match absent : verification des polices SAUTEE "
              "(le rendu peut tomber sur une police de repli sans le dire).")
        return []
    fautives: List[str] = []
    for famille in familles:
        obtenue = resolue(famille)
        # fontconfig peut rendre "Oswald,Oswald Bold" : la 1re valeur fait foi.
        premiere = obtenue.split(",")[0].strip().lower()
        if premiere != famille.strip().lower():
            fautives.append("%s → %s" % (famille, obtenue or "(rien)"))
    if fautives and strict:
        raise RuntimeError(
            "POLICES MANQUANTES — le rendu serait fait avec une police de repli "
            "et personne ne le verrait :\n  " + "\n  ".join(fautives) +
            "\n→ lancer d'abord `installer()` (le lanceur le fait tout seul), "
            "et verifier que outils/calendrier/ttf/ contient bien les .ttf.")
    for f in fautives:
        print("⚠️ police de repli : %s" % f)
    return fautives


def preparer(familles: Iterable[str], strict: bool = True) -> None:
    """Le geste unique appele par le lanceur : installer puis verifier."""
    installer(verbeux=False)
    verifier(familles, strict=strict)


# ------------------------------------------------- ⭐ le controle des GLYPHES

# famille -> fichiers a inspecter (toutes les graisses utilisees au rendu)
_CMAP: Dict[str, set] = {}
_FICHIERS_PAR_FAMILLE: Dict[str, tuple] = {
    "Baloo 2": ("Baloo2-Bold.ttf", "Baloo2-Regular.ttf"),
    "Nunito": ("Nunito-Bold.ttf", "Nunito-Regular.ttf"),
    "Bricolage Grotesque": ("BricolageGrotesque-Bold.ttf",
                            "BricolageGrotesque-Regular.ttf"),
    "Inter": ("Inter-Bold.ttf", "Inter-Regular.ttf"),
}


def _cmap(famille: str) -> set:
    """Les caracteres que cette famille sait REELLEMENT dessiner."""
    if famille in _CMAP:
        return _CMAP[famille]
    from fontTools.ttLib import TTFont          # import tardif : dependance legere
    codes: set = set()
    for nom in _FICHIERS_PAR_FAMILLE.get(famille, ()):
        chemin = os.path.join(DOSSIER_TTF, nom)
        if os.path.exists(chemin):
            codes |= set(TTFont(chemin).getBestCmap())
    _CMAP[famille] = codes
    return codes


def verifier_glyphes(paires, strict: bool = True) -> List[str]:
    """⭐ Un caractere absent de la police sort en CARRE VIDE, sans erreur.

    Paye en clair sur ce module : « 29 JUIN → 2 AOÛT » — la fleche U+2192
    n'existe ni dans Oswald ni dans Barlow Condensed. Le PNG sortait, avec un
    joli tofu au milieu du sous-titre, et rien dans les logs.

    `paires` = iterable de (famille, texte) collecte pendant le dessin. On
    refuse de produire un visuel qui contient un caractere que la police ne sait
    pas tracer. Les familles inconnues sont ignorees (rien a verifier).
    """
    manquants: Dict[str, set] = {}
    for famille, contenu in paires:
        codes = _cmap(famille)
        if not codes:
            continue
        for caractere in str(contenu):
            if ord(caractere) not in codes and caractere not in "\n\t":
                manquants.setdefault(famille, set()).add(caractere)
    if not manquants:
        return []
    lignes = ["%s : %s" % (f, " ".join("%r (U+%04X)" % (c, ord(c))
                                       for c in sorted(m)))
              for f, m in sorted(manquants.items())]
    if strict:
        raise RuntimeError(
            "GLYPHES ABSENTS — ces caracteres sortiraient en carre vide :\n  "
            + "\n  ".join(lignes)
            + "\n→ remplacer le caractere, ou changer de police.")
    for ligne in lignes:
        print("⚠️ glyphe absent : %s" % ligne)
    return lignes
