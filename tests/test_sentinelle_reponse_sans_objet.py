# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_sentinelle_reponse_sans_objet.py
"""🕳️ LA REPONSE QUI ARRIVE ET NE PORTE RIEN (06/08/2026, lot 81).

⭐⭐ CE QUE CE BANC ATTRAPE, ET QU'AUCUN AUTRE N'ATTRAPAIT.
`test_sentinelle_refus_champ` couvre le HTTP 400 (« Invalid request. ») depuis
le lot 76. Mais GraphQL ne se sert pas du code HTTP pour dire « je n'ai pas cet
objet » : il rend **200** et met `errors[]` dans le corps. Mesure du 06/08
contre l'API VeVe, les deux cas cote a cote :

    identifiant inconnu -> HTTP 200 + errors[] « Entity not found »
    champ inexistant    -> HTTP 400 « Invalid request. »

Le premier etait compte comme un SUCCES. C'est ainsi qu'un run pouvait perdre
des items en imprimant `🟢 veve_graphql 7130 requete(s) — RAS`.

⛔ CE BANC DOIT TOMBER SI ON REMET `absent` DANS `ok`, ET AUSSI SI ON LE RANGE
AVEC LES REFUS. Les trois seaux repondent a trois gestes opposes : ralentir,
corriger la requete, aller voir si l'item existe encore. Un banc qui n'exige
que « ce n'est pas ok » laisserait passer la fusion des deux autres.
"""
import pytest

from scraper import sentinelle_sources as ss


def _sentinelle(n_absent=0, n_ok=0, n_refus=0):
    s = ss.Sentinelle()
    for _ in range(n_absent):
        s.noter("veve_graphql", 200, absent=True)
    for _ in range(n_ok):
        s.noter("veve_graphql", 200)
    for _ in range(n_refus):
        s.noter("veve_graphql", 429)
    return s


def test_un_200_sans_objet_n_est_pas_un_succes():
    s = _sentinelle(n_absent=10)
    d = s.obs["veve_graphql"]
    assert d["absent"] == 10
    assert d["ok"] == 0, ("une reponse sans objet comptee dans `ok` : c'est "
                          "exactement le silence qu'on repare")
    assert d["total"] == 10


def test_l_absence_ne_se_range_pas_avec_les_refus():
    """⛔ Un 429 dit « ralentis ». Une absence dit « ton identifiant a
    derive ». Les additionner ferait ralentir un run qui n'a aucun probleme
    de debit — et masquerait le vrai defaut."""
    s = _sentinelle(n_absent=40)
    assert s.obs["veve_graphql"]["repousse"] == 0
    assert s.verdict("veve_graphql") != "se_ferme"
    assert s.pause_conseillee("veve_graphql") == 0.0


def test_le_releve_ne_peut_plus_dire_RAS():
    """⭐⭐ LE DEFAUT ETAIT UNE PHRASE, PAS UN CHIFFRE. Le compteur pouvait
    exister sans que personne ne le lise ; c'est la ligne du log qui mentait."""
    s = _sentinelle(n_absent=3, n_ok=40)
    texte = s.resume()
    assert "RAS" not in texte, texte
    assert "SANS OBJET" in texte
    assert "3" in texte


def test_une_absence_totale_crie_sans_attendre_un_echantillon():
    """⭐ Meme raisonnement que `REFUS_ABSOLU` : 5 reponses vides sur 5, ce
    n'est pas un echantillon insuffisant, c'est qu'on demande les mauvais
    identifiants. Aucun run n'atteindrait MIN_OBS pour le dire."""
    s = _sentinelle(n_absent=ss.REFUS_ABSOLU)
    assert s.absence_criante("veve_graphql")
    crier, texte = s.doit_crier()
    assert crier
    assert "sans rendre d'objet" in texte


def test_un_peu_d_absence_dans_un_gros_run_ne_crie_pas():
    """⛔ Quelques items retires du store, c'est la vie normale d'un
    catalogue. Un garde-fou qui crie tous les jours est un garde-fou qu'on
    finit par ne plus lire."""
    s = _sentinelle(n_absent=2, n_ok=200)
    assert not s.absence_criante("veve_graphql")
    assert s.doit_crier()[0] is False


def test_les_deux_causes_restent_deux_paragraphes():
    """⭐⭐ « on nous repousse » et « la source n'a pas l'objet » demandent des
    gestes opposes. Fondues en un message, la premiere ferait chercher un
    blocage la ou il y a un item retire."""
    s = _sentinelle(n_absent=60, n_refus=60)
    crier, texte = s.doit_crier()
    assert crier
    assert "repousse" in texte and "sans rendre d'objet" in texte
    assert texte.index("repousse") < texte.index("sans rendre d'objet")


def test_noter_reponse_transporte_l_absence():
    """⛔ Le cablage compte autant que le compteur : `noter_reponse` est le
    seul point d'entree des collecteurs. S'il perd le drapeau, le seau reste
    vide et le releve redevient vert."""
    class Reponse:
        status_code = 200

    ss.SENTINELLE.obs.clear()
    ss.noter_reponse("src", Reponse(), absent=True)
    assert ss.SENTINELLE.obs["src"]["absent"] == 1
    assert ss.SENTINELLE.obs["src"]["ok"] == 0
    ss.SENTINELLE.obs.clear()
