# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/discord_burn.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""🔥 LE BURN DU SUPPLY INVENDU — le post forum « 🔥 BURN ».

VeVe garde certains items en boutique un temps limite, puis **brule les
editions invendues**. Le tirage annonce n'est donc pas le tirage final : c'est
un plafond. Ce module suit cette fenetre item par item.

    a bruler     = editions_in_circulation - sold_editions
    supply final = sold_editions
    part brulee  = a bruler / editions_in_circulation

UNE CARTE PAR ITEM, ET ELLE EST **REECRITE**, PAS REPOSTEE
-----------------------------------------------------------
Demande de Preda : « il faudra re-editer l'encarte une fois que le burn est
passe pour signaler bien visuellement que c'est fait ». L'etat retient donc
l'`id` du message : la carte vit du jour ou l'item entre dans la liste jusqu'au
jour ou le burn est constate, et c'est **le meme message** qui passe de l'orange
« a venir » au vert « effectue ». Un investisseur qui a garde le lien voit la
suite de l'histoire, pas un doublon.

🔴🔴 UNE LISTE VIDE N'EST PAS UNE PREUVE DE BURN
------------------------------------------------
Le piege central de ce module. Un item disparait de la page « Leaving Soon »
pour au moins TROIS raisons : il a brule, il a ete vendu jusqu'au dernier, ou
VeVe a prolonge/retire la fenetre. Et il disparait aussi quand le gabarit HTML
change et qu'on ne sait plus lire la page.
➡️ **La disparition ne conclut RIEN.** Le burn n'est ecrit « EFFECTUE » que si
`editionsBurnt` a REELLEMENT augmente cote VeVe entre la publication et
maintenant. Sinon la carte dit ce qui s'est passe (sold out, ou retire sans
burn) — et ne ment pas.
⭐ Meme famille que « un 0 structurel ressemble a un 0 merite » : ici, un « plus
rien dans la liste » ressemblerait a « tout a brule ».

D'OU VIENNENT LES CHIFFRES
--------------------------
* **QUI brule** : la page publique `…/collectibles/en/burning-soon`. C'est la
  reponse de VeVe lui-meme ; rien d'autre ne la deduit sans se tromper. On n'en
  garde que les LIENS (`/{comics|crafts|series|…}/{uuid}`) et le texte de la
  carte — jamais une mise en page.
* **COMBIEN** : VeVe GraphQL, `veve_detail.fetch_dynamic()` — deja ecrit, deja
  instrumente par la sentinelle. Un appel par item concerne (il y en a une
  poignee), et les chiffres sont ceux de l'instant, pas ceux du dernier passage
  hebdomadaire de `dynamic_run`.
* **Le reste** (nom, image, rarete, ATL/ATH, note de classement) : le Sheet,
  qui l'a deja. Zero requete de plus. Sheet illisible = carte plus pauvre,
  jamais carte absente.

⚠️ `comics` : l'uuid du lien est le **series_uuid**, et c'est bien lui que
`publicComicType` attend. Pour un craft, c'est l'uuid de l'ELEMENT. Les deux
conventions sont celles de `discord_drops._lien()` — elles ne se devinent pas.

LE PING
-------
Vide par defaut. Regle posee par Preda : on ne reveille le salon que pour un
burn **massif** — supply final <= `DISCORD_BURN_SEUIL_SUPPLY` (100) **ou** part
brulee >= `DISCORD_BURN_SEUIL_PCT` (90 %). Un burn de 5 % n'est pas une news.
🔴 Le ping vit dans le `content`, JAMAIS dans l'embed : Discord rend `<@&id>`
dans un embed en texte gris, et personne n'est alerte (paye sur `annonce`).
⚠️ Et il ne peut sonner qu'a la CREATION : editer un message ne renotifie
personne. La carte « effectuee » ne ping donc pas, et c'est normal.

Env :
  DISCORD_BURN_THREAD (id du post « 🔥 BURN ») · DISCORD_BURN_WEBHOOK (facultatif)
  DISCORD_BURN_ROLE (vide = ne ping personne) · DISCORD_BURN_STATE
  DISCORD_BURN_URL · DISCORD_BURN_MAX (6) · DISCORD_BURN_DELAI (30)
  DISCORD_BURN_SEUIL_SUPPLY (100) · DISCORD_BURN_SEUIL_PCT (90)
  DISCORD_BURN_GRACE (7) · DISCORD_BURN_SIMULATION
"""

from __future__ import annotations

import datetime as _dt
import html as _html
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from scraper import discord_api as api
from scraper import veve_detail
from scraper.discord_drops import _n, _prix, _records
from scraper.export_elements import lire_notes
from scraper.sheets import _client

MODULE = "burn"

# 🔥 BURN est un POST du forum du hub, comme 📦DROP et 📊 STATS : les posts d'un
# meme salon partagent le webhook, seul le thread_id change. Le repli de
# `api.webhook()` sur DISCORD_HUB_WEBHOOK est donc CORRECT ici — contrairement a
# `annonce`, qui vit dans un AUTRE salon et lit son secret en direct pour ne
# jamais risquer de se tromper de destination.
THREAD = os.environ.get("DISCORD_BURN_THREAD", "1534125779879985212").strip()
ROLE = os.environ.get("DISCORD_BURN_ROLE", "").strip()
STATE_PATH = os.environ.get("DISCORD_BURN_STATE",
                            "data/discord_burn_state.json")

PAGE_URL = os.environ.get(
    "DISCORD_BURN_URL",
    "https://www.veve.me/collectibles/en/burning-soon").strip()

# Anti-avalanche. La page en liste habituellement 1 a 5 items (2 le 04/08/2026,
# compte par Preda). Vingt d'un coup n'est pas une actualite, c'est un symptome
# — on memorise et on le DIT, on ne reveille pas le salon pour un bug.
MAX_NEUFS = int(os.environ.get("DISCORD_BURN_MAX", "6"))

# La fenetre boutique avant burn, en jours. Sert UNIQUEMENT a estimer la date
# affichee quand la page ne porte pas de compte a rebours lisible. Elle n'entre
# dans AUCUNE decision : ce n'est pas elle qui declare un burn fait.
DELAI_JOURS = int(os.environ.get("DISCORD_BURN_DELAI", "30"))

SEUIL_SUPPLY = int(os.environ.get("DISCORD_BURN_SEUIL_SUPPLY", "100"))
SEUIL_PCT = float(os.environ.get("DISCORD_BURN_SEUIL_PCT", "90"))

# Un item disparu de la liste sans burn constate reste surveille ce nombre de
# jours (VeVe peut publier ses compteurs avec du retard). Passe ce delai, la
# carte est close sur ce qu'on SAIT, pas sur ce qu'on espere.
GRACE_JOURS = int(os.environ.get("DISCORD_BURN_GRACE", "7"))

SIMULATION = os.environ.get("DISCORD_BURN_SIMULATION", "").strip().lower() in (
    "1", "true", "oui", "yes")

TIMEOUT = 25
ESSAIS = 3

VEVE_BASE = "https://www.veve.me/collectibles/en"
TABS = [("🟢C-COMICS", "comic"), ("🔵C-COLLECTIBLE", "collectible")]

ORANGE = 0xE67E22        # en attente
VERT = 0x2ECC71          # burn effectue
GRIS = 0x95A5A6          # sorti de la liste sans burn constate
BLEU = 0x1F8BF0          # sold out (rien a bruler)

NOM_RARETE = {
    "COMMON": "Common", "UNCOMMON": "Uncommon", "RARE": "Rare",
    "ULTRA_RARE": "Ultra Rare", "SECRET_RARE": "Secret Rare",
    "EXCLUSIVE": "Exclusive",
}


# ---------------------------------------------------------------------------
# Petits formateurs — le francais, et la virgule qui saute
# ---------------------------------------------------------------------------

def _fr(n: int) -> str:
    """1234567 -> « 1 234 567 »."""
    return f"{int(n):,}".replace(",", " ")


def _pct(part: float) -> str:
    """La virgule francaise, un chiffre apres. ⭐ On formate le pourcentage ICI
    et nulle part ailleurs : deux formateurs pour la meme donnee, c'est un qui
    ment (lecon des lots 50/51)."""
    return f"{part:.1f}".replace(".", ",")


# ---------------------------------------------------------------------------
# 1) LA PAGE — on lit des liens, pas une mise en page
# ---------------------------------------------------------------------------

# `/collectibles/en/comics/<uuid>` — la langue et le prefixe peuvent bouger, la
# forme « famille / uuid » non. On ne capture QUE ce qui porte un uuid : les
# liens de navigation (`/collectibles/en/comics`) n'en ont pas, et c'est
# exactement ce qui les ecarte.
FAMILLES = ("comics", "crafts", "series", "collectibles", "artworks")
# ⚠️ On n'ancre PAS le debut du chemin (« /collectibles/en/… ») : il a deja
# change une fois cote VeVe, et un lien relatif court (« /comics/<uuid> ») est
# tout aussi legitime. `[^"]*?/` avale ce qui precede, quel qu'il soit.
RE_LIEN = re.compile(
    r'href="(?P<href>[^"]*?/(?P<famille>' + "|".join(FAMILLES) +
    r')/(?P<uuid>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}'
    r'-[0-9a-f]{4}-[0-9a-f]{12}))"', re.I)

RE_BADGE = re.compile(r"Leaving\s+(?:in\s+(?P<n>\d+)\s+days?|(?P<today>today))",
                      re.I)
# « 517 left », « 1,234 left », « 1 234 left ». ⚠️ LE SEPARATEUR DE MILLIERS
# EST UN ESPACE, et une carte accole « #547 1999 517 left » : un motif laxiste
# avalait « 547 1999 517 » et rendait 5 471 999 517 (vu au 1er banc). D'ou les
# groupes de 3 chiffres EXACTS — un nombre ne s'etend pas au voisin.
RE_RESTANT = re.compile(
    # ⛔ `(?<!\d)` : sans lui, le motif demarrait AU MILIEU de « 1999 » et
    # rendait « 999 517 ». Un nombre commence la ou le precedent finit.
    r"(?<!\d)(\d{1,3}(?:[,.\u00a0\u202f ]\d{3})*|\d+)\s*left", re.I)
RE_BALISE = re.compile(r"<[^>]+>")

# Marqueur de « on est bien sur la bonne page ». Sans lui, un 200 peut etre une
# page Cloudflare, une redirection ou une page d'erreur maison — et « 0 item »
# ne voudrait plus rien dire.
RE_PAGE = re.compile(r"Leaving\s+Soon|burning-soon", re.I)


def _texte(fragment: str) -> str:
    """HTML -> texte plat, espaces normalises."""
    return re.sub(r"\s+", " ",
                  _html.unescape(RE_BALISE.sub(" ", fragment))).strip()


def charger_page(url: str = "") -> str:
    """Le HTML de la page « Leaving Soon ». Rend "" en cas d'echec — et le DIT.

    ⚠️ www.veve.me est derriere Cloudflare (contrairement a l'hote d'API). Un
    User-Agent de navigateur suffit aujourd'hui ; si un jour ce n'est plus le
    cas, l'echec sera BRUYANT et rien ne sera publie — plutot qu'une liste vide
    interpretee comme « plus rien ne brule »."""
    url = url or PAGE_URL
    entetes = {
        "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36"),
        "accept": "text/html,application/xhtml+xml",
        "accept-language": "en-US,en;q=0.9",
    }
    for essai in range(1, ESSAIS + 1):
        try:
            r = requests.get(url, headers=entetes, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.text
            print(f"  burning-soon : HTTP {r.status_code} "
                  f"(essai {essai}/{ESSAIS})", file=sys.stderr)
        except Exception as e:                              # noqa: BLE001
            print(f"  burning-soon injoignable : {e} "
                  f"(essai {essai}/{ESSAIS})", file=sys.stderr)
        time.sleep(2 * essai)
    return ""


def page_reconnue(page: str) -> bool:
    """Est-ce bien la page « Leaving Soon » ? ⭐ Sans ce controle, « 0 item » et
    « je ne sais plus lire cette page » seraient le meme resultat."""
    return bool(page) and bool(RE_PAGE.search(page))


def analyser(page: str) -> List[Dict[str, Any]]:
    """Le HTML -> [{famille, uuid, url, titre, restant, jours}].

    ⚠️ LE COMPTE A REBOURS EST UNE HEURISTIQUE, ET ELLE EST ASSUMEE. Le badge
    « Leaving in N days » est un FRERE de la carte, pas son contenu : on ne peut
    pas le rattacher par imbrication. On l'attribue donc a l'ancre la plus
    proche, une seule fois chacune. S'il manque, la date est estimee a partir de
    la date de drop ; si les deux manquent, la carte s'affiche SANS date.
    ⛔ Aucune decision ne depend de ce badge : il informe, il ne conclut pas.
    """
    liens = list(RE_LIEN.finditer(page or ""))
    if not liens:
        return []

    items: List[Dict[str, Any]] = []
    vus = set()
    for i, m in enumerate(liens):
        uuid = m.group("uuid").lower()
        if uuid in vus:
            continue                       # une carte = un item, image comprise
        vus.add(uuid)
        # Le corps de la carte : de la FIN de la balise ouvrante jusqu'au DEBUT
        # de la balise qui porte le lien suivant. Les deux bornes comptent :
        # partir de `href=` laisserait les attributs dans le titre, et s'arreter
        # sur le `href=` suivant laisserait une balise ouverte que
        # `RE_BALISE` — qui ne sait retirer que des balises COMPLETES — ne
        # nettoie pas. (Les deux ont ete vus dans le titre du 1er banc.)
        ouvre = page.find(">", m.end())
        debut = ouvre + 1 if ouvre != -1 else m.end()
        if i + 1 < len(liens):
            suivant = liens[i + 1].start()
            balise = page.rfind("<", debut, suivant)
            fin = balise if balise != -1 else suivant
        else:
            fin = len(page)
        # Et on s'arrete a la fermeture de l'ancre quand elle vient avant : le
        # badge de la carte SUIVANTE n'a rien a faire dans ce titre-ci.
        ferme = page.find("</a>", debut)
        if debut < ferme < fin:
            fin = ferme
        corps = _texte(page[debut:fin])
        reste = RE_RESTANT.search(corps)
        href = m.group("href")
        items.append({
            "famille": m.group("famille"),
            "uuid": uuid,
            "url": href if href.startswith("http")
                   else f"https://www.veve.me{href}",
            # Titre de REPLI (le Sheet donne mieux quand il repond). On le
            # coupe au « N left » : au-dela, la carte n'aligne plus que des
            # etiquettes (rarete, type, prix) qui ne sont pas un nom.
            "titre": (corps[:reste.start()] if reste else corps).strip()[:120],
            "restant": _n(reste.group(1)) if reste else 0,
            "jours": None,
            "_pos": m.start(),
        })

    _attacher_badges(page, items)
    for it in items:
        it.pop("_pos", None)
    return items


def _attacher_badges(page: str, items: List[Dict[str, Any]]) -> None:
    """Chaque badge va a l'ancre la PLUS PROCHE, une seule fois chacune."""
    libres = list(items)
    for b in RE_BADGE.finditer(page or ""):
        if not libres:
            return
        jours = 0 if b.group("today") else int(b.group("n"))
        cible = min(libres, key=lambda it: abs(it["_pos"] - b.start()))
        cible["jours"] = jours
        libres.remove(cible)


# ---------------------------------------------------------------------------
# 2) LES CHIFFRES — GraphQL pour l'instant T, le Sheet pour le decor
# ---------------------------------------------------------------------------

def compteurs(uuid: str, famille: str) -> Optional[Dict[str, Any]]:
    """Les compteurs d'editions VeVe, MAINTENANT. None = source muette.

    ⚠️ Pour un comic, l'id GraphQL est le **series_uuid** — celui du lien. Pour
    tout le reste, c'est l'uuid de l'element. Se tromper ne leve pas d'erreur :
    ca rend `null`, donc None, donc une carte non publiee. C'est voulu."""
    try:
        return veve_detail.fetch_dynamic(uuid, is_comic=(famille == "comics"))
    except Exception as e:                                  # noqa: BLE001
        print(f"  GraphQL muet sur {uuid} : {e}", file=sys.stderr)
        return None


def calcul(c: Dict[str, Any]) -> Dict[str, Any]:
    """Les compteurs bruts -> ce qu'on publie.

    ⭐⭐ `editions_in_circulation` est le DENOMINATEUR, pas `totalIssued` : sur
    les items CRAFT, la plupart des editions n'ont jamais ete emises (sonde du
    12/07 : 90,3 % de concordance seulement, et les ecarts sont TOUS la).
    Rapporter le burn au tirage annonce donnerait un pourcentage flatteur et
    faux. C'est la formule de Preda, et c'est la bonne."""
    circ = _n(c.get("editions_in_circulation"))
    vendu = _n(c.get("sold_editions"))
    a_bruler = max(circ - vendu, 0)
    return {
        "circulation": circ,
        "vendues": vendu,
        "brulees": _n(c.get("burned_editions")),
        "disponibles": _n(c.get("veve_total_available")),
        "a_bruler": a_bruler,
        # Le supply final = ce qui reste apres le feu = ce qui a ete vendu.
        "supply_final": vendu,
        "part": (100.0 * a_bruler / circ) if circ > 0 else 0.0,
        "prix": c.get("veve_store_price"),
    }


def decor(sh) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    """{uuid -> fiche} depuis le Sheet, indexe par series_uuid ET veve_uuid, et
    {cle -> note} depuis 🏆A-CLASSEMENT.

    Un comic est indexe par son series_uuid (plusieurs raretes, une fiche) ; un
    collectible par son veve_uuid. Les deux cles cohabitent : la page nous donne
    l'une OU l'autre selon la famille, et on ne sait pas laquelle a l'avance."""
    fiches: Dict[str, Dict[str, Any]] = {}
    for tab, genre in TABS:
        for r in _records(sh, tab):
            cles = [str(r.get("series_uuid") or "").strip().lower(),
                    str(r.get("veve_uuid") or "").strip().lower()]
            for cle in [c for c in cles if c]:
                f = fiches.setdefault(cle, {
                    "genre": genre,
                    "nom": (str(r.get("veve_comic_name") or "").strip()
                            or str(r.get("veve_series_name") or "").strip()
                            or str(r.get("name") or "").strip()),
                    "image": str(r.get("image_url") or "").strip(),
                    "url": str(r.get("veve_url") or "").strip(),
                    "marque": str(r.get("veve_brand") or "").strip(),
                    "rarete": str(r.get("rarity") or "").strip().upper(),
                    "supply": _n(r.get("supply")),
                    "prix": r.get("store_price_gems"),
                    "sortie": str(r.get("releaseDate") or "").strip(),
                    "atl": r.get("atl"), "ath": r.get("ath"),
                })
                if not f["image"] and r.get("image_url"):
                    f["image"] = str(r["image_url"]).strip()
    try:
        notes = lire_notes(sh)
    except Exception as e:                                  # noqa: BLE001
        print(f"  🏆A-CLASSEMENT illisible : {e}", file=sys.stderr)
        notes = {}
    return fiches, {str(k).strip().lower(): v for k, v in notes.items()}


def _jour_burn(it: Dict[str, Any],
               fiche: Dict[str, Any]) -> Optional[_dt.date]:
    """La date de burn : le badge de la page d'abord, la date de drop + DELAI
    ensuite, rien enfin. ⭐ Une estimation s'annonce comme une estimation."""
    if it.get("jours") is not None:
        return _dt.date.today() + _dt.timedelta(days=int(it["jours"]))
    brut = str((fiche or {}).get("sortie") or "")[:10]
    try:
        return _dt.date.fromisoformat(brut) + _dt.timedelta(days=DELAI_JOURS)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 3) LA CARTE
# ---------------------------------------------------------------------------

def merite_ping(d: Dict[str, Any]) -> bool:
    """Regle de Preda : on ne sonne que pour un burn massif — supply final
    minuscule OU quasi-tout le tirage qui part. Sans role configure, jamais."""
    if not ROLE:
        return False
    return (0 < d["supply_final"] <= SEUIL_SUPPLY) or (d["part"] >= SEUIL_PCT)


def _bloc_chiffres(d: Dict[str, Any], fait: bool) -> str:
    """Le tableau aligne, en bloc de code : c'est ce qui se lit d'un coup d'oeil
    sur telephone (une colonne d'emojis, elle, se decale)."""
    # ⚠️ APRES LE FEU, `editions_in_circulation` A DEJA FONDU. Afficher la
    # valeur de l'instant donnerait « 259 en circulation, 341 brûlées » — une
    # carte qui ne s'additionne plus et un pourcentage a −131 %. On montre donc
    # la circulation D'AVANT (memorisee a la publication) : 600 → 259.
    circ = _n(d.get("circulation_depart")) or d["circulation"] if fait \
        else d["circulation"]
    lignes = [
        ("En circulation", _fr(circ)),
        ("Vendues", _fr(d["vendues"])),
        ("Brûlées" if fait else "À brûler",
         _fr(d["brulees_reelles"] if fait else d["a_bruler"])),
    ]
    largeur = max(len(v) for _, v in lignes)
    return "```\n" + "\n".join(
        f"{k:<16}{v:>{largeur}}" for k, v in lignes) + "\n```"


def _lignes_fiche(fiche: Dict[str, Any], note: str, d: Dict[str, Any],
                  genre: str) -> List[str]:
    """Rarete, prix, note de classement, extremes — ce qu'un investisseur
    regarde avant de decider s'il achete AVANT le feu."""
    out: List[str] = []
    tete = []
    rar = NOM_RARETE.get(fiche.get("rarete", ""), "")
    if rar:
        tete.append(f"💠 {rar}")
    # ⛔ `_prix` est PARTAGE avec `discord_drops`, dont les cartes sont en
    # anglais : on ne touche pas a sa sortie, on la francise ICI. Changer
    # l'unite que la machine compte pour une question d'affichage, c'est
    # exactement la faute des lots 50/51.
    p = _prix(d.get("prix") or fiche.get("prix"), genre).replace(".", ",")
    if p:
        tete.append(f"💎 Prix boutique **{p} $**")
    if tete:
        out.append(" · ".join(tete))
    if note:
        out.append(f"📊 Note de classement : **{note}**")
    atl = _prix(fiche.get("atl")).replace(".", ",")
    ath = _prix(fiche.get("ath")).replace(".", ",")
    bornes = []
    if atl:
        bornes.append(f"📉 ATL {atl} $")
    if ath:
        bornes.append(f"📈 ATH {ath} $")
    if bornes:
        out.append(" · ".join(bornes))
    return out


def carte(d: Dict[str, Any]) -> Dict[str, Any]:
    """Le message complet (content + embed). `d` porte deja tout le calcul.

    🔴 Le ping est dans `content`. Dans un embed, `<@&id>` s'affiche en gris et
    n'alerte personne — un test le verrouille."""
    statut, nom = d["statut"], d["nom"]
    fait = statut == "fait"

    if statut == "attente":
        titre, couleur = f"🔥 BURN À VENIR — {nom}", ORANGE
    elif fait:
        titre, couleur = f"✅ BURN EFFECTUÉ — {nom}", VERT
    elif statut == "sold_out":
        titre, couleur = f"💯 SOLD OUT — {nom}", BLEU
    else:
        titre, couleur = f"⏸️ RETIRÉ DE LA LISTE — {nom}", GRIS

    corps: List[str] = []

    if statut == "attente":
        if d.get("ts"):
            quand = f"⏳ Burn **<t:{d['ts']}:D>**"
            if d.get("estime"):
                quand += " *(estimé)*"
            corps.append(quand)
        else:
            corps.append("⏳ Burn imminent — date non communiquée par VeVe")
        corps.append("")
        corps.append(_bloc_chiffres(d, fait=False))
        corps.append(f"🔥 **{_pct(d['part'])} %** du supply en circulation "
                     f"part en fumée")
        corps.append(f"🎯 Supply final estimé : "
                     f"**{_fr(d['supply_final'])} éditions**")
    elif fait:
        corps.append(f"🔥 **{_fr(d['brulees_reelles'])} éditions brûlées** "
                     f"— c'est définitif")
        corps.append("")
        corps.append(_bloc_chiffres(d, fait=True))
        corps.append(f"🎯 Supply final : **{_fr(d['supply_final'])} éditions** "
                     f"(−{_pct(d['part_reelle'])} %)")
        if d.get("ecart"):
            # ⭐ On avait annonce un chiffre : s'il differe, on le DIT. Un
            # module qui se corrige en silence apprend a mentir.
            corps.append(f"ℹ️ Annoncé : {_fr(d['a_bruler_annonce'])} · "
                         f"réel : {_fr(d['brulees_reelles'])}")
    elif statut == "sold_out":
        corps.append("💯 **Vendu jusqu'à la dernière édition** — aucun burn, "
                     "le tirage reste entier.")
        corps.append("")
        corps.append(f"🎯 Supply final : **{_fr(d['supply_final'])} éditions**")
    else:
        corps.append("⏸️ L'item a quitté la liste **sans burn constaté** "
                     "côté VeVe.")
        corps.append("Fenêtre prolongée, retirée, ou compteurs pas encore "
                     "publiés — on ne conclut pas à sa place.")
        corps.append("")
        corps.append(f"📦 En circulation : **{_fr(d['circulation'])}** · "
                     f"💰 vendues : **{_fr(d['vendues'])}**")

    fiche = d.get("fiche") or {}
    extra = _lignes_fiche(fiche, d.get("note", ""), d, d.get("genre", ""))
    if extra:
        corps.append("")
        corps.extend(extra)

    corps.append("")
    corps.append(f"[Voir sur VeVe](<{d['url']}>)")

    embed = {"title": titre[:250], "color": couleur,
             "description": "\n".join(corps)[:4000],
             "footer": {"text": f"Chiffres VeVe du {d['vu_le']} · "
                                f"editions_in_circulation − sold_editions"}}
    if d.get("url"):
        embed["url"] = d["url"]
    if fiche.get("image"):
        embed["image"] = {"url": fiche["image"]}

    ping = bool(d.get("ping")) and bool(ROLE)
    return {"content": f"🔥 <@&{ROLE}>" if ping else "",
            "embeds": [embed],
            "allowed_mentions": api.mentions([ROLE] if ping else [])}


# ---------------------------------------------------------------------------
# 4) L'ETAT — ce qui empeche le doublon ET le mensonge
# ---------------------------------------------------------------------------

def statut_apres_disparition(suivi: Dict, c: Dict[str, Any],
                             aujourdhui: Optional[_dt.date] = None) -> str:
    """L'item n'est plus dans la liste. Qu'est-ce qui s'est passe ?

    ⭐⭐ SEUL `editionsBurnt` FAIT FOI. On le compare a ce qui etait vrai le
    jour de la publication : s'il a monte, VeVe a brule. Sinon on regarde s'il
    ne restait rien a vendre (sold out). Sinon, et seulement sinon, on attend —
    puis on clot en disant qu'on ne sait pas."""
    aujourdhui = aujourdhui or _dt.date.today()
    if c["brulees"] > _n(suivi.get("brulees_depart")):
        return "fait"
    if c["disponibles"] == 0 and c["a_bruler"] == 0:
        return "sold_out"
    depuis = suivi.get("disparu_le")
    if not depuis:
        return "attente_confirmation"
    try:
        ecoule = (aujourdhui - _dt.date.fromisoformat(depuis)).days
    except ValueError:
        return "attente_confirmation"
    return "sans_burn" if ecoule >= GRACE_JOURS else "attente_confirmation"


def _empreinte_carte(msg: Dict) -> str:
    """De quoi savoir si la carte a CHANGE. Rediter un message identique tous
    les matins consomme le quota du hub pour rien."""
    e = (msg.get("embeds") or [{}])[0]
    return f"{e.get('title', '')}|{e.get('color', '')}|{e.get('description', '')}"


# ---------------------------------------------------------------------------
# 5) Main
# ---------------------------------------------------------------------------

def _publier(wh: str, suivi: Dict, msg: Dict, nom: str) -> bool:
    """Poste ou edite, selon qu'on connait deja l'id. Rend True si l'etat a
    bouge. En SIMULATION (ou sans webhook), imprime et n'envoie rien."""
    empreinte = _empreinte_carte(msg)
    if suivi.get("mid") and suivi.get("empreinte") == empreinte:
        return False                       # rien n'a change : on ne touche pas
    if SIMULATION or not wh:
        print(f"  [simulation] {'édition' if suivi.get('mid') else 'création'}"
              f" — {nom}\n"
              f"{(msg.get('embeds') or [{}])[0].get('description', '')}\n",
              flush=True)
        suivi["empreinte"] = empreinte
        return True
    if suivi.get("mid"):
        mid = api.editer(wh, THREAD, suivi["mid"], msg)
    else:
        mid = api.poster(wh, THREAD, msg)
    if not mid:
        print(f"  ⚠️ « {nom} » n'a pas pu être publié — RETENTÉ au prochain "
              f"passage (l'empreinte n'est PAS mémorisée).", file=sys.stderr)
        return False
    suivi["mid"] = mid
    suivi["empreinte"] = empreinte
    api.souffler()
    return True


def run() -> int:                                           # noqa: C901
    t0 = time.time()
    wh = api.webhook(MODULE)
    if not wh and not SIMULATION:
        print("Aucun webhook (ni DISCORD_BURN_WEBHOOK ni DISCORD_HUB_WEBHOOK) "
              "— le module tourne en SIMULATION.", file=sys.stderr)

    page = charger_page()
    if not page_reconnue(page):
        # 🔴 On ne touche a RIEN. Une page illisible ne doit jamais se traduire
        # par « plus rien ne brule » : ce serait clore toutes les cartes en
        # cours sur un silence reseau.
        print("⛔ La page « Leaving Soon » n'a pas été reconnue (réseau, "
              "Cloudflare, ou gabarit changé). Rien n'est publié, rien n'est "
              "clos, l'état est intact.", file=sys.stderr)
        return 1

    liste = analyser(page)
    print(f"burning-soon : {len(liste)} item(s) — "
          f"{', '.join(i['uuid'][:8] for i in liste) or 'aucun'}", flush=True)
    if not liste:
        print("  (la page est bien lue et ne liste rien : c'est un ÉTAT "
              "NORMAL, pas une panne — et surtout pas un burn.)", flush=True)

    state = api.load_state(STATE_PATH, wh, THREAD)
    dossier: Dict[str, Dict] = state.setdefault("items", {})

    # Le Sheet : facultatif. Sans lui, la carte perd le nom joli, l'image et la
    # note — elle ne perd PAS les chiffres, qui sont l'essentiel.
    fiches: Dict[str, Dict[str, Any]] = {}
    notes: Dict[str, str] = {}
    sheet_id = os.environ.get("SHEET_ID", "").strip()
    if sheet_id:
        try:
            fiches, notes = decor(_client().open_by_key(sheet_id))
        except Exception as e:                              # noqa: BLE001
            print(f"  Sheet illisible ({e}) — cartes sans nom joli ni note.",
                  file=sys.stderr)
    else:
        print("  SHEET_ID absent — cartes sans nom joli ni note.",
              file=sys.stderr)

    aujourdhui = _dt.date.today()
    presents = {i["uuid"]: i for i in liste}
    # Les items a traiter : ceux de la page + ceux qu'on suit encore.
    a_voir = list(presents) + [u for u, s in dossier.items()
                               if not s.get("clos") and u not in presents]

    neufs = [u for u in presents if u not in dossier]
    if len(neufs) > MAX_NEUFS:
        print(f"⛔ {len(neufs)} items neufs d'un coup (plafond {MAX_NEUFS}) — "
              f"VeVe n'en met jamais autant en même temps. On MÉMORISE sans "
              f"publier ; relève le plafond si c'est légitime.",
              file=sys.stderr)
        for u in neufs:
            dossier[u] = {"nom": presents[u]["titre"][:80],
                          "famille": presents[u]["famille"],
                          "clos": True, "avale": True}
        api.save_state(STATE_PATH, state, wh, THREAD)
        return 1

    publies = edites = clos = muets = 0

    for uuid in a_voir:
        it = presents.get(uuid) or {}
        suivi = dossier.setdefault(uuid, {})
        famille = it.get("famille") or suivi.get("famille") or "collectibles"

        c_brut = compteurs(uuid, famille)
        if not c_brut:
            muets += 1
            print(f"  ⚠️ {uuid[:8]} : VeVe n'a pas répondu — carte INCHANGÉE, "
                  f"on retente au prochain passage.", file=sys.stderr)
            continue
        c = calcul(c_brut)

        fiche = fiches.get(uuid, {})
        nom = (fiche.get("nom") or suivi.get("nom")
               or it.get("titre", "")[:80] or uuid[:8])
        genre = fiche.get("genre") or ("comic" if famille == "comics"
                                       else "collectible")

        if uuid in presents:
            statut = "attente"
            suivi.pop("disparu_le", None)
        else:
            suivi.setdefault("disparu_le", aujourdhui.isoformat())
            statut = statut_apres_disparition(suivi, c, aujourdhui)
            if statut == "attente_confirmation":
                print(f"  ⏳ {nom} : sorti de la liste, burn NON confirmé "
                      f"(brûlées {c['brulees']} vs "
                      f"{_n(suivi.get('brulees_depart'))} au départ) — "
                      f"on attend, on ne conclut pas.", flush=True)
                continue

        suivi.setdefault("brulees_depart", c["brulees"])
        suivi.setdefault("circulation_depart", c["circulation"])
        suivi["nom"], suivi["famille"] = nom, famille
        if statut == "attente":
            suivi["a_bruler_annonce"] = c["a_bruler"]

        brulees_reelles = max(c["brulees"] - _n(suivi.get("brulees_depart")), 0)
        annonce = _n(suivi.get("a_bruler_annonce")) or c["a_bruler"]
        base = _n(suivi.get("circulation_depart")) or c["circulation"]

        jour = _jour_burn(it, fiche) if statut == "attente" else None
        d = dict(c)
        d.update({
            "statut": statut, "nom": nom, "genre": genre,
            "url": (it.get("url") or fiche.get("url")
                    or f"{VEVE_BASE}/{famille}/{uuid}"),
            "fiche": fiche, "note": notes.get(uuid, ""),
            "vu_le": aujourdhui.strftime("%d/%m/%Y"),
            "circulation_depart": base,
            "brulees_reelles": brulees_reelles,
            "a_bruler_annonce": annonce,
            "part_reelle": (100.0 * brulees_reelles / base) if base else 0.0,
            "ecart": statut == "fait" and brulees_reelles != annonce,
            "ts": int(_dt.datetime.combine(
                jour, _dt.time(12, 0), _dt.timezone.utc).timestamp())
                if jour else 0,
            "estime": bool(jour) and it.get("jours") is None,
        })

        # ⭐ CONTRE-MESURE : la page annonce « N left », GraphQL calcule
        # circulation − vendues. Les deux devraient dire la meme chose. Quand
        # ils divergent, c'est soit une latence, soit une formule qui a change
        # sous nos pieds — et dans les deux cas on veut le savoir AVANT que le
        # chiffre publie devienne faux. On le NOTE, on ne corrige pas : deux
        # definitions qui se reecrivent l'une l'autre, c'est la guerre.
        vu = _n(it.get("restant"))
        if statut == "attente" and vu and abs(vu - c["a_bruler"]) > max(
                5, 0.05 * max(vu, 1)):
            print(f"  ⚠️ {nom} : la page dit {_fr(vu)} restantes, le calcul "
                  f"dit {_fr(c['a_bruler'])} — écart de "
                  f"{_fr(abs(vu - c['a_bruler']))}. On publie le calcul.",
                  file=sys.stderr)

        premiere = not suivi.get("mid")
        d["ping"] = premiere and statut == "attente" and merite_ping(d)

        if _publier(wh, suivi, carte(d), nom):
            if premiere:
                publies += 1
                print(f"  ✅ carte publiée — {nom} : {_fr(c['a_bruler'])} à "
                      f"brûler ({_pct(c['part'])} %)"
                      + (" · PING" if d["ping"] else ""), flush=True)
            else:
                edites += 1
                print(f"  ✏️ carte réécrite — {nom} → {statut}", flush=True)

        if statut in ("fait", "sold_out", "sans_burn"):
            suivi["clos"] = True
            clos += 1

    api.save_state(STATE_PATH, state, wh, THREAD)
    print(f"🔥 BURN : {publies} publiée(s), {edites} réécrite(s), "
          f"{clos} close(s), {muets} source(s) muette(s) — "
          f"{time.time() - t0:.0f}s", flush=True)
    # Une source muette n'est pas une reussite : le run sort en erreur pour que
    # ca se voie dans Actions, sans empecher les autres modules du hub.
    return 1 if muets else 0


if __name__ == "__main__":
    sys.exit(run())
