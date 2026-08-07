# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_sentinelle_absence.py
"""⭐⭐ LA SENTINELLE DOIT ETRE PLUS FIABLE QUE CE QU'ELLE SURVEILLE.

Un garde-fou qu'on ne teste pas est une croyance. Chaque test ici REPRODUIT un
defaut precis, deja paye ou deja identifie — pas une propriete generale.

⛔ ZERO RESEAU. La `Source` est remplacee par un double : c'est la condition
pour que le banc soit rejouable et rapide, et c'est pour ca que tout le
raisonnement de `sentinelle_absence` est pur.

⭐⭐⭐ UN BANC SE JUGE SUR CE QU'IL LAISSE PASSER. Les trois tests qui comptent
le plus sont ceux qui verifient que la sentinelle **NE CRIE PAS** : une
sentinelle qui crie a tort sur une ligne critique apprend a ignorer exactement
ce qu'il fallait lire, et c'est pire que pas de sentinelle du tout.
"""

from datetime import datetime, timedelta, timezone

import pytest

from scraper import sentinelle_absence as S


MAINTENANT = datetime.now(timezone.utc)


def il_y_a(h):
    return MAINTENANT - timedelta(hours=h)


class SourceFactice:
    """Double de la Source. `erreurs` simule un jeton sans portee (404)."""

    def __init__(self, runs=None, commits=None, releases=None, erreurs=None):
        self.runs = runs or {}
        self.commits = commits or {}
        self.releases = releases or {}
        self.erreurs = erreurs or {}

    def dernier_run_reussi(self, owner, depot, fichier):
        if fichier in self.erreurs:
            return None, self.erreurs[fichier]
        return self.runs.get(fichier), ""

    def dernier_commit(self, owner, depot, chemin):
        return self.commits.get(chemin), ""

    def derniere_release(self, owner, depot, tag):
        return self.releases.get(tag), ""


def entree(**kw):
    base = dict(depot="scrapeur-veve", fichier="daily.yml", cadence="15 2 * * *",
                fenetre_h=36, critique=True, preuve="run", ecrit=[],
                valide_fenetre=False)
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _proprietaires_connus(monkeypatch):
    monkeypatch.setitem(S.PROPRIETAIRE, "scrapeur-veve", "VeVePreda")
    monkeypatch.setitem(S.PROPRIETAIRE, "jetonveve", "fanablefrance")


# ═══════════════════════════════════════════════════════════════════════════
# 1. LE DEFAUT D'ORIGINE — le ledger gele du 24/07 au 07/08, sans run rouge
# ═══════════════════════════════════════════════════════════════════════════
def test_un_hebdo_gele_depuis_deux_semaines_est_vu():
    e = entree(fichier="ledger-writer.yml", fenetre_h=216)
    src = SourceFactice(runs={"ledger-writer.yml": il_y_a(14 * 24)})
    c = S.ausculter(e, src)
    assert c.en_retard, "15 jours de silence sur une fenetre de 9 jours doit crier"
    msg, alarme = S.rapport({c.cle: c}, [e], 0)
    assert alarme and "ledger-writer" in msg


def test_un_workflow_qui_n_a_JAMAIS_tourne_est_vu():
    """⭐⭐⭐ « aucun run » n'est pas « pas de nouvelle depuis peu ». C'est le cas
    d'analytics avant le correctif : jamais declenche, donc jamais rouge."""
    e = entree(fichier="analytics.yml", depot="jetonveve", fenetre_h=216)
    c = S.ausculter(e, SourceFactice(runs={}))
    msg, alarme = S.rapport({c.cle: c}, [e], 0)
    assert alarme and "aucun run reussi" in msg


# ═══════════════════════════════════════════════════════════════════════════
# 2. CE QUI COMPTE LE PLUS : NE PAS CRIER A TORT
# ═══════════════════════════════════════════════════════════════════════════
def test_garde_de_diff_un_workflow_sain_qui_n_ecrit_rien_ne_declenche_RIEN():
    """🔴 12 des 25 crons ne committent que sur diff. Sans changement ils ne
    laissent aucune trace d'ecriture. Les surveiller sur l'ecriture ferait une
    fausse alerte quotidienne sur 5 lignes CRITIQUES."""
    e = entree(fichier="rebuild-daily.yml", depot="scrapeur-veve", preuve="run",
               ecrit=["git:dist/index.html"])
    src = SourceFactice(runs={"rebuild-daily.yml": il_y_a(3)},
                        commits={"dist/index.html": il_y_a(500)})  # fige depuis 20 j
    c = S.ausculter(e, src)
    assert not c.en_retard, "preuve=run ne doit JAMAIS regarder la date d'ecriture"


def test_un_quotidien_en_retard_de_deux_heures_ne_declenche_pas():
    """Retard GitHub : 2 h 20 a 3 h 15 de decalage sont NORMAUX. Une fenetre
    plus serree que la cadence est un generateur de fausses alertes."""
    e = entree(fenetre_h=36)
    c = S.ausculter(e, SourceFactice(runs={"daily.yml": il_y_a(26)}))
    assert not c.en_retard


def test_plusieurs_cibles_c_est_la_PLUS_RECENTE_qui_compte():
    """Exiger que TOUTES bougent ferait crier des qu'une seule des cibles a,
    elle, une garde de diff."""
    e = entree(fichier="floors.yml", preuve="ecriture",
               ecrit=["git:data/floors.csv", "git:data/vieux.csv"])
    src = SourceFactice(runs={"floors.yml": None},
                        commits={"data/floors.csv": il_y_a(2),
                                 "data/vieux.csv": il_y_a(900)})
    c = S.ausculter(e, src)
    assert not c.en_retard


# ═══════════════════════════════════════════════════════════════════════════
# 3. L'AVEUGLEMENT N'EST PAS UNE ABSENCE
# ═══════════════════════════════════════════════════════════════════════════
def test_un_404_de_jeton_ne_se_deguise_pas_en_panne():
    """⭐⭐⭐ Un jeton sans portee rend 404, ce qui ressemble trait pour trait a
    « n'a jamais tourne ». Les confondre produirait 25 fausses alertes le jour
    ou le jeton expire — et masquerait la vraie panne dans le bruit."""
    e = entree()
    c = S.ausculter(e, SourceFactice(erreurs={"daily.yml": "HTTP 404"}))
    assert c.aveugle and not c.en_retard
    msg, alarme = S.rapport({c.cle: c}, [e], 0)
    assert alarme, "l'aveuglement doit alerter"
    assert "je n'ai rien pu lire" in msg and "pas « il n'a pas tourne »" in msg


def test_un_jeton_expire_donne_UNE_ligne_pas_vingt_cinq():
    """⭐⭐⭐ Trouve en repetition a blanc le 07/08 : un 401 rend les 25 lignes
    aveugles d'un coup. Les lister une par une noierait le canal sous 25
    messages identiques — et la vraie panne du lendemain passerait dedans.
    Vingt-cinq symptomes d'une seule cause sont UNE ligne."""
    entrees = [entree(fichier=f"w{i}.yml") for i in range(25)]
    src = SourceFactice(erreurs={f"w{i}.yml": "HTTP 401" for i in range(25)})
    cs = {c.cle: c for c in (S.ausculter(e, src) for e in entrees)}
    msg, alarme = S.rapport(cs, entrees, 0)
    assert alarme
    assert msg.count("⚫") == 1, "une seule ligne noire, pas vingt-cinq"
    assert "UNE cause" in msg and "jeton" in msg


def test_deux_aveugles_isoles_restent_nommes_un_par_un():
    """En dessous du seuil, regrouper ferait perdre l'information utile :
    savoir LEQUEL est illisible."""
    entrees = [entree(fichier="a.yml"), entree(fichier="b.yml")]
    src = SourceFactice(erreurs={"a.yml": "HTTP 404", "b.yml": "HTTP 404"})
    cs = {c.cle: c for c in (S.ausculter(e, src) for e in entrees)}
    msg, _ = S.rapport(cs, entrees, 0)
    assert msg.count("⚫") == 2 and "a.yml" in msg and "b.yml" in msg


def test_un_proprietaire_non_declare_rend_aveugle_et_le_dit(monkeypatch):
    """Le jour ou un depot entre au manifeste sans que son compte soit renseigne,
    il doit dire « je ne sais pas », pas disparaitre ni passer pour sain."""
    monkeypatch.setitem(S.PROPRIETAIRE, "depot-neuf", "?")
    e = entree(depot="depot-neuf", fichier="quelquechose.yml")
    c = S.ausculter(e, SourceFactice())
    assert "proprietaire" in c.aveugle


# ═══════════════════════════════════════════════════════════════════════════
# 4. L'ORDRE — l'age ne suffit pas
# ═══════════════════════════════════════════════════════════════════════════
def test_un_consommateur_plus_vieux_que_son_producteur_crie_meme_si_les_deux_sont_frais():
    """⭐⭐⭐ LE CAS QUE PERSONNE NE VOIT. ledger-writer (jeudi) tourne AVANT
    l'analytics de la semaine : les deux sont dans leur fenetre, les deux runs
    sont verts, et le ledger est ecrit depuis un derive perime."""
    prod = entree(depot="jetonveve", fichier="analytics.yml", fenetre_h=216)
    conso = entree(fichier="ledger-writer.yml", fenetre_h=216,
                   depend_de=["jetonveve/analytics.yml"])
    src = SourceFactice(runs={"analytics.yml": il_y_a(2),
                              "ledger-writer.yml": il_y_a(30)})
    cs = {c.cle: c for c in (S.ausculter(prod, src), S.ausculter(conso, src))}
    assert not any(c.en_retard for c in cs.values()), "les deux sont bien frais"
    d = S.desordres(cs, [prod, conso])
    assert d, "et pourtant l'ordre est faux"
    msg, alarme = S.rapport(cs, [prod, conso], 0)
    assert alarme and "avec un run vert" in msg


def test_l_ordre_correct_ne_declenche_rien():
    prod = entree(depot="jetonveve", fichier="analytics.yml", fenetre_h=216)
    conso = entree(fichier="ledger-writer.yml", fenetre_h=216,
                   depend_de=["jetonveve/analytics.yml"])
    src = SourceFactice(runs={"analytics.yml": il_y_a(40),
                              "ledger-writer.yml": il_y_a(2)})
    cs = {c.cle: c for c in (S.ausculter(prod, src), S.ausculter(conso, src))}
    assert not S.desordres(cs, [prod, conso])


# ═══════════════════════════════════════════════════════════════════════════
# 5. ELLE PARLE MEME QUAND TOUT VA BIEN, ET ELLE DIT CE QU'ELLE IGNORE
# ═══════════════════════════════════════════════════════════════════════════
def test_RAS_produit_quand_meme_un_message():
    """Une sentinelle morte ne poste rien, ce qui est indistinguable de « tout
    va bien ». Sans battement quotidien, son propre silence rassure."""
    e = entree()
    c = S.ausculter(e, SourceFactice(runs={"daily.yml": il_y_a(3)}))
    msg, alarme = S.rapport({c.cle: c}, [e], 0)
    assert not alarme and msg.startswith("🟢")


def test_les_angles_morts_sont_annonces_tous_les_jours():
    """⭐⭐⭐ Un manifeste a moitie rempli qui ne le dit pas est pire qu'un vide :
    complet, il devient credible, donc jamais relu."""
    e = entree(preuve="run")
    c = S.ausculter(e, SourceFactice(runs={"daily.yml": il_y_a(3)}))
    msg, _ = S.rapport({c.cle: c}, [e], non_validees=25)
    assert "25 fenetre(s) jamais validee(s)" in msg
    assert "« fini », pas « avance »" in msg


def test_une_cible_illisible_est_nommee_pas_ignoree():
    """Le manifeste v0 porte des miettes de shell tirees des YAML
    ("release:--clobber"). Les sauter en silence laisserait un workflow
    surveille sur RIEN, en ayant l'air surveille."""
    e = entree(fichier="floors.yml", preuve="ecriture",
               ecrit=["release:--clobber", "git:data/floors.csv"])
    src = SourceFactice(runs={"floors.yml": il_y_a(2)},
                        commits={"data/floors.csv": il_y_a(2)})
    c = S.ausculter(e, src)
    assert c.illisibles == ["release:--clobber"]
    msg, _ = S.rapport({c.cle: c}, [e], 0)
    assert "MAL ECRITE" in msg


def test_le_Sheet_est_HORS_DE_PORTEE_pas_illisible():
    """⭐⭐⭐ 26 cibles sur 100 sont le Sheet, 8 sont Discord : de VRAIES
    ecritures que l'API GitHub ne peut pas voir. Les compter comme « illisibles »
    ferait passer une limite de l'instrument pour une saleté a nettoyer — et on
    passerait un mois a « corriger » un manifeste juste. L'inverse serait pire :
    une vraie erreur rangee au rayon des fatalites ne se corrige jamais."""
    e = entree(fichier="daily.yml", preuve="ecriture", ecrit=["sheet", "git:data/d.csv"])
    src = SourceFactice(runs={"daily.yml": il_y_a(2)}, commits={"data/d.csv": il_y_a(2)})
    c = S.ausculter(e, src)
    assert c.hors_portee == ["sheet"] and c.illisibles == []
    msg, _ = S.rapport({c.cle: c}, [e], 0)
    assert "l'API GitHub ne voit pas" in msg


def test_une_ecriture_peut_atterrir_DANS_UN_AUTRE_DEPOT():
    """⭐⭐⭐ Trouve au premier vrai run (07/08) : `catalogue-export` vit dans
    VeVePreda/scrapeur-veve mais publie sa release dans fanablefrance/jetonveve.
    La chercher chez l'emetteur rend 404 — et un 404 ressemble a « rien publie »,
    donc a une panne, alors que tout va bien."""
    ref, ow, dep = S.destination("catalogue@fanablefrance/jetonveve",
                                 "VeVePreda", "scrapeur-veve")
    assert (ref, ow, dep) == ("catalogue", "fanablefrance", "jetonveve")
    # sans `@`, on reste chez l'emetteur
    assert S.destination("catalogue", "VeVePreda", "scrapeur-veve") \
        == ("catalogue", "VeVePreda", "scrapeur-veve")
    # et la cible reste bien formee aux yeux du classement
    assert S.genre_cible("release:catalogue@fanablefrance/jetonveve") == "release"


def test_un_404_sur_une_cible_BIEN_ECRITE_n_est_pas_une_faute_de_frappe():
    """⛔ Le premier run rangeait les deux 404 de `catalogue-export` parmi les
    cibles « A CORRIGER dans le manifeste ». Le manifeste etait juste : on
    cherchait au mauvais endroit. Confondre les deux envoie reparer ce qui
    marche — et laisse le vrai defaut en place."""
    class SrcKO(SourceFactice):
        def derniere_release(self, owner, depot, tag):
            return None, "HTTP 404"
    e = entree(fichier="catalogue-export.yml", preuve="ecriture",
               ecrit=["release:catalogue", "release:--clobber"])
    c = S.ausculter(e, SrcKO(runs={"catalogue-export.yml": il_y_a(2)}))
    assert c.illisibles == ["release:--clobber"], "la miette de shell, elle, est mal ecrite"
    assert len(c.introuvables) == 1 and "cherche dans" in c.introuvables[0]
    msg, _ = S.rapport({c.cle: c}, [e], 0)
    assert "MAL ECRITE" in msg and "NON TROUVEE" in msg


# ═══════════════════════════════════════════════════════════════════════════
# 6. UN JETON PAR COMPTE — contrainte GitHub, pas confort
# ═══════════════════════════════════════════════════════════════════════════
def test_un_jeton_par_compte_et_un_compte_sans_jeton_est_AVEUGLE_pas_muet():
    """Un PAT fine-grained ne porte que sur UN proprietaire, et les workflows
    surveilles vivent sous deux comptes. Un compte sans jeton doit rendre une
    ligne noire explicite — pas disparaitre du rapport, pas passer pour sain."""
    src = S.Source({"VeVePreda": "jeton-A"})          # rien pour fanablefrance
    d, err = src.dernier_run_reussi("fanablefrance", "jetonveve", "floor-watch.yml")
    assert d is None and "aucun jeton pour le compte fanablefrance" in err

    e = entree(depot="jetonveve", fichier="floor-watch.yml", fenetre_h=6)
    c = S.ausculter(e, src)
    assert c.aveugle and not c.en_retard
    msg, alarme = S.rapport({c.cle: c}, [e], 0)
    assert alarme and "je n'ai rien pu lire" in msg


def test_un_jeton_unique_couvre_tous_les_comptes():
    """Le PAT classique reste accepte : un seul jeton, portee `*`."""
    src = S.Source("jeton-unique")
    assert src._jeton("fanablefrance") == "jeton-unique"
    assert src._jeton("VeVePreda") == "jeton-unique"


@pytest.mark.parametrize("cible,attendu", [
    ("git:data/floors.csv", "git"),
    ("release:catalogue", "release"),
    ("sheet", "hors_portee"),
    ("discord", "hors_portee"),
    ("release:--clobber", "illisible"),
    ("git:2>/dev/null", "illisible"),
    ("data/floors.csv", "illisible"),
    ("git:", "illisible"),
])
def test_lecture_des_cibles(cible, attendu):
    assert S.genre_cible(cible) == attendu
