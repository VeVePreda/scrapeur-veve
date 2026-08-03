# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_couvertures_chaine.py

"""🖼️ Banc du report des couvertures on-chain (lot 48, 03/08/2026).

⭐ CE BANC SE JUGE SUR CE QU'IL LAISSE PASSER. Les trois choses qu'il doit
INTERDIRE, et qui feraient chacune un degat silencieux :
  1. ecraser une image existante par celle de la chaine ;
  2. lire la colonne `image` par POSITION (elle est 19e, elle ne le restera pas) ;
  3. combler un trou en silence, sans le compter.
"""

import csv
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper import couvertures_chaine as cc          # noqa: E402
from scraper.export_elements_v3 import ENTETE         # noqa: E402

URL_A = ("https://d11unjture0ske.cloudfront.net/comic_cover."
         "329e5108-cf13-4fad-96b9-dd06fb2ea78b.e1303e68-7848-460e-bbba-aa4dd2ddb71e"
         ".webpFull.webp")
URL_B = ("https://d11unjture0ske.cloudfront.net/collectible_type_image."
         "92635283-99b4-4597-ba69-01e39ccba334.d51709a5-8fb1-4616-8f74-fccbd5e63607"
         ".full.jpeg")


def _ecrire(tmp_path, lignes, entete=None):
    p = tmp_path / "elements_v3.csv"
    ent = entete or ENTETE
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(ent)
        for l in lignes:
            w.writerow([l.get(c, "") for c in ent])
    return str(p)


@pytest.fixture(autouse=True)
def _propre(monkeypatch):
    cc._reinit()
    monkeypatch.delenv("COUVERTURES_CHAINE", raising=False)
    yield
    cc._reinit()


# --------------------------------------------------------------------------
# 1. La colonne existe et sort de l'export
# --------------------------------------------------------------------------

def test_image_est_la_derniere_colonne_de_lentete():
    """⛔ EN FIN, jamais inseree : les 18 premieres ne bougent pas d'un octet."""
    assert ENTETE[-1] == "image"
    assert ENTETE[:18] == [
        "veve_uuid", "series_uuid", "name", "category", "rarity",
        "edition_type", "supply", "first_public", "listings", "note",
        "brand", "licensor", "atl", "atl_date", "ath", "ath_date",
        "series", "source"]


def test_catalogue_from_instance_rend_ladresse_telle_quelle():
    """⛔ On RECOPIE, on ne fabrique pas."""
    from scraper.export_elements_v3 import catalogue_from_instance
    inst = {"image_url": URL_A,
            "metadata": {"rarity": "Rare", "comicNumber": "1",
                         "series": "Superior Iron Man", "startYear": "2014"}}
    c = catalogue_from_instance(inst)
    assert c["image"] == URL_A
    # et l'uuid reste bien celui extrait de cette meme URL
    assert c["veve_uuid"] == "329e5108-cf13-4fad-96b9-dd06fb2ea78b"


# --------------------------------------------------------------------------
# 2. Le chargement
# --------------------------------------------------------------------------

def test_charge_par_nom_de_colonne_pas_par_position(tmp_path):
    """🔴 LE PIEGE QUI A DEJA COUTE : une colonne inseree decale tout.

    On ecrit le CSV avec `image` AILLEURS qu'en derniere position. Un lecteur
    par index rendrait la provenance ; un DictReader rend l'adresse."""
    entete = ["image"] + [c for c in ENTETE if c != "image"]
    p = _ecrire(tmp_path, [{"veve_uuid": "AAA", "image": URL_A,
                            "source": "chaine"}], entete=entete)
    m = cc.charger(p)
    assert m["aaa"] == URL_A, "lu par position au lieu du nom"


def test_fichier_absent_est_un_noop_bruyant(tmp_path, capsys):
    m = cc.charger(str(tmp_path / "rien.csv"))
    assert m == {}
    assert "absent" in capsys.readouterr().err


def test_moisson_ancienne_sans_colonne_image_est_dite(tmp_path, capsys):
    """⭐ « pas de colonne » et « colonne vide » sont deux pannes differentes."""
    entete = [c for c in ENTETE if c != "image"]
    p = _ecrire(tmp_path, [{"veve_uuid": "AAA"}], entete=entete)
    assert cc.charger(p) == {}
    assert "n'a PAS de colonne" in capsys.readouterr().err


def test_forme_inattendue_est_signalee(tmp_path, capsys):
    p = _ecrire(tmp_path, [{"veve_uuid": "AAA",
                            "image": "https://ailleurs.example/truc.png"}])
    cc.charger(p)
    assert cc.bilan()["inattendu"] == 1
    assert "hors des formes connues" in capsys.readouterr().err


def test_uuid_insensible_a_la_casse(tmp_path):
    p = _ecrire(tmp_path, [{"veve_uuid": "AbCdEf", "image": URL_B}])
    cc.charger(p)
    assert cc.image_pour("ABCDEF") == URL_B
    assert cc.image_pour("abcdef") == URL_B


# --------------------------------------------------------------------------
# 3. L'interrupteur
# --------------------------------------------------------------------------

def test_allume_par_defaut(monkeypatch):
    monkeypatch.delenv("COUVERTURES_CHAINE", raising=False)
    assert cc.actif() is True


@pytest.mark.parametrize("v", ["0", "false", "non", "OFF"])
def test_extinction(monkeypatch, v, tmp_path):
    monkeypatch.setenv("COUVERTURES_CHAINE", v)
    assert cc.actif() is False
    p = _ecrire(tmp_path, [{"veve_uuid": "AAA", "image": URL_A}])
    monkeypatch.setenv("ELEMENTS_V3", p)
    assert cc.image_pour("AAA") == "", "eteint, il doit rendre du vide"


# --------------------------------------------------------------------------
# 4. 🔴 LE CONTRAT LE PLUS IMPORTANT : ne jamais ecraser
# --------------------------------------------------------------------------

def test_normalise_ne_touche_pas_une_image_existante(tmp_path, monkeypatch):
    from scraper import sheets
    p = _ecrire(tmp_path, [{"veve_uuid": "AAA", "image": URL_A}])
    monkeypatch.setattr(cc, "CHEMIN", p)
    rec = {"veve_uuid": "AAA", "category": "comic",
           "image_url": "https://deja/la.jpg"}
    sheets._normalise(rec)
    assert rec["image_url"] == "https://deja/la.jpg"
    assert cc.bilan()["posees"] == 0
    assert cc.bilan()["deja"] == 1


def test_normalise_remplit_le_vide(tmp_path, monkeypatch):
    from scraper import sheets
    p = _ecrire(tmp_path, [{"veve_uuid": "AAA", "image": URL_A}])
    monkeypatch.setattr(cc, "CHEMIN", p)
    rec = {"veve_uuid": "AAA", "category": "comic", "image_url": ""}
    sheets._normalise(rec)
    assert rec["image_url"] == URL_A
    assert cc.bilan()["posees"] == 1


@pytest.mark.parametrize("vide", ["", None, "   "])
def test_les_trois_formes_du_vide(tmp_path, monkeypatch, vide):
    """⭐ Une cellule Sheet vide revient tantot en `None`, tantot en `""`."""
    from scraper import sheets
    p = _ecrire(tmp_path, [{"veve_uuid": "AAA", "image": URL_A}])
    monkeypatch.setattr(cc, "CHEMIN", p)
    rec = {"veve_uuid": "AAA", "category": "comic", "image_url": vide}
    sheets._normalise(rec)
    assert rec["image_url"] == URL_A


def test_piece_inconnue_de_la_chaine_est_comptee_pas_comblee(tmp_path, monkeypatch):
    """⛔ PAS DE REPLI MUET (demande Preda) : le trou reste, et il est compte."""
    from scraper import sheets
    p = _ecrire(tmp_path, [{"veve_uuid": "AAA", "image": URL_A}])
    monkeypatch.setattr(cc, "CHEMIN", p)
    rec = {"veve_uuid": "ZZZ", "category": "comic", "image_url": ""}
    sheets._normalise(rec)
    assert rec["image_url"] == ""
    assert cc.bilan()["manquantes"] == 1
    assert "SANS COUVERTURE" in cc.resume()


def test_le_resume_dit_le_reste_pas_seulement_le_succes(tmp_path, monkeypatch):
    from scraper import sheets
    p = _ecrire(tmp_path, [{"veve_uuid": "AAA", "image": URL_A}])
    monkeypatch.setattr(cc, "CHEMIN", p)
    for uid, img in (("AAA", ""), ("ZZZ", ""), ("BBB", "")):
        sheets._normalise({"veve_uuid": uid, "category": "comic",
                           "image_url": img})
    r = cc.resume()
    assert "1 fiche(s) remplie(s)" in r
    assert "2 SANS COUVERTURE" in r


# --------------------------------------------------------------------------
# 5. L'instrument de l'export
# --------------------------------------------------------------------------

def test_releve_images_compte_et_nomme(capsys):
    from scraper.export_elements_v3 import _releve_images
    i = {c: n for n, c in enumerate(ENTETE)}
    def ligne(uid, img, src="chaine", nom="Truc"):
        r = [""] * len(ENTETE)
        r[i["veve_uuid"]], r[i["image"]] = uid, img
        r[i["source"]], r[i["name"]], r[i["category"]] = src, nom, "comic"
        return r
    _releve_images([ligne("A", URL_A), ligne("B", ""), ligne("C", "", "tracker")])
    out = capsys.readouterr()
    assert "1/3" in out.out
    assert "2 SANS VISUEL" in out.err
    assert "chaine=1" in out.err and "tracker=1" in out.err
