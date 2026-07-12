"""Flux VeVe PUBLIC — revenue reel, ventes en gems, pseudos (12/07/2026).

UNE source pour trois besoins (endpoint public, AUCUN cookie) :
  GET https://www.stackr.world/api/trpc/publicVeve.getVeveTransactions
      ?input={"json":{"limit":100,"cursor":<page>}}

Sonde du 12/07 :
  * `cursor` = numero de PAGE (1 = plus recent, absent = page 1) et `limit` =
    taille de page ; cursor=2/limit=5 renvoie bien les items 6 a 10 ;
  * la pagination profonde MARCHE (page 100 x limit 100 = 10 000 tx = 6 jours
    en arriere) — pas de mur a ~750 comme getAllLatestSales_v2 ;
  * rythme observe : ~1 700 tx/jour ;
  * `price` est un decimal NORMALISE (gems ~ $, meme pour MARKET_STACKR : une
    Ultra Rare vendue « 14.00 » ne peut pas etre 14 OMI) — a re-valider au 1er
    run contre _MarketRevenue (memes jours, meme ordre de grandeur).

veve_type :
  * CART_FIAT   : achat boutique en monnaie fiat   -> REVENUE DROP reel
  * STORE_GEM   : achat boutique en gems           -> REVENUE DROP reel
  * MARKET_FIXED: vente marche VeVe (gems)         -> REVENUE MARKET (VeVe)
  * MARKET_STACKR : vente marche StackR            -> REVENUE MARKET (StackR)
  * NFT_TRANSFER: jambe de reglement d'un trade (MEME nft/prix, quelques
    secondes apres) -> EXCLU des revenus (sinon double comptage)
  * ADMIN_COLLECTIBLE_TRANSFER : livraison VeVe (support/rewards) -> EXCLU

Sorties :
  * onglet cache `_VeveRevenue` (upsert par jour PT, RAW natif) ;
  * `data/veve_tx_daily.csv` (commite, meme contenu — sert de repli/historique) ;
  * paires (wallet -> pseudo) recoltees au passage, fusionnees dans 🟣C-PSEUDOS
    (remplace peu a peu les lookups StackR sous cookie : ici c'est PUBLIC).

Deux modes :
  * QUOTIDIEN (defaut) : re-lit la fenetre des VEVE_TX_DAYS derniers jours (3)
    et REMPLACE ces jours -> idempotent, ~50 requetes/jour ;
  * BACKFILL (VEVE_TX_BACKFILL=true) : descend jusqu'a VEVE_TX_UNTIL (ou la
    genese), dedup par veve_id, un seul run (le decalage du curseur pendant le
    run est absorbe par la dedup). A lancer sur le repo PUBLIC (minutes
    illimitees).

Env : SHEET_ID, VEVE_TX_DAYS (3), VEVE_TX_LIMIT (100), VEVE_TX_MAX_PAGES
      (400 en quotidien, 30000 en backfill), VEVE_TX_UNTIL (YYYY-MM-DD),
      VEVE_TX_PAUSE (0.25), VEVE_TX_TIMEOUT (60), VEVE_TX_CSV, VEVE_TX_PSEUDOS
      (true), VEVE_TX_BACKFILL (false).
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
import os
import sys
import time
import urllib.parse
from collections import Counter, defaultdict
from typing import Any, Dict, List, Tuple

import requests

from scraper.sheets import _client, _open_worksheet, append_log

TRPC = ("https://www.stackr.world/api/trpc/publicVeve.getVeveTransactions"
        "?input=")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

REV_TAB = "_VeveRevenue"
REV_HEADER = ["date", "drop_usd", "drop_tx", "market_veve_usd",
              "market_veve_tx", "market_stackr_usd", "market_stackr_tx",
              "transfers", "admin_tx"]

DROP_TYPES = ("CART_FIAT", "STORE_GEM")
MKT_VEVE = "MARKET_FIXED"
MKT_STACKR = "MARKET_STACKR"
TRANSFER = "NFT_TRANSFER"
ADMIN = "ADMIN_COLLECTIBLE_TRANSFER"

DAYS = int(os.environ.get("VEVE_TX_DAYS", "3"))
LIMIT = int(os.environ.get("VEVE_TX_LIMIT", "100"))
PAUSE = float(os.environ.get("VEVE_TX_PAUSE", "0.25"))
TIMEOUT = int(os.environ.get("VEVE_TX_TIMEOUT", "60"))
CSV_PATH = os.environ.get("VEVE_TX_CSV", "data/veve_tx_daily.csv")
BACKFILL = os.environ.get("VEVE_TX_BACKFILL", "false").lower() == "true"
UNTIL = os.environ.get("VEVE_TX_UNTIL", "").strip()
WITH_PSEUDOS = os.environ.get("VEVE_TX_PSEUDOS", "true").lower() != "false"
MAX_PAGES = int(os.environ.get("VEVE_TX_MAX_PAGES",
                               "30000" if BACKFILL else "400"))

# wallets systeme VeVe (jamais des pseudos d'utilisateurs)
SYSTEM_ADDRS = {
    "0xc4817870a6a75704985be4f9933643a27739afc1",   # VeveStore
    "0xdb721de5f825fcb3d2dbe3a4778e34e43ae7c095",   # admin (livraisons)
    "0x7be178ba43a9828c22997a3ec3640497d88d2fd3",   # VeveCollection (officiel)
}


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

def _pt(created_at: str) -> str:
    """created_at (ISO UTC) -> jour PACIFIQUE (comme tout le reste du projet)."""
    s = (created_at or "").strip().replace("Z", "+00:00")
    try:
        dt = _dt.datetime.fromisoformat(s)
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:
        return (dt - _dt.timedelta(hours=8)).date().isoformat()


def _today_pt() -> str:
    return _pt(_dt.datetime.now(_dt.timezone.utc).isoformat())


def _f(x) -> float:
    try:
        return float(str(x).replace(",", ".") or 0)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def fetch_page(cursor: int, session=None, limit: int = LIMIT) -> List[Dict]:
    """Une page du flux (cursor = numero de page, 1 = la plus recente)."""
    payload = {"limit": limit}
    if cursor > 1:
        payload["cursor"] = cursor
        payload["direction"] = "forward"
    url = TRPC + urllib.parse.quote(
        json.dumps({"json": payload}, separators=(",", ":")))
    s = session or requests
    for attempt in range(3):
        try:
            r = s.get(url, headers={"User-Agent": UA,
                                    "Accept": "application/json"},
                      timeout=TIMEOUT)
            if r.status_code >= 500:
                raise RuntimeError(f"HTTP {r.status_code}")
            r.raise_for_status()
            data = r.json()
            return (data.get("result", {}).get("data", {}).get("json")) or []
        except Exception as e:
            if attempt == 2:
                raise
            print(f"    page {cursor} : {e} — retry", flush=True)
            time.sleep(2 + 2 * attempt)
    return []


# ---------------------------------------------------------------------------
# Agregation
# ---------------------------------------------------------------------------

def _blank() -> Dict[str, float]:
    return {"drop_usd": 0.0, "drop_tx": 0, "market_veve_usd": 0.0,
            "market_veve_tx": 0, "market_stackr_usd": 0.0,
            "market_stackr_tx": 0, "transfers": 0, "admin_tx": 0}


def aggregate(items: List[Dict], daily: Dict[str, Dict],
              pseudos: Dict[str, str], types: Dict = None) -> None:
    """Ventile une page dans {jour PT -> compteurs} et recolte les pseudos.

    Seules les transactions COMPLETE comptent dans les revenus (les PENDING
    seront recomptees au run suivant : la fenetre de 3 jours est REJOUEE)."""
    for it in items:
        day = _pt(it.get("created_at"))
        if not day:
            continue
        d = daily.setdefault(day, _blank())
        typ = str(it.get("veve_type") or "")
        if types is not None:
            # inventaire de TOUS les types vus (+ montant) : garde-fou contre
            # un type de vente qu'on ignorerait (enchere, panier gem, etc.)
            t = types.setdefault(typ or "(vide)", [0, 0.0])
            t[0] += 1
            t[1] += _f(it.get("price"))
        price = _f(it.get("price"))
        done = str(it.get("status") or "") == "COMPLETE"
        if typ == TRANSFER:
            d["transfers"] += 1
        elif typ == ADMIN:
            d["admin_tx"] += 1
        elif typ in DROP_TYPES and done:
            d["drop_usd"] += price
            d["drop_tx"] += 1
        elif typ == MKT_VEVE and done:
            d["market_veve_usd"] += price
            d["market_veve_tx"] += 1
        elif typ == MKT_STACKR and done:
            d["market_stackr_usd"] += price
            d["market_stackr_tx"] += 1
        if WITH_PSEUDOS:
            for who in ("buyer", "seller"):
                u = it.get(f"{who}_username")
                a = str(it.get(f"{who}_address") or "").strip().lower()
                if u and a and a not in SYSTEM_ADDRS:
                    pseudos[a] = str(u)


def walk(days: int = DAYS, until: str = "", max_pages: int = MAX_PAGES,
         session=None) -> Tuple[Dict[str, Dict], Dict[str, str], Dict]:
    """Descend le flux page par page. S'arrete :
      * quotidien : des qu'on passe sous la fenetre de `days` jours ;
      * backfill  : a `until` (YYYY-MM-DD) ou quand une page revient vide.
    Dedup par veve_id (le curseur glisse pendant un long run : les nouvelles
    tx qui arrivent decalent les pages -> quelques doublons possibles)."""
    stop = until
    if not stop:
        d0 = _dt.date.fromisoformat(_today_pt()) - _dt.timedelta(days=days - 1)
        stop = d0.isoformat()
    daily: Dict[str, Dict] = {}
    pseudos: Dict[str, str] = {}
    types: Dict[str, list] = {}
    seen: set = set()
    s = session or requests.Session()
    pages = dupes = kept = 0
    oldest = ""
    for cursor in range(1, max_pages + 1):
        items = fetch_page(cursor, s)
        pages += 1
        if not items:
            print(f"  page {cursor} vide -> fin du flux.", flush=True)
            break
        fresh = []
        for it in items:
            vid = str(it.get("veve_id") or "")
            if vid and vid in seen:
                dupes += 1
                continue
            if vid:
                seen.add(vid)
            fresh.append(it)
        aggregate(fresh, daily, pseudos, types)
        kept += len(fresh)
        oldest = _pt(items[-1].get("created_at"))
        if cursor % 25 == 0 or cursor <= 3:
            print(f"  page {cursor} : {kept} tx, jusqu'au {oldest}", flush=True)
        if oldest and oldest < stop:
            break
        time.sleep(PAUSE)
    # le jour le plus ancien atteint est PARTIEL (on s'est arrete au milieu)
    if oldest and oldest in daily and oldest < stop:
        daily.pop(oldest, None)
    known = set(DROP_TYPES) | {MKT_VEVE, MKT_STACKR, TRANSFER, ADMIN}
    print("  types rencontres (tx / somme des prix) :", flush=True)
    for t, (n, tot) in sorted(types.items(), key=lambda x: -x[1][0]):
        flag = "" if t in known else "   <-- TYPE INCONNU (non compte !)"
        print(f"    {t:32s} {n:6d}   {tot:12.2f} ${flag}", flush=True)
    inconnus = {t: v[0] for t, v in types.items() if t not in known}
    stats = {"pages": pages, "tx": kept, "doublons": dupes,
             "jusqu_au": oldest, "jours": len(daily), "pseudos": len(pseudos)}
    if inconnus:
        stats["TYPES_INCONNUS"] = inconnus
    return daily, pseudos, stats


# ---------------------------------------------------------------------------
# Ecritures
# ---------------------------------------------------------------------------

def _rows(daily: Dict[str, Dict]) -> List[List]:
    out = []
    for d in sorted(daily):
        v = daily[d]
        out.append([d, round(v["drop_usd"], 2), v["drop_tx"],
                    round(v["market_veve_usd"], 2), v["market_veve_tx"],
                    round(v["market_stackr_usd"], 2), v["market_stackr_tx"],
                    v["transfers"], v["admin_tx"]])
    return out


def _read_csv() -> Dict[str, List]:
    out: Dict[str, List] = {}
    try:
        with open(CSV_PATH, encoding="utf-8") as f:
            for r in csv.reader(f):
                if r and r[0] != "date":
                    out[r[0]] = r
    except FileNotFoundError:
        pass
    return out


def save_csv(rows: List[List]) -> int:
    """Upsert par jour (les jours rejoues ECRASENT les anciens)."""
    keep = _read_csv()
    for r in rows:
        keep[str(r[0])] = [str(x) for x in r]
    os.makedirs(os.path.dirname(CSV_PATH) or ".", exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(REV_HEADER)
        for d in sorted(keep):
            w.writerow(keep[d])
    return len(keep)


def write_tab(sh, rows: List[List]) -> int:
    """Onglet cache _VeveRevenue : upsert par date, nombres RAW natifs."""
    ws = _open_worksheet(sh, REV_TAB, cols=len(REV_HEADER))
    keep: Dict[str, List] = {}
    try:
        from gspread.utils import ValueRenderOption
        vals = ws.get_all_values(
            value_render_option=ValueRenderOption.unformatted)
    except Exception:
        vals = ws.get_all_values()
    for r in vals[1:] if vals else []:
        if r and str(r[0]).strip() and str(r[0]) != "date":
            keep[str(r[0]).strip()] = r
    for r in rows:
        keep[str(r[0])] = r
    ws.clear()
    ws.update(range_name="A1",
              values=[list(REV_HEADER)] + [keep[d] for d in sorted(keep)],
              value_input_option="RAW")
    try:
        ws.hide()
    except Exception:
        pass
    return len(keep)


def merge_pseudos(sh, pairs: Dict[str, str]) -> Dict[str, int]:
    """Fusionne les paires wallet->pseudo PUBLIQUES dans 🟣C-PSEUDOS.

    Remplace progressivement les lookups StackR sous cookie : ici la source est
    publique. On ne DETRUIT jamais une ligne existante — on complete le wallet
    manquant et on ajoute les pseudos inconnus."""
    if not pairs:
        return {"nouveaux": 0, "wallets_completes": 0}
    try:
        from scraper.stackr import PSEUDOS_TAB, PSEUDOS_HEADER
    except Exception:
        PSEUDOS_TAB, PSEUDOS_HEADER = "🟣C-PSEUDOS", ["username", "wallet_imx"]
    ws = _open_worksheet(sh, PSEUDOS_TAB, cols=len(PSEUDOS_HEADER))
    vals = ws.get_all_values()
    if not vals:
        vals = [list(PSEUDOS_HEADER)]
    head = vals[0]
    i_user = head.index("username") if "username" in head else 0
    i_wal = head.index("wallet_imx") if "wallet_imx" in head else 1
    i_src = head.index("source") if "source" in head else None
    i_fs = head.index("first_seen") if "first_seen" in head else None
    by_user = {}
    for r in vals[1:]:
        if r and len(r) > i_user and str(r[i_user]).strip():
            by_user[str(r[i_user]).strip().lower()] = r
    today = _dt.date.today().isoformat()
    added = filled = 0
    for addr, user in pairs.items():
        row = by_user.get(user.lower())
        if row is None:
            row = [""] * len(head)
            row[i_user] = user
            row[i_wal] = addr
            if i_src is not None:
                row[i_src] = "veve_tx"
            if i_fs is not None:
                row[i_fs] = today
            vals.append(row)
            by_user[user.lower()] = row
            added += 1
        else:
            while len(row) < len(head):
                row.append("")
            if not str(row[i_wal]).strip():
                row[i_wal] = addr
                filled += 1
    ws.clear()
    ws.update(range_name="A1", values=vals, value_input_option="RAW")
    return {"nouveaux": added, "wallets_completes": filled}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID", "").strip()
    if not sheet_id:
        print("SHEET_ID env var is not set.", file=sys.stderr)
        return 2
    mode = "BACKFILL" if BACKFILL else f"quotidien ({DAYS} j)"
    print(f"Flux VeVe public — mode {mode}, limit={LIMIT}, "
          f"max_pages={MAX_PAGES}", flush=True)
    try:
        daily, pseudos, stats = walk(DAYS, UNTIL if BACKFILL else "")
    except Exception as e:
        print(f"veve_tx FAILED: {e}", file=sys.stderr)
        try:
            append_log(sheet_id, "veve_tx", "FAILED", str(e)[:200])
        except Exception:
            pass
        return 1
    rows = _rows(daily)
    summary: Dict[str, Any] = dict(stats)
    if rows:
        summary["csv_jours"] = save_csv(rows)
        sh = _client().open_by_key(sheet_id)
        summary["tab_jours"] = write_tab(sh, rows)
        if WITH_PSEUDOS and pseudos:
            summary.update(merge_pseudos(sh, pseudos))
        # apercu (verification humaine dans les logs)
        for r in rows[-3:]:
            print(f"  {r[0]} : drop {r[1]} $ ({r[2]} tx) · market VeVe {r[3]} $ "
                  f"({r[4]}) · market StackR {r[5]} $ ({r[6]})", flush=True)
    summary["duration"] = f"{time.time() - t0:.0f}s"
    try:
        append_log(sheet_id, "veve_tx", "OK",
                   "; ".join(f"{k}={v}" for k, v in summary.items()))
    except Exception as e:
        print(f"log warning: {e}", flush=True)
    print(f"veve_tx : {summary}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# FIN veve_tx.py v1
