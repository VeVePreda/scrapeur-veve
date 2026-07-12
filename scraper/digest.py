"""📰 DIGEST DISCORD DU MATIN — le resume quotidien + les nouveaux articles.

Demande de Preda (12/07) : « les stats chaque matin c'est bien aussi, ainsi que
quand il y a un nouvel article qui sort ».

Tourne sur PREDA (il a le Sheet). Lit ce qui est deja calcule — il ne collecte
RIEN de nouveau, aucune requete vers VeVe/StackR :

  * ChainActivity / ChainItems  -> activite de la veille (jour PT termine) ;
  * _VeveRevenue               -> revenue drop REEL + marche (VeVe gems +
                                  StackR) ;
  * 🔥H-BURNS                   -> OMI brules ;
  * _ListingDaily              -> mises en vente ;
  * 📝C-BLOG                    -> articles parus depuis le dernier digest ;
  * _MarketUniverse            -> sante du marche (elements qui se vendent).

Etat : data/digest_state.json (dernier jour poste + derniers slugs de blog) ->
aucun doublon si le workflow tourne deux fois.

Env : SHEET_ID, DISCORD_WEBHOOK (sans lui : simulation dans les logs),
      DIGEST_STATE (data/digest_state.json).
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
BLOG_MAX = int(os.environ.get("DIGEST_BLOG_MAX", "5"))
COULEUR = 0x9B59B6          # violet, comme les bannieres du Sheet


def _n(x) -> int:
    try:
        return int(float(str(x).replace(",", ".").replace(" ", "") or 0))
    except (TypeError, ValueError):
        return 0


def _f(x) -> float:
    try:
        return float(str(x).replace(",", ".").replace(" ", "") or 0)
    except (TypeError, ValueError):
        return 0.0


def _records(sh, tab) -> List[Dict[str, Any]]:
    try:
        ws = sh.worksheet(tab)
    except Exception:
        return []
    try:
        from gspread.utils import ValueRenderOption
        return ws.get_all_records(
            value_render_option=ValueRenderOption.unformatted)
    except Exception:
        try:
            return ws.get_all_records()
        except Exception:
            return []


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


def dernier_jour(sh) -> str:
    """Le dernier jour PACIFIQUE complet present dans ChainActivity."""
    jours = {str(r.get("date", "")).strip()
             for r in _records(sh, "ChainActivity")}
    jours.discard("")
    return max(jours) if jours else ""


def build_digest(sh, jour: str) -> Dict:
    """Rassemble les chiffres du jour (aucune collecte : tout est deja la)."""
    act = [r for r in _records(sh, "ChainActivity")
           if str(r.get("date", "")).strip() == jour]
    mints = sum(_n(r.get("mint_collectible")) + _n(r.get("mint_comic"))
                for r in act)
    market = sum(_n(r.get("market_in_collectible")) + _n(r.get("market_in_comic"))
                 for r in act)
    burns = sum(_n(r.get("burn_collectible")) + _n(r.get("burn_comic"))
                for r in act)
    actifs = len({str(r.get("account", "")).strip().lower() for r in act
                  if str(r.get("account", "")).strip()})

    rev = {r.get("date"): r for r in _records(sh, "_VeveRevenue")}.get(jour, {})
    drop = _f(rev.get("drop_usd"))
    mkt = _f(rev.get("market_veve_usd")) + _f(rev.get("market_stackr_usd"))

    burn = {r.get("date"): r for r in _records(sh, "🔥H-BURNS")}.get(jour, {})
    omi = _f(burn.get("omi_burned")) + _f(burn.get("omi_gem"))

    lst = {r.get("date"): r for r in _records(sh, "_ListingDaily")}.get(jour, {})

    univ = sorted(_records(sh, "_MarketUniverse"),
                  key=lambda r: str(r.get("date", "")))
    u = univ[-1] if univ else {}
    return {"jour": jour, "mints": mints, "market": market, "burns": burns,
            "actifs": actifs, "drop": drop, "mkt": mkt, "omi": omi,
            "listings": _n(lst.get("listings")),
            "listeurs": _n(lst.get("listers")),
            "elements": _n(u.get("elements")),
            "vendus": _n(u.get("vendus_7j")),
            "pct_vendus": u.get("pct_vendus_7j", "")}


def nouveaux_articles(sh, connus: List[str]) -> List[Dict]:
    """Les articles du blog jamais annonces (📝C-BLOG, ecrit par blog.py)."""
    vus = set(connus or [])
    out = []
    for r in _records(sh, "📝C-BLOG"):
        slug = str(r.get("slug", "")).strip()
        if slug and slug not in vus:
            out.append({"slug": slug,
                        "titre": str(r.get("title") or slug),
                        "date": str(r.get("published_at")
                                    or r.get("date") or ""),
                        "url": str(r.get("url") or "")})
    out.sort(key=lambda a: a["date"], reverse=True)
    return out


def embeds(d: Dict, articles: List[Dict]) -> List[Dict]:
    def money(x):
        return f"{x:,.0f} $".replace(",", " ")

    fields = [
        {"name": "Revenue drop (réel)", "value": money(d["drop"]),
         "inline": True},
        {"name": "Marché (VeVe + StackR)", "value": money(d["mkt"]),
         "inline": True},
        {"name": "Total", "value": "**" + money(d["drop"] + d["mkt"]) + "**",
         "inline": True},
        {"name": "Mints", "value": f"{d['mints']:,}".replace(",", " "),
         "inline": True},
        {"name": "Ventes on-chain",
         "value": f"{d['market']:,}".replace(",", " "), "inline": True},
        {"name": "Actifs uniques",
         "value": f"{d['actifs']:,}".replace(",", " "), "inline": True},
        {"name": "Mises en vente",
         "value": f"{d['listings']:,} par {d['listeurs']:,} comptes"
                  .replace(",", " "), "inline": True},
        {"name": "OMI brûlés",
         "value": f"{d['omi']:,.0f}".replace(",", " "), "inline": True},
    ]
    if d.get("elements"):
        v = (f"{d['vendus']:,} / {d['elements']:,}".replace(",", " ")
             + (f" ({d['pct_vendus']} %)" if d.get("pct_vendus") else ""))
        fields.append({"name": "Éléments qui se vendent (7 j)", "value": v,
                       "inline": True})
    out = [{"title": f"📊 VeVe — journée du {d['jour']}", "color": COULEUR,
            "fields": fields,
            "footer": {"text": "Jour pacifique terminé · revenue = prix "
                               "réellement payés (flux VeVe public)"}}]
    for a in articles[:BLOG_MAX]:
        e = {"title": f"📝 {a['titre']}"[:250], "color": 0x3498DB,
             "description": a["date"]}
        if a["url"]:
            e["url"] = a["url"]
        out.append(e)
    return out


def post(embs: List[Dict], n_art: int) -> bool:
    contenu = "☀️ **Le point du matin**"
    if n_art:
        contenu += f" · {n_art} nouvel(s) article(s)"
    if not WEBHOOK:
        print("[SIMULATION — pas de DISCORD_WEBHOOK]", flush=True)
        print(json.dumps(embs, ensure_ascii=False, indent=1)[:2000], flush=True)
        return True
    try:
        r = requests.post(WEBHOOK, json={"content": contenu,
                                         "embeds": embs[:10]}, timeout=20)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"Discord KO : {e}", file=sys.stderr)
        return False


def main() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID", "").strip()
    if not sheet_id:
        print("SHEET_ID env var is not set.", file=sys.stderr)
        return 2
    sh = _client().open_by_key(sheet_id)
    state = load_state()
    jour = dernier_jour(sh)
    if not jour:
        print("ChainActivity vide — rien a dire.", file=sys.stderr)
        return 1
    arts = nouveaux_articles(sh, state.get("slugs", []))
    if jour == state.get("jour") and not arts:
        print(f"Deja poste pour le {jour} et aucun nouvel article — "
              f"on ne repete pas.", flush=True)
        return 0
    d = build_digest(sh, jour)
    if post(embeds(d, arts), len(arts)):
        state["jour"] = jour
        state["slugs"] = (state.get("slugs", []) +
                          [a["slug"] for a in arts])[-500:]
        save_state(state)
    resume = {"jour": jour, "articles": len(arts), "total_usd":
              round(d["drop"] + d["mkt"]), "actifs": d["actifs"],
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

# FIN digest.py v1
