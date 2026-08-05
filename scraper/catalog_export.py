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
  tirage,store_price,floor,listings,ath,atl,image,ath_date,atl_date,
  description,veve_comic_name

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
    # 🖼️ LE VISUEL DE LA PIECE. Present depuis toujours dans les DEUX onglets
    # (COLLECTIBLE_COLD et COMICS_COLD, sheets.py), il ne traversait simplement
    # pas l'export : le site avait 19 242 fiches et pas une image.
    ("image", "image_url"),
    # 🔗 LE LIEN VERS LA PAGE VEVE — quatrieme fois exactement le meme motif
    # que `image`, `ath_date` et `description` avant lui (03/08/2026).
    # `veve_url` est une colonne froide des DEUX onglets (`sheets.py` l.58 et
    # l.70), ecrite par `build_veve_url` a CHAQUE sync, et renseignee sur
    # 19 242 / 19 242 lignes — 16 521 comics + 2 721 collectibles, ZERO vide.
    # Elle ne traversait simplement pas l'export : le site affichait un tiret.
    # ⭐ CE N'ETAIT PAS UNE DONNEE MANQUANTE, C'ETAIT UNE LIGNE MANQUANTE.
    # ⚠️ Verifie AVANT d'etre pose, pas apres :
    #   comics       -> https://www.veve.me/collectibles/en/comics/<series_uuid>
    #   collectibles -> https://www.veve.me/collectibles/en/collectibles/<uuid>
    # Preda a ouvert la premiere forme le 03/08 (page vivante) ; la seconde a
    # ete relevee sur la page elle-meme (titre reel « Happy New Year! 2026 -
    # Tier 7 | VeVe », la ou un uuid inexistant rend le titre generique
    # « VeVe Collectibles »). ⛔ Le code HTTP ne prouve RIEN ici : veve.me est
    # une application a rendu client, elle rend 200 sur une adresse morte.
    ("veve_url", "veve_url"),
    ("ath", "ath"), ("atl", "atl"),
    # 📅 LES DATES DES EXTRÊMES. Elles sont dans le Sheet (`ath_date`,
    # `atl_date`, ajoutées EN FIN de COLLECTIBLE_COLD/COMICS_COLD) et ne
    # traversaient pas l'export. ⭐ Sans elles, la jauge de la fiche affiche
    # « plus haut historique : 1 750 » sans dire QUAND — or c'est la date qui
    # transforme un nombre en information.
    ("ath_date", "ath_date"), ("atl_date", "atl_date"),
    # 📝 LA DESCRIPTION. Meme histoire que `image` et `ath_date` avant elle :
    # presente dans les DEUX onglets froids (COLLECTIBLE_COLD et COMICS_COLD,
    # sheets.py l.55 et l.67) depuis toujours, elle ne traversait simplement
    # pas l'export — les fiches du site n'avaient donc aucun texte.
    # ⭐ TROISIEME FOIS QUE CE MOTIF SE PRODUIT SUR CE MEME FICHIER. La donnee
    # est collectee, ecrite dans le Sheet, et perdue a la derniere etape parce
    # que personne n'a ajoute la ligne. Rien n'echoue : la colonne manque, et
    # une fiche sans description a l'air d'une fiche dont on n'a pas la
    # description.
    ("description", "description"),
    # 📕 LE VRAI TITRE DU COMIC — colonne froide depuis le 01/08/2026.
    # ⚠️ VIDE POUR LES COLLECTIBLES, et c'est normal : leur `name` EST deja le
    # nom de l'objet. Le site doit donc s'en servir en REPLI sur `name`,
    # jamais le supposer present. Un `extrasaction="ignore"` rendrait ""
    # sur l'onglet bleu sans lever la moindre erreur.
    ("veve_comic_name", "veve_comic_name"),
]
# nom de sortie -> colonne _DynState (chaud, floor du jour)
DYN_MAP = [("floor", "market_lowestOffer"), ("listings", "market_totalListings")]

# ⛔ `COLD_MAP[:11]` ETAIT UN NOMBRE MAGIQUE. Il voulait dire « tout sauf ath
# et atl », qui sont reinjectes juste apres — mais il le disait par une
# POSITION, pas par un nom. Ajouter une colonne a COLD_MAP la faisait donc
# disparaitre de l'en-tete, et `csv.DictWriter(extrasaction="ignore")` la
# jetait A L'ECRITURE, SANS UN MOT. La donnee etait lue, portee jusqu'au
# writer, puis abandonnee.
# ⭐ Une exclusion NOMMEE dit ce qu'elle veut dire et survit a l'ajout suivant.
_EN_FIN = ("ath", "atl", "ath_date", "atl_date")   # posees apres floor/listings, ordre historique
HEADER = ([o for o, _ in COLD_MAP if o not in _EN_FIN]
          + ["floor", "listings", *_EN_FIN])

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


# ---------------------------------------------------------------------------
# 🛡️ LA PAIRE ATL/ATH IMPOSSIBLE — LE GARDE-FOU QUI MANQUAIT SUR CE CHEMIN
# ---------------------------------------------------------------------------
# ⛔⛔ AJOUTE LE 31/07/2026. `export_elements.py` REFUSE d'exporter une paire
# ATL > ATH depuis le 22/07 — il l'exporte VIDE et compte ce qu'il retient.
# `catalog_export.py` n'avait PAS ce controle, et c'est LUI qui alimente la
# release `catalogue`, donc le SITE. Le pont vers jetonveve etait protege ;
# la source du site recopiait les paires incoherentes telles quelles.
# ⭐⭐ « CORRIGE SUR UN CHEMIN » N'EST PAS « CORRIGE ». Le meme defaut, la
# meme donnee, deux sorties : une assainie, une pas. Cote veveprice on a fini
# par MASQUER l'incoherence a l'affichage — un symptome traite a l'endroit ou
# il se voit, pas a l'endroit ou il naît.
# ⭐ MEME POLITIQUE QU'EN FACE, DELIBEREMENT : vide = « inconnu ». Jamais un
# chiffre qu'on sait faux, jamais une correction devinee ici. La reparation se
# fait dans le Sheet (`repare_atl_ath.py`), pas dans un exportateur.
def _dec(x) -> float:
    """Une cellule Sheet -> float. « 8 888,88 » comme « 6.99 » comme « »."""
    t = str(x or "").replace("\u202f", "").replace("\u00a0", "").replace(" ", "")
    t = t.replace(",", ".").strip()
    try:
        return float(t)
    except ValueError:
        return 0.0


def _paire_corrompue(rec) -> bool:
    """ATL > ATH = paire impossible (decimales FR x100 gelees dans le Sheet)."""
    atl, ath = _dec(rec.get("atl")), _dec(rec.get("ath"))
    return atl > 0 and ath > 0 and atl > ath


# ---------------------------------------------------------------------------
# 🎪 LE PLAFOND DE VRAISEMBLANCE — LE TROLL N'EST PAS UNE CORRUPTION
# ---------------------------------------------------------------------------
# ⛔⛔ AJOUTE LE 03/08/2026, et c'est un defaut DIFFERENT de la paire inversee.
# Preda a signale une fiche « ATL 3 499 / ATH 9 999 999 ». On l'a d'abord rangee
# avec les paires impossibles — a tort : ici `atl < ath`, donc
# `_paire_corrompue` rend False, et elle a RAISON de le rendre. Ce n'est pas
# l'ordre qui cloche, c'est la VALEUR.
#
# ⭐⭐⭐ UN « PLUS HAUT HISTORIQUE » BATI SUR UN PRIX **DEMANDE** ENREGISTRE LES
# TROLLS COMME DES RECORDS. Les valeurs vues dans le Sheet le disent d'elles-
# memes : 9 999 999 · 1 234 567 · 9 696 969 · 888 888 · 8 888 888. Personne n'a
# paye ca — quelqu'un l'a AFFICHE. La memoire du projet le notait deja pour
# ODDY a 888 888 : « listing troll probable, PAS une corruption ».
#
# ⛔ CE N'EST DONC PAS REPARABLE EN AMONT. Le tracker dit la verite : ce prix a
# bien ete demande. `repare_atl_ath.py` re-source depuis le tracker — il
# reecrirait donc exactement la meme valeur. C'est une decision d'AFFICHAGE,
# pas un bug de collecte, et elle se prend ici, au dernier poste avant le site.
#
# MESURE DU 03/08 (Sheet frais, 19 242 lignes) :
#   ath > 15 000 $ : 1 388 (7,21 %)   ·   atl > 15 000 $ : 107 (0,56 %)
#   les DEUX au-dessus : 92           ·   ath seul : 1 296
# ⭐ CES 1 296 SONT LA RAISON D'ETRE DU TRAITEMENT PAR COTE. Leur `atl` est
# parfaitement bon (« ATL 798 / ATH 9 999 999 ») : vider les deux jetterait
# 1 296 plus-bas valides pour punir un plus-haut. On degrade, on ne casse pas.
#
# ⚠️ SEUIL A 15 000 $ (choix de Preda). Ce qui tombe juste au-dessus a ete
# regarde avant de le poser, et ce sont bien des trolls : ATL 13 / ATH 32 999,
# ATL 5 / ATH 25 000, ATL 31 / ATH 30 000 — des demandes absurdes sur des
# comics dont le plancher vaut quelques dollars. Reglable par
# `CATALOG_PLAFOND_EXTREMES` ; a 0 le controle est DESARME (et il le dit).
PLAFOND_EXTREMES = _dec(os.environ.get("CATALOG_PLAFOND_EXTREMES", "15000")) or 0.0


def _hors_plafond(v, plafond: float) -> bool:
    """Une valeur au-dessus du plafond de vraisemblance. 0 = controle desarme."""
    if plafond <= 0:
        return False
    return _dec(v) > plafond


def _assainir_extremes(items: list, plafond: float = None) -> tuple:
    """Assainit les extremes AVANT l'ecriture.

    Rend `(n_paires, n_atl, n_ath, n_orphelines)`.

    TROIS PASSES, ET L'ORDRE COMPTE :

    1. ⭐ LE PLAFOND D'ABORD, COTE PAR COTE. Un `atl` troll (9 999 999) CREE
       une paire inversee : le traiter en premier vide la seule valeur fautive
       et laisse un `ath` parfaitement bon. Passer l'inversion en premier
       viderait les deux — on aurait puni la victime.
    2. Puis la paire impossible (`atl > ath`), qui vide les DEUX : quand
       l'ordre lui-meme est faux, on ne sait plus laquelle des deux ment.

    ⚠️ LES DATES PARTENT AVEC LES VALEURS, dans les deux passes. Garder
    `ath_date` en vidant `ath` laisserait « plus haut historique : (vide) le
    12/03/2024 » — une date qui date un nombre absent. Une demi-donnee est plus
    trompeuse qu'aucune.
    """
    plafond = PLAFOND_EXTREMES if plafond is None else plafond
    n_paires = n_atl = n_ath = n_orphelines = 0
    for rec in items:
        # 1) le plafond, cote par cote
        if _hors_plafond(rec.get("atl"), plafond):
            rec["atl"] = rec["atl_date"] = ""
            n_atl += 1
        if _hors_plafond(rec.get("ath"), plafond):
            rec["ath"] = rec["ath_date"] = ""
            n_ath += 1
        # 2) l'ordre, sur ce qui reste
        if _paire_corrompue(rec):
            rec["atl"] = rec["ath"] = rec["atl_date"] = rec["ath_date"] = ""
            n_paires += 1
        # 3) 🕳️ LES DATES ORPHELINES **DEJA DANS LA SOURCE** (03/08/2026).
        # ⭐⭐ CE GARDE-FOU AVAIT ETE ECRIT POUR NE PAS EN CREER, JAMAIS POUR
        # EN ENLEVER. Sa docstring dit depuis le 22/07 qu'une date sans sa
        # valeur est « plus trompeuse qu'aucune » — et pendant ce temps 256
        # lignes du Sheet (98 `atl_date`, 158 `ath_date`) en portaient une,
        # arrivees par un autre chemin, et traversaient l'export intactes.
        # ⛔ Un controle qui ne regarde que SES propres sorties ne voit pas ce
        # qui entre deja abime. Cette passe balaie TOUTES les lignes, pas
        # seulement celles que les deux precedentes ont touchees.
        # ⚠️ ASYMETRIQUE, ET C'EST VOULU : une VALEUR sans date reste utile
        # (« plus-bas 12 », on ignore quand) ; une DATE sans valeur ne date
        # rien. On ne vide donc que le second cas.
        for _v, _d in (("atl", "atl_date"), ("ath", "ath_date")):
            if not str(rec.get(_v) or "").strip() and str(rec.get(_d) or "").strip():
                rec[_d] = ""
                n_orphelines += 1
    return n_paires, n_atl, n_ath, n_orphelines


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

    # 🔎 LES DIVERGENCES, MESUREES AVANT LA FUSION — apres, la chaine a gagne
    # et l'ecart a disparu. ⭐ MESURER AVANT DE REPARER.
    # ⛔ Non bloquant par construction : ce bloc INFORME, il ne decide rien.
    # Ce qui bloque, c'est `verifier_churn` (l'ampleur) et `valider` (les
    # lignes). Un troisieme veto ici ferait echouer l'export le jour ou VeVe
    # corrige une rarete — c'est-a-dire le jour ou tout fonctionne.
    try:
        d = ID.comparer_divergences(avant, chaine, ID.charger_arbitrees())
        print(ID.rapport_divergences(d))
    except Exception as exc:                          # noqa: BLE001
        print(f"divergences : rapport indisponible ({exc}) — export poursuivi.")

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

    # 🛡️ Assainissement des extremes, JUSTE AVANT l'ecriture : apres l'identite
    # chaine (qui ne touche pas aux prix) et apres le garde-fou de volumetrie.
    n_corrompus, n_atl_haut, n_ath_haut, n_orphelines = _assainir_extremes(items)
    if n_orphelines:
        print(f"  🕳️ {n_orphelines} date(s) d'extreme SANS sa valeur, deja dans "
              f"la source — vide(s). Une date qui date un nombre absent est "
              f"pire qu'une date manquante.", file=sys.stderr)
    if PLAFOND_EXTREMES <= 0:
        print("  🎪 plafond de vraisemblance DESARME "
              "(CATALOG_PLAFOND_EXTREMES=0) — les prix trolls partent tels "
              "quels vers le site.", file=sys.stderr)
    elif n_atl_haut or n_ath_haut:
        pct = 100.0 * (n_atl_haut + n_ath_haut) / max(len(items), 1)
        print(f"  🎪 plafond {PLAFOND_EXTREMES:,.0f} $ : {n_ath_haut} ath et "
              f"{n_atl_haut} atl au-dessus ({pct:.1f} % des valeurs) — vides "
              f"AVEC leur date. ⭐ Ce ne sont pas des corruptions : ce sont des "
              f"prix DEMANDES par des vendeurs (9 999 999, 1 234 567…). Rien a "
              f"reparer en amont, le tracker dit vrai.", file=sys.stderr)
    if n_corrompus:
        # ⭐ Un zero qui ne dit pas POURQUOI il est zero est le defaut qu'on
        # traque partout : on COMPTE ce qu'on retient, et on le dit fort.
        pct = 100.0 * n_corrompus / max(len(items), 1)
        print(f"  🛡️ {n_corrompus} paire(s) ATL/ATH incoherente(s) ({pct:.1f} %) "
              f"— atl > ath, decimales FR x100 dans le Sheet. Exportees VIDES "
              f"avec leurs dates. La reparation se fait dans le Sheet "
              f"(repare_atl_ath.py), pas ici.", file=sys.stderr)

    with gzip.open(out, "wt", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=entete, extrasaction="ignore")
        w.writeheader()
        w.writerows(items)
    with_floor = sum(1 for i in items if i.get("floor"))
    print(f"✅ {out} : {len(items)} items ({with_floor} avec floor).")


if __name__ == "__main__":
    main()
