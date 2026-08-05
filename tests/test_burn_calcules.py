# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_burn_calcules.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""Les burns CALCULES dans le post 🔥 BURN — ce que le lot 68 branche.

⭐⭐ CE BANC SURVEILLE CE QUI, EN SE TROMPANT, PUBLIE QUAND MEME. Trois
mensonges sont possibles ici, et chacun a l'air d'une news :

  1. **annoncer un burn sur un comic qui ne brulera jamais** (les 2,0 % de
     retenues — 108 sur 164 dans la mesure du 05/08) ;
  2. **presenter une DEDUCTION comme une observation** — la carte doit dire
     d'ou vient sa date ;
  3. **doubler une carte** : un item calcule qui apparait ensuite sur la page
     doit RETROUVER sa carte, pas en creer une seconde.

Et un quatrieme, plus sournois, qui n'est pas un mensonge mais un silence :
le garde-fou anti-avalanche compte les items neufs — s'il comptait aussi les
calcules, il clorait TOUTES les cartes d'un coup, y compris celles qu'on vient
de calculer.

    python3 -m pytest tests/test_burn_calcules.py -q
"""

import datetime as _dt

import pytest

from scraper import discord_burn as B


AUJ = _dt.date(2026, 8, 5)


def fiche(nom, sortie, supply, retenues, genre="comic", cle=None):
    return {
        "genre": genre, "nom": nom, "sortie": sortie, "supply": supply,
        "retenues": retenues, "cle_serie": cle or nom.lower(),
        "image": "", "url": "", "marque": "", "rarete": "COMMON",
        "prix": None, "atl": None, "ath": None,
    }


# Les cas viennent tous de la mesure du 05/08 sur le GraphQL VeVe.
FICHES = {
    # ✅ brule : jeudi, retenues 9,9 % — burn calcule le 06/08
    "asm547": fiche("The Amazing Spider-Man #547", "2026-07-07", 1000, 99,
                    cle="asm547"),
    # ✅ brule : burn calcule le 20/08
    "asm548": fiche("The Amazing Spider-Man #548", "2026-07-21", 1000, 99,
                    cle="asm548"),
    # ⛔ ne brule JAMAIS : retenues 2,0 %
    "bouncer": fiche("Bouncer Book 1", "2026-07-09", 1000, 20, cle="bouncer"),
    # ⛔ mercredi
    "mercredi": fiche("Secret Wars II #1", "2026-07-15", 1000, 99,
                      cle="mercredi"),
    # ⛔ un collectible n'est pas un comic
    "craft": fiche("Ron English Reward", "2026-07-26", 600, 15,
                   genre="collectible", cle="craft"),
}


def test_seuls_les_comics_qui_brulent_sortent():
    out = B.burns_calcules(FICHES, {}, {}, AUJ)
    assert [i["uuid"] for i in out] == ["asm547", "asm548"], (
        "un comic à 2,0 % de retenues, un comic du mercredi ou un craft ne "
        "doit jamais recevoir de carte calculée")


def test_tries_du_plus_proche_au_plus_lointain():
    out = B.burns_calcules(FICHES, {}, {}, AUJ)
    assert [i["_jour_calcule"] for i in out] == [_dt.date(2026, 8, 6),
                                                 _dt.date(2026, 8, 20)]


def test_horizon_borne_l_avance():
    """Avec un horizon court, seul le burn imminent sort. ⭐ Le reste
    reviendra tout seul en approchant — rien n'est perdu, rien n'est publié
    trop tôt."""
    out = B.burns_calcules(FICHES, {}, {}, AUJ, horizon=7)
    assert [i["uuid"] for i in out] == ["asm547"]


def test_un_burn_deja_passe_ne_ressort_pas():
    f = {"vieux": fiche("Avengers #8", "2026-04-02", 1000, 99, cle="vieux")}
    assert B.burns_calcules(f, {}, {}, AUJ) == []


# ---------------------------------------------------------------------------
# 🔴 LA PAGE FAIT FOI DES QU'ELLE PARLE
# ---------------------------------------------------------------------------
def test_un_item_deja_sur_la_page_n_est_pas_double():
    """⭐ Sinon la même série aurait deux cartes : celle de VeVe et la nôtre."""
    out = B.burns_calcules(FICHES, {"asm547": {}}, {}, AUJ)
    assert [i["uuid"] for i in out] == ["asm548"]


def test_une_carte_deja_publiee_ou_close_ne_se_recree_pas():
    assert [i["uuid"] for i in
            B.burns_calcules(FICHES, {}, {"asm547": {"mid": "123"}}, AUJ)
            ] == ["asm548"]
    assert [i["uuid"] for i in
            B.burns_calcules(FICHES, {}, {"asm547": {"clos": True}}, AUJ)
            ] == ["asm548"]


def test_sans_sheet_le_module_retombe_sur_son_comportement_d_avant():
    """⛔ Pas de fiches = pas de calcul, et surtout pas d'erreur. Le Sheet est
    FACULTATIF pour ce module, et il doit le rester."""
    assert B.burns_calcules({}, {}, {}, AUJ) == []
    assert B.burns_calcules(None, {}, {}, AUJ) == []


# ---------------------------------------------------------------------------
# 🔴 LA FORME DES PSEUDO-ITEMS
# ---------------------------------------------------------------------------
def test_ne_fabrique_aucun_chiffre_qu_on_n_a_pas_lu():
    """`restant` vient du « N left » de la PAGE. Sur un item calculé, on ne
    l'a pas lu : le poser à autre chose que 0 ferait crier la contre-mesure
    page-vs-calcul contre elle-même."""
    it = B.burns_calcules(FICHES, {}, {}, AUJ)[0]
    assert it["restant"] == 0
    assert it["jours"] is None
    assert it["calcule"] is True
    assert it["famille"] == "comics"       # l'id GraphQL d'un comic = series_uuid


def test_meme_forme_que_les_items_de_la_page():
    """⭐ La boucle principale ne doit faire AUCUNE différence entre les deux —
    c'est ce qui fait qu'un item calculé retrouve sa carte quand VeVe finit
    par l'annoncer."""
    it = B.burns_calcules(FICHES, {}, {}, AUJ)[0]
    attendus = {"famille", "uuid", "url", "titre", "restant", "jours"}
    assert attendus <= set(it)


# ---------------------------------------------------------------------------
# LA DATE AFFICHEE
# ---------------------------------------------------------------------------
def test_jour_burn_prefere_le_badge_de_la_page():
    """Quand VeVe parle, c'est VeVe qui a raison."""
    j = B._jour_burn({"jours": 3}, FICHES["asm547"])
    assert j == _dt.date.today() + _dt.timedelta(days=3)


def test_jour_burn_calcule_quand_la_page_se_tait():
    assert B._jour_burn({"jours": None}, FICHES["asm547"]) == _dt.date(2026, 8, 6)


def test_jour_burn_N_INVENTE_PLUS_de_date_sur_un_item_qui_ne_brule_pas():
    """🔴 LE VERROU DU LOT 68. L'ancien repli faisait `sortie + 30 j` sur
    n'importe quoi : il datait le feu de 108 comics sur 164 qui ne brûlent
    jamais, et se trompait de ~15 jours sur les crafts.
    ⭐⭐ *Un repli qui rend un nombre plausible est pire qu'un vide.*"""
    assert B._jour_burn({"jours": None}, FICHES["bouncer"]) is None
    assert B._jour_burn({"jours": None}, FICHES["craft"]) is None
    assert B._jour_burn({"jours": None}, {}) is None


def test_la_carte_DIT_que_la_date_est_calculee():
    """⭐⭐ Une déduction publiée sans dire qu'elle en est une devient une
    observation dans l'esprit du lecteur."""
    d = {"statut": "attente", "nom": "ASM #547", "genre": "comic",
         "ts": 1786000000, "estime": True, "calcule": True,
         "circulation": 901, "vendues": 385, "brulees": 0, "a_bruler": 516,
         "supply_final": 385, "part": 57.3, "url": "https://x", "fiche": {},
         "note": "", "vu_le": "05/08/2026", "brulees_reelles": 0,
         "a_bruler_annonce": 516, "part_reelle": 0.0,
         "circulation_depart": 901}
    txt = B.carte(d)["embeds"][0]["description"]
    assert "calculée" in txt and "pas encore" in txt
    assert "au plus tôt" in txt

    d["calcule"] = False
    txt2 = B.carte(d)["embeds"][0]["description"]
    assert "pas encore mis" not in txt2 and "*(estimé)*" in txt2
