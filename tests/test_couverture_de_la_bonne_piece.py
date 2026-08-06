# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_couverture_de_la_bonne_piece.py
"""🖼️ LA COUVERTURE D'UNE AUTRE PIECE N'EST PAS « UNE COUVERTURE » (06/08/2026).

⭐⭐ CE QUE CE BANC ATTRAPE. `sheets._normalise` ne posait la couverture
on-chain que dans une case VIDE. Mais `run.py` ecrit `image_url = media[0]` sur
les CINQ lignes de rarete d'un comic AVANT d'arriver la. La case n'etait donc
pas vide — elle contenait la couverture de la serie, ou celle d'une rarete
voisine. Le module precis perdait contre le repli, en silence, et le resultat
etait PLAUSIBLE : une couverture de comic sur une fiche de comic.

Mesure du 06/08 sur 250 series tirees au sort (975 lignes de rarete) :
    ·  3,4 % recoivent LEUR couverture par l'API ;
    · 23,4 % recoivent celle d'une voisine EN AYANT la leur sur la chaine.
La bonne couverture passe de 35,7 % a 59,1 % — ~3 881 fiches sur 16 597.

⛔ ET CE BANC GARDE AUSSI LA RETENUE. Le remplacement ne vaut que quand les
deux moities se prouvent. Un banc qui n'exigerait que « la chaine gagne »
laisserait passer un module qui ecrase tout, y compris ce qu'il ne comprend
pas — et un visuel casse est PIRE qu'un visuel imprecis.
"""
from scraper import couvertures_chaine as cc

A = "11111111-1111-1111-1111-111111111111"   # notre piece
B = "22222222-2222-2222-2222-222222222222"   # une autre rarete
S = "33333333-3333-3333-3333-333333333333"   # la serie

CDN = "https://d11unjture0ske.cloudfront.net/"
SIENNE = f"{CDN}comic_cover.{A}.aaaa.full.jpeg"
VOISINE = f"{CDN}comic_cover.{B}.bbbb.full.jpeg"
DE_SERIE = f"{CDN}comic_type_image.{S}.cccc.full.jpeg"
COLLECTIBLE = f"{CDN}collectible_type_image.{B}.dddd.full.jpeg"


def test_on_reconnait_la_couverture_de_sa_propre_piece():
    assert cc.appartient_a(SIENNE, A)
    assert not cc.appartient_a(VOISINE, A)
    assert not cc.appartient_a(DE_SERIE, A)


def test_la_couverture_d_une_voisine_est_a_corriger():
    assert cc.couverture_d_une_autre_piece(VOISINE, A)


def test_l_image_de_serie_est_a_corriger():
    """⭐ C'est le cas MAJORITAIRE, pas le cas exotique : `media` rend surtout
    des `comic_type_image.<serie>` — l'image de la serie, appliquee aux cinq
    raretes."""
    assert cc.couverture_d_une_autre_piece(DE_SERIE, A)


def test_sa_propre_couverture_n_est_jamais_touchee():
    assert not cc.couverture_d_une_autre_piece(SIENNE, A)


def test_un_visuel_de_collectible_reste_hors_de_portee():
    """⛔ Un `collectible_type_image` est l'image de la piece elle-meme : elle
    ne porte pas le uuid par convention. La juger sur cette regle la
    condamnerait a tort — et remplacerait des visuels justes."""
    assert not cc.couverture_d_une_autre_piece(COLLECTIBLE, A)


def test_une_adresse_dont_on_ne_sait_rien_reste_en_place():
    for inconnue in ("", "   ", "pas-une-url", f"{CDN}autre_chose.{B}.x.jpeg"):
        assert not cc.couverture_d_une_autre_piece(inconnue, A), inconnue


def test_normalise_corrige_la_ligne_qui_porte_la_couverture_d_une_voisine(monkeypatch):
    """⭐⭐ LE BANC QUI JUGE LE CHEMIN REEL. Les deux precedents jugent la
    regle ; celui-ci juge l'endroit ou elle s'applique — c'est la que le
    defaut vivait, pas dans la regle."""
    from scraper import sheets

    cc._reinit()
    monkeypatch.setattr(cc, "_MAP", {A: SIENNE})
    monkeypatch.setenv("COUVERTURES_CHAINE", "1")

    rec = {"veve_uuid": A, "category": "comic", "image_url": DE_SERIE}
    sheets._normalise(rec)
    assert rec["image_url"] == SIENNE
    assert cc.bilan()["remplacees"] == 1


def test_normalise_garde_la_couverture_de_serie_si_la_chaine_n_a_rien(monkeypatch):
    """⛔ On DEGRADE, on ne casse pas : sans remplacant prouve, la couverture
    imprecise reste. Elle est lisible ; un trou ne l'est pas."""
    from scraper import sheets

    cc._reinit()
    monkeypatch.setattr(cc, "_MAP", {})
    monkeypatch.setenv("COUVERTURES_CHAINE", "1")

    rec = {"veve_uuid": A, "category": "comic", "image_url": DE_SERIE}
    sheets._normalise(rec)
    assert rec["image_url"] == DE_SERIE
    assert cc.bilan()["remplacees"] == 0
