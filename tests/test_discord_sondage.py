# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_discord_sondage.py

"""🗳️ LE SONDAGE A DEUX SALONS — un votant, une voix.

Depuis le 28/07/2026 la carte de drop est postee dans DEUX salons : le post
📦DROP (partie INVESTISSEUR) et 📘⎮sondage-drop (PUBLIC). Le retour sur drop en
tire deux lignes, et **une personne presente des deux cotes ne compte que cote
investisseur**.

CE QUE CES TESTS PROTEGENT, ET POURQUOI ILS SONT PUREMENT LOCAUX
---------------------------------------------------------------
Le bug qu'on redoute ici ne leve aucune exception : il rend un TOTAL FAUX QUI A
L'AIR JUSTE (12 + 7 = 19 alors que 4 personnes ont vote deux fois). Une erreur
pareille ne se voit ni dans les logs, ni a l'oeil sur une carte Discord — elle
ne se voit que si on la teste. La regle vit donc dans une fonction PURE,
`fusionner_votes`, et c'est elle qu'on epingle : zero reseau, zero Sheet, zero
token. Les tests tournent partout, y compris hors ligne.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.discord_retour import (fusionner_votes,      # noqa: E402
                                    lignes_sondage,
                                    normaliser_sondage)

D, M, X = "🇩", "🇲", "❌"


# --------------------------------------------------------- le cas nominal

def test_deux_salons_sans_recouvrement():
    """Personne ne vote deux fois : les deux lignes sont intactes."""
    r = fusionner_votes({D: {"a", "b"}, M: {"c"}},
                        {D: {"x"}, X: {"y", "z"}})
    assert r["prive"] == {D: 2, M: 1}
    assert r["public"] == {D: 1, X: 2}
    assert r["doublons"] == 0


def test_ordre_daffichage_stable():
    """🇩 puis 🇲 puis ❌, quel que soit l'ordre rendu par l'API. Un ordre qui
    change d'une carte a l'autre se lit mal."""
    r = fusionner_votes({X: {"a"}, D: {"b"}, M: {"c"}}, {})
    assert list(r["prive"]) == [D, M, X]


# ------------------------------------------------- LE COEUR : le dedoublonnage

def test_le_meme_vote_des_deux_cotes_ne_compte_quune_fois():
    """« alice » vote 🇩 partout : une seule voix, cote investisseur."""
    r = fusionner_votes({D: {"alice"}}, {D: {"alice", "bob"}})
    assert r["prive"] == {D: 1}
    assert r["public"] == {D: 1}          # bob seul
    assert r["doublons"] == 1


def test_vote_contradictoire_le_prive_gagne():
    """« alice » vote 🇩 en prive et ❌ en public.

    Sa voix publique est RETIREE — elle s'est deja exprimee. C'est la regle de
    Preda : « ceux qui votent des deux cotes ne comptent pas dans le public ».
    Elle s'applique quel que soit l'emoji : on dedoublonne des PERSONNES, pas
    des cases a cocher.
    """
    r = fusionner_votes({D: {"alice"}}, {X: {"alice"}})
    assert r["prive"] == {D: 1}
    assert r["public"] == {X: 0}
    assert r["doublons"] == 1


def test_toute_la_ligne_publique_peut_tomber_a_zero():
    """Si le public n'est fait que d'investisseurs, sa ligne ne dit plus rien —
    et elle NE DOIT PAS s'afficher (« 🇩 0 · ❌ 0 » ferait croire a un
    desinteret, alors que c'est un dedoublonnage)."""
    r = fusionner_votes({D: {"a"}, M: {"b"}}, {D: {"a"}, X: {"b"}})
    assert r["public"] == {D: 0, X: 0}
    assert [l for l in lignes_sondage(r) if "public" in l] == []


def test_un_salon_vide_ne_casse_rien():
    """Cartes anterieures au salon public, ou webhook absent : une seule ligne.
    C'est le cas de TOUTES les cartes deja en ligne le jour de la bascule."""
    r = fusionner_votes({D: {"a"}}, {})
    assert r["public"] == {}
    assert r["doublons"] == 0
    assert len(lignes_sondage(r)) == 1

    vide = fusionner_votes({}, {})
    assert lignes_sondage(vide) == []


def test_aucun_double_comptage_dans_un_meme_salon():
    """Une personne qui coche DEUX emojis du meme salon reste deux voix : c'est
    le comportement historique, et ce n'est pas ce qu'on corrige ici. On l'ecrit
    pour que la difference soit un CHOIX visible, pas un oubli."""
    r = fusionner_votes({D: {"a"}, M: {"a"}}, {})
    assert r["prive"] == {D: 1, M: 1}


# ------------------------------------------------- compatibilite de l'etat

def test_ancien_etat_relu_comme_investisseur():
    """L'etat en production contient des sondages a l'ancien format
    (`{emoji: nombre}`). Les relire comme la nouvelle forme viderait la carte a
    la premiere reecriture — un sondage qui disparait tout seul."""
    s = normaliser_sondage({D: 4, M: 2, X: 1})
    assert s["prive"] == {D: 4, M: 2, X: 1}
    assert s["public"] == {}
    assert s["doublons"] == 0


def test_nouvel_etat_relu_tel_quel():
    s = normaliser_sondage({"prive": {D: 3}, "public": {M: 2}, "doublons": 5})
    assert s == {"prive": {D: 3}, "public": {M: 2}, "doublons": 5}


def test_etat_absurde_ne_plante_pas():
    """None, une chaine, une liste : la carte doit partir quand meme."""
    for pourri in (None, "", [], 12, "🇩"):
        s = normaliser_sondage(pourri)
        assert s == {"prive": {}, "public": {}, "doublons": 0}


# ------------------------------------------------- l'affichage

def test_les_deux_lignes_sont_distinctes_et_le_retrait_est_ecrit():
    """Deux lignes nommees (Preda veut voir QUI a vote quoi), et le nombre de
    votants retires est AFFICHE : un dedoublonnage silencieux ferait passer un
    chiffre ampute pour un chiffre brut."""
    r = fusionner_votes({D: {"a", "b"}}, {D: {"a", "c"}, X: {"d"}})
    lignes = lignes_sondage(r)
    assert len(lignes) == 2
    assert "investisseurs" in lignes[0] and "🇩 **2**" in lignes[0]
    assert "public" in lignes[1] and "🇩 **1**" in lignes[1]
    assert "1 votant(s) déjà compté(s)" in lignes[1]


def test_les_zeros_ne_sont_pas_affiches():
    """Un emoji a 0 vote encombre la ligne sans rien apprendre."""
    r = fusionner_votes({D: {"a"}, M: set(), X: set()}, {})
    assert lignes_sondage(r) == ["🗳️ **Sondage investisseurs** : 🇩 **1**"]
