# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_discord_calendrier.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""Tests du module Discord « calendrier ».

Ce qui est teste ici, c'est ce qui, en se trompant, **publie quand meme** :
le garde du samedi, l'anti-doublon de semaine, l'etanchete entre les deux
marques, et le fait qu'un ping ne parte jamais par accident. Un bug de rendu se
voit ; un doublon hebdomadaire, on ne le voit qu'apres l'avoir envoye.

    python3 -m pytest tests/test_discord_calendrier.py -q
"""

from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper import discord_calendrier as C          # noqa: E402


# ----------------------------------------------------------- le garde du jour

def test_le_module_ne_parle_que_le_samedi():
    # 2026-08-01 est un samedi ; le 31/07 un vendredi, le 02/08 un dimanche.
    assert C.est_le_jour(dt.date(2026, 8, 1))
    assert not C.est_le_jour(dt.date(2026, 7, 31))
    assert not C.est_le_jour(dt.date(2026, 8, 2))


def test_la_cle_de_semaine_est_la_semaine_iso():
    assert C.cle_semaine(dt.date(2026, 8, 1)) == C.cle_semaine(dt.date(2026, 7, 27))
    assert C.cle_semaine(dt.date(2026, 8, 1)) != C.cle_semaine(dt.date(2026, 8, 3))


def test_la_cle_survit_au_changement_dannee():
    """Le 1er janvier peut appartenir a la semaine 53 de l'annee precedente."""
    cle = C.cle_semaine(dt.date(2027, 1, 1))
    assert cle.startswith("2026-W") or cle.startswith("2027-W")


# ----------------------------------------------------- l'etanchete des marques

def test_chaque_marque_lit_son_propre_webhook(monkeypatch):
    monkeypatch.setenv("DISCORD_CALENDRIER_WEBHOOK_VEVEFRANCE", "https://vf")
    monkeypatch.setenv("DISCORD_CALENDRIER_WEBHOOK_VEVEINSIGHTS", "https://vi")
    assert C.webhook_de("vevefrance") == "https://vf"
    assert C.webhook_de("veveinsights") == "https://vi"


def test_un_webhook_absent_rend_une_chaine_vide(monkeypatch):
    """Vide = SIMULATION. Surtout pas un repli sur le webhook du hub : le
    calendrier de VeVe France partirait dans le forum de Preda."""
    monkeypatch.delenv("DISCORD_CALENDRIER_WEBHOOK_VEVEFRANCE", raising=False)
    monkeypatch.setenv("DISCORD_HUB_WEBHOOK", "https://hub")
    assert C.webhook_de("vevefrance") == ""


# ------------------------------------------------------------------ le message

class _Theme:
    cle = "vevefrance"
    accent = "#ef4135"
    site = "vevefrance.fr"
    discord = "discord.gg/vevefrance"


def _msg(role=""):
    return C.message(_Theme(), dt.date(2026, 6, 29), dt.date(2026, 8, 2), 138,
                     "calendrier.png", role)


def test_sans_role_le_message_ne_ping_rien():
    payload = _msg()
    assert payload["allowed_mentions"] == {"parse": [], "roles": []}
    assert "<@&" not in payload["content"]


def test_avec_un_role_seul_ce_role_est_autorise():
    payload = _msg("123456")
    assert payload["allowed_mentions"] == {"parse": [], "roles": ["123456"]}
    assert "<@&123456>" in payload["content"]


def test_limage_pointe_vers_la_piece_jointe_pas_vers_une_url():
    """Une URL de pièce jointe Discord expire ; `attachment://` ne périme pas."""
    assert _msg()["embeds"][0]["image"]["url"] == "attachment://calendrier.png"


def test_la_couleur_de_lembed_vient_du_theme():
    assert _msg()["embeds"][0]["color"] == 0xEF4135


def test_le_pied_de_lembed_porte_le_site_et_le_discord():
    pied = _msg()["embeds"][0]["footer"]["text"]
    assert "vevefrance.fr" in pied and "discord.gg/vevefrance" in pied


# ------------------------------------------------- la langue suit le theme

def test_veveinsights_ecrit_en_anglais():
    from outils.calendrier import themes as T
    payload = C.message(T.theme("veveinsights"), dt.date(2026, 6, 29),
                        dt.date(2026, 8, 2), 138, "c.png", "")
    assert "drop calendar" in payload["content"].lower()
    assert "AUG" in payload["content"]           # mois en anglais, pas « AOÛT »


def test_vevefrance_ecrit_en_francais():
    from outils.calendrier import themes as T
    payload = C.message(T.theme("vevefrance"), dt.date(2026, 6, 29),
                        dt.date(2026, 8, 2), 138, "c.png", "")
    assert "calendrier des drops" in payload["content"].lower()
    assert "AOÛT" in payload["content"]


# -------------------------------------------- publier une fois, et une seule

def _grille():
    return {"calendrier": {}, "debut": dt.date(2026, 6, 29),
            "fin": dt.date(2026, 8, 2), "total": 138}


def _bouchonner(monkeypatch, tmp_path, envois):
    """Rendu et reseau remplaces : on teste la DECISION, pas le dessin."""
    faux_png = tmp_path / "calendrier.png"
    faux_png.write_bytes(b"png")
    monkeypatch.setattr(C, "fabriquer", lambda *a, **k: str(faux_png))
    monkeypatch.setattr(C.api, "poster_fichier",
                        lambda *a, **k: (envois.append(a[0]), "MSG1")[1])
    monkeypatch.setattr(C.api, "souffler", lambda *a, **k: None)
    monkeypatch.setenv("DISCORD_CALENDRIER_WEBHOOK_VEVEFRANCE", "https://vf")


def test_publie_puis_se_tait_la_meme_semaine(monkeypatch, tmp_path):
    envois, state = [], {}
    _bouchonner(monkeypatch, tmp_path, envois)
    samedi = dt.date(2026, 8, 1)
    assert C._publier_une_marque("vevefrance", _grille(), str(tmp_path),
                                 samedi, state, None) == 0
    assert len(envois) == 1
    assert state["vevefrance"]["semaine"] == "2026-W31"
    # meme samedi, 2e passage du hub : rien ne repart
    assert C._publier_une_marque("vevefrance", _grille(), str(tmp_path),
                                 samedi, state, None) == 0
    assert len(envois) == 1


def test_la_semaine_suivante_repart(monkeypatch, tmp_path):
    envois, state = [], {}
    _bouchonner(monkeypatch, tmp_path, envois)
    C._publier_une_marque("vevefrance", _grille(), str(tmp_path),
                          dt.date(2026, 8, 1), state, None)
    C._publier_une_marque("vevefrance", _grille(), str(tmp_path),
                          dt.date(2026, 8, 8), state, None)
    assert len(envois) == 2


def test_un_changement_de_salon_oublie_la_semaine(monkeypatch, tmp_path):
    """Si le webhook change, la memoire de CETTE marque devient caduque —
    sinon le nouveau salon resterait muet jusqu'à la semaine suivante."""
    envois, state = [], {}
    _bouchonner(monkeypatch, tmp_path, envois)
    samedi = dt.date(2026, 8, 1)
    C._publier_une_marque("vevefrance", _grille(), str(tmp_path), samedi,
                          state, None)
    monkeypatch.setenv("DISCORD_CALENDRIER_WEBHOOK_VEVEFRANCE", "https://autre")
    C._publier_une_marque("vevefrance", _grille(), str(tmp_path), samedi,
                          state, None)
    assert len(envois) == 2


def test_un_echec_de_publication_nécrit_pas_letat(monkeypatch, tmp_path):
    """Sans ca, une panne reseau ferait sauter la semaine en silence."""
    envois, state = [], {}
    _bouchonner(monkeypatch, tmp_path, envois)
    monkeypatch.setattr(C.api, "poster_fichier", lambda *a, **k: None)
    code = C._publier_une_marque("vevefrance", _grille(), str(tmp_path),
                                 dt.date(2026, 8, 1), state, None)
    assert code == 1
    assert "vevefrance" not in state


def test_une_marque_inconnue_ne_fait_pas_tomber_le_run(monkeypatch, tmp_path):
    state = {}
    assert C._publier_une_marque("vevemystere", _grille(), str(tmp_path),
                                 dt.date(2026, 8, 1), state, None) == 1
    assert state == {}
