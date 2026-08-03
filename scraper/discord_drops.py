# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/discord_drops.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""📦 LES DROPS À VENIR DANS LE POST FORUM « 📦DROP » — carte + sondage D/M/❌.

Une carte par drop (a la maille de la SERIE : les 5 raretes d'un comic sont UNE
seule annonce), le role SONDAGE pinge UNE FOIS pour toute la vague, et trois
reactions posees par le bot pour ouvrir le sondage.

⚠️ LE POINT DUR : UN WEBHOOK NE PEUT PAS REAGIR.
------------------------------------------------
L'API Discord ne permet d'ajouter une reaction qu'avec un **token de bot**
(`PUT /channels/{id}/messages/{id}/reactions/{emoji}/@me`). Un webhook poste,
edite, supprime — jamais il ne reagit. D'ou le partage des roles ici :
  * le WEBHOOK poste la carte (et nous rend l'id du message, `wait=true`) ;
  * le BOT (secret `DISCORD_BOT_TOKEN`) pose les trois reactions dessus.
**Si le token manque ou echoue, la carte part QUAND MEME**, sans reactions, et le
log le dit. Un sondage sans boutons vaut mieux qu'une annonce jamais publiee.

LES DONNEES VIENNENT DU SHEET, PAS DE VEVE
------------------------------------------
Tout est deja dans 🟢C-COMICS / 🔵C-COLLECTIBLE depuis le chantier classement :
`supply` (= totalIssued, le VRAI tirage par rarete), `store_price_gems`,
`edition_type` (le nom de la variante), `rarity`, `series_uuid`, `image_url`,
`drop_method`, `veve_brand`, `start_year`. Aucune requete vers VeVe : zero risque
de se faire remarquer, et impossible de dire autre chose que le Sheet.
⚠️ `releaseAmount` du tracker N'EST PAS le supply d'un comic (c'est celui de la
RARETE de la ligne) — on utilise `supply`, jamais releaseAmount.
Le **Min. MCP Priority Bid est CONSTANT (5 000)** : VeVe ne l'expose nulle part
(30 champs sondes -> « Invalid request »). Il est donc en dur, et c'est assume.

LES GARDE-FOUS
--------------
1. **1er run** : on memorise LE PASSE, et rien que le passe. ⚠️ v2, corrige
   apres le 1er run reel : je memorisais TOUT le catalogue, drops A VENIR
   compris — donc le garde-fou avalait precisement ce qu'on voulait annoncer,
   et ces drops-la ne seraient JAMAIS sortis. Un garde-fou qui mange la donnee
   qu'il protege n'est pas un garde-fou, c'est un bug. (Rattrapage :
   `DISCORD_DROPS_REJOUER=true` oublie les drops a venir de l'etat.)
2. **LA DATE DE DROP FAIT FOI** : on n'annonce QUE des drops A VENIR (releaseDate
   >= aujourd'hui). Meme avec un etat perdu, on ne peut pas deterrer 2021.
   (Regle generale : ne jamais faire d'un ETAT la source de verite quand une
   donnee INTRINSEQUE existe dans les donnees.)
3. **Anti-avalanche** : au-dela de `DISCORD_DROPS_MAX_NEUFS` (8) drops neufs,
   on memorise sans annoncer. VeVe ne sort pas 20 drops dans la nuit ; si ca
   arrive, c'est un bug, et on ne reveille pas le serveur pour un bug.
4. **UN SEUL PING PAR VAGUE** : la 1re carte porte la mention, les suivantes
   partent en silence. Trois drops le meme matin = trois cartes, UNE notif.
5. **Mentions bridees** : `allowed_mentions` n'autorise QUE le role SONDAGE.
6. **Une carte incomplete n'est pas publiee** : sans nom, sans date ou sans
   supply, on saute le drop et on le DIT (il repassera au prochain run, quand
   la fiche sera enrichie). Mieux vaut rien qu'une carte a trous.
7. **429** respecte, cartes espacees (cf. scraper/discord_api.py).

LE MIROIR PUBLIC (28/07/2026)
-----------------------------
📦DROP est dans la partie INVESTISSEUR du serveur. La meme carte part desormais
aussi dans **📘⎮sondage-drop**, qui est PUBLIC — sans ping, avec ses propres
reactions. Les deux salons sont deux POPULATIONS, pas un seul sondage coupe en
deux : `discord_retour` en tire DEUX lignes, et une personne qui a vote des deux
cotes n'est comptee que du cote investisseur (cf. `fusionner_votes`).
**Sans `DISCORD_SONDAGE_WEBHOOK`, le miroir est simplement muet** — il ne
retombe JAMAIS sur le webhook du hub (voir le commentaire de MIROIR_WEBHOOK).

Env :
  DISCORD_DROPS_THREAD (id du post) · DISCORD_DROPS_ROLE (role SONDAGE)
  DISCORD_BOT_TOKEN (SECRET — pour les reactions ; sans lui : pas de reactions)
  DISCORD_DROPS_STATE · DISCORD_DROPS_MAX_NEUFS (8) · DISCORD_DROPS_MAX_CARTES (5)
  DISCORD_DROPS_EMOJI_VEVE · DISCORD_DROPS_EMOJI_MARQUES (JSON marque -> emoji)
  DISCORD_SONDAGE_WEBHOOK (SECRET, salon public) · DISCORD_SONDAGE_SALON
  DISCORD_SONDAGE_THREAD (vide : salon normal, pas un post de forum)
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import time
from typing import Any, Dict, List

from scraper import discord_api as api
from scraper import discord_drops_sortis as sortis
from scraper.sheets import _client, append_log
from scraper.export_elements import lire_notes    # note de 🏆A-CLASSEMENT (lecture reutilisee)

MODULE = "drops"
THREAD = os.environ.get("DISCORD_DROPS_THREAD", "1526540247469391952").strip()
ROLE = os.environ.get("DISCORD_DROPS_ROLE", "1104653344108191818").strip()
STATE_PATH = os.environ.get("DISCORD_DROPS_STATE",
                            "data/discord_drops_state.json")

TABS = [("🟢C-COMICS", "comic"), ("🔵C-COLLECTIBLE", "collectible")]

# ═══ LE MIROIR PUBLIC : 📘⎮sondage-drop ═══
# 📦DROP vit dans la partie INVESTISSEUR du serveur ; 📘sondage-drop est PUBLIC.
# La meme carte part dans les deux, pour que tout le monde puisse voter — mais
# les deux populations sont comptees SEPAREMENT dans le retour sur drop (deux
# lignes), et une personne qui vote des deux cotes n'est comptee que du cote
# investisseur. Le dedoublonnage vit dans `discord_retour.fusionner_votes`.
#
# ⚠️ LE PIEGE, ET IL EST GRAVE : on n'appelle **PAS** `api.webhook("sondage")`.
# Cette fonction RETOMBE sur `DISCORD_HUB_WEBHOOK` quand le secret du module
# manque — et le miroir irait alors deverser toutes les cartes dans le forum du
# hub, sans qu'aucune erreur ne soit levee. Un miroir mal configure doit rester
# MUET, pas se tromper de salon. On lit donc la variable en direct : pas de
# secret, pas de miroir.
MIROIR_WEBHOOK = os.environ.get("DISCORD_SONDAGE_WEBHOOK", "").strip()
# Le salon public est un salon NORMAL, pas un post de forum -> thread vide pour
# le webhook. (S'il devenait un post de forum un jour, poser le thread ici.)
MIROIR_THREAD = os.environ.get("DISCORD_SONDAGE_THREAD", "").strip()
# L'id du SALON, lui, sert aux REACTIONS et a la relecture des votes : l'API des
# reactions parle en `channel_id` (dans un forum, c'est l'id du post).
MIROIR_SALON = os.environ.get("DISCORD_SONDAGE_SALON",
                              "1531670469319852082").strip()


def salon_miroir() -> str:
    """L'id de salon a donner a l'API des reactions pour le miroir."""
    return MIROIR_THREAD or MIROIR_SALON

MAX_NEUFS = int(os.environ.get("DISCORD_DROPS_MAX_NEUFS", "8"))
# Rattrapage : oublier les drops A VENIR deja memorises, pour les (re)annoncer.
# Sert une fois — quand un 1er run trop gourmand les a avales.
REJOUER = os.environ.get("DISCORD_DROPS_REJOUER", "").strip().lower() in (
    "1", "true", "oui", "yes")
MAX_CARTES = int(os.environ.get("DISCORD_DROPS_MAX_CARTES", "5"))
# HORIZON : un drop s'annonce quelques jours avant, pas des mois. Au-dela, ce
# n'est pas une news — et c'est souvent une date bidon. (Run reel du 14/07 :
# 1651 « drops a venir » ! Un chiffre pareil n'est jamais une actualite, c'est
# un symptome.)
HORIZON = int(os.environ.get("DISCORD_DROPS_HORIZON", "7"))

# ═══ LE COMIC DU MERCREDI (VeVe Comic Book Day) ═══
# Idee de Preda, et elle vaut mieux que mon garde-fou : elle traite la CAUSE.
# Le mercredi, VeVe deverse des comics en masse — **3 055 series sur 4 195** dans
# son classement, et il n'en a jamais note une seule. Ce n'est pas de
# l'actualite, c'est du remplissage : ni annonce, ni retour.
#
# ⚠️ C'EST UNE HEURISTIQUE, PAS UN FAIT. Le vrai signal serait un drapeau
# `is_from_veve_comics` (qui n'existe pas encore dans les donnees) ; le jour de
# la semaine n'en est qu'un proxy. **Un comic majeur qui sortirait un mercredi
# passerait a la trappe.** D'ou : debrayable (`DISCORD_SANS_COMIC_DAY=false`), et
# le nombre d'ecartes est ECRIT dans les logs — un filtre silencieux est un
# mensonge par omission.
SANS_COMIC_DAY = os.environ.get(
    "DISCORD_SANS_COMIC_DAY", "true").strip().lower() in ("1", "true", "oui")
JOUR_COMIC_DAY = int(os.environ.get("DISCORD_COMIC_DAY", "2"))   # 2 = mercredi


# L'illustration du message groupe (la banniere « VeVe Comics »). Discord ne
# sert pas de fichiers : il faut une URL. Le plus simple : deposer l'image dans
# un salon Discord, copier son lien, le poser en variable de repo.
IMAGE_COMIC_DAY = os.environ.get("DISCORD_DROPS_IMAGE_COMIC_DAY", "").strip()
LIEN_COMICS = os.environ.get("DISCORD_DROPS_LIEN_COMICS",
                             "https://www.veve.me/comics/en")
MAX_LIGNES_CD = int(os.environ.get("DISCORD_DROPS_COMIC_LIGNES", "30"))


def est_comic_du_mercredi(genre: str, jour: str) -> bool:
    """Un COMIC dont la date de sortie tombe le jour du Comic Book Day."""
    if not SANS_COMIC_DAY or genre != "comic" or not jour:
        return False
    try:
        return _dt.date.fromisoformat(jour).weekday() == JOUR_COMIC_DAY
    except ValueError:
        return False
MCP_BID = os.environ.get("DISCORD_DROPS_MCP_BID", "5,000")

# LES LIENS BOUTIQUE. Trois familles de pages VeVe, et c'est le TYPE DE DROP qui
# tranche : un craft ne vit pas au meme endroit qu'une serie.
#   comics  -> /comics/<series_uuid>     (un comic = une serie)
#   crafts  -> /crafts/<VEVE_UUID>       (drop_method = CRAFT) ⚠️ l'uuid de
#              l'ELEMENT, PAS celui de la serie — verifie par Preda sur
#              « Colossus x Wolverine » : la page vit sous l'uuid de l'objet.
#              Un craft n'a qu'une rarete : son element EST le drop.
#   series  -> /series/<series_uuid>     (tout le reste : les collectibles)
# ⚠️ On ne reutilise PAS la colonne `veve_url` du catalogue : elle pointe vers
# les anciennes routes (/collection/comic/…), qui ne sont plus celles de la
# boutique. Un lien mort est pire que pas de lien.
VEVE_BASE = os.environ.get("DISCORD_DROPS_VEVE_BASE",
                           "https://www.veve.me/collectibles/en")
LIEN_TEXTE = os.environ.get("DISCORD_DROPS_LIEN_TEXTE", "Page VeVe")

EMOJI_VEVE = os.environ.get("DISCORD_DROPS_EMOJI_VEVE",
                            "<:VeVeLogo:1104658104383193178>")
EMOJI_MARQUES = json.loads(os.environ.get(
    "DISCORD_DROPS_EMOJI_MARQUES",
    '{"marvel": "<:marvel:373994236107948032>"}'))

# Les trois reactions du sondage : 🇩rop / 🇲arket / ❌ Pass.
REACTIONS = os.environ.get("DISCORD_DROPS_REACTIONS", "🇩,🇲,❌").split(",")

# L'ordre des raretes, du plus commun au plus rare. La DERNIERE ligne affichee
# est soulignee (c'est la Secret Rare qui fait courir tout le monde).
ORDRE_RARETE = ["COMMON", "UNCOMMON", "RARE", "ULTRA_RARE", "SECRET_RARE",
                "LEGENDARY", "MYTHIC"]
NOM_RARETE = {"COMMON": "Common", "UNCOMMON": "Uncommon", "RARE": "Rare",
              "ULTRA_RARE": "Ultra Rare", "SECRET_RARE": "Secret Rare",
              "LEGENDARY": "Legendary", "MYTHIC": "Mythic"}


# ---------------------------------------------------------------------------
# Lecture du catalogue
# ---------------------------------------------------------------------------

def _records(sh, tab: str) -> List[Dict[str, Any]]:
    try:
        return sh.worksheet(tab).get_all_records()
    except Exception as e:                                  # noqa: BLE001
        print(f"lecture de {tab} impossible : {e}", file=sys.stderr)
        return []


def _n(x) -> int:
    s = str(x or "").replace(" ", "").replace("\xa0", "").replace(",", "")
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return 0


def _quand(x):
    """La date de sortie -> (jour « YYYY-MM-DD », timestamp Unix, heure_connue).

    ⚠️ v4, apres le run reel : j'avais DEUX parseurs — un pour la date (qui
    marchait) et un pour l'heure (qui ne connaissait pas le format du Sheet).
    Resultat : les 5 drops etaient bien trouves, puis TOUS sautes pour « pas
    d'heure exploitable ». **Deux parseurs pour la meme donnee, c'est un qui
    ment.** Il n'y en a plus qu'un.

    ⚠️ v3 : on PARSE, on ne compare pas des chaines. Une cellule qui n'est pas
    une date (« 46212.625 », un texte) donnait une pseudo-date qui, en
    comparaison de chaines, tombait « dans le futur » (« 4… » > « 2… ») —
    d'ou les 1651 « drops a venir »."""
    s = str(x or "").strip()
    if not s:
        return "", 0, False

    # 1. Serial Google (une cellule DATE lue en valeur brute). La PARTIE
    #    DECIMALE porte l'heure : 46212,708 = le 09/07/2026 a 17h00.
    brut = s.replace(",", ".")
    try:
        n = float(brut)
    except ValueError:
        n = None
    if n is not None:
        if not 20000 <= n <= 80000:            # ~1954 a ~2119 : hors plage
            return "", 0, False
        base = _dt.datetime(1899, 12, 30, tzinfo=_dt.timezone.utc)
        d = base + _dt.timedelta(days=n)
        avec_heure = abs(n - int(n)) > 1e-6
        return d.date().isoformat(), int(d.timestamp()), avec_heure

    # 2. Texte. Les formats AVEC heure d'abord : c'est elle qu'on veut.
    t = s.replace("T", " ").replace("Z", "").strip()
    for fmt, heure in (("%Y-%m-%d %H:%M:%S", True), ("%Y-%m-%d %H:%M", True),
                       ("%d/%m/%Y %H:%M:%S", True), ("%d/%m/%Y %H:%M", True),
                       ("%Y-%m-%d", False), ("%d/%m/%Y", False),
                       ("%m/%d/%Y", False)):
        try:
            d = _dt.datetime.strptime(t[:19] if heure else t[:10], fmt)
        except ValueError:
            continue
        d = d.replace(tzinfo=_dt.timezone.utc)
        return d.date().isoformat(), int(d.timestamp()), heure
    return "", 0, False


def _date(x) -> str:
    return _quand(x)[0]


def _fenetre():
    """[aujourd'hui, aujourd'hui + HORIZON] — la fenetre d'une ANNONCE."""
    a = _dt.date.today()
    return a.isoformat(), (a + _dt.timedelta(days=HORIZON)).isoformat()


def drops_a_venir(sh, connus: List[str], trace: bool = False) -> List[Dict]:
    """Un drop = une SERIE (les 5 raretes d'un comic sont UNE annonce).
    Seuls les drops de la FENETRE sont candidats : la date fait foi."""
    vus = set(connus or [])
    notes = lire_notes(sh)                       # {cle -> note} de 🏆A-CLASSEMENT
    aujourdhui, horizon = _fenetre()
    par_serie: Dict[str, Dict] = {}
    illisibles, lointains, comic_day, echantillon = 0, 0, 0, []

    for tab, genre in TABS:
        for r in _records(sh, tab):
            brut = r.get("releaseDate")
            jour, ts, avec_heure = _quand(brut)
            if not jour:
                if str(brut or "").strip():
                    illisibles += 1
                    if len(echantillon) < 3:
                        echantillon.append(repr(brut)[:40])
                continue
            if jour < aujourdhui:
                continue                       # passe : ce n'est plus une news
            if jour > horizon:
                lointains += 1
                continue                       # trop loin : pas encore une news
            if est_comic_du_mercredi(genre, jour):
                comic_day += 1
                continue                       # VeVe Comic Book Day : du volume
            cle = (str(r.get("series_uuid") or "").strip()
                   or str(r.get("veve_uuid") or "").strip())
            if not cle or cle in vus:
                continue
            d = par_serie.setdefault(cle, {
                "cle": cle, "genre": genre, "jour": jour,
                "nom": str(r.get("veve_series_name") or r.get("name") or ""),
                "annee": str(r.get("start_year") or "").strip(),
                "marque": str(r.get("veve_brand") or "").strip(),
                "licence": str(r.get("veve_licensor") or "").strip(),
                "methode": str(r.get("drop_method") or "").strip(),
                "prix": r.get("store_price_gems"),
                "image": str(r.get("image_url") or "").strip(),
                "url": str(r.get("veve_url") or "").strip(),
                # VeVe-Exclusive : a mentionner dans la carte (demande Preda).
                "exclusive": str(r.get("veve_exclusive") or "").strip().upper() == "TRUE",
                "note": notes.get(cle, ""),          # note de classement (si dispo)
                "ts": ts, "avec_heure": avec_heure, "brut": str(brut)[:30],
                "lignes": [],
            })
            d["lignes"].append({
                "rarete": str(r.get("rarity") or "").strip().upper(),
                "variante": str(r.get("edition_type") or "").strip(),
                # Supply PAR RARETE (releaseAmount du tracker) -> leur somme = le
                # vrai total. `supply` (comic-level, recopie) reste le repli
                # collectibles.
                "supply": _n(r.get("supply_rarete") or r.get("supply")),
                # l'uuid de l'ELEMENT (≠ series_uuid) : c'est lui qui ouvre la
                # page d'un craft.
                "uuid": str(r.get("veve_uuid") or "").strip(),
            })
            if not d["image"] and r.get("image_url"):
                d["image"] = str(r["image_url"]).strip()
            if not d["prix"] and r.get("store_price_gems"):
                d["prix"] = r["store_price_gems"]

    if trace:
        print(f"Fenetre : {aujourdhui} -> {horizon} ({HORIZON} j). "
              f"{len(par_serie)} serie(s) dedans · {lointains} au-dela de "
              f"l'horizon · {comic_day} ligne(s) de comic du mercredi ecartee(s)"
              f" · {illisibles} date(s) illisible(s)"
              + (f" (ex. {', '.join(echantillon)})" if echantillon else ""),
              flush=True)

    for d in par_serie.values():
        d["lignes"].sort(key=lambda l: (ORDRE_RARETE.index(l["rarete"])
                                        if l["rarete"] in ORDRE_RARETE else 99))
        d["total"] = sum(l["supply"] for l in d["lignes"])
    return sorted(par_serie.values(), key=lambda d: (d["jour"], d["nom"]))


def cles_hors_fenetre(sh) -> List[str]:
    """Les series DEJA sorties — et ELLES SEULES.

    ⚠️ CORRIGE APRES LE 1er RUN REEL (14/07) : je memorisais TOUT le catalogue,
    y compris les drops A VENIR. Resultat : le garde-fou anti-avalanche avalait
    precisement ce qu'on voulait annoncer, et ces drops-la ne seraient JAMAIS
    sortis. Le 1er run doit dire « le passe, je le connais » — pas « l'avenir
    aussi ». Ce qui est a venir reste annoncable."""
    aujourdhui, horizon = _fenetre()
    out = []
    for tab, _g in TABS:
        for r in _records(sh, tab):
            jour = _date(r.get("releaseDate"))
            if jour and aujourdhui <= jour <= horizon:
                continue                      # a venir : on ne l'enterre pas
            cle = (str(r.get("series_uuid") or "").strip()
                   or str(r.get("veve_uuid") or "").strip())
            if cle:
                out.append(cle)
    return list(dict.fromkeys(out))


def cles_a_venir(sh) -> List[str]:
    return [d["cle"] for d in drops_a_venir(sh, connus=[])]


# ---------------------------------------------------------------------------
# La carte
# ---------------------------------------------------------------------------

def comic_day_a_venir(sh):
    """Le prochain VeVe Comic Book Day de la fenetre, et ses series.

    Meme logique que les drops, mais A LA MAILLE DU JOUR : trente comics le
    meme mercredi, c'est UN evenement, pas trente annonces."""
    aujourdhui, horizon = _fenetre()
    par_jour: Dict[str, Dict[str, Dict]] = {}
    tab, _genre = TABS[0]                         # les comics, et eux seuls
    for r in _records(sh, tab):
        jour, ts, _h = _quand(r.get("releaseDate"))
        if not jour or not (aujourdhui <= jour <= horizon):
            continue
        if not est_comic_du_mercredi("comic", jour):
            continue
        cle = (str(r.get("series_uuid") or "").strip()
               or str(r.get("veve_uuid") or "").strip())
        if not cle:
            continue
        d = par_jour.setdefault(jour, {}).setdefault(cle, {
            "cle": cle, "jour": jour, "ts": ts,
            "nom": str(r.get("veve_series_name") or r.get("name") or ""),
            "prix": r.get("store_price_gems"), "total": 0,
        })
        d["total"] += _n(r.get("supply_rarete") or r.get("supply"))
        if not d["prix"] and r.get("store_price_gems"):
            d["prix"] = r["store_price_gems"]

    if not par_jour:
        return None, []
    jour = min(par_jour)                          # le comic day le plus proche
    return jour, list(par_jour[jour].values())


def message_comic_day(jour: str, series: List[Dict], ping: bool) -> Dict:
    """UN message pour tout le Comic Book Day. **Trie par TIRAGE CROISSANT** :
    avant le drop il n'y a pas encore de ventes, donc le seul signal est la
    RARETE — les petits tirages en haut, c'est la seule chose qui distingue une
    pepite d'un remplissage."""
    series = sorted(series, key=lambda s: (s["total"] or 10 ** 9))
    ts = next((s["ts"] for s in series if s.get("ts")), 0)
    total = sum(s["total"] for s in series)

    lignes = []
    for s in series[:MAX_LIGNES_CD]:
        prix = _prix(s.get("prix"), "comic")
        prix = f" · {prix} 💎" if prix else ""
        lignes.append(f"`{s['total']:>6,} ex` **{s['nom']}**{prix}"
                      .replace(",", " "))
    reste = len(series) - MAX_LIGNES_CD
    if reste > 0:
        lignes.append(f"*… et {reste} autre(s) série(s).*")

    tete = f"{EMOJI_VEVE} "
    if ping and ROLE:
        tete += f"<@&{ROLE}> "
    contenu = f"{tete}📚 **VeVe Comic Book Day**".rstrip()

    entete = (f"🕗 Drop : **<t:{ts}:F>**\n"
              f"**{len(series)} séries** · {total:,} exemplaires au total"
              .replace(",", " "))
    desc = (entete + "\n\n" + "\n".join(lignes)
            + f"\n\n__**Liens**__\n[Tous les comics VeVe](<{LIEN_COMICS}>)")

    e = {"title": f"📚 VeVe Comic Book Day — {jour}", "color": 0x2ECC71,
         "description": desc[:4000],
         "footer": {"text": "ⓘ Trié par supply"}}
    if IMAGE_COMIC_DAY:
        e["image"] = {"url": IMAGE_COMIC_DAY}
    return {"content": contenu, "embeds": [e],
            "allowed_mentions": api.mentions([ROLE] if (ping and ROLE) else [])}


def _complet(d: Dict) -> str:
    """Ce qui manque pour publier. Une carte a trous ne part pas — mais une
    heure manquante n'est PAS un trou : on affiche alors la DATE seule
    (`<t:…:D>`) plutot que de retenir l'annonce. Ce qui compte, c'est le jour ;
    inventer une heure serait pire que de ne pas la dire."""
    if not d.get("nom"):
        return "pas de nom"
    if not d.get("ts"):
        return f"date de drop illisible (cellule : {d.get('brut', '?')!r})"
    if not d.get("lignes") or not d.get("total"):
        return "aucun supply connu (fiche pas encore enrichie ?)"
    return ""


def _prix(x, genre: str = "") -> str:
    """Le prix d'entree, en gems.

    ⚠️ LE PIEGE, PAYE DEUX FOIS (chantier classement, puis ici : « 798 gems »
    sur la carte du Comic Book Day). **Le `storePrice` des COMICS melange DEUX
    ECHELLES** : les vieux comics sont en GEMS (10, 15, 20), les recents en
    CENTIMES (798 = 7,98). Regle : **>= 100 -> diviser par 100, POUR LES COMICS
    SEULEMENT** — un collectible a 1 500 gems existe vraiment, lui.
    Idempotent : 7.98 reste 7.98."""
    try:
        v = float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return ""
    if genre == "comic" and v >= 100:
        v = v / 100.0
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _titre(d: Dict) -> str:
    licence = d.get("licence") or d.get("marque") or ""
    genre = "Comic" if d["genre"] == "comic" else "Collectible"
    quoi = f"{licence} {genre}".strip()
    nom = d["nom"]
    if d.get("annee") and f"({d['annee']})" not in nom:
        nom = f"{nom} ({d['annee']})"
    return f"{quoi}: **{nom}**"


def _lien(d: Dict) -> str:
    """L'URL de la page boutique.

    Le TYPE DE DROP decide de la famille de page — ET de l'identifiant :
      * un comic ou une serie de collectibles s'ouvre par son **series_uuid** ;
      * un CRAFT s'ouvre par l'uuid de son **ELEMENT** (verifie par Preda sur
        « Colossus x Wolverine » : le series_uuid menait a une page etrangere).
        C'est coherent : un craft n'a qu'une rarete, l'element EST le drop.
    Confondre les deux uuid ne donne pas une erreur, ca donne la page de
    QUELQU'UN D'AUTRE — le pire des bugs, celui qui a l'air de marcher."""
    methode = (d.get("methode") or "").upper()
    if d["genre"] == "comic":
        return f"{VEVE_BASE}/comics/{d['cle']}"
    if "CRAFT" in methode:
        uuid = next((l["uuid"] for l in d["lignes"] if l.get("uuid")), d["cle"])
        return f"{VEVE_BASE}/crafts/{uuid}"
    return f"{VEVE_BASE}/series/{d['cle']}"


def _emoji_marque(d: Dict) -> str:
    cle = (d.get("marque") or d.get("licence") or "").strip().lower()
    return EMOJI_MARQUES.get(cle, "")


def texte(d: Dict, ping: bool) -> str:
    tete = f"{EMOJI_VEVE} "
    if ping and ROLE:
        tete += f"<@&{ROLE}> "
    # `F` = date + heure ; `D` = date seule. Dans les deux cas Discord l'affiche
    # dans le FUSEAU DE CHAQUE LECTEUR — personne n'a rien a convertir.
    style = "F" if d.get("avec_heure") else "D"
    lignes = [f"{tete}{_titre(d)} {_emoji_marque(d)}".rstrip(),
              f"🕗 Drop date: **<t:{d['ts']}:{style}>** 🕗"]

    lignes.append("")                       # de l'air : la date respire

    for i, l in enumerate(d["lignes"]):
        nom = NOM_RARETE.get(l["rarete"], l["rarete"].title() or "—")
        # ⚠️ Le n° d'issue (edition_type, ex. « 1 ») est RETIRE : il n'apporte
        # rien. Le NOM DE COVER (Classic Cover, Vintage Variant…) prendra sa
        # place quand VeVe nous le donnera — il n'est pas dans le tracker.
        txt = f"**{nom}** | **{l['supply']:,} Editions**"
        # La DERNIERE rarete (la plus rare) est soulignee : c'est elle qu'on
        # cherche des yeux.
        lignes.append(f"__{txt}__" if i == len(d["lignes"]) - 1 else txt)

    label = "Total Comic Editions" if d["genre"] == "comic" else "Total Editions"
    lignes.append(f"**{label}: {d['total']:,}**")
    if d.get("exclusive"):
        lignes.append("💎 **VeVe-Exclusive**")
    lignes.append("")

    format_ = []
    if d.get("methode"):
        format_.append(f"Format **{d['methode']}**")
    p = _prix(d.get("prix"), d["genre"])
    if p:
        format_.append(f"Enter **{p}** 💎")
    # « Min. MCP Priority Bid » retire (constante, non pertinente) -> a la place,
    # la NOTE DE CLASSEMENT quand elle existe (le jugement de Preda), sinon rien.
    if d.get("note"):
        format_.append(f"Classement : **{d['note']}**")
    lignes.append(" | ".join(format_))
    lignes.append("")

    # Le lien est MASQUE et entre <> : sans les chevrons, Discord collerait un
    # deuxieme embed d'apercu sous la carte et volerait la vedette a l'image.
    lignes.append("__**Liens**__")
    lignes.append(f"[{LIEN_TEXTE}](<{_lien(d)}>)")
    lignes.append("")

    lignes.append("__**Participation**__")
    lignes.append("🇩rop /  🇲arket / ❌ Pass")
    return "\n".join(lignes)


# ═══ LE RATTRAPAGE DU MIROIR PUBLIC (03/08/2026) ═══
# Vecu ce matin : « miroir public KO pour "Chris Robots Will Kill" (Read timed
# out) ». La carte etait dans 📦DROP, la cle etait memorisee comme annoncee, et
# le miroir n'etait JAMAIS retente : ce drop n'aurait eu que les votes prives,
# et le module `retour` aurait lu une ligne de sondage public vide sans savoir
# pourquoi. ⭐⭐ Une erreur avalee pendant que l'etat avance : exactement le
# motif qui a coute six jours de republications le 28/07.
#
# ⛔ CE QU'IL NE FAUT SURTOUT PAS FAIRE : deduire les miroirs manquants en
# comparant `cles` et `miroir`. Au 1er run, `cles` recoit TOUTES les series hors
# fenetre (des centaines) — une telle deduction deverserait des centaines de
# cartes dans le salon public. ⭐ L'ECHEC SE NOTE LUI-MEME, on ne le devine pas :
# seule une cle explicitement inscrite dans `miroir_rate` est retentee.
RATTRAPAGE_MAX = int(os.environ.get("DISCORD_DROPS_MIROIR_RATTRAPAGE", "5"))
ESSAIS_MIROIR = int(os.environ.get("DISCORD_DROPS_MIROIR_ESSAIS", "3"))


def _miroir_rate(state: Dict, cle: str) -> None:
    rates = state.setdefault("miroir_rate", {})
    rates[cle] = int(rates.get(cle, 0)) + 1


def _miroir_ok(state: Dict, cle: str) -> None:
    (state.get("miroir_rate") or {}).pop(cle, None)


def poster_miroir(d: Dict, state: Dict) -> str:
    """La MEME carte dans 📘sondage-drop, **sans aucun ping**.

    Le salon public voit passer la carte et peut voter ; il n'est pas reveille
    pour autant (choix de Preda) — la vague est deja annoncee une fois cote
    investisseur. `ping=False` suffit : `message()` n'ajoute alors ni mention ni
    `allowed_mentions` autorisant un role.

    N'EMET AUCUNE EXCEPTION et ne rend jamais le run en echec : le miroir est un
    BONUS. Une carte publiee dans 📦DROP mais pas dans le public est un manque ;
    un run en echec parce que le miroir a hoquete serait une regression.
    """
    if not MIROIR_WEBHOOK:
        return ""
    try:
        mid = api.poster(MIROIR_WEBHOOK, MIROIR_THREAD, message(d, ping=False))
        if not mid:
            _miroir_rate(state, d["cle"])
            print(f"  ⚠️ miroir public : « {d['nom']} » n'a pas pu etre poste "
                  f"— la carte de 📦DROP, elle, est bien la. RETENTE au "
                  f"prochain passage.", flush=True)
            return ""
        state.setdefault("miroir", {})[d["cle"]] = mid
        _miroir_ok(state, d["cle"])
        n = api.reagir(salon_miroir(), mid, REACTIONS)
        if n < len(REACTIONS):
            print(f"  ⚠️ miroir public : {n}/{len(REACTIONS)} reactions posees "
                  f"sur « {d['nom']} » — sans elles, ce salon ne pourra pas "
                  f"voter (le bot est-il dans 📘sondage-drop ?).", flush=True)
        api.souffler()
        return mid
    except Exception as e:                                  # noqa: BLE001
        _miroir_rate(state, d["cle"])
        print(f"  ⚠️ miroir public KO pour « {d['nom']} » ({e}) — la carte de "
              f"📦DROP est bien la, le miroir sera RETENTE au prochain "
              f"passage.", flush=True)
        return ""


def rattraper_miroir(sh, state: Dict) -> int:
    """Les miroirs rates d'un passage precedent, retentes — et EUX SEULS.

    ⚠️ APPELE AVANT LA SORTIE « aucun drop neuf », pas apres. La lecon est deja
    ecrite plus bas pour le marquage « drop sorti » : place apres cette sortie,
    un traitement ne tourne QUE les jours ou il y a une nouveaute — c'est-a-dire
    presque jamais. Un miroir rate un jour calme doit se rattraper le lendemain,
    justement parce qu'il n'y a rien d'autre a faire ce jour-la.
    """
    rates = state.get("miroir_rate") or {}
    if not MIROIR_WEBHOOK or not rates:
        return 0
    # ⭐ `drops_a_venir(sh, [])` = TOUTE la fenetre, sans filtre d'etat : les
    # drops a rattraper sont justement ceux qui SONT deja dans `cles`.
    par_cle = {d["cle"]: d for d in drops_a_venir(sh, [])}
    faits = 0
    for cle, essais in sorted(rates.items(), key=lambda kv: -kv[1]):
        if faits >= RATTRAPAGE_MAX:
            print(f"📘 rattrapage : {RATTRAPAGE_MAX} par passage au maximum — "
                  f"le reste au prochain tour.", flush=True)
            break
        d = par_cle.get(cle)
        if d is None:
            rates.pop(cle, None)
            print(f"📘 rattrapage abandonne pour {cle} : le drop est sorti de "
                  f"la fenetre, une carte de sondage n'a plus de sens.",
                  flush=True)
            continue
        if essais >= ESSAIS_MIROIR:
            rates.pop(cle, None)
            print(f"⛔ miroir public : « {d['nom'] or cle} » abandonne apres "
                  f"{essais} essais. Ce n'est pas un hoquet reseau — verifier "
                  f"que le bot est bien dans 📘sondage-drop.", flush=True)
            continue
        # ⭐ Un refus de PLAFOND n'est pas un echec du miroir : on s'arrete
        # AVANT d'appeler, sinon on brulerait un essai pour une raison qui n'a
        # rien a voir avec Discord.
        if api.envois() >= api.PLAFOND:
            print(f"📘 rattrapage suspendu : plafond de messages atteint. "
                  f"Aucun essai n'est consomme, on reprend au prochain "
                  f"passage.", flush=True)
            break
        if _complet(d):
            continue                    # fiche incomplete : elle repassera
        if poster_miroir(d, state):
            faits += 1
    # Une cle a 0 n'a plus rien a dire : on garde l'etat minuscule.
    state["miroir_rate"] = {k: v for k, v in rates.items() if v}
    if faits:
        print(f"📘 {faits} miroir(s) public(s) rattrape(s).", flush=True)
    return faits


def marquer_miroir(state: Dict, dates: Dict[str, int]) -> int:
    """Le « ✅ DROP SORTI » repercute sur les cartes du salon public.

    Meme mecanique que cote investisseur, mais sur `state['miroir']` et avec sa
    PROPRE liste de cles deja marquees (`state['miroir_sortis']`) : les deux
    salons ne sont pas au meme rythme, et partager la liste ferait sauter le
    marquage de l'un des deux — silencieusement.
    """
    if not MIROIR_WEBHOOK or not state.get("miroir"):
        return 0
    try:
        sous_etat = state.setdefault("miroir_sortis", {})
        return sortis.marquer(
            state.get("miroir", {}), dates, sous_etat,
            lire=lambda mid: api.lire_message(salon_miroir(), mid),
            editer=lambda mid, charge: api.editer(MIROIR_WEBHOOK, MIROIR_THREAD,
                                                  mid, charge),
            mentions_vides=api.mentions([]),
            souffler=api.souffler,
            journal=lambda m: print(f"[miroir] {m}", flush=True))
    except Exception as e:                                  # noqa: BLE001
        print(f"⚠️ marquage du miroir KO ({e}) — ignore.", flush=True)
        return 0


def dates_par_cle(sh) -> Dict[str, int]:
    """{cle_serie: timestamp du drop}, SANS filtre de fenetre.

    `drops_a_venir()` ecarte volontairement le passe — c'est justement le
    passe qui nous interesse ici. On relit donc les deux onglets sans borne.
    La cle est calculee EXACTEMENT comme a la publication : une formule qui
    divergerait ne retrouverait aucune carte, et le marquage ne marquerait
    rien, en silence.
    """
    out: Dict[str, int] = {}
    for tab, _genre in TABS:
        for r in _records(sh, tab):
            _jour, ts, _avec_heure = _quand(r.get("releaseDate"))
            if not ts:
                continue
            cle = (str(r.get("series_uuid") or "").strip()
                   or str(r.get("veve_uuid") or "").strip())
            if cle:
                out.setdefault(cle, ts)
    return out


def message(d: Dict, ping: bool) -> Dict:
    """L'illustration part dans un embed sans titre : Discord l'affiche en grand
    SOUS le texte, exactement comme sur la carte de Preda."""
    m = {"content": texte(d, ping),
         "allowed_mentions": api.mentions([ROLE] if (ping and ROLE) else [])}
    if d.get("image"):
        e = {"image": {"url": d["image"]}, "color": 0x1F8BF0}
        if d.get("url"):
            e["url"] = d["url"]
        m["embeds"] = [e]
    return m


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID", "").strip()
    if not sheet_id:
        print("SHEET_ID env var is not set.", file=sys.stderr)
        return 2
    wh = api.webhook(MODULE)
    sh = _client().open_by_key(sheet_id)
    state = api.load_state(STATE_PATH, wh, THREAD)
    premier = "cles" not in state

    if premier:
        # Le 1er run apprend LE PASSE, et rien que le passe : les drops a venir
        # sont exactement ce qu'on veut annoncer.
        state["cles"] = cles_hors_fenetre(sh)
        print(f"1er run -> {len(state['cles'])} series HORS FENETRE memorisees "
              f"(le passe et le lointain : seuls les drops des {HORIZON} "
              f"prochains jours restent annoncables).", flush=True)

    if REJOUER:
        avenir = set(cles_a_venir(sh))
        avant = len(state.get("cles", []))
        state["cles"] = [c for c in state.get("cles", []) if c not in avenir]
        print(f"REJOUER : {avant - len(state['cles'])} drop(s) a venir oublies "
              f"de l'etat — ils vont etre (re)annonces.", flush=True)

    neufs = drops_a_venir(sh, state.get("cles", []), trace=True)
    print(f"{len(neufs)} serie(s) neuve(s) a annoncer.", flush=True)
    for d in neufs[:5]:
        heure = "avec heure" if d.get("avec_heure") else \
            f"SANS heure (cellule : {d.get('brut')!r}) -> date seule"
        print(f"   · {d['jour']} — {d['nom'] or d['cle']} "
              f"({len(d['lignes'])} raretes, supply {d['total']}, {heure})",
              flush=True)

    if len(neufs) > MAX_NEUFS:
        print(f"{len(neufs)} drops « neufs » (> {MAX_NEUFS}) -> on memorise "
              f"sans annoncer. VeVe ne sort pas 20 drops dans la nuit : si ca "
              f"arrive, c'est un bug, et on ne reveille pas le serveur pour un "
              f"bug. (Pour forcer : DISCORD_DROPS_MAX_NEUFS plus haut.)",
              flush=True)
        state["cles"] = list(dict.fromkeys(
            list(state.get("cles", [])) + [d["cle"] for d in neufs]))
        neufs = []

    # ═══ 📦 MARQUER LES DROPS PASSES — AVANT TOUTE SORTIE ═══
    # ⚠️ CORRIGE LE 20/07/2026. Ce bloc etait place plus bas, APRES le
    # `if not neufs: ... return 0` juste en dessous. Consequence : le
    # marquage ne tournait QUE les jours ou il y avait un nouveau drop a
    # annoncer — c'est-a-dire presque jamais. Or marquer « drop sorti »
    # concerne les drops PASSES : ca n'a aucun rapport avec l'existence de
    # nouveautes du jour.
    # Le commentaire de la branche ci-dessous mettait deja en garde contre
    # ce piege pour le Comic Book Day (« Sortie prematuree = un message qui
    # ne part jamais »). La lecon etait ecrite ; elle n'avait pas ete
    # appliquee une branche plus loin.
    if wh:
        dates = dates_par_cle(sh)
        n_sortis = sortis.marquer(
            state.get("messages", {}), dates, state,
            lire=lambda mid: api.lire_message(THREAD, mid),
            editer=lambda mid, charge: api.editer(wh, THREAD, mid, charge),
            mentions_vides=api.mentions([]),
            souffler=api.souffler)
        if n_sortis:
            print(f"📦 {n_sortis} carte(s) marquee(s) « drop sorti ».",
                  flush=True)
        n_miroir = marquer_miroir(state, dates)
        if n_miroir:
            print(f"📘 {n_miroir} carte(s) du salon public marquee(s) "
                  f"« drop sorti ».", flush=True)
        # ⚠️ ICI, et pas plus bas : la sortie « aucun drop neuf » est juste
        # apres, et un rattrapage place derriere elle ne tournerait que les
        # jours ou il y a une nouveaute. Meme piege que le marquage ci-dessus,
        # corrige le 20/07 — la lecon est ecrite trois lignes plus haut.
        rattraper_miroir(sh, state)

    if not neufs:
        # ⚠️ Le Comic Book Day doit etre annonce MEME s'il n'y a aucun autre
        # drop : c'est un evenement a part entiere. (Sortie prematuree = un
        # message qui ne part jamais.)
        cd = annoncer_comic_day(sh, state, wh, ping=True)
        api.save_state(STATE_PATH, state, wh, THREAD)
        print(f"Drops : aucun drop individuel a annoncer (comic day : {cd}).",
              flush=True)
        _log(sheet_id, "OK", {"neufs": 0, "comic_day": cd,
                              "duree": f"{time.time() - t0:.0f}s"})
        return 0

    ok, postes, sautes = True, [], []
    # UN SEUL PING POUR LA VAGUE : la 1re carte porte la mention, les suivantes
    # partent en silence. Trois drops le meme matin = trois cartes, UNE notif.
    premier_ping = True

    for d in neufs[:MAX_CARTES]:
        manque = _complet(d)
        if manque:
            sautes.append(f"{d['nom'] or d['cle']} ({manque})")
            continue                    # PAS memorise : il repassera enrichi
        payload = message(d, ping=premier_ping)
        if not wh:
            print(f"\n[SIMULATION — pas de webhook]\n{payload['content']}\n",
                  flush=True)
            mid = "simulation"
        else:
            mid = api.poster(wh, THREAD, payload)
        if not mid:
            ok = False
            continue
        premier_ping = False
        state.setdefault("cles", []).append(d["cle"])
        # On garde l'id de la carte : le module RETOUR ira y relire le sondage
        # (D / M / ❌) 24 h plus tard, et pourra la citer en lien.
        state.setdefault("messages", {})[d["cle"]] = mid
        postes.append(d["nom"])
        if wh:
            n = api.reagir(THREAD, mid, REACTIONS)
            if n < len(REACTIONS):
                print(f"⚠️ {n}/{len(REACTIONS)} reactions posees sur "
                      f"« {d['nom']} » — la carte est publiee quand meme.",
                      flush=True)
            api.souffler()
            # ═══ LE MIROIR PUBLIC (📘sondage-drop), sans ping ═══
            poster_miroir(d, state)

    if sautes:
        print(f"⚠️ {len(sautes)} drop(s) SAUTE(S), fiche incomplete — ils "
              f"repasseront quand le catalogue les aura enrichis : "
              f"{'; '.join(sautes[:5])}", flush=True)

    # ═══ LE COMIC BOOK DAY : UN message pour tout le mercredi ═══
    cd = annoncer_comic_day(sh, state, wh, ping=premier_ping)

    state["cles"] = list(dict.fromkeys(state.get("cles", [])))
    api.save_state(STATE_PATH, state, wh, THREAD)

    resume = {"neufs": len(neufs), "postes": len(postes),
              "sautes": len(sautes), "comic_day": cd,
              "titres": " | ".join(postes[:3]),
              "duree": f"{time.time() - t0:.0f}s"}
    _log(sheet_id, "OK" if ok else "ECHEC", resume)
    print(f"Drops Discord : {resume}", flush=True)
    return 0 if ok else 1


def annoncer_comic_day(sh, state: Dict, wh: str, ping: bool) -> str:
    """Poste (ou reecrit) LE message du prochain Comic Book Day.
    Un message par mercredi : tant que la date approche, il est EDITE (VeVe
    ajoute parfois des series apres coup) ; le mercredi suivant en ouvre un
    nouveau. Le role n'est pinge qu'a la CREATION — un message reecrit ne doit
    pas re-sonner."""
    jour, series = comic_day_a_venir(sh)
    if not jour or not series:
        return "aucun"
    ids = state.setdefault("comic_day", {})
    mid = ids.get(jour)
    # 🔎 DIAGNOSTIC (Preda a vu un ANCIEN message reutilise/edite au lieu d'un
    # NEUF le mercredi suivant). En theorie la cle = la date du mercredi, donc un
    # mercredi neuf ouvre un nouveau post. On TRACE la decision : si un mercredi
    # neuf ressort « deja poste », le bug (etat / cle) est ici, en clair.
    print(f"  🔎 Comic Book Day cible={jour} — "
          f"{'DEJA poste -> edition' if mid else 'nouveau -> post neuf'} "
          f"(mercredis en etat : {', '.join(sorted(ids)) or 'aucun'})", flush=True)
    payload = message_comic_day(jour, series, ping=(ping and not mid))
    if not wh:
        print(f"\n[SIMULATION]\n{payload['content']}\n"
              f"{payload['embeds'][0]['description']}\n", flush=True)
        return f"{jour} (simulation, {len(series)} series)"
    neuf = (api.editer(wh, THREAD, mid, payload) if mid
            else api.poster(wh, THREAD, payload))
    if not neuf:
        return "echec"
    ids[jour] = neuf
    for vieux in sorted(ids)[:-8]:                # l'etat reste minuscule
        ids.pop(vieux, None)
    print(f"Comic Book Day {jour} : {len(series)} series, message "
          f"{'reecrit' if mid == neuf else 'poste'} ({neuf}).", flush=True)
    api.souffler()
    return f"{jour} ({len(series)} series)"


def _log(sheet_id: str, statut: str, resume: Dict) -> None:
    try:
        append_log(sheet_id, "discord_drops", statut,
                   "; ".join(f"{k}={v}" for k, v in resume.items()))
    except Exception:                                       # noqa: BLE001
        pass


if __name__ == "__main__":
    sys.exit(run())

# FIN discord_drops.py v9 — une serie = une carte, une vague = un ping, les
# reactions posees par le bot (un webhook ne sait pas reagir), et la meme carte
# en miroir MUET dans le salon public 📘sondage-drop.
