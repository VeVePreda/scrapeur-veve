# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/identite.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier depose au
# mauvais endroit ne provoque aucune erreur : il dort.

"""🪪 LE REFERENTIEL D'IDENTITE — un seul vocabulaire pour les 4 pipelines.

CONSTAT qui justifie ce module (mesure du 28/07/2026, sur les fichiers reels) :
quatre sources decrivent le meme univers et AUCUNE ne s'accorde.

    Sheet froid -> catalogue.csv.gz   kind 'Comic'      rarity 'COMMON'
    elements.csv (tracker v2)         kind 'comic'      rarity 'COMMON'
    veve.holders (DuckDB)             kind 'comic'      rarity 'Common'
    chaine elements_v3.csv            kind 'comic'      rarity 'COMMON'

    catalogue vs elements : 7 764 noms differents sur 18 926 (41,0 %),
                            100 % des comics, 0 collectible.
    holders  vs les deux  : 86,0 % (holders.name d'un comic = la SERIE).

Ce module ne collecte rien et n'ecrit rien. Il porte UNIQUEMENT :
  * le VOCABULAIRE canonique (declare, donc testable) ;
  * la NORMALISATION (un seul chemin de code, partage par les 2 pipelines) ;
  * la FUSION Sheet + chaine, avec `name_display` qui sauve les libelles
    editoriaux que seul le Sheet porte ;
  * les GARDE-FOUS, qui LEVENT une exception au lieu de rendre un catalogue
    silencieusement faux.

⭐ POURQUOI `kind` RESTE EN 'Comic' / 'Collectible'
La chaine dit 'comic'. Adopter les minuscules vers l'aval viderait
`outils/construire_figures.py` l. 248 (`if r['kind'] != 'Comic': continue`) et
casserait les cles de la fiche 🦊 (`scraper/stats_page.py` l. 1429-1447) — SANS
faire echouer un seul build. C'est le « defaut par repli ». Le referentiel
tranche donc une bonne fois : le vocabulaire de sortie est celui du CATALOGUE,
quelle que soit la source d'entree. `valider()` refuse tout le reste.

⭐ POURQUOI `name_display` EXISTE
Seul le Sheet distingue les variantes de couverture : `Daredevil #131 - Vintage
Variant` vs `Daredevil #131`. Mesure : 450 COMICS portent un suffixe editorial
que ni la chaine ni le tracker ne connaissent (les collectibles n'ont aucune
divergence de nom, la chaine porte deja leurs suffixes). Sans `name_display`,
ces 450 couvertures deviennent des doublons visuels.
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# LE VOCABULAIRE CANONIQUE — declare ici, nulle part ailleurs.
# ---------------------------------------------------------------------------

KIND_COMIC = "Comic"
KIND_COLLECTIBLE = "Collectible"
VOCAB_KIND: Tuple[str, ...] = (KIND_COMIC, KIND_COLLECTIBLE)

VOCAB_RARITY: Tuple[str, ...] = (
    "COMMON", "UNCOMMON", "RARE", "ULTRA_RARE", "SECRET_RARE", "ARTIST_PROOF",
)

# Les 7 colonnes que la chaine sait produire (cf. chantier v3 / COMPARE_ADOPTE).
COLS_CHAINE: Tuple[str, ...] = (
    "name", "kind", "rarity", "edition_type", "tirage", "brand", "licensor",
)

# `series` est traite a part : c'est la colonne qui commande les ADRESSES des
# sites, et c'est la ou Sheet et chaine divergent a 100 % sur les comics.
COL_SERIE = "series"


class IdentiteInvalide(RuntimeError):
    """Un garde-fou a saute. On refuse de publier un catalogue faux."""


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

_ESPACES = re.compile(r"\s+")


def nettoyer(v: object) -> str:
    """Ecrase les espaces multiples et les bords.

    Motif : `elements.csv` porte 2 835 doubles espaces
    (`'Immortal X-Men #16  (2022)'`) contre 49 dans `catalogue.csv.gz`. Deux
    libelles qui ne different que par un espace sont le MEME libelle, mais ils
    produisent deux cles de jointure et deux adresses differentes.
    """
    if v is None:
        return ""
    s = unicodedata.normalize("NFC", str(v))
    return _ESPACES.sub(" ", s).strip()


def normaliser_kind(v: object) -> str:
    """N'importe quelle graphie -> 'Comic' | 'Collectible' | ''.

    Accepte 'comic', 'Comic', 'COMIC', 'comics'... Tout ce qui contient
    'comic' est un comic ; tout ce qui contient 'collectible' est un
    collectible ; le reste rend '' (et `valider` le refusera).
    """
    s = nettoyer(v).lower()
    if not s:
        return ""
    if "comic" in s:
        return KIND_COMIC
    if "collectible" in s or "collectable" in s:
        return KIND_COLLECTIBLE
    return ""


def normaliser_rarity(v: object) -> str:
    """'Ultra Rare' / 'SECRET RARE' / 'ultra-rare' -> 'ULTRA_RARE'.

    ⚠️ La valeur hors norme `SECRET RARE` (espace, pas de souligne) existe
    VRAIMENT : 1 occurrence dans `catalogue.csv.gz` ET dans `elements.csv`.
    Elle produit aujourd'hui une cle de fiche 🦊 distincte de `SECRET_RARE`.
    """
    s = nettoyer(v).upper()
    if not s:
        return ""
    s = re.sub(r"[\s\-]+", "_", s)
    return s


def normaliser_edition_type(v: object) -> str:
    """Le tracker ecrit parfois 'ce'/'fa' en minuscules, et '0' pour 'rien'."""
    s = nettoyer(v)
    if s in ("0", "0.0"):
        return ""
    return s.upper() if re.fullmatch(r"[A-Za-z]{1,3}", s) else s


# ---------------------------------------------------------------------------
# name_display — sauver les libelles editoriaux du Sheet
# ---------------------------------------------------------------------------

# Un suffixe qui ressemble a un TITRE de comic ('#1 (2022)', 'Namor #1 (2020)')
# n'est pas un libelle editorial : c'est le vrai nom de l'oeuvre apres un
# prefixe de serie. On ne le traite pas comme une variante.
_RESSEMBLE_A_UN_TITRE = re.compile(r"#\s*\d|\(\s*\d{4}\s*\)")
_SUFFIXE = re.compile(r"\s[-–—]\s(?P<suf>[^-–—]+)\s*$")


def _jetons(s: str) -> set:
    return {m.lower() for m in re.findall(r"[0-9A-Za-z']+", s or "")}


def suffixe_editorial(nom_sheet: str, nom_canonique: str) -> str:
    """La part du libelle Sheet que le nom canonique ne dit pas.

    Rend '' si le Sheet n'ajoute rien. Trois refus explicites :
      1. pas de separateur ' - ' -> rien a extraire ;
      2. le suffixe ressemble a un titre ('#7 (2025)') -> ce n'est pas une
         variante, c'est l'oeuvre ;
      3. tous les mots du suffixe sont deja dans le nom canonique -> le
         canonique dit deja tout, ajouter serait bavard.
    """
    nom_sheet = nettoyer(nom_sheet)
    nom_canonique = nettoyer(nom_canonique)
    if not nom_sheet or not nom_canonique:
        return ""
    m = _SUFFIXE.search(nom_sheet)
    if not m:
        return ""
    suf = nettoyer(m.group("suf"))
    if not suf or _RESSEMBLE_A_UN_TITRE.search(suf):
        return ""
    if _jetons(suf) <= _jetons(nom_canonique):
        return ""
    return suf


def libelle_affichage(nom_canonique: str, nom_sheet: str) -> str:
    """Le libelle montre a l'humain : canonique + variante s'il y en a une."""
    nom_canonique = nettoyer(nom_canonique)
    suf = suffixe_editorial(nom_sheet, nom_canonique)
    return f"{nom_canonique} - {suf}" if suf else nom_canonique


# ---------------------------------------------------------------------------
# Fusion Sheet + chaine
# ---------------------------------------------------------------------------

def fusionner(sheet: Dict[str, object],
              chaine: Optional[Dict[str, object]] = None,
              *, adopter_serie: bool = True,
              arbitrage: Optional[Dict[str, dict]] = None) -> Dict[str, str]:
    """Une ligne Sheet (+ sa ligne chaine si connue) -> l'identite canonique.

    REGLES, dans l'ordre :
      * la chaine gagne sur les 7 colonnes d'identite, MAIS une valeur chaine
        VIDE ne remplace jamais une valeur Sheet existante (un trou on-chain ne
        doit pas effacer ce qu'on sait deja) ;
      * ⭐ SAUF pour un cas NOMMEMENT arbitre en sens inverse (`arbitrage`) —
        voir « LA CHAINE DIT L'HISTOIRE, VEVE DIT L'ETAT » plus bas ;
      * `series` suit la meme regle mais derriere son propre interrupteur :
        c'est la colonne qui deplace les ADRESSES des sites ;
      * `name_display` conserve la variante de couverture du Sheet ;
      * `release_date` et `store_price` ne sont PAS ici : la chaine ne les
        porte pas, ils restent au Sheet.
    """
    chaine = chaine or {}
    out: Dict[str, str] = {}

    def choisir(col: str, src_chaine: str) -> str:
        # ⭐ L'EXCEPTION SE LIT AVANT LA REGLE, et elle est NOMINATIVE : elle ne
        # vaut que pour un uuid et une colonne precis, jamais pour une famille.
        # ⛔ Tout ce qui n'est pas nomme retombe sur « la chaine gagne » — un
        # arbitrage absent, illisible ou muet ne change RIEN.
        cas = (arbitrage or {}).get(col) or {}
        if cas.get("gagnant") == "sheet":
            v_sh = nettoyer(sheet.get(col))
            if v_sh:
                return v_sh
        v_ch = nettoyer(chaine.get(src_chaine))
        return v_ch if v_ch else nettoyer(sheet.get(col))

    nom_sheet = nettoyer(sheet.get("name"))
    nom = choisir("name", "name")

    out["name"] = nom
    out["name_display"] = libelle_affichage(nom, nom_sheet)
    out["kind"] = normaliser_kind(
        nettoyer(chaine.get("category")) or sheet.get("kind"))
    out["rarity"] = normaliser_rarity(choisir("rarity", "rarity"))
    out["edition_type"] = normaliser_edition_type(
        choisir("edition_type", "edition_type"))
    out["tirage"] = choisir("tirage", "supply")
    out["brand"] = choisir("brand", "brand")
    out["licensor"] = choisir("licensor", "licensor")
    out[COL_SERIE] = (choisir(COL_SERIE, "series") if adopter_serie
                      else nettoyer(sheet.get(COL_SERIE)))
    return out


# ---------------------------------------------------------------------------
# LES GARDE-FOUS
# ---------------------------------------------------------------------------

def valider(lignes: List[Dict[str, str]], *,
            mini_total: int = 15_000,
            mini_par_type: Optional[Dict[str, int]] = None,
            cle: str = "uuid") -> None:
    """Leve `IdentiteInvalide` a la premiere anomalie. Ne rend rien.

    ⭐ `mini_par_type` est le garde-fou qui tue le « defaut par repli ». Un
    catalogue complet dont TOUS les `kind` seraient passes en minuscules a
    18 926 lignes : le seuil global ne bronche pas, `comics-par-annee.json`
    sort vide, et aucun build n'echoue. Compter PAR FAMILLE le voit.
    """
    if len(lignes) < mini_total:
        raise IdentiteInvalide(
            f"volumetrie : {len(lignes)} lignes < {mini_total} — lecture "
            f"incomplete ? On ne publie pas.")

    vus = set()
    par_type: Dict[str, int] = {}
    for i, r in enumerate(lignes):
        uid = nettoyer(r.get(cle))
        if not uid:
            raise IdentiteInvalide(f"ligne {i} : identifiant '{cle}' vide.")
        if uid in vus:
            raise IdentiteInvalide(f"identifiant en double : {uid}")
        vus.add(uid)

        k = r.get("kind")
        if k not in VOCAB_KIND:
            raise IdentiteInvalide(
                f"{uid} : kind {k!r} hors vocabulaire {VOCAB_KIND}. "
                f"C'est exactement ce qui viderait comics-par-annee.json "
                f"sans faire echouer le build.")
        par_type[k] = par_type.get(k, 0) + 1

        rr = r.get("rarity")
        if rr and rr not in VOCAB_RARITY:
            raise IdentiteInvalide(
                f"{uid} : rarity {rr!r} hors vocabulaire {VOCAB_RARITY}.")

        nom = r.get("name") or ""
        if not nom.strip():
            raise IdentiteInvalide(f"{uid} : nom vide.")
        if "  " in nom or nom != nom.strip():
            raise IdentiteInvalide(
                f"{uid} : nom non nettoye {nom!r} — deux libelles qui ne "
                f"different que par un espace font deux adresses.")

    for k, seuil in (mini_par_type or {}).items():
        if par_type.get(k, 0) < seuil:
            raise IdentiteInvalide(
                f"famille {k!r} : {par_type.get(k, 0)} lignes < {seuil}. "
                f"Une famille entiere a disparu du catalogue.")


def verifier_churn(avant: Dict[str, Dict[str, str]],
                   apres: Dict[str, Dict[str, str]],
                   plafonds: Dict[str, float],
                   *, autorise: bool = False) -> None:
    """Refuse un remaniement de masse non approuve.

    ⭐ NE PAS SUPPRIMER — ce garde-fou est ne d'une vraie erreur, la mienne,
    le 28/07/2026. En preparant ce module j'ai branche `veve.holders` comme
    substitut de la chaine. Or, pour un comic, `holders.name` vaut la SERIE
    (`The Amazing Spider-Man`) alors que la vraie chaine COMPOSE le libelle
    (`{series} #{numero} ({annee})`). Resultat : une fusion ou 84,8 % des noms
    s'ecrasaient sur leur nom de serie — un catalogue qui passait TOUS les
    autres garde-fous (vocabulaire bon, volumetrie bonne, familles pleines,
    aucun doublon) et qui etait pourtant inexploitable.

    Ce que ca prouve : la validite ligne a ligne ne dit RIEN de la sanite de
    l'ensemble. Une source degradee produit des lignes parfaitement valides.
    Seul un plafond sur l'AMPLEUR du changement le voit.

    `plafonds` = part MAXIMALE de lignes qui peut changer, par colonne
    (0.45 = 45 %). Depasser exige `autorise=True` — c'est-a-dire une decision
    humaine, ecrite, pas un run qui glisse.
    """
    communs = set(avant) & set(apres)
    if not communs:
        return
    depassements = []
    for col, plafond in plafonds.items():
        n = sum(1 for u in communs
                if (avant[u].get(col) or "") != (apres[u].get(col) or ""))
        part = n / len(communs)
        if part > plafond:
            ex = next((u for u in sorted(communs)
                       if (avant[u].get(col) or "") != (apres[u].get(col) or "")),
                      None)
            depassements.append(
                f"{col} : {n}/{len(communs)} lignes changent "
                f"({100 * part:.1f} % > plafond {100 * plafond:.0f} %)"
                + (f" — ex. {avant[ex].get(col)!r} -> {apres[ex].get(col)!r}"
                   if ex else ""))
    if depassements and not autorise:
        raise IdentiteInvalide(
            "remaniement de masse NON APPROUVE :\n  - "
            + "\n  - ".join(depassements)
            + "\n  Si c'est voulu, relancer en autorisant explicitement le "
              "churn. Si ce n'est pas voulu, la source d'identite est degradee.")


# ---------------------------------------------------------------------------
# 🔎 LES DIVERGENCES ARBITREES — le garde-fou demande par Preda le 05/08/2026
# ---------------------------------------------------------------------------
# « priorite a la chaine, ET une passe de verification VeVe a l'occasion,
#   garde-fou pour ceux deja connus. »
#
# ⭐⭐⭐ POURQUOI CE GARDE-FOU EXISTE, DIT PAR PREDA LUI-MEME : « Tiny Jones a
# ete droppe en SECRET_RARE mais VeVe a corrige en COMMON ». La chaine dit
# l'HISTOIRE (la rarete gravee au mint), le Sheet dit l'ETAT (ce que VeVe
# affiche aujourd'hui). LES DEUX SONT VRAIES, A DES MOMENTS DIFFERENTS.
# ⭐⭐ CE N'EST DONC PAS UNE DIVERGENCE, C'EST UNE CHRONOLOGIE — et aucun taux
# de concordance ne peut faire la difference : 99,96 % s'imprime pareil que la
# source ait tort ou que le temps ait passe.
#
# Consequence : on ne peut pas « corriger » ces cas, seulement les CONNAITRE.
# D'ou une table de cas ARBITRES, et trois etats au lieu de deux :
#
#     CONNUE    deja vue, deja tranchee        -> silencieuse (comptee)
#     NEUVE     jamais vue                     -> NOMMEE (a examiner)
#     RESORBEE  connue, mais les deux sources  -> NOMMEE (VeVe a rebouge,
#               sont de nouveau d'accord          ou la moisson a rattrape)
#
# ⭐⭐⭐ UN AVERTISSEMENT QUI SE DECLENCHE SUR LE CAS NORMAL EST DU BRUIT, ET LE
# BRUIT SE LIT COMME DU SILENCE. `rapport()` imprime « rarity 7 modifies » a
# CHAQUE run depuis le 28/07 : au bout d'une semaine plus personne ne le lit,
# et le jour ou ce sera 8 personne ne le verra.
#
# ⛔ CE GARDE-FOU NE VAUT QUE SUR LES COLONNES OU LA DIVERGENCE EST RARE
# (`rarity` 7 cas, `licensor` 75, `edition_type` 30). Sur `name` (~8 080),
# `brand` (~4 270) ou `series` (16 418), une table de cas connus ne dirait rien
# — c'est le PLAFOND DE CHURN qui les surveille, pas une liste.
# ⭐⭐ UN GARDE-FOU DE CAS CONNUS NE FONCTIONNE QUE LA OU LES CAS SONT RARES :
# ailleurs, la liste devient la donnee.
#
# ===========================================================================
# ⭐⭐⭐ LA CHAINE DIT L'HISTOIRE, VEVE DIT L'ETAT (mesure du 06/08/2026)
# ===========================================================================
# L'intuition ecrite plus haut — « droppe en SECRET_RARE, VeVe a corrige en
# COMMON » — etait une HYPOTHESE. Elle est desormais MESUREE : les 112 cas
# arbitres ont ete reposes a VeVe lui-meme, en direct.
#
#   ⛔ 86 sur 112 sont HORS DE PORTEE : ce sont des comics, et la liste
#      blanche refuse `rarity`, `licensor` et `editionType` sur
#      `publicComicType` (HTTP 400 sur les trois formulations essayees).
#      Pour eux il n'existe AUCUN tiers : le tracker EST le cote Sheet.
#   Sur les 26 restants :
#      edition_type  15/15  la chaine dit comme VeVe        -> arbitrage juste
#      rarity         2/4   ... et 2 fois VeVe dit comme le Sheet
#      licensor       0/7   VeVe dit comme le SHEET, jamais comme la chaine
#
# ⭐⭐ CE N'EST PAS « L'ARBITRAGE ETAIT FAUX ». Les deux valeurs sont vraies a
# des moments differents : la chaine grave le licencie AU MINT, VeVe affiche
# celui d'AUJOURD'HUI. Choisir la chaine, c'est choisir l'histoire — un choix
# legitime, et c'est celui du 05/08.
#
# 🔴 MAIS IL A UNE CONSEQUENCE QUE PERSONNE N'AVAIT MESUREE, ET ELLE SE VOIT
# SUR LE SITE : le catalogue publie du 05/08 porte **7 lignes
# « Cartel Entertainment, LLC » ET 6 lignes « Evoke Entertainment » pour la
# MEME franchise Creepshow**. La licence a change de mains en cours de serie,
# la chaine a donc raison LIGNE PAR LIGNE — et le catalogue se contredit.
# ⭐⭐⭐ **UNE REGLE VRAIE APPLIQUEE LIGNE PAR LIGNE PEUT PRODUIRE UN ENSEMBLE
# FAUX.** Un referentiel qui GROUPE (page licencie, filtre, classement) a
# besoin d'UN nom par franchise, pas du nom exact de chaque mint.
#
# D'ou `gagnant` dans la table : l'arbitrage cesse d'etre une regle de COLONNE
# pour devenir une decision de CAS. Il n'y a rien a inventer par defaut —
# absent, la chaine gagne comme avant.
#
# ⛔ CE QU'ON NE TOUCHE PAS, ET POURQUOI :
#   · les 62 cas ou le Sheet dit `UNKNOWN` — ce n'est pas une divergence,
#     c'est un TROU. N'importe quelle valeur bat `UNKNOWN`.
#   · les 5 « Marvel » (Sheet) vs « Star Wars » (chaine) — la chaine est ici
#     COHERENTE avec 316 autres lignes du catalogue, et « editeur » contre
#     « franchise » est une difference de DEFINITION.
#     ⭐⭐ UN ARBITRAGE DE VERACITE NE TRANCHE PAS UNE DIFFERENCE DE DEFINITION
#     (deja ecrit pour `veve_series_name`, vrai ici aussi).
#   · les 7 cas de `rarity` — la chronologie y est la BONNE lecture, et
#     l'ecart ne casse aucun regroupement.

DIVERGENCES_ARBITREES = os.environ.get("DIVERGENCES_ARBITREES",
                                       "data/divergences_arbitrees.json")

# Normalisation PAR COLONNE, la meme que celle de la mesure 3.1 — sinon on
# reouvrirait ici des divergences de pure forme (`SECRET RARE` vs
# `SECRET_RARE`, `#131` vs `131`) qui ne sont pas des divergences.
_NORME_DIV = {
    "rarity": lambda v: v.upper().replace(" ", "_"),
    "kind": lambda v: v.lower(),
    "edition_type": lambda v: v.lstrip("#"),
}


def _norme_div(col: str, v: object) -> str:
    v = nettoyer(v)
    f = _NORME_DIV.get(col)
    return f(v) if f else v


def charger_arbitrees(chemin: str = None) -> Dict[str, Dict[str, dict]]:
    """{uuid: {colonne: {sheet, chaine, nom}}} — {} si absent ou illisible.

    ⭐ Un fichier absent ne fait pas echouer l'export : il fait seulement que
    TOUTES les divergences seront rapportees comme NEUVES. Bruyant, jamais
    faux. ⛔ L'inverse — se taire faute de table — serait le pire des deux.
    """
    import json
    chemin = chemin or DIVERGENCES_ARBITREES
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f).get("cas", {}) or {}
    except (OSError, ValueError):
        return {}


def comparer_divergences(sheet: Dict[str, Dict[str, object]],
                         chaine: Dict[str, Dict[str, object]],
                         arbitrees: Dict[str, Dict[str, dict]],
                         colonnes: Iterable[str] = ("rarity", "licensor",
                                                    "edition_type", "kind",
                                                    "tirage"),
                         ) -> Dict[str, list]:
    """Range chaque divergence en CONNUE / NEUVE / RESORBEE.

    `sheet` et `chaine` sont indexes par uuid. On compare AVANT fusion : apres,
    la chaine a gagne et la divergence a disparu.
    ⭐ MESURER AVANT DE REPARER — un ecart se constate sur les deux sources
    telles qu'elles sont arrivees, pas sur le resultat de leur fusion.
    """
    src = {"rarity": "rarity", "licensor": "licensor",
           "edition_type": "edition_type", "kind": "category",
           "tirage": "supply"}
    dst = {"rarity": "rarity", "licensor": "licensor",
           "edition_type": "edition_type", "kind": "kind", "tirage": "tirage"}
    out = {"connues": [], "neuves": [], "resorbees": []}
    vues = set()
    for uid, ligne_sheet in sheet.items():
        ligne_ch = chaine.get(uid)
        if not ligne_ch:
            continue
        for col in colonnes:
            a = _norme_div(col, ligne_sheet.get(dst[col]))
            b = _norme_div(col, ligne_ch.get(src[col]))
            if not a or not b:
                continue          # un vide n'est pas un desaccord
            connue = (arbitrees.get(uid) or {}).get(col)
            if a == b:
                if connue:
                    out["resorbees"].append((uid, col, connue))
                continue
            vues.add((uid, col))
            cible = "connues" if connue else "neuves"
            out[cible].append((uid, col, nettoyer(ligne_sheet.get(dst[col])),
                               nettoyer(ligne_ch.get(src[col]))))
    return out


def rapport_divergences(d: Dict[str, list], *, exemples: int = 8) -> str:
    """Le texte du log. Les CONNUES se comptent, les autres se NOMMENT."""
    l = [f"divergences chaine/Sheet : {len(d['connues'])} connue(s) "
         f"(arbitrees, silencieuses) · {len(d['neuves'])} NEUVE(s) · "
         f"{len(d['resorbees'])} RESORBEE(s)"]
    if d["neuves"]:
        l.append("  🆕 NEUVES — jamais vues, a examiner :")
        for uid, col, a, b in d["neuves"][:exemples]:
            l.append(f"     {uid[:8]} {col:13s} Sheet={a!r} -> chaine={b!r}")
        if len(d["neuves"]) > exemples:
            l.append(f"     … et {len(d['neuves']) - exemples} autre(s)")
    if d["resorbees"]:
        l.append("  ♻️ RESORBEES — les deux sources sont de nouveau d'accord "
                 "(VeVe a rebouge, ou la moisson a rattrape) :")
        for uid, col, connue in d["resorbees"][:exemples]:
            l.append(f"     {uid[:8]} {col:13s} etait "
                     f"{connue.get('sheet')!r} vs {connue.get('chaine')!r}")
        if len(d["resorbees"]) > exemples:
            l.append(f"     … et {len(d['resorbees']) - exemples} autre(s)")
    return "\n".join(l)


def rapport(avant: Dict[str, Dict[str, str]],
            apres: Dict[str, Dict[str, str]],
            colonnes: Iterable[str] = ("name", "series", "kind", "rarity",
                                       "edition_type", "tirage", "brand",
                                       "licensor")) -> str:
    """Ce qui a change, colonne par colonne. Rien ne doit bouger en silence."""
    communs = set(avant) & set(apres)
    lignes = [f"identite : {len(avant)} avant · {len(apres)} apres · "
              f"{len(communs)} communs"]
    for c in colonnes:
        n = sum(1 for u in communs
                if (avant[u].get(c) or "") != (apres[u].get(c) or ""))
        if n:
            ex = next((u for u in sorted(communs)
                       if (avant[u].get(c) or "") != (apres[u].get(c) or "")),
                      None)
            detail = ""
            if ex:
                detail = (f"   ex. {avant[ex].get(c)!r} -> "
                          f"{apres[ex].get(c)!r}")
            lignes.append(f"  {c:14s} {n:6d} modifies "
                          f"({100 * n / max(len(communs), 1):5.1f} %){detail}")
        else:
            lignes.append(f"  {c:14s} {0:6d} modifies")
    return "\n".join(lignes)
