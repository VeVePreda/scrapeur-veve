"""
VeVe catalogue scraper — via the my-nft-tracker public REST API.

Why this source
---------------
VeVe's own site is behind Cloudflare (returns 403 to bots) and its GraphQL API only
accepts pre-registered "persisted queries", so it can't be scraped directly.

my-nft-tracker.com is a community VeVe tracker that already aggregates the *entire*
VeVe catalogue and exposes it through a clean, unauthenticated REST API:

    https://my-nft-tracker-backend.azurewebsites.net/api/Nfts

That endpoint returns fully structured JSON (name, edition, type/category, rarity,
release date, mint amounts, store price, series, brand, licensor, images, and the
VeVe product UUID in `externalReference`). We simply paginate it — no browser, no
proxy, no anti-bot fight. At the time of writing it holds ~18,700 products.

This module fetches every product, flattens each into a tidy row, adds a direct VeVe
product URL and image URL, and returns the list. `sheets.py` handles the upsert.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import requests

API_BASE = "https://my-nft-tracker-backend.azurewebsites.net"
NFTS_URL = f"{API_BASE}/api/Nfts"

# Page size to request. The API honours large pages; 250 keeps each response small
# and the run resilient. If the API returns fewer than asked, we adapt to that.
PAGE_SIZE = 250
REQUEST_TIMEOUT = 60
MAX_RETRIES = 4
RETRY_BACKOFF = 3  # seconds, multiplied by attempt number
PAUSE_BETWEEN_PAGES = 0.4  # be polite to the free community backend

USER_AGENT = "veve-catalogue-sync/1.0 (personal catalogue export)"

# VeVe front-end URL patterns, by category, using the VeVe UUID (externalReference).
VEVE_URL_BY_CATEGORY = {
    "collectible": "https://www.veve.me/collectibles/en/collectibles/{uuid}",
    "comic": "https://www.veve.me/collectibles/en/collection/comic/{uuid}",
    "artwork": "https://www.veve.me/collectibles/en/artworks/{uuid}",
}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def _get(session: requests.Session, params: Dict[str, Any]) -> Dict[str, Any]:
    last_err: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(NFTS_URL, params=params, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # network hiccup / 5xx / throttling
            last_err = e
            wait = RETRY_BACKOFF * attempt
            print(f"    request failed (attempt {attempt}/{MAX_RETRIES}): {e} — retrying in {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"Gave up fetching {params}: {last_err}")


def _veve_url(category: Optional[str], external_ref: Optional[str]) -> str:
    if not external_ref:
        return ""
    key = (category or "").strip().lower()
    tmpl = VEVE_URL_BY_CATEGORY.get(key)
    if not tmpl:
        # default to the collectibles path
        tmpl = VEVE_URL_BY_CATEGORY["collectible"]
    return tmpl.format(uuid=external_ref)


def _image_url(image_link: Optional[str]) -> str:
    if not image_link:
        return ""
    if image_link.startswith("http"):
        return image_link
    return f"{API_BASE}{image_link}"


def _flatten_product(p: Dict[str, Any]) -> Dict[str, Any]:
    """Turn one API product object into a flat, human-friendly row."""
    series = p.get("series") or {}
    brand = p.get("brand") or {}
    licensor = p.get("licensor") or {}
    stats = p.get("priceStatistics") or {}
    latest = (stats.get("latest") or {}) if isinstance(stats, dict) else {}

    external_ref = p.get("externalReference")
    category = p.get("category")

    row = {
        # --- identity ---
        "veve_uuid": external_ref,                 # the UUID used in VeVe URLs
        "name": p.get("name"),
        "category": category,
        "edition": p.get("edition"),
        "rarity": p.get("rarity"),
        "releaseDate": p.get("releaseDate"),
        # --- supply ---
        "releaseAmount": p.get("releaseAmount"),
        "availableAmount": p.get("availableAmount"),
        "isEcl": p.get("isEcl"),
        # --- pricing (light) ---
        "storePrice": p.get("storePrice"),
        "market_lowestOffer": latest.get("lowestOffer"),
        "market_totalListings": latest.get("totalListings"),
        "gemsPerMcp": stats.get("gemsPerMcp") if isinstance(stats, dict) else None,
        "noMarketListing": stats.get("noMarketListing") if isinstance(stats, dict) else None,
        # --- relationships ---
        "series_name": series.get("seriesName"),
        "series_edition": series.get("edition"),
        "series_uuid": series.get("externalReference") or series.get("uuid"),
        "brand_name": brand.get("name"),
        "brand_uuid": brand.get("uuid"),
        "licensor_name": licensor.get("name"),
        "licensor_fee": licensor.get("fee"),
        "licensor_uuid": licensor.get("uuid"),
        "provider": p.get("provider"),
        # --- links ---
        "veve_url": _veve_url(category, external_ref),
        "image_url": _image_url(p.get("imageLink")),
        "image_cloudflare": p.get("imageLinkCloudflare"),
        # --- ids for reference/joining ---
        "tracker_uuid": p.get("uuid"),
    }
    return row


def scrape_catalogue(category: Optional[str] = None, limit_total: Optional[int] = None) -> List[Dict[str, Any]]:
    """Fetch the full VeVe catalogue.

    category: None = everything (collectibles + comics). Or "collectible" / "comic".
    limit_total: stop after this many products (useful for a quick test run).

    Returns a list of flat product dicts, keyed conceptually by `veve_uuid`.
    """
    session = _session()
    base_params = {
        "orderBy": "releaseDate",
        "orderAsc": "false",
        "showOnlyReleased": "",  # include unreleased / future drops too
    }
    if category:
        base_params["category"] = category

    # First call to learn the total.
    first = _get(session, {**base_params, "page": 1, "offset": 0, "limit": PAGE_SIZE})
    meta = first.get("meta", {})
    total = int(meta.get("entries_TotalAvailable", 0))
    print(f"Catalogue size reported: {total} products (category={category or 'ALL'})", flush=True)

    by_uuid: Dict[str, Dict[str, Any]] = {}

    def ingest(entries: List[Dict[str, Any]]) -> None:
        for p in entries:
            row = _flatten_product(p)
            key = row.get("veve_uuid") or row.get("tracker_uuid")
            if key:
                by_uuid[key] = row

    ingest(first.get("resultEntries", []))

    offset = len(first.get("resultEntries", []))
    page = 2
    while offset < total:
        if limit_total and len(by_uuid) >= limit_total:
            break
        data = _get(session, {**base_params, "page": page, "offset": offset, "limit": PAGE_SIZE})
        entries = data.get("resultEntries", [])
        if not entries:
            print("    empty page — stopping.", flush=True)
            break
        ingest(entries)
        offset += len(entries)
        page += 1
        if page % 10 == 0:
            print(f"    ... {len(by_uuid)}/{total} products", flush=True)
        time.sleep(PAUSE_BETWEEN_PAGES)

    products = list(by_uuid.values())
    print(f"TOTAL harvested: {len(products)} unique products", flush=True)
    return products


if __name__ == "__main__":
    import sys
    lim = None
    if "--test" in sys.argv:
        lim = 300
    items = scrape_catalogue(limit_total=lim)
    print(f"Got {len(items)} products.")
    if items:
        print("Columns:", ", ".join(items[0].keys()))
        print("Sample:", items[0])
