"""📚 LE PONT : le tirage des comics, du Sheet vers les alertes.

L'alerte « comic à petit tirage bradé » tourne sur jetonveve (le repo public), qui
n'a AUCUN acces au Google Sheet — et c'est tres bien ainsi (le Sheet est prive).
Mais le TIRAGE d'un comic n'existe nulle part ailleurs : `getElements` de StackR
ne donne pas de supply fiable, et je ne vais pas DEVINER ce que veut dire son
champ `quantity` (regle anti-fishing : on prouve, on ne suppose pas).

Ce module exporte donc un petit CSV public-compatible :
    data/comics_supply.csv   ->  veve_uuid, series_uuid, name, rarity,
                                 edition_type, supply
que jetonveve va chercher en lecture seule avec PREDA_TOKEN.

⚠️ LE PIEGE DEJA PAYE (14/07, Captain America #7) : **le tirage d'un COMIC n'est
PAS la somme de ses raretes.** `supply` (= totalIssued) est le tirage de la
SERIE, RECOPIE sur chaque ligne de rarete. Additionner les 5 lignes donnait 5 000
la ou le comic etait SOLD OUT a 1 000. On prend donc le **MAX par serie**, jamais
la somme. Une ligne du CSV = un element (une rarete), mais son `supply` est celui
de sa SERIE.

Env : GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID, COMICS_CSV (defaut
      data/comics_supply.csv), COMICS_SUPPLY_MAX (defaut 5000 : on exporte plus
      large que le seuil d'alerte, pour pouvoir le regler sans re-exporter).
"""

from __future__ import annotations

import csv
import os
import sys
from typing import Dict, List

from scraper.sheets import COMICS_TAB, _client       # noqa: F401

CSV_PATH = os.environ.get("COMICS_CSV", "data/comics_supply.csv")
SUPPLY_MAX = int(os.environ.get("COMICS_SUPPLY_MAX", "5000"))
ENTETE = ["veve_uuid", "series_uuid", "name", "rarity", "edition_type", "supply"]

# La colonne du tirage. `supply` est celle qu'utilisent deja les modules Discord
# en prod. Si elle disparaissait, on CRIE — hors de question d'exporter des
# zeros en silence : une alerte « comic a 1 000 exemplaires » batie sur un
# tirage vide serait pire que pas d'alerte du tout.
COL_SUPPLY = os.environ.get("COMICS_SUPPLY_COL", "supply")


def _num(x) -> int:
    try:
        return int(float(str(x).replace(",", ".").replace(" ", "") or 0))
    except (TypeError, ValueError):
        return 0


def _entetes(valeurs: List[List[str]]) -> int:
    """La ligne d'en-tetes n'est pas forcement la 1re (une banniere peut la
    preceder — c'est ce qui avait casse la lecture de 🏆A-CLASSEMENT). On ANCRE
    sur une colonne connue au lieu de supposer une position."""
    for i, ligne in enumerate(valeurs[:10]):
        if "veve_uuid" in ligne:
            return i
    return -1


def lire_comics(sh) -> List[Dict]:
    ws = sh.worksheet(COMICS_TAB)
    valeurs = ws.get_all_values()
    i = _entetes(valeurs)
    if i < 0:
        raise RuntimeError(f"{COMICS_TAB} : pas de colonne veve_uuid trouvee "
                           f"dans les 10 premieres lignes.")
    entetes = valeurs[i]
    if COL_SUPPLY not in entetes:
        raise RuntimeError(
            f"{COMICS_TAB} : la colonne « {COL_SUPPLY} » a DISPARU. Colonnes "
            f"vues : {entetes}. On s'arrete : exporter des tirages vides "
            f"ferait alerter sur n'importe quoi.")
    return [dict(zip(entetes, l)) for l in valeurs[i + 1:] if any(l)]


def tirages_par_serie(lignes: List[Dict]) -> Dict[str, int]:
    """⚠️ MAX, PAS SOMME. Le supply d'un comic est celui de la SERIE, recopie sur
    chaque ligne de rarete."""
    out: Dict[str, int] = {}
    for r in lignes:
        s = str(r.get("series_uuid") or "").strip()
        v = _num(r.get(COL_SUPPLY))
        if s and v:
            out[s] = max(out.get(s, 0), v)
    return out


def construire(lignes: List[Dict]) -> List[List]:
    tirages = tirages_par_serie(lignes)
    out: List[List] = []
    for r in lignes:
        uid = str(r.get("veve_uuid") or "").strip()
        s = str(r.get("series_uuid") or "").strip()
        supply = tirages.get(s, 0)
        if not uid or not supply or supply > SUPPLY_MAX:
            continue
        out.append([uid, s,
                    (r.get("veve_series_name") or r.get("name") or "").strip(),
                    (r.get("rarity") or "").strip(),
                    (r.get("edition_type") or "").strip(), supply])
    out.sort(key=lambda l: (l[5], l[2]))
    return out


def ecrire(rows: List[List]) -> None:
    os.makedirs(os.path.dirname(CSV_PATH) or ".", exist_ok=True)
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(ENTETE)
        w.writerows(rows)


def main() -> int:
    sid = os.environ.get("SHEET_ID")
    if not sid:
        print("SHEET_ID manquant.", file=sys.stderr)
        return 2
    sh = _client().open_by_key(sid)
    lignes = lire_comics(sh)
    rows = construire(lignes)
    if not rows:
        # On n'ECRASE PAS un CSV valide par un fichier vide : un export rate ne
        # doit pas eteindre les alertes.
        print("⛔ 0 comic exporte — on ne touche pas au CSV existant.",
              file=sys.stderr)
        return 3
    ecrire(rows)
    petits = sum(1 for r in rows if r[5] <= 1000)
    print(f"📚 {len(rows)} elements de comics exportes (≤ {SUPPLY_MAX} ex.), "
          f"dont {petits} a tirage ≤ 1 000 → {CSV_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
