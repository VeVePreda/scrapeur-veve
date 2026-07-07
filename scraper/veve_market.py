"""
VeVe secondary-market listings collector (per collectible).

VeVe's web app fetches the individual offers of a product via the GraphQL op
`MarketFromCollectibleTypeQuery` -> `marketListingFromCollectibleType`, which
returns, per listing:

    sellerId     VeVe user UUID
    sellerName   the seller PSEUDO (public)
    issueNumber  the edition / mint number being sold  (== on-chain `edition`)
    price        ask price
    currency     GEM (VeVe) or OMI (StackR)
    market       VEVE | STACKR
    listingType  FIXED | ...

This is the missing piece for pseudo <-> wallet: an offer ties a pseudo to a
specific (collectible, edition), and CollectChain ties that same
(collectible, edition) to the current owner wallet -> pseudo <-> wallet.

Auth: VeVe uses a session COOKIE (`vv.at`), not a Bearer header. Provide it via
the env var VEVE_AUTH (the raw `cookie:` header value, or just `vv.at=<jwt>`).
The listings are public, so it may also work WITHOUT auth — if VEVE_AUTH is unset
we still try (and log the result).

Tabs written (same spreadsheet):
    MarketListings — current offers snapshot (overwritten each run)
    MarketPseudos  — accumulated sellerId <-> sellerName (pseudo directory)

Env: GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID, VEVE_AUTH (optional),
     MARKET_MAX_PRODUCTS (test cap), MARKET_PAUSE.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, List, Optional

import requests

from scraper.sheets import _client, _open_worksheet, _now, append_log

GRAPHQL_URL = "https://web.api.prod.veve.me/graphql"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF = 2
PAUSE = float(os.environ.get("MARKET_PAUSE", "0.15"))

LANDING_OP = "MarketLandingCollectiblesPageQuery"
LANDING_QUERY = (
    "query MarketLandingCollectiblesPageQuery($cursor: String){ "
    "marketListingByCollectibleType(first: 100, after: $cursor, "
    "sortOptions: {sortBy: CREATED_AT, sortDirection: DESCENDING}){ "
    "pageInfo{ endCursor hasNextPage } "
    "edges{ node{ id name rarity totalMarketListings floorMarketPrice } } } }"
)

LISTINGS_OP = "MarketFromCollectibleTypeQuery"
LISTINGS_QUERY = (
    "query MarketFromCollectibleTypeQuery($cursor: String, $collectibleTypeId: String!, "
    "$sortBy: MarketListingFromCollectibleTypeSortOptions!, $sortDirection: SortDirection!, "
    "$markets: [Market!]){ "
    "marketListingFromCollectibleType(first: 100, after: $cursor, "
    "filterOptions: {collectibleTypeId: $collectibleTypeId, editionFrom: 1, "
    "editionTo: 99999, markets: $markets}, "
    "sortOptions: {sortBy: $sortBy, sortDirection: $sortDirection}){ "
    "totalCount pageInfo{ endCursor hasNextPage } "
    "edges{ node{ id collectibleId market currency listingType "
    "sellerId sellerName issueNumber price } } } }"
)

MARKET_LISTINGS_TAB = "MarketListings"
MARKET_LISTINGS_HEADER = ["snapshot_date", "veve_uuid", "collectible_name",
                          "issue_number", "seller_id", "seller_name",
                          "market", "currency", "price", "listing_type", "listing_id"]
from scraper.stackr import PSEUDOS_TAB, PSEUDOS_HEADER  # unified pseudo directory

MARKET_PSEUDOS_TAB = "MarketPseudos"  # legacy tab, deleted on sight (now merged into Pseudos)
ESCROW_TAB = "_EscrowListings"  # (veve_uuid, edition) -> seller wallet, from chain


def _headers(op: str) -> Dict[str, str]:
    h = {
        "content-type": "application/json",
        "x-auth-version": "2",
        "client-name": "veve-app-web-server",
        "client-version": "1.0",
        "client-operation": op,
        "accept": "*/*",
        "origin": "https://www.veve.me",
        "referer": "https://www.veve.me/",
        "user-agent": "Mozilla/5.0 (compatible; veve-market-sync/1.0)",
    }
    auth = os.environ.get("VEVE_AUTH", "").strip()
    if auth:
        # Accept either a full cookie header or a bare vv.at=... token.
        h["cookie"] = auth
    return h


def _session() -> requests.Session:
    s = requests.Session()
    return s


def _post(op: str, query: str, variables: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    payload = {"operationName": op, "query": query, "variables": variables}
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.post(GRAPHQL_URL, headers=_headers(op), json=payload,
                              timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                if data.get("errors"):
                    print(f"    {op} errors: {str(data['errors'])[:200]}", flush=True)
                    return None
                return data.get("data")
            last_err = f"HTTP {r.status_code}"
            if r.status_code in (401, 403):
                print(f"    {op} auth error {r.status_code} — check VEVE_AUTH cookie.",
                      flush=True)
                return None
        except Exception as e:
            last_err = str(e)
        time.sleep(RETRY_BACKOFF * attempt)
    print(f"    {op} failed: {last_err}", flush=True)
    return None


def list_products_with_listings(max_products: int = 0) -> List[Dict[str, Any]]:
    """All collectibles that currently have market listings (paginated landing)."""
    out: List[Dict[str, Any]] = []
    cursor = ""
    while True:
        data = _post(LANDING_OP, LANDING_QUERY, {"cursor": cursor})
        conn = (data or {}).get("marketListingByCollectibleType") or {}
        for e in conn.get("edges", []):
            n = e.get("node") or {}
            if n.get("id"):
                out.append({"id": n["id"], "name": n.get("name", ""),
                            "listings": n.get("totalMarketListings", 0)})
        if max_products and len(out) >= max_products:
            return out[:max_products]
        pi = conn.get("pageInfo") or {}
        if not pi.get("hasNextPage") or not pi.get("endCursor"):
            break
        cursor = pi["endCursor"]
        time.sleep(PAUSE)
    return out


def fetch_listings(collectible_id: str) -> List[Dict[str, Any]]:
    """All current offers for one collectible (paginated), cheapest first."""
    out: List[Dict[str, Any]] = []
    cursor = ""
    while True:
        data = _post(LISTINGS_OP, LISTINGS_QUERY, {
            "cursor": cursor, "collectibleTypeId": collectible_id,
            "sortBy": "PRICE", "sortDirection": "ASCENDING",
            "markets": ["VEVE", "STACKR"]})
        conn = (data or {}).get("marketListingFromCollectibleType") or {}
        for e in conn.get("edges", []):
            n = e.get("node") or {}
            if n.get("id"):
                out.append(n)
        pi = conn.get("pageInfo") or {}
        if not pi.get("hasNextPage") or not pi.get("endCursor"):
            break
        cursor = pi["endCursor"]
        time.sleep(PAUSE)
    return out


def _write_listings(sheet_id: str, rows: List[List[Any]]) -> None:
    sh = _client().open_by_key(sheet_id)
    ws = _open_worksheet(sh, MARKET_LISTINGS_TAB, cols=len(MARKET_LISTINGS_HEADER))
    ws.clear()
    grid = [MARKET_LISTINGS_HEADER] + rows
    for i in range(0, len(grid), 20000):
        if i == 0:
            ws.update(range_name="A1", values=grid[:20000], value_input_option="RAW")
        else:
            ws.append_rows(grid[i:i + 20000], value_input_option="RAW")
    try:
        ws.freeze(rows=1)
        ws.format("1:1", {"textFormat": {"bold": True}})
    except Exception:
        pass


def _load_escrow(sh) -> Dict[tuple, str]:
    """{(veve_uuid, edition_str) -> seller_wallet} from the chain _EscrowListings."""
    out: Dict[tuple, str] = {}
    try:
        ws = sh.worksheet(ESCROW_TAB)
    except Exception:
        return out
    for r in ws.get_all_records():
        uid = str(r.get("veve_uuid", "")).strip()
        ed = str(r.get("edition", "")).strip()
        w = str(r.get("seller_wallet", "")).strip()
        if uid and ed and w:
            out[(uid, ed)] = w
    return out


def _merge_into_pseudos(sheet_id: str, seen: Dict[str, Dict[str, Any]],
                        onchain: Optional[Dict[str, str]] = None) -> tuple:
    """Merge the market sellers into the single unified `Pseudos` tab (shared with
    StackR), keyed by veve_user_id then username. Fills the wallet from the
    on-chain escrow deposit when StackR doesn't already have it. The market job
    runs LAST in the daily workflow, so it augments StackR's fresh output.
    Returns (new_pseudos, market_sellers_with_wallet)."""
    onchain = onchain or {}
    sh = _client().open_by_key(sheet_id)
    ws = _open_worksheet(sh, PSEUDOS_TAB, cols=len(PSEUDOS_HEADER))
    rows: List[Dict[str, Any]] = [dict(r) for r in ws.get_all_records()] \
        if ws.row_count > 1 else []
    by_uid: Dict[str, Dict[str, Any]] = {}
    by_name: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        uid = str(r.get("veve_user_id", "")).strip()
        nm = str(r.get("username", "")).strip().lower()
        if uid:
            by_uid[uid] = r
        if nm:
            by_name[nm] = r

    now = _now()
    new = 0
    for sid, info in seen.items():
        sname = info["seller_name"]
        wallet = onchain.get(sid, "")
        r = by_uid.get(sid) or by_name.get(str(sname).strip().lower())
        if r is None:
            r = {c: "" for c in PSEUDOS_HEADER}
            r["username"] = sname
            r["veve_user_id"] = sid
            r["wallet_imx"] = wallet
            r["status"] = "ok" if sname else ""
            r["source"] = "market"
            r["first_seen"] = now
            r["last_checked"] = now
            rows.append(r)
            if sid:
                by_uid[sid] = r
            if sname:
                by_name[str(sname).strip().lower()] = r
            new += 1
        else:
            if sname and not str(r.get("username", "")).strip():
                r["username"] = sname
                r["status"] = "ok"
            if sid and not str(r.get("veve_user_id", "")).strip():
                r["veve_user_id"] = sid
            if wallet and not str(r.get("wallet_imx", "")).strip():
                r["wallet_imx"] = wallet
            src = str(r.get("source", "") or "")
            if "market" not in src:
                r["source"] = (src + ",market") if src else "market"
            r["last_checked"] = now

    matched = 0
    for sid, info in seen.items():
        r = by_uid.get(sid) or by_name.get(str(info["seller_name"]).strip().lower())
        if r and str(r.get("wallet_imx", "")).strip():
            matched += 1

    grid = [PSEUDOS_HEADER] + [[r.get(c, "") for c in PSEUDOS_HEADER] for r in rows]
    ws.clear()
    for i in range(0, len(grid), 20000):
        if i == 0:
            ws.update(range_name="A1", values=grid[:20000], value_input_option="RAW")
        else:
            ws.append_rows(grid[i:i + 20000], value_input_option="RAW")
    try:
        ws.freeze(rows=1)
        ws.format("1:1", {"textFormat": {"bold": True}})
    except Exception:
        pass

    # Drop the legacy MarketPseudos tab now that pseudos live in `Pseudos`.
    try:
        sh.del_worksheet(sh.worksheet(MARKET_PSEUDOS_TAB))
    except Exception:
        pass

    return new, matched


def main() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        print("ERROR: SHEET_ID env var is required.", file=sys.stderr)
        return 2
    max_products = int(os.environ.get("MARKET_MAX_PRODUCTS", "0") or "0")

    if not os.environ.get("VEVE_AUTH", "").strip():
        print("Note: VEVE_AUTH not set — trying without auth (listings may be public).",
              flush=True)

    print("Listing products with active market listings...", flush=True)
    products = list_products_with_listings(max_products)
    if not products:
        print("No products with listings returned (auth issue or empty).",
              file=sys.stderr)
        try:
            append_log(sheet_id, "market", "FAILED_NO_DATA",
                       "landing returned no products (check VEVE_AUTH?).")
        except Exception:
            pass
        return 1
    print(f"{len(products)} products with listings.", flush=True)

    escrow = _load_escrow(_client().open_by_key(sheet_id))
    if escrow:
        print(f"Loaded {len(escrow)} on-chain escrow deposits for wallet matching.",
              flush=True)

    rows: List[List[Any]] = []
    pseudos: Dict[str, Dict[str, Any]] = {}
    seller_onchain: Dict[str, str] = {}
    stamp = _now()
    done = 0
    for p in products:
        listings = fetch_listings(p["id"])
        for n in listings:
            sid = str(n.get("sellerId", "") or "")
            sname = n.get("sellerName", "") or ""
            issue = str(n.get("issueNumber", "") or "").strip()
            rows.append([stamp, p["id"], p.get("name", ""), n.get("issueNumber", ""),
                         sid, sname, n.get("market", ""), n.get("currency", ""),
                         n.get("price", ""), n.get("listingType", ""), n.get("id", "")])
            if sid:
                d = pseudos.setdefault(sid, {"seller_name": sname, "count": 0})
                d["seller_name"] = sname or d["seller_name"]
                d["count"] += 1
                if sid not in seller_onchain:
                    ow = escrow.get((p["id"], issue))
                    if ow:
                        seller_onchain[sid] = ow
        done += 1
        if done % 100 == 0:
            print(f"    ... {done}/{len(products)} products, {len(rows)} listings", flush=True)
        time.sleep(PAUSE)

    _write_listings(sheet_id, rows)
    new_pseudos, matched_wallets = _merge_into_pseudos(sheet_id, pseudos, seller_onchain)

    summary = {"status": "OK", "products": len(products), "listings": len(rows),
               "sellers": len(pseudos), "new_pseudos": new_pseudos,
               "wallets_matched": matched_wallets, "duration": f"{time.time()-t0:.0f}s"}
    try:
        append_log(sheet_id, "market", "OK",
                   "; ".join(f"{k}={v}" for k, v in summary.items() if k != "status"))
    except Exception as e:
        print(f"log warning: {e}", flush=True)
    print(f"Done. {summary}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
