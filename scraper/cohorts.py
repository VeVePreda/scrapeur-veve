"""
Analytics — cohortes de NOUVEAUX ENTRANTS (finalite 5).

Compte combien de wallets apparaissent pour la 1ere fois par jour / semaine /
mois / annee, a partir du registre wallet -> first_seen (fusion des 3 sources) :

    - CollectChain deep  (repo astronema, public)   wallet_registry_deep.csv
    - IMX deep           (repo Paolo, public)        wallet_registry_imx.csv
    - maj quotidienne    (repo preda, local)         wallet_registry_daily.csv

Fusion : pour chaque wallet, first_seen = la DATE LA PLUS ANCIENNE vue dans
n'importe quelle source (un vetéran 2022 vu sur IMX prime sur sa réapparition
2026 sur CollectChain). Ecrit l'agregat dans l'onglet 📅A-COHORTES du Sheet.

/!\ Chiffres EXACTS uniquement quand les 2 scans profonds sont TERMINES
(sinon first_seen des anciens wallets est encore trop recent). Avant : apercu.

Env : GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID,
      REGISTRY_URLS (URLs raw des CSV distants, separees par des virgules),
      REGISTRY_LOCAL (chemins locaux, defaut data/wallet_registry_daily.csv),
      COHORTS_TAB (defaut 📅A-COHORTES).
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import os
import sys
import time
from typing import Dict, List

import requests

from scraper.sheets import _client, _open_worksheet, _now, append_log
from scraper import sheet_format as _fmt

COHORTS_TAB = os.environ.get("COHORTS_TAB", "📅A-COHORTES")
HEADER = ["grain", "period", "new_wallets", "cumulative", "pct_total"]
DEFAULT_URLS = [
    "https://raw.githubusercontent.com/astronemagame-maker/astronema/main/data/wallet_registry_deep.csv",
    "https://raw.githubusercontent.com/lepaolo/paolo/main/data/wallet_registry_imx.csv",
]


def _iter_rows(text: str):
    for row in csv.DictReader(io.StringIO(text)):
        w = (row.get("wallet") or "").strip().lower()
        fs = (row.get("first_seen") or "").strip()
        if w and fs:
            yield w, fs


def _merge_first_seen() -> Dict[str, str]:
    """{wallet -> plus ancienne first_seen} sur toutes les sources."""
    first: Dict[str, str] = {}
    # NB: `or` et pas get(k, defaut) — une env var DEFINIE mais VIDE ("") doit
    # retomber sur le defaut (sinon 0 source quand l'input workflow est vide).
    urls = [u.strip() for u in (os.environ.get("REGISTRY_URLS")
            or ",".join(DEFAULT_URLS)).split(",") if u.strip()]
    locals_ = [p.strip() for p in (os.environ.get("REGISTRY_LOCAL")
               or "data/wallet_registry_daily.csv").split(",") if p.strip()]

    sources = 0
    for url in urls:
        try:
            r = requests.get(url, timeout=120)
            if r.status_code != 200:
                print(f"    skip {url} (HTTP {r.status_code})", flush=True)
                continue
            n = 0
            for w, fs in _iter_rows(r.text):
                if w not in first or fs < first[w]:
                    first[w] = fs
                n += 1
            sources += 1
            print(f"    {url.split('/')[-1]} : {n} lignes.", flush=True)
        except Exception as e:
            print(f"    skip {url} ({e})", flush=True)
    for path in locals_:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            n = 0
            for w, fs in _iter_rows(f.read()):
                if w not in first or fs < first[w]:
                    first[w] = fs
                n += 1
        sources += 1
        print(f"    {path} : {n} lignes.", flush=True)
    print(f"Fusion : {len(first)} wallets uniques depuis {sources} source(s).",
          flush=True)
    return first


def _period(date: str, grain: str) -> str:
    """date 'YYYY-MM-DD' -> etiquette de periode selon le grain."""
    try:
        d = _dt.date.fromisoformat(date)
    except ValueError:
        return ""
    if grain == "year":
        return f"{d.year}"
    if grain == "month":
        return f"{d.year}-{d.month:02d}"
    if grain == "week":
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return date  # day


def build_rows(first: Dict[str, str]) -> List[List]:
    dates = list(first.values())
    total = len(dates) or 1
    rows: List[List] = []
    for grain in ("year", "month", "week", "day"):
        counts: Dict[str, int] = {}
        for d in dates:
            p = _period(d, grain)
            if p:
                counts[p] = counts.get(p, 0) + 1
        cum = 0
        for period in sorted(counts):
            n = counts[period]
            cum += n
            rows.append([grain, period, n, cum, round(100.0 * n / total, 2)])
    return rows


def main() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        print("ERROR: SHEET_ID requis.", file=sys.stderr)
        return 2

    print("Fusion des registres first_seen...", flush=True)
    first = _merge_first_seen()
    if not first:
        print("Aucun registre lisible — abandon (rien ecrit).", file=sys.stderr)
        try:
            append_log(sheet_id, "cohorts", "FAILED_NO_DATA",
                       "aucun registre first_seen accessible")
        except Exception:
            pass
        return 1

    rows = build_rows(first)
    sh = _client().open_by_key(sheet_id)
    ws = _open_worksheet(sh, COHORTS_TAB, cols=len(HEADER))
    ws.clear()
    ws.update(range_name="A1", values=[HEADER] + rows, value_input_option="RAW")
    try:
        ws.freeze(rows=1)
        ws.format("1:1", {"textFormat": {"bold": True}})
    except Exception:
        pass

    try:
        _fmt.format_tab(sh, COHORTS_TAB, HEADER, header_rows=1)
    except Exception as e:
        print(f"formatting warning: {e}", flush=True)

    months = sum(1 for r in rows if r[0] == "month")
    summary = {"status": "OK", "wallets": len(first), "rows": len(rows),
               "months": months, "duration": f"{time.time()-t0:.0f}s"}
    try:
        append_log(sheet_id, "cohorts", "OK",
                   "; ".join(f"{k}={v}" for k, v in summary.items() if k != "status"))
    except Exception as e:
        print(f"log warning: {e}", flush=True)
    print(f"Done. {summary}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
