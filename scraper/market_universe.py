"""🏪 UNIVERS DE MARCHÉ — combien d'éléments ont réellement un marché ?

Question de Preda (12/07) : « pourquoi 6 011 ? y a-t-il des items qui ne sont
pas pris en charge ? »

REPONSE : `publicVeve.getElements` ne renvoie PAS tout le catalogue (18 681
produits = 2 631 collectibles + 16 050 comics) mais les **6 011 elements QUI
ONT UN MARCHE** — collectibles ET couvertures de comics melanges, tries par
capitalisation decroissante. Les items jamais listes n'y figurent pas... et de
toute facon on ne peut pas les acheter. C'est donc le bon perimetre pour les
alertes, mais il fallait le mesurer et le SUIVRE dans le temps.

Ce module balaie getElements une fois par jour (~61 requetes) et enregistre :
    date · elements · collectibles · comics · avec_offre (floor > 0) ·
    sans_offre · avec_volume (echanges recents) · capitalisation totale ·
    floor median · part du catalogue couverte
-> onglet cache `_MarketUniverse` (1 ligne/jour, append) que 📊 STATS affiche
   en bloc avec son historique.

PAGINATION : le parametre est `page` (1-based) — `cursor`/`offset`/`skip` sont
IGNORES EN SILENCE (piege verifie le 12/07). Auto-controle inclus.

Env : SHEET_ID, MU_LIMIT (100), MU_CATALOGUE (18681 = taille du catalogue).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import statistics
import sys
import time
import urllib.parse
from typing import Dict, List

import requests

from scraper.sheets import _client, _open_worksheet, append_log

URL = "https://www.stackr.world/api/trpc/publicVeve.getElements?input="
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

TAB = "_MarketUniverse"
HEADER = ["date", "elements", "collectibles", "comics", "aberrants",
          "avec_volume", "vendus_7j", "pct_vendus_7j", "market_cap",
          "floor_median", "floor_moyen", "catalogue", "couverture_pct"]

# ELEMENTS QUI SE VENDENT VRAIMENT (demande Preda 12/07, apres la decouverte
# de floor_watch : sur 6 006 elements ayant un floor, seuls ~1 744 ont une
# vente reelle en 7 jours. Les deux tiers du « marche » sont des VITRINES sans
# acheteur — c'est la que se cachaient les fausses affaires a +1 028 %).
# On compte les elements distincts vendus dans le flux getVeveTransactions.
TX_URL = "https://www.stackr.world/api/trpc/publicVeve.getVeveTransactions?input="
SALES_PAGES = int(os.environ.get("MU_SALES_PAGES", "120"))   # ~12 000 tx ≈ 7 j
SALES_TYPES = ("MARKET_FIXED", "MARKET_AUCTION", "MARKET_STACKR")

# PRIX ABERRANTS (constate au 1er run reel, 12/07) : « Faces of The ADDICTION »
# est liste a 42 420 420 420 420 (un troll : 4242...), ce qui gonflait a lui
# seul la capitalisation a 593 886 milliards. Au-dela de ce plafond, l'element
# est compte a part (colonne `aberrants`) et EXCLU de la capitalisation et des
# statistiques de floor. Rien n'est jete : il reste dans le compte `elements`.
MAX_FLOOR = float(os.environ.get("MU_MAX_FLOOR", "10000000"))   # 10 M gems

LIMIT = int(os.environ.get("MU_LIMIT", "100"))
CATALOGUE = int(os.environ.get("MU_CATALOGUE", "18681"))
RETRIES = int(os.environ.get("MU_RETRIES", "6"))
TIMEOUT = int(os.environ.get("MU_TIMEOUT", "45"))
PAUSE = float(os.environ.get("MU_PAUSE", "0.2"))


def _f(x) -> float:
    try:
        return float(str(x).replace(",", ".") or 0)
    except (TypeError, ValueError):
        return 0.0


def fetch_page(page: int, session=None):
    payload = {"limit": LIMIT}
    if page > 1:
        payload["page"] = page          # `page`, PAS `cursor` (verifie 12/07)
    url = URL + urllib.parse.quote(json.dumps({"json": payload},
                                              separators=(",", ":")))
    s = session or requests
    for attempt in range(RETRIES):
        try:
            r = s.get(url, headers={"User-Agent": UA,
                                    "Accept": "application/json"},
                      timeout=TIMEOUT)
            if r.status_code >= 500:
                raise RuntimeError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json().get("result", {}).get("data", {}).get("json")
        except Exception as e:
            if attempt == RETRIES - 1:
                print(f"    page {page} abandonnee : {e}", flush=True)
                return None
            wait = min(60, 3 * (2 ** attempt))
            print(f"    page {page} : {e} — nouvel essai dans {wait} s",
                  flush=True)
            time.sleep(wait)
    return None


def elements_vendus(session=None, pages: int = SALES_PAGES) -> set:
    """Les elements ayant AU MOINS UNE vente reelle sur la fenetre."""
    s = session or requests.Session()
    vus: set = set()
    for page in range(1, pages + 1):
        payload = {"limit": 100}
        if page > 1:
            payload["cursor"] = page
            payload["direction"] = "forward"
        url = TX_URL + urllib.parse.quote(
            json.dumps({"json": payload}, separators=(",", ":")))
        try:
            r = s.get(url, headers={"User-Agent": UA,
                                    "Accept": "application/json"},
                      timeout=TIMEOUT)
            r.raise_for_status()
            items = r.json().get("result", {}).get("data", {}).get("json") or []
        except Exception as e:
            print(f"    ventes page {page} : {e} — on s'arrete la.", flush=True)
            break
        if not items:
            break
        for it in items:
            if (str(it.get("veve_type")) in SALES_TYPES
                    and str(it.get("status")) == "COMPLETE"):
                uid = str(it.get("element_id") or "")
                if uid:
                    vus.add(uid)
        time.sleep(PAUSE)
    return vus


def sweep(session=None) -> List[Dict]:
    """Tous les elements ayant un marche. Liste vide = balayage non fiable."""
    s = session or requests.Session()
    out: Dict[str, Dict] = {}
    page, total, tete = 1, None, None
    failed = 0
    while page <= 200:
        d = fetch_page(page, s)
        if d is None:
            failed += 1
            page += 1
            continue
        rows = d.get("data") or []
        if not rows:
            break
        if total is None:
            total = int(d.get("totalCount") or 0)
        prem = str(rows[0].get("id") or "")
        if page == 1:
            tete = prem
        elif prem == tete:
            print("  !! PAGINATION CASSEE (page 2 == page 1) — balayage "
                  "abandonne, aucune ligne ecrite.", flush=True)
            return []
        for e in rows:
            uid = str(e.get("id") or "")
            if uid:
                out[uid] = e
        if total and len(out) >= total:
            break
        page += 1
        time.sleep(PAUSE)
    if failed:
        print(f"  {failed} page(s) sautee(s).", flush=True)
    if total and len(out) < 0.9 * total:
        print(f"  balayage trop incomplet ({len(out)}/{total}) — ignore.",
              flush=True)
        return []
    return list(out.values())


def summarize(elements: List[Dict], jour: str = "", vendus: set = None) -> List:
    """Une ligne de bilan pour la journee (les prix aberrants sont ecartes des
    agregats mais restes comptes a part)."""
    jour = jour or _dt.date.today().isoformat()
    coll = sum(1 for e in elements
               if str(e.get("element_type")) == "COLLECTIBLE_TYPE")
    comics = sum(1 for e in elements
                 if str(e.get("element_type")) == "COMIC_COVER")
    sains = [e for e in elements
             if 0 < _f(e.get("floor_market_price")) <= MAX_FLOOR]
    aberrants = sum(1 for e in elements
                    if _f(e.get("floor_market_price")) > MAX_FLOOR)
    floors = [_f(e.get("floor_market_price")) for e in sains]
    vol = sum(1 for e in elements if _f(e.get("volume")) > 0)
    cap = sum(_f(e.get("market_cap")) for e in sains)
    med = statistics.median(floors) if floors else 0
    moy = sum(floors) / len(floors) if floors else 0
    n = len(elements)
    ids = {str(e.get("id") or "") for e in elements}
    nv = len((vendus or set()) & ids)
    return [jour, n, coll, comics, aberrants, vol, nv,
            round(100.0 * nv / n, 1) if (n and vendus is not None) else "",
            round(cap), round(med, 2), round(moy, 2), CATALOGUE,
            round(100.0 * n / CATALOGUE, 1) if CATALOGUE else ""]


def write_tab(sh, ligne: List) -> int:
    """Onglet cache : 1 ligne par jour (upsert)."""
    ws = _open_worksheet(sh, TAB, cols=len(HEADER))
    vals = ws.get_all_values()
    keep: Dict[str, List] = {}
    for r in vals[1:] if vals else []:
        if r and str(r[0]).strip() and str(r[0]) != "date":
            keep[str(r[0]).strip()] = r
    keep[str(ligne[0])] = ligne
    ws.clear()
    ws.update(range_name="A1",
              values=[list(HEADER)] + [keep[d] for d in sorted(keep)],
              value_input_option="RAW")
    try:
        ws.hide()
    except Exception:
        pass
    return len(keep)


def main() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID", "").strip()
    if not sheet_id:
        print("SHEET_ID env var is not set.", file=sys.stderr)
        return 2
    print("Balayage de l'univers de marche (getElements)...", flush=True)
    elements = sweep()
    if not elements:
        print("Balayage non fiable — rien n'est ecrit (l'historique reste "
              "propre).", file=sys.stderr)
        try:
            append_log(sheet_id, "market_universe", "FAILED",
                       "balayage incomplet")
        except Exception:
            pass
        return 1
    print("Ventes reelles (getVeveTransactions)...", flush=True)
    vendus = elements_vendus()
    print(f"   {len(vendus)} elements ont au moins une vente sur la fenetre.",
          flush=True)
    ligne = summarize(elements, vendus=vendus)
    sh = _client().open_by_key(sheet_id)
    jours = write_tab(sh, ligne)
    resume = dict(zip(HEADER, ligne))
    resume["jours_historises"] = jours
    resume["duration"] = f"{time.time() - t0:.0f}s"
    try:
        append_log(sheet_id, "market_universe", "OK",
                   "; ".join(f"{k}={v}" for k, v in resume.items()))
    except Exception as e:
        print(f"log warning: {e}", flush=True)
    print(f"Univers de marche : {resume}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# FIN market_universe.py v1
