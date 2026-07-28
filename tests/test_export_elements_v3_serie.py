# ⚠️ DEPOT : VeVePreda/scrapeur-veve
# CHEMIN : tests/test_export_elements_v3_serie.py

"""La 17e colonne : la SERIE on-chain.

Defaut reel corrige ici (28/07/2026) : `catalogue_from_instance` CALCULAIT la
serie (`md.series`) et l'export la JETAIT — elle ne servait qu'au MAX-par-serie
des comics. Or c'est la colonne qui commande les adresses des 15 sites
(`/comics/<slug(serie)>/<rarete>/`). Sans elle, pipeline 2 ne peut pas basculer,
et aucune moisson supplementaire n'y aurait rien change.
"""
import csv

import pytest

from scraper.export_elements_v3 import (
    ENTETE, OFFCHAIN_COLS, charger_graine, combler_series, construire_v3,
    ecrire, reattacher_offchain,
)

SEIZE = ["veve_uuid", "series_uuid", "name", "category", "rarity",
         "edition_type", "supply", "first_public", "listings", "note",
         "brand", "licensor", "atl", "atl_date", "ath", "ath_date"]


def brut(uid, cat="comic", **kw):
    d = {"veve_uuid": uid, "category": cat, "name": "Storm Vol. 5 #2",
         "rarity": "COMMON", "edition_type": "1", "supply": 1000,
         "brand": "Storm Vol. 5", "licensor": "Marvel", "series": "Storm Vol. 5"}
    d.update(kw)
    return d


def ligne16(uid, cat="comic", brand="Storm Vol. 5"):
    """Une ligne de GRAINE ecrite AVANT le patch : 16 colonnes, pas de serie."""
    r = dict.fromkeys(SEIZE, "")
    r.update(veve_uuid=uid, category=cat, brand=brand, name=f"{brand} #1 (2024)")
    return [r[c] for c in SEIZE]


# --- l'en-tete -------------------------------------------------------------

def test_serie_ajoutee_en_FIN_sans_toucher_aux_16_premieres():
    # Les 16 premieres colonnes doivent rester dans le MEME ordre : les index
    # de `reattacher_offchain` sont positionnels.
    assert ENTETE[:16] == SEIZE
    assert ENTETE[16] == "series" and len(ENTETE) == 17


def test_les_index_offchain_restent_valides():
    for c in OFFCHAIN_COLS:
        assert ENTETE.index(c) == SEIZE.index(c)


# --- l'export ecrit bien la serie ------------------------------------------

def test_construire_v3_ecrit_la_serie_de_la_chaine():
    rows = construire_v3({"u1": brut("u1")}, {})
    assert rows[0][ENTETE.index("series")] == "Storm Vol. 5"


def test_la_serie_dun_collectible_est_celle_de_la_chaine_pas_sa_marque():
    # Pour un collectible, `brand` != serie. C'est tout l'interet de la colonne.
    rows = construire_v3(
        {"u1": brut("u1", cat="collectible", brand="Marvel",
                    series="Cover Girls S1")}, {})
    assert rows[0][ENTETE.index("series")] == "Cover Girls S1"
    assert rows[0][ENTETE.index("brand")] == "Marvel"


# --- le comblage sans remoissonner -----------------------------------------

def test_un_comic_sans_serie_est_comble_depuis_brand():
    # Preuve : dans `catalogue_from_instance`, `brand = series` pour un comic —
    # meme variable, donc meme texte. Ce n'est pas une approximation.
    rows = [ligne16("u1", brand="Daredevil Vol. 9")]
    assert combler_series(rows) == 1
    assert rows[0][ENTETE.index("series")] == "Daredevil Vol. 9"


def test_un_collectible_sans_serie_nest_JAMAIS_devine():
    # `brand` y vaut md.brand : s'en servir deplacerait 92,4 % des adresses de
    # collectibles pour rien (mesure du 28/07). Vide = le consommateur retombe
    # sur le Sheet, qui coincide avec la chaine a 100 % pour les collectibles.
    rows = [ligne16("u1", cat="collectible", brand="Marvel")]
    assert combler_series(rows) == 0
    assert rows[0][ENTETE.index("series")] == ""


def test_une_serie_deja_presente_nest_jamais_ecrasee():
    r = ligne16("u1", brand="Autre") + ["Vraie Serie"]
    assert combler_series([r]) == 0
    assert r[ENTETE.index("series")] == "Vraie Serie"


def test_une_ligne_a_16_colonnes_est_complétée_a_17():
    r = ligne16("u1")
    assert len(r) == 16
    combler_series([r])
    assert len(r) == 17


def test_un_comic_sans_brand_reste_vide_plutot_que_faux():
    rows = [ligne16("u1", brand="")]
    assert combler_series(rows) == 0
    assert rows[0][ENTETE.index("series")] == ""


def test_le_comblage_est_idempotent():
    rows = [ligne16("u1")]
    assert combler_series(rows) == 1
    assert combler_series(rows) == 0


# --- le point de passage unique --------------------------------------------

def test_ecrire_applique_le_comblage(tmp_path):
    # `ecrire` est le SEUL chemin d'ecriture (flush de secours compris) : aucun
    # code ne doit pouvoir produire un CSV a la serie trouee.
    p = tmp_path / "v3.csv"
    ecrire([ligne16("u1", brand="Punisher Vol. 15")], str(p))
    lu = list(csv.DictReader(p.open(encoding="utf-8")))
    assert lu[0]["series"] == "Punisher Vol. 15"
    assert list(lu[0].keys())[:16] == SEIZE


def test_une_graine_a_16_colonnes_se_relit_et_se_comble(tmp_path):
    # Le cas REEL : le elements_v3.csv publie avant le patch.
    p = tmp_path / "graine.csv"
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(SEIZE)
        w.writerow(ligne16("u1", brand="Gargoyles Vol. 1"))
    graine = charger_graine(str(p))
    rows = list(graine.values())
    assert combler_series(rows) == 1
    assert rows[0][ENTETE.index("series")] == "Gargoyles Vol. 1"


def test_reattacher_offchain_vise_toujours_les_bonnes_colonnes():
    r = construire_v3({"u1": brut("u1")}, {})[0]
    reattacher_offchain([r], {"u1": {c: f"<{c}>" for c in OFFCHAIN_COLS}})
    for c in OFFCHAIN_COLS:
        assert r[ENTETE.index(c)] == f"<{c}>"
    assert r[ENTETE.index("series")] == "Storm Vol. 5"   # non ecrasee
