"""📰 DIGEST DISCORD — le point du matin (et celui de la semaine, le vendredi).

Demandes de Preda (12/07, apres le 1er run) :
  * titre avec le NOM du jour : « VeVe — Samedi 11/07/2026 » ;
  * une illustration rectangulaire dans la carte ;
  * les chiffres groupes par LIGNE : TRANSACTION (Global/Mint/Market),
    ACTIF (Unique/Nouveaux/Anciens), REVENUE (Total/Drop/Market) ;
  * dire si c'etait un JOUR DE DROP ;
  * un avertissement : infos indicatives, pas un conseil financier, valeurs
    possiblement inexactes ;
  * le VENDREDI : pas de point du matin, mais LE POINT DE LA SEMAINE ;
  * un garde-fou anti-spam (ne pas se faire bannir par Discord).

BUG DU 1er RUN CORRIGE : « articles: 1001 » — sans etat, TOUT le blog etait
considere comme nouveau. Desormais le premier run MEMORISE sans annoncer.

Le module ne collecte RIEN : il lit la page 📊 STATS deja calculee (memes
chiffres que le Sheet, donc aucune divergence possible) + les onglets sources.

Env : SHEET_ID, DISCORD_WEBHOOK, DIGEST_STATE (data/digest_state.json),
      DIGEST_WEEKLY_DAY (4 = vendredi ; 0 = lundi), DIGEST_IMAGE (illustration
      par defaut), DIGEST_BLOG_MAX (3).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import time
from typing import Any, Dict, List

import requests

from scraper.sheets import _client, append_log

WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "").strip()
STATE_PATH = os.environ.get("DIGEST_STATE", "data/digest_state.json")
BLOG_MAX = int(os.environ.get("DIGEST_BLOG_MAX", "3"))
# Au-dela de ce nombre d'articles « nouveaux », c'est que l'etat est desynchro
# (bug du 12/07 : « articles: 1001 » puis « articles: 501 » — on ne gardait que
# les 500 derniers slugs, donc les autres repassaient pour neufs a chaque run).
# Dans ce cas on MEMORISE TOUT sans rien annoncer : un blog ne publie pas
# 500 articles dans la nuit.
MAX_NEUFS = int(os.environ.get("DIGEST_MAX_NEUFS", "10"))
# LA DATE DE PARUTION FAIT FOI (remarque de Preda, et il a raison) : un article
# est « nouveau » s'il est PARU dans les DIGEST_ARTICLE_JOURS derniers jours.
# L'etat des slugs ne sert plus qu'a ne pas le repeter deux fois — il n'est
# plus la source de verite, ce qui rend le module auto-guerissant : meme avec
# un etat perdu ou corrompu, on ne peut plus deterrer 500 vieux articles.
ARTICLE_JOURS = int(os.environ.get("DIGEST_ARTICLE_JOURS", "3"))
WEEKLY_DAY = int(os.environ.get("DIGEST_WEEKLY_DAY", "4"))     # vendredi
IMAGE = os.environ.get("DIGEST_IMAGE", "").strip()
STATS_TAB = os.environ.get("STATS_TAB", "📊 STATS")

VIOLET = 0x7B2CBF
BLEU = 0x3498DB
OR = 0xF1C40F

JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi",
         "Dimanche"]

AVERTISSEMENT = ("⚠️ Informations fournies à titre indicatif — ce n'est PAS un "
                 "conseil financier. Les chiffres sont issus de sources "
                 "publiques et peuvent comporter des erreurs ou être "
                 "incomplets.")

# Colonnes du tableau quotidien de 📊 STATS (ligne d'en-tetes = 9, donnees des
# la 10). On lit la page telle qu'elle est affichee : aucun risque de dire
# autre chose que le Sheet.
COLS = ["Date", "Drop", "Global", "Mint", "Airdrop", "Market", "Burn",
        "Unique", "Nouveaux", "Anciens", "Quantité", "Comptes",
        "Total", "Drop$", "Market$", "OMI$", "OMI→NFT", "OMI→GEM"]


def _n(x) -> int:
    try:
        return int(float(str(x).replace(",", ".").replace(" ", "")
                         .replace("$", "").replace("~", "") or 0))
    except (TypeError, ValueError):
        return 0


def _fr(x) -> str:
    return f"{_n(x):,}".replace(",", " ")


def _records(sh, tab) -> List[Dict[str, Any]]:
    try:
        ws = sh.worksheet(tab)
        from gspread.utils import ValueRenderOption
        return ws.get_all_records(
            value_render_option=ValueRenderOption.unformatted)
    except Exception:
        return []


def lire_stats(sh) -> List[Dict[str, Any]]:
    """Le tableau quotidien de 📊 STATS, tel qu'affiche (A10:R60)."""
    try:
        ws = sh.worksheet(STATS_TAB)
        from gspread.utils import ValueRenderOption
        vals = ws.get_values("A10:R60",
                             value_render_option=ValueRenderOption.unformatted)
    except Exception as e:
        print(f"lecture 📊 STATS impossible : {e}", file=sys.stderr)
        return []
    out = []
    for r in vals or []:
        if r and str(r[0]).strip():
            d = dict(zip(COLS, list(r) + [""] * (len(COLS) - len(r))))
            out.append(d)
    return out


# ---------------------------------------------------------------------------
# Cartes
# ---------------------------------------------------------------------------

def _ligne(titre: str, cases: List[tuple]) -> List[Dict]:
    """Une LIGNE de la carte : un intitule, puis des cases cote a cote
    (Discord met 3 champs `inline` par ligne)."""
    champs = [{"name": f"__{titre}__", "value": "\\u200b", "inline": False}]
    for nom, val in cases:
        champs.append({"name": nom, "value": f"**{val}**", "inline": True})
    return champs


def carte_jour(d: Dict, drop: Dict) -> Dict:
    jour = str(d.get("Date", ""))
    try:
        dt = _dt.date.fromisoformat(jour)
        titre = f"VeVe — {JOURS[dt.weekday()]} {dt.strftime('%d/%m/%Y')}"
    except ValueError:
        titre = f"VeVe — {jour}"

    fields: List[Dict] = []
    if drop.get("nom"):
        fields.append({"name": "🎉 Jour de drop",
                       "value": f"**{drop['nom']}**", "inline": False})
    fields += _ligne("TRANSACTION", [
        ("Transactions", _fr(d.get("Global"))),
        ("Mint", _fr(d.get("Mint"))),
        ("Market", _fr(d.get("Market"))),
    ])
    fields += _ligne("ACTIF", [
        ("Actifs", _fr(d.get("Unique"))),
        ("Nouveaux", _fr(d.get("Nouveaux"))),
        ("Anciens", _fr(d.get("Anciens"))),
    ])
    fields += _ligne("REVENUE", [
        ("Revenue", _fr(d.get("Total")) + " $"),
        ("Drop", _fr(d.get("Drop$")) + " $"),
        ("Market", _fr(d.get("Market$")) + " $"),
    ])
    e = {"title": titre, "color": VIOLET, "fields": fields,
         "footer": {"text": AVERTISSEMENT}}
    img = drop.get("image") or IMAGE
    if img:
        e["image"] = {"url": img}          # illustration RECTANGULAIRE
    return e


def carte_semaine(rows: List[Dict], drops: int) -> Dict:
    """Le point de la semaine (7 derniers jours du tableau)."""
    sept = rows[:7]
    if not sept:
        return {}
    som = lambda c: sum(_n(r.get(c)) for r in sept)   # noqa: E731
    debut = str(sept[-1].get("Date", ""))
    fin = str(sept[0].get("Date", ""))
    fields = _ligne("TRANSACTION", [
        ("Transactions", _fr(som("Global"))),
        ("Mint", _fr(som("Mint"))),
        ("Market", _fr(som("Market"))),
    ])
    fields += _ligne("ACTIF (cumul des jours)", [
        ("Actifs", _fr(som("Unique"))),
        ("Nouveaux", _fr(som("Nouveaux"))),
        ("Anciens", _fr(som("Anciens"))),
    ])
    fields += _ligne("REVENUE", [
        ("Revenue", _fr(som("Total")) + " $"),
        ("Drop", _fr(som("Drop$")) + " $"),
        ("Market", _fr(som("Market$")) + " $"),
    ])
    fields.append({"name": "Autres", "inline": False,
                   "value": f"🔥 **{_fr(som('Burn'))}** burns · "
                            f"🎉 **{drops}** jour(s) de drop · "
                            f"📦 **{_fr(som('Quantité'))}** mises en vente"})
    e = {"title": f"📅 Le point de la semaine — du {debut} au {fin}",
         "color": OR, "fields": fields,
         "footer": {"text": AVERTISSEMENT}}
    if IMAGE:
        e["image"] = {"url": IMAGE}
    return e


EXCERPT_MAX = int(os.environ.get("DIGEST_EXCERPT", "300"))


def cartes_blog(articles: List[Dict]) -> List[Dict]:
    """Une carte par article : illustration + DEBUT DU TEXTE (demande Preda).
    📝C-BLOG porte deja `excerpt` et `image_url` (ecrits par blog.py)."""
    out = []
    for a in articles[:BLOG_MAX]:
        texte = str(a.get("excerpt") or "").strip()
        if len(texte) > EXCERPT_MAX:
            texte = texte[:EXCERPT_MAX].rsplit(" ", 1)[0] + "…"
        desc = texte
        if a.get("date"):
            desc = (desc + "\n\n" if desc else "") + f"*{a['date']}*"
        e = {"title": f"📝 {a['titre']}"[:250], "color": BLEU,
             "description": desc[:1000] or "Nouvel article"}
        if a.get("url"):
            e["url"] = a["url"]
        if a.get("image"):
            e["image"] = {"url": a["image"]}     # illustration rectangulaire
        out.append(e)
    return out


# ---------------------------------------------------------------------------
# Sources annexes
# ---------------------------------------------------------------------------

def drop_du_jour(sh, jour: str, stats_row: Dict) -> Dict:
    """Y a-t-il eu un drop ce jour-la ? (colonne Drop de 📊 STATS) + une image
    prise dans le catalogue pour illustrer la carte."""
    nom = str(stats_row.get("Drop") or "").strip()
    if not nom:
        return {}
    img = ""
    for tab in ("🔵C-COLLECTIBLE", "🟢C-COMICS"):
        try:
            ws = sh.worksheet(tab)
            head = ws.row_values(1)
            if "image_url" not in head or "releaseDate" not in head:
                continue
            i_img = head.index("image_url") + 1
            i_rel = head.index("releaseDate") + 1
            col_rel = ws.col_values(i_rel)
            col_img = ws.col_values(i_img)
            for k, v in enumerate(col_rel):
                if str(v)[:10] == jour and k < len(col_img) and col_img[k]:
                    img = col_img[k]
                    break
        except Exception:
            continue
        if img:
            break
    return {"nom": nom, "image": img}


def _jour(x) -> str:
    """La date de parution, quel que soit le format du Sheet (ISO, serial)."""
    sx = str(x or "").strip()
    if not sx:
        return ""
    if sx.replace(".", "", 1).isdigit() and len(sx) < 8:     # serial Sheets
        try:
            d = (_dt.date(1899, 12, 30)
                 + _dt.timedelta(days=int(float(sx))))
            return d.isoformat()
        except (ValueError, OverflowError):
            return ""
    return sx[:10]


def nouveaux_articles(sh, connus: List[str], jours: int = None) -> List[Dict]:
    """Les articles PARUS RECEMMENT et pas encore annonces.

    Le filtre principal est la DATE DE PARUTION (colonne du Sheet) ; les slugs
    ne servent qu'a eviter de repeter. Sans date exploitable, on retombe sur
    les slugs (comportement d'avant)."""
    jours = ARTICLE_JOURS if jours is None else jours
    limite = (_dt.date.today() - _dt.timedelta(days=jours)).isoformat()
    vus = set(connus or [])
    out = []
    for r in _records(sh, "📝C-BLOG"):
        slug = str(r.get("slug", "")).strip()
        paru = _jour(r.get("published_at") or r.get("date"))
        if paru and paru < limite:
            continue                      # trop vieux : ce n'est pas une news
        if slug and slug not in vus:
            out.append({"slug": slug,
                        "titre": str(r.get("title") or slug),
                        "date": paru or str(r.get("published_at") or ""),
                        "url": str(r.get("url") or ""),
                        "excerpt": str(r.get("excerpt") or ""),
                        "image": str(r.get("image_url") or "")})
    out.sort(key=lambda a: a["date"], reverse=True)
    return out


def tous_les_slugs(sh) -> List[str]:
    return [str(r.get("slug", "")).strip()
            for r in _records(sh, "📝C-BLOG") if str(r.get("slug", "")).strip()]


# ---------------------------------------------------------------------------
# Discord (avec garde-fou anti-bannissement)
# ---------------------------------------------------------------------------

def post(contenu: str, embeds: List[Dict]) -> bool:
    """UN SEUL message par run, 10 cartes maximum (limite Discord), et on
    RESPECTE le 429 (rate limit) au lieu de s'obstiner — c'est ce qui fait
    bannir un webhook."""
    embeds = [e for e in embeds if e][:10]
    if not embeds:
        return False
    if not WEBHOOK:
        print("[SIMULATION — pas de DISCORD_WEBHOOK]", flush=True)
        print(json.dumps({"content": contenu, "embeds": embeds},
                         ensure_ascii=False, indent=1)[:2500], flush=True)
        return True
    for essai in range(3):
        try:
            r = requests.post(WEBHOOK,
                              json={"content": contenu, "embeds": embeds},
                              timeout=20)
            if r.status_code == 429:
                attente = 5.0
                try:
                    attente = float(r.json().get("retry_after", 5)) + 1
                except Exception:
                    pass
                print(f"Discord : rate limit — on patiente {attente:.0f} s "
                      f"(on ne s'obstine pas, c'est ce qui fait bannir).",
                      flush=True)
                time.sleep(min(attente, 60))
                continue
            r.raise_for_status()
            return True
        except Exception as e:
            print(f"Discord KO ({e})", file=sys.stderr)
            if essai == 2:
                return False
            time.sleep(5)
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_state() -> Dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st: Dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH) or ".", exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st, f)


def main() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID", "").strip()
    if not sheet_id:
        print("SHEET_ID env var is not set.", file=sys.stderr)
        return 2
    sh = _client().open_by_key(sheet_id)
    state = load_state()
    premier = "slugs" not in state

    rows = lire_stats(sh)
    if not rows:
        print("Page 📊 STATS vide — rien a dire.", file=sys.stderr)
        return 1
    jour = str(rows[0].get("Date", ""))

    # 1er RUN (ou etat desynchronise) : on MEMORISE sans rien annoncer.
    arts: List[Dict] = [] if premier else nouveaux_articles(
        sh, state.get("slugs", []))
    if premier or len(arts) > MAX_NEUFS:
        n = len(arts)
        state["slugs"] = tous_les_slugs(sh)
        arts = []
        motif = "1er run" if premier else f"{n} articles « nouveaux »"
        print(f"{motif} -> etat (re)synchronise : {len(state['slugs'])} slugs "
              f"memorises SANS etre annonces (un blog ne publie pas 500 "
              f"articles dans la nuit).", flush=True)

    hebdo = _dt.date.today().weekday() == WEEKLY_DAY
    deja = (state.get("jour") == jour and
            state.get("hebdo_le") == _dt.date.today().isoformat())
    if hebdo:
        if state.get("hebdo_le") == _dt.date.today().isoformat() and not arts:
            print("Point de la semaine deja poste aujourd'hui.", flush=True)
            return 0
        drops = sum(1 for r in rows[:7] if str(r.get("Drop") or "").strip())
        embeds = [carte_semaine(rows, drops)] + cartes_blog(arts)
        contenu = "📅 **Le point de la semaine**"
        if arts:
            contenu += f" · {len(arts)} nouvel(s) article(s)"
        ok = post(contenu, embeds)
        if ok:
            state["hebdo_le"] = _dt.date.today().isoformat()
    else:
        if state.get("jour") == jour and not arts:
            print(f"Deja poste pour le {jour} et aucun nouvel article.",
                  flush=True)
            return 0
        drop = drop_du_jour(sh, jour, rows[0])
        embeds = [carte_jour(rows[0], drop)] + cartes_blog(arts)
        contenu = "☀️ **Le point du matin**"
        if arts:
            contenu += f" · {len(arts)} nouvel(s) article(s)"
        ok = post(contenu, embeds)
        if ok:
            state["jour"] = jour

    if arts:
        # on garde TOUS les slugs (le fichier reste minuscule) — les tronquer
        # est precisement ce qui a desynchronise l'etat.
        state["slugs"] = list(dict.fromkeys(
            list(state.get("slugs", [])) + [a["slug"] for a in arts]))
    save_state(state)
    resume = {"jour": jour, "hebdo": hebdo, "articles": len(arts),
              "duration": f"{time.time() - t0:.0f}s"}
    try:
        append_log(sheet_id, "digest", "OK",
                   "; ".join(f"{k}={v}" for k, v in resume.items()))
    except Exception:
        pass
    print(f"Digest : {resume}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# FIN digest.py v5 (la DATE DE PARUTION fait foi)
