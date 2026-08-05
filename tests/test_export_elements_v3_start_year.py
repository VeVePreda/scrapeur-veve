# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve
# CHEMIN : tests/test_export_elements_v3_start_year.py

"""📅 `start_year` TRAVERSE L'EXPORT — la quatrieme fois dans le meme fichier.

`export_elements_v3.catalogue_from_instance` LISAIT deja `startYear`, s'en
servait pour composer `name` (« serie #numero (annee) »), puis la relachait :
elle n'etait jamais ecrite comme colonne.

⭐⭐ CE QUI SERT DE CLE SERT AUSSI DE VALEUR — le meme motif que `image`,
`ath_date` et `description` avant elle, dans ce meme fichier, dont le
commentaire annonçait deja « TROISIEME FOIS ». Celle-ci etait deux lignes plus
bas.

⭐⭐⭐ REPARER LA COLLECTE NE REPARE PAS L'EXPORT. Le lot 63 a appris a
`collectchain._flatten` a RAMASSER `startYear` (il figure dans `META_GARDES`) —
et la donnee mourait un etage plus loin. CHAQUE ETAGE A SON PROPRE SILENCE, et
celui du second ne ressemble pas a celui du premier : rien a grep, rien a
auditer, juste un `return` qui ne la mentionne pas.

⭐ POURQUOI CE LOT ET PAS PLUS TARD : des 4 colonnes que la mesure 3.1 n'a pas
pu mesurer (`description`, `releaseDate`, `start_year`, `veve_exclusive`), c'est
la SEULE qui n'attend pas une moisson neuve. La donnee arrive deja dans chaque
reponse.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper.export_elements_v3 import (ENTETE, catalogue_from_instance,  # noqa: E402
                                        construire_v3)

URL_COMIC = ("https://d11.cloudfront.net/comic_cover."
             "329e5108-cf13-4fad-96b9-dd06fb2ea78b.a.webp")
URL_COLL = ("https://d11.cloudfront.net/collectible_type_image."
            "11111111-2222-3333-4444-555555555555.a.webp")


def _inst_comic(start_year="2014", **md):
    base = {"rarity": "Rare", "comicNumber": "216",
            "series": "Superior Iron Man", "totalEditions": 5000}
    if start_year is not None:
        base["startYear"] = start_year
    base.update(md)
    return {"image_url": URL_COMIC, "metadata": base}


# ---------------------------------------------------------------------------
# 1. La colonne existe et sort de l'export
# ---------------------------------------------------------------------------

def test_start_year_est_une_colonne_a_part_entiere():
    assert "start_year" in ENTETE
    assert ENTETE.index("start_year") >= 19, (
        "ajoutee EN FIN : `reattacher_offchain` indexe par POSITION, une "
        "insertion au milieu decale les colonnes off-chain.")


def test_catalogue_from_instance_rend_start_year():
    c = catalogue_from_instance(_inst_comic("2014"))
    assert c["start_year"] == "2014"


def test_la_valeur_arrive_jusqua_la_LIGNE_ecrite():
    """⛔ Le contrat ne s'arrete pas au dict : c'est `construire_v3` qui pose
    les colonnes dans l'ordre, et c'est LA que la donnee mourait."""
    c = catalogue_from_instance(_inst_comic("2014"))
    rows = construire_v3({c["veve_uuid"]: c}, {})
    assert len(rows) == 1
    ligne = rows[0]
    assert len(ligne) == len(ENTETE), (
        f"ligne a {len(ligne)} champs pour {len(ENTETE)} colonnes — "
        f"`construire_v3` n'a pas suivi l'entete.")
    assert ligne[ENTETE.index("start_year")] == "2014"


# ---------------------------------------------------------------------------
# 2. On rend la SOURCE, pas son empreinte
# ---------------------------------------------------------------------------

def test_start_year_ne_se_relit_PAS_dans_le_nom_compose():
    """⛔ `name` vaut « Superior Iron Man #1 (2014) » : l'annee y est, et il
    serait tentant de la reextraire. On ne le fait pas.
    ⭐ RELIRE UNE VALEUR DANS LA CHAINE QU'ON VIENT D'EN FABRIQUER, C'EST FAIRE
    CONFIANCE A SON PROPRE FORMATAGE — le jour ou le format du nom change, la
    colonne devient fausse sans qu'une seule ligne de son code ait bouge.

    ⚠️ CE TEST A ETE REECRIT APRES UNE MUTATION QUI LUI A ECHAPPE. Le premier
    cas choisi etait un titre contenant deja « (1973) » avec `startYear=1963` :
    le nom valait « ... (Reprint 1973) #1 (1963) », et une reextraction naive
    (`name.rsplit("(")[-1]`) rendait « 1963 » — LA BONNE VALEUR, PAR HASARD. Le
    test passait, le mutant aussi.
    ⭐⭐⭐ UN CAS DE TEST OU LE BUG DONNE LA BONNE REPONSE NE TESTE RIEN. Il
    faut le cas ou les deux methodes DIVERGENT, pas celui ou elles convergent.

    Le vrai cas discriminant : une serie dont le TITRE porte des parentheses, et
    AUCUN `startYear`. `start_year` doit valoir "" ; une reextraction rendrait
    « 1973) #216 ».
    """
    c = catalogue_from_instance(_inst_comic(None, series="Tarzan (1973)"))
    assert c["name"] == "Tarzan (1973) #216" or c["name"].startswith("Tarzan (1973) #")
    assert c["start_year"] == "", (
        "`start_year` a ete relu dans `name` : le titre contenait deja des "
        "parentheses, et la valeur rendue vient du FORMATAGE, pas de la chaine.")

    # et le sens inverse : `startYear` present fait foi, meme titre a parentheses
    c2 = catalogue_from_instance(_inst_comic(
        "1963", series="Tarzan of the Apes (Reprint 1973)"))
    assert c2["start_year"] == "1963"


# ---------------------------------------------------------------------------
# 3. Le vide reste vide — comics uniquement
# ---------------------------------------------------------------------------

def test_un_collectible_a_start_year_VIDE_et_ce_nest_pas_un_trou():
    """⛔ La chaine ne grave `startYear` que sur les comics. Vide sur un
    collectible n'est pas une donnee manquante, c'est un non-sujet.
    ⭐ Un champ toujours vide sur une population n'est pas un champ mort : il
    faut savoir SUR QUELLE population on le juge."""
    c = catalogue_from_instance({"image_url": URL_COLL,
                                 "metadata": {"name": "Fenrir",
                                              "rarity": "Ultra Rare",
                                              "editionType": "FE"}})
    assert c["category"] == "collectible"
    assert c["start_year"] == ""


@pytest.mark.parametrize("valeur", [None, "", "   "])
def test_un_comic_sans_startYear_donne_du_VIDE_jamais_le_mot_None(valeur):
    """⭐ `None` recopie en CSV s'ecrit « None » — une chaine non vide qui passe
    tous les tests de presence. Un trou doit RESTER un trou."""
    c = catalogue_from_instance(_inst_comic(valeur))
    assert c["start_year"] == ""
    assert c["start_year"] is not None


def test_sans_startYear_le_nom_ne_porte_pas_de_parentheses_vides():
    """Garde-fou de non-regression : meme motif que le `#` sans numero, qui
    avait fabrique 76 noms comme « DuckTales # (2024) »."""
    c = catalogue_from_instance(_inst_comic(None))
    assert "()" not in c["name"]
    assert c["name"] == "Superior Iron Man #216"


# ---------------------------------------------------------------------------
# 4. Compatibilite ascendante
# ---------------------------------------------------------------------------

def test_une_graine_ECRITE_AVANT_ce_lot_reste_lisible(tmp_path):
    """⭐ Un fichier `elements_v3.csv` d'hier n'a pas la colonne. `charger_graine`
    lit par NOM et doit rendre "" — pas lever, pas decaler."""
    from scraper.export_elements_v3 import charger_graine
    ancienne = [c for c in ENTETE if c != "start_year"]
    p = tmp_path / "graine.csv"
    p.write_text(",".join(ancienne) + "\n"
                 + ",".join(["x"] * len(ancienne)).replace(
                     "x", "11111111-2222-3333-4444-555555555555", 1) + "\n",
                 encoding="utf-8")
    g = charger_graine(str(p))
    ligne = next(iter(g.values()))
    assert len(ligne) == len(ENTETE)
    assert ligne[ENTETE.index("start_year")] == ""
