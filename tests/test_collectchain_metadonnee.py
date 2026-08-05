# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve · CHEMIN : tests/test_collectchain_metadonnee.py

"""🔗 LA METADONNEE ON-CHAIN — le banc qui empeche le 5e oubli.

Quatre fois de suite, une donnee « manquante » etait deja dans la reponse :
`supply` (13/07), `veve_comic_name` (01/08), `editions_in_circulation` (05/08),
puis les six champs de metadonnee que `_flatten` laissait tomber (05/08).

⭐⭐⭐ **UN CHAMP NEUF DANS LA REPONSE DOIT FAIRE ECHOUER LE BANC, PAS
DISPARAITRE EN SILENCE.** Un champ jete par une liste noire se retrouve en
cherchant la liste. Un champ simplement **non recopie** par un `return {}` ne
laisse AUCUNE trace : rien a grep, rien a auditer. C'est pour ca que le contrat
est ici, en dur, et pas dans un commentaire.

Le jour ou VeVe ajoute un champ a sa metadonnee, ce banc le NOMME.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper import collectchain as cc                     # noqa: E402

# La metadonnee telle que l'API CollectScan la livre — RELEVEE le 05/08/2026 sur
# https://collectscan.com/api/v2/tokens/<contrat>/transfers (collectibles ET
# comics : l'union des deux, un comic porte comicNumber/startYear la ou un
# collectible porte editionType).
META_RELEVEE_LE_0508 = {
    "brand", "description", "dropDate", "edition", "editionType", "image",
    "licensor", "mintDate", "name", "rarity", "series", "totalEditions",
    "comicNumber", "startYear",
}


def _transfert(md, frm="0xaaa", to="0xbbb", image="collectible_type_image."
               "11111111-2222-3333-4444-555555555555.x.webp"):
    """Un transfert brut, au format exact de l'API."""
    return {
        "timestamp": "2026-07-09T12:00:00.000000Z",
        "block_number": 1, "log_index": 0, "transaction_hash": "0xdead",
        "from": {"hash": frm}, "to": {"hash": to},
        "total": {"token_id": "424242",
                  "token_instance": {"image_url": image, "metadata": md}},
    }


def test_AUCUN_champ_de_la_chaine_ne_disparait_sans_raison():
    """LE BANC CENTRAL. Tout champ livre par VeVe doit etre soit GARDE, soit
    ECARTE **avec un motif ecrit**. Un champ qui n'est ni l'un ni l'autre est un
    oubli — et c'est la faute qu'on a payee quatre fois."""
    connus = cc.META_GARDES | set(cc.META_ECARTES)
    orphelins = META_RELEVEE_LE_0508 - connus
    assert not orphelins, (
        f"champ(s) de metadonnee ni gardes ni ecartes : {sorted(orphelins)}. "
        f"Les ajouter a META_GARDES, ou a META_ECARTES **avec la raison**.")
    for champ, raison in cc.META_ECARTES.items():
        assert raison.strip(), f"« {champ} » est ecarte sans motif ecrit."


def test_les_six_champs_ramasses_arrivent_bien_dans_le_record():
    """Ceux que `_flatten` jetait jusqu'au 05/08. Un par un, nommes : si l'un
    saute a la prochaine refonte, on saura LEQUEL."""
    r = cc._flatten(_transfert({
        "name": "Fenrir", "rarity": "Ultra Rare", "series": "VeVe D&D",
        "totalEditions": 3000, "edition": 12,
        "brand": "VeVe D&D", "licensor": "VeVe",
        "description": "Une description qui vient de la chaine.",
        "dropDate": "2026-01-05", "mintDate": "2025-12-26",
        "editionType": "FE",
        "image": "https://d11.cloudfront.net/collectible_type_image.abc.webp",
    }))
    assert r["brand"] == "VeVe D&D"
    assert r["licensor"] == "VeVe"
    assert r["description"] == "Une description qui vient de la chaine."
    assert r["drop_date"] == "2026-01-05"
    assert r["edition_type"] == "FE"
    assert r["image_url"].endswith("collectible_type_image.abc.webp")


def test_dropDate_et_mintDate_restent_DEUX_champs():
    """⭐ Deux dates qui se ressemblent 9 fois sur 10 sont un piege. Sur un drop
    elles coincident ; sur un craft, non. On les garde separees plutot que
    d'arbitrer une fois pour toutes a la place de l'appelant."""
    r = cc._flatten(_transfert({"name": "x", "dropDate": "2021-10-28",
                                "mintDate": "2024-03-02"}))
    assert (r["drop_date"], r["mint_date"]) == ("2021-10-28", "2024-03-02")


def test_une_metadonnee_VIDE_ne_fait_pas_tomber_le_collecteur():
    """⚠️ Les vieux jetons (2021) n'ont pas tous les champs. Un collecteur qui
    exige une metadonnee complete s'arrete sur le premier jeton d'origine —
    c'est-a-dire sur le plus interessant."""
    r = cc._flatten(_transfert({}))
    assert r is not None
    assert r["brand"] == "" and r["licensor"] == "" and r["image_url"] == ""


def test_la_chaine_ne_pretend_PAS_donner_les_uuid_de_marque():
    """⛔ LA FRONTIERE, EN DUR. La chaine porte les NOMS de marque et de licence,
    jamais leurs uuid. Les croire presents ferait une jointure a ZERO match —
    pas une erreur, un vide. `brand_uuid`/`licensor_uuid` restent au GraphQL."""
    r = cc._flatten(_transfert({"brand": "Marvel", "licensor": "Marvel"}))
    assert "brand_uuid" not in r and "licensor_uuid" not in r


@pytest.mark.parametrize("image,attendu", [
    ("x/collectible_type_image.11111111-2222-3333-4444-555555555555.a.webp",
     "collectible"),
    ("x/comic_cover.11111111-2222-3333-4444-555555555555.a.webp", "comic"),
])
def test_la_categorie_se_LIT_dans_l_adresse_de_l_image(image, attendu):
    """Elle n'est declaree nulle part : c'est le prefixe de l'URL qui la donne.
    ⭐ On RECONNAIT la categorie au lieu de la deduire du reste."""
    r = cc._flatten(_transfert({"name": "x"}, image=image))
    assert r["category"] == attendu
    assert r["veve_uuid"] == "11111111-2222-3333-4444-555555555555"
