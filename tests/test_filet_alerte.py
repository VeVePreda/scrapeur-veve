# -*- coding: utf-8 -*-
"""
🔊 LE BANC DU FILET — « AUCUN WORKFLOW NE TOMBE EN SILENCE »
═══════════════════════════════════════════════════════════════════════════════

POURQUOI CE BANC EXISTE (18/08/2026)
────────────────────────────────────
`.github/workflows/filet.yml` surveille les autres workflows par leur `name:`,
recopie dans sa liste `workflows:`. C'est le seul point faible du procede :

    un workflow AJOUTE, ou RENOMME, sort de la surveillance
    sans le moindre signe. Rien ne rougit. Le filet a l'air plein.

⭐⭐⭐ C'est le profil exact du banc muet, applique au filet lui-meme. Ce
fichier est ce qui empeche ca : il croise la liste du filet avec les workflows
REELS du dossier, dans les deux sens.

CE QU'IL VERIFIE, ET POURQUOI CHAQUE POINT
──────────────────────────────────────────
 ① Tout workflow du dossier est COUVERT — par le filet, par sa propre alerte
   Discord, ou par une exemption NOMMEE ici avec sa raison. Trois portes, pas
   de quatrieme.
 ② Aucun nom de la liste du filet n'est ORPHELIN. Un nom qui ne correspond a
   aucun workflow du dossier = un workflow renomme = une surveillance qui vise
   le vide. ⭐ Ce controle-la est celui qui attrape les fautes de frappe.
 ③ Les workflows exemptes « parce qu'ils alertent deja » alertent VRAIMENT.
   ⛔ Une exception ne se declare pas, elle se mesure.
 ④ Le filet declenche sur `failure`, `timed_out` **et `cancelled`** — ET il
   filtre les annulations de moins de 2 minutes. Les deux moities, jamais
   l'une sans l'autre (voir le renversement d'arbitrage plus bas).
 ⑤ La condition est au niveau du JOB, pas de l'etape — un job saute ne
   reserve aucune machine.
 ⑥ Secret absent ⇒ `exit 1`. Sortir en 0 rendrait « je n'ai pas pu prevenir »
   identique a « tout va bien ».

⭐⭐⭐ CE BANC EST JUGE EN LUI INJECTANT LE MAUVAIS CODE.
Chaque controle a, plus bas, un `test_faux_*` qui lui donne un corpus abime et
exige qu'il rougisse. Un controle dont le terme a zero n'est pas atteignable
est vert par construction, et ne prouve rien.

⚠️ CE QU'IL NE PEUT PAS FAIRE
─────────────────────────────
Il ne voit que CE depot. Le filet jumeau de `fanablefrance/jetonveve` a les
memes regles et personne ne les verifie : jetonveve n'a aucun banc, ni meme un
workflow qui en lancerait. C'est un trou connu, pas un oubli.
"""

import glob
import os
import re

import pytest
import yaml

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOSSIER = os.path.join(RACINE, ".github", "workflows")

FILET = "filet.yml"

# ⛔ LES EXEMPTIONS. Une ligne = un fichier + la raison, en clair.
#    `alerte_propre=True` veut dire : « il alerte lui-meme » — et le controle ③
#    va le VERIFIER dans le fichier. Une exception qui cesse d'etre vraie rougit.
EXEMPTES = {
    "sentinelle.yml": (
        True,
        "Alerte deja elle-meme, avec un texte que le filet ne saurait pas "
        "ecrire : si LA SENTINELLE tombe, l'absence d'alerte ne veut plus rien "
        "dire.",
    ),
    "ledger-writer.yml": (
        True,
        "Alerte deja elle-meme (etape « Alerte Discord si echec »).",
    ),
    "alerte-tech-ping.yml": (
        False,
        "C'est le TESTEUR du webhook : il echoue expres quand le secret manque. "
        "L'inscrire dans le filet ferait tomber le filet sur la meme cause, "
        "sans rien apprendre de plus.",
    ),
}

RE_ALERTE_PROPRE = re.compile(
    r"if:\s*(\$\{\{\s*)?(failure\(\)|always\(\))", re.I)
RE_WEBHOOK = re.compile(r"DISCORD[A-Z_]*WEBHOOK|discord\.com/api/webhooks")


# ─────────────────────────────────────────────────────────────────────────────
# LES CONTROLES, ECRITS COMME DES FONCTIONS PURES
# ⭐ Ils prennent un dictionnaire {nom_de_fichier: texte}. C'est ce qui permet
#   de leur donner un corpus ABIME plus bas, et de verifier qu'ils rougissent.
# ─────────────────────────────────────────────────────────────────────────────

def _noms(corpus):
    """{fichier: name:} — un workflow sans `name:` porte le nom de son fichier."""
    out = {}
    for f, txt in corpus.items():
        y = yaml.safe_load(txt) or {}
        out[f] = y.get("name") or f
    return out


def liste_du_filet(corpus):
    y = yaml.safe_load(corpus[FILET])
    on = y.get(True) or y.get("on")
    return list(on["workflow_run"]["workflows"])


def alerte_lui_meme(txt):
    """Une etape conditionnee a l'echec qui touche un webhook Discord."""
    lignes = txt.split("\n")
    for i, l in enumerate(lignes):
        if RE_ALERTE_PROPRE.search(l):
            if RE_WEBHOOK.search("\n".join(lignes[i:i + 30])):
                return True
    return False


def non_couverts(corpus):
    """Les workflows qui tomberaient en silence. ⭐ La liste doit etre VIDE."""
    surveilles = set(liste_du_filet(corpus))
    noms = _noms(corpus)
    manquants = []
    for f in corpus:
        if f == FILET or f in EXEMPTES:
            continue
        if noms[f] not in surveilles:
            manquants.append(f)
    return sorted(manquants)


def noms_orphelins(corpus):
    """Noms surveilles qui ne correspondent a aucun workflow. ⭐ VIDE aussi."""
    reels = set(_noms(corpus).values())
    return sorted(n for n in liste_du_filet(corpus) if n not in reels)


def exemptions_mensongeres(corpus):
    """Exemptes « parce qu'ils alertent » qui n'alertent pas."""
    faux = []
    for f, (alerte, _raison) in EXEMPTES.items():
        if not alerte or f not in corpus:
            continue
        if not alerte_lui_meme(corpus[f]):
            faux.append(f)
    return sorted(faux)


def condition_du_filet(corpus):
    y = yaml.safe_load(corpus[FILET])
    jobs = y["jobs"]
    assert len(jobs) == 1, "le filet doit tenir en un seul job"
    job = list(jobs.values())[0]
    return job.get("if", ""), job


# ─────────────────────────────────────────────────────────────────────────────
# LE CORPUS REEL
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def corpus():
    fichiers = sorted(glob.glob(os.path.join(DOSSIER, "*.yml")) +
                      glob.glob(os.path.join(DOSSIER, "*.yaml")))
    # ⭐ Un banc qui ne trouve pas son sujet doit ECHOUER, pas passer. C'est la
    #   difference entre « verifie » et « n'a rien regarde ».
    assert fichiers, f"aucun workflow lu dans {DOSSIER} — banc sans sujet"
    c = {os.path.basename(f): open(f, encoding="utf-8").read()
         for f in fichiers}
    assert FILET in c, (
        f"{FILET} est absent : le filet n'est pas installe sur ce depot. "
        "⇒ toute panne de ce depot tombe en silence.")
    return c


def test_tous_les_workflows_sont_couverts(corpus):
    """① Aucun workflow ne peut tomber sans que rien ne soit dit."""
    manquants = non_couverts(corpus)
    assert not manquants, (
        "Ces workflows tomberaient EN SILENCE — ni dans la liste `workflows:` "
        f"de {FILET}, ni porteurs de leur propre alerte, ni exemptes : "
        f"{manquants}\n"
        "⇒ ajouter leur `name:` (pas leur nom de fichier) dans "
        f"{FILET}, ou les exempter par ecrit dans EXEMPTES.")


def test_aucun_nom_surveille_dans_le_vide(corpus):
    """② Un nom orphelin = un workflow renomme = une surveillance qui vise le vide."""
    orphelins = noms_orphelins(corpus)
    assert not orphelins, (
        f"{FILET} surveille des noms qui n'existent plus : {orphelins}\n"
        "⇒ un workflow a ete renomme ou supprime. S'il existe encore sous un "
        "autre nom, IL N'EST PLUS SURVEILLE.")


def test_les_exemptions_sont_vraies(corpus):
    """③ Une exception se mesure, elle ne se declare pas."""
    faux = exemptions_mensongeres(corpus)
    assert not faux, (
        f"Exemptes du filet parce qu'ils « alertent deja », mais on ne trouve "
        f"aucune alerte Discord conditionnee a l'echec dedans : {faux}\n"
        "⇒ soit l'etape a ete retiree, soit il faut les remettre dans le filet.")


# ═══════════════════════════════════════════════════════════════════════════════
# 🔴🔴🔴 LE RENVERSEMENT DU 21/08/2026 — `cancelled` DEVIENT OBLIGATOIRE
# ═══════════════════════════════════════════════════════════════════════════════
# CE BANC EXIGEAIT L'INVERSE. Il exigeait que le filet **n'alerte PAS** sur
# `cancelled`, au nom d'une mesure du 18/08 : « les annulations viennent de la
# file de concurrence, pas d'une panne ».
#
# ⛔ CE QUE CETTE REGLE A LAISSE PASSER, LE 19/08 : le « Hub Discord » a ete tue
#   par le `timeout-minutes: 15` de son job. Les 9 modules Discord n'ont pas
#   tourne. Le forum est reste muet toute la journee. Aucune alerte.
#
# 🔑🔑 LE PIEGE : **UN JOB TUE PAR SON `timeout-minutes` CONCLUT `cancelled`,
#   PAS `timed_out`.** La garde `timed_out` visait un etat que ce depot
#   n'atteint pas. ⭐⭐⭐ *Un invariant peut etre parfaitement respecte et
#   repondre a la mauvaise question.*
#
# 📉 LA MESURE QUI TRANCHE (21/08, **1 000 runs**, 28/07 -> 21/08) :
#     success 874 · skipped 118 · failure 6 · **cancelled 1**
#   L'unique annulation est le Hub Discord du 19/08, **15,4 min** = son timeout.
#   **ZERO annulation de file en 25 jours.** L'argument de 18/08 supposait une
#   population qui n'existe plus.
#   ⭐⭐⭐ *Un argument juste ne survit pas a l'usage qu'il n'avait pas prevu.*
#
# ⛔ ET ON NE ROUVRE PAS LA PORTE AU BRUIT : le controle ④bis exige le filtre de
#   duree. Sans lui, le jour ou la file recommencera a annuler, le salon se
#   remplira — et le raisonnement de 18/08 redeviendra vrai.
#   ⇒ **Les deux controles vont ensemble. Retirer l'un rend l'autre nuisible.**

def test_le_filet_alerte_sur_les_bonnes_conclusions(corpus):
    """④ failure, timed_out ET cancelled."""
    cond, _job = condition_du_filet(corpus)
    assert "failure" in cond, "le filet n'alerte pas sur `failure`"
    assert "timed_out" in cond, (
        "le filet n'alerte pas sur `timed_out` — un workflow qui depasse son "
        "temps est une panne")
    assert "cancelled" in cond, (
        "le filet n'alerte pas sur `cancelled`. ⛔ C'est le trou du 19/08 : un "
        "job tue par son `timeout-minutes` conclut `cancelled`, PAS "
        "`timed_out`. Le Hub Discord est mort ainsi, 9 modules muets, zero "
        "alerte. Mesure du 21/08 sur 1 000 runs : 1 seule annulation en 25 "
        "jours, et c'etait celle-la.")


def test_les_annulations_courtes_sont_filtrees(corpus):
    """④bis Le prix a payer pour couvrir `cancelled` : filtrer la FILE.

    ⭐ Ce controle lit le TEXTE du script, pas l'arbre YAML : GitHub Actions ne
    sait pas soustraire deux dates, le filtre ne PEUT donc pas etre dans le
    `if:` du job. Il vit dans le shell, et c'est la qu'on va le chercher.
    """
    txt = corpus[FILET]
    _cond, job = condition_du_filet(corpus)
    brut = "\n".join(st.get("run", "") for st in job.get("steps", []))
    # 🔴🔴 LES COMMENTAIRES DU SHELL SONT RETIRES AVANT TOUTE RECHERCHE.
    # Premier jet de ce controle : il cherchait « exit 0 » dans le script
    # entier. Or le script EXPLIQUE le filtre en commentaire — la phrase
    # « ⭐ `exit 0` : ce n'est pas une panne du filet » suffisait a le
    # satisfaire. J'ai supprime le VRAI `exit 0` et le banc est reste VERT.
    # ⭐⭐⭐ *Un banc qui lit la documentation du sujet au lieu du sujet est
    # vert par construction.* Mesure faite en injectant la faute, le 21/08.
    script = "\n".join(l for l in brut.splitlines()
                       if not l.lstrip().startswith("#"))

    assert "run_started_at" in txt, (
        "le filet ne recoit pas `run_started_at` : il ne peut pas mesurer la "
        "duree du run, donc pas distinguer une annulation de FILE d'un job "
        "tue par son timeout.")
    assert "updated_at" in txt, "le filet ne recoit pas `updated_at`"
    assert '"cancelled"' in script or "'cancelled'" in script, (
        "le script du filet ne traite pas le cas `cancelled` a part — il "
        "posterait un message pour chaque annulation de file.")
    assert "total_seconds" in script, (
        "le filet ne SOUSTRAIT pas les deux dates : il recoit les bornes du "
        "run mais n'en fait rien. Un filtre qui ne mesure pas ne filtre pas.")
    assert "exit 0" in script, (
        "le filet n'a aucune sortie SILENCIEUSE : une annulation courte ferait "
        "soit un message, soit un rouge. Il faut qu'elle ne fasse RIEN.")


def test_la_condition_est_au_niveau_du_job(corpus):
    """⑤ Sinon chaque fin de workflow reussie reserve une machine."""
    cond, job = condition_du_filet(corpus)
    assert cond, (
        "le job du filet n'a pas de `if:` — il demarrerait une machine a "
        "CHAQUE fin de workflow, y compris les ~900 reussites du mois.")
    for st in job.get("steps", []):
        assert "if" not in st, (
            "la condition doit etre sur le JOB, pas sur une etape : une etape "
            "sautee a deja coute sa machine.")


def test_secret_absent_fait_echouer(corpus):
    """⑥ « je n'ai pas pu prevenir » ne doit pas ressembler a « tout va bien »."""
    txt = corpus[FILET]
    bloc = txt.split('if [ -z "${HOOK:-}" ]', 1)
    assert len(bloc) == 2, "le filet ne verifie pas la presence du secret"
    suite = bloc[1].split("fi", 1)[0]
    assert "exit 1" in suite, (
        "secret absent -> le filet sort en 0 : le run resterait vert alors "
        "qu'aucune alerte n'est partie. C'est le banc muet.")
    assert "set -eu" in txt or "set -e" in txt, (
        "sans `set -e`, un python3 qui echoue laisse l'etape verte des qu'une "
        "commande le suit (mesure du 18/08).")


# ─────────────────────────────────────────────────────────────────────────────
# ⭐⭐⭐ LE BANC DU BANC — on lui donne du mauvais code et on exige qu'il morde.
# ⛔ Sans ces cinq-la, rien ne prouve que les six controles ci-dessus peuvent
#   rougir un jour.
# ─────────────────────────────────────────────────────────────────────────────

def _corpus_jouet(noms_surveilles, autres):
    """Un dépôt fabriqué : un filet + les workflows qu'on veut."""
    filet = {
        "name": "Filet — alerte technique",
        "on": {"workflow_run": {"workflows": list(noms_surveilles),
                                "types": ["completed"]}},
        "jobs": {"dire": {
            "if": ("github.event.workflow_run.conclusion == 'failure' || "
                   "github.event.workflow_run.conclusion == 'timed_out' || "
                   "github.event.workflow_run.conclusion == 'cancelled'"),
            "runs-on": "ubuntu-latest",
            "steps": [{"run": 'set -eu\nif [ -z "${HOOK:-}" ]; then\n'
                              '  exit 1\nfi\n'
                              'if [ "$CONCLUSION" = "cancelled" ]; then\n'
                              '  exit 0\nfi\n'}]}}}
    # ⭐ Le jouet doit porter les DEUX moities, sinon la contre-epreuve du
    #   filtre de duree rougirait pour la mauvaise raison.
    filet["jobs"]["dire"]["steps"][0]["env"] = {
        "DEBUT": "${{ github.event.workflow_run.run_started_at }}",
        "FIN": "${{ github.event.workflow_run.updated_at }}"}
    c = {FILET: yaml.safe_dump(filet, allow_unicode=True)}
    for f, nom in autres.items():
        c[f] = yaml.safe_dump(
            {"name": nom, "on": {"schedule": [{"cron": "0 3 * * *"}]},
             "jobs": {"x": {"runs-on": "ubuntu-latest",
                            "steps": [{"run": "echo hi"}]}}},
            allow_unicode=True)
    return c


def test_faux_un_workflow_neuf_non_inscrit_est_vu():
    """Le cas qui arrivera vraiment : quelqu'un ajoute un workflow."""
    c = _corpus_jouet(["Deja la"], {"a.yml": "Deja la", "neuf.yml": "Tout neuf"})
    assert non_couverts(c) == ["neuf.yml"]


def test_faux_un_workflow_renomme_est_vu():
    """Le nom du filet ne bouge pas, le workflow si : les deux controles mordent."""
    c = _corpus_jouet(["Ancien nom"], {"a.yml": "Nouveau nom"})
    assert non_couverts(c) == ["a.yml"]
    assert noms_orphelins(c) == ["Ancien nom"]


def test_faux_une_faute_de_frappe_est_vue():
    c = _corpus_jouet(["VeVe daily sinc"], {"daily.yml": "VeVe daily sync"})
    assert noms_orphelins(c) == ["VeVe daily sinc"]
    assert non_couverts(c) == ["daily.yml"]


def test_faux_une_exemption_qui_ment_est_vue():
    """On exempte un fichier « parce qu'il alerte », et il n'alerte pas."""
    c = _corpus_jouet([], {})
    c["sentinelle.yml"] = yaml.safe_dump(
        {"name": "Sentinelle d'absence", "on": {"schedule": []},
         "jobs": {"v": {"runs-on": "ubuntu-latest",
                        "steps": [{"run": "echo rien"}]}}},
        allow_unicode=True)
    assert exemptions_mensongeres(c) == ["sentinelle.yml"]
    # ... et la meme, honnete, passe :
    c["sentinelle.yml"] = (
        "name: Sentinelle d'absence\n"
        "jobs:\n  v:\n    steps:\n"
        "      - if: ${{ failure() }}\n"
        "        env:\n          HOOK: ${{ secrets.DISCORD_ALERTE_TECH_WEBHOOK }}\n"
        "        run: curl $HOOK\n")
    assert exemptions_mensongeres(c) == []


def test_faux_un_filet_qui_ignore_cancelled_est_vu():
    """⭐ La contre-epreuve du renversement : on RETIRE `cancelled`, ca rougit.

    C'est exactement l'etat du filet avant le 21/08 — celui qui a laisse passer
    la journee muette du 19/08.
    """
    c = _corpus_jouet([], {})
    y = yaml.safe_load(c[FILET])
    y["jobs"]["dire"]["if"] = y["jobs"]["dire"]["if"].replace(
        " || github.event.workflow_run.conclusion == 'cancelled'", "")
    c[FILET] = yaml.safe_dump(y, allow_unicode=True)
    with pytest.raises(AssertionError, match="cancelled"):
        test_le_filet_alerte_sur_les_bonnes_conclusions(c)


def test_faux_un_filet_sans_filtre_de_duree_est_vu():
    """⭐⭐ Couvrir `cancelled` SANS filtrer la file rouvrirait le bruit.

    Un filet qui alerte sur toutes les annulations est aussi nuisible qu'un
    filet qui n'alerte sur aucune : il se fait ignorer. Ce faux-la l'attrape.
    """
    c = _corpus_jouet([], {})
    y = yaml.safe_load(c[FILET])
    y["jobs"]["dire"]["steps"] = [{"run": 'set -eu\ncurl "$HOOK"\n'}]
    c[FILET] = yaml.safe_dump(y, allow_unicode=True)
    with pytest.raises(AssertionError):
        test_les_annulations_courtes_sont_filtrees(c)


# ⚠️ CE FILET-JOUET EST ECRIT A LA MAIN, PAS PAR `yaml.safe_dump`.
# Le controle ⑥ lit le TEXTE du fichier, pas l'arbre YAML : un `safe_dump`
# reserialise le script en une chaine echappee (`\"${HOOK:-}\"`), que la
# recherche littérale ne retrouve pas. Le premier jet de ce test rougissait donc
# pour la mauvaise raison — « le filet ne verifie pas le secret » au lieu de
# « il sort en 0 ». ⭐ Un controle et sa contre-epreuve doivent lire la MEME
# forme du sujet.
_FILET_BRUT = """name: Filet — alerte technique
on:
  workflow_run:
    workflows: []
    types: [completed]
jobs:
  dire:
    if: github.event.workflow_run.conclusion == 'failure' || github.event.workflow_run.conclusion == 'timed_out'
    runs-on: ubuntu-latest
    steps:
      - run: |
          set -eu
          if [ -z "${HOOK:-}" ]; then
            echo "pas d alerte"
            exit %s
          fi
"""


def test_faux_un_secret_absent_qui_sort_en_zero_est_vu():
    c = {FILET: _FILET_BRUT % "0"}
    with pytest.raises(AssertionError, match="banc muet"):
        test_secret_absent_fait_echouer(c)
    # ... et la meme, honnete, passe :
    test_secret_absent_fait_echouer({FILET: _FILET_BRUT % "1"})
