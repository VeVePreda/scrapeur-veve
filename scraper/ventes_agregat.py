# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve  ·  CHEMIN : scraper/ventes_agregat.py
"""LOT 210-A1/A3 — L'AGREGAT DES VENTES QUE LA FICHE PUBLIERA (DEUX MARCHES).

⭐⭐⭐ CE MODULE NE COLLECTE RIEN, ET C'EST LE COEUR DE SON EXISTENCE.
  · `scraper/stackr_sales.py` collecte le marche StackR depuis le 11/07
    -> `data/stackr_sales.csv` (12 759 ventes, 2 869 pieces au 29/08), OMI.
  · `scraper/ventes_veve.py`  collecte le marche VeVe (lot A3)
    -> `data/veve_ventes.csv` (607 ventes/jour, 416 pieces/jour), DOLLARS.
⛔ NE PAS ECRIRE UN TROISIEME COLLECTEUR : le 28/08 j'ai sonde l'API une heure
avant de decouvrir que le premier existait et tournait chaque nuit.

CE QUE CE MODULE FAIT :
  les deux CSV  ->  data/ventes_stackr.csv
  (les N dernieres ventes de CHAQUE piece, TOUS MARCHES CONFONDUS, en dollars)

═══════════════════════════════════════════════════════════════════════════
🔴🔴🔴 LES DOLLARS, ET COMMENT ILS SONT OBTENUS — LE POINT LE PLUS DELICAT
═══════════════════════════════════════════════════════════════════════════
Demande de Preda (29/08) : « le prix doit etre en $ car personne ne realise
combien ca vaut 135 000 OMI ». Il a raison sur l'usage, et j'avais tranche
« impossible » a tort la veille : le cours OMI HISTORIQUE quotidien existe,
`stackr_sales.py` s'en sert deja pour son onglet _MarketRevenue.

  · MARCHE VeVe   : le prix est en GEMS, et 1 gem ~ 1 $. Recopie tel quel.
  · MARCHE StackR : `price_omi` x LE COURS DU JOUR DE LA VENTE, jamais celui
    du jour de la collecte. Une vente du 7 juillet convertie au cours d'aout
    n'est pas un prix, c'est un nombre qui y ressemble.

⛔⛔ ET SURTOUT : ON N'UTILISE PAS LE `price` DE `getVeveTransactions` POUR LES
VENTES StackR. Le docstring de `veve_tx.py` le supposait « normalise, gems ~ $ »
et portait la mention « a re-valider » — jamais honoree. Mesure du 29/08 :
273 ventes appariees (MEME piece, MEME edition, MOINS DE 2 MIN d'ecart) entre
les deux sources donnent un rapport $/OMI de 0,000239 (p10) a 0,000999 (p90) —
dispersion x4,2, et 8 % SEULEMENT a +/-10 % du cours reel (0,000247). Ce champ
ne mesure pas ce qu'on croyait. ⇒ le dollar StackR est le NOTRE, calcule ici,
et la page peut dire d'ou il vient.

💱 LE COURS : gate.io `/api/v4/spot/candlesticks?currency_pair=OMI_USDT`,
public, sans cle, 120 jours de profondeur (verifie : du 02/05 au 29/08).
⚠️ CryptoCompare `histoday` rend 401 DEPUIS LE 29/08 (cle desormais exigee) :
le chemin PRINCIPAL de `stackr_sales.py` est mort EN SILENCE et ce module ne
s'appuie donc que sur le repli. ⏭️ A corriger dans `stackr_sales.py` aussi.
🔴 UN JOUR NON COUVERT PAR LE COURS NE RECOIT PAS DE DOLLAR — colonne vide, et
la fiche affiche l'OMI. ⛔ Jamais un cours voisin « pour boucher » : c'est
exactement la faute qu'on reproche au champ ci-dessus.

Sortie : data/ventes_stackr.csv
  element_id, ts_utc, marche, edition, price_usd, price_omi, vendeur, acheteur
  trie par (element_id, ts_utc DECROISSANT)

🔴 VENDEUR / ACHETEUR : LE PSEUDO QUAND ON L'A, L'ADRESSE TRONQUEE SINON.
Arbitrage Preda du 29/08. ⚠️ Et la couverture est TRES INEGALE, mesuree le
meme jour : StackR 100 % / 100 %, VeVe 18 % / 9 %. Sur le marche VeVe le repli
sera donc la REGLE, pas l'exception — la fiche doit rendre les deux formes
aussi bien l'une que l'autre.
⛔ L'adresse est tronquee ICI, a la source : ce qui n'est pas dans le fichier
ne peut pas fuiter d'un `view-source`.

Env : VENTES_SRC_STACKR · VENTES_SRC_VEVE · VENTES_OUT
      VENTES_PAR_PIECE (10) · VENTES_ADRESSE_CH (6) · VENTES_COURS_JOURS (120)
"""

from __future__ import annotations

import csv
import datetime as _dt
import os
import sys
from collections import defaultdict
from typing import Dict, List, Optional

import requests

SRC_STACKR = os.environ.get("VENTES_SRC_STACKR", "data/stackr_sales.csv")
SRC_VEVE = os.environ.get("VENTES_SRC_VEVE", "data/veve_ventes.csv")
OUT = os.environ.get("VENTES_OUT", "data/ventes_stackr.csv")
PAR_PIECE = int(os.environ.get("VENTES_PAR_PIECE", "10"))
ADR_CH = int(os.environ.get("VENTES_ADRESSE_CH", "6"))
COURS_JOURS = int(os.environ.get("VENTES_COURS_JOURS", "120"))

ENTETE = ["element_id", "ts_utc", "marche", "edition",
          "price_usd", "price_omi", "vendeur", "acheteur"]

COLS_STACKR = ("ts_utc", "element_id", "edition", "price_omi", "seller", "buyer",
               "seller_username", "buyer_username")
COLS_VEVE = ("ts_utc", "element_id", "edition", "price_usd", "seller", "buyer",
             "seller_username", "buyer_username")

GATE = "https://api.gateio.ws/api/v4/spot/candlesticks"


def cours_omi() -> Dict[str, float]:
    """{ '2026-08-28': 0.0002406, ... } — cloture quotidienne OMI/USDT.

    ⚠️ INDEX 2 = LA CLOTURE. Le tableau de gate.io est
    [ts, volume_quote, close, high, low, open, volume_base, complet] — l'ordre
    n'est PAS celui d'une bougie OHLC classique, et prendre l'index 1 (le
    volume) donnerait des dollars absurdes sans lever la moindre erreur.
    ⭐ Releve le 29/08 sur la reponse reelle, pas sur la documentation.
    """
    try:
        r = requests.get(GATE, timeout=45, params={
            "currency_pair": "OMI_USDT", "interval": "1d", "limit": COURS_JOURS})
        r.raise_for_status()
        d = r.json()
        if not isinstance(d, list):
            raise RuntimeError("racine %s" % type(d).__name__)
        out = {}
        for c in d:
            j = _dt.datetime.utcfromtimestamp(int(c[0])).date().isoformat()
            v = float(c[2])
            if v > 0:
                out[j] = v
        print("[ventes] cours OMI : %d jours (gate.io), du %s au %s"
              % (len(out), min(out), max(out)), flush=True)
        return out
    except Exception as e:
        # ⛔ ON N'INVENTE PAS DE COURS. Sans cours, les ventes StackR partent
        # SANS dollar et la fiche affiche l'OMI — degrade, honnete, et visible.
        print("[ventes] cours OMI INJOIGNABLE (%s) — les ventes StackR "
              "partiront sans dollar." % e, file=sys.stderr)
        return {}


def _adresse(v: str) -> str:
    """`0x5198dbe1a55c...` -> `0x5198db`. Vide reste vide.

    ⛔ Pas d'ellipse unicode dans le FICHIER : ce CSV est relu par un build
    Node puis re-encode ; un caractere non-ASCII dans une colonne technique est
    une occasion de mojibake pour zero gain. Le gabarit ajoutera les points.
    """
    v = (v or "").strip()
    if not v:
        return ""
    return v[: 2 + ADR_CH] if v.startswith("0x") else v[:ADR_CH]


def _qui(pseudo: str, adresse: str) -> str:
    """Le pseudo quand on l'a, l'adresse tronquee sinon.

    ⚠️ `strip()` AVANT le test de verite : la source ecrit parfois une chaine
    d'espaces, qui est VRAIE en Python et donnerait un nom vide a l'ecran.
    """
    p = (pseudo or "").strip()
    return p if p else _adresse(adresse)


def _lire(chemin: str, colonnes) -> List[Dict[str, str]]:
    if not os.path.exists(chemin):
        # ⭐ ABSENT N'EST PAS FAUTIF : `veve_ventes.csv` n'existe pas au premier
        # run, et `stackr_sales.csv` pourrait disparaitre d'un depot frais. On
        # le DIT et on continue avec l'autre marche — un seul marche vaut mieux
        # que pas de tableau du tout.
        print("[ventes] source absente : %s" % chemin, flush=True)
        return []
    with open(chemin, newline="", encoding="utf-8") as f:
        lec = csv.DictReader(f)
        manque = [c for c in colonnes if c not in (lec.fieldnames or [])]
        if manque:
            # ⛔ CELUI-LA EST FATAL. Une colonne renommee en amont ferait ecrire
            # 12 000 prix vides EN SORTANT VERT — la panne la plus chere de ce
            # projet est celle qui ne rougit pas.
            print("[ventes] COLONNES ABSENTES de %s : %s" % (chemin, manque),
                  file=sys.stderr)
            print("[ventes] vu : %s" % (lec.fieldnames,), file=sys.stderr)
            raise SystemExit(1)
        return list(lec)


def main() -> int:
    cours = cours_omi()
    lignes: List[Dict[str, str]] = []
    sans_cours = 0

    for l in _lire(SRC_VEVE, COLS_VEVE):
        lignes.append({
            "element_id": (l.get("element_id") or "").strip(),
            "ts_utc": l.get("ts_utc", ""), "marche": "veve",
            "edition": l.get("edition", ""),
            "price_usd": l.get("price_usd", ""), "price_omi": "",
            "vendeur": _qui(l.get("seller_username"), l.get("seller")),
            "acheteur": _qui(l.get("buyer_username"), l.get("buyer")),
        })

    for l in _lire(SRC_STACKR, COLS_STACKR):
        ts = l.get("ts_utc", "")
        jour = ts[:10]
        usd = ""
        try:
            omi = float(l.get("price_omi") or 0)
        except ValueError:
            omi = 0.0
        # ⚠️ LE COURS DU JOUR DE LA VENTE, PAS D'UN JOUR VOISIN. Un jour manquant
        # (week-end sans bougie, trou chez gate.io, vente plus vieille que la
        # fenetre de 120 j) laisse la colonne VIDE. La fiche montrera l'OMI.
        taux = cours.get(jour)
        if omi > 0 and taux:
            usd = "%.2f" % (omi * taux)
        elif omi > 0:
            sans_cours += 1
        lignes.append({
            "element_id": (l.get("element_id") or "").strip(),
            "ts_utc": ts, "marche": "stackr", "edition": l.get("edition", ""),
            "price_usd": usd, "price_omi": l.get("price_omi", ""),
            "vendeur": _qui(l.get("seller_username"), l.get("seller")),
            "acheteur": _qui(l.get("buyer_username"), l.get("buyer")),
        })

    if sans_cours:
        print("[ventes] %d ventes StackR sans cours pour leur jour — elles "
              "partent en OMI seul." % sans_cours, flush=True)

    par: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    sans_piece = 0
    for l in lignes:
        if not l["element_id"]:
            sans_piece += 1
            continue
        par[l["element_id"]].append(l)
    if sans_piece:
        print("[ventes] %d ligne(s) sans element_id, ecartees." % sans_piece)

    sortie: List[List[str]] = []
    for eid in sorted(par):
        # 🔴 `reverse=True` PUIS la coupe : on garde les N PLUS RECENTES, tous
        # marches confondus. Couper avant de trier garderait les N premieres du
        # fichier — et les deux sources sont APPEND-ONLY, donc leur debut est
        # leur passe le plus vieux. L'inversion publierait, sur chaque fiche,
        # les ventes les plus ANCIENNES en les appelant « dernieres ».
        # ⚠️ TRI SUR LA CHAINE ISO, largeur fixe : l'ordre lexicographique EST
        # l'ordre chronologique. Parser 13 000 dates pour retrouver le meme
        # ordre serait payer un parseur ET ajouter un chemin d'erreur.
        for l in sorted(par[eid], key=lambda x: x["ts_utc"] or "", reverse=True)[:PAR_PIECE]:
            sortie.append([l[c] for c in ENTETE])

    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(ENTETE)
        w.writerows(sortie)

    pieces = len({l[0] for l in sortie})
    avec_usd = sum(1 for l in sortie if l[4])
    m = defaultdict(int)
    for l in sortie:
        m[l[2]] += 1
    print("[ventes] %d lues -> %d publiees sur %d pieces (%s) — %d avec dollar, %d o"
          % (len(lignes), len(sortie), pieces,
             " + ".join("%s %d" % (k, v) for k, v in sorted(m.items())),
             avec_usd, os.path.getsize(OUT)), flush=True)

    # 🩺 GARDE-FOU. Une source qui se vide, un renommage silencieux, un filtre
    # trop large : tout ca produit un fichier PETIT, jamais un plantage.
    if not sortie:
        print("[ventes] AGREGAT VIDE — on refuse de publier.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
