# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_sentinelle_cablage.py
"""A4 — le CABLAGE de la sentinelle sur les 4 sources (29/07/2026).

⭐⭐ CE QUE CE BANC ATTRAPE, ET QUE RIEN D'AUTRE NE VOIT.
Les quatre collecteurs avaient tous la meme forme :

    r = session.get(...)
    r.raise_for_status()        # le code HTTP devient une exception
    ...
    except Exception as e:      # 429 et timeout deviennent EGAUX

A ce stade le statut est PERDU. Un collecteur pouvait donc se faire repousser
toute la nuit sans que rien ne distingue « la source nous bloque » de « la
source rame ». C'est la meme forme que le repli muet d'A3 : l'information
meurt dans le `catch`.

⛔ AUCUN RESEAU : `requests` est remplace. Un banc qui appelle la vraie source
ne prouve rien le jour ou elle nous bloque — le seul jour ou ce code sert.
"""
import pytest
import requests

from scraper import sentinelle_sources as ss


class Reponse:
    """Le minimum qu'un collecteur attend d'une reponse `requests`."""

    def __init__(self, code):
        self.status_code = code
        self.headers = {"content-type": "application/json"}
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        return {}


class Session:
    def __init__(self, code):
        self.code = code
        self.headers = {}
        self.proxies = {}
        self.hooks = {}

    def get(self, *a, **k):
        return Reponse(self.code)


@pytest.fixture(autouse=True)
def sentinelle_vierge():
    ss.SENTINELLE.obs.clear()
    yield
    ss.SENTINELLE.obs.clear()


def test_le_tracker_compte_ses_refus(monkeypatch):
    from scraper import veve_scraper as vs
    monkeypatch.setattr(vs, "MAX_RETRIES", 1)
    monkeypatch.setattr(vs.time, "sleep", lambda *_: None)
    with pytest.raises(RuntimeError):
        vs._get(Session(429), {"offset": 0})
    assert ss.SENTINELLE.obs["tracker"]["repousse"] == 1, (
        "le 429 du tracker n'a pas ete note : il est mort dans raise_for_status")


def test_collectscan_compte_ses_refus(monkeypatch):
    from scraper import collectchain as cc
    monkeypatch.setattr(cc, "MAX_RETRIES", 1)
    monkeypatch.setattr(cc.time, "sleep", lambda *_: None)
    with pytest.raises(RuntimeError):
        cc._get(Session(429), "https://exemple.invalide", {})
    assert ss.SENTINELLE.obs["collectscan"]["repousse"] == 1


def test_stackr_compte_ses_refus(monkeypatch):
    from scraper import stackr_sales as sk
    monkeypatch.setattr(sk.time, "sleep", lambda *_: None)
    monkeypatch.setattr(sk.requests, "get", lambda *a, **k: Reponse(429))
    with pytest.raises(RuntimeError):
        sk._get("publicVeve.test", {})
    assert ss.SENTINELLE.obs["stackr"]["repousse"] == 4   # 4 tentatives


def test_une_panne_reseau_ne_se_compte_pas_comme_un_refus(monkeypatch):
    """⭐ La distinction qui justifie tout le module. Un timeout doit tomber
    dans `reseau`, JAMAIS dans `repousse` : ralentir face a un 5xx ne sert a
    rien, face a un 429 si."""
    from scraper import collectchain as cc
    monkeypatch.setattr(cc, "MAX_RETRIES", 1)
    monkeypatch.setattr(cc.time, "sleep", lambda *_: None)

    class SessionMorte:
        def get(self, *a, **k):
            raise requests.ConnectTimeout("delai depasse")

    with pytest.raises(RuntimeError):
        cc._get(SessionMorte(), "https://exemple.invalide", {})
    d = ss.SENTINELLE.obs["collectscan"]
    assert d["reseau"] == 1 and d["repousse"] == 0


def test_le_graphql_est_instrumente_a_la_FABRIQUE_pas_aux_5_copies():
    """`GRAPHQL_URL` est interroge a 5 endroits de `veve_detail`. Le hook est
    pose sur la session : il voit les 5, et ceux qu'on ajoutera demain."""
    from scraper import veve_detail as vd
    vd._thread_local.__dict__.pop("session", None)
    s = vd._session()
    hooks = s.hooks.get("response") or []
    assert hooks, "aucun hook de reponse sur la session GraphQL"
    for h in hooks:
        h(Reponse(429))
    assert ss.SENTINELLE.obs["veve_graphql"]["repousse"] >= 1


def test_le_graphql_compte_aussi_ce_qui_n_a_jamais_abouti():
    """Une requete qui n'aboutit pas ne declenche aucun hook de reponse. Les
    5 blocs `except` passent tous par `_maybe_disable_proxy` : c'est la
    l'entonnoir, et c'est la qu'on compte."""
    from scraper import veve_detail as vd
    vd._maybe_disable_proxy(requests.ConnectTimeout("delai depasse"))
    assert ss.SENTINELLE.obs["veve_graphql"]["reseau"] == 1
