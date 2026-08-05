# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_burn_prevu.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""Banc de la date de burn CALCULEE.

⭐⭐ CE BANC SE JUGE SUR CE QU'IL LAISSE PASSER, pas sur ce qu'il verifie. La
faute possible ici n'est pas « ca plante » : c'est **une date de burn ecrite sur
un comic qui ne brulera jamais**. Elle a l'air d'une donnee, elle se publie, et
personne ne la remet en cause.

C'est exactement ce qui serait arrive avec la regle telle qu'ecrite au plan :
« comics 2026 hors mercredi » aurait date le feu de **108 comics sur 164** qui
n'ont jamais brule. Les cas reels ci-dessous sont donc des VERROUS, pas des
illustrations : ils viennent tous de la mesure du 05/08/2026, chiffres releves
un par un sur le GraphQL VeVe.

    python3 -m pytest tests/test_burn_prevu.py -q
"""

import datetime as _dt

import pytest

from scraper import burn_prevu as B


# ---------------------------------------------------------------------------
# LES CAS REELS. Chaque ligne a ete relevee le 05/08/2026 sur
# web.api.prod.veve.me/graphql. (nom, sortie, tirage, retenues, a_brule)
# ---------------------------------------------------------------------------
BRULENT = [
    # nom                              sortie        emis  ret
    ("The Amazing Spider-Man #546",   "2026-07-02", 1000,  99),   # 152 brulees
    ("Avengers vs X-Men #6 (2012)",   "2026-06-12", 1000,  99),   # 636 brulees
    ("Uncanny X-Men #131 (2013)",     "2026-06-19", 1000,  99),   # 704 brulees
    ("Avengers #8 (1998)",            "2026-04-02", 1000,  99),   # 598 brulees
    ("Doctor Strange #8 (2023)",      "2026-02-05", 3000, 342),   # 2 370 brulees
    ("The X-Men (1963) ce33b280",     "2026-06-25", 1000,  99),   # 471 brulees
]

NE_BRULENT_PAS = [
    # les 2,0 % — une ligne editoriale entiere, jamais un burn
    ("Bouncer Book 1",                "2026-04-09", 1000,  20),
    ("Metal Hurlant Vol.4",           "2026-04-09", 1000,  20),
    ("Final Incal #2 (2014)",         "2026-02-05", 1000,  20),
    ("Adam Sarlech #1",               "2026-01-08", 1000,  20),
    ("Millennium Book 4",             "2026-03-05", 1000,  20),
]


@pytest.mark.parametrize("nom,sortie,emis,ret", BRULENT)
def test_les_comics_qui_brulent_recoivent_une_date(nom, sortie, emis, ret):
    """Les 43 mesures « A BRULE » ont toutes une part retenue >= 9,9 %."""
    d = B.date_burn_prevue(sortie, emis, ret)
    assert d, f"{nom} : aucune date alors que ce comic a reellement brule"
    attendu = (_dt.date.fromisoformat(sortie)
               + _dt.timedelta(days=B.DELAI_JOURS)).isoformat()
    assert d == attendu


@pytest.mark.parametrize("nom,sortie,emis,ret", NE_BRULENT_PAS)
def test_les_comics_a_2pct_ne_recoivent_JAMAIS_de_date(nom, sortie, emis, ret):
    """🔴 LE VERROU CENTRAL DE CE BANC.

    108 comics sur 164 sont dans ce cas, J+30 largement depasse, zero burn. La
    regle « 2026 hors mercredi » leur aurait donne une date a tous."""
    assert B.date_burn_prevue(sortie, emis, ret) == "", (
        f"{nom} : date de burn inventee sur un comic qui ne brule pas")


def test_le_mercredi_est_exclu_meme_a_10pct():
    """Ultraman #10 : sorti le mercredi 07/01/2026, retenues 9,9 %, J+210 au
    05/08 — et toujours 0 brulee. La condition « hors mercredi » n'est pas une
    precaution de style.
    ⚠️ Mesure a n=3. Si ce test devient faux un jour, c'est cette condition qui
    tombe la premiere, et il faudra le mesurer avant de la retirer."""
    assert _dt.date.fromisoformat("2026-01-07").weekday() == B.JOUR_COMIC_DAY
    assert B.date_burn_prevue("2026-01-07", 1000, 99) == ""


def test_un_craft_n_est_pas_un_comic():
    """Ron English Collectors Reward : fenetre de ~14 jours, pas 30. Appliquer
    la regle des comics aux crafts annoncerait le feu deux semaines trop tard."""
    assert B.date_burn_prevue("2026-07-26", 600, 15, categorie="collectible") == ""


# ---------------------------------------------------------------------------
# LES VIDES — « je ne sais pas » ne doit jamais devenir « il ne brule pas »
# de facon indiscernable d'une vraie reponse.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("emis,ret", [(None, 99), (1000, None), ("", ""),
                                      (0, 0), ("abc", "def")])
def test_ligne_non_enrichie_ne_produit_pas_de_date(emis, ret):
    assert B.date_burn_prevue("2026-07-02", emis, ret) == ""
    assert B.part_retenue(emis, ret) is None or B.part_retenue(emis, ret) == 0.0


def test_part_retenue_ne_replie_pas_sur_zero():
    """⛔ Un comic non enrichi ressemblerait a un comic sans retenues, donc a
    un comic qui ne brule pas. Un vide se comble ; une fausse certitude, non."""
    assert B.part_retenue(1000, None) is None
    assert B.part_retenue(None, 99) is None
    assert B.part_retenue(1000, 99) == pytest.approx(9.9)


def test_date_illisible_rend_vide():
    for mauvais in ("", None, "pas une date", "46212.7 truc", "0", "999999"):
        assert B.date_burn_prevue(mauvais, 1000, 99) == ""


# ---------------------------------------------------------------------------
# LE SEUIL — il doit etre un FOSSE, pas un reglage fin
# ---------------------------------------------------------------------------
def test_le_seuil_tombe_au_milieu_du_fosse():
    """Mesure : 2,0 % d'un cote, 9,9 % de l'autre, aucune valeur entre les deux.
    Un seuil qui separerait a 0,1 pres serait ajuste sur l'echantillon ; celui-ci
    donne le meme verdict partout entre 3 % et 9 %."""
    for seuil in (3.0, 5.0, 7.0, 9.0):
        avant = B.SEUIL_RETENUES_PCT
        try:
            B.SEUIL_RETENUES_PCT = seuil
            assert B.date_burn_prevue("2026-07-02", 1000, 99)      # 9,9 %
            assert not B.date_burn_prevue("2026-04-09", 1000, 20)  # 2,0 %
        finally:
            B.SEUIL_RETENUES_PCT = avant


# ---------------------------------------------------------------------------
# J+30 EST UN PLANCHER
# ---------------------------------------------------------------------------
def test_j30_est_un_plancher_annonce_comme_tel():
    """Le plus rapide des 43 burns mesures a eu lieu a J+34, aucun avant J+30.
    La constante est donc une BORNE BASSE : elle ne doit jamais depasser 30,
    sinon la colonne annoncerait un feu deja passe."""
    assert B.DELAI_JOURS <= 34


# ---------------------------------------------------------------------------
# 🔴 L'ACCORD DES DEUX PARSEURS
# ---------------------------------------------------------------------------
def test_accord_avec_discord_drops():
    """⭐⭐ QUAND ON NE PEUT PAS PARTAGER LE CODE, ON EPINGLE L'ACCORD.

    `burn_prevu.jour_de_sortie` est le SECOND parseur de `releaseDate` du
    depot ; le premier est `discord_drops._quand`, inimportable ici (`sheets`
    appelle `burn_prevu`, et `discord_drops` importe `sheets` : circulaire).
    Ce test rejoue les deux sur la meme batterie et exige le meme jour — le
    jour ou l'un evolue seul, il tombe."""
    from scraper.discord_drops import _quand
    for brut in ("2026-07-02T17:00:00.000Z", "2026-07-02 17:00:00",
                 "2026-07-02", "46205.708", "46205"):
        attendu = _quand(brut)[0]
        assert B.jour_de_sortie(brut) == attendu, (
            f"desaccord sur « {brut} » : "
            f"burn_prevu={B.jour_de_sortie(brut)!r} _quand={attendu!r}")


def test_format_jour_mois_de_l_export_catalogue():
    """`catalogue.csv.gz` sort en JJ/MM/AAAA — format que `_quand` ne lit pas
    et que ce module doit lire, sinon toute mesure hors ligne rend "" en
    silence. ⚠️ C'est le seul endroit ou les deux parseurs DIVERGENT, et la
    divergence est voulue : elle est ecrite ici pour ne pas se decouvrir."""
    assert B.jour_de_sortie("02/07/2026 17:00:00") == "2026-07-02"
    assert B.jour_de_sortie("02/07/2026") == "2026-07-02"


# ---------------------------------------------------------------------------
# LE GAIN : les burns a venir, sans une requete
# ---------------------------------------------------------------------------
def test_burns_a_venir_trie_et_borne():
    lignes = [
        {"releaseDate": "2026-07-21", "supply": 1000, "supply_withheld": 99,
         "category": "comic", "name": "ASM #548"},
        {"releaseDate": "2026-07-07", "supply": 1000, "supply_withheld": 99,
         "category": "comic", "name": "ASM #547"},
        {"releaseDate": "2026-04-09", "supply": 1000, "supply_withheld": 20,
         "category": "comic", "name": "Bouncer"},          # ne brule pas
        {"releaseDate": "2026-04-02", "supply": 1000, "supply_withheld": 99,
         "category": "comic", "name": "Avengers #8"},      # deja brule
    ]
    out = B.burns_a_venir(lignes, aujourdhui=_dt.date(2026, 8, 5))
    assert [n for _, l in out for n in [l["name"]]] == ["ASM #547", "ASM #548"]
    assert out[0][0] == "2026-08-06"
    assert B.burns_a_venir([], aujourdhui=_dt.date(2026, 8, 5)) == []
