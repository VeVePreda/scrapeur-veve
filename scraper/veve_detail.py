"""
VeVe collectible enrichment via VeVe's own GraphQL API.

Discovery (validated live):
- VeVe's GraphQL endpoint https://web.api.prod.veve.me/graphql is directly callable
  from a plain server (datacenter IP) — NO browser, NO cookies — as long as the custom
  client headers below are present (they replace VeVe's header-based CSRF check).
- The site (www.veve.me) is Cloudflare-protected, but the *API host* is not.
- `publicCollectibleType(id)` returns the full detail for a COLLECTIBLE. The `id` equals
  the my-nft-tracker `externalReference` (our `veve_uuid`) for collectibles.
- COMICS are a different type (`publicComicType`) AND their VeVe ids don't match the
  tracker ids, so comics are NOT enriched here (handled separately, later).

Egress:
- If APIFY_PROXY_PASSWORD is set, requests are routed through Apify's RESIDENTIAL proxy
  (robust against any future datacenter-IP blocking). Otherwise they go out directly
  (also works today). Controlled entirely by env vars — no code change needed to switch.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import requests

GRAPHQL_URL = "https://web.api.prod.veve.me/graphql"

# Headers that satisfy VeVe's header-based CSRF/anti-forgery check.
HEADERS = {
    "content-type": "application/json",
    "x-auth-version": "2",
    "client-name": "veve-app-web-server",
    "client-version": "1.0",
    "client-operation": "publicStoreCollectibleEditionsQuery",
    "user-agent": "Mozilla/5.0 (compatible; veve-catalogue-sync/1.0)",
    "accept": "application/json",
}

# Validated field set on publicCollectibleType (see module docstring).
QUERY = (
    "query publicStoreCollectibleEditionsQuery($id: ID!){ "
    "publicCollectibleType(id:$id){ "
    "__typename id name description rarity editionType isSpecialEdition "
    "storePrice marketFee dailyMcpPoints dropMethod dropDate "
    "totalIssued totalStoreAllocation totalAvailable soldEditions "
    "editionsBurnt withheldEditions editionsInCirculation availableReservations "
    "firstAvailableEdition isTotalAvailableVisible "
    "series{ id name season isBlindbox } "
    "brand{ id name licensor{ name } } } }"
)

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF = 2
DEFAULT_WORKERS = 6
PAUSE = 0.05  # small politeness delay per request

_thread_local = threading.local()


def _proxies() -> Optional[Dict[str, str]]:
    pwd = os.environ.get("APIFY_PROXY_PASSWORD")
    if not pwd:
        return None
    # Apify Proxy as a standard HTTP proxy, residential group.
    url = f"http://groups-RESIDENTIAL:{pwd}@proxy.apify.com:8000"
    return {"http": url, "https": url}


def _session() -> requests.Session:
    s = getattr(_thread_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update(HEADERS)
        px = _proxies()
        if px:
            s.proxies.update(px)
        _thread_local.session = s
    return s


def _num(x: Any) -> Any:
    if x in (None, ""):
        return x
    try:
        f = float(x)
        return int(f) if f.is_integer() else f
    except (ValueError, TypeError):
        return x


def fetch_collectible(uuid: str) -> Optional[Dict[str, Any]]:
    """Return enrichment columns for one collectible uuid, or None if not found."""
    payload = {
        "operationName": "publicStoreCollectibleEditionsQuery",
        "variables": {"id": uuid},
        "query": QUERY,
    }
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = _session().post(GRAPHQL_URL, json=payload, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                node = (data.get("data") or {}).get("publicCollectibleType")
                if not node:
                    # errors present (e.g. "Entity not found" for comics/delisted) -> skip
                    return None
                return _map_node(node, uuid)
            last_err = f"HTTP {r.status_code}"
        except Exception as e:
            last_err = str(e)
        time.sleep(RETRY_BACKOFF * attempt)
    print(f"    enrich failed for {uuid}: {last_err}", flush=True)
    return None


def _map_node(n: Dict[str, Any], uuid: str) -> Dict[str, Any]:
    series = n.get("series") or {}
    brand = n.get("brand") or {}
    licensor = (brand.get("licensor") or {}) if isinstance(brand, dict) else {}
    return {
        "veve_uuid": uuid,
        "special_edition": n.get("isSpecialEdition"),
        "edition_type": n.get("editionType"),
        "description": n.get("description"),
        "veve_store_price": _num(n.get("storePrice")),
        "market_fee": _num(n.get("marketFee")),
        "daily_mcp_points": _num(n.get("dailyMcpPoints")),
        "drop_method": n.get("dropMethod"),
        "drop_date": n.get("dropDate"),
        "rarity_editions": _num(n.get("totalIssued")),
        "store_allocation": _num(n.get("totalStoreAllocation")),
        "sold_editions": _num(n.get("soldEditions")),
        "editions_in_circulation": _num(n.get("editionsInCirculation")),
        "burned_editions": _num(n.get("editionsBurnt")),
        "withheld_editions": _num(n.get("withheldEditions")),
        "first_available_edition": _num(n.get("firstAvailableEdition")),
        "veve_total_available": _num(n.get("totalAvailable")),
        "season": _num(series.get("season")),
        "is_blindbox": series.get("isBlindbox"),
        "veve_series_name": series.get("name"),
        "veve_brand": brand.get("name"),
        "veve_licensor": licensor.get("name"),
        "veve_enriched_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
    }


def enrich(uuids: List[str], workers: int = DEFAULT_WORKERS) -> Dict[str, Dict[str, Any]]:
    """Enrich many collectible uuids concurrently. Returns {uuid: columns}."""
    uuids = [u for u in dict.fromkeys(uuids) if u]  # dedupe, drop empties
    total = len(uuids)
    if not total:
        return {}
    via = "Apify residential proxy" if _proxies() else "direct connection"
    print(f"Enriching {total} collectibles via VeVe GraphQL ({via})...", flush=True)

    out: Dict[str, Dict[str, Any]] = {}
    done = 0

    def task(u: str):
        time.sleep(PAUSE)
        return u, fetch_collectible(u)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(task, u) for u in uuids]
        for fut in as_completed(futures):
            u, cols = fut.result()
            done += 1
            if cols:
                out[u] = cols
            if done % 250 == 0:
                print(f"    ... {done}/{total} processed ({len(out)} enriched)", flush=True)

    print(f"Enrichment done: {len(out)}/{total} collectibles enriched.", flush=True)
    return out


if __name__ == "__main__":
    import sys, json
    ids = sys.argv[1:] or ["8648d886-ed81-4ea1-bae7-cb1a0bc975bd"]
    res = enrich(ids)
    print(json.dumps(res, indent=2, ensure_ascii=False))
