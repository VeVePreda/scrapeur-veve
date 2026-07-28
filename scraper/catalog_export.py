#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/catalog_export.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier depose au
# mauvais endroit ne provoque aucune erreur : il dort.
"""catalog_export — catalogue exploitable HORS Sheet (preda -> Release jetonveve).

Exporte le referentiel des items (uuid -> nom, rarete, serie, marque, tirage,
store price, floor du jour) en 1 CSV.gz, publie ensuite en Release `catalogue`
sur jetonveve (public) par le workflow. But : que l'entrepot soit AUTOSUFFISANT
— alertes, chatbot et service de tracking n'ont plus besoin d'un acces Google
pour connaitre les noms/prix ; ils joignent par uuid avec analytics-derived
et transfers.parquet.

Lecture des colonnes PAR NOM au runtime (robuste si l'ordre des colonnes du
Sheet change — meme pattern que fiche.py). Sources : 🔵C-COLLECTIBLE +
🟢C-COMICS (froid) + _DynState (floor/listings/store du jour).

Sortie : catalogue.csv.gz — header :
  uuid,kind,name,edition_type,rarity,release_date,series,brand,licensor,
  tirage,store_price,floor,listings,ath,atl

🪪 IDENTITE CHAINE (28/07/2026) — etape ADDITIVE et GATED, cf. plus bas.

Env : GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID (comme le daily),
      EXPECTED_MIN_ITEMS (defaut 15000, garde-fou exit 1),
      CATALOG_OUT (defaut catalogue.csv.gz),
      CATALOG_IDENTITE_CHAINE (defaut OFF — sans lui, NO-OP total),
      ELEMENTS_V3 (defaut data/elements_v3.csv),
      CATALOG_CHURN_AUTORISE (soupape, cf. `verifier_churn`).
"""
import csv
import gzip
import os
import sys
import time

from scraper import identite as ID
from scraper.sheets import _client

COLLECT_TAB = "🔵C-COLLECTIBLE"
COMICS_TAB = "🟢C-COMICS"
DYN_STATE_TAB = "_DynState"

# nom de sortie -> nom de colonne dans le Sheet (froid)
COLD_MAP = [
    ("uuid", "veve_uuid"), ("kind", "category"), ("name", "name"),
    ("edition_type", "edition_type"), ("rarity", "rarity"),
    ("release_date", "releaseDate"), ("series", "veve_series_name"),
    ("brand", "veve_brand"), ("licensor", "veve_licensor"),
    ("tirage", "supply"), ("store_price", "store_price_gems"),
    ("ath", "ath"), ("atl", "atl"),
]
# nom de sortie -> colonne _DynState (chaud, floor du jour)
DYN_MAP = [("floor", "market_lowestOffer"), ("listings", "market_totalListings")]

HEADER = [o for o, _ in COLD_MAP[:11]] + ["floor", "listings", "ath", "atl"]

# ---------------------------------------------------------------------------
# 🪪 L'IDENTITE CHAINE — etape ADDITIVE, GATED, et REVERSIBLE
# ---------------------------------------------------------------------------
# INTERRUPTEUR : `CATALOG_IDENTITE_CHAINE` (defaut OFF). Sans lui, ce bloc est un
# NO-OP TOTAL : meme en-tete, meme contenu, octet pour octet. Deposer ce fichier
# ne change donc RIEN en prod tant que Preda ne l'allume pas.
# REVERSIBLE : le catalogue est RECONSTRUIT depuis le Sheet a chaque run.
# Remettre la variable a 0 -> le run suivant est de nouveau 100 % Sheet, sans le
# moindre residu. (Meme dispositif que `bascule_identite` pour le pipeline 1.)
ELEMENTS_V3 = os.environ.get("ELEMENTS_V3", "data/elements_v3.csv")

# ⭐ Plafonds de CHURN, calibres sur les VRAIS fichiers (28/07/2026 : le
# catalogue du Sheet contre elements_v3 apres rattrapage de `source`) :
#   name 44,7 % · series 85,7 % · brand 24,3 % · edition_type 3,6 %
#   kind 0 % · rarity 0,04 % · tirage 0,1 % · licensor 0,8 %
# Le plafond de `series` est HAUT parce que ce remaniement-la est ATTENDU et
# DECIDE : `veve_series_name` du Sheet est le nom complet de la couverture, pas
# une serie — 100 % des comics changent, par construction. Les autres plafonds
# restent SERRES : c'est eux qui attraperaient une source degradee.
# ⚠️ Ne pas relever un plafond pour faire passer un run. Un depassement veut dire
# que la source a change de nature — cf. la lecon `verifier_churn`.
PLAFONDS_CHURN = {
    "name": 0.50, ID.COL_SERIE: 0.90, "brand": 0.30, "edition_type": 0.10,
    "kind": 0.01, "rarity": 0.01, "tirage": 0.02, "licensor": 0.05,
}

# Volumetrie PAR FAMILLE (18 926 items au 28/07 : 16 266 comics, 2 660
# collectibles). Un seuil global ne verrait pas une famille entiere disparaitre.
MINI_PAR_TYPE = {ID.KIND_COMIC: 14_000, ID.KIND_COLLECTIBLE: 2_000}


def _identite_active() -> bool:
    return os.environ.get("CATALOG_IDENTITE_CHAINE", "").strip().lower() in (
        "1", "true", "oui", "on")


def lire_chaine(chemin: str) -> dict:
    """{uuid: ligne v3} — UNIQUEMENT les lignes que la chaine a vraiment VUES.

    ⭐⭐ C'EST ICI QUE LA COLONNE `source` SERT. `elements_v3.csv` contient aussi
    des lignes RECOPIEES du tracker (`combler_depuis_officiel`) : 136 objets au
    28/07/2026, jamais mintes on-chain. Les donner a `fusionner` laisserait le
    TRACKER ecraser le Sheet en se faisant passer pour la chaine — l'inverse
    exact de la doctrine. On ne garde donc que `source == 'chaine'`.

    Une colonne `source` ABSENTE (fichier anterieur au 28/07) : on ne devine
    pas, on refuse tout. Mieux vaut un catalogue Sheet qu'un catalogue faux.
    """
    if not os.path.exists(chemin):
        print(f"⛔ {os.path.abspath(chemin)} absent — identite chaine IGNOREE, "
              f"le catalogue reste 100 % Sheet.", file=sys.stderr)
        return {}
    out, hors, sans_col = {}, 0, True
    with open(chemin, encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        sans_col = "source" not in (rd.fieldnames or [])
        for r in rd:
            uid = (r.get("veve_uuid") or "").strip()
            if not uid:
                continue
            if (r.get("source") or "").strip() == "chaine":
                out[uid] = r
            else:
                hors += 1
    if sans_col:
        print("⛔ elements_v3.csv SANS colonne `source` (fichier anterieur au "
              "28/07/2026) — on ne devine pas la provenance : identite chaine "
              "IGNOREE.", file=sys.stderr)
        return {}
    print(f"identite : {len(out)} lignes vues on-chain retenues · {hors} "
          f"ecartees (tracker ou provenance inconnue).")
    return out


def appliquer_identite(items: list, chaine: dict, *, autorise: bool = False,
                       plafonds: dict = None, mini_par_type: dict = None) -> None:
    """Fusionne l'identite chaine DANS `items`, en place. Leve si un garde-fou saute.

    L'ordre compte : on MESURE d'abord (rapport), on VERIFIE l'ampleur ensuite
    (churn), on valide les lignes en dernier. Une source degradee produit des
    lignes parfaitement valides — c'est toute la lecon de `verifier_churn`.
    """
    avant = {i["uuid"]: dict(i) for i in items}
    for i in items:
        i.update(ID.fusionner(i, chaine.get(i["uuid"])))
    apres = {i["uuid"]: i for i in items}
    print(ID.rapport(avant, apres))
    ID.verifier_churn(avant, apres,
                      PLAFONDS_CHURN if plafonds is None else plafonds,
                      autorise=autorise)
    ID.valider(items, mini_total=len(items),
               mini_par_type=MINI_PAR_TYPE if mini_par_type is None
               else mini_par_type)


def _retry(fn, tries=5):
    """Backoff 429/503 (meme lecon que export_elements : ne pas avaler)."""
    for i in range(tries):
        try:
            return fn()
        except Exception as exc:                      # noqa: BLE001
            code = getattr(getattr(exc, "response", None), "status_code", None)
            if code not in (429, 503) or i == tries - 1:
                raise
            wait = [15, 30, 45, 60][min(i, 3)]
            print(f"  {code} Google — retry dans {wait}s ({i + 1}/{tries})")
            time.sleep(wait)
    return None


def _rows_by_name(ws) -> list:
    """get_all_values -> liste de dicts {nom de colonne: valeur}."""
    values = _retry(ws.get_all_values)
    if not values:
        return []
    head = values[0]
    return [dict(zip(head, r)) for r in values[1:] if any(r)]


def main() -> None:
    out = os.environ.get("CATALOG_OUT", "catalogue.csv.gz")
    expected = int(os.environ.get("EXPECTED_MIN_ITEMS") or 15_000)
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        print("ERROR: SHEET_ID requis.", file=sys.stderr)
        sys.exit(1)
    sh = _client().open_by_key(sheet_id)

    # ── floor/listings du jour (facultatif : on exporte meme sans) ──────────
    dyn = {}
    try:
        for r in _rows_by_name(sh.worksheet(DYN_STATE_TAB)):
            uid = (r.get("veve_uuid") or "").strip()
            if uid:
                dyn[uid] = {o: (r.get(c) or "") for o, c in DYN_MAP}
        print(f"_DynState : {len(dyn)} uuids (floor/listings)")
    except Exception as exc:                          # noqa: BLE001
        print(f"⚠️ _DynState illisible ({exc}) — catalogue exporte SANS floors.")

    # ── catalogue froid (collectibles + comics) ─────────────────────────────
    items, seen = [], set()
    for tab, default_kind in ((COLLECT_TAB, "collectible"), (COMICS_TAB, "comic")):
        rows = _rows_by_name(sh.worksheet(tab))
        n = 0
        for r in rows:
            uid = (r.get("veve_uuid") or "").strip()
            if not uid or uid in seen:
                continue
            seen.add(uid)
            rec = {o: (r.get(c) or "") for o, c in COLD_MAP}
            rec["uuid"] = uid
            rec["kind"] = rec["kind"] or default_kind
            rec.update(dyn.get(uid, {o: "" for o, _ in DYN_MAP}))
            items.append(rec)
            n += 1
        print(f"{tab} : {n} items")

    if len(items) < expected:
        print(f"ERREUR GARDE-FOU : {len(items)} items < {expected} — "
              "lecture Sheet incomplete ? Release NON mise a jour.")
        sys.exit(1)

    # ── 🪪 IDENTITE CHAINE (gated) ──────────────────────────────────────────
    # Placee APRES le garde-fou de volumetrie : inutile de fusionner sur une
    # lecture Sheet incomplete. `name_display` n'apparait que si l'etape tourne
    # -> interrupteur eteint = fichier octet pour octet identique a la veille.
    entete = list(HEADER)
    if _identite_active():
        chaine = lire_chaine(ELEMENTS_V3)
        if chaine:
            appliquer_identite(
                items, chaine,
                autorise=os.environ.get("CATALOG_CHURN_AUTORISE", "").strip()
                in ("1", "true", "oui", "on"))
            entete = list(HEADER) + ["name_display"]
    else:
        print("identite chaine : interrupteur OFF (CATALOG_IDENTITE_CHAINE) — "
              "catalogue 100 % Sheet, inchange.")

    with gzip.open(out, "wt", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=entete, extrasaction="ignore")
        w.writeheader()
        w.writerows(items)
    with_floor = sum(1 for i in items if i.get("floor"))
    print(f"✅ {out} : {len(items)} items ({with_floor} avec floor).")


if __name__ == "__main__":
    main()
