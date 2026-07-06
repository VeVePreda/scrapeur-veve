"""
Drop revenue estimation — joins on-chain mint counts with catalogue prices.

Estimated revenue of a drop = number of on-chain MINTS x store price.
(Approximation: premium/discounted checkout, gems payments and free claims
are priced at store price; free drops have storePrice 0 and contribute 0.)

Join strategy, per on-chain item, in order:
1. UUID     — the UUID embedded in the chain image URL equals the catalogue
              `veve_uuid` for collectibles (verified). For comics we also try
              it against `series_uuid`.
2. IMAGE    — the catalogue's enriched `image_url` (VeVe CDN) embeds the same
              UUID as the chain image URL; match on that (+ rarity for comics,
              since all rarities of a comic share the same cover).
3. NAME     — normalised "name [#num (year)]" + rarity.

Every matched row carries the catalogue store price; unmatched items are kept
with an empty price so you can spot them.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Dict, List, Optional, Tuple

from scraper.collectchain import WINDOWS, _UUID_RE

_num_re = re.compile(r"[^0-9.]")


def _price(x: Any) -> Optional[float]:
    if x in (None, ""):
        return None
    try:
        return float(_num_re.sub("", str(x)) or "nan")
    except ValueError:
        return None


def _name_key(name: str, rarity: str, comic_number: str = "",
              start_year: str = "") -> str:
    base = (name or "").strip().lower()
    if comic_number:
        base = f"{base} #{comic_number}"
        if start_year:
            base = f"{base} ({start_year})"
    return f"{base}|{(rarity or '').strip().upper()}"


def build_catalogue_index(cat_rows: List[Dict[str, Any]]) -> Dict[str, Dict]:
    """cat_rows: dict rows of the Catalogue tab. Returns lookup indexes."""
    by_uuid: Dict[str, Dict] = {}
    by_series_rarity: Dict[Tuple[str, str], Dict] = {}
    by_img: Dict[Tuple[str, str], Dict] = {}
    by_name: Dict[str, Dict] = {}
    for r in cat_rows:
        uuid = str(r.get("veve_uuid", "")).strip().lower()
        rarity = str(r.get("rarity", "")).strip().upper()
        if uuid:
            by_uuid[uuid] = r
        suid = str(r.get("series_uuid", "")).strip().lower()
        if suid:
            by_series_rarity[(suid, rarity)] = r
        m = _UUID_RE.search(str(r.get("image_url", "")))
        if m:
            by_img[(m.group(2).lower(), rarity)] = r
            by_img.setdefault((m.group(2).lower(), ""), r)
        nk = _name_key(str(r.get("name", "")), rarity)
        if nk not in by_name:
            by_name[nk] = r
    return {"uuid": by_uuid, "series_rarity": by_series_rarity,
            "img": by_img, "name": by_name}


def match_catalogue(item: Dict[str, Any], idx: Dict[str, Dict]) \
        -> Tuple[Optional[Dict], str]:
    """One ChainItems row -> (catalogue row, match_source)."""
    uuid = str(item.get("veve_uuid", "")).strip().lower()
    rarity = str(item.get("rarity", "")).strip().upper()
    if uuid:
        r = idx["uuid"].get(uuid)
        if r is not None:
            return r, "uuid"
        r = idx["series_rarity"].get((uuid, rarity))
        if r is not None:
            return r, "series+rarity"
        r = idx["img"].get((uuid, rarity)) or idx["img"].get((uuid, ""))
        if r is not None:
            return r, "image"
    # name fallback (with and without #num (year) decoration)
    for nk in (
        _name_key(item.get("name", ""), rarity,
                  str(item.get("comic_number", "")), str(item.get("start_year", ""))),
        _name_key(item.get("name", ""), rarity, str(item.get("comic_number", ""))),
        _name_key(item.get("name", ""), rarity),
    ):
        r = idx["name"].get(nk)
        if r is not None:
            return r, "name"
    return None, "none"


def compute_drop_revenue(item_rows: List[Dict[str, Any]],
                         cat_rows: List[Dict[str, Any]],
                         today: Optional[_dt.date] = None,
                         min_mints_30d: int = 1) -> List[Dict[str, Any]]:
    """ChainItems rows (possibly duplicated per run — counters sum) + Catalogue
    -> one row per item with mints and estimated revenue per window."""
    today = today or _dt.datetime.utcnow().date()
    idx = build_catalogue_index(cat_rows)
    starts = {label: (today - _dt.timedelta(days=days - 1)).strftime("%Y-%m-%d")
              for label, days in WINDOWS}

    # Merge rows by item identity.
    merged: Dict[str, Dict[str, Any]] = {}
    for r in item_rows:
        key = (str(r.get("veve_uuid") or "").lower()
               + "|" + str(r.get("rarity") or "").upper()
               + "|" + str(r.get("name") or "").lower())
        it = merged.setdefault(key, {
            "category": r.get("category", ""), "veve_uuid": r.get("veve_uuid", ""),
            "name": r.get("name", ""), "rarity": r.get("rarity", ""),
            "series": r.get("series", ""), "comic_number": r.get("comic_number", ""),
            "start_year": r.get("start_year", ""),
            "total_editions": r.get("total_editions", ""),
            **{f"mints_{lbl}": 0 for lbl, _ in WINDOWS},
            **{f"market_{lbl}": 0 for lbl, _ in WINDOWS},
        })
        d = str(r.get("date", ""))
        for lbl, _days in WINDOWS:
            if d >= starts[lbl]:
                it[f"mints_{lbl}"] += int(r.get("mints", 0) or 0)
                it[f"market_{lbl}"] += int(r.get("market", 0) or 0)

    out: List[Dict[str, Any]] = []
    for it in merged.values():
        if it["mints_30j"] < min_mints_30d and it["market_30j"] == 0:
            continue
        cat_row, source = match_catalogue(it, idx)
        price = _price(cat_row.get("storePrice")) if cat_row else None
        row = {
            "category": it["category"],
            "name": it["name"] or (cat_row.get("name", "") if cat_row else ""),
            "rarity": it["rarity"],
            "series": it["series"],
            "veve_uuid": it["veve_uuid"],
            "store_price": price if price is not None else "",
            "mints_24h": it["mints_24h"], "mints_7j": it["mints_7j"],
            "mints_30j": it["mints_30j"],
            "revenue_24h": round(it["mints_24h"] * price, 2) if price else "",
            "revenue_7j": round(it["mints_7j"] * price, 2) if price else "",
            "revenue_30j": round(it["mints_30j"] * price, 2) if price else "",
            "market_24h": it["market_24h"], "market_7j": it["market_7j"],
            "market_30j": it["market_30j"],
            "total_editions": it["total_editions"],
            "release_amount": cat_row.get("releaseAmount", "") if cat_row else "",
            "release_date": cat_row.get("releaseDate", "") if cat_row else "",
            "veve_url": cat_row.get("veve_url", "") if cat_row else "",
            "match": source,
        }
        out.append(row)

    out.sort(key=lambda r: (r["revenue_30j"] or 0, r["mints_30j"]), reverse=True)
    return out


def summarize_revenue(rev_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Totals per window x category (headline numbers for the sheet top)."""
    out = []
    for lbl, _ in WINDOWS:
        for cat in ("all", "collectible", "comic"):
            rows = [r for r in rev_rows if cat == "all" or r["category"] == cat]
            out.append({
                "window": lbl, "category": cat,
                "mints": sum(r[f"mints_{lbl}"] for r in rows),
                "est_revenue": round(sum(r[f"revenue_{lbl}"] or 0 for r in rows), 2),
                "items_matched": sum(1 for r in rows
                                     if r["match"] != "none" and r[f"mints_{lbl}"]),
                "items_unmatched": sum(1 for r in rows
                                       if r["match"] == "none" and r[f"mints_{lbl}"]),
            })
    return out
