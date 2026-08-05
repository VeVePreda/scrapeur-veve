# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/burn_prevu.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""🔥 LA DATE DE BURN **CALCULEE** — zero requete, 30 jours d'avance.

POURQUOI CE MODULE EXISTE
-------------------------
Parce que la date de burn n'est PAS collectable. Sonde du 05/08/2026, faite en
direct sur `web.api.prod.veve.me/graphql` : **37 noms de champs** essayes sur
`publicComicType` (`burnDate`, `expiryDate`, `burnsAt`, `expiresAt`, `endDate`,
`leavingAt`, `availableUntil`, `saleEndDate`, …) — **tous HTTP 400**. Et pas sur
un item quelconque : sur `ce33b280-…` (The X-Men, 1963), qui a REELLEMENT brule
(`editionsBurnt` = 471, `totalIssued` 1 000 = 430 vendues + 99 retenues + 471
brulees). Un item qui a brule et dont le champ de burn est refuse : le champ
n'existe pas dans le schema, il n'est pas « absent sur cet item-la ».
⭐ La sonde est rejouable : `python3 outils/sonde_champ_burn.py`. Une absence
qu'on ne peut pas rejouer est une croyance.

L'archive ne peut pas repondre non plus : le supply invendu n'est **jamais
minte**, donc jamais on-chain. Les 52 657 `kind='burn'` de CollectChain sont des
burns d'UTILISATEURS sur de vieux comics (mediane **1 450 jours** apres la
sortie). ⭐⭐⭐ **UNE SOURCE QUI NE VOIT QUE CE QUI EST PARTI NE PEUT PAS DIRE CE
QUI EST RESTE** — deja ecrit pour le denominateur du sold out, vrai aussi pour
le feu.

Reste le calcul. Et il marche.

LA REGLE, ET CE QUE LA MESURE A CORRIGE
---------------------------------------
Regle donnee par Preda (05/08) : « les comics **hors mercredi** sortis **cette
annee** burnent leur invendu **a partir de 30 jours** ».

Mesure du 05/08 sur la population entiere — **164 comics 2026 hors mercredi**,
interroges un par un :

    108  PAS BRULE, J+30 largement depasse
     43  A BRULE
      9  SOLD OUT (rien a bruler)
      4  en attente (J+30 pas encore atteint)

⭐⭐⭐ **APPLIQUER J+30 A « 2026 HORS MERCREDI » AURAIT PRODUIT 108 FAUSSES DATES
DE BURN SUR 164 — DEUX TIERS.** La regle est vraie ; c'est sa POPULATION qui
etait mal decrite. Le jour de sortie et l'annee ne separent rien tout seuls.

CE QUI SEPARE VRAIMENT : LA PART RETENUE
----------------------------------------
    part retenue = withheldEditions / totalIssued

    ceux qui BRULENT       n= 43   min 9,9 %   mediane 11,4 %   max 13,4 %
    ceux qui NE BRULENT PAS n=108   min 2,0 %   mediane  2,0 %   max  2,0 %

**Aucun chevauchement. Zero exception sur 164.** Un seuil a 5 % separe les deux
familles avec une marge de 5 points de chaque cote — ce n'est pas un seuil
ajuste sur les donnees, c'est un fosse.

Les 108 a 2,0 % sont une ligne editoriale entiere (Bouncer, Before The Incal,
Basil & Victoria, Millennium, Gung-Ho, Metal Hurlant, Porcelain…) : VeVe garde
leur stock, indefiniment. Le plus vieux de l'echantillon a **14 mois** et n'a
toujours rien brule.

⭐⭐⭐ **LA REGLE NE SE CADRE PAS PAR UNE ANNEE, ELLE SE CADRE PAR UNE DONNEE.**
C'est ce qui rend ce module durable : il n'y a **ni annee en dur, ni variable
d'environnement, ni date de peremption**. Preda ne savait pas depuis quand la
pratique existe (« mars 2025 ? ») ; la mesure a rendu la question sans objet —
elle remonte a **juin 2024** au moins (Deadpool Kills the Marvel Universe, burns
constates), et le discriminant, lui, se lit dans la ligne.

⭐⭐ Et il etait **deja collecte** : `withheldEditions` est dans `COMIC_QUERY`
depuis toujours, et vit dans `supply_withheld`. Sixieme fois de suite que la
donnee manquante etait deja la, sous une autre forme.

LE MERCREDI RESTE EXCLU — ET LA MESURE LE CONFIRME
--------------------------------------------------
120 comics du mercredi 2026 sondes : **109 a 2,0 %**, aucun burn. Et les **3**
qui sont a 9,9 % n'ont **pas** brule non plus, dont deux tres au-dela de J+30
(Ultraman #10, sorti le 07/01, J+210 ; Ultraman #11, J+182). L'exclusion du
Comic Book Day n'est donc pas une precaution : c'est une condition.
⚠️ n=3 est mince. Si un comic du mercredi a 9,9 % venait a bruler, c'est cette
condition-la qui tomberait la premiere — et le banc le dira.

⛔ ON NE REUTILISE PAS `discord_drops.est_comic_du_mercredi` : elle est
debrayee par `DISCORD_SANS_COMIC_DAY`, un reglage d'ANNONCE. Une regle de
supply ne doit pas changer parce qu'on a modifie la mise en page d'un post.
⭐⭐ *Une fonction qui porte une politique ne se reutilise pas pour un fait.*

J+30 EST UN PLANCHER, PAS UNE DATE
-----------------------------------
Sur les 43 qui ont brule, le plus rapide l'a fait a **J+34**. Aucun avant J+30.
La colonne dit donc « **au plus tot le** », et c'est ce que doit afficher tout
ce qui la publie. ⭐⭐ *Annoncer une borne comme une date, c'est promettre une
precision qu'on n'a pas mesuree.*
✅ Confirmation directe : **The Amazing Spider-Man #546**, sorti le 02/07/2026
(jeudi, retenues 99/1 000 = 9,9 %) — J+30 = 01/08. Constate le 05/08 :
`editionsBurnt` = 152. Le feu a eu lieu dans la fenetre.
⏳ Et **#547**, sorti le 07/07, J+30 = **06/08** : 0 brule au 05/08. C'est le
temoin a regarder demain — il n'y a rien a coder pour le savoir.

CE QUE CE MODULE NE FAIT PAS
----------------------------
Il ne dit pas s'il RESTE quelque chose a bruler. `date_burn_prevue` ne depend
que de trois valeurs qui **ne bougent jamais** (sortie, tirage, retenues) : la
colonne est donc stable et recalculable a l'identique. Le volume invendu, lui,
est une mesure qui PERIME (`supply_circulation` fond le jour du feu) et porte
deja sa date, `supply_vu_le`.
⭐⭐ **UNE VALEUR STABLE ET UNE MESURE PERISSABLE NE SE RANGENT PAS DANS LA MEME
COLONNE** — sinon la premiere herite de la peremption de la seconde.
"""

from __future__ import annotations

import datetime as _dt
from typing import Optional

# Le Comic Book Day. 2 = mercredi (`datetime.weekday()`).
JOUR_COMIC_DAY = 2

# Le delai, en jours. PLANCHER : rien n'a brule avant J+34 dans la mesure.
DELAI_JOURS = 30

# La frontiere entre les deux familles. Mesuree, pas choisie : 2,0 % d'un cote,
# 9,9 % de l'autre, sur 164 comics et zero exception. 5 % tombe au milieu du
# fosse — a 4 % ou a 8 % le resultat serait identique, et c'est ce qui fait
# qu'il n'est pas ajuste sur l'echantillon.
SEUIL_RETENUES_PCT = 5.0


def _nombre(v) -> Optional[float]:
    """Un nombre, ou None. ⛔ None n'est PAS 0 : « je ne sais pas » et « zero »
    menent ici a des conclusions opposees (pas de date / pas de burn)."""
    if v is None or v == "":
        return None
    try:
        return float(str(v).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def jour_de_sortie(release_date) -> str:
    """`releaseDate` -> jour « YYYY-MM-DD », ou "" si illisible.

    ⚠️ DEUXIEME PARSEUR DE `releaseDate` DU DEPOT, ET C'EST ASSUME.
    Le premier est `discord_drops._quand`, qu'on ne peut pas importer ici :
    `sheets` appelle ce module, et `discord_drops` importe `sheets` — l'import
    serait circulaire. ⭐⭐ *Quand on ne peut pas partager le code, on epingle
    l'ACCORD* : `tests/test_burn_prevu.py::test_accord_avec_discord_drops`
    rejoue les deux sur la meme batterie de formats et exige le meme jour. Le
    jour ou l'un des deux evolue seul, le banc tombe.
    ⭐ « Deux parseurs pour la meme donnee, c'est un qui ment » — la lecon de
    `_quand` v4 tient toujours ; on l'a payee en la contournant, pas en
    l'ignorant.

    Formats acceptes, dans cet ordre : serial Google (une cellule DATE lue en
    valeur brute), ISO, et le `JJ/MM/AAAA` de l'export catalogue.
    """
    s = str(release_date or "").strip()
    if not s:
        return ""

    brut = s.replace(",", ".")
    try:
        n = float(brut)
    except ValueError:
        n = None
    if n is not None:
        # ~1954 a ~2119. Hors plage = ce n'etait pas une date, c'etait un nombre.
        if not 20000 <= n <= 80000:
            return ""
        base = _dt.datetime(1899, 12, 30)
        return (base + _dt.timedelta(days=n)).date().isoformat()

    t = s.replace("T", " ").replace("Z", "").strip()
    # ⚠️ `%d/%m/%Y` AVANT `%m/%d/%Y` : l'export du projet est en jour/mois, et
    # les deux formats sont indiscernables jusqu'au 12 du mois. Un ordre
    # d'essai est une decision, pas un detail.
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return _dt.datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            continue
    # Dernier recours : un ISO avec fuseau (« 2026-07-07T17:00:00.000+00:00 »).
    try:
        return _dt.datetime.fromisoformat(
            s.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return ""


def part_retenue(tirage, retenues) -> Optional[float]:
    """La part du tirage que VeVe n'a jamais mise en vente, en %.

    Rend None si l'une des deux valeurs manque. ⛔ Pas de repli sur 0 : une
    ligne non enrichie ressemblerait alors a un comic sans retenues, donc a un
    comic qui ne brule pas — un vide se comble, une fausse certitude non."""
    t, r = _nombre(tirage), _nombre(retenues)
    if t is None or r is None or t <= 0 or r < 0:
        return None
    return 100.0 * r / t


def burne_son_invendu(release_date, tirage, retenues,
                      categorie: str = "comic") -> bool:
    """Ce comic appartient-il a la famille qui brule ?

    Les TROIS conditions, et chacune a coute une mesure :
      1. c'est un COMIC (les crafts ont leur propre fenetre — Ron English :
         14 jours, pas 30) ;
      2. il ne sort PAS le mercredi (les 3 comics du mercredi a 9,9 % n'ont
         pas brule, dont deux a J+182 et J+210) ;
      3. sa part retenue atteint le seuil (9,9 a 13,4 % chez ceux qui brulent,
         2,0 % chez les 108 qui ne brulent jamais).
    """
    if str(categorie or "").strip().lower() != "comic":
        return False
    jour = jour_de_sortie(release_date)
    if not jour:
        return False
    if _dt.date.fromisoformat(jour).weekday() == JOUR_COMIC_DAY:
        return False
    part = part_retenue(tirage, retenues)
    return part is not None and part >= SEUIL_RETENUES_PCT


def date_burn_prevue(release_date, tirage, retenues,
                     categorie: str = "comic") -> str:
    """La date **au plus tot** du burn, « YYYY-MM-DD », ou "" si hors regle.

    ⛔ Ne prend AUCUN argument perissable. Voir le docstring du module : y
    faire entrer la circulation ou les ventes ferait heriter cette colonne
    stable de la peremption d'une mesure."""
    if not burne_son_invendu(release_date, tirage, retenues, categorie):
        return ""
    jour = _dt.date.fromisoformat(jour_de_sortie(release_date))
    return (jour + _dt.timedelta(days=DELAI_JOURS)).isoformat()


def burns_a_venir(lignes, aujourdhui: Optional[_dt.date] = None):
    """Les burns encore devant nous : [(date, ligne), …] tries par date.

    `lignes` : des dict portant `releaseDate`, `supply` (tirage) et
    `supply_withheld` (retenues) — les noms du Sheet.

    ⭐ C'est TOUT le gain du chantier, et il ne coute pas une requete : au
    05/08/2026 la mesure donne 4 comics dont le feu n'est pas encore passe, le
    plus proche etant Spider-Man #547 le **06/08** — connu 30 jours a l'avance,
    sans rien demander a VeVe."""
    auj = aujourdhui or _dt.date.today()
    out = []
    for l in lignes or []:
        d = date_burn_prevue(l.get("releaseDate"), l.get("supply"),
                             l.get("supply_withheld"),
                             l.get("category") or "comic")
        if d and _dt.date.fromisoformat(d) >= auj:
            out.append((d, l))
    out.sort(key=lambda x: x[0])
    return out
