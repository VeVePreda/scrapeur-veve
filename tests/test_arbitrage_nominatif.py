# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_arbitrage_nominatif.py
"""⚖️ L'ARBITRAGE DEVIENT UNE DECISION DE CAS, PLUS UNE REGLE DE COLONNE.

⭐⭐⭐ CE QUE LA MESURE DU 06/08 A TROUVE, ET QUI N'EST PAS « L'ARBITRAGE ETAIT
FAUX ». Les 112 cas ont ete reposes a l'API VeVe. Sur les 26 qu'elle accepte de
juger (les 86 autres sont des comics, et la liste blanche refuse `licensor` /
`rarity` / `editionType` sur `publicComicType`) :

    edition_type  15/15  la chaine dit comme VeVe
    licensor       0/7   VeVe dit comme le SHEET

Les deux valeurs sont vraies a des moments differents : la chaine grave le
licencie AU MINT, VeVe affiche celui d'AUJOURD'HUI. Choisir la chaine, c'est
choisir l'histoire — c'est le choix du 05/08, et il reste le defaut.

🔴 CE QUE PERSONNE N'AVAIT MESURE : le catalogue publie porte **7 lignes
« Cartel Entertainment, LLC » ET 6 lignes « Evoke Entertainment » pour la MEME
franchise Creepshow**. La licence a change de mains en cours de serie : la
chaine a raison LIGNE PAR LIGNE, et l'ensemble se contredit.

⭐⭐⭐ **UNE REGLE VRAIE APPLIQUEE LIGNE PAR LIGNE PEUT PRODUIRE UN ENSEMBLE
FAUX.** Un referentiel qui GROUPE a besoin d'UN nom par franchise.

⛔ CE BANC GARDE SURTOUT LE DEFAUT. Une exception nominative est utile ; une
exception qui deborde est une regression silencieuse. La moitie des tests
ci-dessous verifie que RIEN ne change quand l'arbitrage est absent, muet, ou
porte sur une autre colonne.
"""
import json
import os

from scraper.identite import charger_arbitrees, fusionner

SHEET = {"uuid": "u1", "name": "Creepshow Graveyard", "kind": "Comic",
         "licensor": "Evoke Entertainment", "brand": "Creepshow",
         "rarity": "COMMON", "edition_type": "1", "tirage": "500",
         "series": "Creepshow"}
CHAINE = {"name": "Creepshow Graveyard", "category": "comic",
          "licensor": "Cartel Entertainment, LLC", "brand": "Creepshow",
          "rarity": "COMMON", "edition_type": "1", "supply": "500",
          "series": "Creepshow"}


def test_sans_arbitrage_la_chaine_gagne_comme_avant():
    """⛔ LE DEFAUT NE BOUGE PAS. C'est la moitie du lot."""
    assert fusionner(SHEET, CHAINE)["licensor"] == "Cartel Entertainment, LLC"


def test_un_arbitrage_nominatif_fait_gagner_le_sheet():
    r = fusionner(SHEET, CHAINE, arbitrage={"licensor": {"gagnant": "sheet"}})
    assert r["licensor"] == "Evoke Entertainment"


def test_l_arbitrage_ne_deborde_pas_sur_les_autres_colonnes():
    """⭐ Nominatif veut dire UNE colonne. Un arbitrage sur `licensor` qui
    ferait aussi basculer `brand` ou `rarity` serait pire que pas d'arbitrage :
    on croirait n'avoir touche qu'un champ."""
    r = fusionner(SHEET, {**CHAINE, "brand": "AUTRE MARQUE",
                          "rarity": "SECRET_RARE"},
                  arbitrage={"licensor": {"gagnant": "sheet"}})
    assert r["licensor"] == "Evoke Entertainment"
    assert r["brand"] == "AUTRE MARQUE"
    assert r["rarity"] == "SECRET_RARE"


def test_un_gagnant_inconnu_ou_muet_ne_change_rien():
    for arb in ({}, None, {"licensor": {}},
                {"licensor": {"gagnant": "chaine"}},
                {"licensor": {"gagnant": "veve"}},
                {"rarity": {"gagnant": "sheet"}}):
        r = fusionner(SHEET, CHAINE, arbitrage=arb)
        assert r["licensor"] == "Cartel Entertainment, LLC", arb


def test_un_sheet_vide_ne_gagne_jamais_meme_arbitre():
    """⛔ La regle « un trou ne remplace pas une valeur » passe AVANT
    l'arbitrage. Sinon un arbitrage EFFACERAIT une donnee — exactement ce que
    `choisir` existe pour empecher."""
    r = fusionner({**SHEET, "licensor": ""}, CHAINE,
                  arbitrage={"licensor": {"gagnant": "sheet"}})
    assert r["licensor"] == "Cartel Entertainment, LLC"


def test_la_table_livree_porte_les_7_cas_creepshow_et_rien_d_autre():
    """⭐ Le nombre est le garde-fou : si un futur lot pose `gagnant` un peu
    partout, la regle de colonne serait remplacee par une liste, et la liste
    deviendrait la donnee."""
    cas = charger_arbitrees(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "divergences_arbitrees.json"))
    gagnants = [(u, c) for u, v in cas.items() for c, d in v.items()
                if isinstance(d, dict) and d.get("gagnant")]
    assert len(gagnants) == 7, gagnants
    assert {c for _, c in gagnants} == {"licensor"}
    for u, c in gagnants:
        assert cas[u][c]["gagnant"] == "sheet"
        assert cas[u][c]["sheet"] == "Evoke Entertainment"
        assert cas[u][c].get("pourquoi"), "un arbitrage sans raison se relit comme un caprice"


def test_les_cas_de_definition_restent_a_la_chaine():
    """⛔ « Marvel » (Sheet) vs « Star Wars » (chaine) : la chaine est COHERENTE
    avec 316 autres lignes du catalogue, et editeur/franchise est une
    difference de DEFINITION, pas de veracite. On n'y touche pas."""
    cas = charger_arbitrees(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "divergences_arbitrees.json"))
    sw = [v["licensor"] for v in cas.values()
          if v.get("licensor", {}).get("chaine") == "Star Wars"]
    assert sw, "les 5 cas Star Wars ont disparu de la table"
    assert all("gagnant" not in d for d in sw)
