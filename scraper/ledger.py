"""
Analytics — GRAND LIVRE DES POSSESSIONS (socle des finalites 2/4/5/6).

Rejoue l'archive des transferts CollectChain (Release "chain-archive" du repo
astronema, public) pour reconstruire QUI DETIENT QUEL EXEMPLAIRE aujourd'hui,
puis en derive les agregats whales + concentration dans le Sheet.

Principe : l'archive est produite du PRESENT vers le PASSE (fichiers
transfers_run001, 002, ... = du plus recent au plus vieux ; newest-first dans
chaque fichier). Donc le PREMIER transfert rencontre pour une edition
(uuid, edition) est le PLUS RECENT -> il donne le detenteur actuel.

    to == 0x0 / coffre burn   -> edition BRULEE (plus de detenteur)
    to == escrow marche       -> EN VENTE : detenteur = le vendeur (from), listed=1
    sinon                     -> detenteur = to

Sorties :
    - grand livre complet  -> data/ledger.csv.gz (uuid, edition, holder, listed)
      (commite dans preda ; trop gros pour le Sheet : ~2,5 M lignes)
    - onglet 📊A-WHALES         : top wallets par nb d'exemplaires detenus
    - onglet 📊A-CONCENTRATION  : par collectible (offre, holders, Gini, top1)

/!\ EXACT seulement quand le scan CollectChain est TERMINE (sinon les editions
non tradees depuis le mur du scan manquent). Avant : partiel.

Env : GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID,
      ARCHIVE_DIR (dossier des .csv.gz telecharges, defaut "dl"),
      WHALES_TOP (defaut 200), LEDGER_OUT (defaut data/ledger.csv.gz).
"""

from __future__ import annotations

import csv
import glob
import gzip
import os
import sys
import time
from collections import Counter, defaultdict
from typing import Dict, List, Tuple

from scraper.sheets import _client, _open_worksheet, append_log

try:
    from scraper.collectchain import ZERO, MARKET_ESCROW, BURN_SINK
except Exception:  # valeurs de secours si l'import echoue
    ZERO = "0x0000000000000000000000000000000000000000"
    MARKET_ESCROW = "0xb1af72a77b9065c55cda0680b86655a79b62e42c"
    BURN_SINK = "0x39e3816a8c549ec22cd1a34a8cf7034b3941d8b1"

BURN_TO = {ZERO, BURN_SINK}
WHALES_TAB = "📊A-WHALES"
CONC_TAB = "📊A-CONCENTRATION"
WHALES_HEADER = ["rank", "wallet", "pseudo", "editions_held",
                 "distinct_collectibles", "listed"]
CONC_HEADER = ["veve_uuid", "name", "category", "circulating", "holders",
               "gini", "top1_pct"]


# ---------------------------------------------------------------------------
# Rejeu de l'archive -> grand livre
# ---------------------------------------------------------------------------

def _archive_files(folder: str) -> List[str]:
    """Les .csv.gz tries du PLUS RECENT au plus vieux (runNNN croissant)."""
    files = glob.glob(os.path.join(folder, "*transfers*run*.csv.gz"))
    if not files:
        files = glob.glob(os.path.join(folder, "*.csv.gz"))
    return sorted(files)  # run001 (recent) -> runNNN (vieux)


def build_ledger(folder: str) -> Dict[Tuple[str, str], Tuple[str, int]]:
    """{(uuid, edition) -> (holder, listed)}. holder="" si brulee."""
    ledger: Dict[Tuple[str, str], Tuple[str, int]] = {}
    seen = ledger  # meme dict : la presence de la cle = "deja vu le plus recent"
    n_rows = 0
    for path in _archive_files(folder):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                uid = (row.get("veve_uuid") or "").strip().lower()
                ed = (row.get("edition") or "").strip()
                if not uid or not ed:
                    continue
                key = (uid, ed)
                if key in seen:
                    continue  # deja le transfert le plus recent
                to = (row.get("to") or "").strip().lower()
                frm = (row.get("from") or "").strip().lower()
                kind = (row.get("kind") or "").strip()
                n_rows += 1
                if to in BURN_TO or kind == "burn":
                    ledger[key] = ("", 0)            # brulee
                elif to == MARKET_ESCROW or kind == "listing":
                    ledger[key] = (frm, 1)           # en vente -> vendeur
                else:
                    ledger[key] = (to, 0)
    print(f"Grand livre : {len(ledger)} editions vues ({n_rows} transferts "
          f"les plus recents retenus).", flush=True)
    return ledger


def save_ledger(ledger: Dict[Tuple[str, str], Tuple[str, int]], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["veve_uuid", "edition", "holder", "listed"])
        for (uid, ed), (holder, listed) in ledger.items():
            w.writerow([uid, ed, holder, listed])


# ---------------------------------------------------------------------------
# Agregats
# ---------------------------------------------------------------------------

def _gini(counts: List[int]) -> float:
    xs = sorted(counts)
    n = len(xs)
    s = sum(xs)
    if n == 0 or s == 0:
        return 0.0
    cum = sum((i + 1) * x for i, x in enumerate(xs))
    return round((2 * cum) / (n * s) - (n + 1) / n, 4)


def aggregate(ledger, pseudos: Dict[str, str], names: Dict[str, Tuple[str, str]],
              top: int) -> Tuple[List[List], List[List]]:
    held = Counter()                       # holder -> nb editions
    distinct = defaultdict(set)            # holder -> {uuid}
    listed = Counter()                     # holder -> nb en vente
    per_uuid = defaultdict(Counter)        # uuid -> (holder -> count)

    for (uid, ed), (holder, is_listed) in ledger.items():
        if not holder:                     # brulee
            continue
        held[holder] += 1
        distinct[holder].add(uid)
        if is_listed:
            listed[holder] += 1
        per_uuid[uid][holder] += 1

    # WHALES : top wallets par exemplaires detenus
    whales: List[List] = []
    for rank, (wallet, n) in enumerate(held.most_common(top), 1):
        whales.append([rank, wallet, pseudos.get(wallet, ""), n,
                       len(distinct[wallet]), listed.get(wallet, 0)])

    # CONCENTRATION : par collectible
    conc: List[List] = []
    for uid, holders in per_uuid.items():
        counts = list(holders.values())
        circ = sum(counts)
        nm, cat = names.get(uid, ("", ""))
        conc.append([uid, nm, cat, circ, len(holders), _gini(counts),
                     round(100.0 * max(counts) / circ, 2) if circ else 0])
    conc.sort(key=lambda r: -r[3])         # par offre en circulation desc
    return whales, conc


# ---------------------------------------------------------------------------
# Lecture Sheet (pseudos + noms catalogue) et ecriture
# ---------------------------------------------------------------------------

def _read_pseudos(sh) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        ws = sh.worksheet("🟣C-PSEUDOS")
    except Exception:
        return out
    for r in ws.get_all_records():
        w = str(r.get("wallet_imx", "")).strip().lower()
        u = str(r.get("username", "")).strip()
        if w and u:
            out[w] = u
    return out


def _read_names(sh) -> Dict[str, Tuple[str, str]]:
    out: Dict[str, Tuple[str, str]] = {}
    for tab, cat in (("🔵C-COLLECTIBLE", "collectible"), ("🟢C-COMICS", "comic")):
        try:
            ws = sh.worksheet(tab)
        except Exception:
            continue
        for r in ws.get_all_records():
            u = str(r.get("veve_uuid", "")).strip().lower()
            if u:
                out[u] = (str(r.get("name", "")), cat)
    return out


def _write(sh, tab: str, header: List[str], rows: List[List]) -> None:
    ws = _open_worksheet(sh, tab, cols=len(header))
    ws.clear()
    grid = [header] + rows
    for i in range(0, len(grid), 50000):
        rng = "A1" if i == 0 else None
        chunk = grid[i:i + 50000]
        if i == 0:
            ws.update(range_name="A1", values=chunk, value_input_option="RAW")
        else:
            ws.append_rows(chunk, value_input_option="RAW")
    try:
        ws.freeze(rows=1)
        ws.format("1:1", {"textFormat": {"bold": True}})
    except Exception:
        pass


def main() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        print("ERROR: SHEET_ID requis.", file=sys.stderr)
        return 2
    folder = os.environ.get("ARCHIVE_DIR", "dl")
    top = int(os.environ.get("WHALES_TOP", "200"))
    out = os.environ.get("LEDGER_OUT", "data/ledger.csv.gz")

    files = _archive_files(folder)
    if not files:
        print(f"Aucune archive .csv.gz dans '{folder}' — abandon.", file=sys.stderr)
        try:
            append_log(sheet_id, "ledger", "FAILED_NO_DATA", f"no gz in {folder}")
        except Exception:
            pass
        return 1
    print(f"{len(files)} fichier(s) d'archive a rejouer.", flush=True)

    ledger = build_ledger(folder)
    save_ledger(ledger, out)

    sh = _client().open_by_key(sheet_id)
    pseudos = _read_pseudos(sh)
    names = _read_names(sh)
    whales, conc = aggregate(ledger, pseudos, names, top)

    _write(sh, WHALES_TAB, WHALES_HEADER, whales)
    _write(sh, CONC_TAB, CONC_HEADER, conc)

    summary = {"status": "OK", "editions": len(ledger), "whales": len(whales),
               "collectibles": len(conc), "pseudos": len(pseudos),
               "duration": f"{time.time()-t0:.0f}s"}
    try:
        append_log(sheet_id, "ledger", "OK",
                   "; ".join(f"{k}={v}" for k, v in summary.items() if k != "status"))
    except Exception as e:
        print(f"log warning: {e}", flush=True)
    print(f"Done. {summary}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
