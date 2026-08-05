# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_couvertures_cablage.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""LE CABLAGE DES COUVERTURES — qui lance `scraper.run` doit tirer `elements-v3`.

🔴🔴 CE QUE CE BANC EMPECHE, ET POURQUOI IL NE POUVAIT PAS EXISTER AVANT.

`scraper.run` appelle `couvertures_chaine`, qui lit `data/elements_v3.csv`. Ce
fichier n'existe QUE si le workflow telecharge la Release `elements-v3`. Deux
workflows lancent `scraper.run` ; **un seul le telechargeait**. Le run manuel du
05/08/2026 (`ENRICH_MODE=all`, 19 327 produits, `status=OK`) a donc tourne sans
catalogue-chaine : **0 fiche remplie, 11 336 comics sans couverture**.

⭐⭐ **UN MEME TRAITEMENT SUR DEUX CHEMINS N'EST PAS LE MEME TRAITEMENT.**

⭐⭐⭐ ET SURTOUT : **LE RUN ETAIT VERT.** Le code ne peut pas se plaindre — il
dit « le catalogue reste valide, il aura juste ses trous », ce qui est vrai et
rassurant. **Un manque annonce comme normal ne se lit pas comme un manque.**
Aucun test de code ne pouvait attraper ca : le defaut n'etait pas DANS le
Python, il etait dans ce que le workflow OUBLIAIT de faire avant de l'appeler.
➡️ D'ou un banc qui lit les **workflows**, pas les modules.

⭐⭐ Et c'est la lecon du lot 34, appliquee : *une consigne se lit une fois, un
banc se joue a chaque fois*. Corriger `enrich-backfill.yml` sans poser ce banc
laisserait le prochain workflow refaire exactement le meme trou.
→ [[regle-valider-le-livrable-comme-la-machine]]

    python3 -m pytest tests/test_couvertures_cablage.py -q
"""

import os
import re

import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS = os.path.join(RACINE, ".github", "workflows")

# Ce qu'il faut avoir fait AVANT d'appeler `scraper.run`.
TELECHARGE = "gh release download elements-v3"
APPELLE_RUN = re.compile(r"python\s+-m\s+scraper\.run\b")


def _workflows():
    if not os.path.isdir(WORKFLOWS):
        # ⛔ On ECHOUE, on ne saute pas. Un banc qui se declare vert sans rien
        # verifier est pire que pas de banc — c'est exactement ce qui a laisse
        # passer le trou pendant des semaines.
        pytest.fail(f"{WORKFLOWS} introuvable : ce banc ne peut rien verifier. "
                    "⚠️ `cp -r depot/* ...` NE COPIE PAS les dossiers caches — "
                    "verifier l'arbre avant de conclure a une regression.")
    out = {}
    for nom in sorted(os.listdir(WORKFLOWS)):
        if nom.endswith((".yml", ".yaml")):
            with open(os.path.join(WORKFLOWS, nom), encoding="utf-8") as f:
                out[nom] = f.read()
    assert out, "aucun workflow lu — l'inventaire est vide, donc muet"
    return out


def test_qui_lance_scraper_run_telecharge_elements_v3():
    """🔴 LE VERROU. La regle tient en une phrase : `scraper.run` a besoin du
    catalogue-chaine, donc tout workflow qui l'appelle doit l'avoir telecharge.

    ⭐ La liste n'est PAS ecrite en dur : le banc la DECOUVRE. Un workflow neuf
    qui appellerait `scraper.run` sans le telechargement tombe ici tout seul —
    c'est ce qui distingue un capteur d'une consigne."""
    fautifs = [nom for nom, txt in _workflows().items()
               if APPELLE_RUN.search(txt) and TELECHARGE not in txt]
    assert not fautifs, (
        "ces workflows lancent `scraper.run` SANS télécharger la Release "
        f"`elements-v3` — leurs fiches sortiront sans couverture, et le run "
        f"sera VERT : {', '.join(fautifs)}")


def test_le_banc_sait_echouer():
    """⭐⭐ UN BANC QUI NE SAIT PAS ECHOUER NE PROUVE RIEN. On rejoue la regle
    sur un workflow fabrique qui porte le defaut : elle doit le voir."""
    faux = {"defaut.yml": "steps:\n  - run: python -m scraper.run\n"}
    fautifs = [n for n, t in faux.items()
               if APPELLE_RUN.search(t) and TELECHARGE not in t]
    assert fautifs == ["defaut.yml"]

    # ... et le temoin sain doit rester vert, sinon un banc qui rougit sur
    # tout passerait pour rigoureux.
    sain = {"ok.yml": f"steps:\n  - run: {TELECHARGE}\n  - run: python -m scraper.run\n"}
    assert not [n for n, t in sain.items()
                if APPELLE_RUN.search(t) and TELECHARGE not in t]


def test_enrich_backfill_porte_bien_le_correctif():
    """Le cas nommement corrige par le lot 69. ⚠️ Ce test est REDONDANT avec
    le premier, et c'est voulu : celui-ci nomme le fichier, donc son echec dit
    tout de suite QUOI relire — le premier, lui, survit aux renommages."""
    wf = _workflows()
    assert "enrich-backfill.yml" in wf, (
        "enrich-backfill.yml absent du dépôt — le workflow a-t-il été déposé "
        "au bon endroit ? ⚠️ `.github` est masqué sous Windows.")
    txt = wf["enrich-backfill.yml"]
    assert TELECHARGE in txt
    assert "COUVERTURES_CHAINE" in txt
    assert "permissions:" in txt, (
        "`gh release download` a besoin d'au moins `contents: read`")


def test_le_telechargement_ne_fait_jamais_tomber_le_run():
    """⭐ Une Release indisponible doit laisser passer l'enrichissement des
    19 000 produits. Les fiches gardent leurs trous — ce qui était déjà le cas
    avant ce lot — mais on ne perd pas le run entier pour un visuel."""
    for nom, txt in _workflows().items():
        for ligne in txt.splitlines():
            if TELECHARGE in ligne:
                bloc = txt[txt.index(ligne):txt.index(ligne) + 400]
                assert "||" in bloc, (
                    f"{nom} : `gh release download` sans repli `|| echo` — "
                    "une Release absente ferait tomber tout le run")
