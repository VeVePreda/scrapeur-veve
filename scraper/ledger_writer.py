#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ledger_writer — writer LEGER du ledger (preda, 16/07/2026).

Le calcul lourd (rejeu 38 M lignes) vit sur jetonveve (scraper/ledger_derived.py,
Release publique `analytics-derived`). Ici on TELECHARGE les CSV derives et on
ecrit les MEMES onglets Sheet que scraper/ledger.py, dont on IMPORTE les
fonctions d'ecriture (parite garantie au caractere pres) :

  _MonthlyPulse   <- pulse.csv           (22 col, mois + annees)
  _Reveils        <- reveils.csv
  🎯A-CORNERISATION <- corner_full.csv.gz (111 col)
  _WalletSize     <- wallet_size.csv     (upsert du mois)
  _Whales         <- whales.csv          (3 blocs, pseudo joint ici)
  🟣C-PSEUDOS      <- profiles_full.csv.gz (enrichissement profils + rangs)
  data/wallet_profiles.csv.gz commite (drop-in de l'ancien fichier prod).
  data/ledger.csv.gz N'EST PLUS commite : ledger_full.csv.gz vit dans la
  Release analytics-derived (trop gros pour git, ~limite GitHub 100 Mo).

Garde-fous : meta_ledger.csv obligatoire, run_date pas plus vieux que
MAX_AGE_DAYS (defaut 7), en-tete corner == CORNER_HEADER, en-tete pulse ==
PULSE_HEADER, sinon exit 1 SANS toucher au Sheet. RELEASE_BASE surchargeble
(secours N-1 : .../analytics-derived-prev).

Usage : python -m scraper.ledger_writer
Env   : SHEET_ID (requis), RUN_DATE, RUN_STEPS (all|whales,corner,size,
        pseudos,pulse,save), MAX_AGE_DAYS, RELEASE_BASE.
"""
import csv
import datetime as _dt
import gzip
import io
import os
import sys
import time
import urllib.request

from scraper.ledger import (CORNER_HEADER, CORNER_TAB, PULSE_HEADER,
                            RANK_COLS, WHALE_TYPES, _enrich_pseudos,
                            _open_with_retry, _read_pseudos, _save_profiles,
                            _write, _write_pulse, _write_reveils,
                            _write_size_history, _write_whales_flat)
from scraper.sheets import _open_worksheet, append_log
from scraper import sheet_format as _fmt

BASE = os.environ.get(
    "RELEASE_BASE",
    "https://github.com/fanablefrance/jetonveve/releases/download/analytics-derived")
MAX_AGE = int(os.environ.get("MAX_AGE_DAYS", "7"))
SIZE_HEADER_LOCAL = ["dimension", "bucket", "wallets", "pct_wallets",
                     "total", "pct_total"]
PROFILE_KEYS = ["holdings", "distinct_collectibles", "acquired", "sold",
                "retention", "median_hold_days", "collectorScore",
                "activityStatus", "engagementLevel", "value_store",
                "value_floor", "qty_bucket", "airdropOnly", "last_active",
                "listed"]


def _fetch(name: str) -> bytes:
    url = f"{BASE}/{name}"
    req = urllib.request.Request(url, headers={"User-Agent": "veve-ledger-writer/1.0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    print(f"  {name} : {len(data)/1e6:.1f} Mo", flush=True)
    return data


def _rows(name: str):
    data = _fetch(name)
    if name.endswith(".gz"):
        data = gzip.decompress(data)
    return list(csv.reader(io.StringIO(data.decode("utf-8"))))


def _num(x: str):
    """Coercition CSV -> types Sheet (les nombres redeviennent des nombres,
    les chaines restent des chaines, '' reste vide)."""
    if x == "":
        return ""
    try:
        return int(x)
    except ValueError:
        pass
    try:
        return float(x)
    except ValueError:
        return x


# ═══ PAGE 🎯 CORNÉRISATION (agrege, 16/07) : wallets par profil d'activite +
# supply potentiellement perdue sur les comptes fantomes. Onglet VISIBLE dedie ;
# la table 111-col 🎯A-CORNERISATION (source de la fiche 🦊) reste (cachee a la main).
CORNER_PAGE_TAB = "\U0001F3AF CORNÉRISATION"
_ACT_ORDER = ["Actif", "Engage", "Somnolant", "Inactif", "Desinscrit",
              "Fantome", "Non classe"]
_ACT_LABEL = {"Actif": "Actif (≤ 7 j)", "Engage": "Engagé (≤ 30 j)",
              "Somnolant": "Somnolant (≤ 90 j)", "Inactif": "Inactif (≤ 180 j)",
              "Desinscrit": "Désinscrit (≤ 365 j)", "Fantome": "Fantôme (> 365 j)",
              "Non classe": "Non classé"}


def _i(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _sp(n):
    return f"{n:,}".replace(",", " ")


def build_corner_page(wallets_rows, supply_rows, corner_rows, name_map, meta_d,
                      top_n=20, min_circ=500):
    """Retourne (grid, fmts, bolds). Logique PURE (testee hors ligne).
    corner_rows = corner_items.csv de la Release (data, sans en-tete), schema :
      0 uuid, 1 category, 2 circulating, 3 holders, 4 burned, 5 stock,
      6 ghost_supply, 7 ghost_wallets, 8 pct_ghost, 9 gini, 10 top1, 11 top10.
    name_map = {uuid: nom} depuis corner_full.csv.gz (meme run)."""
    wal = {r[0]: _i(r[1]) for r in wallets_rows if r and r[0]}
    sup = {r[0]: (_i(r[1]), _i(r[2]), _f(r[3])) for r in supply_rows if r and r[0]}
    tot_wal = sum(wal.values()) or 1
    tot_sup = sum(v[0] for v in sup.values()) or 1
    gs, gh, _ = sup.get("Fantome", (0, 0, 0))
    ds, _, _ = sup.get("Desinscrit", (0, 0, 0))
    ghost_pct = 100.0 * gs / tot_sup
    laps_pct = 100.0 * (gs + ds) / tot_sup
    rd = meta_d.get("run_date", "")
    g, fmts, bolds = [], [], []

    def row(*cells):
        g.append(list(cells))
        return len(g)

    bolds.append(row("\U0001F3AF CORNÉRISATION — SUPPLY IMMOBILISÉE & PROFILS D'ACTIVITÉ"))
    row(f"Source : run {rd} · {_sp(tot_wal)} wallets profilés · circulant {_sp(tot_sup)} exemplaires")
    row("")
    bolds.append(row("⚰️ SUPPLY POTENTIELLEMENT PERDUE"))
    bolds.append(row(f"{_sp(gs)} exemplaires", f"{ghost_pct:.1f} % du circulant",
                     f"sur {_sp(gh)} comptes FANTÔMES (muets > 365 j)"))
    row(f"+ Désinscrits : {_sp(gs + ds)} ex", f"{laps_pct:.1f} % (muets > 180 j)")
    row("« Potentiellement » : garde custodiale VeVe, un compte peut revenir "
        "— jamais une supply détruite (le burn est compté ailleurs).")
    row("")
    bolds.append(row("WALLETS PAR PROFIL D'ACTIVITÉ", "", ""))
    bolds.append(row("Profil", "Wallets", "% du total"))
    s0 = len(g) + 1
    for k in _ACT_ORDER:
        if k in wal:
            row(_ACT_LABEL[k], wal[k], round(100.0 * wal[k] / tot_wal, 1))
    e0 = len(g)
    bolds.append(row("TOTAL", tot_wal, 100.0))
    fmts.append((f"B{s0}:B{e0 + 1}", "#,##0"))
    fmts.append((f"C{s0}:C{e0 + 1}", "0.0"))
    row("")
    bolds.append(row("SUPPLY DÉTENUE PAR PROFIL DU DÉTENTEUR", "", "", ""))
    bolds.append(row("Profil", "Exemplaires", "% circulant", "Détenteurs"))
    s1 = len(g) + 1
    for k in _ACT_ORDER:
        if k in sup:
            sv, hv, _ = sup[k]
            row(_ACT_LABEL[k], sv, round(100.0 * sv / tot_sup, 1), hv)
    e1 = len(g)
    bolds.append(row("TOTAL", tot_sup, 100.0, ""))
    fmts.append((f"B{s1}:B{e1 + 1}", "#,##0"))
    fmts.append((f"C{s1}:C{e1 + 1}", "0.0"))
    fmts.append((f"D{s1}:D{e1}", "#,##0"))
    row("")
    items = []
    for r in corner_rows:
        if len(r) < 9:
            continue
        items.append((name_map.get(r[0], r[0]), r[1], _i(r[2]), _i(r[6]), _f(r[8])))

    def _tops(title, data):
        bolds.append(row(title, "", "", "", ""))
        bolds.append(row("Item", "Type", "Circulant", "Fantôme", "% fantôme"))
        s2 = len(g) + 1
        for nm, cat, ci, gsi, pg in data:
            row(nm, cat, ci, gsi, round(pg, 1))
        e2 = len(g)
        if e2 >= s2:
            fmts.append((f"C{s2}:D{e2}", "#,##0"))
            fmts.append((f"E{s2}:E{e2}", "0.0"))
        row("")

    _tops(f"TOP {top_n} — PLUS GROS CIMETIÈRES (supply fantôme absolue)",
          sorted(items, key=lambda x: x[3], reverse=True)[:top_n])
    _tops(f"TOP {top_n} — PLUS CORNÉRISÉS PAR LES FANTÔMES "
          f"(% fantôme, circulant ≥ {min_circ})",
          sorted([x for x in items if x[2] >= min_circ],
                 key=lambda x: x[4], reverse=True)[:top_n])
    return g, fmts, bolds


def _write_corner_page(sh, grid, fmts, bolds):
    """Ecrit l'onglet visible 🎯 CORNÉRISATION. Formatage en UN batch_update."""
    from gspread.utils import a1_range_to_grid_range as _gr
    ws = _open_worksheet(sh, CORNER_PAGE_TAB, cols=8)
    ws.clear()
    ws.update(range_name="A1", values=grid, value_input_option="RAW")
    reqs = []
    for a1, nf in fmts:
        reqs.append({"repeatCell": {"range": _gr(a1, ws.id),
            "cell": {"userEnteredFormat": {"numberFormat":
                     {"type": "NUMBER", "pattern": nf}}},
            "fields": "userEnteredFormat.numberFormat"}})
    for r in bolds:
        reqs.append({"repeatCell": {"range": _gr(f"A{r}:H{r}", ws.id),
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat.bold"}})
    reqs.append({"repeatCell": {"range": _gr("A1", ws.id),
        "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 13}}},
        "fields": "userEnteredFormat.textFormat"}})
    reqs.append({"repeatCell": {"range": _gr("A4:C4", ws.id),
        "cell": {"userEnteredFormat": {
            "backgroundColor": {"red": 0.82, "green": 0.18, "blue": 0.18},
            "textFormat": {"bold": True,
                           "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}},
        "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
    reqs.append({"repeatCell": {"range": _gr("A5:C5", ws.id),
        "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 12}}},
        "fields": "userEnteredFormat.textFormat"}})
    try:
        sh.batch_update({"requests": reqs})
    except Exception as e:
        print(f"corner page format warning: {e}", flush=True)
    if os.environ.get("CORNER_HIDE_DETAIL", "false").lower() == "true":
        try:
            d = sh.worksheet(CORNER_TAB)
            sh.batch_update({"requests": [{"updateSheetProperties": {
                "properties": {"sheetId": d.id, "hidden": True},
                "fields": "hidden"}}]})
        except Exception:
            pass


def main() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        print("ERROR: SHEET_ID requis.", file=sys.stderr)
        return 2
    rd = os.environ.get("RUN_DATE")
    today = _dt.date.fromisoformat(rd) if rd else _dt.date.today()
    steps = [s.strip() for s in
             (os.environ.get("RUN_STEPS") or "all").split(",") if s.strip()]

    def do(step: str) -> bool:
        return "all" in steps or step in steps

    # ── garde-fous AVANT d'ouvrir le Sheet ──────────────────────────────────
    print(f"Release : {BASE}", flush=True)
    meta = _rows("meta_ledger.csv")
    meta_d = dict(zip(meta[0], meta[1]))
    run_date = meta_d.get("run_date", "")
    age = (today - _dt.date.fromisoformat(run_date)).days
    print(f"meta : run_date={run_date} (age {age} j), circulant="
          f"{meta_d.get('circulant')}, holders={meta_d.get('holders')}", flush=True)
    if age > MAX_AGE:
        print(f"ERREUR : derives vieux de {age} j > MAX_AGE_DAYS {MAX_AGE} — "
              f"relancer analytics.yml sur jetonveve (ou RELEASE_BASE=...-prev).")
        return 1

    pulse = _rows("pulse.csv")
    if pulse[0] != PULSE_HEADER:
        print(f"ERREUR : en-tete pulse inattendu : {pulse[0]}")
        return 1
    pulse_rows = [[_num(c) for c in r] for r in pulse[1:]]

    reveils_rows = _rows("reveils.csv")[1:]
    reveils = {r[0]: int(r[1]) for r in reveils_rows}

    corner = _rows("corner_full.csv.gz")
    if corner[0] != CORNER_HEADER:
        print(f"ERREUR : en-tete corner inattendu ({len(corner[0])} col vs "
              f"{len(CORNER_HEADER)}).")
        return 1
    hm_idx = {CORNER_HEADER.index(c) for c in ("hm_prof_act", "hm_prof_ws", "hm_act_ws")}
    corner_rows = [[c if i in hm_idx else _num(c) for i, c in enumerate(r)]
                   for r in corner[1:]]

    size = _rows("wallet_size.csv")
    if size[0] != SIZE_HEADER_LOCAL:
        print(f"ERREUR : en-tete wallet_size inattendu : {size[0]}")
        return 1
    size_rows = [[_num(c) for c in r] for r in size[1:]]

    whales = _rows("whales.csv")[1:]          # block,rank,wallet,metric,...
    profs = _rows("profiles_full.csv.gz")
    p_hdr = profs[0]
    if p_hdr != ["wallet"] + PROFILE_KEYS:
        print(f"ERREUR : en-tete profiles inattendu : {p_hdr}")
        return 1

    # ── Sheet ────────────────────────────────────────────────────────────────
    sh = _open_with_retry(sheet_id)
    pseudos = _read_pseudos(sh)

    profiles = {}
    for r in profs[1:]:
        w = r[0]
        pr = {k: _num(v) for k, v in zip(PROFILE_KEYS, r[1:])}
        pr["pseudo"] = pseudos.get(w, "")
        profiles[w] = pr
    whale_blocks = []
    for title, key in WHALE_TYPES:
        rows = []
        for b, rank, w, metric, h, dc, vs, vf, sc, ac in whales:
            if b != title:
                continue
            rows.append([int(rank), w, pseudos.get(w, ""), _num(metric),
                         _num(h), _num(dc), _num(vs), _num(vf), sc, ac])
            if w in profiles:
                profiles[w][RANK_COLS[key]] = int(rank)
        rows.sort(key=lambda x: x[0])
        whale_blocks.append((title, rows))
    print(f"charge : {len(corner_rows)} items corner, {len(pulse_rows)} lignes "
          f"pulse, {len(profiles)} profils, {sum(len(r) for _, r in whale_blocks)} "
          f"whales.", flush=True)

    enriched = 0
    if do("save"):
        _save_profiles(profiles,
                       os.environ.get("PROFILES_OUT", "data/wallet_profiles.csv.gz"))
    if do("whales"):
        _write_whales_flat(sh, whale_blocks)
    if do("corner"):
        _write(sh, CORNER_TAB, CORNER_HEADER, corner_rows)
    if do("size"):
        _write_size_history(sh, size_rows, run_date[:7])
    if do("pseudos"):
        enriched = _enrich_pseudos(sh, profiles)
    if do("pulse"):
        try:
            _write_pulse(sh, pulse_rows)
            _write_reveils(sh, reveils)
        except Exception as e:
            print(f"pulse warning: {e}", flush=True)

    if do("cornerpage"):
        try:
            name_map = {r[0]: r[1] for r in corner[1:] if len(r) > 1}
            grid, fmts, bolds = build_corner_page(
                _rows("wallets_par_profil.csv")[1:],
                _rows("supply_par_profil.csv")[1:],
                _rows("corner_items.csv")[1:], name_map, meta_d)
            _write_corner_page(sh, grid, fmts, bolds)
            print(f"page 🎯 CORNÉRISATION : {len(grid)} lignes ecrites.", flush=True)
        except Exception as e:
            print(f"corner page warning: {e}", flush=True)

    try:
        from scraper.stackr import PSEUDOS_HEADER
        from scraper.ledger import SIZE_TAB, SIZE_HEADER
        _fmt.format_tab(sh, CORNER_TAB, CORNER_HEADER, header_rows=1)
        _fmt.format_tab(sh, SIZE_TAB, SIZE_HEADER, header_rows=1)
        _fmt.format_tab(sh, "🟣C-PSEUDOS", PSEUDOS_HEADER, header_rows=1)
    except Exception as e:
        print(f"formatting warning: {e}", flush=True)

    summary = {"status": "OK", "source_run": run_date,
               "collectibles": len(corner_rows), "holders": len(profiles),
               "pseudos_enriched": enriched,
               "duration": f"{time.time()-t0:.0f}s"}
    try:
        append_log(sheet_id, "ledger-writer", "OK",
                   "; ".join(f"{k}={v}" for k, v in summary.items() if k != "status"))
    except Exception as e:
        print(f"log warning: {e}", flush=True)
    print(f"Done. {summary}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
