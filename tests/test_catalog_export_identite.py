# ⚠️ DEPOT : VeVePreda/scrapeur-veve
# CHEMIN : tests/test_catalog_export_identite.py

"""Pipeline 2 : le catalogue adopte l'identite de la chaine (etape 4.3).

Ce que ces tests protegent, et pourquoi c'est ce fichier-la qui compte : un
catalogue faux ne leve AUCUNE exception en aval. Il alimente 15 sites, le
grand livre, l'historique de prix et les figures — tous joignent par uuid et
prennent les libelles pour argent comptant. Le seul endroit ou l'erreur est
encore visible, c'est ici.

Les trois defenses, dans l'ordre ou elles s'exercent :
  1. `lire_chaine` n'accepte QUE ce que la chaine a vu (colonne `source`) ;
  2. `verifier_churn` refuse un remaniement de masse non prevu ;
  3. `valider` refuse une ligne hors vocabulaire, un doublon, un nom sale.
"""
import csv

import pytest

from scraper import identite as ID
from scraper.catalog_export import (
    HEADER, MINI_PAR_TYPE, PLAFONDS_CHURN, appliquer_identite, lire_chaine,
)

V3_COLS = ["veve_uuid", "name", "category", "rarity", "edition_type", "supply",
           "brand", "licensor", "series", "source"]


def v3_csv(tmp_path, lignes, avec_source=True):
    cols = V3_COLS if avec_source else [c for c in V3_COLS if c != "source"]
    p = tmp_path / "elements_v3.csv"
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(lignes)
    return str(p)


def chaine(uid, **kw):
    d = dict(veve_uuid=uid, name="Storm Vol. 5 #2 (2024)", category="comic",
             rarity="COMMON", edition_type="2", supply="1000",
             brand="Storm Vol. 5", licensor="Marvel", series="Storm Vol. 5",
             source="chaine")
    d.update(kw)
    return d


def sheet(uid, **kw):
    d = {"uuid": uid, "kind": "Comic", "name": "Storm #2 (2024)",
         "edition_type": "#2", "rarity": "COMMON", "release_date": "2024-01-02",
         "series": "Storm #2 (2024)", "brand": "Storm", "licensor": "Marvel",
         "tirage": "1000", "store_price": "60", "floor": "", "listings": "",
         "ath": "", "atl": ""}
    d.update(kw)
    return d


# --- 1. seule la CHAINE entre ---------------------------------------------

def test_une_ligne_recopiee_du_tracker_est_ECARTEE(tmp_path):
    # ⭐⭐ La raison d'etre de la colonne `source`. 136 objets d'elements_v3
    # viennent du tracker (jamais mintes on-chain) : les laisser passer
    # laisserait le TRACKER ecraser le Sheet en se faisant passer pour la
    # chaine — l'inverse exact de la doctrine.
    p = v3_csv(tmp_path, [chaine("u1"), chaine("u2", source="tracker"),
                          chaine("u3", source="")])
    assert set(lire_chaine(p)) == {"u1"}


def test_un_fichier_SANS_colonne_source_est_refuse_en_bloc(tmp_path, capsys):
    # Un elements_v3 anterieur au 28/07 ne dit rien de sa provenance. On ne
    # devine pas : mieux vaut un catalogue 100 % Sheet qu'un catalogue faux.
    assert lire_chaine(v3_csv(tmp_path, [chaine("u1")], avec_source=False)) == {}
    assert "source" in capsys.readouterr().err


def test_un_fichier_absent_ne_casse_pas_lexport(tmp_path, capsys):
    assert lire_chaine(str(tmp_path / "nulle_part.csv")) == {}
    assert str(tmp_path) in capsys.readouterr().err     # il DIT ou il a cherche


# --- 2. la fusion ----------------------------------------------------------

def test_la_chaine_gagne_sur_le_nom_et_la_serie():
    items = [sheet("u1")]
    appliquer_identite(items, {"u1": chaine("u1")}, plafonds={}, mini_par_type={})
    assert items[0]["name"] == "Storm Vol. 5 #2 (2024)"
    assert items[0][ID.COL_SERIE] == "Storm Vol. 5"      # plus le nom complet


def test_le_suffixe_editorial_du_Sheet_survit_dans_name_display():
    # 450 comics portent un libelle que ni la chaine ni le tracker ne connait.
    items = [sheet("u1", name="Storm #2 (2024) - Vintage Variant")]
    appliquer_identite(items, {"u1": chaine("u1")}, plafonds={}, mini_par_type={})
    assert items[0]["name"] == "Storm Vol. 5 #2 (2024)"
    assert "Vintage Variant" in items[0]["name_display"]


def test_un_item_inconnu_de_la_chaine_garde_le_Sheet():
    items = [sheet("u9")]
    appliquer_identite(items, {}, plafonds={}, mini_par_type={})
    assert items[0]["name"] == "Storm #2 (2024)"


def test_une_valeur_chaine_VIDE_nefface_jamais_le_Sheet():
    # ⭐ Le cas des 76 `#` orphelins : pour un COMIC, `edition_type` vaut le
    # numero du comic. Quand la chaine ne l'a pas, son vide est un TROU DE
    # MOISSON, pas une information — on garde ce que le Sheet sait.
    items = [sheet("u1", edition_type="131")]
    appliquer_identite(items, {"u1": chaine("u1", edition_type="")},
                       plafonds={}, mini_par_type={})
    assert items[0]["edition_type"] == "131"            # conserve, pas efface


def test_le_referentiel_ne_retire_PAS_le_diese_du_Sheet():
    """Mesure, pas supposition : le Sheet ecrit '#131', la chaine '131'.

    `normaliser_edition_type` ne touche pas au '#'. Ce n'est PAS un defaut en
    pratique — sur le vrai catalogue, 0 ligne garde un '#' apres fusion, parce
    que la chaine porte le numero partout ou le Sheet le porte. On l'epingle
    pour que ca reste vrai : si un jour ce test tombe, c'est que la chaine a
    cesse de fournir des numeros, pas que la normalisation a change.
    """
    items = [sheet("u1", edition_type="#131")]
    appliquer_identite(items, {"u1": chaine("u1", edition_type="")},
                       plafonds={}, mini_par_type={})
    assert items[0]["edition_type"] == "#131"


def test_release_date_et_store_price_ne_sont_jamais_touches():
    # La chaine ne les porte pas et ne les portera jamais : les onglets froids
    # du Sheet restent obligatoires. On superpose, on ne remplace pas.
    items = [sheet("u1")]
    appliquer_identite(items, {"u1": chaine("u1")}, plafonds={}, mini_par_type={})
    assert items[0]["release_date"] == "2024-01-02"
    assert items[0]["store_price"] == "60"


# --- 3. les garde-fous -----------------------------------------------------

def _catalogue(n=16_000, m=2_500):
    """Un catalogue REALISTE : seules la serie (et le nom) divergent, comme en
    vrai. Un jeu d'essai ou tout diverge ne teste plus les plafonds, il teste
    le plafond le plus bas."""
    items, ch = [], {}
    for i in range(n):                                   # comics
        u = f"c{i}"
        items.append(sheet(u, series=f"Storm #{i} (2024)",
                           name=f"Storm #{i} (2024)", edition_type=str(i),
                           brand="Storm Vol. 5"))
        # Mesure du 28/07 : le nom change sur 44,7 % du catalogue, pas 100 %.
        # Un jeu d'essai ou TOUT change ne teste plus que le plafond le plus bas.
        nom = f"Storm Vol. 5 #{i} (2024)" if i % 2 else f"Storm #{i} (2024)"
        ch[u] = chaine(u, name=nom, edition_type=str(i))
    for i in range(m):                                   # collectibles
        u = f"k{i}"
        items.append(sheet(u, kind="Collectible", name=f"Figurine {i}",
                           series="Cover Girls S1", brand="Marvel",
                           edition_type="FA"))
        ch[u] = chaine(u, category="collectible", name=f"Figurine {i}",
                       series="Cover Girls S1", brand="Marvel",
                       edition_type="FA")
    return items, ch


def test_le_churn_ATTENDU_de_la_serie_passe_sans_soupape():
    # 85,7 % des series changent, par construction : `veve_series_name` du
    # Sheet est le nom complet de la couverture, pas une serie. Ce
    # remaniement-la est DECIDE, son plafond l'anticipe — et il passe SANS
    # qu'on ait besoin d'ouvrir la soupape.
    items, ch = _catalogue()
    appliquer_identite(items, ch)
    assert all(i[ID.COL_SERIE] in ("Storm Vol. 5", "Cover Girls S1")
               for i in items)


def test_un_remaniement_de_masse_NON_PREVU_est_refuse():
    # LA lecon du 28/07 : une source degradee produit des lignes parfaitement
    # valides. Ici la « chaine » renvoie partout la meme marque — vocabulaire
    # bon, volumetrie bonne, aucun doublon, et pourtant inexploitable.
    items, ch = _catalogue()
    for r in ch.values():
        r["brand"] = "TOUT PAREIL"
    with pytest.raises(ID.IdentiteInvalide, match="remaniement de masse"):
        appliquer_identite(items, ch)


def test_le_meme_remaniement_passe_sil_est_AUTORISE_explicitement():
    items, ch = _catalogue()
    for r in ch.values():
        r["brand"] = "TOUT PAREIL"
    appliquer_identite(items, ch, autorise=True)         # decision ecrite


def test_une_famille_entiere_qui_disparait_est_vue():
    # Le seuil GLOBAL ne broncherait pas : c'est le comptage PAR FAMILLE qui
    # voit qu'il ne reste plus qu'une poignee de collectibles.
    items, ch = _catalogue(m=5)
    with pytest.raises(ID.IdentiteInvalide, match="famille"):
        appliquer_identite(items, ch, plafonds={})


def test_un_kind_hors_vocabulaire_est_refuse():
    items, ch = _catalogue()
    ch["c0"]["category"] = "bande dessinee"
    with pytest.raises(ID.IdentiteInvalide):
        appliquer_identite(items, ch)


# --- 4. le contrat de sortie ----------------------------------------------

def test_name_display_nest_PAS_dans_len_tete_par_defaut():
    # Interrupteur eteint = fichier octet pour octet identique a la veille.
    # C'est ce qui rend le depot de ce lot sans effet tant que Preda n'allume
    # pas la variable.
    assert "name_display" not in HEADER


def test_les_plafonds_couvrent_toutes_les_colonnes_dendite():
    # Une colonne d'identite sans plafond, c'est une colonne qui peut etre
    # massacree en silence.
    for col in ID.COLS_CHAINE:
        assert col in PLAFONDS_CHURN, col
    assert ID.COL_SERIE in PLAFONDS_CHURN


def test_les_seuils_par_famille_visent_les_deux_familles():
    assert set(MINI_PAR_TYPE) == set(ID.VOCAB_KIND)
