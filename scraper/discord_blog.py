"""✍️ LES NOUVEAUX ARTICLES DU BLOG DANS LE POST FORUM « ✍️BLOG ».

Un message par VAGUE d'articles, avec un ping du role BLOG — et jamais deux
notifications pour la meme vague : **si trois articles paraissent la meme nuit,
ils partent dans UN SEUL message** (une carte chacun). Un ping = une notif.

⚠️ LA LECON DES « 1001 ARTICLES » (bug du digest, 12/07 — la plus chere de ce
projet). Je considerais comme « nouveau » tout slug absent de mon etat, et je ne
gardais que les 500 derniers slugs : a chaque run le bot deterrait des centaines
de vieux articles. **Preda a trouve la vraie sortie : « les articles ont une date
de parution dans le Sheet, pourquoi ne pas te baser dessus ? »**
→ **LA DATE DE PARUTION FAIT FOI.** Un article n'est annoncable que s'il est paru
dans les `DISCORD_BLOG_JOURS` derniers jours. Les slugs ne servent plus qu'a ne
pas repeter. Le module devient AUTO-GUERISSANT : meme avec un etat vide ou
corrompu, il ne peut plus annoncer que du recent.
**REGLE GENERALE : ne jamais faire d'un ETAT la source de verite quand une
donnee INTRINSEQUE existe dans les donnees.**

LES GARDE-FOUS (dans l'ordre ou ils se declenchent)
---------------------------------------------------
1. **1er run** (etat vide) : on MEMORISE tout, on n'annonce RIEN. Sinon le
   premier message pingerait le role avec 500 articles.
2. **Filtre par date de parution** : rien de plus vieux que 3 jours, jamais.
3. **Anti-avalanche** : au-dela de `DISCORD_BLOG_MAX_NEUFS` (5) « nouveaux »,
   on memorise sans annoncer et on le DIT dans les logs — un blog ne publie pas
   dix articles dans la nuit ; si ca arrive, c'est que quelque chose est casse,
   et on ne reveille pas le serveur pour un bug.
4. **Un seul message par run**, 10 cartes maximum (limite Discord).
5. **Quota de pings** : `DISCORD_BLOG_PING_MAX` (3) pings par jour au maximum.
   Au-dela, les articles sont quand meme publies — mais en SILENCE (sans ping).
   Un bot qui ping en boucle est un bot qu'on mute.
6. **Mentions bridees** : `allowed_mentions` n'autorise QUE le role BLOG. Meme
   si un titre d'article contenait « @everyone », il ne pingerait personne.
7. **429** : on attend le `retry_after` (cf. scraper/discord_api.py).

Env :
  SHEET_ID, GOOGLE_SERVICE_ACCOUNT_JSON
  DISCORD_HUB_WEBHOOK (ou DISCORD_BLOG_WEBHOOK si le post est dans un AUTRE
    salon — les posts d'un meme forum partagent le webhook du salon)
  DISCORD_BLOG_THREAD (id du post « ✍️BLOG »)
  DISCORD_BLOG_ROLE   (id du role a ping)
  DISCORD_BLOG_STATE (data/discord_blog_state.json) · DISCORD_BLOG_JOURS (3)
  DISCORD_BLOG_MAX_NEUFS (5) · DISCORD_BLOG_PING_MAX (3) · DISCORD_BLOG_EXCERPT (300)
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
import time
from typing import Any, Dict, List

from scraper import discord_api as api
from scraper.sheets import _client, append_log

MODULE = "blog"
THREAD = os.environ.get("DISCORD_BLOG_THREAD", "1526535133040087070").strip()
ROLE = os.environ.get("DISCORD_BLOG_ROLE", "1526535593071345685").strip()
STATE_PATH = os.environ.get("DISCORD_BLOG_STATE",
                            "data/discord_blog_state.json")
BLOG_TAB = os.environ.get("BLOG_TAB", "📝C-BLOG")

JOURS = int(os.environ.get("DISCORD_BLOG_JOURS", "3"))
MAX_NEUFS = int(os.environ.get("DISCORD_BLOG_MAX_NEUFS", "5"))
MAX_CARTES = int(os.environ.get("DISCORD_BLOG_MAX_CARTES", "10"))   # limite API
PING_MAX = int(os.environ.get("DISCORD_BLOG_PING_MAX", "3"))
EXCERPT = int(os.environ.get("DISCORD_BLOG_EXCERPT", "300"))

BLEU = 0x3498DB
AVERTISSEMENT = "ⓘ Article publié sur le blog officiel VeVe — lien vers la source."


# ---------------------------------------------------------------------------
# Lecture du Sheet
# ---------------------------------------------------------------------------

def _records(sh, tab: str) -> List[Dict[str, Any]]:
    try:
        ws = sh.worksheet(tab)
        try:
            from gspread.utils import ValueRenderOption
            return ws.get_all_records(
                value_render_option=ValueRenderOption.unformatted)
        except ImportError:
            return ws.get_all_records()
    except Exception as e:                                  # noqa: BLE001
        print(f"lecture de {tab} impossible : {e}", file=sys.stderr)
        return []


def _jour(x) -> str:
    """La date de parution, quel que soit le format du Sheet (ISO ou serial)."""
    s = str(x or "").strip()
    if not s:
        return ""
    if s.replace(".", "", 1).isdigit() and len(s) < 8:      # serial Sheets
        try:
            return (_dt.date(1899, 12, 30)
                    + _dt.timedelta(days=int(float(s)))).isoformat()
        except (ValueError, OverflowError):
            return ""
    return s[:10]


def articles(sh, connus: List[str], jours: int = None) -> List[Dict]:
    """Les articles PARUS RECEMMENT et pas encore annonces.

    Le filtre PRINCIPAL est la date de parution ; les slugs ne servent qu'a ne
    pas repeter (cf. la lecon des 1001 articles, en tete de fichier)."""
    jours = JOURS if jours is None else jours
    limite = (_dt.date.today() - _dt.timedelta(days=jours)).isoformat()
    vus = set(connus or [])
    out = []
    for r in _records(sh, BLOG_TAB):
        slug = str(r.get("slug", "")).strip()
        if not slug or slug in vus:
            continue
        paru = _jour(r.get("date") or r.get("published_at"))
        if paru and paru < limite:
            continue                       # trop vieux : ce n'est pas une news
        out.append({"slug": slug,
                    "titre": str(r.get("title") or slug),
                    "date": paru,
                    "url": str(r.get("url") or ""),
                    "excerpt": str(r.get("excerpt") or ""),
                    "image": str(r.get("image_url") or ""),
                    "categorie": str(r.get("category") or ""),
                    "auteur": str(r.get("author") or "")})
    out.sort(key=lambda a: a["date"], reverse=True)
    return out


def tous_les_slugs(sh) -> List[str]:
    return [str(r.get("slug", "")).strip() for r in _records(sh, BLOG_TAB)
            if str(r.get("slug", "")).strip()]


# ---------------------------------------------------------------------------
# Le message
# ---------------------------------------------------------------------------

def carte(a: Dict) -> Dict:
    texte = str(a.get("excerpt") or "").strip()
    if len(texte) > EXCERPT:
        texte = texte[:EXCERPT].rsplit(" ", 1)[0] + "…"
    bas = " · ".join(x for x in (a.get("categorie"), a.get("auteur"),
                                 a.get("date")) if x)
    e = {"title": str(a["titre"])[:250], "color": BLEU,
         "description": (texte or "Nouvel article")[:1000]}
    if a.get("url"):
        e["url"] = a["url"]
    if a.get("image"):
        e["image"] = {"url": a["image"]}
    if bas:
        e["footer"] = {"text": bas}
    return e


def message(neufs: List[Dict], ping: bool) -> Dict:
    """UN message pour toute la vague : si trois articles paraissent la meme
    nuit, ils partent ensemble — un ping, une notification."""
    n = len(neufs)
    tete = ("📝 **Nouvel article sur le blog VeVe**" if n == 1 else
            f"📝 **{n} nouveaux articles sur le blog VeVe**")
    contenu = f"<@&{ROLE}> {tete}" if (ping and ROLE) else tete
    return {"content": contenu,
            "embeds": [carte(a) for a in neufs[:MAX_CARTES]],
            # Le role BLOG et LUI SEUL : meme un titre contenant « @everyone »
            # ne pingerait personne.
            "allowed_mentions": api.mentions([ROLE] if (ping and ROLE) else [])}


# ---------------------------------------------------------------------------
# Le quota de pings
# ---------------------------------------------------------------------------

def peut_ping(state: Dict) -> bool:
    jour = _dt.date.today().isoformat()
    return int(state.get("pings", {}).get(jour, 0)) < PING_MAX


def note_ping(state: Dict) -> None:
    jour = _dt.date.today().isoformat()
    pings = state.setdefault("pings", {})
    pings[jour] = int(pings.get(jour, 0)) + 1
    for vieux in [j for j in pings if j < (_dt.date.today()
                                           - _dt.timedelta(days=7)).isoformat()]:
        pings.pop(vieux, None)             # menage : l'etat reste minuscule


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID", "").strip()
    if not sheet_id:
        print("SHEET_ID env var is not set.", file=sys.stderr)
        return 2
    wh = api.webhook(MODULE)
    sh = _client().open_by_key(sheet_id)
    state = api.load_state(STATE_PATH, wh, THREAD)
    premier = "slugs" not in state

    neufs = [] if premier else articles(sh, state.get("slugs", []))

    # GARDE-FOU 1 et 3 : le 1er run memorise sans annoncer ; une avalanche
    # d'articles « nouveaux » est un symptome, pas une actualite.
    if premier or len(neufs) > MAX_NEUFS:
        motif = ("1er run" if premier else
                 f"{len(neufs)} articles « nouveaux » (> {MAX_NEUFS})")
        state["slugs"] = tous_les_slugs(sh)
        print(f"{motif} -> etat (re)synchronise : {len(state['slugs'])} slugs "
              f"memorises SANS etre annonces. On ne reveille pas le serveur "
              f"pour un etat desynchronise.", flush=True)
        neufs = []

    if not neufs:
        api.save_state(STATE_PATH, state, wh, THREAD)
        print("Blog : aucun nouvel article a annoncer.", flush=True)
        _log(sheet_id, "OK", {"neufs": 0, "duree": f"{time.time() - t0:.0f}s"})
        return 0

    ping = peut_ping(state)
    if not ping:
        print(f"Quota de pings atteint ({PING_MAX}/jour) : les articles sont "
              f"publies, mais EN SILENCE.", flush=True)

    payload = message(neufs, ping)
    if not wh:
        print("[SIMULATION — pas de webhook]", flush=True)
        print(payload["content"], flush=True)
        for e in payload["embeds"]:
            print(f"  · {e['title']} — {e.get('url', '')}", flush=True)
        ok = True
    else:
        ok = bool(api.poster(wh, THREAD, payload))

    if ok:
        if ping:
            note_ping(state)
        # On garde TOUS les slugs (le fichier reste minuscule) : les tronquer
        # est precisement ce qui avait desynchronise l'etat du digest.
        state["slugs"] = list(dict.fromkeys(
            list(state.get("slugs", [])) + [a["slug"] for a in neufs]))
    api.save_state(STATE_PATH, state, wh, THREAD)

    resume = {"neufs": len(neufs), "ping": ping,
              "titres": " | ".join(a["titre"][:40] for a in neufs[:3]),
              "duree": f"{time.time() - t0:.0f}s"}
    _log(sheet_id, "OK" if ok else "ECHEC", resume)
    print(f"Blog Discord : {resume}", flush=True)
    return 0 if ok else 1


def _log(sheet_id: str, statut: str, resume: Dict) -> None:
    try:
        append_log(sheet_id, "discord_blog", statut,
                   "; ".join(f"{k}={v}" for k, v in resume.items()))
    except Exception:                                       # noqa: BLE001
        pass


if __name__ == "__main__":
    sys.exit(run())

# FIN discord_blog.py v1 — la date de parution fait foi, une vague = un message,
# un message = un ping, et jamais plus de 3 pings par jour.
