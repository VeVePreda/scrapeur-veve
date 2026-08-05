# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve · CHEMIN : tests/test_format_archive_partage.py

"""🧬 LE FORMAT D'ARCHIVE EST PARTAGE — phase 4.1, volet « meme depot ».

Deux modules de CE depot ecrivent le MEME fichier d'archive des transferts :

    scraper/chain_run.py     l'ecriture QUOTIDIENNE
    scraper/wallet_scan.py   l'ecriture du SCAN PROFOND

Ils declarent chacun leur `ARCHIVE_HEADER`, et rien ne les obligeait a etre
d'accord.

🔴🔴 CE BANC EXISTE PARCE QUE LA FAUTE A ETE COMMISE LE 05/08/2026, LE MATIN
MEME OU J'ECRIVAIS QU'ELLE ARRIVERAIT. Le lot 64 a ajoute `token_id` a
`chain_run.ARCHIVE_HEADER` et a laisse `wallet_scan.ARCHIVE_HEADER` a 10
colonnes. Le commentaire que j'ai ecrit dans le lot 64 disait :

    « le scan profond (astronema/wallet_scan.py) n'a pas encore la colonne »

C'etait vrai — et ca rangeait le fichier chez le voisin. Le meme fichier etait
a cote de moi, dans le depot que j'editais.

⭐⭐⭐ UNE COPIE QU'ON DESIGNE PAR SON AUTRE DEPOT DEVIENT INVISIBLE DANS LE
SIEN. Un `grep ARCHIVE_HEADER scraper/` l'aurait montre en une seconde ; la
phrase « dans l'autre depot » a suffi a ne pas le faire.

⛔ LA DECOUVERTE EST AUTOMATIQUE, PAS UNE LISTE. Une liste en dur des modules a
comparer serait exactement le meme piege un cran plus loin : le jour ou un
troisieme module ecrit ce format, il ne serait pas dans la liste et le banc
resterait vert. Ce banc BALAYE `scraper/` et compare tout ce qu'il trouve.
⭐⭐ UN BANC QUI ENUMERE CE QU'IL SURVEILLE NE SURVEILLE QUE CE QU'IL CONNAIT.
"""
from __future__ import annotations

import importlib
import os
import pathlib
import re
import sys

import pytest

RACINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

# Les 10 premieres colonnes sont un CONTRAT INTER-DEPOTS : `merge_transfers.py`
# (fanablefrance/jetonveve) lit ce format par POSITION (`p[0]`..`p[9]`), avec un
# garde `len(p) < 10`. Figees ici en dur, separement des modules : les relire
# depuis l'un d'eux validerait le depot contre lui-meme.
DIX_PREMIERES_HISTORIQUES = ["block", "log_index", "ts_utc", "date_pt", "kind",
                             "category", "veve_uuid", "edition", "from", "to"]


def _modules_qui_declarent_un_archive_header():
    """Balaye `scraper/` et rend {nom_module: ARCHIVE_HEADER}. Aucune liste."""
    trouves = {}
    for f in sorted((RACINE / "scraper").glob("*.py")):
        texte = f.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"^ARCHIVE_HEADER\s*=", texte, re.M):
            continue
        mod = importlib.import_module("scraper." + f.stem)
        entete = getattr(mod, "ARCHIVE_HEADER", None)
        if isinstance(entete, (list, tuple)):
            trouves[f.stem] = list(entete)
    return trouves


def test_le_balayage_trouve_bien_les_ecrivains_connus():
    """Garde-fou du garde-fou : si le balayage ne trouve plus rien, tous les
    tests suivants passeraient en ne verifiant RIEN.
    ⭐⭐ UN CONTROLE QUI NE TROUVE PLUS SON SUJET NE DIT PAS « JE NE SAIS PAS »,
    IL DIT « TOUT VA BIEN » — c'est exactement le defaut d'`etat_reel.py` §0."""
    trouves = _modules_qui_declarent_un_archive_header()
    assert "chain_run" in trouves, "l'ecriture quotidienne a disparu du balayage"
    assert "wallet_scan" in trouves, "le scan profond a disparu du balayage"
    assert len(trouves) >= 2


def test_TOUS_les_ARCHIVE_HEADER_du_depot_sont_IDENTIQUES():
    """LE TEST CENTRAL. Deux ecrivains du meme fichier, un seul format."""
    trouves = _modules_qui_declarent_un_archive_header()
    distincts = {tuple(v) for v in trouves.values()}
    assert len(distincts) == 1, (
        "ARCHIVE_HEADER divergent dans le meme depot :\n"
        + "\n".join(f"    scraper/{m}.py  ({len(e)} col.)  {e}"
                    for m, e in sorted(trouves.items()))
        + "\n➡️ Les deux ecrivent LE MEME fichier d'archive. Corriger les DEUX, "
          "ou aucun.")


@pytest.mark.parametrize("module", sorted(_modules_qui_declarent_un_archive_header()))
def test_les_dix_premieres_colonnes_ne_bougent_jamais(module):
    """⛔ CONTRAT INTER-DEPOTS. `merge_transfers` lit par POSITION : une colonne
    inseree au milieu ne leve aucune erreur chez lui, elle DECALE les valeurs —
    dans un autre depot, et plus tard.
    ⭐⭐ UN FORMAT PARTAGE PAR TROIS DEPOTS NE SE MODIFIE QU'EN FIN : CE QUI LIT
    PAR POSITION NE SE PLAINT JAMAIS, IL SE DECALE."""
    entete = _modules_qui_declarent_un_archive_header()[module]
    assert entete[:10] == DIX_PREMIERES_HISTORIQUES, (
        f"scraper/{module}.py : les 10 premieres colonnes ont bouge.\n"
        f"    attendu {DIX_PREMIERES_HISTORIQUES}\n"
        f"    obtenu  {entete[:10]}")
    assert len(entete) == len(set(entete)), f"colonne en double dans {module}"


def test_les_deux_ecrivains_produisent_une_LIGNE_de_meme_longueur():
    """⭐⭐⭐ MEME EN-TETE NE VEUT PAS DIRE MEME LIGNE. Les deux modules
    construisent leur ligne dans DEUX fonctions differentes : `chain_run`
    l'ecrit inline, `wallet_scan` a `_archive_row`. Comparer les en-tetes ne dit
    rien de ce qui est ECRIT dessous — et une en-tete allongee au-dessus de
    lignes restees courtes est le pire cas : le fichier s'ouvre, se lit, et
    decale une colonne sur deux."""
    import datetime as _dt

    from scraper import wallet_scan as ws
    from scraper import chain_run as cr
    from scraper import collectchain as cc

    brut = {
        "timestamp": "2026-07-09T12:00:00.000000Z",
        "block_number": 1234, "log_index": 5, "transaction_hash": "0xdead",
        "from": {"hash": "0xaaa"}, "to": {"hash": "0xbbb"},
        "total": {"token_id": "424242", "token_instance": {
            "image_url": "x/comic_cover.11111111-2222-3333-4444-"
                         "555555555555.a.webp",
            "metadata": {"edition": 12, "name": "Un comic"}}}}

    ligne_scan = ws._archive_row(brut, _dt.datetime(2026, 7, 9, 12, 0, 0),
                                 "2026-07-09", "0xaaa", "0xbbb")
    assert len(ligne_scan) == len(ws.ARCHIVE_HEADER), (
        f"wallet_scan : {len(ligne_scan)} champs pour "
        f"{len(ws.ARCHIVE_HEADER)} colonnes")

    # chain_run ecrit sa ligne inline : on la releve par le fichier produit.
    import csv
    import gzip
    import tempfile
    d = tempfile.mkdtemp()
    os.environ["CHAIN_ARCHIVE"] = "true"
    os.environ["CHAIN_ARCHIVE_DIR"] = d
    try:
        cr._archive_records([cc._flatten(brut)], "2000-01-01")
        f = [x for x in os.listdir(d) if x.endswith(".csv.gz")][0]
        with gzip.open(os.path.join(d, f), "rt", encoding="utf-8") as fh:
            lignes = list(csv.reader(fh))
    finally:
        os.environ.pop("CHAIN_ARCHIVE_DIR", None)

    assert len(lignes[1]) == len(ligne_scan), (
        f"les deux ecrivains ne produisent pas le meme nombre de champs : "
        f"chain_run {len(lignes[1])}, wallet_scan {len(ligne_scan)}")
    # et la valeur cle arrive au meme endroit dans les deux
    i = ws.ARCHIVE_HEADER.index("token_id")
    assert ligne_scan[i] == "424242"
    assert lignes[1][i] == "424242"
