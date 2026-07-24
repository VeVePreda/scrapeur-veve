# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_bascule_identite.py
"""Tests de la bascule d'identite v3 (reversible, gated)."""

import csv

# Le module vit dans scraper/ (test dans tests/) : import par le PAQUET, comme
# les autres tests du repo. pytest lance depuis la racine du depot.
from scraper import bascule_identite as bi

HEADER = ["veve_uuid", "series_uuid", "name", "category", "rarity",
          "edition_type", "supply", "first_public", "listings", "note",
          "brand", "licensor", "atl", "atl_date", "ath", "ath_date"]


def _ecrire(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for r in rows:
            w.writerow([r.get(c, "") for c in HEADER])


def _lignes(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _officiel_row(uid, **kw):
    base = {c: "" for c in HEADER}
    base["veve_uuid"] = uid
    base.update(kw)
    return base


def _remplir_v3(path, n, extra=None):
    """v3 avec n lignes (garde-fou) + eventuellement des lignes precises."""
    rows = [_officiel_row(f"pad-{i:012d}", name=f"P{i}", category="comic",
                          rarity="COMMON") for i in range(n)]
    if extra:
        rows += extra
    _ecrire(path, rows)


def test_override_identite_garde_offchain(tmp_path):
    el = str(tmp_path / "elements.csv")
    v3 = str(tmp_path / "elements_v3.csv")
    # elements.csv (daily) : identite TRACKER + off-chain FRAIS
    _ecrire(el, [_officiel_row(
        "u1", name="Amazing Spider-Man #14 (2022)", category="comic",
        rarity="COMMON", edition_type="#14", supply="1000", brand="Amazing Spider-Man",
        licensor="Marvel", listings="7", atl="18", ath="99", first_public="21",
        note="NOTE")])
    # v3 (chaine) : identite CANONIQUE, off-chain vide/perime
    _remplir_v3(v3, 15000, [_officiel_row(
        "u1", name="The Amazing Spider-Man Vol. 6 #14 (2022)", category="comic",
        rarity="RARE", edition_type="14", supply="1500",
        brand="The Amazing Spider-Man Vol. 6", licensor="Marvel",
        listings="999", atl="0", ath="0", first_public="0", note="VIEUX")])
    n = bi.appliquer(el, v3, min_v3=15000)
    assert n == 1
    r = _lignes(el)[0]
    # identite -> chaine
    assert r["name"] == "The Amazing Spider-Man Vol. 6 #14 (2022)"
    assert r["rarity"] == "RARE" and r["edition_type"] == "14"
    assert r["supply"] == "1500" and r["brand"] == "The Amazing Spider-Man Vol. 6"
    # off-chain -> INTACT (daily frais)
    assert r["listings"] == "7" and r["atl"] == "18" and r["ath"] == "99"
    assert r["first_public"] == "21" and r["note"] == "NOTE"


def test_uuid_hors_chaine_garde_tracker(tmp_path):
    """Un drop tout neuf (pas encore dans v3) garde son identite tracker."""
    el = str(tmp_path / "elements.csv")
    v3 = str(tmp_path / "elements_v3.csv")
    _ecrire(el, [_officiel_row("neuf", name="Nouveau Drop", category="collectible",
                               rarity="ULTRA_RARE")])
    _remplir_v3(v3, 15000)                       # ne contient PAS 'neuf'
    bi.appliquer(el, v3, min_v3=15000)
    assert _lignes(el)[0]["name"] == "Nouveau Drop"


def test_valeur_chaine_vide_nefface_pas(tmp_path):
    el = str(tmp_path / "elements.csv")
    v3 = str(tmp_path / "elements_v3.csv")
    _ecrire(el, [_officiel_row("u1", name="Nom Tracker", category="comic",
                               rarity="RARE")])
    _remplir_v3(v3, 15000, [_officiel_row("u1", name="", category="comic",
                                          rarity="")])   # chaine vide
    bi.appliquer(el, v3, min_v3=15000)
    assert _lignes(el)[0]["name"] == "Nom Tracker"        # pas efface


def test_garde_fou_v3_trop_maigre(tmp_path):
    el = str(tmp_path / "elements.csv")
    v3 = str(tmp_path / "elements_v3.csv")
    _ecrire(el, [_officiel_row("u1", name="Nom Tracker")])
    _remplir_v3(v3, 10, [_officiel_row("u1", name="Nom Chaine")])  # 11 < 15000
    assert bi.appliquer(el, v3, min_v3=15000) == -1
    assert _lignes(el)[0]["name"] == "Nom Tracker"        # rien touche


def test_v3_absent_ne_casse_pas(tmp_path):
    el = str(tmp_path / "elements.csv")
    _ecrire(el, [_officiel_row("u1", name="Nom Tracker")])
    assert bi.appliquer(el, str(tmp_path / "absent.csv"), min_v3=15000) == -1
    assert _lignes(el)[0]["name"] == "Nom Tracker"


def test_interrupteur_off_noop(tmp_path, monkeypatch):
    monkeypatch.delenv("BASCULE_IDENTITE_CHAINE", raising=False)
    assert not bi._actif()
    monkeypatch.setenv("BASCULE_IDENTITE_CHAINE", "1")
    assert bi._actif()


def test_header_preserve(tmp_path):
    el = str(tmp_path / "elements.csv")
    v3 = str(tmp_path / "elements_v3.csv")
    _ecrire(el, [_officiel_row("u1", name="X")])
    _remplir_v3(v3, 15000, [_officiel_row("u1", name="Y", category="comic")])
    bi.appliquer(el, v3, min_v3=15000)
    with open(el, encoding="utf-8") as f:
        assert next(csv.reader(f)) == HEADER          # octet pour octet
