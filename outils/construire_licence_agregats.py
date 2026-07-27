#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
⚠️ CE FICHIER VA DANS  D:\\Programme\\Claude\\Projects\\ScrapeurVeVe\\outils\\
   (ce n'est PAS un fichier de dépôt : ses entrées sont des fichiers locaux de
    ScrapeurVeVe, pas des fichiers versionnés.)

    python3 outils/construire_licence_agregats.py

Reconstruit `licence_agregats.json` — les compteurs de la page « Marques » de
vevewiki — et écrit :
    outputs/licence_agregats.json           l'artefact corrigé (à déposer dans
                                            veve-sites/engine/data/)
    outputs/licence_agregats_rapport.md     ce qui a été corroboré, et ce qui
                                            ne l'a pas été

================================================================================
LE DÉFAUT CORRIGÉ (constaté le 27/07/2026)
================================================================================
La page Marques annonçait un « premier drop » qui était en réalité la date de
PREMIÈRE FRAPPE ON-CHAIN. Ce ne sont pas deux mesures de la même chose : VeVe
frappe les jetons dans son coffre AVANT d'ouvrir le drop au public.

    médiane de l'écart frappe -> drop :   +2 jours
    étendue observée          :   0 à +54 jours (Louboutin)

Le blog officiel de VeVe tranche : sur 5 séries vérifiées à la main (RoboCop S1,
Battlestar Galactica, DeLorean, Uncanny X-Men #142, Black Panther (2005) #2), la
date d'annonce colle EXACTEMENT au `release_date` du catalogue, et jamais à la
date de frappe. ➡️ pour dire « premier drop », c'est le catalogue qui fait foi.

⛔ MAIS le catalogue ne peut PAS remplacer l'artefact : il est PARTIEL
   (4 584 de ses 5 047 séries n'ont pas d'alias de licence, et il ne porte que
   411 items Marvel contre 8 486 côté chaîne). Recalculer `n_series`/`n_items`
   dessus donnerait des compteurs faux et silencieusement plus petits.

D'où le partage des rôles retenu ici — chaque source sur ce qu'elle sait :

    n_series / n_items / first_mint   <- la CHAÎNE   (bible/series_firstmint.csv)
    first_drop                        <- le CATALOGUE (catalogue.csv.gz)

================================================================================
LA CORROBORATION (le garde-fou qui évite de republier une date fausse)
================================================================================
Prendre bêtement `min(release_date)` par licence ne marche pas : quand le
catalogue ne contient pas la PREMIÈRE série d'une licence, son minimum est celui
d'une série plus tardive. Vécu : `universal` -> 450 jours d'écart, parce que le
catalogue n'en connaît qu'1 série sur 7, et pas la première (Tomb Of Dracula).

Règle appliquée : on ne publie `first_drop` que si le catalogue contient
**exactement la ou les séries les plus anciennes de la chaîne**. Sinon le champ
reste `null` et l'affichage retombe sur la frappe, honnêtement étiquetée.
⭐ Le garde-fou se contrôle lui-même : c'est la chaîne qui dit QUELLE série
   regarder, et le catalogue qui dit QUAND elle est sortie.
"""
from __future__ import annotations

import csv
import gzip
import json
import pathlib
import sys
from datetime import date, datetime

RACINE = pathlib.Path(__file__).resolve().parent.parent
SERIES_CHAINE = RACINE / 'bible' / 'series_firstmint.csv'
ALIAS = RACINE / 'bible' / 'registre' / 'alias_series_licence.json'
CATALOGUE = RACINE / 'catalogue.csv.gz'
SORTIE = RACINE / 'outputs' / 'licence_agregats.json'
RAPPORT = RACINE / 'outputs' / 'licence_agregats_rapport.md'

# Au-delà de ce délai entre la frappe et le drop, on n'y croit plus : c'est le
# signe que le catalogue a raté la vraie première série. Observé : 54 j max sur
# une série corroborée, 450 j sur une non corroborée.
ECART_MAX_JOURS = 120


def norm(s) -> str:
    """Comparaison de noms de série : espaces normalisés, sans casse."""
    return ' '.join(str(s or '').split()).strip()


def jour(txt: str) -> str:
    """`31/12/2025 16:00:00` (catalogue) ou `2025-12-31` (chaîne) -> ISO."""
    t = str(txt or '').strip()
    if not t:
        return ''
    t = t.split()[0]
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d.%m.%Y'):
        try:
            return datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            continue
    return ''


def charger_alias() -> dict[str, list[str]]:
    brut = json.loads(ALIAS.read_text(encoding='utf-8'))
    return {norm(k): v for k, v in brut.items()}


def agreger_chaine(alias) -> tuple[dict, dict]:
    """Compteurs par licence + la (ou les) série(s) la (les) plus ancienne(s).

    Renvoie ({licence: {n_series, n_items, first_mint}},
             {licence: {series les plus anciennes}}).
    """
    agg: dict[str, dict] = {}
    premieres: dict[str, set] = {}
    with SERIES_CHAINE.open(encoding='utf-8') as f:
        for row in csv.DictReader(f):
            s = norm(row['series'])
            fm = jour(row['first_mint'])
            try:
                nitems = int(row['nitems'])
            except (TypeError, ValueError):
                nitems = 0
            for lic in alias.get(s, []):
                a = agg.setdefault(lic, {'n_series': 0, 'n_items': 0, 'first_mint': ''})
                a['n_series'] += 1
                a['n_items'] += nitems
                if not fm:
                    continue
                if not a['first_mint'] or fm < a['first_mint']:
                    a['first_mint'] = fm
                    premieres[lic] = {s}
                elif fm == a['first_mint']:
                    premieres.setdefault(lic, set()).add(s)
    return agg, premieres


def dates_catalogue(alias) -> dict[str, str]:
    """`{série normalisée: date de sortie la plus ancienne}` — le catalogue."""
    out: dict[str, str] = {}
    with gzip.open(CATALOGUE, 'rt', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            s = norm(row.get('series'))
            if not s or s not in alias:
                continue
            d = jour(row.get('release_date'))
            if d and (s not in out or d < out[s]):
                out[s] = d
    return out


def main() -> int:
    for p in (SERIES_CHAINE, ALIAS, CATALOGUE):
        if not p.exists():
            sys.exit(f"source introuvable : {p}")

    alias = charger_alias()
    agg, premieres = agreger_chaine(alias)
    cat = dates_catalogue(alias)

    # Un artefact vide est un ÉCHEC, pas un résultat (règle « lecture vide =
    # échec » du reste du projet) : on préfère ne rien écrire.
    if len(agg) < 20:
        sys.exit(f"ABANDON : {len(agg)} licences seulement — une source est muette ?")

    corrobore, sans_preuve = [], []
    for lic, a in agg.items():
        srcs = sorted(premieres.get(lic, ()))
        dates = [cat[s] for s in srcs if s in cat]
        if len(dates) != len(srcs) or not dates:
            a['first_drop'] = None
            a['first_drop_source'] = None
            sans_preuve.append((lic, a['first_mint'], srcs,
                                'première série absente du catalogue'))
            continue
        d = min(dates)
        ecart = (date.fromisoformat(d) - date.fromisoformat(a['first_mint'])).days
        if ecart > ECART_MAX_JOURS:
            a['first_drop'] = None
            a['first_drop_source'] = None
            sans_preuve.append((lic, a['first_mint'], srcs,
                                f'écart invraisemblable de {ecart} j'))
            continue
        a['first_drop'] = d
        a['first_drop_source'] = 'catalogue'
        corrobore.append((lic, a['first_mint'], d, ecart, srcs))

    ordre = dict(sorted(agg.items(), key=lambda kv: (kv[1]['first_mint'], kv[0])))
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps(ordre, ensure_ascii=False, indent=1) + '\n',
                      encoding='utf-8')

    ecarts = sorted(e for *_, e, _ in corrobore)
    lignes = [
        '# licence_agregats.json — rapport de construction',
        '',
        f"Produit par `outils/construire_licence_agregats.py` le "
        f"{date.today().isoformat()}.",
        '',
        f"- **{len(agg)} licences**, "
        f"{sum(a['n_series'] for a in agg.values())} séries, "
        f"{sum(a['n_items'] for a in agg.values())} items "
        f"(comptés sur la CHAÎNE — le catalogue est partiel).",
        f"- **{len(corrobore)} `first_drop` corroborés** par le catalogue, "
        f"**{len(sans_preuve)} sans preuve** (le champ reste `null`).",
        f"- Écart frappe → drop : min {ecarts[0]} j · médiane "
        f"{ecarts[len(ecarts) // 2]} j · max {ecarts[-1]} j.",
        '',
    ]
    impossibles = [r for r in corrobore if r[3] < 0]
    if impossibles:
        lignes += [
            '## ⚠️ Drop AVANT la frappe — physiquement impossible, à trancher',
            '',
            "Une des deux sources se trompe sur ces licences. Ce sont toutes des",
            "séries de **l'ère GoChain** (2020) : la plateforme y était custodiale et",
            "n'a laissé aucun transfert de NFT, donc leur « frappe » n'est pas un",
            "fait de chaîne mais une date reconstituée. Le catalogue, lui, colle aux",
            "annonces datées du blog. ➡️ On publie le catalogue, mais on le DIT.",
            '',
            '| licence | frappe (reconstituée) | premier drop (catalogue) | écart (j) |',
            '|---|---|---|---|',
        ]
        for lic, fm, d, e, _ in impossibles:
            lignes.append(f"| `{lic}` | {fm} | {d} | {e:+d} |")
        lignes.append('')
    lignes += [
        '## Sans preuve — la page affichera la FRAPPE, étiquetée comme telle',
        '',
        '| licence | frappe | 1re série on-chain | pourquoi |',
        '|---|---|---|---|',
    ]
    for lic, fm, srcs, pourquoi in sorted(sans_preuve):
        lignes.append(f"| `{lic}` | {fm} | {', '.join(srcs) or '—'} | {pourquoi} |")
    lignes += ['', '## Corroborés — écart frappe → drop', '',
               '| licence | frappe | premier drop | écart (j) |', '|---|---|---|---|']
    for lic, fm, d, e, _ in sorted(corrobore, key=lambda r: -r[3]):
        lignes.append(f"| `{lic}` | {fm} | {d} | {e:+d} |")
    RAPPORT.write_text('\n'.join(lignes) + '\n', encoding='utf-8')

    print(f"OK — {len(agg)} licences · {len(corrobore)} first_drop corroborés · "
          f"{len(sans_preuve)} sans preuve")
    print(f"   {SORTIE}")
    print(f"   {RAPPORT}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
