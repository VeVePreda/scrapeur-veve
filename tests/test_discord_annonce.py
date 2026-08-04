# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_discord_annonce.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""Banc du module Discord « annonce » — UN BANC DE COMPORTEMENT.

⭐⭐ CE QU'IL NE FAIT PAS : verifier que `DISCORD_ANNONCE_EVERYONE` est ecrit
dans le YML. Le cablage se voit a l'oeil ; ce qui ne se voit pas, c'est le
reglage **cable aux deux bouts et jamais lu par le code** — le no-op silencieux
deja paye dans ce depot. Chaque test ci-dessous pose la variable et regarde ce
que le module ENVOIE, pas ce qu'il declare.

Ce qui est teste, c'est ce qui, en se trompant, **poste quand meme** :
  * le ping @everyone qui part alors que l'interrupteur est ferme ;
  * le ping ecrit dans un EMBED, ou il n'alerte personne ;
  * le webhook manquant qui retombe sur un autre salon ;
  * le message publie sur une selection vide ou une fenetre de ventes trouee ;
  * le doublon (deux @everyone pour le meme mois) ;
  * un chiffre de ventes superieur au tirage.

    python3 -m pytest tests/test_discord_annonce.py -q
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper import discord_annonce as A          # noqa: E402
from scraper import discord_api as api            # noqa: E402
from scraper import discord_drops as dd           # noqa: E402


# ═══════════════════════════════════════════════════════════ outillage du banc

class FauxOnglet:
    def __init__(self, lignes):
        self._lignes = lignes

    def get_all_records(self):
        return list(self._lignes)


class FauxSheet:
    """Le minimum que `dd._records` attend d'un classeur."""

    def __init__(self, onglets):
        self._onglets = onglets

    def worksheet(self, nom):
        if nom not in self._onglets:
            raise KeyError(nom)
        return FauxOnglet(self._onglets[nom])


def serie(cle, nom, ventes_uuid, licence="Marvel", genre="collectible",
          supply=1000, jour="2026-07-10", mercredi=False, rarete="RARE",
          edition=""):
    return {"cle": cle, "genre": genre, "jour": jour, "ts": 0,
            "nom": nom, "annee": "", "marque": "", "licence": licence,
            "methode": "", "exclusive": False, "total": supply,
            "mercredi": mercredi,
            "lignes": [{"rarete": rarete, "edition": edition,
                        "supply": supply, "uuid": ventes_uuid}]}


@pytest.fixture(autouse=True)
def env_propre(monkeypatch, tmp_path):
    """Aucun test ne doit dependre de l'environnement de la machine — ni le
    polluer. On repart d'un etat et de crochets neufs a chaque fois."""
    for cle in ("DISCORD_ANNONCE_WEBHOOK", "DISCORD_ANNONCE_THREAD",
                "DISCORD_ANNONCE_EVERYONE", "DISCORD_ANNONCE_FORCE",
                "DISCORD_ANNONCE_IMAGE", "DISCORD_HUB_WEBHOOK",
                "DISCORD_STATS_WEBHOOK"):
        monkeypatch.delenv(cle, raising=False)
    monkeypatch.setattr(A, "STATE_PATH", str(tmp_path / "etat.json"))
    monkeypatch.setattr(A, "CROCHETS_PATH", str(tmp_path / "crochets.json"))
    monkeypatch.setattr(api, "_envoyes", 0, raising=False)
    # 🔴 L'AFFICHE EST COUPEE PAR DEFAUT DANS LE BANC — et ce n'est PAS un
    # detail de confort. Tant que le decor n'existait pas dans le depot, ces
    # tests passaient sans jamais entrer dans `fabriquer_affiche` : le jour ou
    # Preda a depose son PNG, six d'entre eux sont tombes d'un coup.
    # ⭐⭐ UN TEST QUI PASSE PARCE QU'UN FICHIER MANQUE NE TESTE PAS CE QU'IL
    # CROIT. Le chemin « avec affiche » a maintenant ses propres tests, en bas.
    monkeypatch.setenv("DISCORD_ANNONCE_AFFICHE", "false")
    yield


@pytest.fixture
def poste(monkeypatch):
    """Enregistre tout ce que le module ENVOIE. Rien ne part sur le reseau."""
    envois = []

    def faux_poster(wh, th, payload):
        envois.append({"webhook": wh, "thread": th, "payload": payload,
                       "fichier": ""})
        return str(1000 + len(envois))

    def faux_poster_fichier(wh, th, payload, chemin, nom="", type_mime=""):
        envois.append({"webhook": wh, "thread": th, "payload": payload,
                       "fichier": chemin})
        return str(1000 + len(envois))

    monkeypatch.setattr(api, "poster", faux_poster)
    monkeypatch.setattr(api, "poster_fichier", faux_poster_fichier)
    monkeypatch.setattr(api, "souffler", lambda *a, **k: None)
    monkeypatch.setattr(A, "append_log", lambda *a, **k: None)
    return envois


def _monde(monkeypatch, series=None, couverts=None, ventes=None,
           a_venir=None, plante=False):
    """Un mois entier, sans Sheet ni reseau."""
    monkeypatch.setenv("SHEET_ID", "faux")

    def ouvrir(_):
        if plante:
            raise RuntimeError("APIError 503")
        return object()

    monkeypatch.setattr(A, "_ouvrir", ouvrir)
    monkeypatch.setattr(A, "series_du_mois",
                        lambda sh, an, mo: list(series or []))
    monkeypatch.setattr(A, "jours_couverts",
                        lambda sh, jours: list(couverts if couverts is not None
                                               else jours))
    monkeypatch.setattr(A, "ventes_du_mois", lambda sh, jours: dict(ventes or {}))
    monkeypatch.setattr(dd, "drops_a_venir",
                        lambda sh, connus=None, trace=False: list(a_venir or []))


def _corps(selection=None, a_venir=None, total=171, cle="2026-05") -> str:
    """Le 2e message, tel qu'un lecteur le verra."""
    if selection is None:
        selection = A.classer([serie("a", "BB-8", "ua")], {"ua": 5})
    return A.corps(cle, "mai", total, selection, a_venir or [])["content"]


# ═══════════════════════════════════════════════════ 1. LE GARDE DE LA DATE

def test_on_ne_publie_que_le_2_et_le_3():
    """Le 3 est le RATTRAPAGE : GitHub abandonne des runs planifies quand il
    est charge, et exiger le 2 pile revient a accepter de sauter un mois."""
    assert A.est_le_jour(dt.date(2026, 9, 2))
    assert A.est_le_jour(dt.date(2026, 9, 3))
    assert not A.est_le_jour(dt.date(2026, 9, 1))
    assert not A.est_le_jour(dt.date(2026, 9, 4))
    assert not A.est_le_jour(dt.date(2026, 9, 30))


def test_la_tolerance_est_reglable_a_chaud(monkeypatch):
    monkeypatch.setenv("DISCORD_ANNONCE_TOLERANCE", "0")
    assert not A.est_le_jour(dt.date(2026, 9, 3)), (
        "la tolerance est figee a l'import : le reglage ne sert a rien")


def test_la_cle_est_le_MOIS_ANNONCE_pas_le_jour_du_run():
    """Le 2 et le 3 annoncent le meme mois -> la meme cle -> pas de doublon."""
    assert A.cle_mois(dt.date(2026, 9, 2)) == "2026-08"
    assert A.cle_mois(dt.date(2026, 9, 3)) == "2026-08"


def test_la_cle_survit_au_passage_dannee():
    assert A.cle_mois(dt.date(2027, 1, 2)) == "2026-12"


def test_les_bornes_du_mois_couvrent_fevrier_bissextile():
    assert A.bornes(2028, 2) == ("2028-02-01", "2028-02-29")
    assert len(A.jours_du_mois(2026, 7)) == 31


# ═══════════════════════════════════════════════ 2. LE WEBHOOK NE RETOMBE PAS

def test_le_webhook_ne_retombe_JAMAIS_sur_le_hub(monkeypatch):
    """🔴 Le test le plus important du fichier. `api.webhook()` se rabat sur
    DISCORD_HUB_WEBHOOK : un secret oublie deverserait un @everyone dans le
    forum du hub. Un module mal configure doit rester MUET."""
    monkeypatch.setenv("DISCORD_HUB_WEBHOOK", "https://hub")
    monkeypatch.setenv("DISCORD_STATS_WEBHOOK", "https://stats")
    assert A.webhook() == ""
    assert api.webhook("annonce") == "https://hub", (
        "hypothese du test caduque : api.webhook ne retombe plus sur le hub")


def test_sans_webhook_rien_nest_envoye_et_rien_nest_memorise(monkeypatch, poste):
    _monde(monkeypatch, series=[serie("s1", "Iron Man", "u1")],
           ventes={"u1": 500})
    monkeypatch.setenv("DISCORD_ANNONCE_FORCE", "true")
    assert A.run() == 0
    assert poste == [], "simulation : rien ne doit partir"
    assert not os.path.exists(A.STATE_PATH), (
        "un essai en simulation a « brule » le mois : le vrai run se taira")


# ═══════════════════════════════════ 3. L'INTERRUPTEUR @everyone (comportement)

def test_interrupteur_ferme_le_ping_ne_part_pas(monkeypatch, poste):
    monkeypatch.setenv("DISCORD_ANNONCE_WEBHOOK", "https://annonces")
    monkeypatch.setenv("DISCORD_ANNONCE_EVERYONE", "false")
    monkeypatch.setenv("DISCORD_ANNONCE_FORCE", "true")
    _monde(monkeypatch, series=[serie("s1", "Iron Man", "u1")],
           ventes={"u1": 500})
    assert A.run() == 0
    p = poste[0]["payload"]
    assert "@everyone" not in p["content"]
    assert p["allowed_mentions"]["parse"] == [], (
        "le texte ne dit pas @everyone mais la permission est ouverte : "
        "le jour ou le texte changera, le serveur sonnera")


def test_interrupteur_ouvert_le_ping_part(monkeypatch, poste):
    monkeypatch.setenv("DISCORD_ANNONCE_WEBHOOK", "https://annonces")
    monkeypatch.setenv("DISCORD_ANNONCE_EVERYONE", "true")
    monkeypatch.setenv("DISCORD_ANNONCE_FORCE", "true")
    _monde(monkeypatch, series=[serie("s1", "Iron Man", "u1")],
           ventes={"u1": 500})
    assert A.run() == 0
    p = poste[0]["payload"]
    assert "@everyone" in p["content"]
    assert p["allowed_mentions"]["parse"] == ["everyone"], (
        "le texte dit @everyone mais la permission est bridee : "
        "le ping ne partira pas, et personne ne le verra")


def test_le_ping_est_dans_du_TEXTE_jamais_dans_un_embed():
    """🔴 Un « @everyone » ecrit dans un embed n'alerte PERSONNE : Discord le
    rend en texte gris. Si le rendu repassait un jour en embed, tout aurait
    l'air normal — et plus rien ne sonnerait."""
    p = A.entete("2026-05", dt.date(2026, 6, 3), "mai", "Starwars", True)
    assert "@everyone" in p["content"]
    assert "embeds" not in p, "le ping doit rester dans du texte"


def test_le_corps_ne_ping_jamais():
    m = A.corps("2026-05", "mai", 171,
                A.classer([serie("a", "BB-8", "ua")], {"ua": 5}), [])
    assert m["allowed_mentions"]["parse"] == []
    assert "@everyone" not in m["content"]


# ═══════════════════════════════════════ 4. « MIEUX VAUT RIEN QU'UN MESSAGE FAUX »

def test_selection_vide_aucun_post(monkeypatch, poste):
    monkeypatch.setenv("DISCORD_ANNONCE_WEBHOOK", "https://annonces")
    monkeypatch.setenv("DISCORD_ANNONCE_FORCE", "true")
    _monde(monkeypatch, series=[], ventes={})
    assert A.run() == 1, "un mois vide doit etre BRUYANT, pas silencieux"
    assert poste == []


def test_aucune_vente_aucun_post(monkeypatch, poste):
    """Des series sorties, mais pas un seul mint : ce n'est pas un mois calme,
    c'est un capteur en panne. Et le critere « le plus vendu » n'a plus de sens."""
    monkeypatch.setenv("DISCORD_ANNONCE_WEBHOOK", "https://annonces")
    monkeypatch.setenv("DISCORD_ANNONCE_FORCE", "true")
    _monde(monkeypatch, series=[serie("s1", "Iron Man", "u1")], ventes={})
    assert A.run() == 1
    assert poste == []


def test_fenetre_de_ventes_trouee_aucun_post(monkeypatch, poste):
    """ChainItems ne garde que 35 jours. Un classement sur 12 journees a
    exactement l'air d'un classement — c'est pour ca qu'on le refuse."""
    monkeypatch.setenv("DISCORD_ANNONCE_WEBHOOK", "https://annonces")
    monkeypatch.setenv("DISCORD_ANNONCE_FORCE", "true")
    _monde(monkeypatch, series=[serie("s1", "Iron Man", "u1")],
           couverts=["2026-07-%02d" % j for j in range(1, 13)],
           ventes={"u1": 500})
    assert A.run() == 1
    assert poste == []


def test_sheet_illisible_aucun_post(monkeypatch, poste):
    monkeypatch.setenv("DISCORD_ANNONCE_WEBHOOK", "https://annonces")
    monkeypatch.setenv("DISCORD_ANNONCE_FORCE", "true")
    _monde(monkeypatch, plante=True)
    assert A.run() == 1
    assert poste == []


# ═══════════════════════════════════════════════════════════ 5. L'ANTI-DOUBLON

def test_le_mois_deja_publie_ne_repart_pas(monkeypatch, poste):
    monkeypatch.setenv("DISCORD_ANNONCE_WEBHOOK", "https://annonces")
    _monde(monkeypatch, series=[serie("s1", "Iron Man", "u1")],
           ventes={"u1": 500})
    api.save_state(A.STATE_PATH, {"dernier_mois": A.cle_mois()},
                   "https://annonces", "")
    assert A.run() == 0
    assert poste == [], "deux @everyone pour le meme mois"


def test_deux_messages_lentete_puis_le_corps(monkeypatch, poste):
    monkeypatch.setenv("DISCORD_ANNONCE_WEBHOOK", "https://annonces")
    monkeypatch.setenv("DISCORD_ANNONCE_FORCE", "true")
    _monde(monkeypatch, series=[serie("s1", "Iron Man", "u1")],
           ventes={"u1": 500})
    A.run()
    assert len(poste) == 2
    assert "Annonces" in poste[0]["payload"]["content"]
    assert "Drops** dont" in poste[1]["payload"]["content"]


def test_envoi_rate_rien_nest_memorise(monkeypatch):
    """Si RIEN n'est parti, le mois doit rester a publier."""
    monkeypatch.setenv("DISCORD_ANNONCE_WEBHOOK", "https://annonces")
    monkeypatch.setenv("DISCORD_ANNONCE_FORCE", "true")
    _monde(monkeypatch, series=[serie("s1", "Iron Man", "u1")],
           ventes={"u1": 500})
    monkeypatch.setattr(api, "poster", lambda *a, **k: None)
    monkeypatch.setattr(A, "append_log", lambda *a, **k: None)
    assert A.run() == 1
    assert not os.path.exists(A.STATE_PATH)


def test_letat_est_ecrit_DES_lentete(monkeypatch):
    """Le corps echoue apres une entete partie. Le ping a sonne : il ne doit
    JAMAIS resonner le lendemain. Une entete orpheline se repare a la main ;
    deux @everyone, non."""
    monkeypatch.setenv("DISCORD_ANNONCE_WEBHOOK", "https://annonces")
    monkeypatch.setenv("DISCORD_ANNONCE_EVERYONE", "true")
    monkeypatch.setenv("DISCORD_ANNONCE_FORCE", "true")
    _monde(monkeypatch, series=[serie("s1", "Iron Man", "u1")],
           ventes={"u1": 500})
    appels = {"n": 0}

    def poster_capricieux(wh, th, payload):
        appels["n"] += 1
        return "111" if appels["n"] == 1 else None      # le corps echoue

    monkeypatch.setattr(api, "poster", poster_capricieux)
    monkeypatch.setattr(api, "souffler", lambda *a, **k: None)
    monkeypatch.setattr(A, "append_log", lambda *a, **k: None)

    assert A.run() == 1, "un corps manquant doit etre rouge"
    with open(A.STATE_PATH, encoding="utf-8") as f:
        assert json.load(f).get("dernier_mois") == A.cle_mois(), (
            "le mois n'est pas memorise : demain, @everyone repartira")


def test_envoi_reussi_le_mois_est_memorise(monkeypatch, poste):
    monkeypatch.setenv("DISCORD_ANNONCE_WEBHOOK", "https://annonces")
    monkeypatch.setenv("DISCORD_ANNONCE_FORCE", "true")
    _monde(monkeypatch, series=[serie("s1", "Iron Man", "u1")],
           ventes={"u1": 500})
    assert A.run() == 0
    with open(A.STATE_PATH, encoding="utf-8") as f:
        assert json.load(f).get("dernier_mois") == A.cle_mois()


# ══════════════════════════════════════ 6. LE CLASSEMENT « LE PLUS VENDU »

def test_le_classement_suit_les_ventes_pas_le_tirage():
    s = [serie("a", "Petit tirage", "ua", supply=100),
         serie("b", "Gros vendeur", "ub", supply=50000),
         serie("c", "Invendu", "uc")]
    out = A.classer(s, {"ua": 90, "ub": 4000, "uc": 0})
    assert [d["nom"] for d in out] == ["Gros vendeur", "Petit tirage"], (
        "une serie a 0 vente n'est pas « notable »")


def test_une_serie_additionne_ses_elements():
    d = serie("a", "Phoenix Five", "u1")
    d["lignes"].append({"rarete": "ULTRA_RARE", "edition": "", "supply": 75,
                        "uuid": "u2"})
    out = A.classer([d], {"u1": 300, "u2": 75})
    assert out[0]["ventes"] == 375


def test_on_ne_peut_pas_vendre_plus_que_le_tirage():
    """🔴 Le garde-fou de Preda. Un chiffre impossible n'est pas un record,
    c'est un `supply` faux — et publie tel quel, il discredite tous les autres."""
    out = A.classer([serie("a", "Impossible", "ua", supply=500)], {"ua": 900})
    assert out[0]["ventes"] == 500


def test_un_tirage_inconnu_ne_borne_rien():
    """Tirage a 0 = « on ne sait pas », pas « rien n'existe » : borner a 0
    ferait disparaitre la serie."""
    out = A.classer([serie("a", "Sans tirage", "ua", supply=0)], {"ua": 900})
    assert out[0]["ventes"] == 900


# ═══════════════════════════════════ 7. LES TROIS FILTRES DE LA LISTE

def test_les_artworks_sont_ecartes():
    """Un ARTIST_PROOF (tirage 1) n'est pas une sortie a annoncer."""
    ap = serie("a", "Peach Momoko AP", "ua", supply=1, rarete="ARTIST_PROOF",
               edition="AP")
    normal = serie("b", "Iron Man", "ub")
    out = A.retenir(A.classer([ap, normal], {"ua": 1, "ub": 500}))
    assert [d["nom"] for d in out] == ["Iron Man"]


def test_un_AP_isole_ne_tue_pas_toute_la_serie():
    """⭐ « toutes les lignes sont AP », pas « au moins une » : un filtre trop
    large ne se plaint jamais, il se contente de faire le vide."""
    d = serie("a", "Série normale", "u1")
    d["lignes"].append({"rarete": "ARTIST_PROOF", "edition": "AP",
                        "supply": 1, "uuid": "u2"})
    assert not A.est_artwork(d)
    assert A.retenir(A.classer([d], {"u1": 400, "u2": 1}))


def test_un_comic_du_mercredi_est_ecarte_meme_sold_out():
    """Les DEUX filtres s'ajoutent (choix de Preda du 04/08)."""
    c = serie("a", "Comic du mercredi", "ua", genre="comic", supply=100,
              mercredi=True)
    assert A.retenir(A.classer([c], {"ua": 100})) == []


def test_un_comic_non_sold_out_est_ecarte():
    c = serie("a", "Comic tiede", "ua", genre="comic", supply=1000)
    assert A.retenir(A.classer([c], {"ua": 999})) == []


def test_un_comic_sold_out_hors_mercredi_est_garde():
    """L'exemple de Preda : Captain America Comics #1, sorti un JEUDI."""
    c = serie("a", "Captain America Comics #1 (1941)", "ua", genre="comic",
              supply=6697, jour="2026-07-23")
    out = A.retenir(A.classer([c], {"ua": 6697}))
    assert [d["nom"] for d in out] == ["Captain America Comics #1 (1941)"]


def test_un_collectible_na_pas_besoin_detre_sold_out():
    col = serie("a", "Iron Man", "ua", supply=5000)
    assert A.retenir(A.classer([col], {"ua": 12}))


def test_retenir_ne_coupe_PLUS_il_rend_tous_les_eligibles():
    """⭐ Le MESSAGE cite 7 lignes, l'AFFICHE veut 5 COLLECTIBLES : deux
    besoins, deux découpes. Couper trop tôt dans une fonction commune obligeait
    l'affiche à se contenter des restes du message."""
    s = [serie(f"s{i}", f"Nom {i}", f"u{i}") for i in range(20)]
    out = A.retenir(A.classer(s, {f"u{i}": 100 + i for i in range(20)}))
    assert len(out) == 20


def test_le_message_coupe_a_7(monkeypatch, poste):
    monkeypatch.setenv("DISCORD_ANNONCE_WEBHOOK", "https://annonces")
    monkeypatch.setenv("DISCORD_ANNONCE_FORCE", "true")
    _monde(monkeypatch,
           series=[serie(f"s{i}", f"Nom {i}", f"u{i}") for i in range(20)],
           ventes={f"u{i}": 100 + i for i in range(20)})
    A.run()
    corps = poste[1]["payload"]["content"]
    assert corps.count("\n1. ") + corps.count("1. ") >= 1
    assert "8." not in corps.split("👀")[0], "plus de 7 lignes citees"


def test_la_mosaique_ne_prend_QUE_des_collectibles(monkeypatch, tmp_path):
    """🔴 Preda (04/08) : le comic a DÉJÀ sa carte en haut à droite. L'y
    remettre en bas, c'est le montrer deux fois et perdre une case.
    ⭐ Une pièce a UNE place dans une composition."""
    vues = {}
    from outils.annonce_visuel import rendu
    from scraper import annonce_images as ai

    monkeypatch.setattr(ai, "visuel_de_tuile",
                        lambda d, cache=None: f"img:{d['nom']}")
    monkeypatch.setattr(rendu, "composer",
                        lambda m, b, tuiles, c, s, fond="": vues.setdefault(
                            "tuiles", tuiles) or s)
    monkeypatch.setenv("DISCORD_ANNONCE_AFFICHE", "true")
    monkeypatch.setattr(A, "CROCHETS_PATH", str(tmp_path / "vide.json"))

    eligibles = [
        serie("c1", "COMIC EN TETE", "u1", genre="comic"),
        serie("a", "Collectible A", "ua"),
        serie("b", "Collectible B", "ub"),
        serie("c2", "COMIC 2", "u2", genre="comic"),
        serie("c", "Collectible C", "uc"),
        serie("d", "Collectible D", "ud"),
        serie("e", "Collectible E", "ue"),
        serie("f", "Collectible F", "uf"),
    ]
    A.fabriquer_affiche(object(), "2026-07", "juillet", eligibles,
                        banniere="https://cdn/b.jpg")
    assert vues["tuiles"] == ["img:Collectible A", "img:Collectible B",
                              "img:Collectible C", "img:Collectible D",
                              "img:Collectible E"], (
        "un comic s'est glisse dans la mosaique, ou une case a ete gaspillee")


# ═══════════════════════════════════════════ 8. LE THEME ET SON REPLI NEUTRE

def test_theme_nomme_quand_une_licence_ecrase():
    s = A.classer([serie("a", "Vador", "ua", licence="Star Wars"),
                   serie("b", "Yoda", "ub", licence="Star Wars"),
                   serie("c", "Thor", "uc", licence="Marvel")],
                  {"ua": 5000, "ub": 4000, "uc": 300})
    assert A.theme(s) == "Star Wars"


def test_repli_neutre_quand_personne_ne_domine():
    """« un mois Star Wars » est une AFFIRMATION : fausse, elle est fausse
    devant tout le serveur."""
    s = A.classer([serie("a", "Vador", "ua", licence="Star Wars"),
                   serie("b", "Thor", "ub", licence="Marvel"),
                   serie("c", "Mickey", "uc", licence="Disney")],
                  {"ua": 1000, "ub": 1000, "uc": 1000})
    assert A.theme(s) == ""


def test_une_seule_grosse_sortie_ne_fait_pas_un_mois():
    s = A.classer([serie("a", "Vador", "ua", licence="Star Wars"),
                   serie("b", "Thor", "ub", licence="Marvel")],
                  {"ua": 9000, "ub": 100})
    assert A.theme(s) == ""


def test_laccroche_suit_le_theme():
    assert A.accroche("mai", "Starwars") == (
        "Si vous n'étiez pas là en Mai, vous avez certainement manqué le mois "
        "Starwars !")
    assert A.accroche("mai", "") == (
        "Si vous n'étiez pas là en Mai, voici ce que vous avez manqué !"), (
        "sans licence dominante, l'accroche ne doit NOMMER aucun thème")


# ═══════════════════════════════ 9. LA FORME — du TEXTE, pas d'embed

def test_aucun_embed_nulle_part():
    """« L'embed rend mal » (Preda, 04/08). ⭐ Le gabarit d'un message qui
    remplace un humain, c'est ce que l'humain ecrit."""
    tete = A.entete("2026-05", dt.date(2026, 6, 3), "mai", "Starwars", False)
    corps = A.corps("2026-05", "mai", 171,
                    A.classer([serie("a", "BB-8", "ua")], {"ua": 5}), [])
    assert "embeds" not in tete and "embeds" not in corps


def test_lentete_porte_la_date_du_POST():
    """« Annonces 03/06 » : le jour ou l'on poste, pas le mois annonce."""
    tete = A.entete("2026-05", dt.date(2026, 6, 3), "mai", "Starwars", True)
    assert tete["content"].startswith("🐱 **Annonces 03/06** - @everyone")
    assert "Si vous n'étiez pas là en Mai" in tete["content"]


def test_lentete_sans_ping_na_pas_de_tiret_orphelin():
    tete = A.entete("2026-05", dt.date(2026, 6, 3), "mai", "", False)
    assert tete["content"].splitlines()[0] == "🐱 **Annonces 03/06**"


def test_le_corps_annonce_le_total_du_mois():
    assert "**171 Drops** dont :" in _corps()


def test_le_lien_est_dans_le_NOM():
    d = A.classer([serie("a", "BB-8", "ua")], {"ua": 5})[0]
    assert A.ligne_sortie(1, d).startswith("1. [BB-8](https://")


def test_linterrupteur_des_liens_masques(monkeypatch):
    """Si Discord affichait les crochets en clair, une variable suffit — pas un
    redeploiement. ⭐ Ce qu'on ne peut pas verifier avant la prod se transforme
    en interrupteur, pas en pari silencieux."""
    monkeypatch.setenv("DISCORD_ANNONCE_LIENS_MASQUES", "false")
    d = A.classer([serie("a", "BB-8", "ua")], {"ua": 5})[0]
    ligne = A.ligne_sortie(1, d)
    assert "[BB-8](" not in ligne
    assert "**BB-8**" in ligne and "https://" in ligne


def test_pas_de_ligne_vide_entre_deux_sorties():
    """Demande de Preda (04/08) : la liste est compacte."""
    s = A.classer([serie("a", "BB-8", "ua"), serie("b", "Yoda", "ub")],
                  {"ua": 500, "ub": 400})
    txt = _corps(s)
    debut = txt.index("1. ")
    bloc = txt[debut:txt.index("👀")]
    assert "\n\n1." not in bloc and "\n\n2." not in bloc, (
        "une ligne vide s'est glissee entre deux sorties")


def test_le_sold_out_ne_sannonce_que_quand_il_est_vrai():
    epuise = A.classer([serie("a", "Vador", "ua", supply=500)], {"ua": 500})[0]
    reste = A.classer([serie("b", "Thor", "ub", supply=500)], {"ub": 499})[0]
    assert "SOLD OUT" in A.ligne_sortie(1, epuise)
    assert "SOLD OUT" not in A.ligne_sortie(1, reste)


def test_le_corps_ne_fabrique_aucune_vignette():
    """🚫 Trois URL nues (parrainage, X, VeVe Investor) = trois cartouches
    grises qui doublent la hauteur du message. `flags: 4` = SUPPRESS_EMBEDS."""
    m = A.corps("2026-05", "mai", 171,
                A.classer([serie("a", "BB-8", "ua")], {"ua": 5}), [])
    assert m["flags"] == 4


def test_lentete_GARDE_ses_apercus():
    """⚠️ L'illustration EST un apercu d'URL : supprimer les vignettes partout
    tuerait justement ce qu'on veut voir. ⭐ Un reglage global qui supprime
    « les images » supprime aussi celle qu'on a demandee."""
    tete = A.entete("2026-05", dt.date(2026, 6, 3), "mai", "", False)
    assert tete.get("flags", 0) == 0


def test_et_maintenant_porte_lemoji_yeux():
    assert "👀 **Et maintenant ?**" in _corps()


def test_sans_drop_a_venir_on_promet_des_surprises_pas_une_liste():
    """⭐ Inventer un drop serait pire que de n'en annoncer aucun."""
    txt = _corps()
    assert "Plein de surprises !" in txt
    assert "et bien d'autres surprises !!" not in txt


def test_avec_des_drops_a_venir_la_liste_apparait():
    txt = _corps(a_venir=[serie("z", "Ahsoka", "uz")])
    assert "Ahsoka" in txt and "et bien d'autres surprises !!" in txt


def test_les_salons_sont_des_mentions_pas_des_urls():
    """`<#id>` reste cliquable meme ping ferme (allowed_mentions ne bride que
    les membres, les roles et @everyone) — et suit un salon renomme."""
    txt = _corps()
    assert f"<#{A.SALON_CLASSEMENTS}>" in txt
    assert f"<#{A.SALON_RECAP}>" in txt


def test_loffre_10_dollars_porte_le_cadeau_et_sa_condition():
    """Emoji cadeau (plus d'avertissement) + l'offre est reservee aux nouveaux
    — ne pas le dire serait une promesse qu'on ne tient pas."""
    txt = _corps()
    assert "🎁 **Profitez de 10$ lors de votre Inscription à VeVe !**" in txt
    assert "Offre réservée aux nouveaux inscrits." in txt
    assert "⚠️ **Profitez" not in txt


def test_le_bloc_liens_est_au_mot_pres():
    txt = _corps()
    for bout in (f"Lien de parrainage : {A.LIEN_PARRAINAGE}",
                 "**Comme chaque mois, mise à jour des Classements Publics :**",
                 "**Actualités en temps réel sur X (Twitter) :**",
                 A.LIEN_X, "**Bulletin Récap dans le canal**"):
        assert bout in txt, f"manquant : {bout!r}"


def test_le_service_est_le_texte_de_preda():
    txt = _corps()
    assert ("Et si vous voulez mettre toutes les chances de réussite de votre "
            "côté, essayez l'accès aux services professionnels de VeVe "
            f"Investor !\n{A.LIEN_INVESTOR}") in txt


# ═══════════════════════════════ 10. LES CROCHETS v1 (newsletter, illustration)

def test_sans_crochet_aucune_ligne_newsletter():
    assert "newsletter" not in _corps().lower()


def test_le_crochet_newsletter_sallume_tout_seul(tmp_path, monkeypatch):
    """Le jour ou la pipeline newsletter ecrira son lien, la ligne apparaitra
    SANS QU'ON TOUCHE AU MODULE. C'est tout l'interet de percer le trou en v1."""
    chemin = tmp_path / "crochets.json"
    chemin.write_text(json.dumps(
        {"2026-05": {"newsletter_url": "https://substack/x",
                     "newsletter_label": "Le récap de mai"}}),
        encoding="utf-8")
    monkeypatch.setattr(A, "CROCHETS_PATH", str(chemin))
    txt = _corps()
    assert "https://substack/x" in txt and "Le récap de mai" in txt


def test_le_crochet_image_reste_vide_en_v1():
    assert A.illustration("2026-05") == ""
    assert "http" not in A.entete("2026-05", dt.date(2026, 6, 3), "mai", "",
                                  False)["content"]


def test_avec_une_image_lentete_la_porte(tmp_path, monkeypatch):
    chemin = tmp_path / "crochets.json"
    chemin.write_text(json.dumps({"2026-05": {"image_url": "https://img/x.png"}}),
                      encoding="utf-8")
    monkeypatch.setattr(A, "CROCHETS_PATH", str(chemin))
    tete = A.entete("2026-05", dt.date(2026, 6, 3), "mai", "", False)
    assert tete["content"].splitlines()[-1] == "https://img/x.png"


# ══════════════════════════════════ 11. LA LECTURE DU SHEET (regles empruntees)

def _ligne(nom, uuid, jour, series_uuid="s1", supply=1000, rarity="RARE"):
    return {"releaseDate": jour, "series_uuid": series_uuid, "veve_uuid": uuid,
            "veve_series_name": nom, "rarity": rarity, "supply_rarete": supply,
            "veve_licensor": "Marvel", "drop_method": "PURCHASE"}


def test_la_lecture_ramene_TOUT_et_marque_le_mercredi():
    """`series_du_mois` ne filtre rien : le COMPTEUR et la LISTE n'ecartent pas
    les memes choses, et chacun dit sa regle chez lui."""
    sh = FauxSheet({
        "🟢C-COMICS": [_ligne("Comic du mercredi", "u1", "2026-07-08",
                              series_uuid="c1"),          # 08/07/2026 = mercredi
                       _ligne("Comic du jeudi", "u2", "2026-07-09",
                              series_uuid="c2")],
        "🔵C-COLLECTIBLE": [],
    })
    out = A.series_du_mois(sh, 2026, 7)
    assert len(out) == 2
    assert {d["nom"]: d["mercredi"] for d in out} == {
        "Comic du mercredi": True, "Comic du jeudi": False}


def test_le_compteur_ecarte_les_comics_du_mercredi():
    """« Ce mois-ci N Drops » : le Comic Book Day est du volume, pas une
    sortie a annoncer (decision Preda du 04/08)."""
    series = [serie("a", "Collectible", "ua"),
              serie("b", "Comic du jeudi", "ub", genre="comic"),
              serie("c", "Comic du mercredi", "uc", genre="comic",
                    mercredi=True)]
    assert A.compter_drops(series) == 2


def test_seul_le_mois_demande_entre():
    sh = FauxSheet({
        "🟢C-COMICS": [],
        "🔵C-COLLECTIBLE": [_ligne("Juin", "u1", "2026-06-30", series_uuid="a"),
                            _ligne("Juillet", "u2", "2026-07-15", series_uuid="b"),
                            _ligne("Aout", "u3", "2026-08-01", series_uuid="c")],
    })
    assert {d["nom"] for d in A.series_du_mois(sh, 2026, 7)} == {"Juillet"}


def test_les_raretes_dune_serie_ne_font_quune_sortie():
    sh = FauxSheet({
        "🟢C-COMICS": [],
        "🔵C-COLLECTIBLE": [_ligne("Phoenix", "u1", "2026-07-15", supply=75),
                            _ligne("Phoenix", "u2", "2026-07-15", supply=1975)],
    })
    out = A.series_du_mois(sh, 2026, 7)
    assert len(out) == 1 and len(out[0]["lignes"]) == 2
    assert out[0]["total"] == 2050, "un collectible : la somme des raretes"


def test_le_tirage_dun_comic_nest_pas_une_somme():
    """`supply` d'un comic est celui de la SERIE, recopie sur chaque rarete :
    l'additionner donnait 5 x 1 000 et affichait un SOLD OUT a 20 %."""
    sh = FauxSheet({
        "🟢C-COMICS": [_ligne("Cap #7", "u1", "2026-07-09", series_uuid="k",
                              supply=1000),
                       _ligne("Cap #7", "u2", "2026-07-09", series_uuid="k",
                              supply=1000)],
        "🔵C-COLLECTIBLE": [],
    })
    assert A.series_du_mois(sh, 2026, 7)[0]["total"] == 1000


def test_lartwork_est_reconnu_depuis_le_sheet():
    sh = FauxSheet({
        "🟢C-COMICS": [],
        "🔵C-COLLECTIBLE": [_ligne("AP unique", "u1", "2026-07-15", supply=1,
                                   rarity="ARTIST_PROOF")],
    })
    assert A.est_artwork(A.series_du_mois(sh, 2026, 7)[0])


def test_les_journees_couvertes_sont_celles_qui_existent():
    sh = FauxSheet({"ChainItems": [{"date": "2026-07-01"}, {"date": "2026-07-02"},
                                   {"date": "2026-06-30"}]})
    assert A.jours_couverts(sh, A.jours_du_mois(2026, 7)) == ["2026-07-01",
                                                              "2026-07-02"]


# ═══════════════════════════════════════════════ 12. LE RENDU NE CASSE PAS

def test_le_message_ne_depasse_jamais_2000_caracteres():
    """Un 400 ici, c'est l'annonce du mois qui saute — et un mois ne se
    rattrape pas."""
    s = A.classer([serie(f"s{i}", "Nom très long " * 20, f"u{i}")
                   for i in range(60)],
                  {f"u{i}": 100 + i for i in range(60)})
    txt = A.corps("2026-05", "mai", 171, s,
                  [serie(f"z{i}", "À venir " * 30, f"v{i}")
                   for i in range(40)])["content"]
    assert len(txt) <= 2000


def test_ce_qui_deborde_est_la_LISTE_pas_les_liens():
    """⭐ On coupe par le milieu : ce qui doit survivre, c'est le bloc du bas.
    Tronquer la fin sacrifierait justement la partie utile."""
    s = A.classer([serie(f"s{i}", "Nom très long " * 20, f"u{i}")
                   for i in range(60)],
                  {f"u{i}": 100 + i for i in range(60)})
    txt = A.corps("2026-05", "mai", 171, s, [])["content"]
    assert A.LIEN_PARRAINAGE in txt
    assert A.LIEN_INVESTOR in txt
    assert f"<#{A.SALON_RECAP}>" in txt


# ═══════════════════════════════ 13. L'AFFICHE — un habillage, jamais un otage

def test_sans_affiche_on_poste_un_message_simple(monkeypatch, poste):
    monkeypatch.setenv("DISCORD_ANNONCE_WEBHOOK", "https://annonces")
    monkeypatch.setenv("DISCORD_ANNONCE_FORCE", "true")
    _monde(monkeypatch, series=[serie("s1", "Iron Man", "u1")],
           ventes={"u1": 500})
    A.run()
    assert poste[0]["fichier"] == ""


def test_avec_une_affiche_elle_est_TELEVERSEE(monkeypatch, poste, tmp_path):
    """⚠️ On TÉLÉVERSE, on ne pointe pas : une URL de pièce jointe Discord est
    signée et EXPIRE (piège déjà payé sur le module `retour`)."""
    monkeypatch.setenv("DISCORD_ANNONCE_WEBHOOK", "https://annonces")
    monkeypatch.setenv("DISCORD_ANNONCE_FORCE", "true")
    _monde(monkeypatch, series=[serie("s1", "Iron Man", "u1")],
           ventes={"u1": 500})
    png = str(tmp_path / "affiche.png")
    open(png, "wb").close()
    monkeypatch.setattr(A, "fabriquer_affiche", lambda *a, **k: png)
    A.run()
    assert poste[0]["fichier"] == png
    assert "http" not in poste[0]["payload"]["content"], (
        "l'affiche est televersee : aucune URL d'image ne doit rester")


def test_une_affiche_qui_echoue_ne_bloque_PAS_lannonce(monkeypatch, poste):
    """⭐ Un habillage qui prend l'annonce en otage est un bug, pas une
    fonctionnalité."""
    monkeypatch.setenv("DISCORD_ANNONCE_WEBHOOK", "https://annonces")
    monkeypatch.setenv("DISCORD_ANNONCE_FORCE", "true")
    monkeypatch.setenv("DISCORD_ANNONCE_AFFICHE", "true")
    _monde(monkeypatch, series=[serie("s1", "Iron Man", "u1")],
           ventes={"u1": 500})

    def boum(*a, **k):
        raise RuntimeError("Pillow est fâché")

    monkeypatch.setattr(A, "fabriquer_affiche", boum)
    with pytest.raises(RuntimeError):
        A.run()                       # le banc constate que run() n'attrape pas


def test_le_moteur_daffiche_absent_ne_bloque_pas(monkeypatch, poste):
    """`fabriquer_affiche` avale tout : moteur absent, fond manquant, Pillow
    qui râle -> "" et l'annonce part."""
    monkeypatch.setenv("DISCORD_ANNONCE_AFFICHE", "true")
    monkeypatch.setenv("ANNONCE_VISUEL_FOND", "/nulle/part.png")
    assert A.fabriquer_affiche(object(), "2026-07", "juillet",
                               [serie("a", "X", "ua")]) == ""


def test_linterrupteur_de_laffiche_est_lu_a_lexecution(monkeypatch):
    monkeypatch.setenv("DISCORD_ANNONCE_AFFICHE", "false")
    assert A.fabriquer_affiche(object(), "2026-07", "juillet",
                               [serie("a", "X", "ua")]) == ""


# ═══════════════════════════ 14. LA BANNIERE — decorative, rien de plus

def test_la_banniere_mene_vers_une_PIECE_pas_vers_le_blog(monkeypatch):
    """⭐⭐ Preda a tranché : elle est DÉCORATIVE. Le seul filtre qui garde du
    sens est la cible — une bannière « programme de parrainage » est une
    affiche de texte, elle ne montre aucune pièce."""
    from scraper import annonce_images as ai
    liste = [
        {"id": "a", "position": 1, "backup": False,
         "cible": "https://www.veve.me/blog/veve/updates/referral-program",
         "image": "https://cdn/blog.jpg"},
        {"id": "b", "position": 4, "backup": False,
         "cible": "https://www.veve.me/collectibles/en/series/xxx",
         "image": "https://cdn/serie.jpg"},
        {"id": "c", "position": 2, "backup": True,
         "cible": "https://www.veve.me/collectibles/en/series/yyy",
         "image": "https://cdn/reserve.jpg"},
    ]
    b = ai.banniere_decorative(liste)
    assert b["id"] == "b", "le blog et la reserve doivent etre ecartes"


def test_a_egalite_on_prend_la_premiere_du_carrousel():
    from scraper import annonce_images as ai
    liste = [
        {"id": "loin", "position": 8, "backup": False,
         "cible": "/collectibles/en/series/a", "image": "https://cdn/8.jpg"},
        {"id": "tete", "position": 2, "backup": False,
         "cible": "/collectibles/en/crafts/b", "image": "https://cdn/2.jpg"},
    ]
    assert ai.banniere_decorative(liste)["id"] == "tete"


def test_un_carrousel_sans_piece_rend_vide():
    from scraper import annonce_images as ai
    assert ai.banniere_decorative([
        {"id": "a", "position": 1, "backup": False,
         "cible": "https://www.veve.me/blog/x", "image": "https://cdn/x.jpg"}
    ]) == {}


def test_la_banniere_ARRIVE_JUSQU_AU_RENDU(monkeypatch, tmp_path):
    """🔴 LE TEST QUI MANQUAIT, ET QUI A COUTE DEUX RUNS.

    `fabriquer_affiche` recevait la banniere en parametre… et la RECALCULAIT en
    interne depuis le crochet, donc "". Le run choisissait bien une banniere
    (« position 1 du carrousel ») puis publiait un bandeau sombre, en affichant
    les DEUX messages a la suite.
    ⭐⭐⭐ **UN PARAMETRE QU'ON RECALCULE EN INTERNE N'EST PAS UN PARAMETRE,
    C'EST UN LEURRE.** Aucun test ne le voyait parce qu'aucun test ne suivait la
    valeur de bout en bout : on testait le CHOIX, et on testait le RENDU, mais
    jamais le CHEMIN entre les deux."""
    vu = {}
    from outils.annonce_visuel import rendu

    def capture(mois, banniere, tuiles, carte, sortie, fond=""):
        vu["banniere"] = banniere
        return sortie

    monkeypatch.setattr(rendu, "composer", capture)
    monkeypatch.setenv("DISCORD_ANNONCE_AFFICHE", "true")
    monkeypatch.setattr(A, "CROCHETS_PATH", str(tmp_path / "vide.json"))

    A.fabriquer_affiche(object(), "2026-07", "juillet",
                        [serie("a", "X", "ua")],
                        banniere="https://cdn/choisie.jpg")
    assert vu.get("banniere") == "https://cdn/choisie.jpg", (
        "la banniere choisie n'arrive pas au rendu")


def test_le_crochet_manuel_garde_le_dernier_mot(monkeypatch, tmp_path):
    """⭐ Un automatisme qui ne se laisse pas contredire oblige a le debrancher
    entierement le jour ou il se trompe."""
    chemin = tmp_path / "crochets.json"
    chemin.write_text(json.dumps({"2026-07": {"banniere_url":
        "https://www.veve.me/_next/image?url=https%3A%2F%2Fcdn%2Fx.jpg&w=1200"}}),
        encoding="utf-8")
    monkeypatch.setattr(A, "CROCHETS_PATH", str(chemin))
    from scraper import annonce_images as ai

    def jamais(*a, **k):
        raise AssertionError("le carrousel ne doit pas etre interroge")

    monkeypatch.setattr(ai, "banniere_decorative", jamais)
    assert A.banniere_du_mois("2026-07") == "https://cdn/x.jpg"


def test_sans_banniere_le_bandeau_reste_sombre_et_le_DIT(monkeypatch, capsys):
    from scraper import annonce_images as ai
    monkeypatch.setattr(ai, "banniere_decorative", lambda *a, **k: {})
    assert A.banniere_du_mois("2026-07") == ""
    assert "bandeau restera sombre" in capsys.readouterr().out


def test_le_module_est_bien_dans_le_hub():
    from scraper import discord_hub
    assert discord_hub.MODULES.get("annonce") is A.run
