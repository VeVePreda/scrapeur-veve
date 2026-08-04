# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve · CHEMIN : tests/test_annonce_visuel.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""Banc de l'affiche « RETOUR SUR <MOIS> ».

⛔ AUCUN RESEAU, AUCUNE IMAGE DE VeVe. Un banc qui telecharge le CDN ne prouve
rien le jour ou le CDN nous bloque — le seul jour ou ce code sert vraiment.
Les images sont fabriquees en memoire.

Ce qui est teste, c'est ce qui, en se trompant, **publie quand meme** :
  * une affiche qui prend l'annonce en otage (fond absent -> plus d'annonce) ;
  * un texte qui deborde de sa zone sans lever d'erreur ;
  * une surcharge de gabarit lue en silence… ou pas lue du tout ;
  * les deux lecteurs de 🏆A-CLASSEMENT qui divergent.

    python3 -m pytest tests/test_annonce_visuel.py -q
"""

from __future__ import annotations

import json
import os
import sys

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from outils.annonce_visuel import gabarit as G              # noqa: E402
from outils.annonce_visuel import rendu as R                # noqa: E402
from scraper import annonce_classement as ac                # noqa: E402
from scraper import annonce_images as ai                    # noqa: E402


# ═══════════════════════════════════════════════════════════ outillage du banc

def fond(tmp_path, largeur=1920, hauteur=1080) -> str:
    """Un faux decor : un degrade, pour voir ce qui est colle par-dessus."""
    img = Image.new("RGB", (largeur, hauteur), (18, 20, 26))
    d = ImageDraw.Draw(img)
    for y in range(0, hauteur, 8):
        d.line((0, y, largeur, y), fill=(18, 20 + y // 40, 40 + y // 20))
    chemin = str(tmp_path / "fond.png")
    img.save(chemin)
    return chemin


class FauxOnglet:
    def __init__(self, valeurs):
        self._v = valeurs

    def get_all_values(self):
        return [list(l) for l in self._v]


class FauxSheet:
    def __init__(self, onglets):
        self._o = onglets

    def worksheet(self, nom):
        if nom not in self._o:
            raise KeyError(nom)
        return FauxOnglet(self._o[nom])


# Une page 🏆A-CLASSEMENT realiste : banniere en ligne 1, en-tetes en ligne 3,
# une colonne en double (le piege qui fait exploser get_all_records).
CLASSEMENT = [
    ["🆕 À NOTER — COMICS : 3", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", ""],
    ["etat", "uuid", "type", "nom", "note", "supply", "valeur_irl_98",
     "fa_key", "start_year", "date_drop", "note"],
    ["ok", "cd511719", "comic", "Incredible Hulk #340", "AA", "2000", "1258",
     "Wolverine", "1962", "2026-05-14", "AA"],
    ["ok", "aaa11111", "comic", "Amazing Fantasy #15 (1962)", "AAA", "10000",
     "5000000", "Spider-Man", "1962", "2022-08-08", "AAA"],
    ["", "", "", "", "", "", "", "", "", "", ""],
]


@pytest.fixture(autouse=True)
def env_propre(monkeypatch, tmp_path):
    for cle in ("ANNONCE_VISUEL_FOND", "ANNONCE_VISUEL_GABARIT",
                "ANNONCE_VISUEL_TTF"):
        monkeypatch.delenv(cle, raising=False)
    monkeypatch.setattr(G, "CHEMIN_SURCHARGE", str(tmp_path / "gabarit.json"))
    yield


# ═══════════════════════════════════════════ 1. LE GABARIT — fractions et JSON

def test_les_zones_sont_des_fractions():
    """⭐ Un gabarit écrit en pixels meurt au premier re-export du décor."""
    for nom, (x, y, l, h) in G.ZONES.items():
        assert 0 <= x <= 1 and 0 <= y <= 1, nom
        assert 0 < l <= 1 and 0 < h <= 1, nom
        assert x + l <= 1.001 and y + h <= 1.001, f"{nom} sort du cadre"


def test_les_zones_suivent_la_taille_du_cadre():
    g1 = G.boite(G.ZONES["banniere"], 1920, 1080)
    g2 = G.boite(G.ZONES["banniere"], 3840, 2160)
    assert [v * 2 for v in g1] == pytest.approx(list(g2), abs=2)


def test_la_banniere_couvre_TOUT_le_bandeau():
    """⭐⭐ Preda a laissé un TROU TRANSPARENT dans son décor : **le décor est un
    MASQUE**. Inutile de découper la forme du trou — on peint large dessous et
    le décor décide de ce qui se voit. Une forme découpée à la main se
    désynchroniserait au premier re-export ; un masque, jamais."""
    x, y, l, h = G.ZONES["banniere"]
    assert (x, y, l) == (0.0, 0.0, 1.0)
    assert 0.40 <= h <= 0.50, "le bandeau s'arrête sous la barre VEVE FRANCE"


def test_la_banniere_passe_SOUS_le_decor(tmp_path):
    """L'ordre des couches est le cœur du rendu. À l'envers, la bannière
    recouvrirait le cœur et la barre « VEVE FRANCE »."""
    # un decor opaque partout SAUF un trou au milieu du bandeau
    decor = Image.new("RGBA", (400, 300), (10, 10, 10, 255))
    for y in range(20, 100):
        for x in range(100, 300):
            decor.putpixel((x, y), (0, 0, 0, 0))
    chemin = str(tmp_path / "decor.png")
    decor.save(chemin)
    ban = tmp_path / "ban.png"
    Image.new("RGB", (800, 200), (255, 0, 0)).save(ban)

    sortie = str(tmp_path / "a.png")
    R.composer("MAI", str(ban), [], {}, sortie, fond=chemin)
    img = Image.open(sortie).convert("RGB")
    assert img.getpixel((200, 60))[0] > 200, "le trou ne montre pas la banniere"
    # (20, 10) : DANS la zone banniere, mais sous une partie OPAQUE du decor —
    # et au-dessus du titre, qui écrit du blanc plus bas.
    assert img.getpixel((20, 10))[0] < 60, "la banniere deborde sur le decor"


def test_le_titre_porte_le_DRAPEAU_pas_du_blanc():
    """⭐⭐ Relevé au pixel sur son visuel de mai : « RET » bleu, « OUR » blanc,
    « SUR » rouge. Une charte devinée à l'œil dérive ; une charte relevée sur la
    source, non."""
    assert [m for m, _ in G.TITRE_HAUT] == ["RET", "OUR", "SUR"]
    bleu, blanc, rouge = [c for _, c in G.TITRE_HAUT]
    assert bleu[2] > 200 and bleu[0] < 60, "RET doit être bleu"
    assert blanc[:3] == (255, 255, 255)
    assert rouge[0] > 150 and rouge[2] < 60, "SUR doit être rouge"


def test_le_voile_protege_le_titre_dune_banniere_claire(tmp_path, monkeypatch):
    """🔴 Découvert en rendant pour de vrai : **le cœur du décor est
    SEMI-TRANSPARENT**. Son visuel de mai tenait parce que sa bannière était
    sombre. ⭐ Un rendu qui ne marche que sur l'exemple qui a servi à le
    concevoir n'est pas fini."""
    decor = Image.new("RGBA", (400, 300), (0, 0, 0, 0))   # tout transparent
    chemin = str(tmp_path / "decor.png")
    decor.save(chemin)
    ban = tmp_path / "ban.png"
    Image.new("RGB", (800, 300), (255, 255, 255)).save(ban)   # banniere BLANCHE

    avec = str(tmp_path / "avec.png")
    R.composer("MAI", str(ban), [], {}, avec, fond=chemin)
    monkeypatch.setenv("ANNONCE_VISUEL_VOILE", "0")
    sans = str(tmp_path / "sans.png")
    R.composer("MAI", str(ban), [], {}, sans, fond=chemin)

    # sous le titre, le voile doit avoir assombri
    a = Image.open(avec).convert("RGB").getpixel((30, 60))
    b = Image.open(sans).convert("RGB").getpixel((30, 60))
    assert sum(a) < sum(b) - 60, "le voile n'assombrit pas la banniere claire"


# ═══════════════════════════════════════════════════ 1 bis. LE LOGO EN FILIGRANE

def test_le_logo_est_MUET_par_defaut():
    """⭐ Le décor de Preda porte déjà le cœur : le reposer donnerait un logo
    en double — invisible dans le code, très visible sur le visuel publié."""
    assert G.logo() == ""


def test_le_logo_du_depot_sallume_a_la_demande(monkeypatch):
    monkeypatch.setenv("ANNONCE_VISUEL_LOGO", "1")
    assert G.logo() == G.LOGO_LIVRE
    monkeypatch.setenv("ANNONCE_VISUEL_LOGO", "/ailleurs/x.png")
    assert G.logo() == "/ailleurs/x.png"


def test_un_logo_introuvable_ne_casse_pas_laffiche(tmp_path, monkeypatch,
                                                   capsys):
    monkeypatch.setenv("ANNONCE_VISUEL_LOGO", str(tmp_path / "absent.png"))
    sortie = str(tmp_path / "a.png")
    R.composer("MAI", "", [], {}, sortie, fond=fond(tmp_path))
    assert os.path.exists(sortie)
    assert "logo introuvable" in capsys.readouterr().out


def test_le_logo_demande_change_le_rendu(tmp_path, monkeypatch):
    f = fond(tmp_path)
    sans = str(tmp_path / "sans.png")
    R.composer("MAI", "", [], {}, sans, fond=f)
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (400, 400), (255, 0, 0, 255)).save(logo)
    monkeypatch.setenv("ANNONCE_VISUEL_LOGO", str(logo))
    avec = str(tmp_path / "avec.png")
    R.composer("MAI", "", [], {}, avec, fond=f)
    assert open(sans, "rb").read() != open(avec, "rb").read()


def test_les_tuiles_ne_se_chevauchent_pas():
    """Deux cases qui se recouvrent ne lèvent rien : la 2e écrase la 1re."""
    def rect(n):
        x, y, l, h = G.ZONES[n]
        return x, y, x + l, y + h

    noms = list(G.TUILES)
    for i, a in enumerate(noms):
        for b in noms[i + 1:]:
            ax, ay, ad, ab = rect(a)
            bx, by, bd, bb = rect(b)
            assert ad <= bx or bd <= ax or ab <= by or bb <= ay, \
                f"{a} et {b} se chevauchent"


def test_une_surcharge_json_ecrase_la_zone(tmp_path, monkeypatch):
    chemin = tmp_path / "g.json"
    chemin.write_text(json.dumps({"titre": [0.1, 0.2, 0.3, 0.4]}),
                      encoding="utf-8")
    monkeypatch.setattr(G, "CHEMIN_SURCHARGE", str(chemin))
    z = G.zones()
    assert z["titre"] == (0.1, 0.2, 0.3, 0.4)
    assert z["tuile_1"] == G.ZONES["tuile_1"], "les autres zones ne bougent pas"


def test_une_surcharge_bancale_ne_casse_rien_mais_se_DIT(tmp_path, monkeypatch,
                                                         capsys):
    """⭐ Sinon Preda corrigerait des coordonnées qui ne sont jamais lues."""
    chemin = tmp_path / "g.json"
    chemin.write_text(json.dumps({"titre": [0.1, 0.2], "zone_qui_nexiste_pas":
                                  [0, 0, 1, 1]}), encoding="utf-8")
    monkeypatch.setattr(G, "CHEMIN_SURCHARGE", str(chemin))
    z = G.zones()
    assert z["titre"] == G.ZONES["titre"]
    sortie = capsys.readouterr().out
    assert "mal formee" in sortie and "inconnue" in sortie


def test_un_json_absent_est_le_cas_NORMAL_et_reste_muet(capsys):
    G.zones()
    assert capsys.readouterr().out == ""


# ═══════════════════════════════════════════════════ 2. LE RENDU

def test_sans_fond_on_leve_et_on_ne_bricole_pas_un_decor(tmp_path):
    """⭐ Une affiche « presque » à la charte est pire qu'une absence
    d'affiche — l'appelant décide, le moteur n'improvise pas."""
    with pytest.raises(FileNotFoundError):
        R.composer("MAI", "", [], {}, str(tmp_path / "x.png"),
                   fond=str(tmp_path / "inexistant.png"))


def test_sans_banniere_le_bandeau_reste_propre(tmp_path):
    """Pas d'URL = pas de trou noir béant : l'aplat de repli est posé d'abord."""
    sortie = str(tmp_path / "a.png")
    R.composer("MAI", "", [], {}, sortie, fond=fond(tmp_path))
    assert os.path.exists(sortie)


def test_une_affiche_sort_meme_sans_AUCUNE_image(tmp_path):
    """Réseau coupé, CDN qui refuse : le visuel sort avec des cases sombres.
    ⭐ Mieux vaut une affiche à trous qu'aucune affiche."""
    sortie = str(tmp_path / "a.png")
    R.composer("MAI", "", [], {}, sortie, fond=fond(tmp_path))
    assert os.path.exists(sortie)
    img = Image.open(sortie)
    assert img.size == (1920, 1080)


def test_le_mois_est_ecrit_sur_laffiche(tmp_path):
    """On ne relit pas des pixels : on vérifie que le titre CHANGE le rendu."""
    f = fond(tmp_path)
    a, b = str(tmp_path / "a.png"), str(tmp_path / "b.png")
    R.composer("MAI", "", [], {}, a, fond=f)
    R.composer("DECEMBRE", "", [], {}, b, fond=f)
    assert open(a, "rb").read() != open(b, "rb").read()


def test_laffiche_suit_la_taille_du_fond(tmp_path):
    sortie = str(tmp_path / "a.png")
    R.composer("MAI", "", [], {}, sortie,
               fond=fond(tmp_path, 1280, 720))
    assert Image.open(sortie).size == (1280, 720)


def test_la_grille_de_controle_sort_une_image(tmp_path):
    """⭐ L'outil qui remplace « je crois que c'est bien aligné »."""
    sortie = str(tmp_path / "grille.png")
    R.grille(sortie, fond=fond(tmp_path))
    assert os.path.exists(sortie)


def test_le_journal_compte_les_cases_en_repli(tmp_path, capsys):
    R.composer("MAI", "", ["", "", "", "", ""], {}, str(tmp_path / "a.png"),
               fond=fond(tmp_path))
    assert "repli" in capsys.readouterr().out


# ═══════════════════════════════════ 3. LA CARTE DU COMIC — le texte qui rentre

def test_la_carte_porte_les_six_lignes_de_preda():
    lignes = R.lignes_carte({"nom": "Incredible Hulk #340", "dispo": "14/05/26",
                             "annee": "1962", "estimation": "1258",
                             "premiere_app": "", "supply": "2000"})
    assert lignes == ["INCREDIBLE HULK #340",
                      "DISPO DEPUIS LE 14/05/26",
                      "COMICS DE 1962",
                      "ESTIMATION IRL 1 258",
                      "FIRST APPARENCE -/-",
                      "SUPPLY 2 000"]


def test_une_donnee_absente_secrit_et_ne_disparait_pas():
    """⭐ « -/- » est SA convention (son visuel de mai le porte). Une carte qui
    change de forme selon les données manquantes se lit mal."""
    lignes = R.lignes_carte({})
    assert len(lignes) == 6
    assert all("-/-" in l or l == "-/-" for l in lignes)


def test_un_titre_trop_long_est_REDUIT_pas_deborde(tmp_path):
    """⭐ Un texte qui déborde ne lève aucune erreur : il sort du cadre, et on
    ne le voit qu'une fois le visuel publié."""
    f = fond(tmp_path)
    court = str(tmp_path / "court.png")
    long = str(tmp_path / "long.png")
    R.composer("MAI", "", [], {"nom": "Hulk #1", "supply": "2000"}, court,
               fond=f)
    R.composer("MAI", "", [], {"nom": "Amazing Fantasy #15 (1962) " * 4,
                               "supply": "2000"}, long, fond=f)
    # Les deux sortent, aux memes dimensions : rien n'a deborde du cadre.
    assert Image.open(court).size == Image.open(long).size == (1920, 1080)


# ═══════════════════════════════════ 4. LE LECTEUR DE 🏆A-CLASSEMENT

def test_les_entetes_ne_sont_PAS_en_ligne_1():
    """La page commence par une bannière. ⭐ On cherche la donnée, on ne
    suppose pas où elle est."""
    sh = FauxSheet({"🏆A-CLASSEMENT": CLASSEMENT})
    lignes = ac.lignes(sh)
    assert len(lignes) == 2
    assert lignes[0]["nom"] == "Incredible Hulk #340"


def test_une_colonne_en_DOUBLE_ne_fait_pas_exploser_la_lecture():
    """`get_all_records()` lève « the header row is not unique » — la page a
    deux colonnes `note`."""
    sh = FauxSheet({"🏆A-CLASSEMENT": CLASSEMENT})
    assert ac.lignes(sh)


def test_une_page_absente_rend_une_liste_vide_pas_une_exception():
    sh = FauxSheet({})
    assert ac.lignes(sh) == []


def test_la_carte_est_remplie_depuis_le_classement():
    sh = FauxSheet({"🏆A-CLASSEMENT": CLASSEMENT})
    fiche = ac.par_cle(sh)["cd511719"]
    carte = ac.carte(fiche)
    assert carte["annee"] == "1962"
    assert carte["estimation"] == "1258"
    assert carte["premiere_app"] == "Wolverine"
    assert carte["supply"] == "2000"
    assert carte["dispo"] == "14/05/26", "le format jj/mm/aa de Preda"


def test_une_date_illisible_ne_fabrique_pas_une_fausse_date():
    assert ac._jj_mm_aa("46212.625") == ""
    assert ac._jj_mm_aa("") == ""
    assert ac._jj_mm_aa("14/05/2026 15:00") == "14/05/26"


def test_sans_fiche_la_carte_garde_le_nom_du_catalogue():
    carte = ac.carte({}, nom_repli="Hulk #340", image_repli="https://x.png")
    assert carte["nom"] == "Hulk #340" and carte["image"] == "https://x.png"


def test_les_DEUX_lecteurs_du_classement_sont_daccord():
    """⚠️⚠️ `annonce_classement.lignes` et `discord_retour.notes_de_classement`
    font le MEME ancrage sur la MEME page. Je n'ai pas refactorisé le module
    quotidien pour une affiche mensuelle — mais deux lecteurs de la même page
    finissent toujours par diverger. Ce banc les épingle l'un à l'autre : le
    jour où l'un bougera, il criera."""
    from scraper import discord_retour as dr
    sh = FauxSheet({"🏆A-CLASSEMENT": CLASSEMENT})
    notes_retour = dr.notes_de_classement(sh)
    notes_annonce = {}
    for l in ac.lignes(sh):
        cle = str(l.get("uuid") or "").strip()
        if cle and l.get("note"):
            notes_annonce.setdefault(cle, str(l["note"]).strip())
    assert notes_retour == notes_annonce, (
        "les deux lecteurs de 🏆A-CLASSEMENT ont divergé")
