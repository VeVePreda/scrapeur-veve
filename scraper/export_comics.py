"""📚 LE PONT : tirage, OFFRES EN VENTE et NOTE DE CLASSEMENT des comics.

L'alerte « comic a petit tirage brade » tourne sur jetonveve (repo public), qui
n'a AUCUN acces au Google Sheet — et c'est tres bien ainsi. Ce module exporte
donc un CSV minimal que jetonveve lit en lecture seule :

    data/comics_supply.csv
    veve_uuid, series_uuid, name, rarity, edition_type, supply, listings, note

═══ POURQUOI CES DEUX COLONNES EN PLUS (v2, demande de Preda) ═══
* **listings** — « Spider-Man #546 a 1 000 de supply, mais il y a HUIT offres a
  1,75 $ : ce n'est pas une bonne affaire. » Il a raison, et c'est une regle
  generale : **un prix bas sur une offre UNIQUE est un signal ; le meme prix sur
  huit offres est un PLAFOND.** Sans la profondeur du carnet, on confond la
  rarete et le prix du marche. La donnee existe deja : `market_totalListings`,
  collecte chaque jour par `comic_prices` depuis my-nft-tracker.
  (⚠️ Et NON, le champ `quantity` de getElements ne sert a rien ici : verifie le
  14/07, c'est le nombre d'editions EN CIRCULATION — market_cap = floor x
  quantity. Deux minutes de verification qui evitent une regle fausse.)
* **note** — la note de la page 🏆A-CLASSEMENT : le jugement de Preda sur la
  serie. Un comic a 1,50 $ bien note n'est pas la meme affaire qu'un comic a
  1,50 $ mal note.

⚠️ LE PIEGE DU TIRAGE (paye le 14/07 sur Captain America #7) : **le tirage d'un
COMIC n'est PAS la somme de ses raretes.** `supply` est le tirage de la SERIE,
RECOPIE sur chaque ligne de rarete -> on prend le MAX par serie, jamais la somme.

Env : GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID, COMICS_CSV, COMICS_SUPPLY_MAX (5000)
"""

from __future__ import annotations

import csv
import os
import sys
from typing import Dict, List

from scraper.sheets import COMICS_TAB, DYN_STATE_TAB, _client   # noqa: F401

CSV_PATH = os.environ.get("COMICS_CSV", "data/comics_supply.csv")
SUPPLY_MAX = int(os.environ.get("COMICS_SUPPLY_MAX", "5000"))
CLASSEMENT_TAB = os.environ.get("CLASSEMENT_TAB", "🏆A-CLASSEMENT")
ENTETE = ["veve_uuid", "series_uuid", "name", "rarity", "edition_type",
          "supply", "listings", "note"]

COL_SUPPLY = os.environ.get("COMICS_SUPPLY_COL", "supply")
COL_LISTINGS = "market_totalListings"      # ecrit par comic_prices (1x/jour)


def _num(x) -> int:
    try:
        return int(float(str(x).replace(",", ".").replace(" ", "") or 0))
    except (TypeError, ValueError):
        return 0


def _ancre(valeurs: List[List[str]], *colonnes: str) -> int:
    """La ligne d'en-tetes n'est PAS forcement la 1re (une banniere la precede
    sur 🏆A-CLASSEMENT — c'est ce qui avait casse sa lecture). On ancre sur des
    colonnes connues au lieu de supposer une position."""
    for i, ligne in enumerate(valeurs[:40]):
        if all(c in ligne for c in colonnes):
            return i
    return -1


def _lire(ws, *colonnes: str) -> List[Dict]:
    """get_all_values (PAS get_all_records : il EXPLOSE sur des en-tetes en
    double, et il y en a)."""
    valeurs = ws.get_all_values()
    i = _ancre(valeurs, *colonnes)
    if i < 0:
        return []
    entetes = valeurs[i]
    return [dict(zip(entetes, l)) for l in valeurs[i + 1:] if any(l)]


def lire_comics(sh) -> List[Dict]:
    lignes = _lire(sh.worksheet(COMICS_TAB), "veve_uuid")
    if not lignes:
        raise RuntimeError(f"{COMICS_TAB} : pas de colonne veve_uuid trouvee.")
    if COL_SUPPLY not in lignes[0]:
        raise RuntimeError(
            f"{COMICS_TAB} : la colonne « {COL_SUPPLY} » a DISPARU (vues : "
            f"{list(lignes[0])}). On s'arrete : exporter des tirages vides "
            f"ferait alerter sur n'importe quoi.")
    return lignes


def lire_listings(sh) -> Dict[str, int]:
    """{uuid -> nombre d'offres en vente}, depuis l'etat de 🟠H-PRIX.

    ⚠️ LOCALE FR : lecture en valeurs NON FORMATEES. Sur un Sheet francais,
    gspread relit « 6,99 » comme 699 (virgule avalee) — le piege qui avait
    corrompu les prix comics le 10/07."""
    try:
        ws = sh.worksheet(DYN_STATE_TAB)
    except Exception:                                       # noqa: BLE001
        print(f"  (pas d'onglet {DYN_STATE_TAB} : listings inconnus)",
              file=sys.stderr)
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
    """{series_uuid -> note} depuis 🏆A-CLASSEMENT — le jugement de Preda.

    ⚠️ ON REPREND LA LECTURE EPROUVEE DE `discord_retour` (elle, elle marche).
    Ma v2 exigeait les en-tetes EXACTS « series_uuid » et « note » : resultat,
    **0 note sur 14 651 lignes**. Trois pieges, tous deja payes :
      1. les en-tetes ne sont PAS en ligne 1 (une banniere precede) ;
      2. la casse n'est pas garantie (« Note » ≠ « note ») ;
      3. la cle peut s'appeler series_uuid, veve_uuid ou uuid.
    → On BALAIE les 40 premieres lignes en cherchant une ligne qui porte A LA
    FOIS une cle ET une colonne « note » (insensible a la casse). Et on DIT ce
    qu'on a trouve : un export muet est ce qui a masque le probleme."""
    CLES = ("series_uuid", "veve_uuid", "uuid")
    try:
        vals = sh.worksheet(CLASSEMENT_TAB).get_all_values()
    except Exception as e:                                  # noqa: BLE001
        print(f"  lecture de {CLASSEMENT_TAB} impossible : {e}",
              file=sys.stderr)
        return {}

    for i, ligne in enumerate(vals[:40]):
        bas = [str(c).strip().lower() for c in ligne]
        if "note" not in bas:
            continue
        cle = next((c for c in CLES if c in bas), "")
        if not cle:
            continue
        i_note, i_cle = bas.index("note"), bas.index(cle)
        out: Dict[str, str] = {}
        for r in vals[i + 1:]:
            if len(r) <= max(i_note, i_cle):
                continue
            k, n = str(r[i_cle]).strip(), str(r[i_note]).strip()
            if k and n and k not in out:        # la 1re occurrence gagne
                out[k] = n
        print(f"  {CLASSEMENT_TAB} : en-tetes en ligne {i + 1} "
              f"(cle « {cle} »), {len(out)} note(s).", flush=True)
        return out

    print(f"  ⚠️ {CLASSEMENT_TAB} : aucune ligne portant « note » ET une cle "
          f"({'/'.join(CLES)}) dans les 40 premieres lignes. En-tetes vus en "
          f"ligne 1 : {vals[0][:12] if vals else '(vide)'}", file=sys.stderr)
    return {}


def tirages_par_serie(lignes: List[Dict]) -> Dict[str, int]:
    """⚠️ MAX, PAS SOMME (le supply est celui de la SERIE, recopie par rarete)."""
    out: Dict[str, int] = {}
    for r in lignes:
        s = str(r.get("series_uuid") or "").strip()
        v = _num(r.get(COL_SUPPLY))
        if s and v:
            out[s] = max(out.get(s, 0), v)
    return out


def construire(lignes: List[Dict], listings: Dict[str, int] = None,
               notes: Dict[str, str] = None) -> List[List]:
    listings, notes = listings or {}, notes or {}
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
                    (r.get("edition_type") or "").strip(), supply,
                    listings.get(uid, ""),          # "" = INCONNU, pas zero
                    notes.get(s, "")])
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
    listings = lire_listings(sh)
    notes = lire_notes(sh)
    rows = construire(lignes, listings, notes)
    if not rows:
        # On n'ECRASE PAS un CSV valide par un fichier vide : un export rate ne
        # doit pas eteindre les alertes.
        print("⛔ 0 comic exporte — on ne touche pas au CSV existant.",
              file=sys.stderr)
        return 3
    ecrire(rows)
    petits = sum(1 for r in rows if r[5] <= 1000)
    avec_l = sum(1 for r in rows if r[6] != "")
    avec_n = sum(1 for r in rows if r[7])
    print(f"📚 {len(rows)} elements exportes (≤ {SUPPLY_MAX} ex.), dont "
          f"{petits} a tirage ≤ 1 000 · {avec_l} avec un nombre d'offres · "
          f"{avec_n} avec une note de classement -> {CSV_PATH}", flush=True)
    if not avec_l:
        print("⚠️ AUCUN nombre d'offres : le filtre anti-« 8 offres a 1,75 $ » "
              "sera INACTIF. Verifie que comic_prices tourne (il remplit "
              "market_totalListings dans 🟠H-PRIX).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
