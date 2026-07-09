"""
Sonde Market VeVe SANS authentification — diagnostic du chantier 7.

Teste les 2 requetes du module veve_market sans aucun cookie et affiche les
reponses BRUTES (statut HTTP, erreurs GraphQL, echantillon de donnees) :

    1. MarketLandingCollectiblesPageQuery  (grille d'accueil du market)
    2. MarketFromCollectibleTypeQuery      (offres d'un collectible precis)

Si les deux repondent sans auth -> on peut relancer la collecte Market
(pseudos vendeurs + prix des offres) et batir la detection des ventes
(offre disparue + transfert escrow->acheteur = vente au dernier prix liste).

N'ecrit RIEN dans le Sheet. Env optionnel : PROBE_COLLECTIBLE_ID (uuid d'un
collectible a sonder ; par defaut le 1er de la grille).
"""

from __future__ import annotations

import json
import os
import sys

import requests

from scraper.veve_market import (GRAPHQL_URL, LANDING_OP, LANDING_QUERY,
                                 LISTINGS_OP, LISTINGS_QUERY, _headers)


def _post_raw(op: str, query: str, variables) -> dict | None:
    r = requests.post(GRAPHQL_URL, headers=_headers(op),
                      json={"operationName": op, "query": query,
                            "variables": variables},
                      timeout=30)
    print(f"\n{op}: HTTP {r.status_code}", flush=True)
    try:
        data = r.json()
    except Exception:
        print("Reponse non-JSON:", r.text[:400], flush=True)
        return None
    if data.get("errors"):
        print("errors:", json.dumps(data["errors"])[:600], flush=True)
    return data.get("data")


def main() -> int:
    if os.environ.get("VEVE_AUTH", "").strip():
        print("ATTENTION : VEVE_AUTH est defini — ce test est cense tourner SANS auth.")
    else:
        print("Sonde SANS auth (aucun cookie envoye).", flush=True)

    cid = os.environ.get("PROBE_COLLECTIBLE_ID", "").strip()

    d = _post_raw(LANDING_OP, LANDING_QUERY, {"cursor": None})
    if d:
        conn = d.get("marketListingByCollectibleType") or {}
        edges = conn.get("edges") or []
        print(f"Grille : {len(edges)} produits avec offres. Echantillon :", flush=True)
        for e in edges[:5]:
            n = e.get("node") or {}
            print(f"    {n.get('name')!r} rarity={n.get('rarity')} "
                  f"listings={n.get('totalMarketListings')} floor={n.get('floorMarketPrice')}",
                  flush=True)
        if edges and not cid:
            cid = str((edges[0].get("node") or {}).get("id") or "")
    else:
        print("Grille KO sans auth.", flush=True)

    if not cid:
        print("\nPas d'id de collectible disponible pour la requete offres — fin.", flush=True)
        return 0

    d2 = _post_raw(LISTINGS_OP, LISTINGS_QUERY,
                   {"cursor": None, "collectibleTypeId": cid,
                    "sortBy": "PRICE", "sortDirection": "ASCENDING",
                    "markets": ["VEVE", "STACKR"]})
    if d2:
        conn = d2.get("marketListingFromCollectibleType") or {}
        edges = conn.get("edges") or []
        print(f"Offres pour {cid} : totalCount={conn.get('totalCount')}. "
              f"Echantillon :", flush=True)
        for e in edges[:5]:
            n = e.get("node") or {}
            print(f"    edition #{n.get('issueNumber')} {n.get('price')} "
                  f"{n.get('currency')} vendeur={n.get('sellerName')!r} "
                  f"market={n.get('market')}", flush=True)
        print("\nVERDICT : le Market repond SANS auth — collecte relancable.", flush=True)
    else:
        print("\nVERDICT : offres KO sans auth (voir erreurs ci-dessus).", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
