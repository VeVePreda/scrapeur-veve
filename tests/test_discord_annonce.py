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
  * le webhook manquant qui retombe sur un autre salon ;
  * le message publie sur une selection vide ou une fenetre de ventes trouee ;
  * le doublon (deux @everyone pour le meme mois) ;
  * l'entete publiee sans que le mois soit memorise -> re-ping le lendemain.

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
          supply=1000, jour="2026-07-10"):
    return {"cle": cle, "genre": genre, "jour": jour, "ts": 0,
            "nom": nom, "annee": "", "marque": "", "licence": licence,
            "methode": "", "exclusive": False, "total": supply,
            "lignes": [{"rarete": "RARE", "supply": supply,
                        "uuid": ventes_uuid}]}


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
    yield


@pytest.fixture
def poste(monkeypatch):
    """Enregistre tout ce que le module ENVOIE. Rien ne part sur le reseau."""
    envois = []

    def faux_poster(wh, th, payload):
        envois.append({"webhook": wh, "thread": th, "payload": payload})
        return str(1000 + len(envois))

    monkeypatch.setattr(api, "poster", faux_poster)
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
    tete = poste[0]["payload"]
    assert "@everyone" not in tete["content"]
    assert tete["allowed_mentions"]["parse"] == [], (
        "le texte ne dit pas @everyone mais la permission est ouverte : "
        "le jour ou le texte changera, le serveur sonnera")


def test_interrupteur_ouvert_le_ping_part(monkeypatch, poste):
    monkeypatch.setenv("DISCORD_ANNONCE_WEBHOOK", "https://annonces")
    monkeypatch.setenv("DISCORD_ANNONCE_EVERYONE", "true")
    monkeypatch.setenv("DISCORD_ANNONCE_FORCE", "true")
    _monde(monkeypatch, series=[serie("s1", "Iron Man", "u1")],
           ventes={"u1": 500})
    assert A.run() == 0
    tete = poste[0]["payload"]
    assert "@everyone" in tete["content"]
    assert tete["allowed_mentions"]["parse"] == ["everyone"], (
        "le texte dit @everyone mais la permission est bridee : "
        "le ping ne partira pas, et personne ne le verra")


def test_le_corps_ne_ping_jamais(monkeypatch, poste):
    monkeypatch.setenv("DISCORD_ANNONCE_WEBHOOK", "https://annonces")
    monkeypatch.setenv("DISCORD_ANNONCE_EVERYONE", "true")
    monkeypatch.setenv("DISCORD_ANNONCE_FORCE", "true")
    _monde(monkeypatch, series=[serie("s1", "Iron Man", "u1")],
           ventes={"u1": 500})
    A.run()
    assert len(poste) == 2
    corps = poste[1]["payload"]
    assert corps["allowed_mentions"]["parse"] == []
    assert "@everyone" not in corps["content"]


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
        etat = json.load(f)
    assert etat.get("dernier_mois") == A.cle_mois(), (
        "le mois n'est pas memorise : demain, @everyone repartira")


def test_entete_ratee_rien_nest_memorise(monkeypatch):
    """A l'inverse : si RIEN n'est parti, le mois doit rester a publier."""
    monkeypatch.setenv("DISCORD_ANNONCE_WEBHOOK", "https://annonces")
    monkeypatch.setenv("DISCORD_ANNONCE_FORCE", "true")
    _monde(monkeypatch, series=[serie("s1", "Iron Man", "u1")],
           ventes={"u1": 500})
    monkeypatch.setattr(api, "poster", lambda *a, **k: None)
    monkeypatch.setattr(A, "append_log", lambda *a, **k: None)
    assert A.run() == 1
    assert not os.path.exists(A.STATE_PATH)


# ══════════════════════════════════════ 6. LE CLASSEMENT « LE PLUS VENDU »

def test_le_classement_suit_les_ventes_pas_le_tirage():
    s = [serie("a", "Petit tirage", "ua", supply=100),
         serie("b", "Gros vendeur", "ub", supply=50000),
         serie("c", "Invendu", "uc")]
    out = A.classer(s, {"ua": 90, "ub": 4000, "uc": 0})
    assert [d["nom"] for d in out] == ["Gros vendeur", "Petit tirage"], (
        "une serie a 0 vente n'est pas « notable »")


def test_le_sold_out_ne_sannonce_que_quand_il_est_vrai():
    epuise = A.classer([serie("a", "Vador", "ua", supply=500)], {"ua": 500})[0]
    reste = A.classer([serie("b", "Thor", "ub", supply=500)], {"ub": 499})[0]
    assert "SOLD OUT" in A.ligne_serie(1, epuise)
    assert "SOLD OUT" not in A.ligne_serie(1, reste)


def test_une_serie_additionne_ses_elements():
    d = serie("a", "Phoenix Five", "u1")
    d["lignes"].append({"rarete": "ULTRA_RARE", "supply": 75, "uuid": "u2"})
    out = A.classer([d], {"u1": 300, "u2": 75})
    assert out[0]["ventes"] == 375


# ═══════════════════════════════════════════ 7. LE THEME ET SON REPLI NEUTRE

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


def test_le_titre_du_corps_suit_le_theme(monkeypatch):
    s = A.classer([serie("a", "Vador", "ua", licence="Star Wars"),
                   serie("b", "Yoda", "ub", licence="Star Wars")],
                  {"ua": 5000, "ub": 4000})
    titre = A.corps("2026-07", "juillet 2026", s, [], 31, 31)["embeds"][0]["title"]
    assert "Star Wars" in titre
    neutre = A.corps("2026-07", "juillet 2026",
                     A.classer([serie("a", "X", "ua", licence="Marvel"),
                                serie("b", "Y", "ub", licence="Disney")],
                               {"ua": 100, "ub": 100}),
                     [], 31, 31)["embeds"][0]["title"]
    assert neutre == "🌟 Le mois de juillet 2026", (
        "sans licence dominante, le titre ne doit NOMMER aucun theme")


# ══════════════════════════════════════════ 8. LA FENETRE PARTIELLE SE DIT

def test_une_fenetre_incomplete_est_ECRITE_dans_le_message():
    """Un filtre silencieux est un mensonge par omission."""
    s = A.classer([serie("a", "Vador", "ua")], {"ua": 500})
    pied = A.corps("2026-07", "juillet 2026", s, [], 24, 31)["embeds"][0]["footer"]["text"]
    assert "24" in pied and "31" in pied
    complet = A.corps("2026-07", "juillet 2026", s, [], 31, 31)["embeds"][0]["footer"]["text"]
    assert "31 jours sur" not in complet


# ═══════════════════════════════ 9. LES CROCHETS v1 (newsletter, illustration)

def test_sans_crochet_aucune_ligne_newsletter():
    s = A.classer([serie("a", "Vador", "ua")], {"ua": 500})
    champs = A.corps("2026-07", "juillet 2026", s, [], 31, 31)["embeds"][0]["fields"]
    assert not [c for c in champs if "newsletter" in c["name"].lower()]


def test_le_crochet_newsletter_sallume_tout_seul(tmp_path, monkeypatch):
    """Le jour ou la pipeline newsletter ecrira son lien, la ligne apparaitra
    SANS QU'ON TOUCHE AU MODULE. C'est tout l'interet de percer le trou en v1."""
    chemin = tmp_path / "crochets.json"
    chemin.write_text(json.dumps(
        {"2026-07": {"newsletter_url": "https://substack/x",
                     "newsletter_label": "Le récap de juillet"}}),
        encoding="utf-8")
    monkeypatch.setattr(A, "CROCHETS_PATH", str(chemin))
    s = A.classer([serie("a", "Vador", "ua")], {"ua": 500})
    champs = A.corps("2026-07", "juillet 2026", s, [], 31, 31)["embeds"][0]["fields"]
    ligne = [c for c in champs if "newsletter" in c["name"].lower()]
    assert ligne and "substack" in ligne[0]["value"]


def test_le_crochet_image_reste_vide_en_v1():
    assert A.illustration("2026-07") == ""
    assert "embeds" not in A.entete("2026-07", "juillet 2026", "août", False)


def test_avec_une_image_lentete_la_porte(tmp_path, monkeypatch):
    chemin = tmp_path / "crochets.json"
    chemin.write_text(json.dumps({"2026-07": {"image_url": "https://img/x.png"}}),
                      encoding="utf-8")
    monkeypatch.setattr(A, "CROCHETS_PATH", str(chemin))
    tete = A.entete("2026-07", "juillet 2026", "août", False)
    assert tete["embeds"][0]["image"]["url"] == "https://img/x.png"


# ══════════════════════════════════ 10. LA LECTURE DU SHEET (regles empruntees)

def _ligne(nom, uuid, jour, series_uuid="s1", supply=1000):
    return {"releaseDate": jour, "series_uuid": series_uuid, "veve_uuid": uuid,
            "veve_series_name": nom, "rarity": "RARE", "supply_rarete": supply,
            "veve_licensor": "Marvel", "drop_method": "PURCHASE"}


def test_les_comics_du_mercredi_sont_ecartes():
    """3 055 series sur 4 195 : du remplissage, pas de l'actualite. Le filtre
    reste celui de `discord_drops` — on ne le reapprend pas ici."""
    sh = FauxSheet({
        "🟢C-COMICS": [_ligne("Comic du mercredi", "u1", "2026-07-08",
                              series_uuid="c1"),          # 08/07/2026 = mercredi
                       _ligne("Comic du jeudi", "u2", "2026-07-09",
                              series_uuid="c2")],
        "🔵C-COLLECTIBLE": [],
    })
    noms = {d["nom"] for d in A.series_du_mois(sh, 2026, 7)}
    assert noms == {"Comic du jeudi"}


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


def test_les_journees_couvertes_sont_celles_qui_existent():
    sh = FauxSheet({"ChainItems": [{"date": "2026-07-01"}, {"date": "2026-07-02"},
                                   {"date": "2026-06-30"}]})
    assert A.jours_couverts(sh, A.jours_du_mois(2026, 7)) == ["2026-07-01",
                                                              "2026-07-02"]


# ═══════════════════════════════════════════════ 11. LE RENDU NE CASSE PAS

def test_un_champ_ne_depasse_jamais_la_limite_discord():
    """1 024 caracteres par champ. Un 400 ici, c'est l'annonce du mois qui
    saute — et un mois ne se rattrape pas."""
    s = A.classer([serie(f"s{i}", "Nom très long " * 12, f"u{i}")
                   for i in range(40)],
                  {f"u{i}": 100 + i for i in range(40)})
    emb = A.corps("2026-07", "juillet 2026", s, [], 31, 31)["embeds"][0]
    for champ in emb["fields"]:
        assert len(champ["value"]) <= 1024


def test_les_liens_de_veve_france_sont_dans_le_message():
    s = A.classer([serie("a", "Vador", "ua")], {"ua": 500})
    champs = A.corps("2026-07", "juillet 2026", s, [], 31, 31)["embeds"][0]["fields"]
    tout = " ".join(c["value"] for c in champs)
    for lien in (A.LIEN_PARRAINAGE, A.LIEN_CLASSEMENTS, A.LIEN_RECAP,
                 A.LIEN_INVESTOR, A.LIEN_X):
        assert lien in tout


def test_le_module_est_bien_dans_le_hub():
    from scraper import discord_hub
    assert discord_hub.MODULES.get("annonce") is A.run
