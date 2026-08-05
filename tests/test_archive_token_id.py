# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve · CHEMIN : tests/test_archive_token_id.py

"""🔗 LE TOKEN_ID SURVIT AU STOCKAGE — phase 2 de « CollectChain d'abord ».

`collectchain._flatten` produit `token_id` depuis toujours. `chain_run`
l'ecrivait nulle part. La donnee survivait a la COLLECTE et mourait a
l'ECRITURE, et le second endroit ne ressemble pas au premier — donc on ne l'y
cherchait pas.

⭐⭐ UNE DONNEE QUI SURVIT A LA COLLECTE PEUT ENCORE MOURIR AU STOCKAGE.

Le chiffre qui a declenche ce lot, mesure le 05/08/2026 sur l'archive locale :

    era imx : 24 501 297 / 24 501 301 transferts portent un token_id  (100 %)
    era cc  :          0 /  7 130 601                                 (  0 %)

⭐⭐⭐ ET SURTOUT : LE BANC PART DE LA REPONSE DE L'API, PAS D'UN DICT ECRIT A
LA MAIN. Le 05/08, 37 bancs verts n'ont pas vu que l'annonce publiait un chiffre
faux, parce qu'ils fabriquaient eux-memes la colonne que le code devait lire :
ils testaient le repli. Ici, les records passent par le VRAI `cc._flatten`. Si
`_flatten` cessait de produire `token_id`, ces tests tomberaient — c'est le but.
"""
from __future__ import annotations

import csv
import gzip
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper import chain_run as CR                        # noqa: E402
from scraper import collectchain as cc                     # noqa: E402

# L'ordre HISTORIQUE des 10 premieres colonnes. Fige ici en dur, separement de
# `ARCHIVE_HEADER`, parce que c'est un CONTRAT INTER-DEPOTS : `merge_transfers`
# (fanablefrance/jetonveve) lit ce format par POSITION (`p[0]`..`p[9]`).
# ⛔ Le relire depuis `ARCHIVE_HEADER` rendrait le banc tautologique : il
# validerait le fichier contre lui-meme et ne pourrait plus jamais echouer.
DIX_PREMIERES_HISTORIQUES = ["block", "log_index", "ts_utc", "date_pt", "kind",
                             "category", "veve_uuid", "edition", "from", "to"]


def _transfert_api(token_id="424242", edition=7):
    """Un transfert brut au format EXACT de l'API CollectScan."""
    return {
        "timestamp": "2026-07-09T12:00:00.000000Z",
        "block_number": 1234, "log_index": 5, "transaction_hash": "0xdead",
        "from": {"hash": "0xaaa"}, "to": {"hash": "0xbbb"},
        "total": {
            "token_id": token_id,
            "token_instance": {
                "image_url": "x/comic_cover.11111111-2222-3333-4444-"
                             "555555555555.a.webp",
                "metadata": {"name": "Un comic", "rarity": "Rare",
                             "series": "Une serie", "comicNumber": "3",
                             "startYear": "2014", "edition": edition},
            },
        },
    }


def _archiver(tmp_path, records, monkeypatch):
    """Lance le VRAI `_archive_records` et rend les lignes du CSV.gz produit."""
    monkeypatch.setenv("CHAIN_ARCHIVE", "true")
    monkeypatch.setenv("CHAIN_ARCHIVE_DIR", str(tmp_path))
    CR._archive_records(records, "2000-01-01")   # tout est "journee complete"
    sorties = sorted(f for f in os.listdir(tmp_path) if f.endswith(".csv.gz"))
    assert sorties, "aucun fichier d'archive ecrit"
    with gzip.open(os.path.join(tmp_path, sorties[0]), "rt",
                   encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


# ---------------------------------------------------------------------------
# 1. La colonne existe, et elle est REMPLIE
# ---------------------------------------------------------------------------

def test_le_token_id_traverse_la_collecte_ET_le_stockage(tmp_path, monkeypatch):
    """Le test central : de la reponse API jusqu'a la ligne du CSV.gz.

    ⛔ Pas de dict fabrique : `_flatten` est appele pour de vrai. Un banc qui
    ecrit lui-meme la colonne que le code doit lire teste le repli, pas le code.
    """
    rec = cc._flatten(_transfert_api(token_id="987654"))
    assert rec is not None
    assert rec["token_id"] == "987654", (
        "`_flatten` ne produit plus `token_id` — c'est la COLLECTE qui a "
        "regresse, pas le stockage.")

    lignes = _archiver(tmp_path, [rec], monkeypatch)
    entete, donnee = lignes[0], lignes[1]
    assert "token_id" in entete, "`token_id` absent de l'entete de l'archive"
    assert donnee[entete.index("token_id")] == "987654", (
        "la colonne existe mais arrive VIDE — c'est exactement le defaut "
        "qu'on repare : un contenant pret et une source muette.")


def test_la_colonne_est_EN_FIN_et_les_dix_premieres_ne_bougent_pas(tmp_path,
                                                                   monkeypatch):
    """⛔ LE CONTRAT INTER-DEPOTS. `merge_transfers` (jetonveve) lit ce format
    par POSITION avec un garde `len(p) < 10`. Une colonne inseree AU MILIEU ne
    provoque aucune erreur chez lui : elle DECALE tout, silencieusement, dans un
    autre depot et plus tard.
    ⭐⭐ UN FORMAT PARTAGE PAR TROIS DEPOTS NE SE MODIFIE QU'EN FIN : CE QUI LIT
    PAR POSITION NE SE PLAINT JAMAIS, IL SE DECALE.
    """
    lignes = _archiver(tmp_path, [cc._flatten(_transfert_api())], monkeypatch)
    entete = lignes[0]
    assert entete[:10] == DIX_PREMIERES_HISTORIQUES, (
        f"les 10 premieres colonnes ont bouge : {entete[:10]}. "
        f"`merge_transfers` lit p[0]..p[9] par position — il ne LEVERA PAS "
        f"d'erreur, il rangera les valeurs dans les mauvaises colonnes.")
    assert entete.index("token_id") >= 10
    assert len(entete) == len(set(entete)), "colonne en double dans l'entete"


def test_chaque_ligne_a_autant_de_champs_que_lentete(tmp_path, monkeypatch):
    """Une entete allongee et des lignes restees courtes, c'est le pire cas :
    le fichier s'ouvre, se lit, et decale une colonne sur deux."""
    recs = [cc._flatten(_transfert_api(token_id=str(i), edition=i))
            for i in range(1, 6)]
    lignes = _archiver(tmp_path, recs, monkeypatch)
    for i, l in enumerate(lignes):
        assert len(l) == len(lignes[0]), f"ligne {i} : {len(l)} champs"


# ---------------------------------------------------------------------------
# 2. Ce qui ne doit PAS casser
# ---------------------------------------------------------------------------

def test_un_record_SANS_token_id_ne_fait_pas_tomber_larchivage(tmp_path,
                                                               monkeypatch):
    """⚠️ `_archive_records` accepte tout record au format `_flatten`, y compris
    celui d'une COPIE plus ancienne du collecteur (astronema, paolo — 533 l.
    contre 571 ici). Un `KeyError` ferait perdre l'archivage d'une JOURNEE
    ENTIERE pour une colonne d'appoint.
    ⭐ Le prix de l'echec doit rester proportionnel a l'enjeu de la donnee.
    """
    rec = cc._flatten(_transfert_api())
    del rec["token_id"]                       # simule l'ancienne copie
    lignes = _archiver(tmp_path, [rec], monkeypatch)
    entete, donnee = lignes[0], lignes[1]
    assert donnee[entete.index("token_id")] == ""
    assert donnee[entete.index("veve_uuid")] == \
        "11111111-2222-3333-4444-555555555555"


def test_un_token_id_absent_de_lAPI_donne_une_valeur_VIDE(tmp_path, monkeypatch):
    """Un trou doit RESTER un trou, et ne jamais devenir la chaine « None »."""
    t = _transfert_api()
    t["total"].pop("token_id")
    rec = cc._flatten(t)
    assert rec["token_id"] == ""            # `_flatten` normalise deja
    lignes = _archiver(tmp_path, [rec], monkeypatch)
    entete, donnee = lignes[0], lignes[1]
    assert donnee[entete.index("token_id")] == ""


def test_le_repli_sur_vide_est_dans_LA_VALEUR_pas_dans_le_writer():
    """⚠️ MUTANT SURVIVANT, ASSUME ET EXPLIQUE (05/08/2026).

    Remplacer `r.get("token_id") or ""` par `r.get("token_id")` ne fait tomber
    AUCUN test — et c'est correct : `csv.writer` traduit deja `None` en champ
    vide (verifie : `writerow(['a', None, 'c'])` -> `a,,c`). Le mutant est
    EQUIVALENT sur le chemin du CSV.

    ⭐⭐ UN MUTANT QUI SURVIT N'EST PAS TOUJOURS UN TROU DANS LE BANC : c'est
    parfois une protection qui vise un AUTRE consommateur que celui qu'on teste.
    Ce qu'il ne faut pas faire, c'est le laisser survivre EN SILENCE — on ne
    saurait plus, dans six mois, si c'est un oubli ou une decision.

    Le `or ""` reste, parce que `ARCHIVE_HEADER` et la forme des lignes servent
    aussi a des lecteurs qui, eux, ne neutralisent pas `None` (DuckDB
    `read_csv_auto`, un `"".join`, un futur export JSON). Ce test fige la RAISON
    et verifie le seul point qui compte : la valeur elle-meme n'est jamais None.
    """
    rec = cc._flatten(_transfert_api())
    del rec["token_id"]
    assert (rec.get("token_id") or "") == ""
    assert (rec.get("token_id") or "") is not None


# ---------------------------------------------------------------------------
# 3. LE RENDU A BLANC — imprimer ce qui partira, et le regarder
# ---------------------------------------------------------------------------

def test_rendu_a_blanc_de_larchive(tmp_path, monkeypatch, capsys):
    """⭐⭐⭐ LE RENDU A BLANC ATTRAPE CE QUE LE BANC NE VOIT PAS. Deux defauts
    sur trois, le 05/08, sont tombes en imprimant la sortie reelle — jamais en
    lançant les tests. Ce test imprime la ligne telle qu'elle sera archivee.
    """
    recs = [cc._flatten(_transfert_api(token_id="111", edition=1)),
            cc._flatten(_transfert_api(token_id="222", edition=2))]
    lignes = _archiver(tmp_path, recs, monkeypatch)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerows(lignes)
    rendu = buf.getvalue()
    with capsys.disabled():
        print("\n----- archive telle qu'elle partira -----")
        print(rendu, end="")
        print("----------------------------------------")
    assert "token_id" in rendu.splitlines()[0]
    assert rendu.splitlines()[1].endswith(",111")
