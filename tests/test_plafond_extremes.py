# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_plafond_extremes.py

"""🎪 Banc du plafond de vraisemblance sur ATL/ATH (lot 49, 03/08/2026).

⭐ CE BANC SE JUGE SUR CE QU'IL LAISSE PASSER. Les quatre choses qu'il doit
INTERDIRE :
  1. laisser un prix troll (9 999 999) arriver jusqu'au site ;
  2. vider un `atl` VALIDE parce que l'`ath` de la même ligne est troll ;
  3. laisser une date orpheline derrière une valeur vidée ;
  4. désarmer le plafond **en silence**.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.catalog_export import (            # noqa: E402
    PLAFOND_EXTREMES, _assainir_extremes, _hors_plafond, _paire_corrompue)


def rec(atl="", ath="", atl_date="2024-01-01", ath_date="2024-06-01"):
    return {"atl": atl, "ath": ath, "atl_date": atl_date, "ath_date": ath_date}


# --------------------------------------------------------------------------
# 1. Le seuil lui-même
# --------------------------------------------------------------------------

def test_le_seuil_par_defaut_est_celui_choisi_par_preda():
    assert PLAFOND_EXTREMES == 15000.0


@pytest.mark.parametrize("v,attendu", [
    ("9999999", True), ("1234567", True), ("9696969", True),
    ("888888", True), ("15001", True),
    ("15000", False),            # ⭐ le seuil lui-même PASSE (strictement au-dessus)
    ("14999", False), ("798", False), ("", False), (None, False),
])
def test_hors_plafond(v, attendu):
    assert _hors_plafond(v, 15000.0) is attendu


def test_les_decimales_fr_sont_lues():
    """⭐ Le Sheet rend « 8 888,88 » : espace insécable + virgule."""
    assert _hors_plafond("9 999 999,00", 15000.0) is True
    assert _hors_plafond("1 299,99", 15000.0) is False


# --------------------------------------------------------------------------
# 2. 🔴 LE CONTRAT LE PLUS IMPORTANT : traiter CÔTÉ PAR CÔTÉ
# --------------------------------------------------------------------------

def test_un_ath_troll_ne_fait_pas_perdre_un_atl_valide():
    """🔴 1 296 lignes du catalogue sont dans ce cas exact (mesuré 03/08)."""
    r = rec(atl="798", ath="9999999")
    n_p, n_atl, n_ath, _n_o = _assainir_extremes([r])
    assert r["atl"] == "798", "l'atl valide a été jeté avec le troll"
    assert r["atl_date"] == "2024-01-01"
    assert r["ath"] == "" and r["ath_date"] == ""
    assert (n_p, n_atl, n_ath) == (0, 0, 1)


def test_un_atl_troll_ne_fait_pas_perdre_un_ath_valide():
    """⭐ ET C'EST POURQUOI LE PLAFOND PASSE EN PREMIER : un atl troll CRÉE
    une paire inversée. L'inversion d'abord aurait vidé les deux."""
    r = rec(atl="9999999", ath="120")
    n_p, n_atl, n_ath, _n_o = _assainir_extremes([r])
    assert r["ath"] == "120" and r["ath_date"] == "2024-06-01"
    assert r["atl"] == "" and r["atl_date"] == ""
    assert n_p == 0, "traité comme une paire inversée au lieu d'un troll"
    assert (n_atl, n_ath) == (1, 0)


def test_les_deux_trolls_vident_tout():
    r = rec(atl="9999999", ath="9999999")
    _, n_atl, n_ath, _n_o = _assainir_extremes([r])
    assert r == {"atl": "", "ath": "", "atl_date": "", "ath_date": ""}
    assert (n_atl, n_ath) == (1, 1)


# --------------------------------------------------------------------------
# 3. L'ancien contrat n'a pas bougé
# --------------------------------------------------------------------------

def test_la_paire_inversee_vide_toujours_les_deux():
    """⛔ Quand l'ORDRE est faux, on ne sait plus laquelle des deux ment."""
    r = rec(atl="500", ath="20")
    n_p, n_atl, n_ath, _n_o = _assainir_extremes([r])
    assert r == {"atl": "", "ath": "", "atl_date": "", "ath_date": ""}
    assert (n_p, n_atl, n_ath) == (1, 0, 0)


def test_une_paire_saine_nest_pas_touchee():
    r = rec(atl="12", ath="480")
    assert _assainir_extremes([r]) == (0, 0, 0, 0)
    assert r == rec(atl="12", ath="480")


def test_le_cas_signale_par_preda():
    """ATL 3 499 / ATH 9 999 999 — ⛔ ce n'est PAS une paire inversée."""
    r = rec(atl="3499", ath="9999999")
    assert _paire_corrompue(r) is False, "atl < ath : l'ordre est correct"
    n_p, _, n_ath, _n_o = _assainir_extremes([r])
    assert n_p == 0 and n_ath == 1
    assert r["atl"] == "3499" and r["ath"] == ""


# --------------------------------------------------------------------------
# 4. ⛔ Aucune date orpheline, jamais
# --------------------------------------------------------------------------

@pytest.mark.parametrize("r", [
    rec(atl="798", ath="9999999"), rec(atl="9999999", ath="120"),
    rec(atl="9999999", ath="9999999"), rec(atl="500", ath="20"),
])
def test_jamais_de_date_sans_sa_valeur(r):
    _assainir_extremes([r])
    for cle in ("atl", "ath"):
        if not r[cle]:
            assert r[cle + "_date"] == "", f"{cle}_date survit à {cle}"


# --------------------------------------------------------------------------
# 5. Le désarmement doit être possible — et bruyant
# --------------------------------------------------------------------------

def test_plafond_a_zero_desarme_le_controle():
    r = rec(atl="798", ath="9999999")
    n_p, n_atl, n_ath, _n_o = _assainir_extremes([r], plafond=0)
    assert (n_atl, n_ath) == (0, 0)
    assert r["ath"] == "9999999"


def test_desarme_lordre_reste_verifie():
    """⛔ Désarmer le plafond ne doit pas désarmer l'autre garde-fou."""
    r = rec(atl="500", ath="20")
    n_p, _, _, _n_o = _assainir_extremes([r], plafond=0)
    assert n_p == 1 and r["atl"] == ""


# --------------------------------------------------------------------------
# 6. Volume : l'ordre des deux passes change le résultat, on le prouve
# --------------------------------------------------------------------------

def test_lordre_des_passes_est_bien_celui_qui_preserve_le_plus():
    """⭐ 1 000 lignes « atl troll + ath valide » : la bonne passe en garde
    1 000 ath ; l'ordre inverse en aurait perdu 1 000."""
    items = [rec(atl="9999999", ath="120") for _ in range(1000)]
    n_p, n_atl, n_ath, _n_o = _assainir_extremes(items)
    assert n_p == 0 and n_atl == 1000 and n_ath == 0
    assert all(x["ath"] == "120" for x in items)


# --------------------------------------------------------------------------
# 7. 🕳️ Les dates orphelines DÉJÀ dans la source
# --------------------------------------------------------------------------

def test_une_date_sans_sa_valeur_est_videe():
    """🔴 256 lignes du Sheet sont dans ce cas (98 atl_date, 158 ath_date).
    ⭐ Le garde-fou avait été écrit pour ne pas EN CRÉER, jamais pour EN
    ENLEVER — il ne regardait que ses propres sorties."""
    r = rec(atl="", ath="480")
    n_p, n_atl, n_ath, n_o = _assainir_extremes([r])
    assert r["atl_date"] == ""
    assert r["ath"] == "480" and r["ath_date"] == "2024-06-01"
    assert (n_p, n_atl, n_ath, n_o) == (0, 0, 0, 1)


def test_une_valeur_sans_date_est_LAISSEE():
    """⚠️ ASYMÉTRIQUE, et c'est voulu : « plus-bas 12 » sans savoir quand
    reste utile ; une date sans valeur ne date rien."""
    r = rec(atl="12", ath="480", atl_date="", ath_date="")
    assert _assainir_extremes([r]) == (0, 0, 0, 0)
    assert r["atl"] == "12" and r["ath"] == "480"


def test_les_orphelines_sont_balayees_meme_hors_plafond(monkeypatch):
    """⛔ Désarmer le plafond ne désarme pas ce balayage."""
    r = rec(atl="", ath="")
    n_p, _, _, n_o = _assainir_extremes([r], plafond=0)
    assert n_o == 2 and r["atl_date"] == "" and r["ath_date"] == ""
