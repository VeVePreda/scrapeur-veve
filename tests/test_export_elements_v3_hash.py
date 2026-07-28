# ⚠️ DEPOT : VeVePreda/scrapeur-veve
# CHEMIN : tests/test_export_elements_v3_hash.py

"""Le `#` orphelin — un separateur sans ce qu'il separe.

`catalogue_from_instance` compose le nom d'un comic en `{serie} #{numero}
({annee})`. Quand la chaine ne porte pas de `comicNumber`, le `#` restait :
**76 lignes** au 28/07/2026 (52 libelles distincts), toutes des comics, toutes
a `edition_type` vide — c'est le MEME trou vu deux fois.

⚠️ CE QUE CE CORRECTIF NE FAIT PAS : changer les adresses. La vraie `slugify`
de `veve-sites/engine/lib/dataset.mjs` reduit `[^a-z0-9]+` a un seul tiret, donc
'DuckTales # (2024)' donne DEJA `ducktales-2024` — identique a la version
corrigee. Le `duck-tales--2024` qu'on redoutait n'existe pas. C'est un defaut
d'AFFICHAGE (cartes Discord, titres, newsletters). Le dire evite de recommencer
a le croire.
"""
import csv

import pytest

from scraper.export_elements_v3 import (
    ENTETE, catalogue_from_instance, corriger_hash_orphelin, ecrire,
)

I_NOM, I_CAT = ENTETE.index("name"), ENTETE.index("category")


def ligne(nom, cat="comic"):
    r = [""] * len(ENTETE)
    r[0], r[I_CAT], r[I_NOM] = "u1", cat, nom
    return r


def inst(comic_no, annee="2024", serie="DuckTales"):
    return {"image_url": "x/comic_cover.0f0e0d0c-0b0a-0908-0706-050403020100.jpg",
            "metadata": {"series": serie, "comicNumber": comic_no,
                         "startYear": annee, "rarity": "Common",
                         "totalEditions": 100, "publisher": "Disney"}}


# --- a la SOURCE : on ne compose plus un `#` vide --------------------------

def test_sans_numero_le_hash_ne_sort_plus():
    assert catalogue_from_instance(inst(""))["name"] == "DuckTales (2024)"


def test_sans_numero_ni_annee_le_nom_est_la_serie():
    assert catalogue_from_instance(inst("", ""))["name"] == "DuckTales"


def test_avec_numero_rien_ne_change():
    # L'ecriture normale d'un comic ne doit pas bouger d'un octet.
    assert catalogue_from_instance(inst("7"))["name"] == "DuckTales #7 (2024)"


def test_un_numero_zero_reste_un_numero():
    # '0' est un vrai numero de comic (les #0 existent) — pas un trou.
    assert catalogue_from_instance(inst("0"))["name"] == "DuckTales #0 (2024)"


# --- le RATTRAPAGE des lignes deja ecrites ---------------------------------

@pytest.mark.parametrize("avant,apres", [
    ("DuckTales # (2024)", "DuckTales (2024)"),
    ("Gargoyles Vol. 1 # (2025)", "Gargoyles Vol. 1 (2025)"),
    ("A Man's Skin # (2021)", "A Man's Skin (2021)"),
    ("Bigby Bear #", "Bigby Bear"),
])
def test_le_hash_orphelin_est_retire(avant, apres):
    r = ligne(avant)
    assert corriger_hash_orphelin([r]) == 1
    assert r[I_NOM] == apres


@pytest.mark.parametrize("nom", [
    "Storm Vol. 5 #2 (2024)",
    "Amazing Spider-Man #252 (1963)",
    "Harley Quinn X Elvira  #2 (2025)",   # double espace, mais numero present
    "Metal Hurlant #1",
])
def test_un_hash_SUIVI_dun_numero_nest_jamais_touche(nom):
    r = ligne(nom)
    assert corriger_hash_orphelin([r]) == 0
    assert r[I_NOM] == nom


def test_un_collectible_nest_jamais_touche():
    # Un collectible peut legitimement porter un '#' dans son nom : il ne vient
    # pas d'une composition, il vient de `md.name`.
    r = ligne("Lot # 5 - Prototype", cat="collectible")
    assert corriger_hash_orphelin([r]) == 0


def test_le_correctif_est_idempotent():
    r = ligne("DuckTales # (2024)")
    assert corriger_hash_orphelin([r]) == 1
    assert corriger_hash_orphelin([r]) == 0


def test_un_nom_qui_ne_serait_QUE_un_hash_est_laisse_tel_quel():
    # Vider un nom serait pire que le laisser laid : le consommateur perdrait
    # sa cle d'affichage. On ne remplace jamais un defaut par un trou.
    r = ligne("#")
    assert corriger_hash_orphelin([r]) == 0
    assert r[I_NOM] == "#"


def test_ecrire_applique_le_correctif(tmp_path):
    # `ecrire` est le point de passage UNIQUE : aucun chemin de code ne doit
    # pouvoir produire un CSV a `#` orphelin.
    p = tmp_path / "v3.csv"
    ecrire([ligne("DuckTales # (2024)")], str(p))
    lu = list(csv.DictReader(p.open(encoding="utf-8")))
    assert lu[0]["name"] == "DuckTales (2024)"


# --- la mesure, pour qu'elle ne se re-invente pas --------------------------

def test_le_correctif_ne_change_PAS_le_slug_des_sites():
    """La preuve, portee par un test : meme slug avant et apres.

    C'est la seule facon de ne pas re-ecrire un jour « le `#` casse les URL ».
    Regle recopiee de veve-sites/engine/lib/dataset.mjs.
    """
    import re as _re

    def slugify(s):
        s = _re.sub(r"[^a-z0-9]+", "-", str(s).lower())
        return _re.sub(r"^-+|-+$", "", s)[:60] or "item"

    for avant, apres in [("DuckTales # (2024)", "DuckTales (2024)"),
                         ("Sonja Reborn # (2025)", "Sonja Reborn (2025)")]:
        assert slugify(avant) == slugify(apres)
