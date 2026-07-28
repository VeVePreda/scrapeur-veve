# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_calendrier.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""Tests du calendrier visuel — la partie qui peut MENTIR sans planter.

Ce qui est teste ici est exactement ce qui, en se trompant, ne leve aucune
erreur : une fenetre decalee d'une semaine, un comic compte 5 fois, une date en
texte mal lue, un titre qui deborde de sa case. Le rendu graphique, lui, se
verifie a l'oeil — un test ne dira jamais qu'un visuel est moche.

    python3 -m pytest tests/test_calendrier.py -q
"""

from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from outils.calendrier import donnees as D          # noqa: E402
from outils.calendrier import rendu as R            # noqa: E402
from outils.calendrier import themes as T           # noqa: E402


# ------------------------------------------------------------------- fenetre

def test_fenetre_se_termine_par_la_semaine_en_cours():
    # mardi 28/07/2026 -> la derniere ligne est la semaine du lundi 27
    debut, fin = D.fenetre(dt.date(2026, 7, 28), semaines=5)
    assert debut == dt.date(2026, 6, 29)            # un lundi
    assert fin == dt.date(2026, 8, 2)               # le dimanche de la 5e semaine
    assert debut.weekday() == 0 and fin.weekday() == 6


def test_fenetre_donne_toujours_un_multiple_de_sept():
    for jour in range(1, 29):
        debut, fin = D.fenetre(dt.date(2026, 2, jour), semaines=5)
        assert len(D.jours_de(debut, fin)) == 35


def test_decalage_recule_bien_dune_semaine():
    a, _ = D.fenetre(dt.date(2026, 7, 28))
    b, _ = D.fenetre(dt.date(2026, 7, 28), decalage=-1)
    assert (a - b).days == 7


# --------------------------------------------------------------------- dates

def test_date_de_lit_le_texte_du_sheet_et_le_datetime_du_xlsx():
    attendu = dt.date(2026, 7, 22)
    assert D.date_de("2026-07-22 20:00:00") == attendu
    assert D.date_de(dt.datetime(2026, 7, 22, 20, 0)) == attendu
    assert D.date_de("2026-07-22T20:00:00") == attendu
    assert D.date_de("22/07/2026") == attendu


def test_date_illisible_ne_leve_pas():
    assert D.date_de("") is None
    assert D.date_de(None) is None
    assert D.date_de("pas une date") is None


# ---------------------------------------------------------------- regroupage

def _ligne(**kw):
    base = {"veve_uuid": "u", "name": "n", "rarity": "COMMON", "edition_type": "",
            "releaseDate": "2026-07-22 20:00:00", "veve_series_name": "S",
            "series_uuid": "s1", "veve_brand": "B", "veve_licensor": "Marvel",
            "image_url": "", "drop_method": "", "supply": "", "_nature": "comic"}
    base.update(kw)
    return base


def test_les_cinq_raretes_dun_comic_ne_font_quun_seul_drop():
    """⚠️ LE test du module : compter les lignes ferait « 150 drops » un mercredi."""
    lignes = [_ligne(rarity=r) for r in
              ("COMMON", "UNCOMMON", "RARE", "ULTRA_RARE", "SECRET_RARE")]
    cal = D.grouper(lignes, dt.date(2026, 7, 20), dt.date(2026, 7, 26))
    jour = cal[dt.date(2026, 7, 22)]
    assert jour.nb == 1
    assert jour.series[0].editions == 5


def test_limage_retenue_est_celle_de_la_rarete_la_plus_basse():
    lignes = [_ligne(rarity="SECRET_RARE", image_url="rare.webp"),
              _ligne(rarity="COMMON", image_url="base.webp")]
    cal = D.grouper(lignes, dt.date(2026, 7, 20), dt.date(2026, 7, 26))
    assert cal[dt.date(2026, 7, 22)].series[0].image_url == "base.webp"


def test_lordre_des_lignes_ne_change_pas_le_resultat():
    """Deux runs doivent donner le meme visuel : le choix doit etre deterministe."""
    lignes = [_ligne(rarity="SECRET_RARE", image_url="rare.webp"),
              _ligne(rarity="COMMON", image_url="base.webp")]
    a = D.grouper(lignes, dt.date(2026, 7, 20), dt.date(2026, 7, 26))
    b = D.grouper(list(reversed(lignes)), dt.date(2026, 7, 20), dt.date(2026, 7, 26))
    cle = dt.date(2026, 7, 22)
    assert a[cle].series[0].image_url == b[cle].series[0].image_url


def test_les_jours_vides_restent_dans_la_grille():
    cal = D.grouper([_ligne()], dt.date(2026, 7, 20), dt.date(2026, 7, 26))
    assert len(cal) == 7
    assert cal[dt.date(2026, 7, 21)].vide


def test_hors_fenetre_est_ignore():
    cal = D.grouper([_ligne(releaseDate="2021-01-01 20:00:00")],
                    dt.date(2026, 7, 20), dt.date(2026, 7, 26))
    assert sum(j.nb for j in cal.values()) == 0


def test_les_series_illustrees_passent_devant():
    lignes = [_ligne(series_uuid="a", veve_series_name="AAA", image_url=""),
              _ligne(series_uuid="b", veve_series_name="ZZZ", image_url="z.webp")]
    cal = D.grouper(lignes, dt.date(2026, 7, 20), dt.date(2026, 7, 26))
    assert cal[dt.date(2026, 7, 22)].series[0].nom == "ZZZ"


# ------------------------------------------------------------------ decoupage

def test_un_titre_long_ne_deborde_jamais_du_nombre_de_lignes():
    lignes = R._couper("Godzilla Conquers The Multiverse #1 (2026)", 130, 15, 3, 0.50)
    assert len(lignes) <= 3


def test_un_mot_plus_long_que_la_case_est_coupe():
    """Sans cette coupe, le mot sortait de la case — et le clip le tranchait net."""
    lignes = R._couper("Aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 100, 15, 3, 0.62)
    assert all(len(l) <= 12 for l in lignes)


def test_une_police_large_tient_moins_de_caracteres():
    etroite = R._couper("un titre de serie assez long", 130, 15, 3, 0.42)
    large = R._couper("un titre de serie assez long", 130, 15, 3, 0.62)
    assert len(etroite[0]) > len(large[0])


# --------------------------------------------------------------------- themes

def test_les_marques_ne_partagent_ni_palette_ni_polices():
    """La règle Preda : on ne doit pas pouvoir deviner un lien entre marques."""
    vus = set()
    for cle, th in T.THEMES.items():
        signature = (th.police_titre, th.police_texte, th.accent, th.fond)
        assert signature not in vus, "deux marques ont la même signature : %s" % cle
        vus.add(signature)


def test_seules_les_marques_cousines_partagent_la_silhouette():
    """Deux marques SANS parenté déclarée doivent aussi différer de mise en page.

    VeVe France et VeVe Insights font exception : `newsletters-v4/README.md` les
    déclare jumelles (l'une est la version anglaise de l'autre).
    """
    for cle_a, a in T.THEMES.items():
        for cle_b, b in T.THEMES.items():
            if cle_a >= cle_b:
                continue
            cousines = (a.cousin_de == cle_b) or (b.cousin_de == cle_a)
            if cousines:
                continue
            assert (a.entete, a.position_jour) != (b.entete, b.position_jour), \
                "%s et %s ont la même silhouette sans être cousines" % (cle_a, cle_b)


def test_toute_marque_porte_son_site_et_son_discord():
    for cle, th in T.THEMES.items():
        assert th.site and th.discord, cle           # l'outil est promotionnel


def test_chaque_marque_a_son_logo_livre():
    """Un logo manquant ne casse rien : l'en-tête tombe sur une pastille unie."""
    for cle, th in T.THEMES.items():
        chemin = os.path.join(R.DOSSIER_LOGOS, th.logo)
        assert os.path.exists(chemin), "logo absent pour %s : %s" % (cle, chemin)


# ------------------------------------------------------------------- glyphes

def test_le_controle_de_glyphes_attrape_la_fleche():
    """La flèche U+2192 n'existe pas dans Nunito : elle sortait en carré vide."""
    from outils.calendrier import polices as P
    if not os.path.isdir(P.DOSSIER_TTF):
        return                                       # polices non livrées ici
    manquants = P.verifier_glyphes([("Nunito", "29 JUIN → 2 AOÛT")], strict=False)
    assert manquants, "le contrôle aurait dû signaler la flèche"
    assert not P.verifier_glyphes([("Nunito", "29 JUIN » 2 AOÛT")], strict=False)


def test_tous_les_textes_du_visuel_sont_tracables():
    """Le garde-fou en conditions réelles : aucune police ne doit reculer.

    Les libellés (mois, jours, mentions légales) contiennent des accents et des
    signes que les polices sous-ensemblées pourraient avoir perdus au subsetting.
    """
    from outils.calendrier import polices as P
    if not os.path.isdir(P.DOSSIER_TTF):
        return
    paires = []
    for th in T.THEMES.values():
        lg = T.langue_de(th)
        mots = (list(T.JOURS[lg]) + list(T.MOIS_LONG[lg]) + list(T.MOIS_COURT[lg])
                + list(T.MOTS[lg].values())
                + [th.titre, th.marque, th.site, th.discord, th.mention])
        paires += [(th.police_titre, m) for m in mots]
        paires += [(th.police_texte, m) for m in mots]
    assert not P.verifier_glyphes(paires, strict=False)
