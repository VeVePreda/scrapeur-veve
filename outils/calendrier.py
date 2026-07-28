#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : outils/calendrier.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""📅 LE LANCEUR DU CALENDRIER VISUEL DES DROPS.

    # le carre 1080, VeVe France, depuis le miroir local (hors reseau sauf pour
    # les visuels CloudFront) :
    python3 outils/calendrier.py --theme vevefrance --xlsx "github/VeVe Scraper.xlsx"

    # les deux marques d'un coup :
    python3 outils/calendrier.py --tout --xlsx "github/VeVe Scraper.xlsx"

⚠️ UN SEUL FORMAT : LE CARRE 1080 (decision du 28/07). Le meme fichier sert au
post Discord du samedi, aux reseaux et a la newsletter — c'etait le seul format
vraiment utilise, et en garder trois multipliait les rendus a verifier a l'oeil.
`--cote 2160` sort le meme visuel en double resolution si besoin d'impression.

CE QUE LE LANCEUR GARANTIT
--------------------------
* Les **polices sont installees puis VERIFIEES** avant tout rendu. Sans ce
  garde-fou, une police absente ne casse rien : cairo prend DejaVu et le visuel
  part, moche, sans que personne ne le sache. `--polices-souples` desactive la
  verification — a n'utiliser que pour deboguer.
* Le run **DIT ce qu'il a fait** : fenetre retenue, nombre de drops, visuels en
  cache / telecharges / en echec, fichiers ecrits. (Preda veut une trace visible
  de ce qui a change.)
* Aucune requete vers VeVe : la donnee vient du Sheet ou de son miroir, seuls
  les VISUELS sont tires du CDN, et une seule fois grace au cache disque.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys

# Permet `python3 outils/calendrier.py` depuis la racine du depot.
_RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RACINE not in sys.path:
    sys.path.insert(0, _RACINE)

from outils.calendrier import donnees as D          # noqa: E402
from outils.calendrier import polices as P          # noqa: E402
from outils.calendrier import rendu as R            # noqa: E402
from outils.calendrier import themes as T           # noqa: E402
from outils.calendrier import visuels as V          # noqa: E402

# Miroir cherche par defaut, dans l'ordre. ⭐ Un livrable qui a besoin d'un
# fichier dit OU il l'a cherche quand il ne le trouve pas.
MIROIRS = ("github/VeVe Scraper.xlsx", "VeVe Scraper.xlsx",
           "../github/VeVe Scraper.xlsx")


def trouver_miroir(donne: str | None) -> str:
    if donne:
        return donne
    for chemin in MIROIRS:
        if os.path.exists(chemin):
            return chemin
    raise SystemExit(
        "Aucun miroir 'VeVe Scraper.xlsx' trouvé. Cherché ici :\n  - "
        + "\n  - ".join(os.path.abspath(m) for m in MIROIRS)
        + "\n→ passer --xlsx <chemin>, ou --sheet pour lire le Google Sheet.")


def une_sortie(calendrier, th, *, aujourdhui, cote, dossier, cache, journal,
               garder_svg) -> str:
    svg = R.construire(calendrier, th, aujourdhui=aujourdhui, cote=cote,
                       cache=cache, journal=journal)
    base = "calendrier-%s-%s" % (th.cle, aujourdhui.isoformat())
    os.makedirs(dossier, exist_ok=True)
    png = os.path.join(dossier, base + ".png")
    R.en_png(svg, png)
    if garder_svg:
        with open(os.path.join(dossier, base + ".svg"), "w", encoding="utf-8") as f:
            f.write(svg)
    return png


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Calendrier visuel des drops VeVe")
    ap.add_argument("--theme", default="vevefrance",
                    help="marque : " + ", ".join(sorted(T.THEMES)))
    ap.add_argument("--tout", action="store_true", help="toutes les marques")
    ap.add_argument("--cote", type=int, default=1080,
                    help="côté du carré en pixels (défaut 1080)")
    ap.add_argument("--semaines", type=int, default=5)
    ap.add_argument("--decalage", type=int, default=0,
                    help="décale la fenêtre de N semaines (négatif = passé)")
    ap.add_argument("--date", default="",
                    help="se placer un autre jour (AAAA-MM-JJ) — pour rejouer")
    ap.add_argument("--xlsx", default="", help="miroir 'VeVe Scraper.xlsx'")
    ap.add_argument("--sheet", action="store_true",
                    help="lire le Google Sheet en direct (secrets requis)")
    ap.add_argument("--sortie", default="outputs")
    ap.add_argument("--cache", default=V.CACHE_DEFAUT)
    ap.add_argument("--svg", action="store_true", help="garder aussi le .svg")
    ap.add_argument("--polices-souples", action="store_true",
                    help="ne PAS échouer si une police manque (débogage seulement)")
    args = ap.parse_args(argv)

    aujourdhui = (_dt.date.fromisoformat(args.date) if args.date
                  else _dt.date.today())
    debut, fin = D.fenetre(aujourdhui, semaines=args.semaines,
                           decalage=args.decalage)

    themes = ([T.THEMES[c] for c in sorted(T.THEMES)] if args.tout
              else [T.theme(args.theme)])

    familles = sorted({f for th in themes for f in th.familles()})
    P.preparer(familles, strict=not args.polices_souples)

    source = "Google Sheet (direct)" if args.sheet else trouver_miroir(args.xlsx)
    calendrier = D.charger(debut, fin, xlsx=None if args.sheet else source,
                           sheet=args.sheet)
    total = sum(j.nb for j in calendrier.values())
    pleins = sum(1 for j in calendrier.values() if not j.vide)
    print("fenêtre : %s → %s (%d semaines) · %d drops (maille série) sur %d jours"
          % (debut, fin, args.semaines, total, pleins))
    print("source  : %s" % source)
    if total == 0:
        print("⚠️ AUCUN drop dans la fenêtre — miroir périmé, ou --decalage trop loin.")

    journal = V.Journal()
    ecrits = []
    for th in themes:
        ecrits.append(une_sortie(calendrier, th, aujourdhui=aujourdhui,
                                 cote=args.cote, dossier=args.sortie,
                                 cache=args.cache, journal=journal,
                                 garder_svg=args.svg))
    print(journal.resume())
    for chemin in ecrits:
        print("écrit : %s" % chemin)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
