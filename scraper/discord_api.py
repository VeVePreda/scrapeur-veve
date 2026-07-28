# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/discord_api.py
# (un jumeau EXISTE dans jetonveve/scraper/ — ne pas confondre les deux)
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""🔌 LA COUCHE DISCORD — une seule, partagee par tous les modules du hub.

Pourquoi ce fichier : Preda a raison de refuser « 50 workflows ». Le corollaire,
c'est aussi de refuser 50 copies du meme code reseau — sinon les garde-fous
divergent (un module respecte le 429, l'autre l'oublie ; un module bride les
mentions, l'autre ping @everyone par accident). **Les garde-fous se codent UNE
fois, ici, et tout le monde en herite.**

LES QUATRE PIEGES, PAYES UNE FOIS
---------------------------------
1. **Poster dans un post de forum = poster dans un THREAD.** Le webhook
   appartient au SALON ; on lui ajoute `?thread_id=<id du post>`. Sans ca, un
   webhook de forum refuse le message ou cree un nouveau post.
2. **Pour EDITER, il faut l'id du message.** Un webhook ne peut PAS relire un
   salon (il faudrait un vrai bot) : les ids vivent dans l'etat, commite par le
   workflow. PATCH 404 = message supprime a la main -> on le RECREE.
3. **Le 429.** On attend le `retry_after`. S'obstiner sur un rate limit est
   exactement ce qui fait bannir un webhook.
4. **Les mentions.** `allowed_mentions` est TOUJOURS explicite : par defaut on
   ne ping RIEN, et quand on ping un role on autorise CE role et lui seul. Un
   bot qui ping @everyone par accident, c'est une seule fois dans une vie.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import sys
import time
from typing import Dict, List, Optional
from urllib.parse import urlencode

import requests

TIMEOUT = 20
ESSAIS = 3

# ═══ LE PLAFOND, ET L'ESPACEMENT ═══
# Deux garde-fous anti-bannissement, valables pour TOUS les modules a la fois
# (c'est tout l'interet d'avoir une seule couche reseau) :
#  * `PLAFOND` : nombre TOTAL de messages envoyes par run, tous modules
#    confondus. Au-dela, on refuse d'envoyer et on le DIT. Un bot qui deverse
#    trente messages d'affilee est un bot qu'on bannit.
#  * `PAUSE` : quelques secondes entre deux envois. Discord ne se plaint pas
#    d'une seconde de trop ; il se plaint d'une rafale.
PLAFOND = int(os.environ.get("DISCORD_MAX_MESSAGES", "15"))
PAUSE = float(os.environ.get("DISCORD_PAUSE_S", "3"))
_envoyes = 0


def envois() -> int:
    return _envoyes


def _quota_ok(quoi: str) -> bool:
    """Le compteur est GLOBAL au run : les stats, le blog, les drops et le
    retour puisent dans le meme budget."""
    global _envoyes
    if _envoyes >= PLAFOND:
        print(f"⛔ PLAFOND ATTEINT ({PLAFOND} messages sur ce run) — {quoi} "
              f"n'est PAS envoye. Le reste passera au prochain tour. (Regler "
              f"avec DISCORD_MAX_MESSAGES.)", flush=True)
        return False
    _envoyes += 1
    return True


# ---------------------------------------------------------------------------
# Le webhook : un seul secret pour tout le hub, avec des surcharges par module
# ---------------------------------------------------------------------------

def webhook(module: str = "") -> str:
    """`DISCORD_<MODULE>_WEBHOOK` si le module a le sien, sinon le webhook du
    hub. Les posts d'un MEME forum partagent le webhook du salon : seul le
    `thread_id` change. Un module dans un autre salon aura besoin du sien."""
    for cle in (f"DISCORD_{module.upper()}_WEBHOOK" if module else "",
                "DISCORD_HUB_WEBHOOK", "DISCORD_STATS_WEBHOOK"):
        if cle and os.environ.get(cle, "").strip():
            return os.environ[cle].strip()
    return ""


def empreinte(wh: str, thread: str) -> str:
    """Empreinte du couple webhook+post — le jeton n'est JAMAIS ecrit nulle
    part, pas meme dans l'etat. S'il change, les ids memorises sont caducs."""
    return hashlib.sha1(f"{wh}|{thread}".encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Etat (les ids des messages, les slugs deja annonces…)
# ---------------------------------------------------------------------------

def load_state(chemin: str, wh: str, thread: str) -> Dict:
    try:
        with open(chemin, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:                                       # noqa: BLE001
        return {}
    if wh and st.get("empreinte") not in (None, empreinte(wh, thread)):
        print("Le webhook ou le post a change : les ids memorises sont caducs, "
              "on repart de zero.", flush=True)
        return {}
    return st


def save_state(chemin: str, st: Dict, wh: str, thread: str) -> None:
    st["empreinte"] = empreinte(wh, thread)
    st["maj"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Les mentions : explicites, toujours
# ---------------------------------------------------------------------------

def mentions(roles: Optional[List[str]] = None) -> Dict:
    """Sans argument : le message ne ping RIEN (ni @everyone, ni un role, ni un
    membre), quoi qu'il contienne. Avec un role : CE role et lui seul."""
    return {"parse": [], "roles": [str(r) for r in roles or []]}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _q(base: str, **params) -> str:
    # Un parametre vide (thread_id="") ne doit PAS etre serialise : poster dans
    # un SALON NORMAL (pas un post de forum) se fait SANS thread_id — l'ajouter
    # vide ferait echouer la requete. On ne garde que les params renseignes.
    params = {k: v for k, v in params.items() if v not in (None, "")}
    if not params:
        return base
    return base + ("&" if "?" in base else "?") + urlencode(params)


def _429(r) -> bool:
    if r.status_code != 429:
        return False
    attente = 5.0
    try:
        attente = float(r.json().get("retry_after", 5)) + 1
    except Exception:                                       # noqa: BLE001
        pass
    print(f"Discord : rate limit — on patiente {attente:.0f} s (s'obstiner sur "
          f"un 429 est ce qui fait bannir un webhook).", flush=True)
    time.sleep(min(attente, 60))
    return True


def poster(wh: str, thread: str, payload: Dict) -> Optional[str]:
    """POST -> l'id du message cree (`wait=true`).

    `thread` = id du post de forum ; **laisse-le vide pour poster dans un salon
    normal** (le module feed, par exemple). `_q` retire un thread_id vide."""
    if not _quota_ok("un nouveau message"):
        return None
    url = _q(wh, thread_id=thread, wait="true")
    for _ in range(ESSAIS):
        r = requests.post(url, json=payload, timeout=TIMEOUT)
        if _429(r):
            continue
        if r.status_code >= 400:
            print(f"Discord POST {r.status_code} : {r.text[:300]}",
                  file=sys.stderr)
            return None
        return str(r.json().get("id") or "")
    return None


def poster_fichier(wh: str, thread: str, payload: Dict, chemin: str,
                   nom: str = "", type_mime: str = "image/png") -> Optional[str]:
    """POST avec une PIECE JOINTE -> l'id du message cree.

    ⚠️ POURQUOI CE N'EST PAS `poster()` AVEC UNE URL
    ------------------------------------------------
    On pourrait poster un embed dont l'image pointe vers un lien. Mais **une URL
    de piece jointe Discord est SIGNEE et EXPIRE** (`ex/is/hm`) : au bout de
    quelques heures l'image ne s'affiche plus — piege deja paye sur les images
    du module `retour`. Un calendrier qu'on republie chaque samedi et que les
    gens gardent dans leurs favoris ne peut pas dependre d'un lien perissable :
    on TELEVERSE le fichier, il vit dans le message.

    ⚠️ `json=` DEVIENT `payload_json` : en multipart, Discord attend le corps du
    message dans un champ de formulaire nomme `payload_json`, pas dans le corps
    JSON de la requete. Envoyer les deux, ou l'un a la place de l'autre, rend un
    400 laconique.

    Les garde-fous restent ceux de la maison : quota, 429, mentions bridees.
    """
    if not _quota_ok(f"un message avec le fichier {os.path.basename(chemin)}"):
        return None
    if not os.path.exists(chemin):
        print(f"fichier introuvable : {chemin}", file=sys.stderr)
        return None
    url = _q(wh, thread_id=thread, wait="true")
    nom = nom or os.path.basename(chemin)
    for _ in range(ESSAIS):
        # Le fichier est rouvert a CHAQUE essai : un flux deja lu jusqu'au bout
        # renverrait un corps VIDE au 2e tour, et Discord accepterait un message
        # sans image sans se plaindre.
        with open(chemin, "rb") as f:
            r = requests.post(
                url,
                data={"payload_json": json.dumps(payload)},
                files={"files[0]": (nom, f, type_mime)},
                timeout=max(TIMEOUT, 60),          # un PNG de 1 Mo prend plus
            )
        if _429(r):
            continue
        if r.status_code >= 400:
            print(f"Discord POST fichier {r.status_code} : {r.text[:300]}",
                  file=sys.stderr)
            return None
        return str(r.json().get("id") or "")
    return None


def editer(wh: str, thread: str, mid: str, payload: Dict) -> Optional[str]:
    """PATCH. 404 = message supprime a la main -> on le RECREE."""
    if not _quota_ok(f"la reecriture du message {mid}"):
        return mid                # on garde l'id : rien n'est perdu
    url = _q(f"{wh}/messages/{mid}", thread_id=thread)
    for _ in range(ESSAIS):
        r = requests.patch(url, json=payload, timeout=TIMEOUT)
        if _429(r):
            continue
        if r.status_code == 404:
            print(f"message {mid} introuvable (supprime ?) — on le recree.",
                  flush=True)
            return poster(wh, thread, payload)
        if r.status_code >= 400:
            print(f"Discord PATCH {r.status_code} : {r.text[:300]}",
                  file=sys.stderr)
            return None
        return mid
    return None


def supprimer(wh: str, thread: str, mid: str) -> bool:
    url = _q(f"{wh}/messages/{mid}", thread_id=thread)
    for _ in range(ESSAIS):
        r = requests.delete(url, timeout=TIMEOUT)
        if _429(r):
            continue
        return r.status_code in (204, 404)      # 404 = deja parti, tant mieux
    return False


def souffler(secondes: float = None) -> None:
    """Entre deux messages : on ne bouscule pas Discord. Une rafale de trente
    messages est exactement ce qui fait bannir un webhook."""
    time.sleep(PAUSE if secondes is None else secondes)


# ---------------------------------------------------------------------------
# LES REACTIONS — la seule chose qu'un webhook ne sait PAS faire
# ---------------------------------------------------------------------------
# L'API ne permet d'ajouter une reaction qu'avec un TOKEN DE BOT :
#   PUT /channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me
# (dans un post de forum, le `channel_id` EST l'id du post — un thread est un
# salon a part entiere ; c'est le webhook, lui, qui a besoin de `?thread_id=`).
# Le bot doit etre sur le serveur avec « Voir le salon », « Lire l'historique »
# et « Ajouter des reactions ».
#
# ⚠️ PRINCIPE : une reaction qui echoue ne doit JAMAIS faire echouer l'annonce.
# Un sondage sans boutons vaut mieux qu'un drop jamais publie — on le signale
# dans les logs, et on continue.

BOT = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
API = "https://discord.com/api/v10"


def lire_message(channel: str, message_id: str) -> Optional[Dict]:
    """Le message complet (contenu + embeds), lu par le BOT.

    Un webhook ne peut PAS relire ce qu'il a poste — d'ou le bot, comme pour
    les reactions. Sert au marquage « drop sorti » : pour rediter une carte
    sans la reconstruire, il faut d'abord la lire.

    Rend None si la lecture echoue (message supprime, droits, reseau) :
    l'appelant decide, personne ne plante.
    """
    if not BOT:
        return None
    url = f"{API}/channels/{channel}/messages/{message_id}"
    for _ in range(ESSAIS):
        try:
            r = requests.get(url, headers={"Authorization": f"Bot {BOT}"},
                             timeout=TIMEOUT)
        except Exception as e:                              # noqa: BLE001
            print(f"lecture du message KO ({e})", file=sys.stderr)
            return None
        if _429(r):
            continue
        if r.status_code >= 400:
            print(f"lecture du message {r.status_code} : {r.text[:200]}",
                  file=sys.stderr)
            return None
        return r.json()
    return None


def lire_reactions(channel: str, message_id: str) -> Dict[str, int]:
    """Les compteurs de reactions d'un message : {emoji: nombre}.

    Encore un truc qu'un webhook ne sait pas faire — il faut le BOT (un webhook
    ne peut meme pas RELIRE ce qu'il a poste). Sert au « retour drop » : on
    confronte le sondage a ce qui s'est reellement passe."""
    if not BOT:
        return {}
    url = f"{API}/channels/{channel}/messages/{message_id}"
    for _ in range(ESSAIS):
        try:
            r = requests.get(url, headers={"Authorization": f"Bot {BOT}"},
                             timeout=TIMEOUT)
        except Exception as e:                              # noqa: BLE001
            print(f"lecture des reactions KO ({e})", file=sys.stderr)
            return {}
        if _429(r):
            continue
        if r.status_code >= 400:
            print(f"lecture des reactions {r.status_code} : {r.text[:200]}",
                  file=sys.stderr)
            return {}
        out = {}
        for re_ in (r.json().get("reactions") or []):
            nom = (re_.get("emoji") or {}).get("name") or ""
            # le bot a pose la 1re reaction : elle ne compte pas comme un vote
            out[nom] = max(0, int(re_.get("count", 0)) - 1)
        return out
    return {}


def lire_votants(channel: str, message_id: str,
                 max_pages: int = 10) -> Dict[str, set]:
    """QUI a vote quoi : {emoji: {user_id, ...}} — les bots exclus.

    ⚠️ POURQUOI CETTE FONCTION EXISTE, alors que `lire_reactions` renvoie deja
    des compteurs : **un compteur ne se deduplique pas.** Depuis que la meme
    carte de drop est postee dans DEUX salons (le post investisseur 📦DROP et le
    salon public 📘sondage-drop), la meme personne peut voter deux fois. Pour
    n'en compter qu'une, il faut son IDENTITE — pas un nombre. Additionner deux
    compteurs donnerait un total faux **qui a l'air juste** : le pire des bugs.

    ⚠️ LE BOT NE SE SOUSTRAIT PLUS « -1 ». `lire_reactions` retire 1 a chaque
    compteur en supposant que la seule reaction non-humaine est celle que le bot
    a posee pour ouvrir le sondage. Ici on filtre sur `user["bot"]` : c'est le
    FAIT, pas une supposition. Si un jour un second bot reagit, le « -1 »
    mentirait en silence ; ce filtre-ci, non.

    Rend {} sans token de bot (comme le reste de ce fichier : un sondage
    illisible ne fait jamais echouer une publication).
    """
    if not BOT:
        return {}
    message = lire_message(channel, message_id)
    if not message:
        return {}

    from urllib.parse import quote
    entetes = {"Authorization": f"Bot {BOT}"}
    out: Dict[str, set] = {}
    for re_ in (message.get("reactions") or []):
        emo = re_.get("emoji") or {}
        nom = emo.get("name") or ""
        if not nom:
            continue
        # Un emoji PERSONNALISE se demande sous la forme `nom:id` ; un emoji
        # unicode, sous son seul caractere. Confondre les deux rend 400.
        cle_api = f"{nom}:{emo['id']}" if emo.get("id") else nom
        gens: set = set()
        apres = ""
        for _page in range(max_pages):
            url = _q(f"{API}/channels/{channel}/messages/{message_id}"
                     f"/reactions/{quote(cle_api)}", limit="100", after=apres)
            try:
                r = requests.get(url, headers=entetes, timeout=TIMEOUT)
            except Exception as e:                          # noqa: BLE001
                print(f"votants {nom} KO ({e})", file=sys.stderr)
                break
            if _429(r):
                continue
            if r.status_code >= 400:
                print(f"votants {nom} : {r.status_code} {r.text[:200]}",
                      file=sys.stderr)
                break
            lot = r.json() or []
            for u in lot:
                if u.get("bot"):
                    continue              # le bot qui a ouvert le sondage
                if u.get("id"):
                    gens.add(str(u["id"]))
            if len(lot) < 100:
                break                     # derniere page
            apres = str(lot[-1].get("id") or "")
            if not apres:
                break
            time.sleep(0.35)
        out[nom] = gens
        time.sleep(0.35)          # on ne mitraille pas l'API de lecture
    return out


def reagir(channel: str, message_id: str, emojis: List[str]) -> int:
    """Pose les reactions une par une. Renvoie le nombre de reussites."""
    if not BOT:
        print("Pas de DISCORD_BOT_TOKEN : aucune reaction posee (un webhook ne "
              "peut PAS reagir). La carte, elle, est bien publiee.", flush=True)
        return 0
    from urllib.parse import quote
    entetes = {"Authorization": f"Bot {BOT}"}
    n = 0
    for e in [x.strip() for x in emojis if x and x.strip()]:
        url = (f"{API}/channels/{channel}/messages/{message_id}"
               f"/reactions/{quote(e)}/@me")
        for _ in range(ESSAIS):
            try:
                r = requests.put(url, headers=entetes, timeout=TIMEOUT)
            except Exception as exc:                        # noqa: BLE001
                print(f"reaction {e} KO ({exc})", file=sys.stderr)
                break
            if _429(r):
                continue
            if r.status_code in (200, 204):
                n += 1
            else:
                print(f"reaction {e} refusee ({r.status_code}) : "
                      f"{r.text[:200]}", file=sys.stderr)
            break
        time.sleep(0.35)          # 3 reactions = 3 appels : on y va doucement
    return n
