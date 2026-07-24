# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/bascule_identite.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier depose au
# mauvais endroit ne provoque aucune erreur : il dort.

"""🔀 BASCULE v3 (RÉVERSIBLE) — l'identité d'elements.csv vient de la CHAÎNE.

Étape ADDITIVE et GATED, lancee dans le daily APRÈS l'export officiel v2. Elle
ne touche PAS export_elements_v2 : elle POST-TRAITE `data/elements.csv` en
remplacant les seules colonnes d'IDENTITE (adoptees de la chaine le 23/07) par
celles de `data/elements_v3.csv` — et laisse INTACT tout le OFF-CHAIN frais du
jour (floor/listings/atl/ath/note/first_public).

    Chaine (override) : name, category, rarity, edition_type, supply, brand, licensor
    Daily/tracker (garde) : series_uuid, first_public, listings, note, atl,
                            atl_date, ath, ath_date

INTERRUPTEUR : `BASCULE_IDENTITE_CHAINE` (defaut OFF). Sans lui, ce module est un
NO-OP total -> re-uploader ne change RIEN en prod tant que Preda ne l'active pas.

RÉVERSIBLE PAR CONSTRUCTION : le daily RECONSTRUIT elements.csv depuis le tracker
(v2) a chaque tour AVANT cette etape. Donc :
  * activer  = poser la var `BASCULE_IDENTITE_CHAINE=1` (+ l'etape telecharge v3) ;
  * revenir  = la remettre a 0 -> le lendemain, elements.csv est de nouveau 100 %
               tracker, sans le moindre residu. (Immediat : relancer l'export v2.)

GARDE-FOUS (un catalogue casse ne doit JAMAIS ecraser l'identite en prod) :
  * v3 absent ou < `BASCULE_MIN_V3` lignes (defaut 15000) -> ON NE TOUCHE A RIEN.
  * on ne remplace un champ que si la valeur chaine est NON VIDE (un trou v3 ne
    doit pas effacer un nom tracker existant).
  * l'en-tete d'elements.csv est preserve OCTET POUR OCTET.
"""

from __future__ import annotations

import csv
import os
import sys
from typing import Dict, List

ELEMENTS_CSV = os.environ.get("ELEMENTS_CSV", "data/elements.csv")
ELEMENTS_V3 = os.environ.get("ELEMENTS_V3", "data/elements_v3.csv")
MIN_V3 = int(os.environ.get("BASCULE_MIN_V3", "15000"))

# Les colonnes ADOPTEES de la chaine (cf. COMPARE_ADOPTE / chantier v3).
COLS_CHAINE = ["name", "category", "rarity", "edition_type", "supply",
               "brand", "licensor"]


def _actif() -> bool:
    return os.environ.get("BASCULE_IDENTITE_CHAINE", "").strip().lower() in (
        "1", "true", "oui", "on")


def _lire(chemin: str) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    with open(chemin, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            uid = (r.get("veve_uuid") or "").strip()
            if uid:
                out[uid] = r
    return out


def appliquer(elements: str = ELEMENTS_CSV, v3: str = ELEMENTS_V3,
              min_v3: int = MIN_V3) -> int:
    """Remplace en place les colonnes d'identite d'`elements` par celles de `v3`.
    Retourne le nb de lignes modifiees. Ne fait RIEN (retour -1) si garde-fou."""
    if not os.path.exists(elements):
        print(f"⛔ {elements} absent — rien a basculer.", file=sys.stderr)
        return -1
    if not os.path.exists(v3):
        print(f"⛔ {v3} absent (catalogue chaine non telecharge ?) — "
              f"identite tracker CONSERVEE, aucune bascule.", file=sys.stderr)
        return -1

    with open(elements, encoding="utf-8", newline="") as f:
        rd = csv.reader(f)
        header = next(rd)
        rows = [dict(zip(header, r)) for r in rd]
    chaine = _lire(v3)

    if len(chaine) < min_v3:
        print(f"⛔ catalogue chaine trop maigre ({len(chaine)} < {min_v3}) — "
              f"identite tracker CONSERVEE (garde-fou anti-ecrasement).",
              file=sys.stderr)
        return -1

    cols = [c for c in COLS_CHAINE if c in header]
    modifs = 0
    couverts = 0
    for row in rows:
        src = chaine.get((row.get("veve_uuid") or "").strip())
        if not src:
            continue                     # uuid hors chaine (drop tout neuf) : garde tracker
        couverts += 1
        touche = False
        for c in cols:
            v = (src.get(c) or "").strip()
            if v != "" and v != (row.get(c) or ""):
                row[c] = v               # valeur chaine NON VIDE et differente
                touche = True
        modifs += 1 if touche else 0

    with open(elements, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for row in rows:
            w.writerow([row.get(c, "") for c in header])

    print(f"🔀 bascule identite CHAINE : {len(rows)} lignes · {couverts} "
          f"couvertes par la chaine · {modifs} modifiees (colonnes : "
          f"{', '.join(cols)}). Off-chain (floor/atl/ath/listings/note) INTACT.",
          flush=True)
    return modifs


def main() -> int:
    if not _actif():
        print("bascule identite : interrupteur OFF (BASCULE_IDENTITE_CHAINE) — "
              "elements.csv reste 100 % tracker. NO-OP.", flush=True)
        return 0
    r = appliquer()
    return 0 if r >= 0 else 0     # un garde-fou ne doit pas casser le daily


if __name__ == "__main__":
    sys.exit(main())
