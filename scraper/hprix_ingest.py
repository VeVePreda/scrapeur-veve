"""🌉 hprix_ingest — le CONSOMMATEUR du pont veille → 🟠H-PRIX.

jetonveve (PUBLIC) observe le floor VeVe des collectibles 1x/h et ecrit les
CHANGEMENTS dans data/hprix_feed.csv (colonnes uuid,name,categorie,floor_usd,ts —
le floor est en gems ~ $, EXACTEMENT la meme unite que `market_lowestOffer` de
🟠H-PRIX ; verifie 15/07 : Sea Queen = 5 000 000 des deux cotes -> AUCUNE
conversion). Ici, cote preda (le SEUL a avoir l'acces Sheet), on lit ce feed et
on append les floors dans 🟠H-PRIX via sheets.sync_dynamic (append-on-change deja
en place la-bas), en portant l'heure d'OBSERVATION comme snapshot_date.

Un WATERMARK (data/hprix_watermark.txt = le dernier ts ingere) evite de retraiter
le feed a chaque run — sinon une valeur ancienne, differente de l'etat courant,
se re-appendrait en double.

Le feed est PUBLIC (repo fanablefrance/jetonveve) : le workflow le recupere en
sparse-checkout SANS token. S'il manque, on ne touche a rien (le pont s'eteint
tout seul — c'est le pont elements.csv, a l'envers).

Env : GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID,
      HPRIX_FEED_IN   (defaut _jetonveve/data/hprix_feed.csv),
      HPRIX_WATERMARK (defaut data/hprix_watermark.txt).
"""

from __future__ import annotations

import csv
import os
import sys
import time

from scraper import sheets

FEED_IN = os.environ.get("HPRIX_FEED_IN", "_jetonveve/data/hprix_feed.csv")
WATERMARK = os.environ.get("HPRIX_WATERMARK", "data/hprix_watermark.txt")


def _num(x):
    if x in (None, ""):
        return None
    try:
        f = float(str(x).replace(",", "."))
        return int(f) if f.is_integer() else f
    except (ValueError, TypeError):
        return None


def _lire_watermark() -> str:
    try:
        with open(WATERMARK, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def _ecrire_watermark(ts: str) -> None:
    os.makedirs(os.path.dirname(WATERMARK) or ".", exist_ok=True)
    with open(WATERMARK, "w", encoding="utf-8") as f:
        f.write(ts)


def lire_feed(chemin: str, apres: str):
    """(items, max_ts). items = les lignes de ts STRICTEMENT > watermark, dans
    l'ordre chronologique (le feed est deja ecrit dans l'ordre). Rend
    (None, apres) si le feed est absent -> le pont ne fait rien ce tour.

    On compare les ts en CHAINES : le format "YYYY-MM-DD HH:MM:SS" (UTC) est
    trie lexicographiquement comme chronologiquement. Le `>` STRICT evite de
    retraiter le dernier lot (plusieurs floors partagent la meme seconde de
    rafraichissement) ; un rafraichissement suivant a une seconde plus tardive."""
    items = []
    max_ts = apres or ""
    try:
        with open(chemin, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                ts = (r.get("ts") or "").strip()
                uid = (r.get("uuid") or "").strip()
                floor = _num(r.get("floor_usd"))
                if not ts or not uid or floor is None:
                    continue
                if apres and ts <= apres:
                    continue
                cat = (r.get("categorie") or "").strip() or "collectible"
                items.append({
                    "veve_uuid": uid,
                    "name": r.get("name") or uid[:8],
                    "category": cat,
                    "market_lowestOffer": floor,
                    "snapshot_date": ts,          # l'heure d'OBSERVATION, pas d'ingestion
                })
                if ts > max_ts:
                    max_ts = ts
    except FileNotFoundError:
        return None, apres
    return items, max_ts


def main() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        print("ERROR: SHEET_ID env var is required.", file=sys.stderr)
        return 2

    wm = _lire_watermark()
    items, max_ts = lire_feed(FEED_IN, wm)
    if items is None:
        print(f"🌉 feed absent ({FEED_IN}) — le pont ne fait rien ce tour.",
              flush=True)
        return 0
    if not items:
        print(f"🌉 rien de neuf depuis {wm or '(debut)'} — 0 floor ingere.",
              flush=True)
        return 0

    summary = sheets.sync_dynamic(items, sheet_id)
    # On n'avance le watermark qu'APRES une ecriture OK : si le Sheet a echoue,
    # on retentera les memes lignes au prochain run (la recolte est sacree).
    if summary.get("status") == "OK":
        _ecrire_watermark(max_ts)
    summary["feed_rows"] = len(items)
    summary["watermark"] = max_ts
    summary["duration"] = f"{time.time() - t0:.0f}s"
    try:
        sheets.append_run_log(sheet_id, summary, source="hprix_bridge")
    except Exception as e:
        print(f"run log warning: {e}", flush=True)

    print(f"🌉 pont H-PRIX : {len(items)} changement(s) lus, "
          f"{summary.get('rows_appended')} appende(s), "
          f"watermark → {max_ts}, en {time.time()-t0:.0f}s.", flush=True)
    return 0 if summary.get("status") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
