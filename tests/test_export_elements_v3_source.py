# ⚠️ DEPOT : VeVePreda/scrapeur-veve
# CHEMIN : tests/test_export_elements_v3_source.py

"""La 18e colonne : la PROVENANCE de la ligne (`source`).

Defaut reel corrige ici (28/07/2026). `combler_depuis_officiel` recopiait les
lignes du tracker DANS elements_v3.csv telles quelles : une fois dedans, plus
rien ne disait d'ou elles venaient. Consequences mesurees :

  1. la couverture chaine ne pouvait qu'etre ESTIMEE, par une empreinte
     indirecte (les doubles espaces des noms du tracker) ;
  2. la doctrine du 28/07 etait INAPPLICABLE. Elle dit : la chaine fait autorite
     Y COMPRIS PAR SON SILENCE — mais seulement sur les objets qu'elle a VUS.
     Cas reel : `Robocop: Jetpack Edition` portait `edition_type=FE` au tracker
     et RIEN a la chaine ; faute de savoir si la chaine l'avait vu, la regle
     « une valeur vide ne remplace jamais » a conserve l'erreur.

⭐ La regle centrale de ce fichier : on n'ecrit `source` QUE la ou on SAIT.
L'inconnu s'ecrit "" et ne se devine pas — c'est la meme discipline que le
comblage de `series`, et la meme lecon que `verifier_churn`.
"""
import collections
import csv

import pytest

from scraper.export_elements_v3 import (
    ENTETE, OFFCHAIN_COLS, SRC_CHAINE, SRC_INCONNU, SRC_TRACKER, VOCAB_SOURCE,
    appliquer_backfill_source, balayage_integral, charger_backfill_source,
    charger_graine, combler_depuis_officiel, combler_series, compter_sources,
    construire_v3, ecrire, fusion, reattacher_offchain, resoudre_source_inconnue,
    valider_sources,
)

SEIZE = ["veve_uuid", "series_uuid", "name", "category", "rarity",
         "edition_type", "supply", "first_public", "listings", "note",
         "brand", "licensor", "atl", "atl_date", "ath", "ath_date"]

I_SRC = ENTETE.index("source")


def brut(uid, cat="comic", **kw):
    d = {"veve_uuid": uid, "category": cat, "name": "Storm Vol. 5 #2",
         "rarity": "COMMON", "edition_type": "1", "supply": 1000,
         "brand": "Storm Vol. 5", "licensor": "Marvel", "series": "Storm Vol. 5"}
    d.update(kw)
    return d


def off(uid, **kw):
    """Une ligne de l'officiel (elements.csv) : 16 colonnes, PAS de `source`."""
    d = dict.fromkeys(SEIZE, "")
    d.update(veve_uuid=uid, category="collectible", name="Robocop: Jetpack",
             rarity="RARE", edition_type="FE", brand="Robocop")
    d.update(kw)
    return d


def ligne_heritee(uid, cat="comic"):
    """Ligne de GRAINE ecrite AVANT le 28/07 : ni `series`, ni `source`."""
    r = dict.fromkeys(SEIZE, "")
    r.update(veve_uuid=uid, category=cat, brand="Storm Vol. 5",
             name="Storm Vol. 5 #1 (2024)")
    return [r[c] for c in SEIZE]


# --- l'en-tete -------------------------------------------------------------

def test_source_ajoutee_en_FIN_sans_toucher_a_ce_qui_precede():
    # Meme discipline que `series` : les colonnes ANTERIEURES ne bougent pas
    # d'un octet, parce que `reattacher_offchain` indexe par POSITION.
    assert ENTETE[:16] == SEIZE
    assert ENTETE[16] == "series"
    assert ENTETE[-1] == "source" and len(ENTETE) == 18


def test_les_index_offchain_restent_valides():
    for c in OFFCHAIN_COLS:
        assert ENTETE.index(c) == SEIZE.index(c)


# --- qui pose quelle provenance --------------------------------------------

def test_une_ligne_moissonnee_est_marquee_chaine():
    rows = construire_v3({"u1": brut("u1")}, {})
    assert rows[0][I_SRC] == SRC_CHAINE


def test_une_ligne_reprise_de_lofficiel_est_marquee_tracker():
    rows = combler_depuis_officiel([], {"u9": off("u9")})
    assert rows[0][I_SRC] == SRC_TRACKER


def test_le_tracker_ne_peut_PAS_se_faire_passer_pour_la_chaine():
    # ⭐ Le piege exact : l'officiel n'a pas de colonne `source`, donc une
    # recopie naive (`r.get("source", "")`) donnerait "" — l'INCONNU — et on
    # perdrait precisement l'information pour laquelle la colonne existe.
    # Et si un jour l'officiel en portait une, elle ne doit pas faire foi.
    rows = combler_depuis_officiel([], {"u9": off("u9", source=SRC_CHAINE)})
    assert rows[0][I_SRC] == SRC_TRACKER


def test_le_comblage_ne_retouche_pas_une_ligne_deja_vue():
    chaine = construire_v3({"u1": brut("u1")}, {})
    rows = combler_depuis_officiel(chaine, {"u1": off("u1")})
    assert len(rows) == 1
    assert rows[0][I_SRC] == SRC_CHAINE      # jamais retrogradee


def test_une_ligne_tracker_devient_chaine_des_que_la_chaine_la_voit():
    # Auto-cicatrisant : le run courant fait foi pour un uuid revu (`fusion`).
    graine = {"u1": combler_depuis_officiel([], {"u1": off("u1")})[0]}
    assert graine["u1"][I_SRC] == SRC_TRACKER
    rows = fusion(construire_v3({"u1": brut("u1")}, {}), graine)
    assert len(rows) == 1 and rows[0][I_SRC] == SRC_CHAINE


# --- l'inconnu ne se devine pas --------------------------------------------

def test_une_ligne_heritee_reste_INCONNUE():
    # Sa provenance n'est plus reconstituable : ni l'archive CollectChain locale
    # (elle repond « trade recemment », pas « moissonne » : 358 faux positifs
    # mesures le 28/07), ni les empreintes tracker (23 lignes sur 19 261) ne
    # savent trancher. On n'invente rien : c'est une moisson complete qui
    # resoudra, par elimination.
    r = ligne_heritee("u1")
    combler_series([r])                       # allonge a la largeur de l'entete
    assert r[I_SRC] == SRC_INCONNU


def test_une_graine_sans_colonne_source_se_relit_en_inconnu(tmp_path):
    p = tmp_path / "graine.csv"
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(SEIZE)
        w.writerow(ligne_heritee("u1"))
    (r,) = charger_graine(str(p)).values()
    assert r[I_SRC] == SRC_INCONNU


def test_une_source_deja_ecrite_nest_jamais_ecrasee_par_le_comblage_de_serie():
    r = ligne_heritee("u1") + ["", SRC_CHAINE]
    combler_series([r])
    assert r[I_SRC] == SRC_CHAINE


# --- lever l'inconnu, par elimination et seulement alors -------------------

@pytest.mark.parametrize("swept,depart,attendu", [
    (True,  None,             True),   # parti du sommet ET arrive au bout
    (True,  {"block": 1234},  False),  # ⭐ profond : « swept » du BAS seulement
    (False, None,             False),  # budget-temps / plateau / plafond
    (False, {"block": 1234},  False),
])
def test_seul_un_run_parti_du_sommet_et_arrive_au_bout_est_integral(
        swept, depart, attendu):
    # LE piege : `swept` seul ne prouve rien. Un `profond` REPREND au curseur et
    # peut finir « swept » en n'ayant vu que le bas de l'histoire.
    assert balayage_integral({"swept": swept}, depart) is attendu


def test_apres_un_balayage_integral_linconnu_connu_de_lofficiel_est_tracker():
    # ⭐ La sortie de crise : un balayage complet n'a pas produit cet uuid, or
    # l'officiel le porte -> sa ligne v3 vient du tracker. Prouve, pas devine.
    r = ligne_heritee("u1")
    combler_series([r])
    assert resoudre_source_inconnue([r], {"u1": off("u1")}) == 1
    assert r[I_SRC] == SRC_TRACKER


def test_un_inconnu_des_DEUX_reste_inconnu():
    # 168 uuid ne sont connus QUE de la chaine (mesure du 28/07). Absents de
    # l'officiel, ils ne peuvent pas venir du tracker — mais on ne les baptise
    # pas `chaine` pour autant : on ne comble jamais un trou par une supposition.
    r = ligne_heritee("u1")
    combler_series([r])
    assert resoudre_source_inconnue([r], {}) == 0
    assert r[I_SRC] == SRC_INCONNU


def test_lelimination_ne_retouche_pas_une_provenance_deja_connue():
    rows = construire_v3({"u1": brut("u1")}, {})
    assert resoudre_source_inconnue(rows, {"u1": off("u1")}) == 0
    assert rows[0][I_SRC] == SRC_CHAINE


# --- le rattrapage de l'herite (instantane du 28/07/2026) ------------------

def _table(tmp_path, lignes, gz=True):
    import gzip as _gz
    p = tmp_path / ("t.csv.gz" if gz else "t.csv")
    ouvre = _gz.open if gz else open
    with ouvre(p, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["veve_uuid", "source"])
        w.writerows(lignes)
    return str(p)


def test_le_rattrapage_pose_la_provenance_des_lignes_heritees(tmp_path):
    r1, r2 = ligne_heritee("u1"), ligne_heritee("u2")
    combler_series([r1, r2])
    t = charger_backfill_source(
        _table(tmp_path, [("u1", SRC_CHAINE), ("u2", SRC_TRACKER)]))
    assert appliquer_backfill_source([r1, r2], t) == {SRC_CHAINE: 1,
                                                     SRC_TRACKER: 1}
    assert r1[I_SRC] == SRC_CHAINE and r2[I_SRC] == SRC_TRACKER


def test_le_rattrapage_n_EXTRAPOLE_pas():
    # ⛔ La table est un INSTANTANE de lignes precises, pas la regle « tout ce
    # qui n'y est pas vient du tracker ». Sinon une graine restauree d'une
    # vieille sauvegarde se ferait massivement estampiller en silence.
    r = ligne_heritee("u_absent_de_la_table")
    combler_series([r])
    assert appliquer_backfill_source([r], {"u1": SRC_CHAINE}) == {SRC_CHAINE: 0,
                                                                 SRC_TRACKER: 0}
    assert r[I_SRC] == SRC_INCONNU


def test_le_rattrapage_n_ecrase_jamais_une_provenance_prouvee():
    # La moisson fait foi : si le run a VU l'objet, la table de 28/07 ne peut
    # pas le contredire.
    rows = construire_v3({"u1": brut("u1")}, {})
    assert appliquer_backfill_source(rows, {"u1": SRC_TRACKER}) == {
        SRC_CHAINE: 0, SRC_TRACKER: 0}
    assert rows[0][I_SRC] == SRC_CHAINE


def test_le_rattrapage_est_idempotent(tmp_path):
    r = ligne_heritee("u1")
    combler_series([r])
    t = charger_backfill_source(_table(tmp_path, [("u1", SRC_CHAINE)]))
    assert appliquer_backfill_source([r], t)[SRC_CHAINE] == 1
    assert appliquer_backfill_source([r], t)[SRC_CHAINE] == 0


@pytest.mark.parametrize("gz", [True, False])
def test_la_table_se_lit_gzippee_ou_non(tmp_path, gz):
    assert charger_backfill_source(
        _table(tmp_path, [("u1", SRC_CHAINE)], gz)) == {"u1": SRC_CHAINE}


def test_une_table_absente_ne_casse_rien_et_DIT_ou_elle_a_cherche(capsys):
    # ⭐ Un module qui reclame un fichier sans dire lequel a deja coute un 1er
    # run en echec (lecon du 28/07 sur le corpus Medium).
    assert charger_backfill_source("/introuvable/table.csv.gz") == {}
    assert "/introuvable/table.csv.gz" in capsys.readouterr().err


def test_une_valeur_hors_vocabulaire_dans_la_table_est_IGNOREE(tmp_path):
    t = charger_backfill_source(_table(tmp_path, [("u1", "on-chain"),
                                                  ("u2", SRC_CHAINE)]))
    assert t == {"u2": SRC_CHAINE}


def test_la_vraie_table_livree_est_coherente():
    """Le fichier EMBARQUE dans le lot, pas une invention de test."""
    import pathlib
    p = (pathlib.Path(__file__).resolve().parents[1]
         / "data" / "source_backfill_2026-07-28.csv.gz")
    if not p.exists():                      # depot sans la donnee : on n'echoue pas
        pytest.skip("table de rattrapage absente du depot")
    t = charger_backfill_source(str(p))
    n = collections.Counter(t.values())
    assert len(t) == 7794, "l'instantane porte les 7 794 lignes INCONNUES du run #14"
    assert n[SRC_CHAINE] == 7658 and n[SRC_TRACKER] == 136
    assert all(len(u) == 36 and u == u.lower() for u in t)


# --- les garde-fous ---------------------------------------------------------

def test_valider_sources_refuse_une_provenance_inventee():
    # Une provenance inventee serait PIRE que pas de provenance : c'est elle qui
    # autorisera la chaine a effacer un champ du tracker (autorite du silence).
    r = construire_v3({"u1": brut("u1")}, {})[0]
    r[I_SRC] = "on-chain"
    with pytest.raises(ValueError):
        valider_sources([r])


def test_le_vocabulaire_est_ferme():
    assert set(VOCAB_SOURCE) == {SRC_CHAINE, SRC_TRACKER, SRC_INCONNU}


def test_compter_sources_donne_la_couverture_exacte():
    # ⭐ Ce que la colonne apporte vraiment : un chiffre MESURE la ou il fallait
    # jusqu'ici l'estimer par les doubles espaces des noms du tracker.
    rows = construire_v3({"u1": brut("u1"), "u2": brut("u2")}, {})
    rows = combler_depuis_officiel(rows, {"u9": off("u9")})
    rows.append(ligne_heritee("u8"))
    combler_series(rows)
    assert compter_sources(rows) == {SRC_CHAINE: 2, SRC_TRACKER: 1,
                                     SRC_INCONNU: 1}


def test_reattacher_offchain_ne_touche_pas_a_la_source():
    r = construire_v3({"u1": brut("u1")}, {})[0]
    reattacher_offchain([r], {"u1": {c: f"<{c}>" for c in OFFCHAIN_COLS}})
    assert r[I_SRC] == SRC_CHAINE


# --- le point de passage unique --------------------------------------------

def test_ecrire_produit_la_colonne_et_les_16_premieres_intactes(tmp_path):
    p = tmp_path / "v3.csv"
    rows = construire_v3({"u1": brut("u1")}, {})
    rows = combler_depuis_officiel(rows, {"u9": off("u9")})
    ecrire(rows, str(p))
    lu = {r["veve_uuid"]: r for r in csv.DictReader(p.open(encoding="utf-8"))}
    assert list(lu["u1"].keys())[:16] == SEIZE
    assert lu["u1"]["source"] == SRC_CHAINE
    assert lu["u9"]["source"] == SRC_TRACKER


def test_ecrire_refuse_decrire_une_provenance_inventee(tmp_path):
    p = tmp_path / "v3.csv"
    r = construire_v3({"u1": brut("u1")}, {})[0]
    r[I_SRC] = "chaîne"                       # accent : pas le vocabulaire
    with pytest.raises(ValueError):
        ecrire([r], str(p))
    assert not p.exists()                     # rien d'ecrit, meme partiellement


def test_ecrire_imprime_la_couverture(tmp_path, capsys):
    p = tmp_path / "v3.csv"
    rows = combler_depuis_officiel(construire_v3({"u1": brut("u1")}, {}),
                                   {"u9": off("u9")})
    ecrire(rows, str(p))
    sortie = capsys.readouterr().out
    assert "source" in sortie and "chaine=1" in sortie and "tracker=1" in sortie


# --- de bout en bout, comme la machine -------------------------------------

def _uid(n):
    return f"00000000-0000-0000-0000-{n:012d}"


U_CHAINE = _uid(1)


def _tr(n):
    return {"block_number": 1, "log_index": n, "timestamp": "2026-07-28T00:00:00Z",
            "total": {"token_instance": {
                "image_url": f"x/collectible_type_image.{_uid(n)}.z.full.jpeg",
                "metadata": {"name": f"C{n}", "rarity": "Common",
                             "editionType": "FA", "totalEditions": 1,
                             "brand": "B", "licensor": "L", "series": "S"}}}}


class _FauxCC:
    """Chaine bidon paginee par `params['p']` : deux pages, puis plus rien.

    Deux pages, et non une : il faut qu'une REPRISE au curseur (`p=1`) ait
    encore de la matiere, sinon le test du piege ne testerait que le vide.
    """
    TRANSFERS_URL = "x"
    PAUSE_BETWEEN_PAGES = 0
    PAGES = [[_tr(n) for n in range(1, 61)], [_tr(61)]]

    def _session(self):
        return None

    def _parse_ts(self, x):
        return None

    def _get(self, session, url, params):
        i = (params or {}).get("p", 0)
        if i >= len(self.PAGES):
            return {"items": []}
        nxt = {"p": i + 1} if i + 1 < len(self.PAGES) else None
        return {"items": self.PAGES[i], "next_page_params": nxt}


def _decor(tmp_path, monkeypatch, mode, state=None):
    """Une graine HERITEE (16 colonnes) + un officiel, et le module cable dessus."""
    import sys
    import scraper
    import scraper.export_elements_v3 as v3

    graine = tmp_path / "v3.csv"
    with graine.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(SEIZE)
        w.writerow(ligne_heritee("u_vieux"))     # heritee ET dans l'officiel
        w.writerow(ligne_heritee("u_orphelin"))  # heritee, INCONNUE de l'officiel
    officiel = tmp_path / "elements.csv"
    with officiel.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(SEIZE)
        for uid in ("u_vieux", "u_dormant"):
            w.writerow([off(uid)[c] for c in SEIZE])
    st = tmp_path / "state.json"
    if state is not None:
        st.write_text(__import__("json").dumps(state), encoding="utf-8")

    faux = _FauxCC()
    monkeypatch.setitem(sys.modules, "scraper.collectchain", faux)
    monkeypatch.setattr(scraper, "collectchain", faux, raising=False)
    monkeypatch.setattr(v3, "CSV_V3", str(graine))
    monkeypatch.setattr(v3, "CSV_OFFICIEL", str(officiel))
    monkeypatch.setattr(v3, "STATE_V3", str(st))
    # hermetique : le bout-en-bout teste l'ELIMINATION, pas la table du 28/07.
    monkeypatch.setattr(v3, "BACKFILL_SOURCE", str(tmp_path / "pas_de_table.csv.gz"))
    monkeypatch.setenv("ELEMENTS_V3_MODE", mode)
    monkeypatch.setenv("ELEMENTS_V3_ACCUMULATE", "1")
    monkeypatch.setenv("ELEMENTS_V3_TIME_BUDGET_MIN", "0")
    return v3, graine


def _lu(chemin):
    return {r["veve_uuid"]: r for r in
            csv.DictReader(open(chemin, encoding="utf-8"))}


def test_bout_en_bout_un_run_integral_tranche_tout_ce_qui_est_prouvable(
        tmp_path, monkeypatch):
    v3, graine = _decor(tmp_path, monkeypatch, "integral")
    assert v3.main() == 0
    lu = _lu(graine)
    assert lu[U_CHAINE]["source"] == SRC_CHAINE       # moissonne ce run
    assert lu["u_dormant"]["source"] == SRC_TRACKER   # repris de l'officiel
    assert lu["u_vieux"]["source"] == SRC_TRACKER     # tranche par elimination
    assert lu["u_orphelin"]["source"] == SRC_INCONNU  # connu de personne : inconnu


def test_bout_en_bout_une_reprise_au_curseur_ne_tranche_RIEN(
        tmp_path, monkeypatch):
    # ⭐ Le piege : ce run finit « swept » (le faux client n'a plus de page) mais
    # il est PARTI DU CURSEUR. Croire son verdict marquerait `tracker` des
    # lignes que la chaine connait tres bien.
    v3, graine = _decor(tmp_path, monkeypatch, "profond",
                        state={"cursor": {"p": 1}, "swept": False})
    assert v3.main() == 0
    lu = _lu(graine)
    assert lu["u_vieux"]["source"] == SRC_INCONNU     # rien n'a ete devine
    assert lu["u_dormant"]["source"] == SRC_TRACKER   # le comblage, lui, SAIT
