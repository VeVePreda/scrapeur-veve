# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/ecomi_run.py

"""🪙 ECOMI / TOKEN OMI → l'onglet 📝C-BLOG. UN COLLECTEUR, RIEN D'AUTRE.

Demande de Preda (03/08/2026) : collecter les articles d'ECOMI — le compte
Medium officiel du **token OMI** — et les publier sur Discord.

⭐⭐ POURQUOI CE FICHIER EXISTE, ALORS QUE `discord_veille.py` SAVAIT DÉJÀ LIRE
UN FLUX RSS
-------------------------------------------------------------------------------
Parce que **le blog VeVe ne marche pas comme ça**, et que Preda a posé la bonne
question : « es-tu sûr que c'est le même système ? ». Non, ça ne l'était pas.

Le blog VeVe a DEUX ÉTAGES, et le Sheet est la charnière :

    blog.yml (02:00 UTC) ──► scraper/blog_run.py ──► onglet 📝C-BLOG
                                                          │
    discord.yml (07:45 UTC) ──► scraper/discord_blog.py ◄──┘  (LIT, puis annonce)

L'en-tête de `discord.yml` l'écrit noir sur blanc : « Il ne COLLECTE RIEN : il
lit ce que le pipeline a déjà écrit dans le Sheet. »

Ma première version d'ECOMI faisait les trois d'un coup (lire le RSS, écrire le
Sheet, annoncer) depuis le hub Discord. Ça marchait — et ça créait **un second
chemin d'écriture vers le même onglet**, donc **deux annonceurs possibles pour
un même article**, donc un garde-fou de plus à maintenir. C'est la famille de
bug qui nous a coûté six jours de republications le 28/07.

⭐ **Une source de plus ne doit pas amener une architecture de plus.** ECOMI
entre donc par la MÊME porte que le blog VeVe : ce module collecte et écrit,
`discord_blog.py` annonce. Un écrivain, un annonceur.

CE QU'IL FAIT, ET CE QU'IL NE FAIT PAS
--------------------------------------
· Lit le flux RSS d'ECOMI, en fabrique des lignes au format de `blog.py`, et
  appelle **son** `sync_blog()` — même upsert par `slug`, même garde-fou
  « 0 article n'écrase rien », même tri. ⛔ On ne réécrit JAMAIS un second
  chemin d'écriture vers un onglet : deux chemins = deux comportements le jour
  où l'un des deux change. (Même principe que `medium_vers_blog.py`.)
· ⛔ **Il ne parle pas à Discord.** Pas un webhook, pas un jeton, pas un ping.

LES PRÉCAUTIONS, CHACUNE POUR UN RISQUE MESURÉ
-----------------------------------------------
1. ⭐ **`slug` préfixé `ecomi-`** (leçon `medium-`). Une collision de slug entre
   deux sources ne ferait pas un doublon : elle **fusionnerait deux articles en
   une seule ligne**, en silence. Le préfixe rend la collision impossible et se
   repère à l'œil dans l'onglet.
2. ⭐ **`category` et `author` = `ECOMI`.** La provenance vit DANS LA DONNÉE,
   pas seulement dans le préfixe du slug : l'onglet se filtre à l'œil ou par
   formule, et c'est de là que `discord_blog.py` tire la couleur et la ligne
   d'auteur de la carte.
3. ⭐ **On reverse TOUT le flux à chaque passage**, pas seulement les
   nouveautés. `sync_blog` est un upsert : reverser un article déjà présent ne
   coûte rien, et un versement raté (Sheet indisponible, quota) **se répare tout
   seul** au passage suivant. L'écriture n'a lieu que si au moins un slug manque
   — un jour ordinaire ne fait donc qu'UNE lecture.
4. ⭐ **Chez Medium, le RSS met TOUT l'article dans `description`.** Recopié tel
   quel, `excerpt` dirait la même chose que `content` (7 343 signes sur
   « Introducing OMI Unlimited »). On taille donc un vrai chapô.
5. ⭐ **Les liens sont nettoyés du mouchard `?source=rss-…`** que Medium colle à
   chaque URL : deux passages ne doivent pas produire deux adresses différentes
   pour le même article.
6. ⛔ **AUCUN FILTRE PAR SUJET, délibérément.** Vérifié le 03/08 : les 10
   articles du flux portent le tag `omi` — ce compte ne parle que du token. Un
   filtre par mots-clés n'écarterait rien aujourd'hui, mais ferait disparaître
   **en silence** le premier article hors moule. Un article de trop se lit et
   s'oublie ; un article manqué ne se rattrape pas. À la place, **le tag de
   chaque ligne versée est écrit dans le journal du run** : la dérive se verra
   là, et se décidera sur des faits.

⚠️ QUOTA SHEETS PARTAGÉ : ce module s'exécute DANS `blog.yml`, à la suite de
`blog_run`, donc dans le même job et sous la même `concurrency` — jamais en
parallèle d'une autre écriture du même onglet. ⛔ Ne pas lui donner son propre
workflow : ce serait rouvrir la porte d'une écriture concurrente.

ENV :
  SHEET_ID · GOOGLE_SERVICE_ACCOUNT_JSON      (obligatoires)
  ECOMI_FEED       (défaut https://medium.com/feed/@ecomi-official)
  ECOMI_PREFIXE    (défaut `ecomi-`)   ⛔ le changer casse le lien avec
                   `discord_blog.py`, qui reconnaît la source par ce préfixe.
  ECOMI_CATEGORIE  (défaut `ECOMI`)
  ECOMI_APERCU     (1 = dire ce qu'il ferait, n'écrire NULLE PART)

Lancement : `python -m scraper.ecomi_run`  (ou `--apercu`)
"""

from __future__ import annotations

import html as _html
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List

import requests

from scraper import blog

FEED = os.environ.get("ECOMI_FEED",
                      "https://medium.com/feed/@ecomi-official").strip()
PREFIXE = os.environ.get("ECOMI_PREFIXE", "ecomi-").strip()
CATEGORIE = os.environ.get("ECOMI_CATEGORIE", "ECOMI").strip()
AUTEUR_DEFAUT = "ECOMI"
APERCU = os.environ.get("ECOMI_APERCU", "").strip() in ("1", "oui", "true") \
    or "--apercu" in sys.argv

# Un User-Agent de navigateur : certains hébergeurs répondent 403 à un client
# « python-requests » (leçon GoChain). On se présente proprement.
UA = os.environ.get("ECOMI_UA",
                    "Mozilla/5.0 (compatible; VeVeFranceVeille/1.0; +https://veve.co)")
TIMEOUT = 20
ESSAIS = 3

CONTENU_MAX = blog.CONTENT_MAX_CHARS     # 45 000 : la cellule Sheets coupe à 50 000
CHAPO = 400

NS = {"content": "http://purl.org/rss/1.0/modules/content/",
      "dc": "http://purl.org/dc/elements/1.1/"}


# ---------------------------------------------------------------------------
# Lecture du flux
# ---------------------------------------------------------------------------

def _texte(html_brut: str) -> str:
    """HTML -> texte nu (balises retirées, entités décodées, espaces tassés)."""
    sans = re.sub(r"<[^>]+>", " ", html_brut or "")
    return re.sub(r"\s+", " ", _html.unescape(sans)).strip()


def _image(html_brut: str) -> str:
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_brut or "")
    return m.group(1) if m else ""


def _url_propre(url: str) -> str:
    """Retire le mouchard `?source=rss-…` que Medium colle à chaque lien."""
    return re.sub(r"[?&]source=[^&]*", "", url or "").rstrip("?&")


def _date_iso(pub: str) -> str:
    """« Fri, 31 Jul 2026 18:44:44 GMT » -> « 2026-07-31 » (vide si illisible)."""
    if not pub:
        return ""
    try:
        return parsedate_to_datetime(pub).date().isoformat()
    except (TypeError, ValueError, IndexError):
        return ""


def _slug(guid: str, url: str) -> str:
    """`https://medium.com/p/bed907a5488b` -> `ecomi-bed907a5488b`.

    On part du GUID, pas de l'URL : Medium met le titre dans l'adresse, et un
    titre corrigé après publication changerait le slug — donc créerait une
    seconde ligne pour le même article. Le guid, lui, ne bouge pas."""
    brut = (guid or url or "").rstrip("/").split("/")[-1]
    brut = re.sub(r"[?#].*$", "", brut)
    brut = re.sub(r"[^A-Za-z0-9_-]+", "-", brut).strip("-").lower()
    return f"{PREFIXE}{brut}" if brut else ""


def _chapo(texte: str, n: int = CHAPO) -> str:
    texte = (texte or "").strip()
    return texte if len(texte) <= n else texte[:n].rsplit(" ", 1)[0] + "…"


def charger_flux(url: str = FEED) -> str:
    """Le XML brut, ou "" si la source ne répond pas. ⛔ On n'invente rien : un
    flux injoignable ne doit PAS produire une liste vide qui ressemblerait à
    « ECOMI n'a rien publié »."""
    for essai in range(ESSAIS):
        try:
            r = requests.get(url, headers={
                "User-Agent": UA,
                "Accept": "application/rss+xml, application/xml, text/xml"},
                timeout=TIMEOUT)
            if r.status_code >= 400:
                print(f"{url} : HTTP {r.status_code}", file=sys.stderr)
            else:
                return r.text
        except requests.RequestException as e:
            print(f"{url} : {e} (essai {essai + 1}/{ESSAIS})", file=sys.stderr)
        time.sleep(2 * (essai + 1))
    return ""


def lignes(xml_text: str) -> List[Dict[str, Any]]:
    """Les items du flux, au format des colonnes de `blog.py`."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"flux illisible (XML) : {e}", file=sys.stderr)
        return []
    out: List[Dict[str, Any]] = []
    for it in root.iter("item"):
        lien = (it.findtext("link") or "").strip()
        guid = (it.findtext("guid") or lien or "").strip()
        slug = _slug(guid, lien)
        if not slug:
            continue
        corps_html = (it.findtext("content:encoded", default="", namespaces=NS)
                      or it.findtext("description", default="") or "")
        desc_html = it.findtext("description", default="") or ""
        corps = _texte(corps_html)
        if len(corps) > CONTENU_MAX:
            corps = corps[:CONTENU_MAX].rstrip() + "…"
        cats = [c.text.strip() for c in it.findall("category")
                if c is not None and c.text]
        out.append({
            "slug": slug,
            "date": _date_iso(it.findtext("pubDate") or ""),
            "title": (it.findtext("title") or lien or "").strip(),
            "category": CATEGORIE,
            "tags": ", ".join(cats),
            "author": (it.findtext("dc:creator", default="",
                                   namespaces=NS) or "").strip() or AUTEUR_DEFAUT,
            "reading_time": "",
            "excerpt": _chapo(_texte(desc_html) or corps),
            "content": corps,
            "url": _url_propre(lien),
            "image_url": _image(corps_html) or _image(desc_html),
        })
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID", "").strip()
    if not sheet_id and not APERCU:
        print("SHEET_ID env var is not set.", file=sys.stderr)
        return 2

    xml_text = charger_flux()
    if not xml_text:
        print("⛔ flux ECOMI injoignable — on ne touche à RIEN. "
              "Rien n'est perdu : tout le flux sera reversé au prochain passage.",
              file=sys.stderr, flush=True)
        return 1

    toutes = lignes(xml_text)
    if not toutes:
        print("⛔ flux ECOMI lu mais vide ou illisible — on ne touche à rien.",
              file=sys.stderr, flush=True)
        return 1
    print(f"🪙 flux ECOMI : {len(toutes)} article(s) lus.", flush=True)

    if APERCU:
        print("--- APERÇU (rien ne sera écrit) ---", flush=True)
        for l in toutes:
            print(f"  {l['date']}  {l['slug']:26s}  [{l['tags']}]  {l['title']}",
                  flush=True)
        return 0

    _sh, ws = blog._open(sheet_id)
    deja = set(blog._read_existing(ws))
    manquants = [l for l in toutes if l["slug"] not in deja]
    if not manquants:
        print(f"📝C-BLOG déjà à jour ({len(toutes)} article(s) du flux, "
              f"0 manquant) — aucune écriture.", flush=True)
        _log(sheet_id, "OK", {"lus": len(toutes), "verses": 0,
                              "duree": f"{time.time() - t0:.0f}s"})
        return 0

    res = blog.sync_blog(manquants, sheet_id)
    statut = str(res.get("status", res))
    print(f"📝C-BLOG : {len(manquants)} ligne(s) versée(s) -> {statut}",
          flush=True)
    # ⭐ LE JOURNAL TIENT LIEU DE FILTRE : on ne bloque aucun sujet, mais on
    # ÉCRIT le tag de chaque ligne versée. C'est là qu'on verra ECOMI dériver
    # du token — et on décidera alors avec des faits, pas par précaution.
    for l in manquants:
        print(f"    + {l['slug']}  [{l['tags']}]  {l['title']}", flush=True)

    ok = not statut.startswith("FAILED")
    _log(sheet_id, "OK" if ok else "ECHEC",
         {"lus": len(toutes), "verses": len(manquants), "statut": statut,
          "duree": f"{time.time() - t0:.0f}s"})
    return 0 if ok else 1


def _log(sheet_id: str, statut: str, resume: Dict[str, Any]) -> None:
    try:
        from scraper.sheets import append_log
        append_log(sheet_id, "ecomi_run", statut,
                   "; ".join(f"{k}={v}" for k, v in resume.items()))
    except Exception:                                       # noqa: BLE001
        pass


if __name__ == "__main__":
    sys.exit(run())

# FIN ecomi_run.py — un collecteur, une porte d'écriture, zéro Discord.
# C'est `discord_blog.py` qui annonce, comme pour les articles du blog VeVe.
