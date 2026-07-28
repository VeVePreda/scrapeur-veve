# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/export_elements_v3.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier depose au
# mauvais endroit ne provoque aucune erreur : il dort.

"""🌉 LE PONT v3 — elements.csv fabrique depuis la CHAINE (CollectChain).

Suite du spike GO-catalogue (23/07). L'IDENTITE du catalogue vient de la
metadata on-chain d'un transfert (`total.token_instance.metadata`), pas du
tracker communautaire :

    name, category, rarity, edition_type, supply, brand, licensor  <- CHAINE

Ce que la chaine NE porte PAS reste OFF-CHAIN et est REPORTE de l'export
officiel (data/elements.csv) tel quel — donc identique, donc 0 ecart au
comparateur :

    series_uuid, first_public, listings, note, atl, atl_date, ath, ath_date

    (spike : series_uuid absent de la chaine ; first_public = first_available_edition
     un NUMERO, pas la dropDate ; aucun prix on-chain.)

Ce module ecrit `data/elements_v3.csv` et NE TOUCHE PAS a data/elements.csv.
La bascule se juge au comparateur (scraper.compare_elements, pilote par
ELEMENTS_V2=data/elements_v3.csv) : identite a 0 sur plusieurs jours, comme le
pont elements. export_elements.py (v1) et export_elements_v2.py (tracker)
restent en repli.

En-tete : les 16 colonnes de v1/v2 OCTET POUR OCTET, puis deux colonnes AJOUTEES
EN FIN — `series` (28/07, la serie on-chain, qui commande les adresses des sites)
et `source` (28/07, `chaine`|`tracker`|vide=inconnu, la provenance de la ligne).
Ajouter en fin, et jamais au milieu : `reattacher_offchain` indexe par POSITION,
et `compare_elements` lit par NOM — il ignore donc les deux nouvelles.

--- ALIMENTATION ---
La metadata catalogue n'est PAS dans l'archive des transferts (schema reduit).
v3 doit la MOISSONNER en direct : un echantillon de metadata (le plus recent)
par veve_uuid. La moisson pleine (~26 800 types) = un run GitHub, comme tout
collecteur (le sandbox ne fait que des sondes ciblees). `collapse()` accepte
n'importe quel iterable de transferts bruts (API live, JSONL moissonne...).
"""

from __future__ import annotations

import csv
import gzip
import os
import re
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Les 16 premieres colonnes = l'en-tete v1/v2, inchange. Puis les ajouts EN FIN.
ENTETE = ["veve_uuid", "series_uuid", "name", "category", "rarity",
          "edition_type", "supply", "first_public", "listings", "note",
          "brand", "licensor", "atl", "atl_date", "ath", "ath_date",
          # 🆕 17e colonne (28/07/2026) — LA SERIE ON-CHAIN.
          # `catalogue_from_instance` la calculait deja (`md.series`) mais
          # l'export la JETAIT : elle ne servait qu'au MAX-par-serie des comics.
          # Or c'est LA colonne qui commande les adresses des 15 sites
          # (/comics/<slug(serie)>/<rarete>/). Sans elle, pipeline 2 ne peut pas
          # basculer. Ajoutee EN FIN : les index de `reattacher_offchain` et
          # l'ordre des 16 premieres colonnes ne bougent pas d'un octet, et
          # `compare_elements` lit par NOM (DictReader) — il l'ignore.
          "series",
          # 🆕 18e colonne (28/07/2026) — LA PROVENANCE DE LA LIGNE.
          # Sans elle, une fois `combler_depuis_officiel` passe, plus RIEN ne
          # distingue une ligne moissonnee sur la chaine d'une ligne recopiee du
          # tracker. Or la doctrine du 28/07 en depend entierement : la chaine
          # fait autorite Y COMPRIS PAR SON SILENCE, mais seulement sur les
          # objets qu'elle a VUS. (Cas reel : `Robocop: Jetpack Edition` portait
          # un `edition_type=FE` FAUX au tracker ; la chaine, elle, ne lui en
          # donnait aucun — et la regle « une valeur vide ne remplace jamais »
          # a conserve l'erreur, faute de savoir que la chaine l'avait vu.)
          # Ajoutee EN FIN, pour la meme raison que `series` : les 17 premieres
          # colonnes ne bougent pas d'un octet.
          "source"]

# Le vocabulaire de `source` — declare ici, nulle part ailleurs.
#   "chaine"  : la ligne SORT de la moisson CollectChain de ce run.
#   "tracker" : la ligne a ete recopiee de l'officiel par `combler_depuis_officiel`.
#   ""        : INCONNU. Ligne heritee d'une graine ecrite AVANT le 28/07/2026 :
#               sa provenance n'est plus reconstituable a posteriori, et on ne la
#               DEVINE PAS (⭐ un trou n'est pas une information).
SRC_CHAINE = "chaine"
SRC_TRACKER = "tracker"
SRC_INCONNU = ""
VOCAB_SOURCE = (SRC_CHAINE, SRC_TRACKER, SRC_INCONNU)

# Table de RATTRAPAGE de la provenance, etablie le 28/07/2026 (cf.
# `appliquer_backfill_source`). Un INSTANTANE, pas une regle : elle ne porte que
# les 7 794 lignes qui etaient INCONNUES apres le run #14, et rien d'autre.
BACKFILL_SOURCE = os.environ.get("ELEMENTS_V3_BACKFILL_SOURCE",
                                 "data/source_backfill_2026-07-28.csv.gz")

CSV_V3 = os.environ.get("ELEMENTS_V3", "data/elements_v3.csv")
CSV_OFFICIEL = os.environ.get("ELEMENTS_CSV", "data/elements.csv")
# Etat de reprise (mode profond) : curseur de pagination + flag balayage complet.
STATE_V3 = os.environ.get("ELEMENTS_V3_STATE", "data/elements_v3_state.json")
SUPPLY_MAX = int(os.environ.get("ELEMENTS_SUPPLY_MAX", "0"))   # 0 = tout

# Les 8 colonnes OFF-CHAIN reportees de l'officiel (cf. docstring).
OFFCHAIN_COLS = ["series_uuid", "first_public", "listings", "note",
                 "atl", "atl_date", "ath", "ath_date"]

# `collectible_type_image.<veve_uuid>` ou `comic_cover.<veve_uuid>` — le 1er uuid
# apres le prefixe EST le veve_uuid du catalogue (le 2e n'est PAS le series_uuid,
# verifie 23/07 : il differe du series_uuid officiel -> series_uuid reste off-chain).
_UUID_RE = re.compile(
    r"(collectible_type_image|comic_cover)\."
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.I,
)


def _norm_rarity(r: Any) -> str:
    """'Ultra Rare' -> 'ULTRA_RARE' ; 'Rare' -> 'RARE' (format de l'officiel)."""
    s = str(r or "").strip()
    return re.sub(r"[\s\-]+", "_", s).upper()


def _num(x) -> int:
    try:
        return int(float(str(x).replace(",", ".").replace(" ", "") or 0))
    except (TypeError, ValueError):
        return 0


def catalogue_from_instance(inst: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Un `token_instance` -> les champs catalogue tires de la CHAINE.

    Retourne None si l'instance n'est pas rattachable (pas de veve_uuid ET pas
    de metadata exploitable). category deduite de l'URL image, sinon des cles
    de metadata (comics : comicNumber/artists ; collectibles : editionType)."""
    if not isinstance(inst, dict):
        return None
    md = inst.get("metadata") or {}
    if not isinstance(md, dict):
        md = {}
    img = inst.get("image_url") or inst.get("media_url") or ""
    m = _UUID_RE.search(img)
    if m:
        cat = "collectible" if m.group(1).lower().startswith("collectible") \
            else "comic"
        uuid = m.group(2).lower()
    else:
        # Repli : deviner la categorie par les cles de metadata (uuid inconnu).
        if any(k in md for k in ("comicNumber", "coverArtists", "artists")):
            cat, uuid = "comic", ""
        elif any(k in md for k in ("editionType", "rarity")):
            cat, uuid = "collectible", ""
        else:
            return None
    if not uuid and not md:
        return None

    rarity = _norm_rarity(md.get("rarity"))
    total_ed = _num(md.get("totalEditions"))
    series = str(md.get("series") or "").strip()

    if cat == "comic":
        comic_no = str(md.get("comicNumber") or "").strip()
        start_year = str(md.get("startYear") or "").strip()
        # name = "{serie} #{numero} ({annee})" (calibre sur l'officiel 23/07).
        # ⭐ SANS NUMERO, PAS DE `#` (28/07/2026). Composer `#` avec un numero
        # vide fabriquait 76 noms comme 'DuckTales # (2024)'. Le `#` est un
        # SEPARATEUR : sans ce qu'il separe, il ne veut plus rien dire.
        name = f"{series} #{comic_no}" if comic_no else series
        if start_year:
            name = f"{name} ({start_year})"
        edition_type = comic_no                  # comics : edition_type = comicNumber
        brand = series                           # comics : brand = la serie
        licensor = str(md.get("publisher") or "").strip()  # comics : licensor = publisher
    else:
        name = str(md.get("name") or "").strip()
        et = str(md.get("editionType") or "").strip()
        edition_type = "" if et in ("0", "0.0") else et.upper()
        brand = str(md.get("brand") or "").strip()
        licensor = str(md.get("licensor") or "").strip()

    return {
        "veve_uuid": uuid,
        "category": cat,
        "name": name,
        "rarity": rarity,
        "edition_type": edition_type,
        "supply": total_ed,
        "brand": brand,
        "licensor": licensor,
        "series": series,       # sert au MAX-par-serie des comics
    }


def _order(item: Dict[str, Any]) -> Tuple[int, int]:
    """Cle de recence d'un transfert brut : (block, log_index)."""
    b = item.get("block_number")
    b = b if isinstance(b, int) else _num(b)
    li = item.get("log_index")
    li = li if isinstance(li, int) else _num(li)
    return (b, li)


def collapse(transfers: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Iterable de transferts BRUTS (API) -> {veve_uuid: catalogue le plus recent}.

    « Derniere metadata par item » : si un item reapparait, on garde celle du
    transfert au (block, log_index) le plus GRAND (metadata la plus a jour)."""
    best: Dict[str, Dict[str, Any]] = {}
    best_ord: Dict[str, Tuple[int, int]] = {}
    for t in transfers:
        inst = (((t.get("total") or {}).get("token_instance")) or {})
        cat = catalogue_from_instance(inst)
        if not cat or not cat["veve_uuid"]:
            continue
        uid = cat["veve_uuid"]
        o = _order(t)
        if uid not in best or o >= best_ord[uid]:
            best[uid] = cat
            best_ord[uid] = o
    return best


def lire_officiel(chemin: str) -> Dict[str, Dict[str, str]]:
    """{veve_uuid: ligne officielle} — source des colonnes OFF-CHAIN reportees."""
    out: Dict[str, Dict[str, str]] = {}
    if not os.path.exists(chemin):
        return out
    with open(chemin, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            uid = (r.get("veve_uuid") or "").strip()
            if uid:
                out[uid] = r
    return out


def construire_v3(catalogue: Dict[str, Dict[str, Any]],
                  officiel: Dict[str, Dict[str, str]]) -> List[List]:
    """Le catalogue on-chain + les colonnes off-chain reportees -> lignes ENTETE."""
    # ⭐ Tirage d'un COMIC = MAX par SERIE (comme v1/v2). CLE DE GROUPE = le
    # `series_uuid` OFFICIEL qu'on reporte deja (fin), avec repli sur la chaine
    # de serie on-chain. Grouper sur la chaine `series` seule SUR-AGREGEAIT
    # (plusieurs series_uuid partagent un meme libelle -> MAX gonfle : 30000 vs
    # 7500, cf. 1er rapport 23/07). La cle officielle recolle au decoupage v1.
    def _serie_key(uid: str, c: Dict[str, Any]) -> str:
        su = (officiel.get(uid, {}).get("series_uuid") or "").strip()
        return su or ("~" + c["series"])       # ~ = repli libelle si hors officiel

    max_par_serie: Dict[str, int] = {}
    for uid, c in catalogue.items():
        if c["category"] == "comic" and c["supply"]:
            k = _serie_key(uid, c)
            if k not in ("", "~"):
                max_par_serie[k] = max(max_par_serie.get(k, 0), c["supply"])

    rows: List[List] = []
    for uid, c in catalogue.items():
        off = officiel.get(uid, {})
        if c["category"] == "comic":
            supply = max_par_serie.get(_serie_key(uid, c), c["supply"])
        else:
            supply = c["supply"]
        if SUPPLY_MAX and supply and supply > SUPPLY_MAX:
            continue
        rows.append([
            uid,
            (off.get("series_uuid") or "").strip(),   # OFF-CHAIN reporte
            c["name"],
            c["category"],
            c["rarity"],
            c["edition_type"],
            supply if supply else "",
            (off.get("first_public") or "").strip(),  # OFF-CHAIN reporte
            (off.get("listings") or "").strip(),       # OFF-CHAIN reporte
            (off.get("note") or "").strip(),           # OFF-CHAIN reporte
            c["brand"],
            c["licensor"],
            (off.get("atl") or "").strip(),            # OFF-CHAIN reporte
            (off.get("atl_date") or "").strip(),
            (off.get("ath") or "").strip(),
            (off.get("ath_date") or "").strip(),
            c["series"],                               # 🆕 CHAINE
            SRC_CHAINE,                                # 🆕 provenance : moisson
        ])
    rows.sort(key=lambda l: (l[3], l[6] if l[6] != "" else 0, l[2]))
    return rows


def combler_series(rows: List[List]) -> int:
    """Remplit `series` la ou elle manque, SANS remoissonner. Rend le nb rempli.

    Pourquoi c'est necessaire : les lignes venues d'une GRAINE ecrite avant le
    28/07/2026, ou reprises du tracker par `combler_depuis_officiel`, n'ont
    aucune serie. Sans ce comblage il faudrait une moisson COMPLETE (~2 h 31)
    juste pour repeupler une colonne — alors que la couverture chaine est deja
    a 99,4 %.

    REGLE, et sa preuve :
      * COMIC -> `series = brand`. Ce n'est pas une approximation : dans
        `catalogue_from_instance`, `brand` EST affecte depuis la meme variable
        `series` (`brand = series`). Les deux colonnes portent le meme texte.
      * COLLECTIBLE -> on ne devine RIEN, on laisse vide. `brand` y vaut
        `md.brand`, qui n'est PAS la serie : s'en servir deplacerait 92,4 % des
        adresses de collectibles pour rien (mesure du 28/07). Une valeur vide
        laisse le consommateur retomber sur le Sheet — dont la serie coincide
        avec la chaine a 100 % pour les collectibles (mesure du 28/07).

    ⭐ Un trou n'est pas une information : on ne comble que ce qu'on peut PROUVER.
    """
    i_cat, i_brand, i_ser = (ENTETE.index("category"), ENTETE.index("brand"),
                             ENTETE.index("series"))
    n = 0
    for r in rows:
        while len(r) < len(ENTETE):        # ligne d'une graine plus ancienne
            r.append("")
        if not (r[i_ser] or "").strip() and (r[i_cat] or "").strip() == "comic":
            b = (r[i_brand] or "").strip()
            if b:
                r[i_ser] = b
                n += 1
    return n


# Un `#` que RIEN ne suit (espace ou fin de chaine) : le separateur orphelin.
_HASH_ORPHELIN = re.compile(r"\s*#(?=\s|$)")


def corriger_hash_orphelin(rows: List[List]) -> int:
    """Retire le `#` sans numero des noms de comics. Rend le nb corrige.

    `catalogue_from_instance` compose `{serie} #{numero} ({annee})`. Quand la
    chaine ne porte pas de `comicNumber`, le `#` restait quand meme : 76 noms
    comme 'DuckTales # (2024)' (52 libelles distincts) au 28/07/2026.

    Pourquoi une correction ICI et pas seulement a la composition : les lignes
    deja ecrites viennent de la GRAINE. Sans ce rattrapage, il faudrait une
    moisson complete — qu'on sait desormais hors de portee (cf. `integral`).

    ⚠️ CE QUE CE CORRECTIF NE CHANGE PAS — les ADRESSES. La vraie `slugify` des
    sites reduit `[^a-z0-9]+` a un seul tiret : 'DuckTales # (2024)' donne deja
    `ducktales-2024`, exactement comme la version corrigee. Le `duck-tales--2024`
    que je redoutais n'existe pas. C'est un defaut d'AFFICHAGE (cartes Discord,
    titres des sites, newsletters), pas d'URL. Verifie dans `dataset.mjs`.

    ⛔ On ne touche QUE le `#` orphelin : un `#` suivi d'un numero est l'ecriture
    normale d'un comic et ne bouge pas d'un octet.
    """
    i_cat, i_nom = ENTETE.index("category"), ENTETE.index("name")
    n = 0
    for r in rows:
        if (r[i_cat] or "").strip() != "comic":
            continue
        nom = r[i_nom] or ""
        if not _HASH_ORPHELIN.search(nom):
            continue
        corrige = re.sub(r"\s{2,}", " ", _HASH_ORPHELIN.sub("", nom)).strip()
        if corrige and corrige != nom:
            r[i_nom] = corrige
            n += 1
    return n


def compter_sources(rows: List[List]) -> Dict[str, int]:
    """{source: nb} sur les lignes. Rend la couverture chaine MESURABLE.

    ⭐ Pourquoi c'est ici et pas dans un rapport separe : jusqu'au 28/07/2026 la
    couverture chaine ne pouvait qu'etre ESTIMEE par une empreinte indirecte (les
    doubles espaces des noms du tracker). Un chiffre qu'on estime est un chiffre
    qu'on finit par croire. Desormais chaque run l'IMPRIME, exactement.
    """
    i_src = ENTETE.index("source")
    out: Dict[str, int] = {}
    for r in rows:
        v = (r[i_src] if len(r) > i_src else "") or SRC_INCONNU
        out[v] = out.get(v, 0) + 1
    return out


def valider_sources(rows: List[List]) -> None:
    """Garde-fou : aucune valeur de `source` hors vocabulaire ne sort d'ici.

    Une provenance inventee serait pire que pas de provenance : c'est elle qui
    autorisera la chaine a EFFACER un champ du tracker (autorite du silence).
    """
    hors = {s for s in compter_sources(rows) if s not in VOCAB_SOURCE}
    if hors:
        raise ValueError(
            f"source hors vocabulaire {sorted(hors)} — attendu {VOCAB_SOURCE}.")


def ecrire(rows: List[List], chemin: str) -> None:
    # Point de passage UNIQUE de toutes les ecritures (flush de secours compris)
    # : c'est ici que le comblage de serie s'applique, pour qu'aucun chemin de
    # code ne puisse produire un CSV a la serie trouee.
    n = combler_series(rows)
    if n:
        print(f"  serie : {n} comic(s) completes depuis brand "
              f"(meme texte on-chain, aucune moisson requise).", flush=True)
    h = corriger_hash_orphelin(rows)
    if h:
        print(f"  nom : {h} comic(s) debarrasses d'un '#' sans numero "
              f"(separateur orphelin — affichage, pas adresse).", flush=True)
    # ⛔ On ne DEVINE aucune provenance ici : `combler_series` a deja allonge les
    # lignes courtes (graine < 18 colonnes) avec des "" — soit exactement
    # INCONNU, qui est la verite pour elles.
    valider_sources(rows)
    src = compter_sources(rows)
    print("  source : "
          + " · ".join(f"{k or 'inconnu'}={src.get(k, 0)}" for k in VOCAB_SOURCE)
          + f"  (total {len(rows)})", flush=True)
    os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
    with open(chemin, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(ENTETE)
        w.writerows(rows)


def charger_graine(chemin: str) -> Dict[str, List]:
    """La graine (CSV_V3 d'un run precedent) -> {veve_uuid: ligne ENTETE}.
    Chargee EN MEMOIRE avant la moisson : le flush de secours ecrase ensuite
    CSV_V3 avec la tranche courante, donc on ne peut plus la relire du disque."""
    out: Dict[str, List] = {}
    if not os.path.exists(chemin):
        return out
    with open(chemin, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            uid = (r.get("veve_uuid") or "").strip()
            if uid:
                out[uid] = [r.get(c, "") for c in ENTETE]
    return out


def fusion(rows: List[List], graine: Dict[str, List]) -> List[List]:
    """rows du run + lignes de la graine ABSENTES du run (types non revus) — on
    ne reperd JAMAIS un type. Le run courant fait foi pour un uuid revu."""
    vus = {r[0] for r in rows}
    out = list(rows) + [g for uid, g in graine.items() if uid not in vus]
    out.sort(key=lambda l: (l[3], _num(l[6]) if l[6] != "" else 0, l[2]))
    return out


def reattacher_offchain(rows: List[List],
                        officiel: Dict[str, Dict[str, str]]) -> List[List]:
    """Rattache le OFF-CHAIN (series_uuid, first_public, listings, note, atl/ath)
    depuis l'officiel FRAIS, pour CHAQUE ligne connue de l'officiel — quelle que
    soit sa provenance (chaine, graine, comblage). Indispensable apres un
    rapatriement d'un catalogue CHAINE-ONLY (off-chain vide) : sinon les lignes
    dormantes garderaient un off-chain vide et pollueraient le verdict d'identite.
    Sans officiel (ex. run astronema chaine-only) : no-op."""
    if not officiel:
        return rows
    idx = {c: ENTETE.index(c) for c in OFFCHAIN_COLS}
    for r in rows:
        o = officiel.get(r[0])
        if not o:
            continue
        for c in OFFCHAIN_COLS:
            r[idx[c]] = (o.get(c) or "").strip()
    return rows


def combler_depuis_officiel(rows: List[List],
                            officiel: Dict[str, Dict[str, str]]) -> List[List]:
    """COMPLETUDE : tout uuid de l'officiel (elements.csv) pas encore couvert par
    la chaine est repris TEL QUEL (tracker). elements_v3 est alors COMPLET des le
    1er run — chaine pour l'actif, tracker pour la traine DORMANTE (jamais tradee
    recemment). Les runs profonds convertissent progressivement la traine en
    chaine (le uuid passe alors dans `rows`, il fait foi). Auto-cicatrisant."""
    vus = {r[0] for r in rows}
    i_src = ENTETE.index("source")
    ajout = 0
    for uid, r in officiel.items():
        if uid in vus:
            continue
        ligne = [r.get(c, "") for c in ENTETE]
        # ⭐ MARQUAGE EXPLICITE, et non `r.get("source")` : l'officiel n'a pas
        # cette colonne, la recopie donnerait "" (INCONNU) et on perdrait
        # precisement l'information qu'on vient d'ajouter la colonne pour avoir.
        ligne[i_src] = SRC_TRACKER
        rows.append(ligne)
        ajout += 1
    if ajout:
        print(f"  completude : +{ajout} type(s) DORMANT(s) repris de l'officiel "
              f"(tracker) — catalogue complet ({len(rows)}).", flush=True)
    rows.sort(key=lambda l: (l[3], _num(l[6]) if l[6] != "" else 0, l[2]))
    return rows


def charger_backfill_source(chemin: str) -> Dict[str, str]:
    """{veve_uuid: source} de la table de rattrapage. {} si absente.

    Accepte .csv comme .csv.gz. DIT OU ELLE A CHERCHE quand elle ne trouve pas :
    un module qui reclame un fichier sans dire lequel a deja coute un 1er run.
    """
    if not os.path.exists(chemin):
        print(f"  backfill source : table absente ({os.path.abspath(chemin)}) — "
              f"aucun rattrapage, l'INCONNU reste INCONNU.", file=sys.stderr)
        return {}
    ouvre = gzip.open if chemin.endswith(".gz") else open
    out: Dict[str, str] = {}
    with ouvre(chemin, "rt", encoding="utf-8") as f:      # type: ignore[operator]
        for r in csv.DictReader(f):
            uid = (r.get("veve_uuid") or "").strip().lower()
            src = (r.get("source") or "").strip()
            if uid and src in (SRC_CHAINE, SRC_TRACKER):
                out[uid] = src
    return out


def appliquer_backfill_source(rows: List[List],
                              table: Dict[str, str]) -> Dict[str, int]:
    """Pose la provenance des lignes HERITEES depuis l'instantane du 28/07/2026.

    ── D'OU VIENT CETTE TABLE, ET POURQUOI ELLE EST FIABLE ──────────────────
    Le run #14 (mode `integral`) a prouve la provenance de 11 467 lignes en
    moissonnant 3 mois de chaine — puis il a tape le plafond de 20 000 pages.
    Descendre jusqu'a la genese CollectChain n'etait pas l'affaire d'un run :
    le versement de MIGRATION du 28/01/2026 pese a lui seul 12,05 MILLIONS de
    transferts (les autres mois : 121 000 a 756 000), soit ~236 000 pages. Une
    douzaine de dispatches pour re-apprendre ce qu'on sait deja.

    L'archive locale des transferts CollectChain repond a la meme question hors
    ligne — et le run #14 l'a VALIDEE, ligne a ligne :
      * aucune des 11 467 lignes prouvees `chaine` ne manque a l'archive, sauf
        222 drops posterieurs au 15/07 (sa date d'arret) : 0 contre-exemple ;
      * son angle mort (apres le 15/07) et l'ensemble a classer (rien depuis
        3 mois) NE SE RECOUVRENT PAS — c'est ce qui la rend valide ici, alors
        qu'elle ne l'etait pas pour classer les lignes recentes ;
      * l'invariant de composition (`name == "{brand} #{n} (annee)"`) echoue sur
        16 des 136 lignes que l'archive dit `tracker`, et sur 0 des 11 467
        prouvees `chaine`. Deux instruments independants, meme verdict.

    ── CE QUE CETTE FONCTION NE FAIT PAS ────────────────────────────────────
    ⛔ Elle n'EXTRAPOLE jamais : un uuid absent de la table reste INCONNU. La
    table est un instantane de 7 794 lignes precises, pas la regle « tout ce qui
    n'est pas dans l'archive est du tracker » — sinon un jour une graine
    restauree d'une vieille sauvegarde se ferait massivement estampiller.
    ⛔ Elle n'ECRASE jamais une provenance deja connue : la moisson fait foi.
    """
    i_src = ENTETE.index("source")
    n = {SRC_CHAINE: 0, SRC_TRACKER: 0}
    if not table:
        return n
    for r in rows:
        if (r[i_src] or "") != SRC_INCONNU:
            continue
        s = table.get((r[0] or "").strip().lower())
        if s:
            r[i_src] = s
            n[s] += 1
    return n


def balayage_integral(meta: Dict[str, Any], start_params: Any) -> bool:
    """Ce run a-t-il vu TOUTE la chaine ? La question qui autorise l'elimination.

    ⚠️ `swept` seul NE SUFFIT PAS, et c'est le piege : un run `profond` REPREND
    au curseur, donc il peut atteindre le bout de l'histoire — et sortir
    `swept=True` — en n'ayant balaye que le BAS. Le prendre pour un balayage
    integral marquerait `tracker` des milliers de lignes que la chaine connait.
    Il faut AUSSI etre parti du SOMMET (`start_params is None`).
    """
    return bool(meta.get("swept")) and start_params is None


def resoudre_source_inconnue(rows: List[List],
                             officiel: Dict[str, Dict[str, str]]) -> int:
    """Apres un balayage INTEGRAL parti du SOMMET : leve l'INCONNU par elimination.

    ⛔ A n'appeler QUE si la machine a prouve les deux conditions (cf. `main`) :
       `meta['swept']` (l'API n'avait plus de page) ET un depart du SOMMET
       (`start_params is None`). Un `profond` qui REPREND au curseur peut tres
       bien finir « swept » en n'ayant balaye que le BAS de l'histoire : croire
       son verdict marquerait `tracker` des milliers de lignes que la chaine
       connait parfaitement.

    Le raisonnement, une fois ces conditions tenues : si un balayage complet n'a
    PAS produit cet uuid, la chaine ne le connait pas ; s'il est par ailleurs
    dans l'officiel, sa ligne v3 vient donc du tracker. Un uuid inconnu des DEUX
    reste INCONNU — on ne comble jamais un trou par une supposition.
    """
    i_src = ENTETE.index("source")
    n = 0
    for r in rows:
        if (r[i_src] or "") == SRC_INCONNU and r[0] in officiel:
            r[i_src] = SRC_TRACKER
            n += 1
    return n


def lire_state(chemin: str) -> Dict[str, Any]:
    """Etat de reprise : {cursor, swept, oldest, ...} — {} si absent/illisible."""
    import json
    if not os.path.exists(chemin):
        return {}
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:                                          # noqa: BLE001
        return {}


def ecrire_state(chemin: str, state: Dict[str, Any]) -> None:
    import json
    os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(state, f)


def main() -> int:
    """Moissonne la metadata chaine, reporte l'off-chain, ecrit elements_v3.csv.

    La moisson pleine tourne en GitHub Actions (le sandbox ne joint pas l'API en
    volume). Ici on branche `fetch_transfers` de collectchain, qui pagine +
    reprend proprement ; ELEMENTS_V3_CUTOFF borne la profondeur du balayage."""
    try:
        from scraper import collectchain as cc
    except Exception as e:                                     # noqa: BLE001
        print(f"⛔ import collectchain impossible ({e}).", file=sys.stderr)
        return 2

    import datetime as _dt
    import time as _time
    # ── MODE ──────────────────────────────────────────────────────────────
    # 'tete'   : repart du sommet, arret sur couverture (plateau). Entretien
    #            quotidien : attrape les nouveaux drops, rafraichit la metadata.
    # 'profond': REPREND au curseur du state (descend plus bas sans re-scanner
    #            le haut), plateau DESARME. Repete jusqu'a swept -> univers COMPLET.
    # 'integral': part du SOMMET (comme 'tete') mais plateau DESARME et fenetre
    #            large — le seul run qui peut PROUVER la provenance des lignes
    #            heritees (cf. `balayage_integral`). Un mode nomme plutot que
    #            trois reglages a saisir a la main : c'est justement ce genre de
    #            saisie qui produit des runs verts mais faux.
    mode = os.environ.get("ELEMENTS_V3_MODE", "tete").strip().lower()
    profond = mode == "profond"
    integral_demande = mode == "integral"
    balaye_tout = profond or integral_demande
    state = lire_state(STATE_V3)
    start_params = None
    if profond and state.get("cursor") and not state.get("swept"):
        start_params = state["cursor"]
        print(f"  mode PROFOND : reprise au curseur du state "
              f"(deja descendu jusqu'a {state.get('oldest', '?')}).", flush=True)
    elif profond and state.get("swept"):
        print("  mode PROFOND : state deja 'swept' (univers complet balaye) — "
              "on repart du sommet pour rafraichir.", flush=True)

    # profond : fenetre large par defaut (on veut tout) + plateau desarme.
    # `... or default` : un env ABSENT *ou VIDE* (input workflow non renseigne)
    # retombe sur le defaut du mode — sinon int("") planterait.
    days = int(os.environ.get("ELEMENTS_V3_LOOKBACK_DAYS")
               or ("3650" if balaye_tout else "120"))
    cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=days)
    plateau = int(os.environ.get("ELEMENTS_V3_PLATEAU_PAGES")
                  or ("0" if balaye_tout else "300"))
    # ⭐ GARANTIE ANTI-TIMEOUT : budget-temps INTERNE < timeout du job GitHub
    # (300 min). On s'arrete PROPREMENT avant le couperet -> l'ecriture + l'upload
    # Release s'executent (sur un timeout GitHub, meme les steps `if: always()`
    # sont sautes). Le reste se recolte au dispatch suivant (accumulation).
    budget_min = int(os.environ.get("ELEMENTS_V3_TIME_BUDGET_MIN") or "240")
    deadline = _time.monotonic() + budget_min * 60 if budget_min > 0 else None
    flush_every = int(os.environ.get("ELEMENTS_V3_FLUSH_EVERY") or "200")

    # officiel + GRAINE charges AVANT la moisson. La graine en memoire est LA
    # reference d'accumulation : le flush ecrase ensuite CSV_V3 avec la tranche
    # courante, donc on ne peut plus la relire du disque (bug evite en profond).
    officiel = lire_officiel(CSV_OFFICIEL)
    accumule = os.environ.get("ELEMENTS_V3_ACCUMULATE", "").strip() in (
        "1", "true", "oui")
    graine = charger_graine(CSV_V3) if accumule else {}
    if graine:
        print(f"  graine chargee en memoire : {len(graine)} types (reference "
              f"d'accumulation).", flush=True)

    def _flush(best: Dict[str, Dict[str, Any]]) -> None:
        """Sauvegarde de secours : ecrit le CSV COMPLET (tranche courante FUSION
        graine) en cours de route -> meme une chute hors timeout ne perd rien."""
        try:
            partiel = construire_v3(best, officiel)
            if partiel:
                ecrire(fusion(partiel, graine), CSV_V3)
        except Exception as e:                                 # noqa: BLE001
            print(f"    (flush de secours ignore : {e})", file=sys.stderr)

    arret = "curseur/fin (plateau desarme)" if plateau == 0 \
        else f"couverture ({plateau} pages sans nouveau)"
    print(f"Moisson metadata chaine [{mode}] depuis {cutoff:%Y-%m-%d} · arret sur "
          f"{arret} ou budget-temps ({budget_min} min) · flush /{flush_every} "
          f"pages …", flush=True)

    catalogue, meta = harvest(cc, cutoff, plateau, deadline=deadline,
                              flush=_flush, flush_every=flush_every,
                              start_params=start_params)
    # tete : la tranche DOIT voir l'univers actif -> <50 = quelque chose a casse.
    # profond : une tranche est bornee par le budget, elle peut etre petite ;
    # on rejette seulement une tranche VIDE (API muette). L'accumulation + le
    # curseur completent le reste au fil des dispatches.
    seuil = 1 if profond else 50
    if len(catalogue) < seuil:
        print(f"⛔ moisson trop maigre ({len(catalogue)} types) — rien d'ecrit.",
              file=sys.stderr)
        return 3
    rows = construire_v3(catalogue, officiel)
    if not rows:
        print("⛔ 0 ligne — rien d'ecrit.", file=sys.stderr)
        return 3
    # ACCUMULATION : fusion avec la graine EN MEMOIRE (chargee avant le flush).
    # Les types d'un run precedent PAS revus cette fois sont conserves.
    if accumule:
        rows = fusion(rows, graine)
    # COMPLETUDE : combler la traine dormante depuis l'officiel (defaut ON —
    # ELEMENTS_V3_COMBLER_OFFICIEL=0 pour un run chaine-pur). Decision Preda 23/07 :
    # inutile de balayer jusqu'a 2021 pour les dormants, le tracker les porte.
    if os.environ.get("ELEMENTS_V3_COMBLER_OFFICIEL", "1").strip() != "0":
        rows = combler_depuis_officiel(rows, officiel)
    # OFF-CHAIN toujours frais depuis l'officiel (répare un catalogue chaîne-only
    # rapatrié dont l'off-chain serait vide). No-op si pas d'officiel (astronema).
    rows = reattacher_offchain(rows, officiel)

    # ── PROVENANCE, 1/2 : le RATTRAPAGE de l'herite (instantane du 28/07/2026).
    # Ne touche QUE les lignes encore INCONNUES, et seulement celles que la table
    # nomme. Idempotent : une fois posees, elles ne repassent plus ici.
    bf = appliquer_backfill_source(rows, charger_backfill_source(BACKFILL_SOURCE))
    if bf[SRC_CHAINE] or bf[SRC_TRACKER]:
        print(f"  backfill source : {bf[SRC_CHAINE]} ligne(s) heritee(s) posees "
              f"en 'chaine', {bf[SRC_TRACKER]} en 'tracker' (instantane du "
              f"28/07/2026, aucune extrapolation).", flush=True)

    # ── PROVENANCE, 2/2 : lever l'INCONNU restant, si la machine l'a prouve.
    # Les lignes heritees d'une graine ecrite avant le 28/07/2026 sont INCONNUES
    # et le restent, run apres run, tant qu'un balayage INTEGRAL parti du SOMMET
    # n'a pas tranche. Les deux conditions sont VERIFIEES ici, pas declarees par
    # l'operateur : `swept` (plus aucune page cote API) ET depart du sommet.
    # Un run tronque (budget-temps, plateau, plafond de pages) laisse donc
    # l'INCONNU tel quel — c'est le bon sens de la panne : on degrade vers « je
    # ne sais pas », jamais vers un `tracker` invente.
    integral = balayage_integral(meta, start_params)
    if integral and os.environ.get(
            "ELEMENTS_V3_RESOUDRE_SOURCE", "1").strip() != "0":
        n = resoudre_source_inconnue(rows, officiel)
        if n:
            print(f"  source : balayage INTEGRAL depuis le sommet -> {n} "
                  f"ligne(s) INCONNUE(s) tranchee(s) en 'tracker' (la chaine ne "
                  f"les a pas produites, l'officiel les porte).", flush=True)
    elif not integral:
        print("  source : balayage NON integral (ou reprise au curseur) — "
              "l'INCONNU herite reste INCONNU, rien n'est devine.", flush=True)

    ecrire(rows, CSV_V3)

    # ── STATE de reprise : curseur pour descendre plus bas au prochain profond.
    if profond:
        new_state = {
            "cursor": meta["cursor"],
            "swept": bool(meta["swept"]),
            "oldest": meta["oldest"] or state.get("oldest", ""),
            "pages_last": meta["pages"],
            # compteur de dispatches (garde-fou d'auto-relance cote workflow).
            "runs": int(state.get("runs", 0)) + 1,
            "updated": _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        }
        ecrire_state(STATE_V3, new_state)
        if meta["swept"]:
            print("  ✅ BALAYAGE INTEGRAL TERMINE (swept) — l'univers on-chain "
                  "est couvert. Passe en mode 'tete' pour l'entretien.", flush=True)
        else:
            print(f"  ↪ state sauve : curseur pose (descendu jusqu'a "
                  f"{new_state['oldest']}). Relancer en PROFOND continue plus "
                  f"bas.", flush=True)

    nc = sum(1 for r in rows if r[3] == "comic")
    print(f"🌉 v3 : {len(rows)} elements ({nc} comics, {len(rows) - nc} "
          f"collectibles) · +{meta['types']} vus ce run -> {CSV_V3}", flush=True)
    return 0


def harvest(cc, cutoff, plateau_pages: int = 300, deadline=None,
            flush=None, flush_every: int = 0, start_params=None
            ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """Pagine /transfers newest-first et COLLECTE la metadata catalogue au vol,
    avec des garde-fous pour ne jamais balayer des millions de lignes pour rien
    NI perdre une recolte sur un couperet :

      * REPRISE PAR CURSEUR : `start_params` = curseur d'ou REPRENDRE (mode
        profond) au lieu du sommet -> des dispatches successifs descendent PLUS
        BAS sans re-scanner le haut. None = repart du sommet.
      * arret sur COUVERTURE : si `plateau_pages` pages defilent sans AUCUN
        nouveau veve_uuid -> arret (0 = DESARME, pour un balayage integral).
      * arret sur BUDGET-TEMPS : `deadline` (time.monotonic) -> arret PROPRE
        avant le timeout du job.
      * flush de SECOURS tous les `flush_every` pages ; plafond dur
        `ELEMENTS_V3_MAX_PAGES` ; arret sur CUTOFF.

    Retourne (best, meta). meta = {cursor, swept, pages, oldest, types} :
      * `cursor` = curseur pour REPRENDRE plus bas au prochain dispatch (None si
        `swept`), pour ne pas re-scanner le sommet.
      * `swept` = True quand toute l'histoire est balayee (plus de page suivante).
    Journalise sa progression (sinon un run long semble plante)."""
    import time
    session = cc._session()
    params: Dict[str, Any] = dict(start_params) if start_params else {}
    pages = 0
    max_pages = int(os.environ.get("ELEMENTS_V3_MAX_PAGES") or "20000")
    best: Dict[str, Dict[str, Any]] = {}
    best_ord: Dict[str, Tuple[int, int]] = {}
    since_new = 0
    newest_date = ""
    swept = False
    last_nxt = start_params      # si 0 page traitee, on reprend au meme point
    oldest = ""
    while pages < max_pages:
        data = cc._get(session, cc.TRANSFERS_URL, params)
        items = data.get("items", [])
        if not items:
            swept = True
            print(f"  ✓ plus aucun transfert -> BALAYAGE COMPLET "
                  f"({len(best)} types).", flush=True)
            break
        new_this = 0
        stop = False
        for it in items:
            ts = cc._parse_ts(it.get("timestamp"))
            if ts is not None and ts < cutoff:
                stop = True
                break
            if not newest_date and it.get("timestamp"):
                newest_date = str(it["timestamp"])[:10]
            inst = (((it.get("total") or {}).get("token_instance")) or {})
            cat = catalogue_from_instance(inst)
            if not cat or not cat["veve_uuid"]:
                continue
            uid = cat["veve_uuid"]
            o = _order(it)
            if uid not in best:
                new_this += 1
            if uid not in best or o >= best_ord[uid]:
                best[uid] = cat
                best_ord[uid] = o
        pages += 1
        since_new = 0 if new_this else since_new + 1
        try:
            oldest = str(items[-1].get("timestamp"))[:10]
        except Exception:
            pass
        nxt = data.get("next_page_params")
        last_nxt = nxt                       # curseur de la page SUIVANTE
        if pages % 25 == 0:
            print(f"    … {pages} pages · {len(best)} types · "
                  f"{since_new} page(s) sans nouveau · jusqu'a {oldest}",
                  flush=True)
        if flush and flush_every and pages % flush_every == 0:
            flush(best)          # sauvegarde de secours du CSV partiel
        if stop:
            print(f"  ✓ cutoff atteint -> arret ({len(best)} types, "
                  f"{pages} pages).", flush=True)
            break
        if not nxt:
            swept = True
            print(f"  ✓ fin des transferts -> BALAYAGE COMPLET "
                  f"({len(best)} types, {pages} pages).", flush=True)
            break
        if plateau_pages and since_new >= plateau_pages:
            print(f"  ✓ couverture plafonnee : {plateau_pages} pages sans "
                  f"nouveau type -> arret ({len(best)} types).", flush=True)
            break
        if deadline is not None and time.monotonic() >= deadline:
            print(f"  ⏱️ budget-temps atteint -> arret PROPRE ({len(best)} "
                  f"types, {pages} pages). Reprise au curseur au prochain "
                  f"dispatch.", flush=True)
            break
        params = dict(nxt)
        time.sleep(cc.PAUSE_BETWEEN_PAGES)
    meta = {"cursor": None if swept else last_nxt, "swept": swept,
            "pages": pages, "oldest": oldest, "types": len(best)}
    return best, meta


if __name__ == "__main__":
    sys.exit(main())
