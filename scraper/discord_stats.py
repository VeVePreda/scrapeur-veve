"""📊 LES STATS DANS LE POST FORUM DISCORD — 3 messages permanents, REECRITS.

Demande de Preda (14/07) : « 1 message qui recap les années, 1 message qui
recap les mois, 1 message qui recap les 15 derniers jours », chacun avec un
**nom de code** dans son message, dans le post « 📊 STATS » du forum
« 📁⎮hub-actu-test ».

POURQUOI TROIS MESSAGES EDITES, ET PAS UN MESSAGE PAR JOUR
----------------------------------------------------------
Preda voulait au depart « un systeme qui supprime petit a petit les stats
journalieres et mensuelles pour ne laisser que celles des années ». Un webhook
Discord peut EDITER ses propres messages : trois messages reecrits chaque matin
font ce menage TOUT SEULS, sans jamais rien supprimer —
  * un jour qui sort des 15 derniers est deja compte dans SON mois ;
  * un mois clos est deja compte dans SON année ;
  * l'année, elle, ne bouge plus.
Le post reste donc propre en permanence (3 messages, jamais 400), et
l'historique n'est jamais perdu : il remonte d'un cran de granularite.

ORDRE DE CREATION : ANNEES, puis MOIS, puis JOURS — dans un fil Discord le
dernier message est en BAS, donc le tableau qu'on lit tous les matins (les
jours) tombe sous les yeux en ouvrant le post.

LES DEUX PIEGES DISCORD (payes une fois, plus jamais)
-----------------------------------------------------
1. **Poster dans un post de forum** = poster dans un THREAD : le webhook
   appartient au SALON, on lui ajoute `?thread_id=<id du post>`. Sans ce
   parametre, un webhook de forum se plaint (« Cannot send messages in a forum
   channel ») ou cree un nouveau post.
2. **Pour EDITER, il faut l'id du message** : on ne peut pas relire le salon
   avec un webhook (l'API ne le permet pas — il faudrait un vrai bot). L'id est
   donc memorise dans l'etat (`data/discord_stats_state.json`, commite par le
   workflow). Si Preda supprime un message a la main, le PATCH renvoie 404
   « Unknown Message » -> on en RECREE un et on reecrit l'id. Rien ne casse.

Env :
  SHEET_ID, GOOGLE_SERVICE_ACCOUNT_JSON  (lecture du Sheet)
  DISCORD_STATS_WEBHOOK   (SECRET — webhook du salon forum ; sans lui : simulation)
  DISCORD_STATS_THREAD    (id du post « 📊 STATS » ; defaut ci-dessous)
  DISCORD_STATS_STATE     (data/discord_stats_state.json)
  DISCORD_STATS_JOURS     (15)   DISCORD_STATS_MOIS (24)
  DISCORD_STATS_BLOCS     (annees,mois,jours — pour cibler a la main)
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

import requests

from scraper import stats_read
from scraper.sheets import _client, append_log

WEBHOOK = os.environ.get("DISCORD_STATS_WEBHOOK", "").strip()
THREAD = os.environ.get("DISCORD_STATS_THREAD", "1526491450538196992").strip()
STATE_PATH = os.environ.get("DISCORD_STATS_STATE",
                            "data/discord_stats_state.json")
N_JOURS = int(os.environ.get("DISCORD_STATS_JOURS", "15"))
N_MOIS = int(os.environ.get("DISCORD_STATS_MOIS", "24"))
BLOCS = [b.strip() for b in
         os.environ.get("DISCORD_STATS_BLOCS", "annees,mois,jours").split(",")
         if b.strip()]

# Le NOM DE CODE de chaque message (demande de Preda) : il est ecrit DANS le
# message, ce qui permet de savoir d'un coup d'oeil qui est qui — et de le
# retrouver a la main si l'etat est perdu.
CODES = {"annees": "VEVE-STATS-ANNEES",
         "mois": "VEVE-STATS-MOIS",
         "jours": "VEVE-STATS-JOURS"}

TITRES = {"annees": "🏛️ **Les années** — vue d'ensemble depuis 2021",
          "mois": f"📅 **Les mois** — les {N_MOIS} derniers",
          "jours": f"📊 **Les jours** — les {N_JOURS} derniers"}

COULEURS = {"annees": 0xF1C40F,      # or
            "mois": 0x7B2CBF,        # violet
            "jours": 0x3498DB}       # bleu

AVERTISSEMENT = ("⚠️ Chiffres indicatifs, issus de sources publiques — ce n'est "
                 "PAS un conseil financier et des erreurs sont possibles.")

# Les 9 colonnes retenues pour Discord (la page 📊 STATS en compte 20 : tout
# afficher rendrait le tableau illisible sur telephone).
COLONNES = [
    ("periode", "Période", False),
    ("tx", "Tx", True),
    ("mint", "Mint", True),
    ("market", "Market", True),
    ("burn", "Burn", True),
    ("actifs", "Actifs", True),
    ("nouveaux", "Nouv.", True),
    ("revenue", "Revenue $", True),
]

JOURS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi",
            "Dimanche"]


# ---------------------------------------------------------------------------
# Mise en forme
# ---------------------------------------------------------------------------

def _fr(x) -> str:
    n = stats_read.nombre(x)
    return f"{n:,}".replace(",", " ") if n else "—"


def _periode(cle: str, brut: str) -> str:
    """Jours -> « lun. 14/07 » ; mois -> « 2026-07 » ; années -> « 2026 »."""
    s = str(brut or "").strip()
    if cle != "jours":
        return s
    try:
        d = _dt.date.fromisoformat(s[:10])
    except ValueError:
        return s
    return f"{JOURS_FR[d.weekday()][:3].lower()}. {d.strftime('%d/%m')}"


def tableau(cle: str, lignes: List[Dict[str, Any]]) -> str:
    """Un tableau ALIGNE dans un bloc de code (la seule facon d'avoir des
    colonnes droites sur Discord : les embeds n'alignent rien)."""
    entetes = [nom for _c, nom, _r in COLONNES] + ["🎉"]
    corps: List[List[str]] = []
    for r in lignes:
        cells = [_periode(cle, r.get("periode"))]
        cells += [_fr(r.get(c)) for c, _n, _al in COLONNES[1:]]
        cells.append("•" if str(r.get("drop") or "").strip() else "")
        corps.append(cells)
    larg = [max(len(entetes[i]), *(len(l[i]) for l in corps)) if corps
            else len(entetes[i]) for i in range(len(entetes))]

    def _ligne(cells: List[str]) -> str:
        out = [cells[0].ljust(larg[0])]                 # periode a gauche
        out += [cells[i].rjust(larg[i]) for i in range(1, len(cells) - 1)]
        out.append(cells[-1].ljust(larg[-1]))           # marqueur de drop
        return "  ".join(out).rstrip()

    lines = [_ligne(entetes), "-" * min(len(_ligne(entetes)), 90)]
    lines += [_ligne(c) for c in corps]
    return "```\n" + "\n".join(lines) + "\n```"


def entete_semaine(sem: Optional[Dict]) -> str:
    if not sem:
        return ""
    d, f = sem["debut"], sem["fin"]
    drops = f" · 🎉 {sem['drops']} drop(s)" if sem["drops"] else ""
    return (f"**La semaine écoulée** — du {d} au {f} ({sem['jours']} j){drops}\n"
            f"Transactions **{_fr(sem['tx'])}** · Mint **{_fr(sem['mint'])}** · "
            f"Market **{_fr(sem['market'])}** · Burn **{_fr(sem['burn'])}**\n"
            f"Actifs **{_fr(sem['actifs'])}** · Nouveaux "
            f"**{_fr(sem['nouveaux'])}** · Revenue **{_fr(sem['revenue'])} $**\n"
            f"*Les wallets actifs sont ici ADDITIONNÉS jour par jour : un même "
            f"wallet actif deux jours compte deux fois.*\n​\n")


def carte(cle: str, lignes: List[Dict], sem: Optional[Dict] = None) -> Dict:
    desc = (entete_semaine(sem) if cle == "jours" else "") + tableau(cle, lignes)
    maj = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=2)
    return {
        "title": {"annees": "🏛️ Par année", "mois": "📅 Par mois",
                  "jours": "📊 Par jour"}[cle],
        "color": COULEURS[cle],
        "description": desc[:4000],
        "footer": {"text": f"{CODES[cle]} · mis à jour le "
                           f"{maj.strftime('%d/%m/%Y à %H:%M')} (Paris)\n"
                           f"{AVERTISSEMENT}"},
    }


def message(cle: str, lignes: List[Dict], sem=None) -> Dict:
    """Le NOM DE CODE est dans le message lui-meme (demande de Preda)."""
    return {"content": f"{TITRES[cle]}  ·  `⟦{CODES[cle]}⟧`",
            "embeds": [carte(cle, lignes, sem)],
            "allowed_mentions": {"parse": []}}


# ---------------------------------------------------------------------------
# Discord : poster une fois, editer pour toujours
# ---------------------------------------------------------------------------

def _q(base: str, **params) -> str:
    from urllib.parse import urlencode
    return base + ("&" if "?" in base else "?") + urlencode(params)


def _attendre_429(r) -> bool:
    if r.status_code != 429:
        return False
    attente = 5.0
    try:
        attente = float(r.json().get("retry_after", 5)) + 1
    except Exception:                                       # noqa: BLE001
        pass
    print(f"Discord : rate limit — on patiente {attente:.0f} s (s'obstiner "
          f"sur un 429 est ce qui fait bannir un webhook).", flush=True)
    time.sleep(min(attente, 60))
    return True


def poster(payload: Dict) -> Optional[str]:
    """POST dans le THREAD -> renvoie l'id du message cree (`wait=true`)."""
    url = _q(WEBHOOK, thread_id=THREAD, wait="true")
    for _ in range(3):
        r = requests.post(url, json=payload, timeout=20)
        if _attendre_429(r):
            continue
        if r.status_code >= 400:
            print(f"Discord POST {r.status_code} : {r.text[:300]}",
                  file=sys.stderr)
            return None
        return str(r.json().get("id") or "")
    return None


def editer(mid: str, payload: Dict) -> Optional[str]:
    """PATCH du message existant. 404 = message supprime a la main -> on le
    RECREE (et on renvoie le nouvel id)."""
    url = _q(f"{WEBHOOK}/messages/{mid}", thread_id=THREAD)
    for _ in range(3):
        r = requests.patch(url, json=payload, timeout=20)
        if _attendre_429(r):
            continue
        if r.status_code == 404:
            print(f"message {mid} introuvable (supprime ?) — on le recree.",
                  flush=True)
            return poster(payload)
        if r.status_code >= 400:
            print(f"Discord PATCH {r.status_code} : {r.text[:300]}",
                  file=sys.stderr)
            return None
        return mid
    return None


def publier(cle: str, payload: Dict, state: Dict) -> bool:
    if not WEBHOOK:
        print(f"\n[SIMULATION — pas de DISCORD_STATS_WEBHOOK] {CODES[cle]}",
              flush=True)
        print(payload["content"], flush=True)
        print(payload["embeds"][0]["description"], flush=True)
        return True
    ids = state.setdefault("messages", {})
    mid = str(ids.get(cle) or "")
    neuf = editer(mid, payload) if mid else poster(payload)
    if not neuf:
        return False
    ids[cle] = neuf
    print(f"{CODES[cle]} : {'edite' if mid == neuf else 'poste'} ({neuf})",
          flush=True)
    time.sleep(1.5)                     # on ne bouscule pas Discord
    return True


# ---------------------------------------------------------------------------
# Etat
# ---------------------------------------------------------------------------

def empreinte() -> str:
    """Empreinte du couple webhook+post — SANS jamais ecrire le webhook nulle
    part. S'il change, les ids memorises ne valent plus rien."""
    return hashlib.sha1(f"{WEBHOOK}|{THREAD}".encode()).hexdigest()[:12]


def load_state() -> Dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:                                       # noqa: BLE001
        st = {}
    if WEBHOOK and st.get("empreinte") not in (None, empreinte()):
        print("Le webhook ou le post a change : les ids memorises sont "
              "caducs, on repart de zero (3 nouveaux messages).", flush=True)
        st = {}
    return st


def save_state(st: Dict) -> None:
    st["empreinte"] = empreinte()
    st["maj"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(STATE_PATH) or ".", exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    t0 = time.time()
    sheet_id = os.environ.get("SHEET_ID", "").strip()
    if not sheet_id:
        print("SHEET_ID env var is not set.", file=sys.stderr)
        return 2
    if not THREAD:
        print("DISCORD_STATS_THREAD manquant (id du post forum).",
              file=sys.stderr)
        return 2

    sh = _client().open_by_key(sheet_id)
    page = stats_read.lire(sh)
    jours, mois, annees = page["jours"], page["mois"], page["annees"]
    if not jours and not mois and not annees:
        print("📊 STATS illisible — AUCUN message poste (mieux vaut rien "
              "qu'un tableau faux).", file=sys.stderr)
        return 1

    state = load_state()
    sem = stats_read.semaine(jours)
    contenus = {
        "annees": (annees, None),
        "mois": (mois[:N_MOIS], None),
        "jours": (jours[:N_JOURS], sem),
    }

    # ORDRE : annees -> mois -> jours (le dernier poste est en bas du fil).
    ok, faits = True, []
    for cle in ("annees", "mois", "jours"):
        if cle not in BLOCS:
            continue
        lignes, s = contenus[cle]
        if not lignes:
            print(f"{CODES[cle]} : aucune donnee dans 📊 STATS — on ne touche "
                  f"pas au message existant.", flush=True)
            continue
        if publier(cle, message(cle, lignes, s), state):
            faits.append(cle)
        else:
            ok = False

    save_state(state)
    resume = {"jours": len(jours[:N_JOURS]), "mois": len(mois[:N_MOIS]),
              "annees": len(annees), "publies": ",".join(faits) or "aucun",
              "duree": f"{time.time() - t0:.0f}s"}
    try:
        append_log(sheet_id, "discord_stats", "OK" if ok else "ECHEC",
                   "; ".join(f"{k}={v}" for k, v in resume.items()))
    except Exception:                                       # noqa: BLE001
        pass
    print(f"Stats Discord : {resume}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

# FIN discord_stats.py v1 — 3 messages, un nom de code chacun, reecrits chaque
# matin : le post se range tout seul.
