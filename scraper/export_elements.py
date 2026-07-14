"""🌉 LE PONT — tout ce que jetonveve doit savoir du catalogue, en un CSV.

Remplace `export_comics.py` : la chasse aux numeros porte sur les comics ET les
collectibles, donc le pont doit porter les deux.

    data/elements.csv
    veve_uuid, series_uuid, name, category, rarity, edition_type,
    supply, first_public, listings, note, brand, licensor

═══ CE QUE CHAQUE COLONNE SERT, ET LE PIEGE QU'ELLE PORTE ═══
* **supply** — ⚠️ POUR UN COMIC, C'EST LE TIRAGE DE LA SERIE, RECOPIE SUR CHAQUE
  LIGNE DE RARETE : on prend le **MAX** par serie, jamais la somme (5 x 1 000 !=
  5 000 : Captain America #7 etait SOLD OUT a 1 000 et s'affichait a « 20 % du
  tirage »). Pour un COLLECTIBLE, au contraire, chaque ligne a SON tirage.
* **first_public** (`first_available_edition`) — VeVe RETIENT des editions : la
  1re reellement vendue au public n'est presque jamais le #1. Elle ne se devine
  pas, elle se lit.
* **listings** (`market_totalListings`, collecte par comic_prices) — la
  profondeur du carnet. « 8 offres a 1,75 $ », ce n'est pas une aubaine, c'est le
  prix du marche. VIDE = INCONNU, jamais zero.
* **note** — la note de 🏆A-CLASSEMENT (le jugement de Preda).
* **brand / licensor** — servent a rattacher les DATES CLES (1939 ne veut dire
  quelque chose que sur un Batman).

Env : GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID, ELEMENTS_CSV, ELEMENTS_SUPPLY_MAX
"""

from __future__ import annotations

import csv
import os
import sys
from typing import Dict, List

from scraper.sheets import (COLLECT_TAB, COMICS_TAB, DYN_STATE_TAB,  # noqa: F401
                            _client)

CSV_PATH = os.environ.get("ELEMENTS_CSV", "data/elements.csv")
SUPPLY_MAX = int(os.environ.get("ELEMENTS_SUPPLY_MAX", "0"))   # 0 = tout
CLASSEMENT_TAB = os.environ.get("CLASSEMENT_TAB", "🏆A-CLASSEMENT")
ENTETE = ["veve_uuid", "series_uuid", "name", "category", "rarity",
          "edition_type", "supply", "first_public", "listings", "note",
          "brand", "licensor"]
COL_LISTINGS = "market_totalListings"


def _num(x) -> int:
    try:
        return int(float(str(x).replace(",", ".").replace(" ", "") or 0))
    except (TypeError, ValueError):
        return 0


def _ancre(vals: List[List[str]], *cols: str) -> int:
    for i, l in enumerate(vals[:40]):
        if all(c in l for c in cols):
            return i
    return -1


def _lire(ws, *cols: str) -> List[Dict]:
    """get_all_values, PAS get_all_records (il EXPLOSE sur des en-tetes en
    double), et on ANCRE la ligne d'en-tetes au lieu de la supposer en 1."""
    vals = ws.get_all_values()
    i = _ancre(vals, *cols)
    if i < 0:
        return []
    ent = vals[i]
    return [dict(zip(ent, l)) for l in vals[i + 1:] if any(l)]


def lire_listings(sh) -> Dict[str, int]:
    """⚠️ LOCALE FR : lecture NON FORMATEE (gspread relit « 6,99 » en 699)."""
    try:
        ws = sh.worksheet(DYN_STATE_TAB)
    except Exception:                                       # noqa: BLE001
        return {}
    from gspread.utils import ValueRenderOption
    out: Dict[str, int] = {}
    for r in ws.get_all_records(
            value_render_option=ValueRenderOption.unformatted):
        uid = str(r.get("veve_uuid") or "").strip()
        if uid and str(r.get(COL_LISTINGS, "")).strip() != "":
            out[uid] = _num(r.get(COL_LISTINGS))
    return out


def lire_notes(sh) -> Dict[str, str]:
    """{cle -> note} depuis 🏆A-CLASSEMENT. Balayage EPROUVE (en-tetes en ligne
    2, cle « uuid », casse non garantie) : on reprend la lecture de
    discord_retour au lieu d'en ecrire une deuxieme. Deux lectures de la meme
    page, c'est une qui ment."""
    CLES = ("series_uuid", "veve_uuid", "uuid")
    try:
        vals = sh.worksheet(CLASSEMENT_TAB).get_all_values()
    except Exception as e:                                  # noqa: BLE001
        print(f"  {CLASSEMENT_TAB} illisible : {e}", file=sys.stderr)
        return {}
    for i, l in enumerate(vals[:40]):
        bas = [str(c).strip().lower() for c in l]
        if "note" not in bas:
            continue
        cle = next((c for c in CLES if c in bas), "")
        if not cle:
            continue
        i_n, i_c = bas.index("note"), bas.index(cle)
        out: Dict[str, str] = {}
        for r in vals[i + 1:]:
            if len(r) <= max(i_n, i_c):
                continue
            k, n = str(r[i_c]).strip(), str(r[i_n]).strip()
            if k and n and k not in out:
                out[k] = n
        print(f"  {CLASSEMENT_TAB} : en-tetes ligne {i + 1} (cle « {cle} »), "
              f"{len(out)} note(s).", flush=True)
        return out
    print(f"  ⚠️ {CLASSEMENT_TAB} : aucune ligne avec « note » ET une cle.",
          file=sys.stderr)
    return {}


def tirages_comics(lignes: List[Dict]) -> Dict[str, int]:
    """MAX par serie — le supply d'un comic est celui de la SERIE."""
    out: Dict[str, int] = {}
    for r in lignes:
        s = str(r.get("series_uuid") or "").strip()
        v = _num(r.get("supply"))
        if s and v:
            out[s] = max(out.get(s, 0), v)
    return out


def construire(comics: List[Dict], collect: List[Dict],
               listings: Dict[str, int] = None,
               notes: Dict[str, str] = None) -> List[List]:
    listings, notes = listings or {}, notes or {}
    par_serie = tirages_comics(comics)
    out: List[List] = []

    for lignes, cat in ((comics, "comic"), (collect, "collectible")):
        for r in lignes:
            uid = str(r.get("veve_uuid") or "").strip()
            if not uid:
                continue
            s = str(r.get("series_uuid") or "").strip()
            # LA regle : serie pour un comic, element pour un collectible.
            supply = par_serie.get(s, 0) if cat == "comic" \
                else _num(r.get("supply"))
            if SUPPLY_MAX and supply > SUPPLY_MAX:
                continue
            note = notes.get(s) or notes.get(uid) or ""
            out.append([
                uid, s,
                (r.get("veve_series_name") or r.get("name") or "").strip(),
                cat,
                (r.get("rarity") or "").strip(),
                (r.get("edition_type") or "").strip(),
                supply,
                _num(r.get("first_available_edition")) or "",
                listings.get(uid, ""),        # "" = INCONNU, pas zero
                note,
                (r.get("veve_brand") or "").strip(),
                (r.get("veve_licensor") or "").strip(),
            ])
    out.sort(key=lambda l: (l[3], l[6], l[2]))
    return out


def main() -> int:
    sid = os.environ.get("SHEET_ID")
    if not sid:
        print("SHEET_ID manquant.", file=sys.stderr)
        return 2
    sh = _client().open_by_key(sid)
    comics = _lire(sh.worksheet(COMICS_TAB), "veve_uuid")
    collect = _lire(sh.worksheet(COLLECT_TAB), "veve_uuid")
    if not comics or not collect:
        print("⛔ catalogue illisible — on ne touche pas au CSV existant.",
              file=sys.stderr)
        return 3
    rows = construire(comics, collect, lire_listings(sh), lire_notes(sh))
    if not rows:
        print("⛔ 0 element — on ne touche pas au CSV existant.",
              file=sys.stderr)
        return 3
    os.makedirs(os.path.dirname(CSV_PATH) or ".", exist_ok=True)
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(ENTETE)
        w.writerows(rows)

    n_c = sum(1 for r in rows if r[3] == "comic")
    petits = sum(1 for r in rows if r[3] == "comic" and r[6] and r[6] <= 1000)
    fp = sum(1 for r in rows if r[7])
    print(f"🌉 {len(rows)} elements ({n_c} comics dont {petits} a tirage "
          f"≤ 1 000 · {len(rows) - n_c} collectibles) · {fp} avec une 1re "
          f"edition publique · {sum(1 for r in rows if r[8] != '')} avec des "
          f"offres · {sum(1 for r in rows if r[9])} avec une note -> {CSV_PATH}",
          flush=True)
    if not fp:
        print("⚠️ AUCUNE 1re edition publique : la colonne "
              "first_available_edition est vide dans le catalogue.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
