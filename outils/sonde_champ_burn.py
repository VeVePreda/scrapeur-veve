#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : outils/sonde_champ_burn.py
#
# outils/sonde_champ_burn.py — REJOUER la preuve que la date de burn n'est pas
# collectable chez VeVe. Une requete par nom candidat, sur un comic qui a
# REELLEMENT brule.
#
#   python3 outils/sonde_champ_burn.py            # les 4 noms du chantier
#   python3 outils/sonde_champ_burn.py --tout     # les 37 noms sondes le 05/08
#   python3 outils/sonde_champ_burn.py --id <uuid>
#
# ---------------------------------------------------------------------------
# 🔴🔴 POURQUOI CET OUTIL EXISTE (05/08/2026)
#
# Le lot 67 SUPPRIME de `veve_detail.py` un repli qui essayait trois noms de
# champ (`burnDate`, `burnsAt`, `burnAt`) avant d'abandonner. Il le supprime
# parce qu'aucun de ces noms n'existe. Mais une suppression fondee sur une
# mesure qu'on ne peut plus rejouer n'est plus une mesure : c'est une croyance
# qui a l'air d'un fait, et le prochain lecteur la remettra — ou pire, la
# recopiera sans la verifier.
#
# ⭐⭐⭐ UNE ABSENCE QU'ON NE PEUT PAS REJOUER EST UNE CROYANCE.
#
# C'est deja arrive une fois, en sens inverse : le 05/08 au matin, le message
# « VeVe refuse le champ » a ete lu comme « VeVe a retire le champ », puis
# recopie en memoire comme un fait etabli. Il n'etait ni l'un ni l'autre — il
# etait une INTERPRETATION d'un HTTP 400.
# ⭐⭐⭐ UN MESSAGE D'ERREUR QUI INTERPRETE AU LIEU DE DECRIRE PROPAGE SON
# HYPOTHESE A TOUS SES LECTEURS. Cet outil ne conclut donc rien tout seul : il
# imprime le code HTTP et la reponse, et c'est le lecteur qui tranche.
#
# ⚠️ CE QU'IL COUTE : une requete par nom, sur un endpoint public deja
# instrumente par la sentinelle. ⛔ NE PAS le brancher sur un cron : une sonde
# qui tourne toute seule devient du trafic, et le trafic devient un motif.
# ---------------------------------------------------------------------------
import argparse
import json
import sys
import urllib.error
import urllib.request

URL = "https://web.api.prod.veve.me/graphql"

# Les memes en-tetes que `scraper/veve_detail.py` — recopies et non importes
# pour que la sonde tourne dans un dossier nu, sans le paquet. ⚠️ Si VeVe change
# son controle CSRF, les deux endroits sont a changer.
HEADERS = {
    "content-type": "application/json",
    "x-auth-version": "2",
    "client-name": "veve-app-web-server",
    "client-version": "1.0",
    "client-operation": "publicStoreCollectibleEditionsQuery",
    "user-agent": "Mozilla/5.0 (compatible; veve-catalogue-sync/1.0)",
    "accept": "application/json",
}

# 🔥 LE TEMOIN. The X-Men (1963), sorti le JEUDI 25/06/2026, retenues 99/1000.
# Au 05/08/2026 : totalIssued 1 000 = 430 vendues + 99 retenues + 471 BRULEES.
# ⭐ Le choix du temoin EST l'argument : sur un comic sans burn programme, un
# HTTP 400 ne prouverait rien (« le champ n'existe que sur les items concernes »
# resterait possible). Sur celui-ci, il a brule — si le champ existait, il
# porterait une valeur.
TEMOIN = "ce33b280-66fc-403c-aa6e-9f7887752744"

BASE = ("query publicStoreCollectibleEditionsQuery($id: ID!){ "
        "publicComicType(id:$id){ id name dropDate totalIssued soldEditions "
        "editionsBurnt editionsInCirculation withheldEditions%s } }")

# Les 4 du chantier : les 3 candidats supprimes + `expiryDate`, que le plan du
# 05/08 voulait collecter.
COURT = ["burnDate", "burnsAt", "burnAt", "expiryDate"]

# Les 37 sondes le 05/08. ⚠️ La liste est LONGUE exprès : « je n'ai pas trouve
# le bon nom » et « le nom n'existe pas » se ressemblent, et seule l'etendue de
# la recherche les separe.
TOUT = COURT + [
    "burnedAt", "burnStartDate", "burnEndDate", "burnAtDate",
    "expiresAt", "expiryAt", "expirationDate", "expiry",
    "endDate", "endsAt", "saleEndDate", "saleEndsAt", "availableUntil",
    "availableUntilDate", "storeEndDate", "storeExpiryDate", "removedAt",
    "retiredAt", "withdrawnAt", "leavingAt", "leavingDate", "leavesAt",
    "burnScheduledAt", "scheduledBurnDate", "editionsBurntAt", "burnTime",
    "burnTimestamp", "isBurning", "burningSoon", "willBurn",
    "storeAvailabilityEndDate", "availabilityEndDate", "dropEndDate",
]


def interroge(uuid: str, champ: str):
    """Rend (code HTTP, corps). ⛔ N'interprete pas : un 400 est rendu tel quel."""
    corps = json.dumps({
        "operationName": "publicStoreCollectibleEditionsQuery",
        "variables": {"id": uuid},
        "query": BASE % (" " + champ if champ else ""),
    }).encode()
    req = urllib.request.Request(URL, data=corps, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:                       # reseau coupe, DNS, proxy…
        return 0, f"({e.__class__.__name__}) {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--id", default=TEMOIN, help="uuid du comic temoin")
    ap.add_argument("--tout", action="store_true",
                    help="les 37 noms au lieu des 4 du chantier")
    a = ap.parse_args()

    print(f"temoin : {a.id}")
    code, corps = interroge(a.id, "")
    print(f"\n[requete PROUVEE, sans champ ajoute] HTTP {code}")
    print("  " + corps[:400])
    if code != 200:
        print("\n⛔ Le temoin lui-meme ne repond pas. Tout ce qui suit serait "
              "un refus du COMIC, pas du CHAMP — on s'arrete la.",
              file=sys.stderr)
        return 2
    try:
        n = (json.loads(corps).get("data") or {}).get("publicComicType") or {}
        brulees = n.get("editionsBurnt")
    except Exception:
        brulees = None
    if not brulees:
        print(f"\n⚠️ Le temoin affiche editionsBurnt={brulees!r}. Il n'a donc "
              "PAS brule, et un refus ci-dessous ne prouverait rien : "
              "choisir un autre temoin avec --id.", file=sys.stderr)
    else:
        print(f"\n✅ Le temoin a bien brule ({brulees} editions) — un champ de "
              "date de burn, s'il existait, aurait ici une valeur.")

    champs = TOUT if a.tout else COURT
    refuses, acceptes = [], []
    print(f"\n{'champ ajoute':30} {'HTTP':>5}   reponse")
    print("-" * 78)
    for c in champs:
        code, corps = interroge(a.id, c)
        ok = code == 200 and '"errors"' not in corps
        (acceptes if ok else refuses).append(c)
        print(f"{c:30} {code:>5}   {'✅ ' + corps[:120] if ok else '⛔'}")

    print("\n" + "=" * 78)
    print(f"refuses  : {len(refuses)}/{len(champs)}")
    print(f"acceptes : {len(acceptes)}/{len(champs)}"
          + (f"  -> {', '.join(acceptes)}" if acceptes else ""))
    if acceptes:
        print("\n🔴 UN NOM PASSE. La suppression du lot 67 n'est plus fondee : "
              "relire scraper/burn_prevu.py et scraper/veve_detail.py.")
        return 1
    print("\n✅ Aucun nom ne passe, sur un comic qui a reellement brule. "
          "La date de burn n'est pas exposee : elle se CALCULE "
          "(scraper/burn_prevu.py).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
