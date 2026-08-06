# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_egress_capteur.py
"""🛰️ LE CAPTEUR DE SORTIES DIRECTES (06/08/2026, lot 81).

⭐⭐ ON NE SUPPRIME PAS UNE PROTECTION, ON LA REMPLACE PAR UN CAPTEUR. Le proxy
Apify est mort — constate en direct le 05/08 : `Egress: Apify proxy unavailable
(ProxyError); falling back to DIRECT connection`, puis 7 130 requetes GraphQL
en clair depuis un runner GitHub. Le repli fait son travail (un proxy mort ne
doit pas faire tomber un run) ; ce qui manquait, c'est que personne n'apprend
qu'il s'est declenche.

⛔ CE BANC GARDE LA DISTINCTION QUI FAIT TOUT : « pas de proxy configure » est
une DECISION assumee, « proxy configure et mort » est une protection qu'on
croit avoir. Un capteur qui crierait dans les deux cas serait desarme en une
semaine.
"""
import importlib

import pytest


@pytest.fixture
def vd(monkeypatch):
    from scraper import veve_detail as m
    importlib.reload(m)
    yield m
    importlib.reload(m)


def test_sans_proxy_configure_le_capteur_se_tait(vd):
    """C'est une decision, pas un repli : on sort en direct et on le sait."""
    vd._egress_promis = False
    vd._egress_tenu = False
    for _ in range(1000):
        vd._compter_egress()
    assert vd._egress_compte == 0
    assert "assume" in vd.bilan_egress()


def test_proxy_vivant_ne_compte_rien(vd):
    vd._egress_promis = True
    vd._egress_tenu = True
    for _ in range(1000):
        vd._compter_egress()
    assert vd._egress_compte == 0
    assert "comme prevu" in vd.bilan_egress()


def test_proxy_promis_mais_mort_compte_chaque_requete(vd):
    """⭐ Le seul cas ou l'on se croit protege sans l'etre."""
    vd._egress_promis = True
    vd._egress_tenu = False
    for _ in range(7130):
        vd._compter_egress()
    assert vd._egress_compte == 7130
    bilan = vd.bilan_egress()
    assert "EN CLAIR" in bilan and "7130" in bilan


def test_le_bilan_parle_meme_quand_tout_va_bien(vd):
    """⭐⭐ Un capteur qui ne parle que dans le drame ne se relit jamais — et
    le jour ou il se tait, on ne sait pas s'il fonctionne ou s'il est mort.
    Les trois etats produisent une phrase."""
    for promis, tenu in ((False, False), (True, True), (True, False)):
        vd._egress_promis, vd._egress_tenu = promis, tenu
        assert vd.bilan_egress().startswith("🛰️ egress :")


def test_le_hook_compte_le_corps_et_pas_seulement_le_code(vd):
    """🕳️ Un 200 GraphQL avec `errors[]` et `data: null` doit remonter comme
    une ABSENCE, pas comme un succes."""
    from scraper import sentinelle_sources as ss

    class Reponse:
        status_code = 200
        content = b"x"

        def json(self):
            return {"data": {"publicComicType": None},
                    "errors": [{"message": "Entity not found"}]}

    ss.SENTINELLE.obs.clear()
    vd._noter_reponse_graphql(Reponse())
    assert ss.SENTINELLE.obs["veve_graphql"]["absent"] == 1
    assert ss.SENTINELLE.obs["veve_graphql"]["ok"] == 0
    ss.SENTINELLE.obs.clear()


def test_une_reponse_pleine_reste_un_succes(vd):
    from scraper import sentinelle_sources as ss

    class Reponse:
        status_code = 200
        content = b"x"

        def json(self):
            return {"data": {"publicComicType": {"id": "abc"}}}

    ss.SENTINELLE.obs.clear()
    vd._noter_reponse_graphql(Reponse())
    assert ss.SENTINELLE.obs["veve_graphql"]["ok"] == 1
    assert ss.SENTINELLE.obs["veve_graphql"]["absent"] == 0
    ss.SENTINELLE.obs.clear()


def test_un_corps_illisible_ne_fait_pas_tomber_la_collecte(vd):
    """⛔ Un hook qui casse ferait tomber un run de 7 000 requetes pour un
    compteur. Le code reste la verite de repli."""
    from scraper import sentinelle_sources as ss

    class Reponse:
        status_code = 200
        content = b"<html>pas du json</html>"

        def json(self):
            raise ValueError("pas du json")

    ss.SENTINELLE.obs.clear()
    vd._noter_reponse_graphql(Reponse())
    assert ss.SENTINELLE.obs["veve_graphql"]["ok"] == 1
    ss.SENTINELLE.obs.clear()
