# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_lecture_non_formatee.py

"""🔴 Banc de la lecture NON FORMATÉE du catalogue (lot 50, 03/08/2026).

LE DÉFAUT QU'IL FERME : `sync_catalogue` relisait les 19 242 lignes existantes
en valeurs **affichées**, puis les réécrivait. Un nombre faisait l'aller-retour
par sa représentation texte, et la virgule n'y survivait pas —
« 9,99 » → 999, « 2,5 » → 25.

⭐ CE BANC SE JUGE SUR CE QU'IL LAISSE PASSER. Les quatre choses interdites :
  1. relire le catalogue en valeurs formatées ;
  2. rendre une date en numéro de série (le bug qu'on échangerait contre l'autre) ;
  3. convertir en date un nombre qui n'en est pas un ;
  4. laisser le compteur de paires impossibles muet.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper import sheets                       # noqa: E402
from scraper.sheets import (                     # noqa: E402
    COLONNES_DATE, LECTURE_NON_FORMATEE, _compter_paires, _date_depuis_serie,
    _lire_lignes, _nombre)


class FauxOnglet:
    """Un onglet qui SAIT lequel des deux rendus on lui demande.

    ⭐ C'est tout l'objet du banc : vérifier l'ARGUMENT passé, pas seulement le
    résultat. Un test qui ne regarde que la sortie passerait aussi bien avec la
    lecture formatée si la fixture était propre."""

    def __init__(self, formate, non_formate):
        self.formate, self.non_formate = formate, non_formate
        self.appel = None

    def get_all_records(self, value_render_option=None, **kw):
        self.appel = value_render_option
        return ([dict(x) for x in self.non_formate] if value_render_option
                else [dict(x) for x in self.formate])


@pytest.fixture(autouse=True)
def _propre():
    sheets._PAIRES["lues"] = sheets._PAIRES["impossibles"] = 0
    yield
    sheets._PAIRES["lues"] = sheets._PAIRES["impossibles"] = 0


# --------------------------------------------------------------------------
# 1. 🔴 On demande bien le NOMBRE, pas son apparence
# --------------------------------------------------------------------------

def test_la_lecture_est_non_formatee_par_defaut():
    assert LECTURE_NON_FORMATEE is True


def test_get_all_records_recoit_bien_loption():
    ws = FauxOnglet([{"veve_uuid": "A", "atl": "9,99"}],
                    [{"veve_uuid": "A", "atl": 9.99}])
    _lire_lignes(ws)
    assert ws.appel is not None, "lu en valeurs FORMATÉES — le défaut est intact"
    assert "UNFORMATTED" in str(ws.appel).upper()


def test_le_cas_reel_mesure_le_03_08():
    """8 lignes re-demandées au tracker, 8 sur 8 : la virgule est SUPPRIMÉE."""
    ws = FauxOnglet(
        formate=[{"veve_uuid": "A", "atl": "9,99", "ath": 11},
                 {"veve_uuid": "B", "atl": "2,5", "ath": 10}],
        non_formate=[{"veve_uuid": "A", "atl": 9.99, "ath": 11},
                     {"veve_uuid": "B", "atl": 2.5, "ath": 10}])
    lignes = _lire_lignes(ws)
    assert lignes[0]["atl"] == 9.99 and lignes[1]["atl"] == 2.5
    # ⭐ et la paire redevient possible d'elle-même
    assert lignes[0]["atl"] < lignes[0]["ath"]


# --------------------------------------------------------------------------
# 2. ⛔ Le bug qu'on refuse d'échanger contre l'autre : les dates
# --------------------------------------------------------------------------

def test_un_numero_de_serie_redevient_une_date():
    assert _date_depuis_serie(45615) == "2024-11-19"
    assert _date_depuis_serie(1) == "1899-12-31"


def test_une_date_deja_en_texte_ne_bouge_pas():
    assert _date_depuis_serie("2024-11-19") == "2024-11-19"
    assert _date_depuis_serie("") == ""
    assert _date_depuis_serie(None) is None


@pytest.mark.parametrize("v", [0, 0.5, 100001, 9999999, -3, True, False])
def test_on_ne_convertit_PAS_un_nombre_qui_nest_pas_une_date(v):
    """⛔ On ne devine rien. Un tirage de 9 999 999 n'est pas une date, et
    `True` est un `int` en Python — le piège classique."""
    assert _date_depuis_serie(v) == v


def test_toutes_les_colonnes_de_date_sont_traitees():
    ws = FauxOnglet([], [{c: 45615 for c in COLONNES_DATE} | {"veve_uuid": "A"}])
    r = _lire_lignes(ws)[0]
    for c in COLONNES_DATE:
        assert r[c] == "2024-11-19", f"{c} laissée en numéro de série"


def test_les_colonnes_de_date_couvrent_les_onglets_reels():
    """⛔ Une colonne de date oubliée sortirait en 45615 sur le site."""
    for c in ("releaseDate", "atl_date", "ath_date",
              "first_seen", "last_seen", "veve_enriched_at"):
        assert c in COLONNES_DATE


def test_un_horodatage_garde_son_heure():
    v = _date_depuis_serie(45615.5)
    assert v.startswith("2024-11-19") and v.endswith("12:00:00")


# --------------------------------------------------------------------------
# 3. 🩺 Le capteur
# --------------------------------------------------------------------------

def test_le_capteur_compte_les_paires_impossibles():
    _compter_paires([
        {"atl": 999, "ath": 11},      # impossible
        {"atl": 9.99, "ath": 11},     # saine
        {"atl": 2.5, "ath": 10},      # saine
        {"atl": 475, "ath": 55},      # impossible
    ])
    assert sheets._PAIRES == {"lues": 4, "impossibles": 2}


def test_le_capteur_ignore_ce_qui_nest_pas_une_paire():
    _compter_paires([{"atl": "", "ath": 11}, {"atl": 5, "ath": ""},
                     {"atl": 0, "ath": 11}, {"atl": "x", "ath": "y"}])
    assert sheets._PAIRES == {"lues": 0, "impossibles": 0}


def test_le_capteur_voit_encore_une_cellule_abimee_en_texte():
    """⚠️ Il doit COMPTER ce qui est cassé, pas l'ignorer poliment."""
    _compter_paires([{"atl": "999", "ath": "11"}])
    assert sheets._PAIRES["impossibles"] == 1


@pytest.mark.parametrize("v,attendu", [
    ("9,99", 9.99), ("1 299,50", 1299.5), (9.99, 9.99), ("", None),
    (None, None), ("abc", None), (True, None), (False, None),
])
def test_nombre(v, attendu):
    assert _nombre(v) == attendu


# --------------------------------------------------------------------------
# 4. L'interrupteur
# --------------------------------------------------------------------------

def test_le_repli_formate_reste_atteignable(monkeypatch):
    """⭐ Un correctif sur le chemin de lecture du catalogue doit pouvoir
    s'éteindre sans redéployer — mais il est ALLUMÉ par défaut."""
    monkeypatch.setattr(sheets, "LECTURE_NON_FORMATEE", False)
    ws = FauxOnglet([{"veve_uuid": "A", "atl": "9,99"}], [])
    lignes = _lire_lignes(ws)
    assert ws.appel is None and lignes[0]["atl"] == "9,99"
