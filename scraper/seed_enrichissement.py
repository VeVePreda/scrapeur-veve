# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/seed_enrichissement.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""🌱 SEED DU CACHE D'ENRICHISSEMENT — une fois (etape 4 du chantier pont elements).

Lit UNE fois les onglets froids 🔵C-COLLECTIBLE / 🟢C-COMICS et en fige les
colonnes d'enrichissement (supply, first_public, edition_type, series_uuid)
dans data/enrichissement.csv. A partir de la, le builder v2 lit ce fichier au
lieu des onglets, et le daily le maintient (sheets.sync_catalogue).

C'est une PROJECTION a l'identique : on lit exactement les memes colonnes, avec
la meme normalisation, que l'ancienne lecture d'onglets de export_elements_v2.
Le cache seede rend donc au builder v2 le MEME dict qu'avant -> l'identite du
comparateur v1/v2 reste a 0.

MODE D'EMPLOI (regle du projet : on regle en simulation, jamais en public)
--------------------------------------------------------------------------
  ENRICH_SEED_SIMULER=1 (defaut via le workflow) : tout est lu et calcule, RIEN
  n'est ecrit ; le rapport dit exactement ce que contiendrait le cache. Relancer
  avec simuler=non pour ecrire data/enrichissement.csv (le workflow le commite).

⚠️ Le sandbox n'a PAS d'acces Google : ce module tourne sur GitHub Actions
(workflow enrich-seed), comme repare_atl_ath.

Env : GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID, ENRICH_SEED_SIMULER, ENRICH_CACHE.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List

from scraper import enrich_cache

SIMULER = os.environ.get("ENRICH_SEED_SIMULER", "1").strip().lower() not in (
    "0", "non", "false")


def lire_onglets(sh) -> List[Dict[str, Any]]:
    """Les lignes des deux onglets froids, telles que le builder v2 les lisait.

    On reprend _lire de export_elements (get_all_values + ancrage des en-tetes,
    JAMAIS get_all_records qui explose sur des en-tetes en double) plutot que
    d'ecrire une deuxieme lecture — deux lectures de la meme page, c'est une qui
    ment."""
    from scraper.sheets import COLLECT_TAB, COMICS_TAB
    from scraper.export_elements import _lire
    lignes: List[Dict[str, Any]] = []
    for tab in (COMICS_TAB, COLLECT_TAB):
        part = _lire(sh.worksheet(tab), "veve_uuid")
        print(f"  {tab} : {len(part)} ligne(s).", flush=True)
        lignes.extend(part)
    return lignes


def _rapport(records: List[Dict[str, Any]]) -> None:
    """Ce que contiendra le cache — les compteurs sont le seul signal qu'on aura
    (un zero se remarque)."""
    vus, avec_s, avec_fp, avec_et, avec_serie = set(), 0, 0, 0, 0
    for r in records:
        e = enrich_cache._extraire(r)
        uid = e["veve_uuid"]
        if not uid:
            continue
        vus.add(uid)
        avec_s += 1 if e["supply"] else 0
        avec_fp += 1 if e["first_public"] else 0
        avec_et += 1 if e["edition_type"] else 0
        avec_serie += 1 if e["series_uuid"] else 0
    print(f"  cache projete : {len(vus)} uuid uniques · {avec_s} avec supply · "
          f"{avec_fp} avec 1re edition publique · {avec_et} avec edition_type · "
          f"{avec_serie} avec series_uuid.", flush=True)
    if not len(vus):
        print("⚠️ 0 uuid — onglets illisibles ? Rien ne sera ecrit.",
              file=sys.stderr)


def main() -> int:
    sid = os.environ.get("SHEET_ID")
    if not sid:
        print("SHEET_ID manquant.", file=sys.stderr)
        return 2
    print(("🌱 SIMULATION (ENRICH_SEED_SIMULER=1) : tout est lu, RIEN n'est "
           "ecrit." if SIMULER else
           "✍️ ECRITURE REELLE : data/enrichissement.csv va etre (re)ecrit."),
          flush=True)

    from scraper.export_elements import _retry
    from scraper.sheets import _client
    sh = _retry("ouverture du Sheet", lambda: _client().open_by_key(sid))
    records = _retry("lecture des onglets froids", lambda: lire_onglets(sh))
    if not records:
        print("⛔ onglets vides — on ne touche a RIEN.", file=sys.stderr)
        return 3

    _rapport(records)
    stats = enrich_cache.maj_depuis_records(records, simuler=SIMULER)
    print(f"  {'[SIMULATION] ' if SIMULER else ''}cache : {stats['avant']} "
          f"avant -> {stats['apres']} apres · {stats['ajouts']} ajout(s) · "
          f"{stats['reecritures']} reecriture(s) · {stats['inchanges']} "
          f"inchange(s).", flush=True)
    if SIMULER:
        print("  [SIMULATION — rien n'a ete ecrit. Relancer avec simuler=non "
              "pour ecrire le cache.]", flush=True)
    else:
        print(f"🌱 cache ecrit -> {enrich_cache.CACHE_PATH}", flush=True)
    print("Etape suivante : lancer « Pont elements v2 (double en silence) » — "
          "le builder v2 lit desormais le cache ; le comparateur doit rester a "
          "0 ecart d'identite.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
