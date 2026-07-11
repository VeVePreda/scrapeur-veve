"""
CollectChain tracker — entry point.

Modes (env CHAIN_MODE):
    backfill — fetch the last CHAIN_BACKFILL_DAYS (default 31) days of
               transfers and REPLACE the ChainActivity tab. Run once, or
               whenever you want to rebuild from scratch. ~30-60 min.
    daily    — incremental: fetch only transfers newer than the checkpoint
               stored in ChainMeta, append, prune old rows, recompute stats.

Env:
    SHEET_ID              spreadsheet id (same as the catalogue sheet)
    CHAIN_MODE            backfill | daily          (default: daily)
    CHAIN_BACKFILL_DAYS   days for backfill mode    (default: 31)
    CHAIN_ARCHIVE         "true" (defaut) = archiver les journees PT completes
                          traitees en archive/transfers_daily_<date>.csv.gz
                          (continuite de l'archive du scan profond ; le workflow
                          les uploade dans la Release chain-archive-daily)
    CHAIN_ARCHIVE_DIR     dossier de sortie (defaut "archive")
"""

from __future__ import annotations

import csv
import datetime as _dt
import gzip
import os
import sys
import time

from scraper import collectchain as cc
from scraper import chain_sheets as cs

# Colonnes de l'archive des transferts — IDENTIQUES a celles du scan profond
# (wallet_scan / Release chain-archive du repo astronema) pour que ledger.py
# lise les deux sources uniformement.
ARCHIVE_HEADER = ["block", "log_index", "ts_utc", "date_pt", "kind", "category",
                  "veve_uuid", "edition", "from", "to"]


def _archive_records(records, min_complete_day: str):
    """CONTINUITE DE L'ARCHIVE : ecrit les transferts traites dans
    archive/transfers_daily_<date_pt>.csv.gz — UN fichier par journee PT.

    Idempotent : re-traiter une journee (backfill) reecrit le meme fichier,
    remplace dans la Release par --clobber. `min_complete_day` = journee PT
    contenant le cutoff, potentiellement PARTIELLE -> exclue, ainsi que tout
    ce qui est plus ancien (on n'archive que des journees completes ; le scan
    profond ou un backfill plus large les fournit). Les chevauchements avec le
    scan profond sont deduplique par (block, log_index) dans ledger.replay.
    Retourne {date_pt: nb_lignes}.
    """
    if os.environ.get("CHAIN_ARCHIVE", "true").strip().lower() != "true":
        return {}
    outdir = os.environ.get("CHAIN_ARCHIVE_DIR", "archive")
    by_day = {}
    for r in records:
        if r["date"] <= min_complete_day:
            continue                      # journee du cutoff = partielle
        by_day.setdefault(r["date"], []).append(r)
    if not by_day:
        return {}
    os.makedirs(outdir, exist_ok=True)
    counts = {}
    for day, recs in sorted(by_day.items()):
        recs.sort(key=lambda r: (r["ts"], r["block"] or 0, r["log_index"] or 0))
        path = os.path.join(outdir, f"transfers_daily_{day}.csv.gz")
        with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(ARCHIVE_HEADER)
            for r in recs:
                w.writerow([r["block"], r["log_index"] or 0,
                            r["ts"].strftime("%Y-%m-%d %H:%M:%S"), r["date"],
                            r["kind"], r["category"], r["veve_uuid"],
                            r["edition"], r["from"], r["to"]])
        counts[day] = len(recs)
    return counts


def main() -> int:
    sheet_id = os.environ.get("SHEET_ID", "").strip()
    if not sheet_id:
        print("SHEET_ID env var is not set.", file=sys.stderr)
        return 2

    mode = os.environ.get("CHAIN_MODE", "daily").strip().lower()
    backfill_days = int(os.environ.get("CHAIN_BACKFILL_DAYS", "31"))
    t0 = time.time()
    summary = {"mode": mode, "status": "OK", "note": ""}

    try:
        totals = cc.chain_totals()
        print(f"Chain totals: {totals}", flush=True)
    except Exception as e:
        totals = None
        print(f"stats endpoint warning: {e}", flush=True)

    # Only ever process fully-finished PACIFIC days (les journees sont decoupees
    # en PT, le fuseau metier VeVe) : tout ce qui est a/apres minuit PT du jour
    # courant est ignore et sera traite demain.
    now_pt = _dt.datetime.now(cc.PT)
    pt_midnight = now_pt.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = pt_midnight.astimezone(_dt.timezone.utc).replace(tzinfo=None)
    last_complete_day = now_pt.date() - _dt.timedelta(days=1)

    try:
        if mode == "backfill":
            cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=backfill_days)
            print(f"BACKFILL: fetching transfers {cutoff:%Y-%m-%d} → "
                  f"{last_complete_day} (complete days only)...", flush=True)
            records, meta = cc.fetch_transfers(cutoff, until=today_start)
            rows = cc.aggregate_daily(records)
            added = cs.append_activity(sheet_id, rows, replace=True)
            cs.append_items(sheet_id, cc.aggregate_items(records), replace=True)
            pruned = 0
        else:
            checkpoint = cs.read_checkpoint(sheet_id)
            cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=cs.RETENTION_DAYS)
            print(f"DAILY: checkpoint={checkpoint}, safety cutoff={cutoff:%Y-%m-%d}, "
                  f"last complete day={last_complete_day}", flush=True)
            if checkpoint is None:
                print("No checkpoint found — did you run the backfill? "
                      "Falling back to the last 2 days only.", flush=True)
                cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=2)
            records, meta = cc.fetch_transfers(cutoff, checkpoint=checkpoint,
                                               until=today_start)
            rows = cc.aggregate_daily(records)
            added = cs.append_activity(sheet_id, rows)
            cs.append_items(sheet_id, cc.aggregate_items(records))
            pruned = cs.prune_activity(sheet_id) + cs.prune_items(sheet_id)

        # CONTINUITE DE L'ARCHIVE : les journees PT completes traitees ce run
        # partent en archive/ (upload Release chain-archive-daily par le workflow).
        cutoff_pt_day = cutoff.replace(tzinfo=_dt.timezone.utc) \
            .astimezone(cc.PT).strftime("%Y-%m-%d")
        arch = _archive_records(records, cutoff_pt_day)
        if arch:
            summary["archived_days"] = len(arch)
            summary["archived_rows"] = sum(arch.values())
            print(f"Archive quotidienne : {len(arch)} journee(s), "
                  f"{sum(arch.values())} transferts -> archive/.", flush=True)

        # LISTING quotidien (groupe a part sur 📊 STATS) : nouveaux depots
        # escrow + comptes "purs" (listent sans mint/achat/vente ce jour-la).
        listing_rows = cc.aggregate_listing_daily(records)
        if listing_rows:
            summary["listing_days"] = cs.merge_listing_daily(
                sheet_id, listing_rows, replace=(mode == "backfill"))

        # Market escrow deposits -> (veve_uuid, edition) -> seller wallet, for the
        # pseudo<->wallet join with the Market listings.
        esc_added = cs.merge_escrow(sheet_id, cc.escrow_listings(records))

        # Registre wallets (data/wallet_registry_daily.csv) — voir wallet_scan.py.
        # Non bloquant : le suivi on-chain du Sheet ne depend pas du registre.
        try:
            from scraper import wallet_scan as ws
            summary.update(ws.update_from_records(records))
        except Exception as e:
            print(f"wallet registry warning: {e}", flush=True)

        summary.update(transfers_fetched=meta["count"], pages=meta["pages"],
                       activity_rows_added=added, rows_pruned=pruned,
                       escrow_listings_added=esc_added)

        # Recompute the window stats from everything in the tab. Windows are
        # anchored on the last COMPLETE day (24h = yesterday), since today is
        # deliberately not collected yet.
        print("Reading ChainActivity to recompute the window stats...", flush=True)
        activity = cs.read_activity(sheet_id)
        stats = cc.compute_window_stats(activity, today=last_complete_day)

        for s in stats:
            if s["window"] == "24h" and s["scope"] == "all" and s["category"] == "all":
                summary["unique_accounts_24h"] = s["unique_accounts"]

        # DropRevenue abandoned: raw per-item counts stay in ChainItems (hidden)
        # for any external drop-revenue analysis.

        # Only advance the checkpoint after everything else succeeded.
        if meta.get("newest_block"):
            cs.write_meta(sheet_id, meta, totals)

    except Exception as e:
        summary["status"] = "FAILED"
        summary["note"] = str(e)[:300]
        try:
            cs.append_chain_runlog(sheet_id, summary)
        except Exception:
            pass
        raise

    summary["note"] = (summary["note"] + f" duration={time.time()-t0:.0f}s").strip()
    cs.append_chain_runlog(sheet_id, summary)
    print(f"Done: {summary}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
