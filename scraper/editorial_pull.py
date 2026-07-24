"""
Récolteur éditorial GÉNÉRIQUE — le constructeur de contenu, étape 1.

⚠️ CE FICHIER VA DANS LE DÉPÔT  VeVePreda/scrapeur-veve , dans  scraper/
    (chemin exact : scraper/editorial_pull.py)

But (bible/architecture-generateur-sites.md) : lire les onglets d'un **Sheet
éditorial** et en écrire un **snapshot committé** dans le dépôt du SITE
(`sites/<SITE>/editorial/<page>.json`). UN SEUL code pour les 15 sites : rien
n'est vevewiki-spécifique — tout est piloté par le **manifeste** du site.

Doctrine (identique pour tout le réseau) :
  • Config par site = `sites/<SITE>/manifest.yml`, clés `editorial:` + `languages:`.
  • Auth Google = on RÉUTILISE `scraper.sheets._client()` (service-account gspread).
  • Snapshot → git : **upsert par clé, JAMAIS d'effacement** (une clé disparue du
    Sheet est CONSERVÉE dans le snapshot ; c'est le rôle du consommateur, pas du
    récolteur, de dépublier via `publie`/date).
  • **Lecture vide = ÉCHEC** : on ne publie pas une page à zéro. Si UNE page de
    contenu revient vide, tout le run échoue AVANT d'écrire quoi que ce soit —
    aucun snapshot existant n'est écrasé par du vide.
  • **Quota Sheets partagé** : ce récolteur doit tourner DÉCALÉ des crons
    daily / réparation / moisson (réglage de planification, pas de code).

Règle d'or de non-duplication : toute logique réutilisable par un 2ᵉ site vit
ICI (builder commun), jamais dans une page ni dans un script propre à un site.

Où ça tourne : dans le workflow CI de veve-sites (à créer, étape 5), où le dépôt
du site est le cwd et scrapeur-veve est sur le PYTHONPATH. D'où la racine par
défaut = PROJECT_ROOT (ou cwd), comme le fait déjà `engine/lib/manifest.mjs`.

Usage :
    SITE=vevewiki python -m scraper.editorial_pull
    python scraper/editorial_pull.py --site vevewiki --root /chemin/veve-sites
    python scraper/editorial_pull.py --site vevewiki --dry-run   # ne rien écrire
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:                                    # PyYAML : déjà présent (requirements.txt)
    import yaml
except Exception as e:                  # noqa: BLE001
    raise RuntimeError("PyYAML requis pour lire le manifeste du site.") from e


# ---------------------------------------------------------------------------
# Conventions RÉSEAU (pas vevewiki-spécifiques) — la spec du Sheet éditorial est
# la même pour tous les sites (bible/sheet-vevewiki-spec.md). Un site peut TOUT
# redéfinir dans son manifeste (`editorial.tabs`, `editorial.keys`,
# `editorial.allow_empty`) ; ces valeurs ne sont que des défauts raisonnables.
#
# key = colonne(s) formant la clé stable d'upsert. Peut être composite (liste).
# allow_empty = une page « file d'attente » (Submit) a le droit d'être vide.
# ---------------------------------------------------------------------------
PAGE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "glossary": {"tab": "Glossary", "key": "id",       "allow_empty": False},
    "acronyms": {"tab": "Acronyms", "key": "sigle",    "allow_empty": False},
    "annuaire": {"tab": "Annuaire", "key": ["type", "nom"], "allow_empty": False},
    "history":  {"tab": "History",  "key": "id",       "allow_empty": False},
    "brands":   {"tab": "Brands",   "key": "licence",  "allow_empty": False},
    "blog":     {"tab": "Blog",     "key": "slug",     "allow_empty": False},
    "submit":   {"tab": "Submit",   "key": None,       "allow_empty": True},
}
# Ordre de repli pour deviner la clé d'une page inconnue du réseau.
_KEY_FALLBACK = ("id", "slug", "sigle", "licence", "key", "uuid")


class EditorialError(RuntimeError):
    """Erreur de récolte qui doit FAIRE ÉCHOUER le run (avant toute écriture)."""


# ---------------------------------------------------------------------------
# Manifeste
# ---------------------------------------------------------------------------
def _project_root(cli_root: Optional[str]) -> str:
    return cli_root or os.environ.get("PROJECT_ROOT") or os.getcwd()


def _load_manifest(root: str, site: str) -> Dict[str, Any]:
    path = os.path.join(root, "sites", site, "manifest.yml")
    if not os.path.exists(path):
        raise EditorialError(f"Manifeste introuvable : {path}")
    with open(path, "r", encoding="utf-8") as fh:
        man = yaml.safe_load(fh) or {}
    if not isinstance(man, dict):
        raise EditorialError(f"Manifeste illisible : {path}")
    return man


def _page_config(man: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]], List[str]]:
    """Extrait du manifeste : sheet_id, la liste des pages (résolues avec les
    défauts réseau + surcharges du site), et les langues actives (métadonnée)."""
    ed = man.get("editorial") or {}
    sheet_id = str(ed.get("sheet_id") or "").strip()
    if not sheet_id:
        raise EditorialError(
            "manifest.yml : bloc `editorial.sheet_id` manquant (le Sheet du site).")

    pages_decl = ed.get("pages")
    if not pages_decl:
        raise EditorialError("manifest.yml : `editorial.pages` vide ou absent.")

    tabs_over: Dict[str, str] = {k: str(v) for k, v in (ed.get("tabs") or {}).items()}
    keys_over: Dict[str, Any] = dict(ed.get("keys") or {})
    allow_over = set(ed.get("allow_empty") or [])

    pages: List[Dict[str, Any]] = []
    for name in pages_decl:
        name = str(name).strip()
        base = dict(PAGE_DEFAULTS.get(name, {}))
        tab = tabs_over.get(name) or base.get("tab") or name.capitalize()
        key = keys_over.get(name, base.get("key", None))
        allow_empty = (name in allow_over) or bool(base.get("allow_empty", False))
        pages.append({"name": name, "tab": tab, "key": key,
                      "allow_empty": allow_empty})

    langs = ((man.get("languages") or {}).get("active")
             or (ed.get("languages") or {}).get("active") or [])
    langs = [str(l).strip() for l in langs if str(l).strip()]
    return sheet_id, pages, langs


# ---------------------------------------------------------------------------
# Lecture d'un onglet (transport) — isolée pour rester testable hors réseau.
# ---------------------------------------------------------------------------
def _open_spreadsheet(sheet_id: str):
    """Ouvre le classeur via l'auth service-account RÉUTILISÉE de sheets.py."""
    from scraper.sheets import _client               # même auth que tout le pipeline
    return _client().open_by_key(sheet_id)


def _find_worksheet(sh, title: str):
    """Résout un onglet par titre, insensible à la casse/espaces. On NE CRÉE
    JAMAIS l'onglet (contrairement à sheets._open_worksheet) : un onglet éditorial
    manquant est une erreur de config, pas quelque chose à fabriquer vide."""
    import time as _t
    try:                                              # optionnel : absent en test hors réseau
        from gspread.exceptions import APIError as _APIError
    except Exception:                                 # noqa: BLE001
        _APIError = ()                                # rien à rattraper -> pas de retry
    want = title.strip().lower()
    last: Optional[Exception] = None
    for i, delay in enumerate((0, 10, 20, 40, 60)):
        if delay:
            print(f"  onglet {title!r} : API Sheets indisponible, pause {delay}s "
                  f"(essai {i}/4)...", flush=True)
            _t.sleep(delay)
        try:
            for ws in sh.worksheets():
                if ws.title.strip().lower() == want:
                    return ws
            raise EditorialError(f"Onglet éditorial introuvable : {title!r}")
        except _APIError as e:                         # 429/503 transitoires : on rejoue
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code not in (429, 503) or i == 4:
                raise
            last = e
    if last:
        raise last
    raise EditorialError(f"Onglet éditorial introuvable : {title!r}")


def _read_tab_values(sh, title: str) -> List[List[str]]:
    """Renvoie la grille brute [ligne][colonne] (1re ligne = en-têtes)."""
    ws = _find_worksheet(sh, title)
    return ws.get_all_values()


# ---------------------------------------------------------------------------
# Transformation (PUR — aucune I/O réseau, entièrement testable).
# ---------------------------------------------------------------------------
def _clean_headers(raw: Sequence[str]) -> List[str]:
    """Nettoie la ligne d'en-têtes : retire tabulations/espaces parasites (bug
    `\\tpublie` vu le 24/07), et rend les noms uniques (colonnes en double ->
    `nom`, `nom__2`, …). Une colonne d'en-tête vide devient `col_<n>`."""
    seen: Dict[str, int] = {}
    out: List[str] = []
    for i, h in enumerate(raw):
        name = str(h or "").replace("\t", " ").strip()
        if not name:
            name = f"col_{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}__{seen[name]}"
        else:
            seen[name] = 1
        out.append(name)
    return out


def _records_from_values(values: List[List[str]]) -> List[Dict[str, Any]]:
    """Grille -> liste de dicts, dans l'ordre du Sheet. Ignore les lignes
    entièrement vides. Complète les cellules manquantes en fin de ligne."""
    if not values:
        return []
    headers = _clean_headers(values[0])
    n = len(headers)
    records: List[Dict[str, Any]] = []
    for row in values[1:]:
        if not any(str(c).strip() for c in row):
            continue                                  # ligne vide -> ignorée
        cells = list(row) + [""] * (n - len(row))
        records.append({headers[i]: cells[i] for i in range(n)})
    return records


def _key_of(rec: Dict[str, Any], key: Any) -> Optional[str]:
    """Valeur de clé (composite si `key` est une liste). None si la clé n'est pas
    renseignée (la ligne sera gardée mais non dédupliquée)."""
    if key is None:
        return None
    cols = key if isinstance(key, (list, tuple)) else [key]
    parts = [str(rec.get(c, "")).strip() for c in cols]
    if not any(parts):
        return None
    return "␟".join(parts)                       # séparateur improbable dans le texte


def merge_snapshot(old_records: List[Dict[str, Any]],
                   new_records: List[Dict[str, Any]],
                   key: Any) -> List[Dict[str, Any]]:
    """Upsert par clé, JAMAIS d'effacement.

    - Ordre = celui du Sheet pour les lignes présentes (la timeline History en
      dépend), puis on RÉ-APPEND en fin les anciennes lignes dont la clé a
      disparu du Sheet (conservées telles quelles).
    - Sans clé (`key is None`, ex. Submit) : remplacement complet par le Sheet
      (file d'attente vivante — pas de mémoire à préserver).
    """
    if key is None:
        return list(new_records)

    old_by_key: Dict[str, Dict[str, Any]] = {}
    for r in old_records:
        k = _key_of(r, key)
        if k is not None:
            old_by_key[k] = r

    out: List[Dict[str, Any]] = []
    seen: set = set()
    for r in new_records:
        k = _key_of(r, key)
        if k is None:
            out.append(r)                             # ligne sans clé : gardée telle quelle
            continue
        out.append(r)                                 # le Sheet fait FOI pour une clé présente
        seen.add(k)

    for k, r in old_by_key.items():                   # clés disparues du Sheet : conservées
        if k not in seen:
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Écriture du snapshot
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _editorial_dir(root: str, site: str) -> str:
    return os.path.join(root, "sites", site, "editorial")


def _read_old_snapshot(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        recs = data.get("records") if isinstance(data, dict) else data
        return list(recs) if isinstance(recs, list) else []
    except Exception as e:                             # noqa: BLE001
        print(f"  ⚠️ snapshot existant illisible ({path}): {e} — repart de zéro "
              f"pour le merge (l'upsert protège tout de même le Sheet vivant).",
              file=sys.stderr)
        return []


def _write_snapshot(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, path)                              # écriture atomique


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def pull(site: str, root: Optional[str] = None, dry_run: bool = False,
         _sheet_opener=None) -> Dict[str, Any]:
    """Récolte toutes les pages du site puis écrit les snapshots.

    Séquence en DEUX temps (garde-fou « vide = échec ») :
      1. LIRE + valider TOUTES les pages. Si une page de contenu revient vide,
         on lève AVANT d'écrire — aucun snapshot n'est touché.
      2. N'écrire qu'une fois tout validé.

    `_sheet_opener` : point d'injection pour les tests hors réseau (reçoit le
    sheet_id, renvoie un objet exposant `.worksheets()`/`get_all_values()`).
    """
    root = _project_root(root)
    man = _load_manifest(root, site)
    sheet_id, pages, langs = _page_config(man)

    opener = _sheet_opener or _open_spreadsheet
    sh = opener(sheet_id)

    # --- Temps 1 : lire et valider TOUT --------------------------------------
    staged: List[Dict[str, Any]] = []
    for page in pages:
        values = _read_tab_values(sh, page["tab"])
        new_records = _records_from_values(values)
        if not new_records and not page["allow_empty"]:
            raise EditorialError(
                f"Page '{page['name']}' (onglet {page['tab']!r}) : LECTURE VIDE. "
                f"Run interrompu — aucun snapshot écrasé (on ne publie pas une "
                f"page à zéro). Vérifier le Sheet / les droits / un hoquet API.")
        staged.append({"page": page, "new_records": new_records})

    # --- Temps 2 : merger + écrire -------------------------------------------
    out_dir = _editorial_dir(root, site)
    summary: Dict[str, Any] = {"status": "OK", "site": site, "sheet_id": sheet_id,
                               "languages": langs, "pages": {}, "dry_run": dry_run}
    for item in staged:
        page = item["page"]
        path = os.path.join(out_dir, f"{page['name']}.json")
        old = _read_old_snapshot(path)
        merged = merge_snapshot(old, item["new_records"], page["key"])
        payload = {
            "page": page["name"],
            "tab": page["tab"],
            "site": site,
            "key": page["key"],
            "languages": langs,
            "pulled_at": _now_iso(),
            "count": len(merged),
            "records": merged,
        }
        if not dry_run:
            _write_snapshot(path, payload)
        summary["pages"][page["name"]] = {
            "tab": page["tab"], "read": len(item["new_records"]),
            "kept": len(merged), "path": os.path.relpath(path, root),
        }
        print(f"  ✅ {page['name']:9s} onglet {page['tab']!r}: "
              f"{len(item['new_records'])} lus → {len(merged)} au snapshot"
              f"{' (dry-run)' if dry_run else ''}", flush=True)

    print(f"🌾 Récolte éditoriale {site} : {len(pages)} page(s), "
          f"langues={','.join(langs) or '—'}.", flush=True)
    return summary


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Récolteur éditorial générique (snapshot→git).")
    p.add_argument("--site", default=os.environ.get("SITE"),
                   help="Nom du site (défaut : variable d'env SITE).")
    p.add_argument("--root", default=None,
                   help="Racine du dépôt du site (défaut : PROJECT_ROOT ou cwd).")
    p.add_argument("--dry-run", action="store_true",
                   help="Lire et valider sans écrire de snapshot.")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    if not args.site:
        print("❌ Aucun site : passer --site ou définir la variable d'env SITE.",
              file=sys.stderr)
        return 2
    try:
        pull(args.site, root=args.root, dry_run=args.dry_run)
    except EditorialError as e:
        print(f"❌ Récolte éditoriale échouée : {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
