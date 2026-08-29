# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve  ·  CHEMIN : scraper/ventes_veve.py
"""LOT 210-A3 — LES VENTES DU MARCHE VeVe, UNE PAR LIGNE.

Demande de Preda (29/08) : « il faut aussi les ventes veve des qu'on peut ».

⭐⭐ CE QUI MANQUAIT N'ETAIT PAS LA SOURCE, C'ETAIT LA CONSERVATION.
`scraper/veve_tx.py` lit deja ce flux chaque nuit (`veve-tx.yml`, 01:50 UTC) —
mais il n'en garde qu'un AGREGAT QUOTIDIEN de revenue (`veve_tx_daily.csv`).
Les ventes unitaires passent et sont jetees. Ce module les garde, dans la meme
forme que `data/stackr_sales.csv`, pour que `ventes_agregat.py` fusionne les
deux marches sans les distinguer autrement que par une colonne.
⛔ NE PAS le fondre dans `veve_tx.py` : 753 lignes qui alimentent un onglet
Sheet et le revenue de drop. Un fichier de plus coute moins cher qu'un patch
dans un module qui a trois consommateurs.

Source (mesuree le 29/08, PUBLIQUE, sans cookie) :
  GET stackr.world/api/trpc/publicVeve.getVeveTransactions
      ?input={"json":{"limit":<N>,"cursor":<page>}}
  -> une LISTE NUE (pas {items}), triee `created_at` DECROISSANT.

🔴🔴 LES CONVENTIONS SONT L'INVERSE DE `getAllLatestSales_v2` — trois pieges
mesures le meme jour, et chacun rend 200 :
  · `limit`  est un NOMBRE ici, une CHAINE la-bas ;
  · `cursor` est un NUMERO DE PAGE 1-BASE ici (`cursor:0` -> ERREUR),
    un DECALAGE 0-base la-bas ;
  · `page`, `offset`, `skip` sont IGNORES EN SILENCE : meme reponse, meme
    premiere page, aucun message. ⇒ le garde-fou de progression plus bas
    n'est pas une precaution, c'est le SEUL moyen de savoir qu'on avance.

PERIMETRE : `veve_type == MARKET_FIXED` — le marche VeVe (gems). Les autres
types sont ecartes, et chacun pour une raison differente :
  · MARKET_STACKR : deja collecte, en OMI, par `stackr_sales.py`. ⛔ Et son
    `price` ici N'EST PAS convertible : mesure du 29/08 sur 273 ventes
    appariees (meme piece, meme edition, < 2 min d'ecart), le rapport $/OMI va
    de 0,000239 (p10) a 0,000999 (p90) — dispersion x4,2, 8 % seulement au
    cours reel. Ce champ ne dit pas ce qu'on croyait.
  · STORE_GEM / CART_FIAT : achats en BOUTIQUE, pas des ventes entre
    collectionneurs. Les melanger gonflerait le marche secondaire du primaire.
  · NFT_TRANSFER : la jambe de reglement d'un trade (meme nft, meme prix,
    quelques secondes apres) -> DOUBLE COMPTAGE.
  · ADMIN_COLLECTIBLE_TRANSFER / CRAFT / MARKET_AUCTION : ni vente, ni marche.

⭐ LE PRIX EST EN GEMS, ET 1 GEM ~ 1 $. C'est la seule raison pour laquelle on
peut ecrire `price_usd` sans conversion. ⛔ Ne JAMAIS appliquer ce raisonnement
aux ventes StackR (voir plus haut) : la mesure dit le contraire.

Sortie :
  data/veve_ventes.csv  1 ligne/vente, APPEND-ONLY, dedup par `veve_id`

Env : VEVE_VENTES_CSV · VEVE_VENTES_JOURS (3) · VEVE_VENTES_LIMIT (250)
      VEVE_VENTES_MAX_PAGES (200) · VEVE_VENTES_PAUSE (0.4)
      VEVE_VENTES_BACKFILL (false, remonte jusqu'a VEVE_VENTES_JOURS quoi qu'il arrive)
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
import os
import sys
import urllib.parse
from typing import Dict, List, Set

import requests

URL = "https://www.stackr.world/api/trpc/publicVeve.getVeveTransactions"
CSV = os.environ.get("VEVE_VENTES_CSV", "data/veve_ventes.csv")
JOURS = int(os.environ.get("VEVE_VENTES_JOURS", "3"))
LIMIT = int(os.environ.get("VEVE_VENTES_LIMIT", "250"))
MAX_PAGES = int(os.environ.get("VEVE_VENTES_MAX_PAGES", "200"))
PAUSE = float(os.environ.get("VEVE_VENTES_PAUSE", "0.4"))

# ⚠️ UN User-Agent DE NAVIGATEUR, ET CE N'EST PAS DU FOLKLORE : le WAF rend 403
# sur l'UA par defaut de `requests` (meme piege que GoChain, paye deux fois).
ENTETES = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/127.0 Safari/537.36"),
    "Referer": "https://www.stackr.world/",
    "Accept": "*/*",
}

TYPE_GARDE = "MARKET_FIXED"
ENTETE = ["veve_id", "ts_utc", "date_pt", "element_id", "element_type", "edition",
          "name", "rarity", "price_usd", "seller", "buyer",
          "seller_username", "buyer_username"]

# Le fuseau des journees VeVe, comme partout ailleurs dans ce depot.
try:
    from zoneinfo import ZoneInfo
    PT = ZoneInfo("America/Los_Angeles")
except Exception:                                    # pragma: no cover
    PT = None


def _page(n: int) -> List[Dict]:
    """Une page. ⚠️ `cursor` est 1-BASE : `n=1` est la plus recente."""
    inp = json.dumps({"json": {"limit": LIMIT, "cursor": n}}, separators=(",", ":"))
    r = requests.get(URL, params={"input": inp}, headers=ENTETES, timeout=60)
    r.raise_for_status()
    d = r.json()
    if "error" in d:
        raise RuntimeError("tRPC: %s" % str(d["error"])[:200])
    j = d["result"]["data"]["json"]
    # ⚠️ RACINE = LISTE NUE. `getAllLatestSales_v2` rend `{items, totalCount}` ;
    # ici c'est une liste. Ecrire `j["items"]` leverait une TypeError peu
    # parlante — on verifie, et on le DIT.
    if not isinstance(j, list):
        raise RuntimeError("racine inattendue : %s" % type(j).__name__)
    return j


def _lire_connus() -> Set[str]:
    if not os.path.exists(CSV):
        return set()
    with open(CSV, newline="", encoding="utf-8") as f:
        return {r["veve_id"] for r in csv.DictReader(f) if r.get("veve_id")}


def _jour_pt(ts: str) -> str:
    t = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (t.astimezone(PT) if PT else t).date().isoformat()


def main() -> int:
    connus = _lire_connus()
    print("[ventes-veve] %d ventes deja connues." % len(connus), flush=True)

    limite = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=JOURS)
    neuves: List[List[str]] = []
    vus: Set[str] = set()
    precedent = None
    pages = 0

    for n in range(1, MAX_PAGES + 1):
        try:
            lot = _page(n)
        except Exception as e:
            # ⚠️ ON S'ARRETE, ON NE REESSAIE PAS EN BOUCLE. StackR etrangle
            # quand on pousse (mesure : limit=500 tient ~5 appels, puis 500 et
            # timeout 30 s sur TOUT pendant une minute). Une boucle de reprise
            # transformerait un ralentissement en panne, et un run de 30 min en
            # run de 6 h. Ce qui est deja recolte est ecrit -> le lendemain
            # rattrape, puisque le fichier est append-only et dedupe.
            print("[ventes-veve] page %d en echec (%s) — on s'arrete la." % (n, e),
                  file=sys.stderr)
            break
        pages += 1
        if not lot:
            print("[ventes-veve] page %d vide — fin du flux." % n, flush=True)
            break

        recent = max(x.get("created_at") or "" for x in lot)
        # 🔴🔴 LE GARDE-FOU DE PROGRESSION, ET IL EST INDISPENSABLE ICI.
        # Un nom de parametre inconnu ne rougit PAS sur cette API : elle rend
        # 200 et la meme premiere page, indefiniment. Sans ce test, le jour ou
        # `cursor` est renomme, ce module tourne 200 fois, ecrit 250 doublons
        # dedupes en 0 ligne neuve, et sort VERT.
        if precedent is not None and recent >= precedent:
            print("[ventes-veve] page %d ne recule pas (%s >= %s) — PAGINATION "
                  "CASSEE, on s'arrete." % (n, recent[:19], precedent[:19]),
                  file=sys.stderr)
            break
        precedent = recent

        fini = False
        for x in lot:
            ts = x.get("created_at") or ""
            try:
                quand = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                continue
            if quand < limite:
                fini = True
                continue
            if x.get("veve_type") != TYPE_GARDE:
                continue
            vid = str(x.get("veve_id") or "")
            if not vid or vid in connus or vid in vus:
                continue
            prix = x.get("price")
            # ⚠️ Un prix absent est SAUTE, jamais mis a 0 : « vendu pour rien »
            # est une information fausse, pas une information manquante.
            try:
                prix = float(prix)
            except (TypeError, ValueError):
                continue
            if prix <= 0:
                continue
            vus.add(vid)
            neuves.append([
                vid, quand.strftime("%Y-%m-%d %H:%M:%S"), _jour_pt(ts),
                x.get("element_id") or "", x.get("element_type") or "",
                x.get("nft_issue") or "", x.get("name") or "", x.get("rarity") or "",
                "%.2f" % prix,
                x.get("seller_address") or "", x.get("buyer_address") or "",
                x.get("seller_username") or "", x.get("buyer_username") or "",
            ])
        if fini:
            print("[ventes-veve] fenetre de %d j atteinte a la page %d." % (JOURS, n),
                  flush=True)
            break
        import time
        time.sleep(PAUSE)

    if not neuves:
        print("[ventes-veve] %d pages lues, aucune vente neuve." % pages, flush=True)
        return 0

    neuf = not os.path.exists(CSV)
    os.makedirs(os.path.dirname(CSV) or ".", exist_ok=True)
    # ⭐ APPEND-ONLY, comme `stackr_sales.csv`. Une vente passee ne change
    # jamais : la reecrire entierement chaque jour, c'est risquer de perdre
    # l'historique sur une source qui a un mauvais jour.
    with open(CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        if neuf:
            w.writerow(ENTETE)
        w.writerows(neuves)

    print("[ventes-veve] %d pages, %d ventes VeVe neuves ecrites (total %d)."
          % (pages, len(neuves), len(connus) + len(neuves)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
