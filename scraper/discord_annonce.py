# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/discord_annonce.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""📢 L'ANNONCE DE DEBUT DE MOIS — le 2 de chaque mois, dans « Annonces ».

La newsletter sort le 1er ; l'annonce vient juste apres. DEUX messages : une
ENTETE (courte, c'est elle qui portera l'illustration un jour) puis le CORPS
(un embed : le bilan du mois passe, ce qui arrive, les liens).

Conçu avec Preda le 23/07/2026, ecrit le 04/08/2026. Le 2 aout, rien n'est
sorti et Preda a cru a une panne : ce n'etait pas une panne, le module
n'existait pas. ⭐ Un chantier « conçu » ressemble a un chantier livre quand on
n'en voit que la date qui passe.

CE QU'IL CALCULE — 0 requete VeVe, il lit le Sheet comme `discord_drops`
----------------------------------------------------------------------
* le mois PRECEDENT (nom francais, bornes) ;
* les series sorties dans ce mois-la, **comics du mercredi exclus**
  (`discord_drops.est_comic_du_mercredi` — 3 055 series sur 4 195, c'est du
  volume, pas de l'actualite) ;
* **CE QUI S'EST LE PLUS VENDU** (choix de Preda du 04/08) : les mints
  on-chain de l'onglet `ChainItems`, sommes sur le mois, par serie ;
* le **theme** du mois = la licence dominante DE CETTE SELECTION, avec un
  **repli neutre** : si aucune licence n'ecrase les autres, on dit « le mois de
  juillet » plutot qu'une affirmation fausse ;
* le teaser « a venir » = `discord_drops.drops_a_venir`, le MEME calcul que le
  post 📦DROP (7 jours) — juste reformule.

⭐⭐ JE RECOPIE LA BOUCLE, JAMAIS LES REGLES. Le lien d'une fiche, son titre, le
filtre du mercredi, le tirage d'une serie : chacune de ces regles a deja un
proprietaire (`discord_drops`, `discord_retour`) et une cicatrice. Les
redefinir ici, c'est signer pour deux verites qui divergeront sans jamais
echouer. Ce fichier n'invente qu'une chose : le classement par ventes.

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
4. **L'ETAT EST ECRIT DES QUE L'ENTETE EST PARTIE**, avant meme le corps. Si le
   corps echoue, on crie — mais on ne repingera JAMAIS. Un salon avec une
   entete orpheline se repare a la main ; deux @everyone, non.

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
  DISCORD_ANNONCE_MAX        (6 series citees)
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

COULEUR = 0xF1C40F                       # jaune « annonce », distinct des autres
MAX_CHAMP = 1024                         # limite Discord d'un champ d'embed

MOIS_FR = ["", "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"]

# ═══ LES CONSTANTES DE VeVe FRANCE ═══
# Connues, jamais recalculees (fiche chantier-annonce-mensuelle, 23/07).
GUILDE = "310073753709182977"
LIEN_PARRAINAGE = "https://veve.sjv.io/VeVeFrance"
LIEN_CLASSEMENTS = f"https://discord.com/channels/{GUILDE}/1075084049632206920"
LIEN_X = "https://twitter.com/VeVe_France"
LIEN_RECAP = f"https://discord.com/channels/{GUILDE}/970395941607710840"
LIEN_INVESTOR = f"https://discord.com/channels/{GUILDE}/1022145175499329616"

AVERTISSEMENT = ("ⓘ Ventes estimées d'après les mints on-chain — chiffres "
                 "indicatifs, issus de sources publiques, ce n'est PAS un "
                 "conseil financier.")


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
    tourner avant de sonner 20 000 personnes."""
    return _bool("DISCORD_ANNONCE_EVERYONE", "false")


def force() -> bool:
    return _bool("DISCORD_ANNONCE_FORCE", "false")


def jour_cible() -> int:
    return int(os.environ.get("DISCORD_ANNONCE_JOUR", "2"))


def tolerance() -> int:
    return int(os.environ.get("DISCORD_ANNONCE_TOLERANCE", "1"))


def max_series() -> int:
    return int(os.environ.get("DISCORD_ANNONCE_MAX", "6"))


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


def nom_mois(an: int, mo: int) -> str:
    return f"{MOIS_FR[mo]} {an}"


# ---------------------------------------------------------------------------
# LES SERIES DU MOIS — la boucle est a moi, les regles restent chez elles
# ---------------------------------------------------------------------------

def series_du_mois(sh, an: int, mo: int) -> List[Dict[str, Any]]:
    """Les series dont la date de sortie tombe dans le mois — une SERIE, pas
    une ligne de rarete (les 5 raretes d'un comic sont UNE sortie).

    Regles empruntees, jamais recopiees :
      `dd._quand`                 la date (serial Google, texte, heure)
      `dd.est_comic_du_mercredi`  le deversement du Comic Book Day, ecarte
      `dd._n`                     les nombres du Sheet
    La forme rendue est celle de `dd.drops_a_venir` : c'est ce qui permet a
    `dd._titre` et `dd._lien` de fonctionner dessus **sans que je redefinisse
    l'uuid d'un craft** — le bug qui a l'air de marcher."""
    debut, fin = bornes(an, mo)
    par_serie: Dict[str, Dict[str, Any]] = {}
    ecartes_comic_day = 0

    for tab, genre in dd.TABS:
        for r in dd._records(sh, tab):
            jour, ts, avec_heure = dd._quand(r.get("releaseDate"))
            if not jour or not (debut <= jour <= fin):
                continue
            if dd.est_comic_du_mercredi(genre, jour):
                ecartes_comic_day += 1
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
                "lignes": [],
            })
            d["lignes"].append({
                "rarete": str(r.get("rarity") or "").strip().upper(),
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

    print(f"annonce : {len(par_serie)} serie(s) sortie(s) entre {debut} et "
          f"{fin} · {ecartes_comic_day} ligne(s) de comic du mercredi "
          f"ecartee(s).", flush=True)
    return list(par_serie.values())


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
    """Chaque serie recoit ses ventes (la somme de ses elements), puis on trie
    du plus vendu au moins vendu. Les series a 0 vente sortent : « notable »
    veut dire quelque chose."""
    out = []
    for d in series:
        d = dict(d)
        d["ventes"] = sum(ventes.get(l["uuid"], 0)
                          for l in d["lignes"] if l.get("uuid"))
        if d["ventes"] > 0:
            out.append(d)
    out.sort(key=lambda d: (-d["ventes"], d.get("nom", "")))
    return out


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
# LA MISE EN FORME
# ---------------------------------------------------------------------------

def _fr(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def _couper(txt: str, limite: int = MAX_CHAMP) -> str:
    """Discord refuse un champ d'embed de plus de 1 024 caracteres — et un 400
    ici, c'est l'annonce du mois qui saute. On coupe a la ligne."""
    if len(txt) <= limite:
        return txt
    gardees: List[str] = []
    taille = 0
    for ligne in txt.split("\n"):
        if taille + len(ligne) + 1 > limite - 2:
            break
        gardees.append(ligne)
        taille += len(ligne) + 1
    return "\n".join(gardees) + "\n…"


def ligne_serie(i: int, d: Dict[str, Any]) -> str:
    """« **1.** [Nom](url) — Marvel · ≈ 1 240 vendus sur 2 000 »."""
    nom = d.get("nom") or "(sans nom)"
    lien = dd._lien(d)
    licence = (d.get("licence") or d.get("marque") or "").strip()
    bout = f"**{i}.** [{nom}]({lien})"
    if licence:
        bout += f" — *{licence}*"
    if d.get("exclusive"):
        bout += " 💎"
    detail = f"≈ **{_fr(d['ventes'])}** vendus"
    if d.get("total"):
        detail += f" sur {_fr(d['total'])}"
        # ⚠️ « epuise » n'est pas « vendus == tirage » : la chaine compte parfois
        # un mint de plus que le tirage declare. `dr.est_epuise` porte deja cette
        # tolerance — on l'appelle plutot que d'ecrire un `==` qui dirait
        # « 100,2 % » un jour sur deux.
        if dr.est_epuise(d["ventes"], d["total"]):
            detail += " · **SOLD OUT** 🔥"
    return f"{bout}\n  {detail}"


def ligne_a_venir(d: Dict[str, Any]) -> str:
    """`<t:…:D>` : Discord affiche la date dans le fuseau de CHAQUE lecteur —
    personne n'a rien a convertir."""
    nom = d.get("nom") or "(sans nom)"
    quand = f"<t:{d['ts']}:D>" if d.get("ts") else d.get("jour", "")
    return f"• [{nom}]({dd._lien(d)}) — {quand}"


def entete(cle: str, mois_passe: str, mois_neuf: str,
           ping: bool) -> Dict[str, Any]:
    """LE 1er MESSAGE. Court : c'est lui qui portera l'illustration."""
    contenu = "@everyone\n" if ping else ""
    contenu += (f"## 📢 Nouveau mois chez VeVe France !\n"
                f"### 🗓️ Le bilan de {mois_passe}, et ce qui arrive en "
                f"{mois_neuf}.")
    payload: Dict[str, Any] = {
        "content": contenu,
        # ⭐ `api.mentions()` bride TOUT par defaut : sans cette ouverture
        # explicite, le texte « @everyone » ne pingerait personne. C'est
        # volontaire — le ping se DEMANDE, il ne s'obtient pas par accident.
        "allowed_mentions": ({"parse": ["everyone"]} if ping
                             else api.mentions()),
    }
    img = illustration(cle)
    if img:
        payload["embeds"] = [{"color": COULEUR, "image": {"url": img}}]
    return payload


def corps(cle: str, mois_passe: str, selection: List[Dict[str, Any]],
          a_venir: List[Dict[str, Any]], couverture: int,
          total_jours: int) -> Dict[str, Any]:
    """LE 2e MESSAGE — un embed, pas un pave."""
    lic = theme(selection)
    titre = (f"🌟 {mois_passe.capitalize()}, un mois {lic}" if lic
             else f"🌟 Le mois de {mois_passe}")

    champs: List[Dict[str, Any]] = []

    top = "\n".join(ligne_serie(i, d) for i, d in enumerate(selection, 1))
    champs.append({"name": "🔥 Ce qui est le plus parti le mois dernier",
                   "value": _couper(top), "inline": False})

    if a_venir:
        champs.append({"name": "👀 Et maintenant ?",
                       "value": _couper("\n".join(ligne_a_venir(d)
                                                  for d in a_venir)),
                       "inline": False})

    # Le crochet newsletter : absent aujourd'hui, automatique le jour ou la
    # pipeline ecrira son lien. Rien a rouvrir ici.
    cro = crochets(cle)
    if cro.get("newsletter_url"):
        label = cro.get("newsletter_label") or "Lire la newsletter du mois"
        champs.append({"name": "📰 La newsletter",
                       "value": f"[{label}]({cro['newsletter_url']})",
                       "inline": False})

    champs.append({
        "name": "🔗 Nous suivre",
        "value": (f"🎁 [Rejoindre VeVe]({LIEN_PARRAINAGE}) — **10 $ offerts** "
                  f"à l'inscription\n"
                  f"🏆 [Les classements du mois]({LIEN_CLASSEMENTS})\n"
                  f"📰 [Le bulletin Récap]({LIEN_RECAP})\n"
                  f"📈 [VeVe Investor]({LIEN_INVESTOR})\n"
                  f"🐦 [VeVe France sur X]({LIEN_X})"),
        "inline": False})

    pied = AVERTISSEMENT
    if couverture < total_jours:
        # ⭐ Un filtre silencieux est un mensonge par omission : si la fenetre
        # de mesure est incomplete, ca se DIT, dans le message lui-meme.
        pied = (f"ⓘ Fenêtre de mesure : {couverture} jours sur {total_jours}. "
                + AVERTISSEMENT[2:])

    return {
        "content": "",
        "allowed_mentions": api.mentions(),      # le corps ne ping jamais
        "embeds": [{
            "title": titre,
            "color": COULEUR,
            "description": ("Voici les sorties qui ont trouvé le plus de "
                            "preneurs, et ce qui arrive."),
            "fields": champs,
            "footer": {"text": pied},
        }],
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

    an, mo = mois_annonce()
    cle = cle_mois()
    mois_passe = nom_mois(an, mo)
    mois_neuf = MOIS_FR[aujourdhui().month]

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

    selection = classer(series, ventes)[:max_series()]
    if not selection:
        print(f"::error::annonce : aucune serie vendue trouvee pour {cle} "
              f"({len(series)} serie(s) sortie(s), "
              f"{len(ventes)} element(s) avec des mints) — RIEN n'est poste. "
              f"Un mois sans une seule vente n'est pas un mois calme, c'est un "
              f"capteur en panne.", file=sys.stderr)
        return 1

    ping = everyone_ouvert()
    # Les DEUX messages sont fabriques AVANT le premier envoi : une erreur de
    # rendu ne doit pas laisser une entete orpheline dans le salon.
    m_entete = entete(cle, mois_passe, mois_neuf, ping)
    m_corps = corps(cle, mois_passe, selection, a_venir, len(couverts),
                    len(jours))

    if not wh:
        print("\n[SIMULATION — pas de DISCORD_ANNONCE_WEBHOOK] ANNONCE "
              f"{cle}", flush=True)
        print(m_entete["content"], flush=True)
        emb = m_corps["embeds"][0]
        print(f"\n{emb['title']}\n{emb['description']}", flush=True)
        for f in emb["fields"]:
            print(f"\n— {f['name']} —\n{f['value']}", flush=True)
        print(f"\nfooter: {emb['footer']['text']}", flush=True)
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
    print(f"annonce : {cle} publiee ({mid} + {mid2}), "
          f"{len(selection)} serie(s) citee(s), ping "
          f"{'OUI' if ping else 'non'}.", flush=True)

    try:
        append_log(sheet_id, "discord_annonce", "OK",
                   f"mois={cle}; series={len(selection)}; "
                   f"couverture={len(couverts)}/{len(jours)}; ping={ping}; "
                   f"duree={time.time() - t0:.0f}s")
    except Exception:                                       # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(run())

# FIN discord_annonce.py — une annonce par mois, jamais deux, et jamais un ping
# sur un message dont on n'est pas sur.
