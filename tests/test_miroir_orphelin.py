# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_miroir_orphelin.py   (NEUF)
"""♻️ L'ORPHELIN DU MIROIR — « un delai n'est pas une preuve de non-creation ».

🔴🔴🔴 LE DEFAUT, MESURE LE 20/08/2026
─────────────────────────────────────────────────────────────────────────────
`api.poster()` fait un POST. Si Discord CREE le message puis met trop longtemps
a repondre, `requests` leve `Read timed out`. Le code en concluait « ca n'a pas
marche » et repostait le lendemain.

Ce qu'on a mesure sur `data/discord_drops_state.json`, carte TMNT — Dojo
Discipline (`c594d1ff-…`) :

    carte 📦DROP ................. 07:48:01
    miroir INSCRIT dans l'etat ... 08:18:55   (le rattrapage)
    la capture de Preda .......... 07:48      dans le salon MIROIR

⇒ Le message de 07:48 existait, **et n'etait dans aucun etat**.
  · Sans `mid`, `reagir()` n'est jamais appelee ⇒ **la carte n'a pas d'emojis**.
    C'est exactement le « les emojis manquent » de Preda.
  · Rien ne s'imprime dans les logs, puisque rien n'a « echoue ».
  · Le rattrapage cree un SECOND exemplaire ⇒ **doublon**.
  · L'orphelin, inconnu de l'etat, ne recevra JAMAIS son « ✅ DROP SORTI ».

Taux mesure sur les 13 miroirs de l'etat (03/08 -> 20/08) : **3 en retard,
23 %**. ⚠️ Moins noir que l'impression de Preda (« un message sur deux ») — mais
son observation etait juste et le mecanisme est reel.

⭐⭐⭐ UN RETRY SUR UNE ECRITURE NON IDEMPOTENTE FABRIQUE UN DOUBLON *ET* UN
ORPHELIN, ET LES DEUX SONT SILENCIEUX.

⚠️ CE QUE CE BANC NE COUVRE PAS
─────────────────────────────────────────────────────────────────────────────
Il remplace Discord par un faux. Il eprouve donc la REGLE (« relire, adopter,
reagir »), pas le comportement reel de l'API : il ne peut pas prouver que
Discord rendra bien le message dans les 25 derniers, ni que le bot a le droit
« Lire l'historique » sur 📗⎮drop-sondage. Ça se constate dans le salon.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper import discord_api as api          # noqa: E402
from scraper import discord_drops as DD         # noqa: E402


# ⭐ Une fiche de drop MINIMALE mais COMPLETE : `message()` lit `genre`,
# `lignes`, `total`… Une fiche incomplete ferait rougir ce banc pour une raison
# etrangere a son sujet — et un banc qui tombe a cote de sa question finit par
# etre ignore.
DROP = {"cle": "tmnt-dojo", "nom": "TMNT — Dojo Discipline",
        "ts": 1787000000, "avec_heure": True, "genre": "collectible",
        "licence": "TMNT", "marque": "TMNT", "annee": 2026,
        "lignes": [{"rarete": "common", "supply": 5000}],
        "total": 5000, "url": "https://www.veve.me/collectibles/tmnt-dojo"}


@pytest.fixture
def salon(monkeypatch):
    """Un faux Discord : ce qui a ete poste, ce qui a recu des emojis."""
    etat = {"messages": [], "emojis": {}, "envois": 0}

    monkeypatch.setattr(DD, "MIROIR_WEBHOOK", "https://faux/webhook")
    monkeypatch.setattr(DD, "MIROIR_THREAD", "")
    monkeypatch.setattr(DD, "MIROIR_SALON", "999")
    monkeypatch.setattr(api, "souffler", lambda *a, **k: None)

    def reagir(_ch, mid, emojis):
        etat["emojis"][mid] = list(emojis)
        return len(emojis)
    monkeypatch.setattr(api, "reagir", reagir)

    def retrouver(_ch, contenu, limite=25):
        for m in reversed(etat["messages"][-limite:]):
            if m["content"] == contenu:
                return m["id"]
        return None
    monkeypatch.setattr(api, "retrouver_identique", retrouver)
    return etat


def _poster_qui_cree_puis_expire(etat):
    """Discord CREE le message, PUIS la reponse se perd. Le cas reel."""
    def poster(_wh, _th, charge):
        etat["envois"] += 1
        etat["messages"].append({"id": f"mid{etat['envois']}",
                                 "content": charge.get("content") or ""})
        raise RuntimeError("HTTPSConnectionPool: Read timed out. (read timeout=20)")
    return poster


# ═══════════════════════════════════════════════════════════════════════════
# LE CAS REEL DU 20/08
# ═══════════════════════════════════════════════════════════════════════════

def test_un_read_timed_out_qui_a_cree_le_message_est_adopte(salon, monkeypatch):
    """🔑 LE CONTROLE CENTRAL : on adopte au lieu de reposter."""
    monkeypatch.setattr(api, "poster", _poster_qui_cree_puis_expire(salon))
    state = {}

    mid = DD.poster_miroir(DROP, state)

    assert mid == "mid1", "l'exemplaire cree par Discord n'a pas ete adopte"
    assert state["miroir"]["tmnt-dojo"] == "mid1", (
        "l'etat ne pointe pas sur la carte : elle ne recevra jamais son "
        "« ✅ DROP SORTI » et restera perimee dans le salon.")
    assert salon["emojis"].get("mid1") == DD.REACTIONS, (
        "la carte adoptee n'a pas recu ses emojis de vote — c'est tout le "
        "defaut que Preda a vu.")
    assert not state.get("miroir_rate"), (
        "un rate a ete note alors que la carte EXISTE : le rattrapage en "
        "posterait un second demain (le doublon).")


def test_pas_de_second_exemplaire_au_passage_suivant(salon, monkeypatch):
    """⭐ LA CONSEQUENCE : le doublon ne peut plus se former.

    Deuxieme passage, meme drop, meme panne. Le salon ne doit contenir qu'UNE
    seule carte de plus, pas deux.
    """
    monkeypatch.setattr(api, "poster", _poster_qui_cree_puis_expire(salon))
    state = {}
    DD.poster_miroir(DROP, state)
    avant = len(salon["messages"])

    # Le rattrapage du lendemain repasse par la meme porte.
    DD.poster_miroir(DROP, state)
    apres = len(salon["messages"])

    assert apres == avant + 1, (
        f"{apres - avant} message(s) crees au second passage : chaque tentative "
        f"empile un exemplaire de plus dans le salon.")
    assert state["miroir"]["tmnt-dojo"] == salon["messages"][-1]["id"]


# ═══════════════════════════════════════════════════════════════════════════
# ⛔ LES CAS OU ADOPTER SERAIT PIRE QUE LE DEFAUT
# ═══════════════════════════════════════════════════════════════════════════

def test_un_vrai_echec_sans_message_reste_un_rate(salon, monkeypatch):
    """Discord n'a RIEN cree : on ne doit rien adopter, et noter le rate."""
    def poster(_wh, _th, _charge):
        raise RuntimeError("Read timed out")
    monkeypatch.setattr(api, "poster", poster)
    state = {}

    assert DD.poster_miroir(DROP, state) == ""
    assert state["miroir_rate"]["tmnt-dojo"] == 1, (
        "sans rate memorise, le rattrapage ne repassera jamais : la carte "
        "n'existerait nulle part.")
    assert "miroir" not in state or "tmnt-dojo" not in state.get("miroir", {})


def test_on_n_adopte_pas_la_carte_d_un_autre_drop(salon, monkeypatch):
    """⛔ Adopter le mauvais message ferait pointer l'etat sur une carte
    etrangere, qu'on editerait ensuite. Pire que le defaut repare.

    ⭐ C'est pour ca que la comparaison est EXACTE et porte sur tout le
    contenu : une ressemblance (« le titre est dedans ») confondrait deux
    drops de la meme serie.
    """
    salon["messages"].append({"id": "vieux", "content": "Une autre carte"})

    def poster(_wh, _th, _charge):
        raise RuntimeError("Read timed out")
    monkeypatch.setattr(api, "poster", poster)
    state = {}

    assert DD.poster_miroir(DROP, state) == ""
    assert state["miroir_rate"]["tmnt-dojo"] == 1


def test_une_reponse_vide_passe_aussi_par_l_adoption(salon, monkeypatch):
    """`poster()` rend None sans lever : meme piege, meme remede."""
    def poster(_wh, _th, charge):
        salon["messages"].append({"id": "mid-vide",
                                  "content": charge.get("content") or ""})
        return None
    monkeypatch.setattr(api, "poster", poster)
    state = {}

    assert DD.poster_miroir(DROP, state) == "mid-vide"
    assert salon["emojis"].get("mid-vide") == DD.REACTIONS


def test_sans_bot_token_on_retombe_sur_le_rattrapage(monkeypatch):
    """⚠️ Un webhook ne sait pas relire un salon. Sans bot, pas d'adoption —
    et le rattrapage existant doit reprendre son role de repli."""
    monkeypatch.setattr(api, "BOT", "")
    assert api.retrouver_identique("999", "peu importe") is None


# ═══════════════════════════════════════════════════════════════════════════
# 🔴🔴🔴 CE BLOC EPROUVE LA **VRAIE** `retrouver_identique`
# ═══════════════════════════════════════════════════════════════════════════
# Les tests ci-dessus remplacent `api.retrouver_identique` par un faux. Ils
# eprouvent donc la CHAINE (relire -> adopter -> reagir), et c'est ce qu'on
# leur demande — mais ils ne disent RIEN de la comparaison elle-meme.
#
# ⛔ Mesure faite le 21/08, en injectant la faute : j'ai remplace la
#   comparaison exacte par « n'importe quel message fait l'affaire », et les
#   six tests du haut sont restes VERTS. Ils regardaient mon faux.
# ⭐⭐⭐ *Une mesure qui compte la sortie de sa propre fabrique ne dit rien de
#   la source.* Les tests ci-dessous descendent donc jusqu'au HTTP.

class _Reponse:
    def __init__(self, corps, code=200):
        self.status_code, self._corps = code, corps
        self.text = str(corps)

    def json(self):
        return self._corps


@pytest.fixture
def salon_http(monkeypatch):
    """Le vrai `retrouver_identique`, avec un faux `requests.get`."""
    boite = {"messages": [], "urls": []}
    monkeypatch.setattr(api, "BOT", "faux-token")

    def get(url, headers=None, timeout=None):
        boite["urls"].append(url)
        return _Reponse(list(reversed(boite["messages"])))
    monkeypatch.setattr(api.requests, "get", get)
    return boite


CONTENU = "🅥 TMNT Collectible: **Dojo Discipline (2026)**\n🕗 Drop date: **<t:1:F>** 🕗"


def test_vrai_la_comparaison_est_exacte(salon_http):
    """🔑 Un message QUI RESSEMBLE ne doit pas etre adopte."""
    salon_http["messages"] = [
        {"id": "a", "content": CONTENU + "\n(une ligne de plus)"},
        {"id": "b", "content": CONTENU[:-5]},
        {"id": "c", "content": "TMNT Collectible: **Dojo Discipline (2026)**"},
    ]
    assert api.retrouver_identique("999", CONTENU) is None, (
        "un message RESSEMBLANT a ete adopte. L'etat pointerait sur une carte "
        "etrangere, qu'on editerait ensuite — pire que le defaut repare.")


def test_vrai_le_message_identique_est_trouve(salon_http):
    salon_http["messages"] = [{"id": "vieux", "content": "autre chose"},
                              {"id": "bon", "content": CONTENU}]
    assert api.retrouver_identique("999", CONTENU) == "bon"


def test_vrai_deux_appels_rendent_le_meme_id(salon_http):
    """⭐ La fonction est sure a rejouer : c'est ce qui empeche le doublon."""
    salon_http["messages"] = [{"id": "bon", "content": CONTENU}]
    assert (api.retrouver_identique("999", CONTENU)
            == api.retrouver_identique("999", CONTENU) == "bon")


def test_vrai_un_contenu_vide_ne_cherche_rien(salon_http):
    """⛔ Sans quoi une carte tout-en-embed adopterait le premier message vide
    du salon."""
    salon_http["messages"] = [{"id": "x", "content": ""}]
    assert api.retrouver_identique("999", "") is None
    assert salon_http["urls"] == [], "une requete a ete faite pour rien"


def test_vrai_une_erreur_http_ne_fait_pas_adopter(salon_http, monkeypatch):
    monkeypatch.setattr(api.requests, "get",
                        lambda *a, **k: _Reponse({"message": "Missing Access"},
                                                 403))
    assert api.retrouver_identique("999", CONTENU) is None


def test_vrai_une_panne_reseau_ne_fait_pas_adopter(salon_http, monkeypatch):
    def boum(*a, **k):
        raise RuntimeError("Read timed out")
    monkeypatch.setattr(api.requests, "get", boum)
    assert api.retrouver_identique("999", CONTENU) is None
