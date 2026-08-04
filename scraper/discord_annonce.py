# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/discord_annonce.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""📢 L'ANNONCE DE DEBUT DE MOIS — le 2 de chaque mois, dans « Annonces ».

La newsletter sort le 1er ; l'annonce vient juste apres.

DEUX MESSAGES, EN TEXTE — **PAS D'EMBED** (« l'embed rend mal », Preda 04/08) :
  1. l'entete : « Annonces 02/09 » + le ping + l'accroche + l'illustration ;
  2. le corps : « Ce mois-ci N Drops dont : » + le palmares + « 👀 Et maintenant ? »
     + les liens (parrainage, classements, X, Récap) + VeVe Investor.

⭐⭐⭐ TROIS FORMES ESSAYEES, ET C'EST LA LEcON DU LOT : un embed invente, puis
du texte recopie sur son vrai post, puis 4 embeds, puis ce texte-ci. **Le
gabarit d'un message qui remplace un humain, c'est ce que l'humain ecrit** — un
cadre colore ne l'est pas. ⛔ Demander la capture du vrai post AVANT d'ecrire le
rendu, pas apres.

🔴 UN EMBED NE PING PAS. Ecrire « @everyone » dans un embed n'alerte PERSONNE :
Discord le rend en texte gris. Le ping vit donc dans le `content` du 1er
message — ce n'est pas un choix de mise en page, c'est la seule facon que ca
sonne. (Raison de plus de rester en texte.)

CE QU'IL CALCULE — 0 requete VeVe, il lit le Sheet comme `discord_drops`
----------------------------------------------------------------------
* le mois PRECEDENT (nom francais, bornes) et **le nombre de series sorties,
  HORS comics du mercredi** (« 171 Drops ») ;
* **CE QUI S'EST LE PLUS VENDU** : les mints on-chain de `ChainItems`, sommes
  sur le mois, par serie ;
* le **theme** du mois = la licence dominante de la selection, avec un **repli
  neutre** : si aucune licence n'ecrase, on ne nomme pas de theme ;
* le teaser « Et maintenant ? » = `dd.drops_a_venir`, le MEME calcul que 📦DROP.

LES TROIS FILTRES DE LA LISTE (decisions Preda du 04/08)
--------------------------------------------------------
1. **PAS D'ARTWORK** : une serie dont TOUTES les lignes sont des `ARTIST_PROOF`
   (edition « AP », tirage 1). ⚠️ Un AP isole dans une serie normale ne fait pas
   de la serie un artwork — sinon on jetterait la serie entiere pour une ligne.
2. **LES COMICS SEULEMENT S'ILS SONT SOLD OUT**, *et* hors mercredi (les deux
   filtres s'ajoutent — choix de Preda). Le VeVe Comic Book Day deverse 115
   series sur 142 en mai : c'est du volume, pas de l'actualite.
3. **7 lignes au maximum.**

⚠️ CE QUE JE NE PEUX PAS PROUVER HORS LIGNE : que le `supply` d'un comic soit
bien son tirage REEL et non son plafond mintable. S'il porte le plafond, aucun
comic ne passera jamais le filtre « sold out ». Le module **compte et ecrit**
dans les logs combien de comics etaient candidats et combien ont passe le
filtre — le 1er vrai run tranchera. ⭐ Une hypothese qu'on ne peut pas verifier
se transforme en compteur, pas en silence.

🚨 @EVERYONE — POURQUOI CE MODULE EST LE PLUS DANGEREUX DU HUB
--------------------------------------------------------------
Texte 100 % automatique + ping de tout le serveur. Les garde-fous ne sont pas
des precautions, ce sont des conditions d'existence :

1. **LE WEBHOOK NE RETOMBE SUR RIEN.** On n'appelle **PAS** `api.webhook()` :
   cette fonction se rabat sur `DISCORD_HUB_WEBHOOK` quand le secret du module
   manque. Un secret oublie deverserait donc un @everyone dans le forum du hub.
   Meme lecon que le miroir de `discord_drops` : **un module mal configure doit
   rester MUET, pas se tromper de salon.**
2. **PAS DE POST DU TOUT** si la selection est vide, si le Sheet est illisible,
   ou si la fenetre de ventes est trouee (voir COUVERTURE_MIN). Mieux vaut rien
   qu'un message faux — et ca vaut double quand on sonne tout le serveur.
3. **UN INTERRUPTEUR** (`DISCORD_ANNONCE_EVERYONE`, ferme par defaut) coupe le
   ping sans toucher au code. ⭐ Il est lu **a l'execution**, pas a l'import :
   un reglage qu'on peut poser sans que le code le lise est un no-op silencieux.
4. **ON NE PEUT PAS VENDRE PLUS QUE LE TIRAGE.** Les ventes sont bornees au
   tirage, et un depassement est ECRIT dans les logs — c'est le symptome d'un
   `supply` faux, pas un record de vente.

⏰ LE 2, MAIS PAS SEULEMENT LE 2
-------------------------------
Les crons GitHub sont en UTC (+2 h l'ete) et arrivent avec 2 h 20 a 3 h 15 de
retard mesure — et GitHub **abandonne** des runs planifies quand il est charge.
Un module « du 2 » doit donc tolerer de tourner le 2 a 23 h **ou le 3** :
`DISCORD_ANNONCE_TOLERANCE` ouvre la fenetre, et la cle `YYYY-MM` (le mois
ANNONCE, pas le jour du run) garantit qu'il ne postera pas deux fois.
⛔ Aucun cron dedie : le hub passe deja tous les jours, et c'est precisement ce
qui donne au module son rattrapage du 3. Un cron « 0 8 2 * * » n'aurait, lui,
aucune seconde chance.

Env :
  SHEET_ID, GOOGLE_SERVICE_ACCOUNT_JSON     (lecture du Sheet)
  DISCORD_ANNONCE_WEBHOOK    (SECRET du salon « Annonces » ; VIDE = simulation,
                              JAMAIS de repli sur un autre salon)
  DISCORD_ANNONCE_THREAD     (vide = salon normal ; un id = post de forum)
  DISCORD_ANNONCE_EVERYONE   (true = le ping part ; defaut FALSE)
  DISCORD_ANNONCE_JOUR       (2)   · DISCORD_ANNONCE_TOLERANCE (1 -> le 2 et le 3)
  DISCORD_ANNONCE_MAX        (7 lignes)
  DISCORD_ANNONCE_EMOJI      (🐱 — un emoji custom s'ecrit `<:nom:id>`)
  DISCORD_ANNONCE_LIENS_MASQUES (true = `[nom](url)` ; false = le nom puis l'URL)
  DISCORD_ANNONCE_SEUIL_THEME(0.40 de part de ventes pour nommer un theme)
  DISCORD_ANNONCE_COUVERTURE (20 journees de ChainItems minimum)
  DISCORD_ANNONCE_STATE      (data/discord_annonce_state.json)
  DISCORD_ANNONCE_CROCHETS   (data/annonce_crochets.json — newsletter + image)
  DISCORD_ANNONCE_IMAGE      (repli d'illustration, vide en v1)
  DISCORD_ANNONCE_FORCE      (true = ignore le jour ET l'anti-doublon)
"""

from __future__ import annotations

import calendar as _cal
import datetime as _dt
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from scraper import discord_api as api
from scraper import discord_drops as dd
from scraper import discord_retour as dr
from scraper.sheets import _client, append_log

MODULE = "annonce"

STATE_PATH = os.environ.get("DISCORD_ANNONCE_STATE",
                            os.path.join("data", "discord_annonce_state.json"))
CROCHETS_PATH = os.environ.get("DISCORD_ANNONCE_CROCHETS",
                               os.path.join("data", "annonce_crochets.json"))

MAX_CONTENU = 2000                       # limite Discord d'un message texte
# SUPPRESS_EMBEDS (1 << 2) : Discord ne fabrique AUCUN apercu pour les URL du
# message. C'est le seul moyen propre — mettre les liens entre `<…>` marche
# aussi, mais il faudrait le faire URL par URL et ne rien oublier a jamais.
SUPPRIMER_VIGNETTES = 4

MOIS_FR = ["", "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"]

# ═══ LES CONSTANTES DE VeVe FRANCE ═══
# Recopiees sur un VRAI post de Preda (celui du 03/06/2026) : c'est lui le
# gabarit, pas mon idee de ce qu'une annonce devrait etre.
GUILDE = "310073753709182977"
LIEN_PARRAINAGE = "https://veve.sjv.io/VeVeFrance"
LIEN_X = "https://twitter.com/VeVe_France"
LIEN_INVESTOR = f"https://discord.com/channels/{GUILDE}/1022145175499329616"
# ⭐ Les salons s'ecrivent `<#id>` : Discord les rend colores, avec leur vrai
# nom, et le lien SUIT un salon renomme. ⚠️ `allowed_mentions` ne bride PAS les
# mentions de salon (seulement les membres, les roles et @everyone) : un
# `<#id>` reste cliquable meme ping ferme.
SALON_CLASSEMENTS = "1075084049632206920"
SALON_RECAP = "970395941607710840"

PHRASE_INVESTOR = ("Et si vous voulez mettre toutes les chances de réussite de "
                   "votre côté, essayez l'accès aux services professionnels de "
                   "VeVe Investor !")

# Ce qui fait un « artwork » : la rarete ARTIST_PROOF (edition « AP », tirage 1).
# Choix de Preda du 04/08 — c'est le seul marqueur present dans les donnees.
RARETE_AP = "ARTIST_PROOF"
EDITION_AP = "AP"


# ---------------------------------------------------------------------------
# Les reglages — LUS A L'EXECUTION, jamais figes a l'import
# ---------------------------------------------------------------------------
# ⭐⭐ Un reglage pose en variable sans etre lu par le code est un no-op
# silencieux. Le figer a l'import en est la version sournoise : le banc pose la
# variable, le module ne la voit pas, et le test passe pour de mauvaises
# raisons. Ici, chaque reglage se relit quand on s'en sert.

def _bool(cle: str, defaut: str = "false") -> bool:
    return os.environ.get(cle, defaut).strip().lower() in ("1", "true", "oui",
                                                           "yes")


def webhook() -> str:
    """🔴 LE SECRET DU SALON « Annonces », ET RIEN D'AUTRE.

    Pas de `api.webhook("annonce")` : cette fonction retombe sur
    `DISCORD_HUB_WEBHOOK`. Un secret manquant enverrait alors un @everyone dans
    le forum du hub, sans qu'aucune erreur ne soit levee. Vide = SIMULATION."""
    return os.environ.get("DISCORD_ANNONCE_WEBHOOK", "").strip()


def thread() -> str:
    """Salon NORMAL par defaut -> vide (le `_q` de `discord_api` retire un
    thread_id vide, correctif venu du module feed)."""
    return os.environ.get("DISCORD_ANNONCE_THREAD", "").strip()


def everyone_ouvert() -> bool:
    """L'interrupteur d'arret. FERME par defaut : le premier mois se regarde
    tourner avant de sonner tout le serveur."""
    return _bool("DISCORD_ANNONCE_EVERYONE", "false")


def force() -> bool:
    return _bool("DISCORD_ANNONCE_FORCE", "false")


def jour_cible() -> int:
    return int(os.environ.get("DISCORD_ANNONCE_JOUR", "2"))


def tolerance() -> int:
    return int(os.environ.get("DISCORD_ANNONCE_TOLERANCE", "1"))


def max_lignes() -> int:
    return int(os.environ.get("DISCORD_ANNONCE_MAX", "7"))


def emoji() -> str:
    """L'emoji de tete (« 🐱 Annonces 02/09 »). Reglable : celui de Preda est
    peut-etre un emoji PERSONNALISE du serveur, qui s'ecrit `<:nom:id>` — un
    webhook ne peut pas le poster autrement."""
    return os.environ.get("DISCORD_ANNONCE_EMOJI", "🐱").strip()


def seuil_theme() -> float:
    return float(os.environ.get("DISCORD_ANNONCE_SEUIL_THEME", "0.40"))


def couverture_min() -> int:
    return int(os.environ.get("DISCORD_ANNONCE_COUVERTURE", "20"))


# ---------------------------------------------------------------------------
# LE CALENDRIER — le mois annonce, la fenetre de publication, la cle
# ---------------------------------------------------------------------------

def aujourdhui() -> _dt.date:
    """Heure de PARIS (UTC+2 l'ete), comme feed et calendrier. Le hub tourne a
    07:45 UTC : le jour est le meme des deux cotes, mais on l'ecrit — un fuseau
    non ecrit se lit dans celui du lecteur."""
    return (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=2)).date()


def est_le_jour(jour: Optional[_dt.date] = None) -> bool:
    """Le 2… et les jours de rattrapage. GitHub abandonne des runs planifies :
    exiger le 2 pile, c'est accepter de sauter un mois en silence."""
    j = (jour or aujourdhui()).day
    cible = jour_cible()
    return cible <= j <= cible + tolerance()


def mois_annonce(jour: Optional[_dt.date] = None) -> Tuple[int, int]:
    """Le mois PRECEDENT — (annee, mois). C'est LUI l'identite du message : un
    run du 2 et un run de rattrapage du 3 annoncent le meme mois, donc portent
    la meme cle. (Meme principe que `discord_feed`, qui date sa semaine sur le
    dernier jour LU et non sur « aujourd'hui ».)"""
    j = jour or aujourdhui()
    premier = j.replace(day=1)
    dernier_du_precedent = premier - _dt.timedelta(days=1)
    return dernier_du_precedent.year, dernier_du_precedent.month


def cle_mois(jour: Optional[_dt.date] = None) -> str:
    an, mo = mois_annonce(jour)
    return "%04d-%02d" % (an, mo)


def bornes(an: int, mo: int) -> Tuple[str, str]:
    """(« 2026-07-01 », « 2026-07-31 »)."""
    fin = _cal.monthrange(an, mo)[1]
    return "%04d-%02d-01" % (an, mo), "%04d-%02d-%02d" % (an, mo, fin)


def jours_du_mois(an: int, mo: int) -> List[str]:
    fin = _cal.monthrange(an, mo)[1]
    return ["%04d-%02d-%02d" % (an, mo, d) for d in range(1, fin + 1)]


# ---------------------------------------------------------------------------
# LES SERIES DU MOIS — la boucle est a moi, les regles restent chez elles
# ---------------------------------------------------------------------------

def series_du_mois(sh, an: int, mo: int) -> List[Dict[str, Any]]:
    """TOUTES les series dont la date de sortie tombe dans le mois — une SERIE,
    pas une ligne de rarete (les 5 raretes d'un comic sont UNE sortie).

    ⚠️ ON NE FILTRE RIEN ICI, ET C'EST VOULU : le COMPTEUR (`compter_drops`) et
    la LISTE (`retenir`) n'ecartent pas les memes choses, et chacun dit sa
    regle chez lui. **Compter et choisir sont deux gestes differents ; les
    melanger donne un total qui ne correspond a rien.**

    Regles empruntees, jamais recopiees : `dd._quand` (la date), `dd._n` (les
    nombres), `dd.est_comic_du_mercredi` (le Comic Book Day). La forme rendue
    est celle de `dd.drops_a_venir` : c'est ce qui permet a `dd._lien` de
    fonctionner dessus **sans que je redefinisse l'uuid d'un craft** — le bug
    qui a l'air de marcher."""
    debut, fin = bornes(an, mo)
    par_serie: Dict[str, Dict[str, Any]] = {}

    for tab, genre in dd.TABS:
        for r in dd._records(sh, tab):
            jour, ts, avec_heure = dd._quand(r.get("releaseDate"))
            if not jour or not (debut <= jour <= fin):
                continue
            cle = (str(r.get("series_uuid") or "").strip()
                   or str(r.get("veve_uuid") or "").strip())
            if not cle:
                continue
            d = par_serie.setdefault(cle, {
                "cle": cle, "genre": genre, "jour": jour, "ts": ts,
                "avec_heure": avec_heure,
                "nom": str(r.get("veve_series_name") or r.get("name") or ""),
                "annee": str(r.get("start_year") or "").strip(),
                "marque": str(r.get("veve_brand") or "").strip(),
                "licence": str(r.get("veve_licensor") or "").strip(),
                "methode": str(r.get("drop_method") or "").strip(),
                "exclusive": str(r.get("veve_exclusive") or "").strip().upper() == "TRUE",
                "mercredi": dd.est_comic_du_mercredi(genre, jour),
                "lignes": [],
            })
            d["lignes"].append({
                "rarete": str(r.get("rarity") or "").strip().upper(),
                "edition": str(r.get("edition_type") or "").strip().upper(),
                "supply": dd._n(r.get("supply_rarete") or r.get("supply")),
                "uuid": str(r.get("veve_uuid") or "").strip(),
            })

    for d in par_serie.values():
        # ⚠️ LE TIRAGE N'EST PAS UNE SOMME POUR UN COMIC : `supply` y est celui
        # de la SERIE, recopie sur chaque rarete. `dr.total_serie` porte cette
        # cicatrice (Captain America #7, SOLD OUT affiche a 20 %) — on l'appelle,
        # on ne la reapprend pas.
        d["total"] = dr.total_serie(d["genre"],
                                    [l["supply"] for l in d["lignes"]])
    return list(par_serie.values())


def compter_drops(series: List[Dict[str, Any]]) -> int:
    """« Ce mois-ci **N Drops** dont : » — LE COMPTEUR, hors comics du mercredi
    (decision Preda du 04/08).

    ⭐⭐ COMPTER ET CHOISIR RESTENT DEUX GESTES DIFFERENTS : ce total ignore le
    deversement du Comic Book Day, mais garde tout le reste (y compris ce que
    la LISTE ecarte : les artworks, les comics non sold out, les series a 0
    vente). Annoncer « 171 Drops » puis n'en citer que 7 est normal ; annoncer
    un total qui ne correspond a aucune realite ne l'est pas."""
    return sum(1 for d in series if not d.get("mercredi"))


def est_artwork(d: Dict[str, Any]) -> bool:
    """Une serie d'ARTWORK : toutes ses lignes sont des Artist Proof (tirage 1).

    ⚠️ « toutes », pas « au moins une » : un AP glisse dans une serie normale ne
    doit pas faire disparaitre la serie entiere. Un filtre trop large ne se
    plaint jamais — il se contente de faire le vide."""
    lignes = d.get("lignes") or []
    if not lignes:
        return False
    return all(l.get("rarete") == RARETE_AP or l.get("edition") == EDITION_AP
               for l in lignes)


# ---------------------------------------------------------------------------
# LES VENTES DU MOIS — le critere de Preda (04/08) : « le plus vendu »
# ---------------------------------------------------------------------------
# ⚠️ `ChainItems` ne garde que 35 jours (`chain_sheets.RETENTION_DAYS`). Le 2 du
# mois, le mois passe tient tout juste dedans — le 5, il serait deja rogne par
# le debut. D'ou la COUVERTURE : on compte les journees reellement presentes et
# on refuse de classer sur une fenetre trouee. ⭐ Un classement partiel ne se
# signale pas tout seul : il a exactement l'air d'un classement.

def jours_couverts(sh, jours: List[str]) -> List[str]:
    """Les journees du mois qui existent VRAIMENT dans ChainItems."""
    voulus = set(jours)
    vus = {str(r.get("date") or "")[:10]
           for r in dd._records(sh, dr.ITEMS_TAB)}
    return sorted(vus & voulus)


def ventes_du_mois(sh, jours: List[str]) -> Dict[str, int]:
    """{veve_uuid: mints} sur les journees demandees.

    `dr.chaine_par_uuid` fait deja exactement ca (et lit l'onglet une fois) —
    une seule facon de compter un mint dans tout le depot."""
    return {u: v.get("mints", 0)
            for u, v in dr.chaine_par_uuid(sh, jours).items()}


def classer(series: List[Dict[str, Any]],
            ventes: Dict[str, int]) -> List[Dict[str, Any]]:
    """Chaque serie recoit ses ventes, puis on trie du plus vendu au moins
    vendu. Les series a 0 vente sortent : « notable » veut dire quelque chose.

    🔴 LE GARDE-FOU DE PREDA : **on ne peut pas vendre plus qu'il n'y a de
    tirage.** Un depassement n'est pas un record, c'est le symptome d'un
    `supply` faux (ou d'un mint compte deux fois) — on borne, et on l'ECRIT.
    ⭐ Un chiffre impossible qu'on publie tel quel discredite tous les autres."""
    out = []
    for d in series:
        d = dict(d)
        brut = sum(ventes.get(l["uuid"], 0)
                   for l in d["lignes"] if l.get("uuid"))
        total = d.get("total") or 0
        if total and brut > total:
            print(f"⚠️ annonce : « {d.get('nom')} » — {brut} ventes pour un "
                  f"tirage de {total}. On borne au tirage : un chiffre "
                  f"impossible est un `supply` faux, pas un record.",
                  flush=True)
            brut = total
        d["ventes"] = brut
        if brut > 0:
            out.append(d)
    out.sort(key=lambda d: (-d["ventes"], d.get("nom", "")))
    return out


def retenir(classees: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """LES TROIS FILTRES DE LA LISTE (decisions Preda du 04/08), et ils sont
    BAVARDS : chaque famille d'ecartes est comptee dans les logs.
    ⭐ Un filtre silencieux est un mensonge par omission — et c'est le seul
    moyen de savoir, au 1er vrai run, si le `supply` des comics permet ou non
    de detecter un sold out."""
    gardees, art, merc, pas_epuise, comics_vus = [], 0, 0, 0, 0
    for d in classees:
        if est_artwork(d):
            art += 1
            continue
        if d["genre"] == "comic":
            comics_vus += 1
            if d.get("mercredi"):
                merc += 1
                continue
            if not dr.est_epuise(d.get("ventes", 0), d.get("total", 0)):
                pas_epuise += 1
                continue
        gardees.append(d)
    sortie = gardees[:max_lignes()]
    print(f"annonce : {len(sortie)} serie(s) citee(s) sur {len(gardees)} "
          f"eligible(s) · ecartees : {art} artwork(s), {merc} comic(s) du "
          f"mercredi, {pas_epuise} comic(s) non sold out (sur {comics_vus} "
          f"comic(s) vendus ce mois-ci).", flush=True)
    return sortie


def theme(selection: List[Dict[str, Any]]) -> str:
    """La licence dominante de la selection, PONDEREE PAR LES VENTES — ou une
    chaine vide.

    ⭐ LE REPLI NEUTRE EST LE COEUR DE LA FONCTION. « un mois Star Wars » est
    une affirmation ; si elle est fausse, elle est fausse devant tout le
    serveur. Il faut qu'une licence pese `seuil_theme()` des ventes de la
    selection ET qu'elle y ait au moins deux series : une seule grosse sortie
    ne fait pas un mois."""
    total = sum(d.get("ventes", 0) for d in selection)
    if total <= 0:
        return ""
    poids: Dict[str, int] = {}
    combien: Dict[str, int] = {}
    for d in selection:
        nom = (d.get("licence") or d.get("marque") or "").strip()
        if not nom:
            continue
        poids[nom] = poids.get(nom, 0) + d.get("ventes", 0)
        combien[nom] = combien.get(nom, 0) + 1
    if not poids:
        return ""
    gagnant = max(poids, key=lambda k: poids[k])
    if combien[gagnant] < 2:
        return ""
    return gagnant if poids[gagnant] / total >= seuil_theme() else ""


# ---------------------------------------------------------------------------
# LES CROCHETS v1 — l'illustration et la ligne newsletter, prevues mais vides
# ---------------------------------------------------------------------------
# Reporte en v1 (decision Preda), mais le trou est perce des maintenant : le
# jour ou la pipeline newsletter ecrira son URL de parution, la ligne
# apparaitra SANS QU'ON TOUCHE A CE MODULE.
#
#   data/annonce_crochets.json
#   { "2026-08": { "newsletter_url": "https://…", "newsletter_label": "…",
#                  "image_url": "https://…" } }
#
# ⚠️ Pas d'URL de piece jointe Discord ici : elles sont SIGNEES et EXPIRENT
# (`ex/is/hm`) — piege deja paye sur les images du module `retour`. Et les
# images de la newsletter sont en base64 dans le HTML : inutilisables telles
# quelles. Le jour venu, heberger sur le depot public (raw.githubusercontent).

def crochets(cle: str) -> Dict[str, str]:
    """Ce qui est prevu pour ce mois-la. Fichier absent = {} : un crochet vide
    ne fait echouer personne, il ne s'affiche simplement pas."""
    try:
        with open(CROCHETS_PATH, encoding="utf-8") as f:
            tout = json.load(f)
    except Exception:                                       # noqa: BLE001
        return {}
    val = tout.get(cle) or {}
    return val if isinstance(val, dict) else {}


def illustration(cle: str) -> str:
    return (crochets(cle).get("image_url")
            or os.environ.get("DISCORD_ANNONCE_IMAGE", "").strip())


# ---------------------------------------------------------------------------
# LA MISE EN FORME — DU TEXTE, PAS D'EMBED
# ---------------------------------------------------------------------------
# ⭐⭐⭐ TROISIEME FORME, ET C'EST LA BONNE : embed invente -> texte recopie sur
# son post -> 4 embeds -> texte. Preda a tranche : « l'embed rend mal ».
# **Le gabarit d'un message qui remplace un humain, c'est ce que l'humain
# ecrit** — et un cadre colore n'est pas ce qu'il ecrit.
#
# ⚠️ LE SEUL PARI DE CETTE FORME : les LIENS MASQUES `[nom](url)`. Ils rendent
# dans un embed a coup sur ; dans un message NORMAL, Discord les supporte
# depuis 2023 mais un vieux client afficherait les crochets en clair. D'ou
# `DISCORD_ANNONCE_LIENS_MASQUES` : une variable a basculer si le 1er run rend
# mal, sans redeployer une ligne de code. ⭐ Ce qu'on ne peut pas verifier avant
# la prod se transforme en interrupteur, pas en pari silencieux.


def _fr(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def liens_masques() -> bool:
    return _bool("DISCORD_ANNONCE_LIENS_MASQUES", "true")


def _lien_nomme(nom: str, url: str) -> str:
    """« [BB-8](https://…) » ou, interrupteur ferme, le nom puis l'URL."""
    return f"[{nom}]({url})" if liens_masques() else f"**{nom}**\n{url}"


def ligne_sortie(i: int, d: Dict[str, Any]) -> str:
    """« 1. [Captain America Comics #1 (1941)](url)
           ≈ 6 697 vendus sur 6 697 · SOLD OUT 🔥 »

    Le lien vit DANS le nom (demande de Preda) — `dd._lien` sait quel uuid
    ouvre quelle page : un craft s'ouvre par son ELEMENT, pas par sa serie."""
    nom = d.get("nom") or "(sans nom)"
    ligne = f"{i}. {_lien_nomme(nom, dd._lien(d))}"
    detail = f"≈ {_fr(d['ventes'])} vendus"
    if d.get("total"):
        detail += f" sur {_fr(d['total'])}"
        # ⚠️ « epuise » n'est pas « vendus == tirage » : la chaine compte parfois
        # un mint de plus que le tirage declare. `dr.est_epuise` porte deja
        # cette tolerance — on ne reecrit pas un `==` maison.
        if dr.est_epuise(d["ventes"], d["total"]):
            detail += " · **SOLD OUT** 🔥"
    return f"{ligne}\n {detail}"


def ligne_a_venir(d: Dict[str, Any]) -> str:
    """`<t:…:D>` : Discord affiche la date dans le fuseau de CHAQUE lecteur —
    personne n'a rien a convertir."""
    nom = d.get("nom") or "(sans nom)"
    quand = f"<t:{d['ts']}:D>" if d.get("ts") else d.get("jour", "")
    return f"• {_lien_nomme(nom, dd._lien(d))} — {quand}"


def accroche(mois_passe: str, lic: str) -> str:
    """« Si vous n'étiez pas là en Mai, vous avez certainement manqué le mois
    Starwars ! » — et son REPLI NEUTRE quand aucune licence ne domine : on ne
    nomme pas un theme qu'on n'a pas."""
    mois = mois_passe.capitalize()
    if lic:
        return (f"Si vous n'étiez pas là en {mois}, vous avez certainement "
                f"manqué le mois {lic} !")
    return f"Si vous n'étiez pas là en {mois}, voici ce que vous avez manqué !"


def entete(cle: str, jour: _dt.date, mois_passe: str, lic: str,
           ping: bool) -> Dict[str, Any]:
    """LE 1er MESSAGE : le titre date, le ping, l'accroche, et l'illustration.

    ⚠️ « Annonces 03/06 » porte la date DU POST (jj/mm), pas celle du mois
    annonce — c'est ce que Preda ecrit.
    🔴 LE PING VIT ICI, DANS DU TEXTE. Un « @everyone » ecrit dans un embed
    n'alerte personne : Discord le rend en texte gris."""
    titre = f"{emoji()} **Annonces {jour.strftime('%d/%m')}**"
    if ping:
        titre += " - @everyone"
    lignes = [titre, accroche(mois_passe, lic)]
    img = illustration(cle)
    if img:
        # Une URL seule sur sa ligne : Discord en fait un apercu. (Le jour ou
        # l'illustration sera generee, la televerser serait encore mieux — une
        # URL de piece jointe Discord, elle, EXPIRE.)
        lignes.append(img)
    return {
        "content": "\n".join(lignes),
        # ⭐ `api.mentions()` bride TOUT par defaut : sans cette ouverture
        # explicite, le texte « @everyone » ne pingerait personne. C'est
        # volontaire — le ping se DEMANDE, il ne s'obtient pas par accident.
        "allowed_mentions": ({"parse": ["everyone"]} if ping
                             else api.mentions()),
    }


def bloc_liens(cle: str) -> List[str]:
    """Le bas du message, au mot pres comme Preda l'ecrit."""
    lignes: List[str] = []
    cro = crochets(cle)
    if cro.get("newsletter_url"):
        label = cro.get("newsletter_label") or "La newsletter du mois"
        lignes += [f"📰 **{label} :**", cro["newsletter_url"], ""]
    lignes += ["🎁 **Profitez de 10$ lors de votre Inscription à VeVe !**",
               "Offre réservée aux nouveaux inscrits.",
               f"Lien de parrainage : {LIEN_PARRAINAGE}",
               "",
               "**Comme chaque mois, mise à jour des Classements Publics :**",
               f"<#{SALON_CLASSEMENTS}>",
               "",
               "**Actualités en temps réel sur X (Twitter) :**",
               LIEN_X,
               "",
               "**Bulletin Récap dans le canal**",
               f"<#{SALON_RECAP}>",
               "",
               PHRASE_INVESTOR,
               LIEN_INVESTOR]
    return lignes


def corps(cle: str, mois_passe: str, total_drops: int,
          selection: List[Dict[str, Any]],
          a_venir: List[Dict[str, Any]]) -> Dict[str, Any]:
    """LE 2e MESSAGE : les sorties, le teaser, les liens, le service.

    ⭐ QUAND CA DEBORDE, C'EST LA LISTE QUI CEDE, JAMAIS LE BAS. Un message
    Discord fait 2 000 caracteres ; ce qui doit survivre, ce sont les liens —
    tronquer la fin sacrifierait justement la partie utile."""
    entrees = [ligne_sortie(i, d) for i, d in enumerate(selection, 1)]

    if a_venir:
        suite = [ligne_a_venir(d) for d in a_venir]
        suite.append("et bien d'autres surprises !!")
    else:
        # ⭐ Rien de prevu dans la fenetre : on ne fabrique pas une liste, on
        # dit la verite avec le sourire. Inventer un drop serait pire que de
        # n'en annoncer aucun.
        suite = ["Plein de surprises !"]

    def assembler(n: int) -> str:
        lignes = [f"Ce mois-ci **{_fr(total_drops)} Drops** dont :"]
        lignes += entrees[:n]
        if n < len(entrees):
            lignes.append("…")
        lignes += ["", "👀 **Et maintenant ?**"] + suite + [""]
        lignes += bloc_liens(cle)
        return "\n".join(lignes)

    n = len(entrees)
    texte = assembler(n)
    while len(texte) > MAX_CONTENU and n > 1:
        n -= 1
        texte = assembler(n)
    if n < len(entrees):
        print(f"annonce : message trop long — {len(entrees) - n} ligne(s) de "
              f"la liste retiree(s). Le bloc de liens, lui, est intact.",
              flush=True)

    return {
        "content": texte[:MAX_CONTENU],
        # Le corps ne ping JAMAIS. ⚠️ Un `<#id>` reste cliquable malgre tout :
        # `allowed_mentions` ne bride que les membres, les roles et @everyone.
        "allowed_mentions": api.mentions(),
        # 🚫 PAS DE VIGNETTES. Discord fabrique un apercu pour chaque URL nue
        # (parrainage, X, VeVe Investor) : trois cartouches grises qui doublent
        # la hauteur du message et noient la liste. `flags: 4` =
        # SUPPRESS_EMBEDS, le seul drapeau qu'un webhook a le droit de poser
        # avec SUPPRESS_NOTIFICATIONS.
        # ⚠️ IL EST SUR LE CORPS, PAS SUR L'ENTETE : l'illustration du 1er
        # message EST un apercu d'URL. Le mettre partout tuerait justement ce
        # qu'on veut voir. ⭐ Un reglage global qui supprime « les images »
        # supprime aussi celle qu'on a demandee.
        "flags": SUPPRIMER_VIGNETTES,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _ouvrir(sheet_id: str):
    """Isole pour que le banc puisse mettre un faux Sheet a la place."""
    return _client().open_by_key(sheet_id)


def run() -> int:
    t0 = time.time()
    forcer = force()

    if not forcer and not est_le_jour():
        print(f"annonce : on ne publie que du {jour_cible()} au "
              f"{jour_cible() + tolerance()} du mois — pas aujourd'hui, rien a "
              f"faire. (DISCORD_ANNONCE_FORCE=true pour forcer.)", flush=True)
        return 0

    jour = aujourdhui()
    an, mo = mois_annonce(jour)
    cle = cle_mois(jour)
    # ⚠️ « en Mai », sans l'annee : c'est ce que Preda ecrit.
    mois_passe = MOIS_FR[mo]

    wh, th = webhook(), thread()
    state = api.load_state(STATE_PATH, wh, th)
    if not forcer and state.get("dernier_mois") == cle:
        print(f"annonce : {cle} est deja publie — on ne reposte pas (c'est ce "
              f"qui rend le rattrapage du {jour_cible() + tolerance()} sans "
              f"danger).", flush=True)
        return 0

    sheet_id = os.environ.get("SHEET_ID", "").strip()
    if not sheet_id:
        print("SHEET_ID env var is not set.", file=sys.stderr)
        return 2

    # ═══ LECTURE — un Sheet illisible NE POSTE RIEN, il crie ═══
    try:
        sh = _ouvrir(sheet_id)
        series = series_du_mois(sh, an, mo)
        jours = jours_du_mois(an, mo)
        couverts = jours_couverts(sh, jours)
        ventes = ventes_du_mois(sh, couverts)
        a_venir = dd.drops_a_venir(sh, connus=[])
    except Exception as e:                                  # noqa: BLE001
        print(f"annonce : Sheet illisible ({e}) — AUCUN message poste. Mieux "
              f"vaut rien qu'une annonce fausse, et ca vaut double quand on "
              f"sonne tout le serveur.", file=sys.stderr)
        return 1

    if len(couverts) < couverture_min():
        print(f"::error::annonce : ChainItems ne couvre que {len(couverts)} "
              f"journee(s) de {cle} (minimum {couverture_min()}) — le "
              f"classement « le plus vendu » serait fausse par une fenetre "
              f"trouee. RIEN n'est poste. (Retention de ChainItems : 35 jours ; "
              f"un run tres en retard perd le debut du mois.)", file=sys.stderr)
        return 1

    total_drops = compter_drops(series)
    selection = retenir(classer(series, ventes))
    if not selection:
        print(f"::error::annonce : aucune serie a citer pour {cle} "
              f"({total_drops} serie(s) sortie(s)) — RIEN n'est poste. "
              f"Un mois sans une seule sortie citable n'est pas un mois calme, "
              f"c'est un capteur en panne (ou un filtre trop serre : voir le "
              f"detail des ecartes ci-dessus).", file=sys.stderr)
        return 1

    if len(couverts) < len(jours):
        print(f"annonce : fenetre de mesure {len(couverts)}/{len(jours)} "
              f"journees — le classement porte sur ce qui est mesurable, pas "
              f"sur le mois entier.", flush=True)

    ping = everyone_ouvert()
    lic = theme(selection)
    # Les DEUX messages sont fabriques AVANT le premier envoi : une erreur de
    # rendu ne doit pas laisser une entete orpheline dans le salon.
    m_entete = entete(cle, jour, mois_passe, lic, ping)
    m_corps = corps(cle, mois_passe, total_drops, selection, a_venir)

    if not wh:
        print(f"\n[SIMULATION — pas de DISCORD_ANNONCE_WEBHOOK] ANNONCE {cle}",
              flush=True)
        print(m_entete["content"], flush=True)
        print("\n────────────── (2e message) ──────────────\n", flush=True)
        print(m_corps["content"], flush=True)
        etat_ping = "OUI" if ping else "non (interrupteur ferme)"
        print(f"\nping @everyone : {etat_ping}", flush=True)
        # On N'ECRIT PAS l'etat en simulation : sinon un essai « brulerait » le
        # mois et le vrai run se tairait.
        print(f"annonce (simulation) : {cle}, {time.time() - t0:.0f}s",
              flush=True)
        return 0

    mid = api.poster(wh, th, m_entete)
    if not mid:
        print("annonce : l'entete n'est pas partie (plafond ou erreur) — RIEN "
              "n'est memorise, on reessaiera au prochain passage du hub.",
              file=sys.stderr)
        return 1

    # 🔴 L'ETAT EST ECRIT ICI, PAS A LA FIN. Le ping est parti : quoi qu'il
    # arrive au corps, il ne repartira jamais une seconde fois.
    # ⭐ Une entete orpheline se repare a la main ; deux @everyone, non.
    state["dernier_mois"] = cle
    state["entete"] = mid
    api.save_state(STATE_PATH, state, wh, th)

    api.souffler()
    mid2 = api.poster(wh, th, m_corps)
    if not mid2:
        print(f"::error::annonce : l'entete de {cle} est publiee ({mid}) mais "
              f"le CORPS a echoue. Le mois est marque comme fait — on ne "
              f"repingera pas @everyone pour le rattraper. A publier a la main.",
              file=sys.stderr)
        return 1

    state["corps"] = mid2
    api.save_state(STATE_PATH, state, wh, th)
    print(f"annonce : {cle} publiee ({mid} + {mid2}), {total_drops} drops "
          f"annonces, {len(selection)} serie(s) citee(s), ping "
          f"{'OUI' if ping else 'non'}.", flush=True)

    try:
        append_log(sheet_id, "discord_annonce", "OK",
                   f"mois={cle}; drops={total_drops}; "
                   f"citees={len(selection)}; "
                   f"couverture={len(couverts)}/{len(jours)}; ping={ping}; "
                   f"duree={time.time() - t0:.0f}s")
    except Exception:                                       # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(run())

# FIN discord_annonce.py — une annonce par mois, jamais deux, et jamais un ping
# sur un message dont on n'est pas sur.
