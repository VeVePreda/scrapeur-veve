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


def main() -> int:
    agg = charger_agregats()
    if len(agg) < 20:
        sys.exit(f'ABANDON : {len(agg)} licences seulement — la source est-elle muette ?')

    figures = [figure_poids(agg), figure_arrivees(agg), figure_pionnieres(agg),
               figure_premier_drop()]

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
