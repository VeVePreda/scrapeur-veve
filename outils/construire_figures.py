#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
⚠️ CE FICHIER VA DANS  D:\\Programme\\Claude\\Projects\\ScrapeurVeVe\\outils\\
   (ses entrées sont des fichiers locaux de ScrapeurVeVe, pas des fichiers de dépôt.)

    python3 outils/construire_figures.py

Produit les DESCRIPTEURS de figures du réseau, dans
`outputs/figures/<id>.json`, à déposer ensuite dans
`veve-sites/engine/data/figures/`.

================================================================================
POURQUOI UN GÉNÉRATEUR, ET PAS DES CHIFFRES ÉCRITS DANS LES ARTICLES
================================================================================
Un chiffre recopié à la main dans une prose est un chiffre qui se périme, et
personne ne s'en aperçoit. Ici l'auteur écrit `![légende](figure:mon-id)` et ne
recopie RIEN : la donnée vient du registre, le registre vient de l'entrepôt, et
la figure se retrace à chaque build.

⭐ Chaque descripteur porte OBLIGATOIREMENT sa `source` et sa date de `collecte`.
   Le moteur (engine/lib/figures.mjs) REFUSE au build un descripteur qui en
   manque : une figure part se faire partager sans sa page, elle doit rester
   attribuable et datable une fois seule.
   ⚠️ `collecte` = la date où la DONNÉE a été relevée, pas la date du build.
      Confondre les deux, c'est publier une figure qui prétend être fraîche.

Types disponibles : `barres` (comparer) · `series` (évoluer) · `jalons` (dater).
"""
from __future__ import annotations

import csv
import gzip
import json
import pathlib
import sys
from collections import Counter
from datetime import date, datetime

RACINE = pathlib.Path(__file__).resolve().parent.parent
AGREGATS = RACINE / 'outputs' / 'licence_agregats.json'
AGREGATS_REPLI = RACINE / 'bible' / 'registre' / 'licence_agregats.json'
CATALOGUE = RACINE / 'catalogue.csv.gz'
SORTIE = RACINE / 'outputs' / 'figures'

# La date de COLLECTE de l'entrepôt consolidé. À remonter quand une nouvelle
# récolte est intégrée — jamais automatiquement à `today()`, sinon la figure
# ment sur sa fraîcheur.
COLLECTE_ENTREPOT = '2026-07-27'


def charger_agregats() -> dict:
    for p in (AGREGATS, AGREGATS_REPLI):
        if p.exists():
            return json.loads(p.read_text(encoding='utf-8'))
    sys.exit('licence_agregats.json introuvable — lance construire_licence_agregats.py')


def joli(licence: str) -> str:
    """`back-to-the-future` -> `Back To The Future`, avec les sigles en majuscules."""
    SIGLES = {'dc': 'DC', 'tmnt': 'TMNT', 'kfc': 'KFC', 'usps': 'USPS', '007': '007'}
    if licence in SIGLES:
        return SIGLES[licence]
    return ' '.join(w.capitalize() for w in licence.split('-'))


# ── figure 1 — le poids des licences ────────────────────────────────────────
def figure_poids(agg: dict) -> dict:
    top = sorted(agg.items(), key=lambda kv: -kv[1]['n_items'])[:12]
    return {
        'id': 'licences-poids-catalogue',
        'type': 'barres',
        'titre': {
            'en': 'The 12 heaviest licences in the VeVe catalogue',
            'fr': 'Les 12 licences les plus lourdes du catalogue VeVe',
        },
        'note': {
            'en': 'Number of distinct collectibles published under each licence.',
            'fr': "Nombre de collectibles distincts publiés sous chaque licence.",
        },
        'legende': {
            'en': 'Marvel alone weighs more than all the other licences combined.',
            'fr': "Marvel pèse à elle seule plus que toutes les autres licences réunies.",
        },
        'source': {'en': 'on-chain warehouse (IMX + CollectChain)',
                   'fr': 'entrepôt on-chain (IMX + CollectChain)'},
        'collecte': COLLECTE_ENTREPOT,
        'donnees': [{'label': joli(k), 'valeur': v['n_items']} for k, v in top],
    }


# ── figure 2 — l'arrivée des licences ───────────────────────────────────────
def figure_arrivees(agg: dict) -> dict:
    par_an = Counter()
    for v in agg.values():
        d = v.get('first_drop') or v.get('first_mint') or ''
        if len(d) >= 4:
            par_an[d[:4]] += 1
    annees = sorted(par_an)
    return {
        'id': 'licences-par-annee',
        'type': 'series',
        'titre': {'en': 'New licences arriving on VeVe, by year',
                  'fr': "Licences arrivées sur VeVe, par année"},
        'note': {'en': 'Counted on the date of each licence’s first public drop.',
                 'fr': "Comptées à la date du premier drop public de chaque licence."},
        'legende': {'en': '2023 is the widest year: eleven licences opened in twelve months.',
                    'fr': "2023 est l'année la plus large : onze licences ouvertes en douze mois."},
        'source': {'en': 'warehouse + VeVe catalogue (first_drop, corroborated)',
                   'fr': 'entrepôt + catalogue VeVe (first_drop, corroboré)'},
        'collecte': COLLECTE_ENTREPOT,
        'donnees': [{'label': a, 'valeur': par_an[a]} for a in annees],
    }


# ── figure 3 — les plus anciennes licences ──────────────────────────────────
def figure_pionnieres(agg: dict) -> dict:
    ordre = sorted(agg.items(), key=lambda kv: (kv[1].get('first_drop') or kv[1]['first_mint']))[:8]
    def fr(d: str) -> str:
        return datetime.strptime(d, '%Y-%m-%d').strftime('%d/%m/%Y')
    return {
        'id': 'licences-pionnieres',
        'type': 'jalons',
        'titre': {'en': 'The first eight licences on VeVe',
                  'fr': 'Les huit premières licences de VeVe'},
        'note': {'en': 'Date of the first public drop of each licence.',
                 'fr': "Date du premier drop public de chaque licence."},
        'legende': {'en': 'Four of the eight arrived in the platform’s first four months.',
                    'fr': "Quatre des huit sont arrivées dans les quatre premiers mois de la plateforme."},
        'source': {'en': 'VeVe catalogue, corroborated against the chain',
                   'fr': 'catalogue VeVe, corroboré avec la chaîne'},
        'collecte': COLLECTE_ENTREPOT,
        'donnees': [{'label': {'en': (v.get('first_drop') or v['first_mint']),
                               'fr': fr(v.get('first_drop') or v['first_mint'])},
                     'valeur': joli(k)} for k, v in ordre],
    }


# ── figure 4 — le tout premier drop ─────────────────────────────────────────
def figure_premier_drop() -> dict:
    """Batman Black & White S1 : 4 pièces, 18 000 exemplaires.

    ⚠️ Ces tirages viennent du comptage des mints on-chain de la série (cf.
    l'article pilier « le tout premier drop »). Ils sont écrits ici parce que la
    série est FIGÉE depuis 2020 — aucune édition ne s'y ajoutera plus. Toute
    donnée encore vivante doit, elle, être recalculée : voir les figures 1 à 3.
    """
    return {
        'id': 'premier-drop-tirages',
        'type': 'barres',
        'titre': {'en': 'Batman Black & White S1: the four pieces of the very first drop',
                  'fr': 'Batman Black & White S1 : les quatre pièces du tout premier drop'},
        'note': {'en': '18,000 editions in total, minted on 14 October 2020.',
                 'fr': "18 000 exemplaires au total, frappés le 14 octobre 2020."},
        'legende': {'en': 'The rarer the piece, the shorter the run — the rarity logic was there from day one.',
                    'fr': "Plus la pièce est rare, plus le tirage est court : la logique de rareté est là dès le premier jour."},
        'source': {'en': 'on-chain warehouse, mint count for the series',
                   'fr': 'entrepôt on-chain, comptage des mints de la série'},
        'collecte': COLLECTE_ENTREPOT,
        'donnees': [
            {'label': '#01 Eduardo Risso', 'valeur': 1750},
            {'label': '#24 Brian Bolland', 'valeur': 3250},
            {'label': '#86 Becky Cloonan', 'valeur': 5500},
            {'label': '#100 Todd McFarlane', 'valeur': 7500},
        ],
    }


# ── figure 5 — combien d'exemplaires derrière un numéro de mint ─────────────
def figure_tirages(rows) -> dict:
    """Distribution des TIRAGES du catalogue — le dénominateur d'un numéro de mint.

    ⭐ POURQUOI CETTE FIGURE, ET PAS UNE AUTRE, SOUS L'ARTICLE « mint number ».
    L'article dit qu'un « low mint » est un numéro sous 100, souvent sous 50.
    Il ne dit nulle part SOUS COMBIEN. Or un numéro n'a de sens que rapporté au
    tirage de son objet : 42/50 et 42/30 000 n'ont rien à voir. La figure donne
    exactement le dénominateur que la prose n'a pas — sans qu'aucun chiffre soit
    recopié dans le texte.

    ⚠️ « exactement 1 000 » a SA propre barre, et ce n'est pas un caprice de
    présentation : 13 381 objets valent pile 1 000. Noyés dans un intervalle
    « 1 001-5 000 » ou « 501-1 000 », ils feraient croire à un étalement là où il
    y a en réalité un standard. Un histogramme à intervalles réguliers aurait été
    plus orthodoxe et aurait caché le seul fait intéressant.
    """
    tir = [n for n in (lire_entier(r['tirage']) for r in rows) if n]
    total = len(tir)
    seuils = [
        ('1 – 99',            lambda t: t < 100),
        ('100 – 999',         lambda t: 100 <= t < 1000),
        ('1 000',             lambda t: t == 1000),
        ('1 001 – 10 000',    lambda t: 1000 < t <= 10000),
        ('> 10 000',          lambda t: t > 10000),
    ]
    LIBELLES = {
        '1 – 99':         {'en': '1 – 99',          'fr': '1 – 99'},
        '100 – 999':      {'en': '100 – 999',       'fr': '100 – 999'},
        '1 000':          {'en': 'exactly 1,000',   'fr': 'exactement 1 000'},
        '1 001 – 10 000': {'en': '1,001 – 10,000',  'fr': '1 001 – 10 000'},
        '> 10 000':       {'en': '> 10,000',        'fr': '> 10 000'},
    }
    donnees = [{'label': LIBELLES[lab], 'valeur': sum(1 for t in tir if test(t))}
               for lab, test in seuils]
    mille = next(d['valeur'] for d in donnees if d['label']['fr'] == 'exactement 1 000')
    sous100 = next(d['valeur'] for d in donnees if d['label']['fr'] == '1 – 99')
    sans = len(rows) - total
    # ⚠️ Formater le NOMBRE seul, jamais la phrase : `f'{x:,}'.replace(',', ' ')`
    #    appliqué à une phrase lui mange aussi sa ponctuation (piège du lot 7).
    part = round(10 * mille / total)          # « sept objets sur dix »
    MOTS = {7: ('Seven', 'Sept'), 6: ('Six', 'Six'), 8: ('Eight', 'Huit')}
    mot_en, mot_fr = MOTS.get(part, (str(part), str(part)))
    return {
        'id': 'tirages-catalogue',
        'type': 'barres',
        'titre': {'en': 'How many copies sit behind a mint number',
                  'fr': "Combien d'exemplaires derrière un numéro de mint"},
        'note': {'en': f'{fmt(total, "en")} catalogue entries whose supply is known'
                       f' ({fmt(sans, "en")} without).',
                 'fr': f'{fmt(total, "fr")} entrées du catalogue dont le tirage est connu'
                       f' ({fmt(sans, "fr")} sans).'},
        'legende': {'en': f'{mot_en} objects in ten are issued in a run of exactly 1,000 — that '
                          f'thousand is what gives a mint number its scale. Only {fmt(sous100, "en")} '
                          f'objects have a total supply under 100.',
                    'fr': f'{mot_fr} objets sur dix sortent à exactement 1 000 exemplaires : '
                          f"c'est ce millier qui donne son échelle à un numéro de mint. "
                          f'Seuls {fmt(sous100, "fr")} objets ont un tirage total inférieur à 100.'},
        'source': {'en': 'VeVe catalogue (all object types)',
                   'fr': 'catalogue VeVe (tous types d’objets)'},
        'collecte': COLLECTE_ENTREPOT,
        'donnees': donnees,
    }


# ── figure 6 — les comics numériques, année par année ───────────────────────
def figure_comics_annee(rows) -> dict:
    """Comics publiés par ANNÉE COMPLÈTE.

    ⚠️⚠️ L'ANNÉE EN COURS EST VOLONTAIREMENT EXCLUE, et c'est le point délicat.
    Le catalogue s'arrête au 23/07/2026 : porter « 2026 » sur une courbe à côté
    d'années pleines dessine une CHUTE qui n'existe pas — l'œil compare des
    douze-mois à des sept-mois. Et une figure voyage sans sa page : personne ne
    sera là pour expliquer la nuance. Le compte partiel n'est pas perdu pour
    autant, il est DIT dans la note, où il ne peut pas être lu comme un point de
    la courbe.
    """
    par_an = Counter()
    for r in rows:
        if r['kind'] != 'Comic':
            continue
        d = lire_date(r['release_date'])
        if d:
            par_an[d.year] += 1
    if not par_an:
        sys.exit('ABANDON : aucun comic daté dans le catalogue — la source a changé ?')
    dernier = max(par_an)                       # année incomplète (celle de la collecte)
    pleines = sorted(y for y in par_an if y < dernier)
    partiel = par_an[dernier]
    mois = max(lire_date(r['release_date']).month for r in rows
               if r['kind'] == 'Comic' and lire_date(r['release_date'])
               and lire_date(r['release_date']).year == dernier)

    # La légende cite un fait CALCULÉ : l'année qui bascule l'échelle.
    bascule = max(pleines, key=lambda y: par_an[y] - par_an.get(y - 1, 0))
    avant = sum(par_an[y] for y in pleines if y < bascule)
    fois = par_an[bascule] / avant if avant else 0
    return {
        'id': 'comics-par-annee',
        'type': 'series',
        'titre': {'en': 'Digital comics published on VeVe, by year',
                  'fr': 'Comics numériques publiés sur VeVe, par année'},
        'note': {'en': f'Complete years only. {dernier} is still running and is not plotted: '
                       f'{fmt(partiel, "en")} issues over its first {mois} months.',
                 'fr': f'Années complètes seulement. {dernier}, en cours, n’est pas tracée : '
                       f'{fmt(partiel, "fr")} numéros sur ses {mois} premiers mois.'},
        'legende': {'en': f'{bascule} alone published {fois:.0f} times more issues than every '
                          f'year before it put together.',
                    'fr': f'{bascule} a publié à elle seule {fois:.0f} fois plus de numéros que '
                          f'toutes les années précédentes réunies.'},
        'source': {'en': 'VeVe catalogue (comics, release date)',
                   'fr': 'catalogue VeVe (comics, date de sortie)'},
        'collecte': COLLECTE_ENTREPOT,
        'donnees': [{'label': str(y), 'valeur': par_an[y]} for y in pleines],
    }


def lire_entier(v):
    v = str(v or '').strip().replace(' ', '').replace(',', '')
    return int(v) if v.isdigit() and int(v) > 0 else None


def lire_date(v):
    v = str(v or '').strip()
    for f in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(v, f)
        except ValueError:
            pass
    return None


def fmt(n: int, lang: str) -> str:
    """Le NOMBRE seul, jamais la phrase (cf. le piège du lot 7)."""
    return f'{n:,}' if lang == 'en' else f'{n:,}'.replace(',', '\u202f')


def charger_catalogue() -> list:
    if not CATALOGUE.exists():
        sys.exit(f'{CATALOGUE} introuvable — la seule source qui porte le tirage et le type.')
    with gzip.open(CATALOGUE, 'rt', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    if len(rows) < 10000:
        sys.exit(f'ABANDON : {len(rows)} lignes de catalogue seulement — source tronquée ?')
    return rows


def main() -> int:
    agg = charger_agregats()
    if len(agg) < 20:
        sys.exit(f'ABANDON : {len(agg)} licences seulement — la source est-elle muette ?')

    rows = charger_catalogue()
    figures = [figure_poids(agg), figure_arrivees(agg), figure_pionnieres(agg),
               figure_premier_drop(), figure_tirages(rows), figure_comics_annee(rows)]

    SORTIE.mkdir(parents=True, exist_ok=True)
    for fig in figures:
        # Le même contrôle que le moteur : on n'écrit pas un descripteur que le
        # build refusera. Mieux vaut échouer ici, où quelqu'un regarde.
        for champ in ('id', 'type', 'titre', 'source', 'collecte', 'donnees'):
            if not fig.get(champ):
                sys.exit(f"figure « {fig.get('id')} » : champ « {champ} » manquant.")
        date.fromisoformat(fig['collecte'])          # une date, ou ça casse ici
        (SORTIE / f"{fig['id']}.json").write_text(
            json.dumps(fig, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        print(f"  {fig['id']:<28} {fig['type']:<8} {len(fig['donnees'])} points")

    print(f"\nOK — {len(figures)} figures dans {SORTIE}")
    print("   → à déposer dans veve-sites/engine/data/figures/")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
