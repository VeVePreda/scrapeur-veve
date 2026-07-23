# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/compare_elements.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""🔬 LE COMPARATEUR v1/v2 du pont elements.csv — la phase « double en silence ».

Il ne decide RIEN : il mesure, colonne par colonne, ce qui separerait le pont
v2 (tracker) du pont v1 (onglets froids) si on basculait aujourd'hui.

TROIS familles de colonnes, trois lectures :
  * IDENTITE (series_uuid, name, category, rarity, supply, first_public,
    note) : tout ecart est un PROBLEME a comprendre avant bascule — elles ne
    bougent pas d'heure en heure, une difference n'a pas d'excuse temporelle.
    C'est LA SEULE famille comptee dans le verdict.
  * SOURCE (edition_type, brand, licensor) : les onglets (GraphQL fige) et le
    tracker (vivant) ne racontent pas toujours la meme chose — noms plus
    courts, types FE/FA divergents. DECISION DU 22/07 (Preda) : le tracker
    fait foi. Verifie ce jour-la : aucune divergence ne fait perdre de date
    cle (les cartes Jedi gardent licensor='Star Wars', les Loki 'Marvel').
    On LISTE tout (paires groupees) pour garder l'oeil, sans bloquer.
  * VIVANTES (listings, atl/ath + dates) : v1 date du dernier daily, v2 du
    scrape de l'instant — un ecart PEUT n'etre que du temps qui passe. On
    donne le taux et des exemples ; c'est la TENDANCE sur plusieurs jours
    qui compte (un taux qui ne baisse pas apres la reparation ×100 serait
    un signal).

Sortie : rapport dans le log. `COMPARE_SEUIL_STABLE` (defaut 0) : au-dela de
N ecarts sur les colonnes d'IDENTITE, code retour 1 pour faire remarquer le
run — 0 signifie donc « tout ecart d'identite rend le run rouge » (arme
depuis que la famille SOURCE ne pollue plus le compte) ; -1 desarme.
"""

from __future__ import annotations

import csv
import os
import sys
from typing import Dict, List

V1 = os.environ.get("ELEMENTS_CSV", "data/elements.csv")
V2 = os.environ.get("ELEMENTS_V2", "data/elements_v2.csv")
SEUIL = int(os.environ.get("COMPARE_SEUIL_STABLE", "0"))

IDENTITE = ["series_uuid", "name", "category", "rarity",
            "supply", "first_public", "note"]
SOURCE = ["edition_type", "brand", "licensor"]
VIVANTES = ["listings", "atl", "atl_date", "ath", "ath_date"]

# ⭐ COLONNES « ADOPTEES » (v3, catalogue depuis la chaine — Preda 23/07) : ces
# colonnes viennent desormais de la CHAINE par CHOIX (name/brand = titre canonique,
# rarity/licensor = verite VeVe au mint). Elles NE reviendront jamais a 0 face a
# l'officiel : c'est voulu. Listees pour l'oeil (paires groupees), mais SORTIES du
# verdict bloquant — sinon « identite 0 » serait inatteignable. Vide par defaut
# (v2 inchange). Ex v3 : COMPARE_ADOPTE="name,brand,rarity,licensor,supply,edition_type".
ADOPTE = [c.strip() for c in os.environ.get("COMPARE_ADOPTE", "").split(",")
          if c.strip()]
IDENTITE = [c for c in IDENTITE if c not in ADOPTE]
SOURCE = [c for c in SOURCE if c not in ADOPTE]


def _lire(chemin: str) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    with open(chemin, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            uid = (r.get("veve_uuid") or "").strip()
            if uid:
                out[uid] = r
    return out


def _egal(col: str, a: str, b: str) -> bool:
    a, b = (a or "").strip(), (b or "").strip()
    if a == b:
        return True
    # nombres : 6.99 == 6,99 == "6.990" ; tolerance 1 centime sur les prix
    try:
        fa = float(a.replace(",", ".").replace(" ", ""))
        fb = float(b.replace(",", ".").replace(" ", ""))
        return abs(fa - fb) <= (0.01 if col in ("atl", "ath") else 0)
    except (TypeError, ValueError):
        return False


def main() -> int:
    for chemin in (V1, V2):
        if not os.path.exists(chemin):
            print(f"⛔ {chemin} absent — rien a comparer.", file=sys.stderr)
            return 0
    v1, v2 = _lire(V1), _lire(V2)
    seulement_v1 = sorted(set(v1) - set(v2))
    seulement_v2 = sorted(set(v2) - set(v1))
    communs = sorted(set(v1) & set(v2))

    print("══════════════════════════════════════════════════════")
    print(f"  COMPARATEUR PONT v1 (onglets) / v2 (tracker)")
    print(f"  v1 : {len(v1)} lignes · v2 : {len(v2)} lignes · "
          f"communes : {len(communs)}")
    if seulement_v1:
        print(f"  ⚠️ {len(seulement_v1)} uuid SEULEMENT en v1 — ex : "
              + ", ".join(u[:8] for u in seulement_v1[:5]))
    if seulement_v2:
        print(f"  ℹ️ {len(seulement_v2)} uuid SEULEMENT en v2 — ex : "
              + ", ".join(u[:8] for u in seulement_v2[:5]))

    total_identite = 0
    familles = [("IDENTITE (0 ecart exige — compte au verdict)", IDENTITE),
                ("SOURCE (tracker fait foi — non bloquant)", SOURCE)]
    if ADOPTE:
        familles.append(
            ("ADOPTE (chaine fait foi — hors verdict, ecart VOULU)", ADOPTE))
    familles.append(("VIVANTES (drift temporel tolere)", VIVANTES))
    for fam, cols in familles:
        print(f"  ── {fam} " + "─" * max(40 - len(fam), 3))
        for col in cols:
            diffs: List[str] = [u for u in communs
                                if not _egal(col, v1[u].get(col, ""),
                                             v2[u].get(col, ""))]
            if col in IDENTITE:
                total_identite += len(diffs)
            pct = 100.0 * len(diffs) / max(len(communs), 1)
            marque = " " if not diffs else \
                ("⚠️" if col in IDENTITE else
                 ("≠" if col in SOURCE else ("↪" if col in ADOPTE else "≈")))
            print(f"  {marque} {col:<14} {len(diffs):>6} ecart(s) ({pct:.2f} %)")
            if (col in SOURCE or col in ADOPTE) and diffs:
                # Divergences de source ASSUMEES : on regroupe par PAIRE de
                # valeurs — la liste COMPLETE tient en quelques lignes et se
                # relit d'un coup d'oeil a chaque rapport (une paire NOUVELLE
                # qui toucherait une date cle doit se voir tout de suite).
                paires: Dict[tuple, int] = {}
                for u in diffs:
                    p = (v1[u].get(col, ""), v2[u].get(col, ""))
                    paires[p] = paires.get(p, 0) + 1
                haut = sorted(paires.items(), key=lambda x: -x[1])
                for (a, b), n in haut[:40]:
                    print(f"       {n:>5} ×  v1={a!r}  v2={b!r}")
                if len(haut) > 40:
                    print(f"       … et {len(haut) - 40} autre(s) paire(s) "
                          f"distincte(s).")
            else:
                # IDENTITE : un ecart est une ANOMALIE — l'uuid sert a
                # retrouver la ligne fautive. VIVANTES : 3 exemples suffisent.
                for u in diffs[:3]:
                    print(f"       {u[:8]}…  v1={v1[u].get(col, '')!r}  "
                          f"v2={v2[u].get(col, '')!r}")
    print("══════════════════════════════════════════════════════")
    # seuil 0 = TOUT ecart d'identite marque le run (arme depuis que la
    # famille SOURCE ne pollue plus le compte) ; -1 pour desarmer.
    if SEUIL >= 0 and total_identite > SEUIL:
        print(f"⛔ {total_identite} ecart(s) sur les colonnes d'IDENTITE "
              f"(seuil {SEUIL}) — a comprendre avant toute bascule.",
              file=sys.stderr)
        return 1
    print(f"Verdict : {total_identite} ecart(s) d'identite. La bascule ne "
          f"se decide que sur plusieurs rapports consecutifs propres "
          f"(identite a 0 ET atl/ath effondres apres le daily post-reparation).",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
