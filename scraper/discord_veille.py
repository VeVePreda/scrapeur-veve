# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/discord_veille.py

"""📰 LA VEILLE DES BLOGS PARTENAIRES — un module hub, N flux RSS, N salons.

Demande de Preda : publier les nouveaux articles d'**ElmonX** (Medium) et de
**Candy** (Ghost) dans LEUR post de forum respectif. Demain une 3e source = une
ligne dans `SOURCES`, rien d'autre.

POURQUOI DU RSS, PAS DU SCRAPING
--------------------------------
Medium et Candy exposent un flux **RSS 2.0** propre (titre, lien, date de
parution, auteur, catégories, corps). On lit le flux, point — pas de HTML à
gratter, pas de Sheet à traverser. C'est plus simple ET plus robuste que le
module `blog` VeVe (qui, lui, doit scraper un WordPress puis passer par le Sheet).

CE QU'ON REPREND MOT POUR MOT DU MODULE `blog` (leçons déjà payées)
-------------------------------------------------------------------
* **LA DATE DE PARUTION FAIT FOI.** Un article n'est annonçable que s'il est
  paru dans les `DISCORD_VEILLE_JOURS` derniers jours. L'état (les guid déjà vus)
  ne sert QU'À ne pas répéter — jamais de source de vérité. Même avec un état
  vide, on ne peut pas déterrer un vieil article. (cf. le bug des « 1001
  articles » du digest.)
* **1er run par source** : on mémorise tous les guid, on n'annonce RIEN (sinon
  le premier passage cracherait tout l'historique du flux).
* **Anti-avalanche** : au-delà de `DISCORD_VEILLE_MAX_NEUFS` (5) « nouveaux », on
  mémorise sans annoncer et on le dit — un blog ne publie pas dix articles dans
  la nuit ; si ça arrive, c'est un symptôme, pas une actualité.
* **Une vague = un message** : si trois articles paraissent ensemble, ils
  partent dans UN message (une carte chacun, 10 max — limite Discord).
* **Mentions bridées** : `allowed_mentions` par défaut ne ping RIEN. (Choix
  Preda : aucun ping pour la veille. Un rôle reste activable par source via
  `DISCORD_<SRC>_ROLE`, on l'autorise alors LUI SEUL.)
* **429 / plafond / espacement** : hérités de `scraper/discord_api.py`.

CE QUI CHANGE : PLUSIEURS SALONS, DONC PLUSIEURS WEBHOOKS
--------------------------------------------------------
Chaque source vise un POST DE FORUM (thread_id). Le webhook appartient au SALON
de forum : si ElmonX et Candy vivent dans le MÊME forum, un seul webhook suffit
(`DISCORD_VEILLE_WEBHOOK`) et seul le thread change ; s'ils sont dans deux forums
différents, chacun a le sien (`DISCORD_ELMONX_WEBHOOK`, `DISCORD_CANDY_WEBHOOK`).
La résolution essaie, dans l'ordre : le webhook de la source, celui de la veille,
puis celui du hub.

Env (par source SRC ∈ {ELMONX, CANDY}) :
  DISCORD_<SRC>_WEBHOOK   (sinon DISCORD_VEILLE_WEBHOOK, sinon hub)
  DISCORD_<SRC>_THREAD    (id du post de forum ; défaut fourni)
  DISCORD_<SRC>_ROLE      (id d'un rôle à ping ; vide = ne ping personne)
Communs :
  DISCORD_VEILLE_STATE (data/discord_veille_state.json)
  DISCORD_VEILLE_JOURS (3) · DISCORD_VEILLE_MAX_NEUFS (5) · DISCORD_VEILLE_EXCERPT (300)
  SHEET_ID, GOOGLE_SERVICE_ACCOUNT_JSON  (facultatif : juste pour le journal)
"""

from __future__ import annotations

import datetime as _dt
import html as _html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional

import requests

from scraper import discord_api as api

MODULE = "veille"

# ═══ LES SOURCES — ajouter un blog = ajouter une ligne ici ═══
# `cle` sert au préfixe d'env (DISCORD_ELMONX_*) et à la clé d'état.
SOURCES = [
    {"cle": "elmonx", "nom": "ElmonX",
     "feed": "https://medium.com/feed/elmonx",
     "thread_defaut": "1526847750749028352",
     "couleur": 0x2B6FFF, "emoji": "🔷"},
    {"cle": "candy", "nom": "Candy",
     "feed": "https://blog.candy.io/rss",
     "thread_defaut": "1526846817931755652",
     "couleur": 0xEC4899, "emoji": "🍬"},
]

STATE_PATH = os.environ.get("DISCORD_VEILLE_STATE",
                            "data/discord_veille_state.json")
JOURS = int(os.environ.get("DISCORD_VEILLE_JOURS", "3"))
MAX_NEUFS = int(os.environ.get("DISCORD_VEILLE_MAX_NEUFS", "5"))
MAX_CARTES = int(os.environ.get("DISCORD_VEILLE_MAX_CARTES", "10"))   # limite API
EXCERPT = int(os.environ.get("DISCORD_VEILLE_EXCERPT", "300"))

# Un User-Agent de navigateur : certains hébergeurs répondent 403 à un client
# « python-requests » (cf. la leçon GoChain). On se présente proprement.
UA = os.environ.get("DISCORD_VEILLE_UA",
                    "Mozilla/5.0 (compatible; VeVeFranceVeille/1.0; +https://veve.co)")
TIMEOUT = 20

NS = {"content": "http://purl.org/rss/1.0/modules/content/",
      "dc": "http://purl.org/dc/elements/1.1/"}

AVERTISSEMENT = "ⓘ Article publié sur le blog officiel de la marque — lien vers la source."


# ---------------------------------------------------------------------------
# Résolution des réglages d'une source
# ---------------------------------------------------------------------------

def _env(cle: str, suffixe: str, defaut: str = "") -> str:
    return os.environ.get(f"DISCORD_{cle.upper()}_{suffixe}", defaut).strip()


def _webhook(cle: str) -> str:
    for v in (_env(cle, "WEBHOOK"),
              os.environ.get("DISCORD_VEILLE_WEBHOOK", "").strip(),
              api.webhook(MODULE)):
        if v:
            return v
    return ""


# ---------------------------------------------------------------------------
# Lecture d'un flux RSS -> liste d'articles normalisés
# ---------------------------------------------------------------------------

def _texte(html_brut: str) -> str:
    """HTML -> texte nu (balises retirées, entités décodées, espaces tassés)."""
    sans = re.sub(r"<[^>]+>", " ", html_brut or "")
    return re.sub(r"\s+", " ", _html.unescape(sans)).strip()


def _image(html_brut: str) -> str:
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_brut or "")
    return m.group(1) if m else ""


def _date_iso(pub: str) -> str:
    """« Tue, 21 Jul 2026 21:33:26 GMT » -> « 2026-07-21 » (vide si illisible)."""
    if not pub:
        return ""
    try:
        return parsedate_to_datetime(pub).date().isoformat()
    except (TypeError, ValueError, IndexError):
        return ""


def parser(xml_text: str) -> List[Dict]:
    """Les items d'un flux RSS 2.0 (Medium, Ghost…), du plus récent au plus
    ancien. On ne lève JAMAIS : un flux malformé rend une liste vide."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"flux illisible (XML) : {e}", file=sys.stderr)
        return []
    out = []
    for it in root.iter("item"):
        titre = (it.findtext("title") or "").strip()
        lien = (it.findtext("link") or "").strip()
        guid = (it.findtext("guid") or lien or "").strip()
        if not guid:
            continue
        corps = (it.findtext("content:encoded", default="", namespaces=NS)
                 or it.findtext("description", default="") or "")
        desc = it.findtext("description", default="") or ""
        cats = [c.text.strip() for c in it.findall("category")
                if c is not None and c.text]
        out.append({
            "guid": guid,
            "titre": titre or lien,
            "url": lien,
            "date": _date_iso(it.findtext("pubDate") or ""),
            "auteur": (it.findtext("dc:creator", default="", namespaces=NS) or "").strip(),
            "categorie": cats[0] if cats else "",
            "excerpt": _texte(desc) or _texte(corps),
            "image": _image(corps) or _image(desc),
        })
    out.sort(key=lambda a: a["date"], reverse=True)
    return out


def charger_flux(url: str) -> Optional[str]:
    """Le XML brut, ou None si la source ne répond pas (on n'invente rien)."""
    for essai in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": UA,
                                           "Accept": "application/rss+xml, application/xml, text/xml"},
                             timeout=TIMEOUT)
            if r.status_code >= 400:
                print(f"{url} : HTTP {r.status_code}", file=sys.stderr)
                return None
            return r.text
        except requests.RequestException as e:
            print(f"{url} : {e} (essai {essai + 1}/3)", file=sys.stderr)
            time.sleep(2 * (essai + 1))
    return None


# ---------------------------------------------------------------------------
# Le message (une vague = un message, une carte par article)
# ---------------------------------------------------------------------------

def carte(src: Dict, a: Dict) -> Dict:
    texte = a.get("excerpt") or "Nouvel article"
    if len(texte) > EXCERPT:
        texte = texte[:EXCERPT].rsplit(" ", 1)[0] + "…"
    bas = " · ".join(x for x in (src["nom"], a.get("categorie"),
                                 a.get("auteur"), a.get("date")) if x)
    e = {"title": a["titre"][:250], "color": src["couleur"],
         "description": texte[:1000]}
    if a.get("url"):
        e["url"] = a["url"]
    if a.get("image"):
        e["image"] = {"url": a["image"]}
    if bas:
        e["footer"] = {"text": bas}
    return e


def message(src: Dict, neufs: List[Dict], role: str) -> Dict:
    n = len(neufs)
    tete = (f"{src['emoji']} **Nouvel article — {src['nom']}**" if n == 1 else
            f"{src['emoji']} **{n} nouveaux articles — {src['nom']}**")
    contenu = f"<@&{role}> {tete}" if role else tete
    return {"content": contenu,
            "embeds": [carte(src, a) for a in neufs[:MAX_CARTES]],
            "allowed_mentions": api.mentions([role] if role else None)}


# ---------------------------------------------------------------------------
# État (guid déjà vus, par source) — simple, sans empreinte : le dédoublonnage
# se fait par guid, pas besoin de lier l'état à un webhook.
# ---------------------------------------------------------------------------

def charger_etat() -> Dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                       # noqa: BLE001
        return {}


def sauver_etat(st: Dict) -> None:
    st["maj"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(STATE_PATH) or ".", exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Une source, de bout en bout
# ---------------------------------------------------------------------------

def traiter(src: Dict, etat: Dict) -> bool:
    cle = src["cle"]
    wh = _webhook(cle)
    thread = _env(cle, "THREAD", src["thread_defaut"])
    role = _env(cle, "ROLE")                      # défaut vide -> aucun ping

    xml_text = charger_flux(src["feed"])
    if xml_text is None:
        print(f"[{src['nom']}] flux injoignable — on ne touche à rien.",
              flush=True)
        return False
    articles = parser(xml_text)
    if not articles:
        print(f"[{src['nom']}] flux vide ou illisible — rien à faire.",
              flush=True)
        return True

    sous = etat.setdefault(cle, {})
    premier = "guids" not in sous
    vus = set(sous.get("guids", []))
    tous = [a["guid"] for a in articles]

    # LA DATE FAIT FOI : on ne retient que le récent ET le non-déjà-vu.
    limite = (_dt.date.today() - _dt.timedelta(days=JOURS)).isoformat()
    neufs = [a for a in articles
             if a["guid"] not in vus and (not a["date"] or a["date"] >= limite)]

    # 1er run + anti-avalanche : on mémorise, on n'annonce pas.
    if premier or len(neufs) > MAX_NEUFS:
        motif = ("1er run" if premier
                 else f"{len(neufs)} articles « nouveaux » (> {MAX_NEUFS})")
        sous["guids"] = list(dict.fromkeys(list(vus) + tous))
        print(f"[{src['nom']}] {motif} -> {len(sous['guids'])} guid mémorisés "
              f"SANS annonce.", flush=True)
        return True

    if not neufs:
        print(f"[{src['nom']}] aucun nouvel article.", flush=True)
        return True

    payload = message(src, neufs, role)
    if not wh:
        print(f"\n[{src['nom']} — SIMULATION, pas de webhook] {payload['content']}",
              flush=True)
        for e in payload["embeds"]:
            print(f"  · {e['title']} — {e.get('url', '')}", flush=True)
        ok = True
    else:
        ok = bool(api.poster(wh, thread, payload))
        if ok:
            api.souffler()

    if ok:
        sous["guids"] = list(dict.fromkeys(
            list(vus) + [a["guid"] for a in neufs]))
        print(f"[{src['nom']}] {len(neufs)} article(s) publié(s).", flush=True)
    return ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run() -> int:
    t0 = time.time()
    etat = charger_etat()
    ok = True
    for src in SOURCES:
        try:
            if not traiter(src, etat):
                ok = False
        except Exception:                                   # noqa: BLE001
            import traceback
            traceback.print_exc()
            ok = False
    sauver_etat(etat)

    # Journal (facultatif : n'échoue jamais le module s'il manque le Sheet).
    try:
        from scraper.sheets import append_log
        sheet_id = os.environ.get("SHEET_ID", "").strip()
        if sheet_id:
            append_log(sheet_id, "discord_veille", "OK" if ok else "ECHEC",
                       f"sources={len(SOURCES)}; duree={time.time() - t0:.0f}s")
    except Exception:                                       # noqa: BLE001
        pass

    print(f"Veille : {len(SOURCES)} source(s), {time.time() - t0:.0f}s, "
          f"{'OK' if ok else 'au moins un échec'}.", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())

# FIN discord_veille.py — un flux RSS par source, la date de parution fait foi,
# une vague = un message, et une source qui tombe n'emporte pas l'autre.
