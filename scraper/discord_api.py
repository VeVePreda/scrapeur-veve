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
    """POST dans le THREAD -> l'id du message cree (`wait=true`)."""
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


def editer(wh: str, thread: str, mid: str, payload: Dict) -> Optional[str]:
    """PATCH. 404 = message supprime a la main -> on le RECREE."""
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


def souffler(secondes: float = 1.5) -> None:
    """Entre deux messages : on ne bouscule pas Discord."""
    time.sleep(secondes)
