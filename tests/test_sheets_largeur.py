# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_sheets_largeur.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""L'onglet trop ETROIT — le defaut qui ne se voit que le jour d'un ajout.

🔴🔴 CE QUE CE BANC EMPECHE, EN UNE PHRASE : qu'une colonne ajoutee au
catalogue fasse tomber le SYNC ENTIER la nuit suivante, sans que rien ne l'ait
annonce.

L'histoire, le 05/08/2026 : le lot 67 ajoute `burn_date_prevue` et fait passer
🟢C-COMICS de **39 a 40** colonnes. Or l'onglet vit sur le Sheet avec 39
colonnes (derniere lettre **AM**, relue par Preda). `sync_catalogue` ecrit la
grille entiere en un `values.update` ancre en A1 : Google rend
« Range … exceeds grid limits » et **tout** le sync tombe.

⭐⭐⭐ **UN PARAMETRE QUI NE S'APPLIQUE QU'A LA CREATION EST UN PARAMETRE QUI NE
S'APPLIQUE PRESQUE JAMAIS.** `_open_worksheet(..., cols=N)` posait N a la
creation de l'onglet, et jamais ensuite — donc jamais, en pratique.

⭐⭐ Et c'est un banc de COMPORTEMENT : il ne verifie pas qu'`add_cols` existe,
il verifie **combien de colonnes l'onglet a apres l'appel**. Un banc qui
verifierait l'appel laisserait passer un `resize` qui retrecit.

    python3 -m pytest tests/test_sheets_largeur.py -q
"""

import pytest

from scraper import sheets as S


class FauxOnglet:
    """Le strict minimum de l'interface gspread qu'on emploie."""

    def __init__(self, titre="🟢C-COMICS", cols=39, rows=20000):
        self.title = titre
        self.col_count = cols
        self.row_count = rows
        self.appels = []

    def add_cols(self, n):
        self.appels.append(("add_cols", n))
        self.col_count += n

    def resize(self, rows=None, cols=None):          # piege : ne doit PAS servir
        self.appels.append(("resize", rows, cols))
        if cols is not None:
            self.col_count = cols
        if rows is not None:
            self.row_count = rows


# ---------------------------------------------------------------------------
# LE CAS REEL DU 05/08 — 39 colonnes, 40 demandees
# ---------------------------------------------------------------------------
def test_le_cas_du_0508_onglet_a_39_le_lot_en_exige_40():
    ws = FauxOnglet(cols=39)
    ajoute = S.elargir_si_besoin(ws, 40)
    assert ajoute == 1
    assert ws.col_count == 40, (
        "l'onglet n'a pas ete elargi : le sync catalogue tomberait cette nuit")


def test_la_largeur_reellement_exigee_par_le_catalogue():
    """⭐ On ne code pas « 40 » en dur : on demande au module ce qu'il ECRIT.
    Le jour ou une colonne s'ajoute, ce test suit tout seul — et l'onglet
    simule a 39 colonnes rappelle qu'il faudra l'elargir."""
    besoin = len(S.COMICS_COLD) + len(S.BOOKKEEPING)
    ws = FauxOnglet(cols=39)
    S.elargir_si_besoin(ws, besoin)
    assert ws.col_count >= besoin
    assert "burn_date_prevue" in S.COMICS_COLD


# ---------------------------------------------------------------------------
# 🔴 CE QU'IL NE DOIT JAMAIS FAIRE
# ---------------------------------------------------------------------------
def test_ne_retrecit_JAMAIS():
    """⛔ Retrecir DETRUIT des donnees. Une colonne de trop ne gene personne ;
    une colonne en moins est irrattrapable."""
    ws = FauxOnglet(cols=60)
    assert S.elargir_si_besoin(ws, 40) == 0
    assert ws.col_count == 60
    assert ws.appels == [], "aucune requete ne doit partir quand c'est assez large"


def test_gratuit_quand_la_largeur_suffit_deja():
    """⭐ Le cas NORMAL est le cas de tous les jours : il ne doit rien coûter.
    Un garde-fou qui consomme du quota a chaque run finit par etre retire."""
    ws = FauxOnglet(cols=40)
    assert S.elargir_si_besoin(ws, 40) == 0
    assert ws.appels == []


def test_largeur_inconnue_ne_touche_a_rien():
    """Un objet qui ne sait pas dire sa largeur ne doit pas faire planter le
    sync. ⭐ Ne pas savoir se declare ; c'est le supposer qui coute."""
    class Muet:
        title = "x"
        col_count = None
    assert S.elargir_si_besoin(Muet(), 40) == 0


# ---------------------------------------------------------------------------
# LE BRANCHEMENT — le garde-fou doit etre SUR LE CHEMIN, pas a cote
# ---------------------------------------------------------------------------
def test_open_worksheet_elargit_un_onglet_existant(monkeypatch):
    """🔴 LE VERROU. `elargir_si_besoin` pourrait etre parfait et n'etre
    appele nulle part — c'est exactement ce qui s'est passe pendant des mois
    avec le parametre `cols`. ⭐⭐ *Une constante definie n'est pas une branche
    branchee.*"""
    ws = FauxOnglet(cols=39)

    class FauxClasseur:
        def worksheet(self, tab):
            return ws

        def add_worksheet(self, **kw):                    # ne doit pas servir
            raise AssertionError("l'onglet existe : on ne doit pas le creer")

    rendu = S._open_worksheet(FauxClasseur(), "🟢C-COMICS", cols=40)
    assert rendu is ws
    assert ws.col_count == 40


def test_open_worksheet_cree_a_la_bonne_largeur():
    """Le cas de creation continue de marcher — c'est le seul qui marchait."""
    vus = {}

    class FauxClasseur:
        def worksheet(self, tab):
            import gspread
            raise gspread.WorksheetNotFound(tab)

        def add_worksheet(self, title, rows, cols):
            vus.update(title=title, rows=rows, cols=cols)
            return FauxOnglet(titre=title, cols=cols)

    ws = S._open_worksheet(FauxClasseur(), "🆕", cols=40)
    assert vus["cols"] == 40 and ws.col_count == 40
