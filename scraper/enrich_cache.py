# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/enrich_cache.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""🗃️ LE CACHE FICHIER D'ENRICHISSEMENT — etape 4 du chantier « pont elements ».

POURQUOI (rappel du chantier)
-----------------------------
Le builder v2 (export_elements_v2) fabrique elements_v2.csv depuis le TRACKER,
SAUF deux colonnes ENTIERES (supply, first_public) + un texte d'identite
(edition_type) qu'il lisait encore dans les onglets froids 🔵C-COLLECTIBLE /
🟢C-COMICS. C'etait le DERNIER endroit ou des nombres relus par du code avaient
une CELLULE pour source de verite (la famille des ×100, des 429, des 503).

Ce module remplace cette lecture par un fichier LOCAL, data/enrichissement.csv,
qui n'est PLUS une cellule Sheet :
  * SEED unique depuis les onglets (scraper.seed_enrichissement, simulate-first
    comme repare_atl_ath) ;
  * MAINTENU par le daily : sheets.sync_catalogue projette dans ce fichier les
    MEMES records normalises qu'il ecrit dans les onglets — zero requete Sheets
    en plus, zero logique dupliquee, la valeur du cache est par construction
    celle de l'onglet ;
  * LU par le builder v2 (lire_enrichissement).

LE CONTRAT DU FICHIER
---------------------
Colonnes : veve_uuid, series_uuid, supply, first_public, edition_type.
  * supply / first_public : ENTIERS (0 = inconnu, comme les onglets — le ×100
    ne mordait que les decimales, ces deux colonnes sont entieres) ;
  * series_uuid / edition_type : TEXTE.

`charger()` rend EXACTEMENT le dict que l'ancienne lecture d'onglets rendait
({uuid -> {supply, first_public, series_uuid, edition_type}}), donc le builder
v2 produit la MEME sortie — l'identite du comparateur reste a 0 apres bascule.

LA MISE A JOUR EST NON DESTRUCTIVE
----------------------------------
`maj_depuis_records()` fait de l'AJOUT / de la REECRITURE par uuid, JAMAIS de
suppression :
  * un uuid inconnu est ajoute ;
  * une valeur FRAICHE et non vide remplace l'ancienne (reecriture) ;
  * une valeur vide (ou 0 pour les nombres) NE remplace JAMAIS une valeur connue
    — meme regle idempotente que sheets._fill_new_cold ; un item retire du
    tracker garde donc son enrichissement.

Env : ENRICH_CACHE (defaut data/enrichissement.csv).
"""

from __future__ import annotations

import csv
import os
from typing import Any, Dict, Iterable, List

CACHE_PATH = os.environ.get("ENRICH_CACHE", "data/enrichissement.csv")

ENTETE = ["veve_uuid", "series_uuid", "supply", "first_public", "edition_type"]
# Champs porteurs (tout sauf la cle) — l'ordre de la mise a jour non destructive.
CHAMPS = ["series_uuid", "supply", "first_public", "edition_type"]
# Les deux colonnes ENTIERES : pour elles, 0 == inconnu (jamais un ecrasement).
NUM_CHAMPS = {"supply", "first_public"}


def _num(x) -> int:
    """Entier tolerant a la locale FR (meme fonction que export_elements_v2)."""
    try:
        return int(float(str(x).replace(",", ".").replace(" ", "")
                         .replace(" ", "") or 0))
    except (TypeError, ValueError):
        return 0


def _extraire(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Un enregistrement de catalogue (record normalise OU ligne d'onglet) ->
    les 5 colonnes du cache. La 1re edition publique vit sous le nom
    `first_available_edition` dans les onglets/records ; on la range sous
    `first_public` (le nom que le builder v2 attend)."""
    return {
        "veve_uuid": str(rec.get("veve_uuid") or "").strip(),
        "series_uuid": str(rec.get("series_uuid") or "").strip(),
        "supply": _num(rec.get("supply")),
        "first_public": _num(rec.get("first_available_edition")),
        "edition_type": str(rec.get("edition_type") or "").strip(),
    }


def _vide(champ: str, valeur: Any) -> bool:
    """Une valeur « inconnue » qui ne doit jamais ecraser une valeur connue.
    Pour les deux colonnes entieres, 0 vaut inconnu (aligne sur _fill_new_cold,
    qui remplit des que `not rec.get('supply')`)."""
    if champ in NUM_CHAMPS:
        return _num(valeur) == 0
    return str(valeur or "").strip() == ""


def charger(path: str = None) -> Dict[str, Dict[str, Any]]:
    """{uuid -> {series_uuid, supply(int), first_public(int), edition_type}}.

    Rend le MEME dict que l'ancienne lecture d'onglets de export_elements_v2 :
    supply/first_public en entiers, series_uuid/edition_type en texte."""
    path = path or CACHE_PATH
    out: Dict[str, Dict[str, Any]] = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            uid = str(r.get("veve_uuid") or "").strip()
            if not uid:
                continue
            out[uid] = {
                "series_uuid": str(r.get("series_uuid") or "").strip(),
                "supply": _num(r.get("supply")),
                "first_public": _num(r.get("first_public")),
                "edition_type": str(r.get("edition_type") or "").strip(),
            }
    return out


def maj_depuis_records(records: Iterable[Dict[str, Any]],
                       path: str = None,
                       simuler: bool = False) -> Dict[str, int]:
    """Fusionne des records de catalogue dans le cache (ajout / reecriture par
    uuid, jamais de suppression) et reecrit le fichier — sauf en simulation.

    `records` : un iterable de dicts portant au moins veve_uuid, series_uuid,
    supply, first_available_edition, edition_type (les records normalises de
    sync_catalogue, ou les lignes d'onglet lues par le seed)."""
    path = path or CACHE_PATH
    cache = charger(path)
    stats = {"avant": len(cache), "ajouts": 0, "reecritures": 0,
             "inchanges": 0, "vus": 0}
    for rec in records:
        e = _extraire(rec)
        uid = e["veve_uuid"]
        if not uid:
            continue
        stats["vus"] += 1
        old = cache.get(uid)
        if old is None:
            cache[uid] = {c: e[c] for c in CHAMPS}
            stats["ajouts"] += 1
            continue
        change = False
        for c in CHAMPS:
            neuf = e[c]
            if _vide(c, neuf):
                continue                      # jamais ecraser un connu par du vide
            neuf = _num(neuf) if c in NUM_CHAMPS else neuf
            if str(old.get(c, "")) != str(neuf):
                old[c] = neuf
                change = True
        stats["reecritures" if change else "inchanges"] += 1
    stats["apres"] = len(cache)
    if not simuler:
        ecrire(path, cache)
    return stats


def ecrire(path: str, cache: Dict[str, Dict[str, Any]]) -> None:
    """Ecrit le cache, TRIE par veve_uuid — un ordre stable = un diff git minimal
    d'un jour a l'autre (le cache ne bouge que sur les items neufs/re-enrichis)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lignes: List[List[Any]] = []
    for uid in sorted(cache):
        e = cache[uid]
        lignes.append([uid, e.get("series_uuid", ""),
                       _num(e.get("supply")), _num(e.get("first_public")),
                       e.get("edition_type", "")])
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(ENTETE)
        w.writerows(lignes)
