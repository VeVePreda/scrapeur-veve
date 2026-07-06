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
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
import time

from scraper import collectchain as cc
from scraper import chain_revenue as crv
from scraper import chain_sheets as cs


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

    try:
        if mode == "backfill":
            cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=backfill_days)
            print(f"BACKFILL: fetching transfers since {cutoff:%Y-%m-%d %H:%M} UTC "
                  f"({backfill_days} days)...", flush=True)
            records, meta = cc.fetch_transfers(cutoff)
            rows = cc.aggregate_daily(records)
            added = cs.append_activity(sheet_id, rows, replace=True)
            cs.append_items(sheet_id, cc.aggregate_items(records), replace=True)
            pruned = 0
        else:
            checkpoint = cs.read_checkpoint(sheet_id)
            cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=cs.RETENTION_DAYS)
            print(f"DAILY: checkpoint={checkpoint}, safety cutoff={cutoff:%Y-%m-%d}",
                  flush=True)
            if checkpoint is None:
                print("No checkpoint found — did you run the backfill? "
                      "Falling back to the last 2 days only.", flush=True)
                cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=2)
            records, meta = cc.fetch_transfers(cutoff, checkpoint=checkpoint)
            rows = cc.aggregate_daily(records)
            added = cs.append_activity(sheet_id, rows)
            cs.append_items(sheet_id, cc.aggregate_items(records))
            pruned = cs.prune_activity(sheet_id) + cs.prune_items(sheet_id)

        summary.update(transfers_fetched=meta["count"], pages=meta["pages"],
                       activity_rows_added=added, rows_pruned=pruned)

        # Recompute the window stats from everything in the tab.
        print("Reading ChainActivity to recompute 24h/7j/30j stats...", flush=True)
        activity = cs.read_activity(sheet_id)
        stats = cc.compute_window_stats(activity)
        top = cc.compute_top_accounts(activity)
        cs.write_stats(sheet_id, stats, top)

        for s in stats:
            if s["window"] == "24h" and s["scope"] == "all" and s["category"] == "all":
                summary["unique_accounts_24h"] = s["unique_accounts"]

        # Per-item view + drop revenue estimation (mints x store price).
        print("Computing per-item stats + drop revenue...", flush=True)
        items = cs.read_items(sheet_id)
        catalogue = cs.read_catalogue(sheet_id)
        rev = crv.compute_drop_revenue(items, catalogue)
        cs.write_revenue(sheet_id, rev, crv.summarize_revenue(rev))
        unmatched = sum(1 for r in rev if r["match"] == "none")
        if unmatched:
            summary["note"] += f" unmatched_items={unmatched}"

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
