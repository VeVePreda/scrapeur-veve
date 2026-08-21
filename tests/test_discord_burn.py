# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_discord_burn.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""Banc du module Discord « burn » — UN BANC DE COMPORTEMENT.

⭐⭐ CE QU'IL SURVEILLE N'EST PAS « est-ce que ca plante ». C'est **ce qui, en
se trompant, publie quand meme** — et surtout ce qui publierait une AFFIRMATION
FAUSSE. Un burn annonce a tort n'a pas l'air d'un bug : il a l'air d'une news.

Les quatre mensonges possibles, chacun verrouille ici :
  1. « BURN EFFECTUE » alors que l'item est juste SOLD OUT ;
  2. « BURN EFFECTUE » alors que la page etait simplement illisible ;
  3. un pourcentage rapporte au tirage annonce et non aux editions en
     circulation (flatteur, et faux sur tous les crafts) ;
  4. un ping loge dans l'embed — ou il ne reveille personne, ce qui se voit
     encore moins qu'une erreur.

    python3 -m pytest tests/test_discord_burn.py -q
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper import discord_api as api            # noqa: E402
from scraper import discord_burn as B             # noqa: E402


# ═══════════════════════════════════════════════════════════ outillage du banc

# Un fragment fidele a ce que rend la page « Leaving Soon » : le badge est un
# FRERE de la carte (pas son contenu), et les liens de navigation en haut de
# page portent la meme famille SANS uuid — c'est exactement ce qui doit etre
# ecarte sans y penser.
PAGE = """
<html><head><title>VeVe Collectibles</title></head><body>
<nav>
  <a href="/collectibles/en/comics">Comics</a>
  <a href="/collectibles/en/collectibles">Collectibles</a>
</nav>
<h1>Leaving Soon</h1>
<div class="grid">
  <div class="card">
    <span class="badge">Leaving in 5 days</span>
    <a href="/collectibles/en/comics/37d973d9-8e7d-476a-8c9b-7804ef45d9da">
      <img src="https://img/x.jpg"/>
      <h3>The Amazing Spider-Man</h3>
      <p>The Amazing Spider-Man #547</p><span>1999</span>
      <span>517 left</span><span>6.99</span>
    </a>
  </div>
  <div class="card">
    <span class="badge">Leaving in 12 days</span>
    <a href="/collectibles/en/crafts/24624bd2-2ea0-4754-9b6e-1497803316ad">
      <h3>Ron English Collectors Reward</h3>
      <span>341 left</span><span>Secret Rare</span><span>Craft</span>
    </a>
  </div>
</div>
</body></html>
"""

PAGE_VIDE = """
<html><body><h1>Leaving Soon</h1>
<nav><a href="/collectibles/en/comics">Comics</a></nav>
<p>Nothing is leaving soon.</p></body></html>
"""

CLOUDFLARE = ("<html><body><h1>Just a moment...</h1>"
              "<p>Checking your browser before accessing.</p></body></html>")

SPIDEY = "37d973d9-8e7d-476a-8c9b-7804ef45d9da"
RON = "24624bd2-2ea0-4754-9b6e-1497803316ad"


def compteurs(circulation, vendues, brulees=0, disponibles=None, prix=None):
    """La forme que rend `veve_detail.fetch_dynamic` (cles du projet)."""
    return {
        "editions_in_circulation": circulation,
        "sold_editions": vendues,
        "burned_editions": brulees,
        "veve_total_available": (circulation - vendues
                                 if disponibles is None else disponibles),
        "veve_store_price": prix,
        "store_allocation": circulation,
        "withheld_editions": 0,
    }


class Journal:
    """Ce qui est PARTI, et par quelle porte. Un banc qui ne regarde que le
    code de retour ne voit pas la difference entre « publie » et « reecrit »."""

    def __init__(self):
        self.postes, self.edites = [], []
        self._n = 0

    def poster(self, wh, thread, payload):
        self._n += 1
        mid = f"msg{self._n}"
        self.postes.append((thread, mid, payload))
        return mid

    def editer(self, wh, thread, mid, payload):
        self.edites.append((thread, mid, payload))
        return mid


@pytest.fixture
def banc(tmp_path, monkeypatch):
    """Un module isole : etat dans tmp, webhook factice, aucun reseau."""
    j = Journal()
    monkeypatch.setattr(api, "poster", j.poster)
    monkeypatch.setattr(api, "editer", j.editer)
    monkeypatch.setattr(api, "souffler", lambda *a, **k: None)
    monkeypatch.setattr(B, "STATE_PATH", str(tmp_path / "burn_state.json"))
    monkeypatch.setattr(B, "SIMULATION", False)
    monkeypatch.setattr(B, "ROLE", "")
    monkeypatch.setenv("DISCORD_HUB_WEBHOOK", "https://discord/webhook/xxx")
    monkeypatch.delenv("SHEET_ID", raising=False)
    return j


def etat(banc_module=B):
    with open(banc_module.STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def desc(payload):
    return payload["embeds"][0]["description"]


# ═══════════════════════════════════════════════════ 1. LIRE LA PAGE, ET SAVOIR
#                                                        QU'ON NE SAIT PAS LIRE

def test_analyse_trouve_les_deux_items_et_pas_la_navigation():
    items = B.analyser(PAGE)
    assert [i["uuid"] for i in items] == [SPIDEY, RON]
    assert [i["famille"] for i in items] == ["comics", "crafts"]


def test_analyse_relit_le_nombre_restant_de_la_carte():
    """Le « N left » de la page sert de CONTRE-MESURE au calcul GraphQL. S'il
    n'etait pas lu, un ecart entre les deux sources passerait inapercu."""
    par_uuid = {i["uuid"]: i for i in B.analyser(PAGE)}
    assert par_uuid[SPIDEY]["restant"] == 517
    assert par_uuid[RON]["restant"] == 341


def test_la_date_de_la_carte_n_est_pas_avalee_par_le_nombre_restant():
    """🔴 RUN RÉEL DU 04/08. La carte du craft affiche sa date : le texte à plat
    donne « … 26 Jul 26 341 left ». Le « 26 » de l'année et le « 341 » se
    lisaient comme UN nombre groupé — 26 341 — et la contre-mesure criait un
    écart de 26 000 **chaque matin**.
    ⭐⭐ Un séparateur de milliers ambigu avec le séparateur de MOTS n'est pas un
    séparateur. veve.me est anglais : il groupe à la virgule.
    ⚠️ Et une fausse alarme quotidienne est pire qu'une alarme absente : elle
    apprend à ne plus lire les logs."""
    page = ('<h1>Leaving Soon</h1>'
            f'<a href="/collectibles/en/crafts/{RON}">'
            '<h3>Ron English Collectors Reward</h3>'
            '<span>26 Jul 26</span><span>341 left</span>'
            '<span>Secret Rare</span></a>')
    assert B.analyser(page)[0]["restant"] == 341


def test_les_milliers_a_la_virgule_restent_lus():
    page = (f'<h1>Leaving Soon</h1><a href="/collectibles/en/comics/{SPIDEY}">'
            '<span>9,517 left</span></a>')
    assert B.analyser(page)[0]["restant"] == 9517


def test_le_badge_va_a_la_carte_la_plus_proche_et_une_seule_fois():
    par_uuid = {i["uuid"]: i for i in B.analyser(PAGE)}
    assert par_uuid[SPIDEY]["jours"] == 5
    assert par_uuid[RON]["jours"] == 12


def test_un_lien_absolu_est_lu_comme_un_relatif():
    """VeVe a deja change le prefixe de ses chemins une fois. Le module ne doit
    pas dependre de « /collectibles/en/ »."""
    page = (f'<h1>Leaving Soon</h1><a href="https://www.veve.me/collectibles/'
            f'en/series/{RON}">x</a>')
    assert [i["uuid"] for i in B.analyser(page)] == [RON]


def test_page_cloudflare_n_est_pas_reconnue():
    """🔴 SANS CE CONTROLE, « 0 item » et « je ne sais plus lire » seraient le
    meme resultat — et le module conclurait au burn de tout le monde."""
    assert B.page_reconnue(CLOUDFLARE) is False
    assert B.page_reconnue("") is False
    assert B.page_reconnue(PAGE_VIDE) is True


def test_page_illisible_ne_publie_rien_et_ne_touche_pas_a_l_etat(banc,
                                                                monkeypatch):
    monkeypatch.setattr(B, "charger_page", lambda *a, **k: CLOUDFLARE)
    assert B.run() == 1
    assert banc.postes == [] and banc.edites == []
    assert not os.path.exists(B.STATE_PATH)


# ═══════════════════════════════════════════════════════ 2. LE CALCUL DU BURN

def test_le_denominateur_est_la_circulation_pas_le_tirage_annonce():
    """⭐⭐ Sur un craft, la plupart des editions ne sont jamais emises : 341
    sur 600 en circulation, c'est 56,8 % — pas 5,7 % d'un tirage de 6 000."""
    c = B.calcul(compteurs(circulation=600, vendues=259))
    assert c["a_bruler"] == 341
    assert c["supply_final"] == 259
    assert round(c["part"], 1) == 56.8


def test_un_a_bruler_negatif_est_impossible():
    """Les compteurs VeVe se desynchronisent parfois d'une poignee d'unites
    (sonde du 12/07). Un « -3 a bruler » serait publie tel quel."""
    assert B.calcul(compteurs(circulation=100, vendues=103))["a_bruler"] == 0


def test_une_circulation_nulle_ne_divise_pas_par_zero():
    assert B.calcul(compteurs(circulation=0, vendues=0))["part"] == 0.0


def test_les_nombres_sont_ecrits_en_francais():
    """⭐ La virgule qui saute a coute deux lots (50 et 51). Ici elle est
    verrouillee des la source : un seul formateur, teste."""
    assert B._fr(47199) == "47 199"
    assert B._pct(56.78) == "56,8"


# ═══════════════════════════════════════════════════════════ 3. LA CARTE ET LE
#                                                               PING QUI SONNE

def _d(statut="attente", **kw):
    base = dict(B.calcul(compteurs(600, 259)), statut=statut, nom="Ron English",
                genre="collectible", url="https://veve/x", fiche={}, note="",
                vu_le="04/08/2026", brulees_reelles=341, a_bruler_annonce=341,
                part_reelle=56.8, ecart=False, ts=0, estime=False, ping=False)
    base.update(kw)
    return base


def test_le_ping_est_dans_le_content_jamais_dans_l_embed(monkeypatch):
    """🔴🔴 Un `<@&id>` ecrit dans un embed s'affiche en gris et n'alerte
    personne. Tout aurait l'air normal, et plus rien ne sonnerait."""
    monkeypatch.setattr(B, "ROLE", "999")
    m = B.carte(_d(ping=True))
    assert "<@&999>" in m["content"]
    assert "<@&999>" not in desc(m)
    assert m["allowed_mentions"]["roles"] == ["999"]
    assert m["allowed_mentions"]["parse"] == []


def test_sans_role_configure_aucune_mention_n_est_autorisee(monkeypatch):
    monkeypatch.setattr(B, "ROLE", "")
    m = B.carte(_d(ping=True))
    assert m["content"] == ""
    assert m["allowed_mentions"] == {"parse": [], "roles": []}


def test_le_ping_suit_les_deux_seuils_de_preda(monkeypatch):
    """Supply final <= 100 OU part brulee >= 90 %. Un burn de 5 % ne sonne
    jamais, aussi gros soit le tirage."""
    monkeypatch.setattr(B, "ROLE", "999")
    assert B.merite_ping(B.calcul(compteurs(1000, 80))) is True     # final 80
    assert B.merite_ping(B.calcul(compteurs(1000, 50))) is True     # 95 %
    assert B.merite_ping(B.calcul(compteurs(1000, 950))) is False   # 5 %
    monkeypatch.setattr(B, "ROLE", "")
    assert B.merite_ping(B.calcul(compteurs(1000, 80))) is False


def test_la_carte_en_attente_dit_le_pourcentage_et_le_supply_final():
    d = B.carte(_d())
    assert "🔥 BURN À VENIR" in d["embeds"][0]["title"]
    assert d["embeds"][0]["color"] == B.ORANGE
    assert "56,8 %" in desc(d)
    assert "259 éditions" in desc(d)


def test_la_carte_effectuee_change_de_couleur_et_de_titre():
    d = B.carte(_d(statut="fait"))
    assert d["embeds"][0]["title"].startswith("✅ BURN EFFECTUÉ")
    assert d["embeds"][0]["color"] == B.VERT
    assert "341 éditions brûlées" in desc(d)


def test_un_ecart_entre_l_annonce_et_le_reel_est_ecrit_noir_sur_blanc():
    """⭐ Un module qui se corrige en silence apprend a mentir."""
    d = B.carte(_d(statut="fait", brulees_reelles=300, a_bruler_annonce=341,
                   ecart=True))
    assert "Annoncé : 341" in desc(d) and "réel : 300" in desc(d)


def test_une_paire_atl_superieure_a_ath_n_est_pas_publiee_du_tout():
    """🔴 RUN RÉEL DU 04/08 : « 📉 ATL 13 $ · 📈 ATH 8 $ » sur le comic.
    ⭐⭐ Quand deux nombres se contredisent, on ne sait pas LEQUEL est faux —
    en garder un, c'est choisir au hasard lequel on publie. On n'en montre
    aucun. Une carte muette reste vraie ; une carte qui place le plus-bas
    au-dessus du plus-haut perd toute sa crédibilité, et c'est une carte
    d'investisseur."""
    corps = desc(B.carte(_d(fiche={"atl": 13, "ath": 8})))
    assert "ATL" not in corps and "ATH" not in corps
    # …et une paire saine passe toujours (sinon le correctif aurait tout muté)
    saine = desc(B.carte(_d(fiche={"atl": 20, "ath": 38})))
    assert "ATL 20 $" in saine and "ATH 38 $" in saine


def test_une_borne_manquante_n_est_pas_une_incoherence():
    assert B.extremes_incoherents({"atl": None, "ath": 38}) is False
    assert B.extremes_incoherents({}) is False
    assert "ATH 38 $" in desc(B.carte(_d(fiche={"ath": 38})))


def test_la_note_de_classement_figure_sur_la_carte():
    """Demande explicite de Preda : c'est SON jugement qui distingue la carte
    d'un simple releve de compteurs."""
    d = B.carte(_d(note="A+", fiche={"rarete": "SECRET_RARE"}))
    assert "Note de classement : **A+**" in desc(d)
    assert "Secret Rare" in desc(d)


# ═══════════════════════════════════════════════════ 4. LE CYCLE DE VIE D'UNE
#                                                       CARTE (le coeur du lot)

def _lancer(monkeypatch, page, chiffres):
    monkeypatch.setattr(B, "charger_page", lambda *a, **k: page)
    monkeypatch.setattr(B, "compteurs", lambda u, f: chiffres.get(u))
    return B.run()


def test_premier_passage_une_carte_par_item(banc, monkeypatch):
    _lancer(monkeypatch, PAGE, {SPIDEY: compteurs(47199, 46682),
                                RON: compteurs(600, 259)})
    assert len(banc.postes) == 2 and banc.edites == []
    assert set(etat()["items"]) == {SPIDEY, RON}
    assert etat()["items"][RON]["mid"] == "msg2"


def test_deuxieme_passage_identique_ne_reecrit_rien(banc, monkeypatch):
    """Rediter chaque matin un message inchange consomme le quota du hub pour
    rien — et le hub a un PLAFOND partage par tous les modules."""
    chiffres = {SPIDEY: compteurs(47199, 46682), RON: compteurs(600, 259)}
    _lancer(monkeypatch, PAGE, chiffres)
    banc.postes.clear()
    _lancer(monkeypatch, PAGE, chiffres)
    assert banc.postes == [] and banc.edites == []


def test_les_ventes_qui_avancent_reecrivent_la_meme_carte(banc, monkeypatch):
    _lancer(monkeypatch, PAGE, {SPIDEY: compteurs(47199, 46682),
                                RON: compteurs(600, 259)})
    mid = etat()["items"][RON]["mid"]
    banc.postes.clear()
    _lancer(monkeypatch, PAGE, {SPIDEY: compteurs(47199, 46682),
                                RON: compteurs(600, 400)})
    assert banc.postes == []                      # aucun doublon
    assert [e[1] for e in banc.edites] == [mid]   # le MEME message
    corps = desc(banc.edites[0][2])
    assert "À brûler" in corps and "200" in corps       # 600 − 400
    assert "400 éditions" in corps                      # le supply final suit


def test_le_burn_constate_reecrit_la_carte_en_vert(banc, monkeypatch):
    """Le scenario nominal de Preda : l'item quitte la liste, `editionsBurnt`
    monte, et l'encart DEJA POSTE devient vert."""
    _lancer(monkeypatch, PAGE, {SPIDEY: compteurs(47199, 46682),
                                RON: compteurs(600, 259)})
    mid = etat()["items"][RON]["mid"]
    banc.postes.clear()

    page_sans_ron = PAGE.replace(RON, "00000000-0000-0000-0000-000000000000")
    _lancer(monkeypatch, page_sans_ron,
            {SPIDEY: compteurs(47199, 46682),
             "00000000-0000-0000-0000-000000000000": compteurs(10, 10),
             RON: compteurs(259, 259, brulees=341, disponibles=0)})

    edite = [e for e in banc.edites if e[1] == mid]
    assert len(edite) == 1
    p = edite[0][2]
    assert p["embeds"][0]["color"] == B.VERT
    assert "BURN EFFECTUÉ" in p["embeds"][0]["title"]
    assert "341 éditions brûlées" in desc(p)
    assert etat()["items"][RON]["clos"] is True


def test_la_carte_effectuee_rapporte_le_burn_a_la_circulation_D_AVANT(
        banc, monkeypatch):
    """🔴 LE PIEGE ATTRAPE AU RENDU A BLANC. Apres le feu,
    `editions_in_circulation` a DEJA fondu (600 -> 259). Rapporter les 341
    brulees a cette valeur-la donnait **−131,7 %**, et un bloc de chiffres qui
    ne s'additionne plus. La base est celle memorisee A LA PUBLICATION."""
    _lancer(monkeypatch, PAGE, {SPIDEY: compteurs(47199, 46682),
                                RON: compteurs(600, 259)})
    banc.postes.clear()
    page_sans_ron = PAGE.replace(RON, "00000000-0000-0000-0000-000000000000")
    _lancer(monkeypatch, page_sans_ron,
            {SPIDEY: compteurs(47199, 46682),
             "00000000-0000-0000-0000-000000000000": compteurs(10, 10),
             RON: compteurs(259, 259, brulees=341, disponibles=0)})
    corps = [e[2] for e in banc.edites if e[1] == "msg2"][0]["embeds"][0][
        "description"]
    assert "−56,8 %" in corps            # 341 / 600, pas 341 / 259
    assert "−131" not in corps
    assert "En circulation  600" in corps or "En circulation" in corps
    assert "600" in corps                # la base d'avant est encore visible


def test_un_sold_out_n_est_jamais_annonce_comme_un_burn(banc, monkeypatch):
    """🔴 Le mensonge n°1. L'item disparait de la liste, mais `editionsBurnt`
    n'a pas bouge : il a ete vendu jusqu'au dernier. Rien n'a brule."""
    _lancer(monkeypatch, PAGE, {SPIDEY: compteurs(47199, 46682),
                                RON: compteurs(600, 259)})
    banc.postes.clear()
    page_sans_ron = PAGE.replace(RON, "00000000-0000-0000-0000-000000000000")
    _lancer(monkeypatch, page_sans_ron,
            {SPIDEY: compteurs(47199, 46682),
             "00000000-0000-0000-0000-000000000000": compteurs(10, 10),
             RON: compteurs(600, 600, brulees=0, disponibles=0)})
    p = [e[2] for e in banc.edites if e[1] == "msg2"][0]
    assert "SOLD OUT" in p["embeds"][0]["title"]
    assert "BURN EFFECTUÉ" not in p["embeds"][0]["title"]
    assert p["embeds"][0]["color"] == B.BLEU


def test_une_disparition_sans_preuve_attend_avant_de_conclure(banc,
                                                              monkeypatch):
    """VeVe publie parfois ses compteurs en retard. Tant qu'on ne SAIT pas, on
    ne reecrit rien — surtout pas « effectue »."""
    _lancer(monkeypatch, PAGE, {SPIDEY: compteurs(47199, 46682),
                                RON: compteurs(600, 259)})
    banc.postes.clear()
    page_sans_ron = PAGE.replace(RON, "00000000-0000-0000-0000-000000000000")
    _lancer(monkeypatch, page_sans_ron,
            {SPIDEY: compteurs(47199, 46682),
             "00000000-0000-0000-0000-000000000000": compteurs(10, 10),
             RON: compteurs(600, 259)})           # rien n'a bouge du tout
    assert [e for e in banc.edites if e[1] == "msg2"] == []
    assert etat()["items"][RON].get("clos") is not True


def test_passe_le_delai_de_grace_la_carte_est_close_sans_mentir(banc,
                                                                monkeypatch):
    _lancer(monkeypatch, PAGE, {SPIDEY: compteurs(47199, 46682),
                                RON: compteurs(600, 259)})
    st = etat()
    vieux = (dt.date.today() - dt.timedelta(days=B.GRACE_JOURS + 1)).isoformat()
    st["items"][RON]["disparu_le"] = vieux
    with open(B.STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st, f)
    banc.postes.clear()

    page_sans_ron = PAGE.replace(RON, "00000000-0000-0000-0000-000000000000")
    _lancer(monkeypatch, page_sans_ron,
            {SPIDEY: compteurs(47199, 46682),
             "00000000-0000-0000-0000-000000000000": compteurs(10, 10),
             RON: compteurs(600, 259)})
    p = [e[2] for e in banc.edites if e[1] == "msg2"][0]
    assert "RETIRÉ DE LA LISTE" in p["embeds"][0]["title"]
    assert "sans burn constaté" in desc(p)


def test_une_page_vide_ne_declare_aucun_burn(banc, monkeypatch):
    """🔴 Le mensonge n°2, et le plus dangereux : la page repond, elle est bien
    la bonne, elle ne liste rien. Ce n'est PAS « tout a brule »."""
    _lancer(monkeypatch, PAGE, {SPIDEY: compteurs(47199, 46682),
                                RON: compteurs(600, 259)})
    banc.postes.clear()
    _lancer(monkeypatch, PAGE_VIDE, {SPIDEY: compteurs(47199, 46682),
                                     RON: compteurs(600, 259)})
    titres = [e[2]["embeds"][0]["title"] for e in banc.edites]
    assert not any("EFFECTUÉ" in t for t in titres)


# ═══════════════════════════════════════════════════════════ 5. LES GARDE-FOUS

def test_une_source_muette_ne_touche_pas_a_la_carte(banc, monkeypatch):
    """Un GraphQL sans reponse ne doit pas se traduire par « 0 en
    circulation » : la carte reste telle quelle, et le run sort en ERREUR pour
    que ca se voie dans Actions."""
    _lancer(monkeypatch, PAGE, {SPIDEY: compteurs(47199, 46682),
                                RON: compteurs(600, 259)})
    banc.postes.clear()
    code = _lancer(monkeypatch, PAGE, {SPIDEY: compteurs(47199, 46682)})
    assert code == 1
    assert banc.edites == [] and banc.postes == []


def test_l_echec_de_publication_ne_memorise_pas_l_empreinte(banc, monkeypatch):
    """⭐ Sinon la carte serait consideree comme « a jour » et ne repartirait
    JAMAIS — l'echec avale la donnee qu'il devait proteger."""
    monkeypatch.setattr(api, "poster", lambda *a, **k: None)
    _lancer(monkeypatch, PAGE, {SPIDEY: compteurs(47199, 46682),
                                RON: compteurs(600, 259)})
    assert "empreinte" not in etat()["items"][RON]
    assert "mid" not in etat()["items"][RON]


def test_l_anti_avalanche_memorise_sans_publier(banc, monkeypatch):
    """VeVe ne met jamais 20 items en burn le meme jour. Si ca arrive, c'est un
    bug — et on ne reveille pas le salon pour un bug."""
    monkeypatch.setattr(B, "MAX_NEUFS", 1)
    code = _lancer(monkeypatch, PAGE, {SPIDEY: compteurs(47199, 46682),
                                       RON: compteurs(600, 259)})
    assert code == 1
    assert banc.postes == []
    # ⭐ La TRACE du report reste : c'est elle qui permet de dire « on a
    #   differe » plutot que « on a perdu ».
    assert all(v.get("avale") for v in etat()["items"].values())


# ═══════════════════════════════════════════════════════════════════════════════
# 🔴🔴 CE BANC EXIGEAIT `clos: True`. IL EXIGE MAINTENANT `clos: False`.
# ═══════════════════════════════════════════════════════════════════════════════
# La ligne retiree ci-dessus etait :
#     assert all(v.get("clos") for v in etat()["items"].values())
# Elle etait FIDELE au code, et le code avait un trou.
#
# 🐛 LE TROU, MESURE LE 20/08 : la boucle principale traite
#       a_voir = presents + (suivis NON clos)
#   Un item avale sortait avec `clos: True`. Tant qu'il RESTE sur la page
#   `burning-soon`, `presents` le remet dans `a_voir` au passage suivant : le
#   garde-fou n'etait donc qu'un report d'un passage, et les 9 items avales du
#   20/08 portaient bien tous un `mid` — ils avaient fini publies.
#   ⛔ MAIS SI L'ITEM DISPARAIT DE LA PAGE AVANT LE PASSAGE SUIVANT, il n'est
#     plus dans `presents` **et** il est exclu des suivis :
#     **jamais publie, jamais rattrape, sans un mot.**
#   On est passe a cote PAR LE RYTHME (la page tient plusieurs jours, le cron
#   est quotidien), pas par la conception.
# ⭐⭐⭐ *Un garde-fou qui ferme la porte derriere lui protege une fois et perd
#   ensuite.* Le test ci-dessous est celui qui manquait.

def test_un_item_avale_revient_meme_si_la_page_ne_le_montre_plus(
        banc, monkeypatch):
    """🔑 LE VRAI CONTROLE DU GARDE-FOU : le report doit survivre a la page.

    Passage 1 : le plafond mord, rien n'est publie.
    Passage 2 : la page ne montre PLUS l'item (VeVe l'a retire).
    ⇒ Il doit quand meme etre traite. Avec `clos: True`, il disparaissait.
    """
    monkeypatch.setattr(B, "MAX_NEUFS", 1)
    code = _lancer(monkeypatch, PAGE, {SPIDEY: compteurs(47199, 46682),
                                       RON: compteurs(600, 259)})
    assert code == 1 and banc.postes == []
    suivis = etat()["items"]
    assert set(suivis) == {SPIDEY, RON}

    # ⭐⭐ C'EST ICI QUE TOUT SE JOUE — on reconstruit `a_voir` exactement
    #   comme la boucle principale le fait (`discord_burn.py`, « Les items a
    #   traiter »). Un item `clos` en est exclu des qu'il quitte la page.
    page_vide = {}
    a_voir = list(page_vide) + [u for u, s in suivis.items()
                                if not s.get("clos") and u not in page_vide]
    assert set(a_voir) == {SPIDEY, RON}, (
        "un item avale par le plafond est SORTI de la surveillance des que "
        "VeVe l'a retire de sa page : jamais publie, jamais rattrape, et "
        "sans un mot. C'est ce que `clos: True` provoquait.")


def test_l_horizon_des_burns_calcules_est_de_48h():
    """🔥 « ne plus annoncer a la decouverte, mais 48 h avant » (Preda, 21/08).

    ⭐ Ce controle porte sur le REGLAGE, pas sur le calcul : `burn_date_prevue`
    est toujours lue des la sortie du comic (lot 67). Seul le moment de
    PUBLIER recule. Un retour a 30 rendrait la demande sans effet, en silence.
    """
    assert B.HORIZON_JOURS == 2, (
        f"HORIZON_JOURS vaut {B.HORIZON_JOURS} : les burns calcules seraient "
        f"annonces {B.HORIZON_JOURS} jours a l'avance, alors que Preda a "
        f"demande 48 h. (Se regle par la variable DISCORD_BURN_HORIZON.)")


def test_la_carte_part_meme_sans_sheet(banc, monkeypatch):
    """Sheet illisible = carte plus pauvre (pas de nom joli, pas de note), pas
    carte absente. Les chiffres sont l'essentiel et ils viennent de VeVe."""
    _lancer(monkeypatch, PAGE, {SPIDEY: compteurs(47199, 46682),
                                RON: compteurs(600, 259)})
    assert len(banc.postes) == 2
    assert "341" in desc(banc.postes[1][2])


def test_l_id_du_post_est_bien_celui_du_salon_burn(banc, monkeypatch):
    """Un thread_id errone poste dans le mauvais fil sans lever d'erreur."""
    _lancer(monkeypatch, PAGE, {SPIDEY: compteurs(47199, 46682),
                                RON: compteurs(600, 259)})
    assert {p[0] for p in banc.postes} == {B.THREAD}
    assert B.THREAD == "1534125779879985212"


def test_le_module_est_dans_le_registre_du_hub():
    """⭐ Un module ecrit, teste, depose — et jamais appele. Deja vu ici avec
    `calendrier`, absent du repli du cron pendant des semaines."""
    from scraper import discord_hub
    assert discord_hub.MODULES.get("burn") is B.run
