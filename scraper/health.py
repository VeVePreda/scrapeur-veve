"""
Sante du pipeline — bloc "fraicheur des sources" ecrit sur 🏠ACCUEIL.

Pourquoi : Preda verifiait la sante des jobs en collant les logs GitHub dans le
chat. Ce module rend l'etat visible d'un coup d'oeil sur la page d'accueil :
une ligne par source avec le dernier run, son statut et un feu 🟢/🟠/🔴.
Un cookie StackR expire, un job en echec ou un cron saute se voient sans
ouvrir GitHub.

Sources :
  * 🤖LOGS (LOGS_TAB) — dernier run par source (retention 7 j). Sources
    quotidiennes : catalogue, chain, dynamic, floors, comic_prices, logos,
    pseudos, wallets. Manuelles (informatif, jamais rouge) : blog, ledger,
    cohorts, market.
  * 🔥H-BURNS — le tracker burns tourne sur le repo jetonveve et ne logge pas
    dans 🤖LOGS : on lit la date de la derniere ligne de l'onglet.

Seuils (sources quotidiennes) : 🟢 <= 30 h ; 🟠 <= 54 h ou statut SKIPPED ;
🔴 au-dela, statut FAILED*, ou source absente des logs.
Detection cookie StackR mort : details contenant "verifiedVeVe=OFF" ou "401"
-> note "🔑 cookie ?" et au moins 🟠.

Ecriture : bloc ANCRE en A60 de 🏠ACCUEIL (sous le dashboard, ~45 lignes max),
via ws.update SANS clear — ne touche pas au reste de l'onglet. Comme
ledger._write_dashboard efface l'onglet a chaque run, ledger re-appelle
write_health() juste apres. Le daily.yml l'execute chaque nuit (step sante).

Env : SHEET_ID ; HEALTH_NOW ("YYYY-MM-DD HH:MM:SS" UTC, tests uniquement).
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
from typing import Dict, List, Optional, Tuple

from scraper.sheets import _client, _open_worksheet, LOGS_TAB

STATS_TAB = os.environ.get("STATS_TAB", "📊 STATS")
ANCHOR_ROW = 48                     # ancrage par defaut (sous le tableau quotidien)
BURNS_TAB = "🔥H-BURNS"

DAILY = "daily"
MANUAL = "manual"

# (source dans 🤖LOGS, libelle affiche, cadence)
SOURCES = [
    ("catalogue", "Catalogue (froid + marques)", DAILY),
    ("chain", "CollectChain (activite)", DAILY),
    ("dynamic", "Editions (GraphQL)", DAILY),
    ("floors", "Floor collectibles", DAILY),
    ("comic_prices", "Prix + floor comics", DAILY),
    ("logos", "Logos marques", DAILY),
    ("pseudos", "Pseudos StackR", DAILY),
    ("wallets", "Registre wallets", DAILY),
    ("blog", "Blog VeVe", MANUAL),
    ("ledger", "Grand livre / analytics", MANUAL),
    ("cohorts", "Cohortes", MANUAL),
]

GREEN_HOURS = 30      # un quotidien qui a tourne dans les ~30 h = OK
ORANGE_HOURS = 54     # au-dela de ~2 crons rates -> rouge


def _now() -> _dt.datetime:
    env = os.environ.get("HEALTH_NOW", "").strip()
    if env:
        return _dt.datetime.strptime(env, "%Y-%m-%d %H:%M:%S")
    return _dt.datetime.utcnow()


def _parse_ts(x: str) -> Optional[_dt.datetime]:
    x = (x or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y-%m-%d"):
        try:
            return _dt.datetime.strptime(x[:19], fmt)
        except ValueError:
            continue
    return None


def _age_label(hours: float) -> str:
    if hours < 1:
        return "il y a <1 h"
    if hours < 48:
        return f"il y a {int(round(hours))} h"
    return f"il y a {hours / 24:.1f} j"


def _read_last_logs(sh) -> Dict[str, Tuple[Optional[_dt.datetime], str, str]]:
    """{source -> (ts du dernier run, status, details)} depuis 🤖LOGS."""
    out: Dict[str, Tuple[Optional[_dt.datetime], str, str]] = {}
    try:
        ws = sh.worksheet(LOGS_TAB)
        rows = ws.get_all_records()
    except Exception:
        return out
    for r in rows:
        src = str(r.get("source", "")).strip()
        if not src:
            continue
        ts = _parse_ts(str(r.get("ts_utc", "")))
        if ts is None:
            continue
        cur = out.get(src)
        if cur is None or (cur[0] is not None and ts >= cur[0]):
            out[src] = (ts, str(r.get("status", "")).strip(),
                        str(r.get("details", "")).strip())
    return out


def _read_burns_last(sh) -> Optional[str]:
    """Derniere date presente dans 🔥H-BURNS (le tracker vit sur jetonveve)."""
    try:
        ws = sh.worksheet(BURNS_TAB)
        dates = [str(r.get("date", "")).strip() for r in ws.get_all_records()]
        dates = [d for d in dates if d]
        return max(dates) if dates else None
    except Exception:
        return None


def _status_row(label: str, kind: str, ts: Optional[_dt.datetime], status: str,
                details: str, now: _dt.datetime) -> List[str]:
    note = ""
    up = status.upper()
    if "VERIFIEDVEVE=OFF" in details.upper() or "401" in details:
        note = "🔑 cookie ?"
    if ts is None:
        if kind == MANUAL:
            return [label, "hors logs (purge 7 j)", status or "-", "⚪"]
        return [label, "jamais vu (purge 7 j)", status or "-", "🔴"]
    hours = (now - ts).total_seconds() / 3600.0
    last = ts.strftime("%Y-%m-%d %H:%M")
    age = _age_label(hours)
    if kind == MANUAL:
        return [label, last, status or "-", f"⚪ {age}"]
    if up.startswith("FAIL"):
        light = "🔴"
    elif up == "SKIPPED" or note:
        light = "🟠"
    elif hours <= GREEN_HOURS:
        light = "🟢"
    elif hours <= ORANGE_HOURS:
        light = "🟠"
    else:
        light = "🔴"
    stat = (status or "-") + (f" {note}" if note else "")
    return [label, last, stat, f"{light} {age}"]


def build_rows(sh, now: Optional[_dt.datetime] = None) -> List[List[str]]:
    now = now or _now()
    logs = _read_last_logs(sh)
    rows: List[List[str]] = [
        ["🩺 SANTE DES SOURCES", "", "",
         f"maj : {now.strftime('%Y-%m-%d %H:%M')} UTC"],
        ["source", "dernier run (UTC)", "statut", "fraicheur"],
    ]
    for src, label, kind in SOURCES:
        ts, status, details = logs.get(src, (None, "", ""))
        rows.append(_status_row(label, kind, ts, status, details, now))
    # Burns (jetonveve, pas dans 🤖LOGS) : fraicheur par la derniere date du tab.
    last_day = _read_burns_last(sh)
    if last_day is None:
        rows.append(["Burns OMI (jetonveve)", "onglet vide/absent", "-", "🔴"])
    else:
        d = _parse_ts(last_day)
        days = (now.date() - d.date()).days if d else 99
        light = "🟢" if days <= 2 else ("🟠" if days <= 3 else "🔴")
        rows.append(["Burns OMI (jetonveve)", f"{last_day} (🔥H-BURNS)", "-",
                     f"{light} il y a {days} j"])
    return rows


def write_health(sh, now: Optional[_dt.datetime] = None,
                 anchor_row: Optional[int] = None) -> int:
    """Ecrit le bloc a l'ancre A<anchor_row> de 📊 STATS (sans clear)."""
    row = anchor_row or ANCHOR_ROW
    rows = build_rows(sh, now)
    ws = _open_worksheet(sh, STATS_TAB, cols=6)
    ws.update(range_name=f"A{row}", values=rows,
              value_input_option="RAW")
    try:
        ws.format(f"{row}:{row + 1}", {"textFormat": {"bold": True}})
    except Exception:
        pass
    return len(rows)


def main() -> int:
    sheet_id = os.environ.get("SHEET_ID", "").strip()
    if not sheet_id:
        print("SHEET_ID env var is not set.", file=sys.stderr)
        return 2
    sh = _client().open_by_key(sheet_id)
    n = write_health(sh)
    print(f"Sante des sources : bloc de {n} lignes ecrit sur {STATS_TAB} "
          f"(ancre A{ANCHOR_ROW}).", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
