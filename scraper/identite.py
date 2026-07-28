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
              *, adopter_serie: bool = True) -> Dict[str, str]:
    """Une ligne Sheet (+ sa ligne chaine si connue) -> l'identite canonique.

    REGLES, dans l'ordre :
      * la chaine gagne sur les 7 colonnes d'identite, MAIS une valeur chaine
        VIDE ne remplace jamais une valeur Sheet existante (un trou on-chain ne
        doit pas effacer ce qu'on sait deja) ;
      * `series` suit la meme regle mais derriere son propre interrupteur :
        c'est la colonne qui deplace les ADRESSES des sites ;
      * `name_display` conserve la variante de couverture du Sheet ;
      * `release_date` et `store_price` ne sont PAS ici : la chaine ne les
        porte pas, ils restent au Sheet.
    """
    chaine = chaine or {}
    out: Dict[str, str] = {}

    def choisir(col: str, src_chaine: str) -> str:
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
