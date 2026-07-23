# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/export_elements_v3.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier depose au
# mauvais endroit ne provoque aucune erreur : il dort.

"""🌉 LE PONT v3 — elements.csv fabrique depuis la CHAINE (CollectChain).

Suite du spike GO-catalogue (23/07). L'IDENTITE du catalogue vient de la
metadata on-chain d'un transfert (`total.token_instance.metadata`), pas du
tracker communautaire :

    name, category, rarity, edition_type, supply, brand, licensor  <- CHAINE

Ce que la chaine NE porte PAS reste OFF-CHAIN et est REPORTE de l'export
officiel (data/elements.csv) tel quel — donc identique, donc 0 ecart au
comparateur :

    series_uuid, first_public, listings, note, atl, atl_date, ath, ath_date

    (spike : series_uuid absent de la chaine ; first_public = first_available_edition
     un NUMERO, pas la dropDate ; aucun prix on-chain.)

Ce module ecrit `data/elements_v3.csv` et NE TOUCHE PAS a data/elements.csv.
La bascule se juge au comparateur (scraper.compare_elements, pilote par
ELEMENTS_V2=data/elements_v3.csv) : identite a 0 sur plusieurs jours, comme le
pont elements. export_elements.py (v1) et export_elements_v2.py (tracker)
restent en repli.

En-tete OCTET POUR OCTET identique a v1/v2.

--- ALIMENTATION ---
La metadata catalogue n'est PAS dans l'archive des transferts (schema reduit).
v3 doit la MOISSONNER en direct : un echantillon de metadata (le plus recent)
par veve_uuid. La moisson pleine (~26 800 types) = un run GitHub, comme tout
collecteur (le sandbox ne fait que des sondes ciblees). `collapse()` accepte
n'importe quel iterable de transferts bruts (API live, JSONL moissonne...).
"""

from __future__ import annotations

import csv
import os
import re
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

# En-tete identique v1/v2/v3.
ENTETE = ["veve_uuid", "series_uuid", "name", "category", "rarity",
          "edition_type", "supply", "first_public", "listings", "note",
          "brand", "licensor", "atl", "atl_date", "ath", "ath_date"]

CSV_V3 = os.environ.get("ELEMENTS_V3", "data/elements_v3.csv")
CSV_OFFICIEL = os.environ.get("ELEMENTS_CSV", "data/elements.csv")
SUPPLY_MAX = int(os.environ.get("ELEMENTS_SUPPLY_MAX", "0"))   # 0 = tout

# Les 8 colonnes OFF-CHAIN reportees de l'officiel (cf. docstring).
OFFCHAIN_COLS = ["series_uuid", "first_public", "listings", "note",
                 "atl", "atl_date", "ath", "ath_date"]

# `collectible_type_image.<veve_uuid>` ou `comic_cover.<veve_uuid>` — le 1er uuid
# apres le prefixe EST le veve_uuid du catalogue (le 2e n'est PAS le series_uuid,
# verifie 23/07 : il differe du series_uuid officiel -> series_uuid reste off-chain).
_UUID_RE = re.compile(
    r"(collectible_type_image|comic_cover)\."
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.I,
)


def _norm_rarity(r: Any) -> str:
    """'Ultra Rare' -> 'ULTRA_RARE' ; 'Rare' -> 'RARE' (format de l'officiel)."""
    s = str(r or "").strip()
    return re.sub(r"[\s\-]+", "_", s).upper()


def _num(x) -> int:
    try:
        return int(float(str(x).replace(",", ".").replace(" ", "") or 0))
    except (TypeError, ValueError):
        return 0


def catalogue_from_instance(inst: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Un `token_instance` -> les champs catalogue tires de la CHAINE.

    Retourne None si l'instance n'est pas rattachable (pas de veve_uuid ET pas
    de metadata exploitable). category deduite de l'URL image, sinon des cles
    de metadata (comics : comicNumber/artists ; collectibles : editionType)."""
    if not isinstance(inst, dict):
        return None
    md = inst.get("metadata") or {}
    if not isinstance(md, dict):
        md = {}
    img = inst.get("image_url") or inst.get("media_url") or ""
    m = _UUID_RE.search(img)
    if m:
        cat = "collectible" if m.group(1).lower().startswith("collectible") \
            else "comic"
        uuid = m.group(2).lower()
    else:
        # Repli : deviner la categorie par les cles de metadata (uuid inconnu).
        if any(k in md for k in ("comicNumber", "coverArtists", "artists")):
            cat, uuid = "comic", ""
        elif any(k in md for k in ("editionType", "rarity")):
            cat, uuid = "collectible", ""
        else:
            return None
    if not uuid and not md:
        return None

    rarity = _norm_rarity(md.get("rarity"))
    total_ed = _num(md.get("totalEditions"))
    series = str(md.get("series") or "").strip()

    if cat == "comic":
        comic_no = str(md.get("comicNumber") or "").strip()
        start_year = str(md.get("startYear") or "").strip()
        # name = "{serie} #{numero} ({annee})" (calibre sur l'officiel 23/07).
        name = f"{series} #{comic_no}"
        if start_year:
            name = f"{name} ({start_year})"
        edition_type = comic_no                  # comics : edition_type = comicNumber
        brand = series                           # comics : brand = la serie
        licensor = str(md.get("publisher") or "").strip()  # comics : licensor = publisher
    else:
        name = str(md.get("name") or "").strip()
        et = str(md.get("editionType") or "").strip()
        edition_type = "" if et in ("0", "0.0") else et.upper()
        brand = str(md.get("brand") or "").strip()
        licensor = str(md.get("licensor") or "").strip()

    return {
        "veve_uuid": uuid,
        "category": cat,
        "name": name,
        "rarity": rarity,
        "edition_type": edition_type,
        "supply": total_ed,
        "brand": brand,
        "licensor": licensor,
        "series": series,       # sert au MAX-par-serie des comics
    }


def _order(item: Dict[str, Any]) -> Tuple[int, int]:
    """Cle de recence d'un transfert brut : (block, log_index)."""
    b = item.get("block_number")
    b = b if isinstance(b, int) else _num(b)
    li = item.get("log_index")
    li = li if isinstance(li, int) else _num(li)
    return (b, li)


def collapse(transfers: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Iterable de transferts BRUTS (API) -> {veve_uuid: catalogue le plus recent}.

    « Derniere metadata par item » : si un item reapparait, on garde celle du
    transfert au (block, log_index) le plus GRAND (metadata la plus a jour)."""
    best: Dict[str, Dict[str, Any]] = {}
    best_ord: Dict[str, Tuple[int, int]] = {}
    for t in transfers:
        inst = (((t.get("total") or {}).get("token_instance")) or {})
        cat = catalogue_from_instance(inst)
        if not cat or not cat["veve_uuid"]:
            continue
        uid = cat["veve_uuid"]
        o = _order(t)
        if uid not in best or o >= best_ord[uid]:
            best[uid] = cat
            best_ord[uid] = o
    return best


def lire_officiel(chemin: str) -> Dict[str, Dict[str, str]]:
    """{veve_uuid: ligne officielle} — source des colonnes OFF-CHAIN reportees."""
    out: Dict[str, Dict[str, str]] = {}
    if not os.path.exists(chemin):
        return out
    with open(chemin, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            uid = (r.get("veve_uuid") or "").strip()
            if uid:
                out[uid] = r
    return out


def construire_v3(catalogue: Dict[str, Dict[str, Any]],
                  officiel: Dict[str, Dict[str, str]]) -> List[List]:
    """Le catalogue on-chain + les colonnes off-chain reportees -> lignes ENTETE."""
    # tirage des comics = MAX par serie (comme v1/v2), calcule sur la CHAINE.
    max_par_serie: Dict[str, int] = {}
    for c in catalogue.values():
        if c["category"] == "comic" and c["series"] and c["supply"]:
            s = c["series"]
            max_par_serie[s] = max(max_par_serie.get(s, 0), c["supply"])

    rows: List[List] = []
    for uid, c in catalogue.items():
        off = officiel.get(uid, {})
        if c["category"] == "comic":
            supply = max_par_serie.get(c["series"], c["supply"])
        else:
            supply = c["supply"]
        if SUPPLY_MAX and supply and supply > SUPPLY_MAX:
            continue
        rows.append([
            uid,
            (off.get("series_uuid") or "").strip(),   # OFF-CHAIN reporte
            c["name"],
            c["category"],
            c["rarity"],
            c["edition_type"],
            supply if supply else "",
            (off.get("first_public") or "").strip(),  # OFF-CHAIN reporte
            (off.get("listings") or "").strip(),       # OFF-CHAIN reporte
            (off.get("note") or "").strip(),           # OFF-CHAIN reporte
            c["brand"],
            c["licensor"],
            (off.get("atl") or "").strip(),            # OFF-CHAIN reporte
            (off.get("atl_date") or "").strip(),
            (off.get("ath") or "").strip(),
            (off.get("ath_date") or "").strip(),
        ])
    rows.sort(key=lambda l: (l[3], l[6] if l[6] != "" else 0, l[2]))
    return rows


def ecrire(rows: List[List], chemin: str) -> None:
    os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
    with open(chemin, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(ENTETE)
        w.writerows(rows)


def main() -> int:
    """Moissonne la metadata chaine, reporte l'off-chain, ecrit elements_v3.csv.

    La moisson pleine tourne en GitHub Actions (le sandbox ne joint pas l'API en
    volume). Ici on branche `fetch_transfers` de collectchain, qui pagine +
    reprend proprement ; ELEMENTS_V3_CUTOFF borne la profondeur du balayage."""
    try:
        from scraper import collectchain as cc
    except Exception as e:                                     # noqa: BLE001
        print(f"⛔ import collectchain impossible ({e}).", file=sys.stderr)
        return 2

    import datetime as _dt
    days = int(os.environ.get("ELEMENTS_V3_LOOKBACK_DAYS", "120"))
    cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=days)
    plateau = int(os.environ.get("ELEMENTS_V3_PLATEAU_PAGES", "300"))
    print(f"Moisson metadata chaine depuis {cutoff:%Y-%m-%d} "
          f"(arret couverture apres {plateau} pages sans nouveau type) …",
          flush=True)

    catalogue = harvest(cc, cutoff, plateau)
    if len(catalogue) < 50:
        print(f"⛔ moisson trop maigre ({len(catalogue)} types) — rien d'ecrit.",
              file=sys.stderr)
        return 3
    officiel = lire_officiel(CSV_OFFICIEL)
    rows = construire_v3(catalogue, officiel)
    if not rows:
        print("⛔ 0 ligne — rien d'ecrit.", file=sys.stderr)
        return 3
    # ACCUMULATION : des dispatches successifs cumulent la couverture. Les items
    # deja moissonnes lors d'un run PRECEDENT (presents dans le CSV_V3 graine)
    # mais PAS revus cette fois sont conserves — on ne reperd jamais un type.
    if os.environ.get("ELEMENTS_V3_ACCUMULATE", "").strip() in ("1", "true", "oui"):
        rows = _accumuler(rows, CSV_V3)
    ecrire(rows, CSV_V3)
    nc = sum(1 for r in rows if r[3] == "comic")
    print(f"🌉 v3 : {len(rows)} elements ({nc} comics, {len(rows) - nc} "
          f"collectibles) depuis {len(catalogue)} items on-chain -> {CSV_V3}",
          flush=True)
    return 0


def _accumuler(rows: List[List], graine_csv: str) -> List[List]:
    """Fusionne la moisson du run avec la graine (CSV_V3 d'un run precedent) :
    les uuid de la graine ABSENTS du run courant sont conserves tels quels.
    Le run courant fait foi pour un uuid revu (metadata plus recente)."""
    if not os.path.exists(graine_csv):
        return rows
    vus = {r[0] for r in rows}
    gardes = 0
    with open(graine_csv, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            uid = (r.get("veve_uuid") or "").strip()
            if not uid or uid in vus:
                continue
            rows.append([r.get(c, "") for c in ENTETE])
            gardes += 1
    if gardes:
        print(f"  accumulation : +{gardes} type(s) conserve(s) d'un run "
              f"precedent (couverture cumulee : {len(rows)}).", flush=True)
    rows.sort(key=lambda l: (l[3], _num(l[6]) if l[6] != "" else 0, l[2]))
    return rows


def harvest(cc, cutoff, plateau_pages: int = 300) -> Dict[str, Dict[str, Any]]:
    """Pagine /transfers newest-first et COLLECTE la metadata catalogue au vol,
    avec DEUX garde-fous pour ne pas balayer des millions de lignes pour rien :

      * arret sur COUVERTURE : si `plateau_pages` pages defilent sans AUCUN
        nouveau veve_uuid, l'univers actif est couvert -> on s'arrete (0 =
        desarme). Les types dormants se completeront via le scan profond.
      * arret sur CUTOFF : transferts plus vieux que `cutoff`.
      * plafond dur `ELEMENTS_V3_MAX_PAGES` (securite budget).

    Retourne directement {veve_uuid: catalogue le plus recent} — collapse
    integre a la pagination (metadata au (block,log_index) le plus grand).
    Journalise sa progression (sinon un run long semble plante)."""
    import time
    session = cc._session()
    params: Dict[str, Any] = {}
    pages = 0
    max_pages = int(os.environ.get("ELEMENTS_V3_MAX_PAGES", "20000"))
    best: Dict[str, Dict[str, Any]] = {}
    best_ord: Dict[str, Tuple[int, int]] = {}
    since_new = 0
    newest_date = ""
    while pages < max_pages:
        data = cc._get(session, cc.TRANSFERS_URL, params)
        items = data.get("items", [])
        if not items:
            break
        new_this = 0
        stop = False
        for it in items:
            ts = cc._parse_ts(it.get("timestamp"))
            if ts is not None and ts < cutoff:
                stop = True
                break
            if not newest_date and it.get("timestamp"):
                newest_date = str(it["timestamp"])[:10]
            inst = (((it.get("total") or {}).get("token_instance")) or {})
            cat = catalogue_from_instance(inst)
            if not cat or not cat["veve_uuid"]:
                continue
            uid = cat["veve_uuid"]
            o = _order(it)
            if uid not in best:
                new_this += 1
            if uid not in best or o >= best_ord[uid]:
                best[uid] = cat
                best_ord[uid] = o
        pages += 1
        since_new = 0 if new_this else since_new + 1
        if pages % 25 == 0:
            oldest = "?"
            try:
                oldest = str(items[-1].get("timestamp"))[:10]
            except Exception:
                pass
            print(f"    … {pages} pages · {len(best)} types · "
                  f"{since_new} page(s) sans nouveau · jusqu'a {oldest}",
                  flush=True)
        if plateau_pages and since_new >= plateau_pages:
            print(f"  ✓ couverture plafonnee : {plateau_pages} pages sans "
                  f"nouveau type -> arret ({len(best)} types).", flush=True)
            break
        nxt = data.get("next_page_params")
        if stop or not nxt:
            print(f"  ✓ {'cutoff' if stop else 'fin des transferts'} atteint "
                  f"-> arret ({len(best)} types, {pages} pages).", flush=True)
            break
        params = dict(nxt)
        time.sleep(cc.PAUSE_BETWEEN_PAGES)
    return best


if __name__ == "__main__":
    sys.exit(main())
