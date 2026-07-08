"""
VeVe blog scraper — article catalogue with FULL article content.

Source
------
The VeVe blog (https://www.veve.me/blog/) is a classic server-rendered WordPress
site (Yoast SEO). Two levels are scraped:

1. Listing pages (/blog/page/N/) — one card per article gives the title, its
   permalink, the primary category, the tags, the excerpt, the date and the
   cover image. No JavaScript rendering needed.
2. Each article page — for the FULL body text (div.entry-content) plus the
   author, reading time, precise excerpt and cover image, all exposed cleanly in
   the page's <meta> tags (article:published_time, twitter "Written by" /
   "Time to read", og:description, og:image).

Discretion / volume: article pages are only fetched for articles NOT already in
the sheet (or whose content cell is empty). So the first run does a full backfill
(~1 request per article, ~1000 total), and every later run only fetches the
handful of brand-new posts.

WordPress permalinks are the stable anchors we parse the listing against:
    - category links   ->  href contains  /blog/category/
    - tag links        ->  href contains  /blog/tag/
    - the date link    ->  title="date-time"  (href like /2026/07)
    - the article link ->  /blog/<cat-path>/<slug>/  (not category/tag/page)

Rows are upserted by slug and never deleted (a source hiccup can't wipe the tab).

Runs on demand (scraper/blog_run.py). Env: GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID,
BLOG_MAX_PAGES (0 = all listing pages), BLOG_WITH_CONTENT (default true),
BLOG_MAX_NEW (0 = no cap on article fetches per run).
"""

from __future__ import annotations

import datetime as _dt
import re
import time
from typing import Any, Dict, List, Optional, Set

import requests
from bs4 import BeautifulSoup

from scraper import sheets

BLOG_BASE = "https://www.veve.me/blog"
BLOG_TAB = "📝C-BLOG"
BLOG_HEADER = [
    "slug", "date", "title", "category", "tags", "author", "reading_time",
    "excerpt", "content", "url", "image_url", "first_seen", "last_seen",
]
KEY = "slug"
CONTENT_COL = "content"

REQUEST_TIMEOUT = 60
MAX_RETRIES = 4
RETRY_BACKOFF = 3            # seconds * attempt
PAUSE_BETWEEN_PAGES = 0.5    # between listing pages
PAUSE_BETWEEN_ARTICLES = 0.25  # between article-page fetches
SAFETY_PAGE_CAP = 200        # never loop forever
CONTENT_MAX_CHARS = 45000    # Google Sheets cell limit is 50k; keep a margin

USER_AGENT = "veve-blog-sync/1.0 (personal catalogue export)"

_CAT_RE = re.compile(r"/blog/category/", re.I)
_TAG_RE = re.compile(r"/blog/tag/", re.I)
_PAGE_RE = re.compile(r"/blog/page/\d+", re.I)
_DATE_HREF_RE = re.compile(r"/20\d\d/\d\d", re.I)
_AUTHOR_RE = re.compile(r"/author/", re.I)
# an article permalink: /blog/<something>/…/<slug>/  (excludes category/tag/page)
_ARTICLE_RE = re.compile(r"/blog/(?!category/|tag/|page/)[^?#]+/[^?#]+/?$", re.I)
_NOISE_CLASS_RE = re.compile(
    r"(related|share|social|post-navigation|comments?|author-box|newsletter)", re.I)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


def _get(session: requests.Session, url: str) -> Optional[str]:
    """GET a page. Returns HTML, or None on a 404 (past the last page / gone)."""
    last_err: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            wait = RETRY_BACKOFF * attempt
            print(f"    request failed (attempt {attempt}/{MAX_RETRIES}): {e} "
                  f"— retrying in {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"Gave up fetching {url}: {last_err}")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _slug_from_url(url: str) -> str:
    path = re.sub(r"[?#].*$", "", url or "").rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def _parse_date(text: str) -> str:
    """'July 6, 2026' -> '2026-07-06' (empty string if unparseable)."""
    t = (text or "").strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return _dt.datetime.strptime(t, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _img_src(img) -> str:
    if img is None:
        return ""
    for attr in ("data-src", "data-lazy-src", "src"):
        v = img.get(attr)
        if v and not v.startswith("data:"):
            return v.strip()
    srcset = img.get("srcset") or img.get("data-srcset")
    if srcset:
        return srcset.split(",")[0].strip().split(" ")[0]
    return ""


# ---------------------------------------------------------------------------
# Listing parsing
# ---------------------------------------------------------------------------

def _card_containers(soup: BeautifulSoup) -> List[Any]:
    """One container element per article card. Primary: WordPress <article>.
    Fallback: the parent of each article-title heading."""
    articles = soup.find_all("article")
    if articles:
        return articles
    seen: List[str] = []
    containers: List[Any] = []
    for h in soup.find_all(re.compile(r"^h[1-4]$")):
        a = h.find("a", href=True)
        if a and _ARTICLE_RE.search(a["href"]) and a["href"] not in seen:
            seen.append(a["href"])
            containers.append(h.parent or h)
    return containers


def _extract_card(card) -> Optional[Dict[str, Any]]:
    anchors = card.find_all("a", href=True)
    if not anchors:
        return None

    category = ""
    tags: List[str] = []
    date = ""
    title = ""
    url = ""

    for a in anchors:
        href = a["href"]
        txt = a.get_text(" ", strip=True)
        if _CAT_RE.search(href):
            if not category:
                category = txt
        elif _TAG_RE.search(href):
            if txt:
                tags.append(txt)
        elif a.get("title") == "date-time" or _DATE_HREF_RE.search(href):
            if not date:
                date = _parse_date(txt)
        elif _ARTICLE_RE.search(href) and _PAGE_RE.search(href) is None:
            if txt and txt.lower() != "read more" and len(txt) > len(title):
                title, url = txt, href
            elif not url:
                url = href

    if not url:
        return None

    heading = card.find(re.compile(r"^h[1-4]$"))
    if heading:
        h_txt = heading.get_text(" ", strip=True)
        if h_txt:
            title = h_txt

    excerpt = ""
    for p in card.find_all("p"):
        t = p.get_text(" ", strip=True)
        if t and t.lower() != "read more" and t != title:
            excerpt = t
            break

    image_url = _img_src(card.find("img"))

    return {
        "slug": _slug_from_url(url),
        "date": date,
        "title": title,
        "category": category,
        "tags": ", ".join(dict.fromkeys(tags)),
        "excerpt": excerpt,
        "url": re.sub(r"[?#].*$", "", url),
        "image_url": image_url,
    }


def parse_listing(html: str) -> List[Dict[str, Any]]:
    """All article cards on one listing page."""
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []
    for card in _card_containers(soup):
        rec = _extract_card(card)
        if rec and rec.get("slug"):
            out.append(rec)
    return out


def scrape_blog(max_pages: int = 0) -> List[Dict[str, Any]]:
    """Walk the blog listing pages and return one row per article (deduped by slug)."""
    session = _session()
    by_slug: Dict[str, Dict[str, Any]] = {}
    page = 1
    cap = max_pages if max_pages > 0 else SAFETY_PAGE_CAP
    while page <= cap:
        url = f"{BLOG_BASE}/" if page == 1 else f"{BLOG_BASE}/page/{page}/"
        html = _get(session, url)
        if html is None:
            break
        cards = parse_listing(html)
        if not cards:
            break
        new = 0
        for c in cards:
            if c["slug"] not in by_slug:
                new += 1
            by_slug[c["slug"]] = c
        print(f"    page {page}: {len(cards)} cards ({len(by_slug)} unique so far)",
              flush=True)
        if new == 0 and page > 1:
            break
        page += 1
        time.sleep(PAUSE_BETWEEN_PAGES)

    articles = list(by_slug.values())
    articles.sort(key=lambda r: (r.get("date", ""), r.get("slug", "")), reverse=True)
    print(f"TOTAL blog articles listed: {len(articles)} (scanned {page - 1} page(s))",
          flush=True)
    return articles


# ---------------------------------------------------------------------------
# Article-page parsing (full content + author + reading time via meta tags)
# ---------------------------------------------------------------------------

def _meta_map(soup: BeautifulSoup) -> Dict[str, str]:
    metas: Dict[str, str] = {}
    for m in soup.find_all("meta"):
        key = m.get("property") or m.get("name")
        val = m.get("content")
        if key and val is not None and key not in metas:
            metas[key] = val
    return metas


def _meta_by_label(metas: Dict[str, str], label: str) -> str:
    """Twitter card label/data pairs: return the data whose label matches."""
    for i in ("1", "2", "3", "4"):
        if (metas.get(f"twitter:label{i}") or "").strip().lower() == label.lower():
            return (metas.get(f"twitter:data{i}") or "").strip()
    return ""


def _extract_content(soup: BeautifulSoup, metas: Dict[str, str]) -> str:
    node = (soup.select_one("div.entry-content")
            or soup.select_one("article .entry-content")
            or soup.select_one("[class*=entry-content]")
            or soup.find("article"))
    if node is None:
        return (metas.get("og:description") or metas.get("description") or "").strip()

    for bad in node.select("script, style, noscript"):
        bad.decompose()
    for bad in node.find_all(class_=_NOISE_CLASS_RE):
        bad.decompose()

    text = node.get_text("\n", strip=True)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > CONTENT_MAX_CHARS:
        text = text[:CONTENT_MAX_CHARS].rstrip() + "…"
    return text


def parse_article(html: str) -> Dict[str, Any]:
    """Full-content fields from one article page."""
    soup = BeautifulSoup(html, "html.parser")
    metas = _meta_map(soup)

    author = _meta_by_label(metas, "Written by")
    if not author:
        a = soup.find("a", href=_AUTHOR_RE)
        if a:
            author = a.get_text(" ", strip=True)

    published = metas.get("article:published_time", "")
    date = published[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", published or "") else ""

    return {
        "author": author,
        "reading_time": _meta_by_label(metas, "Time to read"),
        "excerpt": (metas.get("og:description") or metas.get("description") or "").strip(),
        "image_url": (metas.get("og:image") or "").strip(),
        "category": (metas.get("article:section") or "").strip(),
        "date": date,
        "content": _extract_content(soup, metas),
    }


def enrich_with_content(articles: List[Dict[str, Any]], skip_slugs: Set[str],
                        max_new: int = 0, checkpoint_every: int = 0,
                        on_checkpoint=None) -> int:
    """Fetch each article page (skipping slugs that already have content) and add
    the full-content fields in place. Returns how many pages were fetched.

    checkpoint_every / on_checkpoint: if set, on_checkpoint(articles) is called
    every `checkpoint_every` fetched articles so progress can be persisted before
    a long backfill risks hitting the job timeout (the run stays resumable — a
    later run skips articles that already carry content)."""
    session = _session()
    todo = [a for a in articles if a.get("slug") and a["slug"] not in skip_slugs]
    print(f"Fetching full content for {len(todo)} article(s) "
          f"({len(skip_slugs)} already have content)...", flush=True)
    fetched = 0
    for art in todo:
        if max_new and fetched >= max_new:
            print(f"    reached BLOG_MAX_NEW={max_new} — stopping content fetch.",
                  flush=True)
            break
        try:
            html = _get(session, art["url"])
        except Exception as e:
            print(f"    skip {art['slug']}: {e}", flush=True)
            continue
        if html is None:
            continue
        extra = parse_article(html)
        # Only overwrite listing fields when the article page has a value.
        for k, v in extra.items():
            if v not in (None, ""):
                art[k] = v
        fetched += 1
        if fetched % 25 == 0:
            print(f"    ... {fetched}/{len(todo)} articles fetched", flush=True)
        if checkpoint_every and on_checkpoint and fetched % checkpoint_every == 0:
            try:
                on_checkpoint(articles)
                print(f"    checkpoint saved at {fetched}/{len(todo)}.", flush=True)
            except Exception as e:
                print(f"    checkpoint warning: {e}", flush=True)
        time.sleep(PAUSE_BETWEEN_ARTICLES)
    print(f"Content fetched for {fetched} article(s).", flush=True)
    return fetched


# ---------------------------------------------------------------------------
# Sheet sync (upsert by slug — rows are never deleted)
# ---------------------------------------------------------------------------

def _open(spreadsheet_id: str):
    gc = sheets._client()
    sh = gc.open_by_key(spreadsheet_id)
    ws = sheets._open_worksheet(sh, BLOG_TAB, cols=len(BLOG_HEADER))
    return sh, ws


def _read_existing(ws) -> Dict[str, Dict[str, Any]]:
    existing: Dict[str, Dict[str, Any]] = {}
    if ws.row_count > 1:
        for r in ws.get_all_records():
            sid = str(r.get(KEY, "")).strip()
            if sid:
                existing[sid] = dict(r)
    return existing


def slugs_with_content(spreadsheet_id: str) -> Set[str]:
    """Slugs already carrying a non-empty content cell (skip re-fetching those)."""
    try:
        _, ws = _open(spreadsheet_id)
    except Exception as e:
        print(f"    could not read existing blog tab: {e}", flush=True)
        return set()
    out: Set[str] = set()
    for sid, rec in _read_existing(ws).items():
        if str(rec.get(CONTENT_COL, "")).strip():
            out.add(sid)
    return out


def sync_blog(articles: List[Dict[str, Any]], spreadsheet_id: str) -> Dict[str, Any]:
    """Merge scraped articles into the "📝C-BLOG" tab.

    Guard-rail: if nothing was harvested we abort without touching the tab, so a
    fetch failure can never wipe the existing rows.
    """
    if not articles:
        return {"status": "FAILED_NO_DATA",
                "note": "no blog articles harvested — tab left untouched."}

    sh, ws = _open(spreadsheet_id)
    existing = _read_existing(ws)

    now = sheets._now()
    added, updated = 0, 0
    new_titles: List[str] = []
    merged: Dict[str, Dict[str, Any]] = dict(existing)

    for art in articles:
        sid = str(art.get(KEY, "")).strip()
        if not sid:
            continue
        if sid in merged:
            old = merged[sid]
            rec = {**old, **{k: v for k, v in art.items() if v not in (None, "")}}
            rec["first_seen"] = old.get("first_seen") or now
            rec["last_seen"] = now
            merged[sid] = rec
            updated += 1
        else:
            rec = dict(art)
            rec["first_seen"] = now
            rec["last_seen"] = now
            merged[sid] = rec
            added += 1
            new_titles.append(art.get("title", "") or sid)

    ordered = sorted(merged.values(),
                     key=lambda r: (str(r.get("date", "")), str(r.get("slug", ""))),
                     reverse=True)
    grid = [BLOG_HEADER] + [[rec.get(col, "") for col in BLOG_HEADER]
                            for rec in ordered]

    ws.clear()
    ws.update(range_name="A1", values=grid, value_input_option="RAW")
    try:
        ws.freeze(rows=1)
        ws.format("1:1", {"textFormat": {"bold": True}})
    except Exception as e:
        print(f"    formatting warning: {e}", flush=True)

    cats = {str(r.get("category", "")).strip() for r in merged.values()
            if str(r.get("category", "")).strip()}
    with_content = sum(1 for r in merged.values()
                       if str(r.get(CONTENT_COL, "")).strip())

    return {
        "status": "OK",
        "total_rows": len(merged),
        "new_articles": added,
        "updated_articles": updated,
        "with_content": with_content,
        "categories": len(cats),
        "new_titles": new_titles[:30],
    }


if __name__ == "__main__":
    import sys
    lim = 2 if "--test" in sys.argv else 0
    items = scrape_blog(max_pages=lim)
    if items and "--content" in sys.argv:
        enrich_with_content(items[:3], skip_slugs=set())
    print(f"Got {len(items)} articles.")
    if items:
        print("Columns:", ", ".join(items[0].keys()))
        print("Sample:", {k: (v[:80] + "…" if isinstance(v, str) and len(v) > 80 else v)
                           for k, v in items[0].items()})
