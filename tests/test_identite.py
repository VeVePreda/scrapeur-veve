# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_identite.py

"""Preuve du referentiel d'identite.

Chaque test porte le defaut REEL qu'il empeche, mesure le 28/07/2026 sur les
fichiers de production. Un test sans defaut derriere lui ne sert a rien.
"""
import pytest

from scraper.identite import (
    IdentiteInvalide, KIND_COLLECTIBLE, KIND_COMIC, VOCAB_KIND, VOCAB_RARITY,
    fusionner, libelle_affichage, nettoyer, normaliser_edition_type,
    normaliser_kind, normaliser_rarity, rapport, suffixe_editorial, valider,
    verifier_churn,
)


def ligne(uuid, **kw):
    base = {"uuid": uuid, "kind": KIND_COMIC, "name": "Storm Vol. 5 #2",
            "rarity": "COMMON", "series": "Storm", "edition_type": "1",
            "tirage": "1000", "brand": "Storm", "licensor": "Marvel"}
    base.update(kw)
    return base


# --- nettoyage -------------------------------------------------------------

def test_nettoyer_ecrase_les_doubles_espaces():
    # elements.csv porte 2 835 doubles espaces ; catalogue.csv.gz en a 49.
    assert nettoyer("Immortal X-Men #16  (2022)") == "Immortal X-Men #16 (2022)"
    assert nettoyer("  bord  ") == "bord"
    assert nettoyer(None) == ""


# --- vocabulaire -----------------------------------------------------------

@pytest.mark.parametrize("brut", ["comic", "Comic", "COMIC", " comics "])
def test_kind_toutes_graphies_vers_Comic(brut):
    # Le defaut par repli : construire_figures fait `!= 'Comic'`.
    assert normaliser_kind(brut) == KIND_COMIC


@pytest.mark.parametrize("brut", ["collectible", "Collectible", "COLLECTABLE"])
def test_kind_toutes_graphies_vers_Collectible(brut):
    assert normaliser_kind(brut) == KIND_COLLECTIBLE


def test_kind_inconnu_rend_vide_et_sera_refuse():
    assert normaliser_kind("figurine") == ""
    assert normaliser_kind("") == ""


@pytest.mark.parametrize("brut,attendu", [
    ("Ultra Rare", "ULTRA_RARE"),
    ("SECRET RARE", "SECRET_RARE"),   # valeur hors norme REELLE (1 occurrence)
    ("ultra-rare", "ULTRA_RARE"),
    ("COMMON", "COMMON"),
    ("", ""),
])
def test_rarity_normalisee(brut, attendu):
    assert normaliser_rarity(brut) == attendu


def test_edition_type_zero_vaut_rien():
    # Le tracker met un 0 numerique la ou il n'y a pas de type.
    assert normaliser_edition_type("0") == ""
    assert normaliser_edition_type("0.0") == ""
    assert normaliser_edition_type("fa") == "FA"
    assert normaliser_edition_type("12") == "12"


# --- name_display : les 450 comics a variante ------------------------------

def test_variante_du_Sheet_conservee():
    # Seul le Sheet distingue les couvertures. 450 comics concernes.
    assert libelle_affichage("Daredevil Vol. 1 #131",
                             "Daredevil #131 - Vintage Variant") \
        == "Daredevil Vol. 1 #131 - Vintage Variant"


def test_suffixe_qui_est_un_titre_nest_pas_une_variante():
    # 'Namor #1 (2020)' apres un tiret est l'oeuvre, pas une variante.
    assert suffixe_editorial("Marvel - Namor #1 (2020)", "Namor Vol. 1 #1") == ""
    assert suffixe_editorial("X - Hellfire Gala #1 (2022)", "Hellfire Gala") == ""


def test_suffixe_deja_dit_par_le_canonique_nest_pas_repete():
    assert suffixe_editorial("Storm #2 - Storm", "Storm Vol. 5 #2") == ""


def test_sans_variante_laffichage_est_le_canonique():
    assert libelle_affichage("Storm Vol. 5 #2", "Storm #2 (2024)") \
        == "Storm Vol. 5 #2"


# --- fusion ----------------------------------------------------------------

def test_la_chaine_gagne_sur_lidentite():
    sheet = {"name": "Storm #2 (2024)", "series": "Storm #2 (2024)",
             "kind": "Comic", "rarity": "COMMON", "brand": "x", "licensor": "y",
             "tirage": "5", "edition_type": "1"}
    ch = {"name": "Storm Vol. 5 #2", "series": "Storm", "category": "comic",
          "rarity": "Common", "brand": "Storm", "licensor": "Marvel",
          "supply": "1000", "edition_type": "1"}
    r = fusionner(sheet, ch)
    assert r["name"] == "Storm Vol. 5 #2"
    assert r["series"] == "Storm"          # <- deplace les adresses
    assert r["kind"] == "Comic"            # <- vocabulaire catalogue conserve
    assert r["rarity"] == "COMMON"
    assert r["tirage"] == "1000"


def test_valeur_chaine_vide_neffance_jamais_le_Sheet():
    sheet = {"name": "Batgirl", "series": "Cover Girls S1", "kind": "Collectible",
             "rarity": "RARE", "brand": "DC", "licensor": "WB", "tirage": "500",
             "edition_type": "FA"}
    r = fusionner(sheet, {"name": "", "series": "", "brand": None})
    assert r["name"] == "Batgirl"
    assert r["series"] == "Cover Girls S1"
    assert r["brand"] == "DC"


def test_uuid_absent_de_la_chaine_garde_tout_le_Sheet():
    sheet = {"name": "Drop tout neuf", "series": "S", "kind": "Collectible",
             "rarity": "COMMON", "brand": "b", "licensor": "l", "tirage": "1",
             "edition_type": ""}
    assert fusionner(sheet, None)["name"] == "Drop tout neuf"


def test_serie_non_adoptee_si_linterrupteur_est_ferme():
    # Permet de basculer les LIBELLES sans deplacer les ADRESSES.
    sheet = {"name": "Storm #2 (2024)", "series": "Storm #2 (2024)",
             "kind": "Comic", "rarity": "COMMON", "brand": "", "licensor": "",
             "tirage": "", "edition_type": ""}
    ch = {"name": "Storm Vol. 5 #2", "series": "Storm", "category": "comic"}
    r = fusionner(sheet, ch, adopter_serie=False)
    assert r["name"] == "Storm Vol. 5 #2"
    assert r["series"] == "Storm #2 (2024)"


def test_le_nom_fusionne_est_nettoye():
    r = fusionner({"name": "Immortal X-Men #16  (2022)", "kind": "Comic"}, {})
    assert r["name"] == "Immortal X-Men #16 (2022)"


# --- garde-fous ------------------------------------------------------------

def test_volumetrie_globale():
    with pytest.raises(IdentiteInvalide, match="volumetrie"):
        valider([ligne("u1")], mini_total=15_000)


def test_kind_hors_vocabulaire_refuse():
    lignes = [ligne(f"u{i}") for i in range(20)]
    lignes[7]["kind"] = "comic"          # minuscule = le defaut par repli
    with pytest.raises(IdentiteInvalide, match="hors vocabulaire"):
        valider(lignes, mini_total=10)


def test_famille_entiere_disparue_refusee():
    # LE test qui tue le defaut par repli : le total ne bouge pas, la famille si.
    lignes = [ligne(f"u{i}", kind=KIND_COLLECTIBLE) for i in range(100)]
    valider(lignes, mini_total=10)                       # le total passe
    with pytest.raises(IdentiteInvalide, match="famille"):
        valider(lignes, mini_total=10, mini_par_type={KIND_COMIC: 50})


def test_rarity_hors_vocabulaire_refusee():
    lignes = [ligne(f"u{i}") for i in range(20)]
    lignes[3]["rarity"] = "SECRET RARE"   # non normalisee
    with pytest.raises(IdentiteInvalide, match="rarity"):
        valider(lignes, mini_total=10)


def test_doublon_duuid_refuse():
    with pytest.raises(IdentiteInvalide, match="double"):
        valider([ligne("u1"), ligne("u1")], mini_total=1)


def test_nom_vide_refuse():
    with pytest.raises(IdentiteInvalide, match="nom vide"):
        valider([ligne("u1", name="  ")], mini_total=1)


def test_nom_sale_refuse():
    with pytest.raises(IdentiteInvalide, match="non nettoye"):
        valider([ligne("u1", name="Storm  #2")], mini_total=1)


def test_un_catalogue_sain_passe():
    lignes = ([ligne(f"c{i}") for i in range(60)]
              + [ligne(f"k{i}", kind=KIND_COLLECTIBLE, series="S",
                       name=f"Objet {i}") for i in range(40)])
    valider(lignes, mini_total=100,
            mini_par_type={KIND_COMIC: 50, KIND_COLLECTIBLE: 30})


def test_vocabulaires_declares_non_vides():
    assert VOCAB_KIND == ("Comic", "Collectible")
    assert "ULTRA_RARE" in VOCAB_RARITY and len(VOCAB_RARITY) == 6


# --- churn : le garde-fou ne d'une vraie erreur ----------------------------

def _paire(n_change, total=100, col="name"):
    av = {f"u{i}": ligne(f"u{i}") for i in range(total)}
    ap = {u: dict(r) for u, r in av.items()}
    for i in range(n_change):
        ap[f"u{i}"][col] = "Autre libelle"
    return av, ap


def test_churn_de_masse_refuse_par_defaut():
    # Le cas REEL du 28/07 : une source degradee ecrase 84,8 % des noms sur
    # leur nom de serie. Toutes les lignes restent VALIDES une a une.
    av, ap = _paire(85)
    with pytest.raises(IdentiteInvalide, match="NON APPROUVE"):
        verifier_churn(av, ap, {"name": 0.45})


def test_churn_sous_le_plafond_passe():
    av, ap = _paire(30)
    verifier_churn(av, ap, {"name": 0.45})


def test_churn_de_masse_accepte_si_explicitement_autorise():
    av, ap = _paire(85)
    verifier_churn(av, ap, {"name": 0.45}, autorise=True)


def test_le_message_de_churn_nomme_la_colonne_et_montre_un_exemple():
    av, ap = _paire(85)
    with pytest.raises(IdentiteInvalide) as e:
        verifier_churn(av, ap, {"name": 0.45})
    assert "name" in str(e.value) and "Autre libelle" in str(e.value)


def test_un_catalogue_valide_ligne_a_ligne_peut_etre_insense_en_masse():
    # La demonstration en un test : `valider` passe, `verifier_churn` refuse.
    av, ap = _paire(90)
    valider(list(ap.values()), mini_total=10,
            mini_par_type={KIND_COMIC: 10})          # ✅ chaque ligne est bonne
    with pytest.raises(IdentiteInvalide):
        verifier_churn(av, ap, {"name": 0.45})       # ⛔ l'ensemble ne l'est pas


# --- rapport ---------------------------------------------------------------

def test_le_rapport_chiffre_ce_qui_bouge():
    av = {"u1": ligne("u1"), "u2": ligne("u2")}
    ap = {"u1": ligne("u1", name="Autre nom"), "u2": ligne("u2")}
    txt = rapport(av, ap)
    assert "1 modifies" in txt.replace("     1 modifies", "1 modifies")
    assert "Autre nom" in txt
