# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve · CHEMIN : tests/test_divergences_arbitrees.py

"""🔎 LE GARDE-FOU DES DIVERGENCES ARBITREES — demande de Preda, 05/08/2026.

    « priorite a la chaine, ET une passe de verification VeVe a l'occasion,
      garde-fou pour ceux deja connus. »

⭐⭐⭐ CE QUI A DECLENCHE CE BANC, DIT PAR PREDA : « Tiny Jones a ete droppe en
SECRET_RARE mais VeVe a corrige en COMMON ». La chaine dit l'HISTOIRE (la
rarete gravee au mint), le Sheet dit l'ETAT (ce que VeVe affiche aujourd'hui).
LES DEUX SONT VRAIES, A DES MOMENTS DIFFERENTS.

⭐⭐ CE N'EST DONC PAS UNE DIVERGENCE, C'EST UNE CHRONOLOGIE. Aucun taux de
concordance ne peut faire la difference : « 99,96 % » s'imprime exactement
pareil que la source ait tort ou que le temps ait passe. Ma mesure 3.1 les
comptait comme des erreurs ; c'est Preda qui a su que c'en etait une correction.
⭐⭐⭐ UNE MESURE DIT L'ECART, ELLE NE DIT JAMAIS LEQUEL DES DEUX A BOUGE.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
from scraper import identite as ID                        # noqa: E402

TABLE = os.path.join(RACINE, "data", "divergences_arbitrees.json")
U1 = "11111111-1111-1111-1111-111111111111"
U2 = "22222222-2222-2222-2222-222222222222"


def _sheet(uid, **kw):
    base = {"rarity": "COMMON", "licensor": "Marvel", "edition_type": "FE",
            "kind": "Collectible", "tirage": "3000"}
    base.update(kw)
    return {uid: base}


def _chaine(uid, **kw):
    base = {"rarity": "COMMON", "licensor": "Marvel", "edition_type": "FE",
            "category": "collectible", "supply": "3000"}
    base.update(kw)
    return {uid: base}


# ---------------------------------------------------------------------------
# 1. Les trois etats
# ---------------------------------------------------------------------------

def test_une_divergence_ARBITREE_est_silencieuse():
    """⭐⭐⭐ UN AVERTISSEMENT QUI SE DECLENCHE SUR LE CAS NORMAL EST DU BRUIT,
    ET LE BRUIT SE LIT COMME DU SILENCE. Les 7 rarity s'impriment a chaque run
    depuis le 28/07 : au bout d'une semaine plus personne ne les lit, et le jour
    ou ce sera 8 personne ne le verra."""
    arb = {U1: {"rarity": {"sheet": "COMMON", "chaine": "SECRET_RARE"}}}
    d = ID.comparer_divergences(_sheet(U1), _chaine(U1, rarity="SECRET_RARE"),
                                arb)
    assert len(d["connues"]) == 1 and not d["neuves"] and not d["resorbees"]
    txt = ID.rapport_divergences(d)
    assert "1 connue" in txt
    assert U1[:8] not in txt, "un cas arbitre ne doit pas etre NOMME"


def test_une_divergence_NEUVE_est_nommee():
    """Le cas qui compte : une rarete qui diverge sans avoir ete tranchee."""
    d = ID.comparer_divergences(_sheet(U1), _chaine(U1, rarity="ULTRA_RARE"),
                                {})
    assert len(d["neuves"]) == 1
    txt = ID.rapport_divergences(d)
    assert U1[:8] in txt and "NEUVE" in txt
    assert "'COMMON'" in txt and "'ULTRA_RARE'" in txt


def test_une_divergence_RESORBEE_est_nommee_aussi():
    """⭐⭐ LA DISPARITION D'UN ECART EST UNE INFORMATION, PAS UN RETOUR A LA
    NORMALE. Si VeVe re-corrige Tiny Jones en SECRET_RARE, les deux sources
    redeviennent d'accord — et c'est exactement le moment ou il faut le savoir,
    parce que la table d'arbitrage vient de se perimer.
    ⛔ Un garde-fou qui ne surveille que l'apparition laisse la table pourrir."""
    arb = {U1: {"rarity": {"sheet": "COMMON", "chaine": "SECRET_RARE"}}}
    d = ID.comparer_divergences(_sheet(U1, rarity="SECRET_RARE"),
                                _chaine(U1, rarity="SECRET_RARE"), arb)
    assert len(d["resorbees"]) == 1 and not d["connues"] and not d["neuves"]
    assert "RESORBEE" in ID.rapport_divergences(d)


# ---------------------------------------------------------------------------
# 2. Ce qui ne doit PAS compter comme une divergence
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("col,a,b", [
    ("rarity", "SECRET RARE", "SECRET_RARE"),      # l'espace du Sheet
    ("kind", "Comic", "comic"),                     # la casse
    ("edition_type", "#131", "131"),                # le prefixe des comics
])
def test_un_ecart_de_FORME_n_est_pas_une_divergence(col, a, b):
    """⛔ Sans cette normalisation, le rapport rouvrirait a chaque run 19 000
    faux ecarts — et la vraie divergence s'y noierait.
    ⭐ La normalisation est DECLAREE dans `_NORME_DIV`, colonne par colonne :
    une normalisation muette est une main sur la balance."""
    dst = {"rarity": "rarity", "kind": "kind", "edition_type": "edition_type"}
    src = {"rarity": "rarity", "kind": "category",
           "edition_type": "edition_type"}
    d = ID.comparer_divergences({U1: {dst[col]: a}}, {U1: {src[col]: b}}, {},
                                colonnes=(col,))
    assert not d["neuves"], f"{a!r} vs {b!r} compte a tort comme une divergence"


def test_un_VIDE_n_est_pas_un_desaccord():
    """⭐ Un trou n'est pas une opinion contraire. La chaine muette sur 619
    `edition_type` ne conteste rien — et `fusionner` ne la laissera d'ailleurs
    pas ecraser le Sheet."""
    d = ID.comparer_divergences(_sheet(U1), _chaine(U1, rarity=""), {})
    assert not d["neuves"]
    d2 = ID.comparer_divergences(_sheet(U1, rarity=""), _chaine(U1), {})
    assert not d2["neuves"]


def test_un_item_ABSENT_de_la_chaine_est_ignore():
    """La chaine ne connait rien avant le premier mint : un drop a venir n'est
    pas une divergence."""
    d = ID.comparer_divergences(_sheet(U1), {}, {})
    assert not any(d.values())


# ---------------------------------------------------------------------------
# 3. La table livree
# ---------------------------------------------------------------------------

def test_la_table_livree_est_lisible_et_complete():
    arb = ID.charger_arbitrees(TABLE)
    assert arb, f"{TABLE} illisible ou vide"
    cols = {c for v in arb.values() for c in v}
    assert {"rarity", "licensor", "edition_type"} <= cols
    n = sum(len(v) for v in arb.values())
    assert n >= 100, f"seulement {n} divergences arbitrees"
    for uid, par_col in arb.items():
        for col, info in par_col.items():
            assert info.get("sheet") and info.get("chaine"), (
                f"{uid[:8]} {col} : une entree sans les deux valeurs ne permet "
                f"pas de detecter une RESORPTION")


def test_la_table_ne_couvre_PAS_name_brand_series():
    """⛔⛔ LA LIMITE DU DISPOSITIF, EN DUR. Sur `name` (~8 080 divergences),
    `brand` (~4 270) et `series` (16 418), une table de cas connus contiendrait
    la moitie du catalogue : elle ne signalerait plus rien, elle SERAIT la
    donnee.
    ⭐⭐ UN GARDE-FOU DE CAS CONNUS NE FONCTIONNE QUE LA OU LES CAS SONT RARES.
    Ces colonnes-la sont surveillees par le PLAFOND DE CHURN, qui mesure
    l'ampleur au lieu d'enumerer les cas."""
    cols = {c for v in ID.charger_arbitrees(TABLE).values() for c in v}
    for interdite in ("name", "brand", "series"):
        assert interdite not in cols, (
            f"`{interdite}` ne doit pas entrer dans la table : sa divergence "
            f"porte sur des milliers de lignes. C'est PLAFONDS_CHURN qui la "
            f"surveille.")


def test_une_table_ABSENTE_rend_tout_NEUF_et_ne_leve_pas():
    """⭐ Un fichier manquant doit rendre le rapport BRUYANT, jamais MUET.
    ⛔ L'inverse — se taire faute de table — serait le pire des deux etats."""
    assert ID.charger_arbitrees("/tmp/_inexistant_.json") == {}
    d = ID.comparer_divergences(_sheet(U1), _chaine(U1, rarity="ULTRA_RARE"),
                                ID.charger_arbitrees("/tmp/_inexistant_.json"))
    assert len(d["neuves"]) == 1


def test_le_rapport_ne_cite_pas_TOUT_quand_il_y_en_a_beaucoup():
    """Un rapport de 8 000 lignes ne se lit pas — donc il ne se lit pas."""
    sheet, chaine = {}, {}
    for i in range(50):
        u = f"{i:08d}-0000-0000-0000-000000000000"
        sheet.update(_sheet(u)); chaine.update(_chaine(u, rarity="RARE"))
    txt = ID.rapport_divergences(ID.comparer_divergences(sheet, chaine, {}))
    assert "50 NEUVE" in txt
    assert "et 42 autre(s)" in txt
    assert len(txt.splitlines()) < 15
