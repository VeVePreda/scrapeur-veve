# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/discord_feed.py
# (comme discord_api.py, un jumeau du dossier scraper existe dans jetonveve/ —
#  ce fichier va dans scrapeur-veve, avec les autres modules du hub.)

"""📈 LE COMPARATIF HEBDO — un module de plus dans le hub, RIEN de plus.

Demande de Preda : chaque DIMANCHE, poster dans le salon « Feed investor » un
petit comparatif de la semaine — combien de nouveaux, combien de transactions
par jour, et l'evolution face a la semaine d'avant — avec un lien vers le detail
(le post « 📊 STATS »).

    Exemple brut a rendre plus joli :
        Stats 17/07
        +567 nouveaux cette semaine, 813 la semaine dernière.
        6542 transaction en moyenne cette semaine. (+8%)
        Détails : <lien du post 📊 STATS>

CE QUI CHANGE PAR RAPPORT AUX AUTRES MODULES DU HUB
---------------------------------------------------
1. **UN SALON NORMAL, PAS UN POST DE FORUM.** Les stats/blog/drops/retour
   vivent dans des POSTS de forum (`?thread_id=`). Ici on poste dans un salon
   classique : `DISCORD_FEED_THREAD` reste VIDE, et `discord_api._q` retire un
   thread_id vide. Son propre webhook : `DISCORD_FEED_WEBHOOK`.
2. **ON POSTE DU NEUF, ON N'EDITE PAS.** Un feed hebdo est une SUITE de bilans :
   chacun reste, on ne reecrit pas le precedent (contrairement aux 4 messages de
   📊 STATS, eux, edites). Donc l'etat ne sert pas a EDITER mais a NE PAS
   REPOSTER : il retient la derniere semaine ISO publiee.
3. **IL SE GARDE LUI-MEME AU DIMANCHE.** Le hub tourne tous les jours (2 fois) ;
   ce module ne parle QUE le dimanche (`DISCORD_FEED_JOUR`, 6 = dimanche). Et
   comme le dimanche le hub passe DEUX fois, l'etat « semaine deja publiee »
   empeche le doublon. `DISCORD_FEED_FORCE=true` court-circuite les deux pour
   tester n'importe quand.

IL NE COLLECTE RIEN : il lit la page « 📊 STATS » deja ecrite par le pipeline
(via `stats_read`), exactement comme le module `stats`. Aucune requete VeVe.

Env :
  SHEET_ID, GOOGLE_SERVICE_ACCOUNT_JSON   (lecture du Sheet)
  DISCORD_FEED_WEBHOOK     (SECRET du salon « Feed investor » ; sans lui :
                            simulation dans les logs)
  DISCORD_FEED_THREAD      (VIDE = salon normal ; un id = post de forum)
  DISCORD_FEED_DETAILS_URL (lien « Détails » -> le post 📊 STATS)
  DISCORD_FEED_STATE       (data/discord_feed_state.json)
  DISCORD_FEED_JOUR        (6 = dimanche ; lun=0 … dim=6)
  DISCORD_FEED_FORCE       (true = ignore le jour ET l'anti-doublon)
  DISCORD_FEED_ROLE        (id d'un role a ping ; vide = ne ping personne)
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
import time
from typing import Dict, List, Optional

from scraper import discord_api as api
from scraper import stats_read
from scraper.sheets import _client, append_log

MODULE = "feed"
WEBHOOK = api.webhook(MODULE)
# VIDE par defaut : « Feed investor » est un salon normal, pas un post de forum.
THREAD = os.environ.get("DISCORD_FEED_THREAD", "").strip()
STATE_PATH = os.environ.get("DISCORD_FEED_STATE",
                            "data/discord_feed_state.json")

# Le post « 📊 STATS » : c'est LA le detail jour par jour.
DETAILS_URL = os.environ.get(
    "DISCORD_FEED_DETAILS_URL",
    "https://discord.com/channels/310073753709182977/1526491450538196992"
).strip()

# 6 = dimanche (lundi=0 … dimanche=6, comme date.weekday()).
JOUR = int(os.environ.get("DISCORD_FEED_JOUR", "6"))
FORCE = os.environ.get("DISCORD_FEED_FORCE", "false").lower() == "true"
ROLE = os.environ.get("DISCORD_FEED_ROLE", "").strip()

COULEUR = 0x2ECC71                        # vert « pouls du marche »
TITRE = "📈 Le point de la semaine — VeVe"
# Meme prudence que le module stats : ce ne sont pas des conseils.
AVERTISSEMENT = ("ⓘ Chiffres indicatifs, issus de sources publiques — ce n'est "
                 "PAS un conseil financier et des erreurs sont possibles.")

MOIS_FR = ["", "janv.", "févr.", "mars", "avril", "mai", "juin", "juil.",
           "août", "sept.", "oct.", "nov.", "déc."]


# ---------------------------------------------------------------------------
# Petites mises en forme FR
# ---------------------------------------------------------------------------

def _fr(n: int) -> str:
    """12345 -> « 12 345 » (espace insecable fine seulement a l'affichage)."""
    return f"{int(n):,}".replace(",", " ")


def _signe(n: int) -> str:
    return f"+{_fr(n)}" if n > 0 else _fr(n)


def _jj_mm(brut: str) -> str:
    """« 2026-07-17 » -> « 17 juil. »."""
    d = stats_read._norm(brut)
    try:
        j = _dt.date.fromisoformat(d[:10])
        return f"{j.day} {MOIS_FR[j.month]}"
    except ValueError:
        return d


def _evolution(maintenant: float, avant: float):
    """Rend (fleche, texte) pour l'ecart relatif — ex. « 📈 +8 % »."""
    if avant <= 0:
        return ("", "nouveau" if maintenant > 0 else "—")
    pct = round((maintenant - avant) / avant * 100)
    if pct > 0:
        return ("📈", f"+{pct} %")
    if pct < 0:
        return ("📉", f"{pct} %")
    return ("➡️", "stable")


# ---------------------------------------------------------------------------
# Les deux semaines, lues dans « 📊 STATS »
# ---------------------------------------------------------------------------

def deux_semaines(jours: List[Dict]) -> Optional[Dict]:
    """La semaine ecoulee (les 7 derniers jours) ET celle d'avant (les 7
    precedents). `stats_read.lire` rend les jours du plus RECENT au plus ancien,
    donc jours[:7] = cette semaine, jours[7:14] = la precedente.

    `stats_read.semaine` fait la somme et pose debut/fin/jours : on l'appelle sur
    chaque tranche. Rend None si l'on n'a pas au moins une semaine pleine."""
    cette = stats_read.semaine(jours[:7], 7)
    prec = stats_read.semaine(jours[7:14], 7)
    if not cette:
        return None
    return {"cette": cette, "prec": prec}


def _moy_tx(sem: Optional[Dict]) -> float:
    if not sem or not sem.get("jours"):
        return 0.0
    return sem["tx"] / sem["jours"]


# ---------------------------------------------------------------------------
# Le message — un embed propre, pas un pave
# ---------------------------------------------------------------------------

def carte(data: Dict) -> Dict:
    cette, prec = data["cette"], data.get("prec")

    nouv_now = int(cette.get("nouveaux", 0))
    nouv_prev = int(prec.get("nouveaux", 0)) if prec else 0
    fl_n, ev_n = _evolution(nouv_now, nouv_prev)

    tx_now = _moy_tx(cette)
    tx_prev = _moy_tx(prec)
    fl_t, ev_t = _evolution(tx_now, tx_prev)

    periode = f"{_jj_mm(cette['debut'])} → {_jj_mm(cette['fin'])}"

    # Champ NOUVEAUX : le chiffre en gros, la comparaison en dessous.
    val_nouv = f"**{_signe(nouv_now)}** cette semaine\n"
    if prec:
        val_nouv += f"{_fr(nouv_prev)} la semaine passée  ·  {fl_n} {ev_n}"
    else:
        val_nouv += "_(pas de semaine précédente à comparer)_"

    # Champ TRANSACTIONS : la moyenne par jour, et l'evolution.
    val_tx = f"**{_fr(round(tx_now))}** / jour en moyenne\n"
    if prec and tx_prev > 0:
        val_tx += f"{_fr(round(tx_prev))} / jour la semaine passée  ·  {fl_t} {ev_t}"
    else:
        val_tx += "_(pas de semaine précédente à comparer)_"

    return {
        "title": TITRE,
        "color": COULEUR,
        "description": f"🗓️ **Semaine du {periode}**",
        "fields": [
            {"name": "👥 Nouveaux arrivants", "value": val_nouv, "inline": False},
            {"name": "🔁 Transactions", "value": val_tx, "inline": False},
            {"name": "​",
             "value": f"🔎 **[Le détail jour par jour → 📊 STATS]({DETAILS_URL})**",
             "inline": False},
        ],
        "footer": {"text": AVERTISSEMENT},
    }


def message(data: Dict) -> Dict:
    contenu = ""
    if ROLE:
        contenu = f"<@&{ROLE}> "
    return {
        "content": contenu,
        "embeds": [carte(data)],
        "allowed_mentions": api.mentions([ROLE] if ROLE else None),
    }


# ---------------------------------------------------------------------------
# La cle d'anti-doublon : la semaine ISO de la reference (le dernier jour lu)
# ---------------------------------------------------------------------------

def _cle_semaine(cette: Dict) -> str:
    """« 2026-W29 » — construite sur le DERNIER jour de la semaine lue (et non
    sur « aujourd'hui »), pour rester juste meme si un run est en retard."""
    try:
        d = _dt.date.fromisoformat(stats_read._norm(cette.get("fin"))[:10])
    except ValueError:
        d = _dt.date.today()
    an, sem, _ = d.isocalendar()
    return f"{an}-W{sem:02d}"


def _est_dimanche() -> bool:
    # Heure de Paris (UTC+2 l'ete). Le hub tourne a 03:45/07:45 UTC : cote Paris
    # on est deja dimanche, donc pas de piege de bascule de jour ici.
    paris = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=2)
    return paris.weekday() == JOUR


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run() -> int:
    t0 = time.time()

    if not FORCE and not _est_dimanche():
        print(f"feed : on ne poste que le jour {JOUR} (dimanche) — aujourd'hui "
              f"ce n'est pas le cas, rien a faire. (DISCORD_FEED_FORCE=true pour "
              f"forcer.)", flush=True)
        return 0

    sheet_id = os.environ.get("SHEET_ID", "").strip()
    if not sheet_id:
        print("SHEET_ID env var is not set.", file=sys.stderr)
        return 2

    sh = _client().open_by_key(sheet_id)
    page = stats_read.lire(sh)
    jours = page.get("jours", [])
    data = deux_semaines(jours)
    if not data:
        print("📊 STATS : pas assez de jours pour un comparatif hebdo — AUCUN "
              "message poste (mieux vaut rien qu'un bilan faux).",
              file=sys.stderr)
        return 1

    cle = _cle_semaine(data["cette"])
    state = api.load_state(STATE_PATH, WEBHOOK, THREAD)
    if not FORCE and state.get("derniere_semaine") == cle:
        print(f"feed : le bilan de la semaine {cle} est deja publie — on ne "
              f"reposte pas (anti-doublon des deux runs du dimanche).",
              flush=True)
        return 0

    payload = message(data)

    if not WEBHOOK:
        print("\n[SIMULATION — pas de webhook] FEED INVESTOR", flush=True)
        print(payload["content"] or "(sans ping)", flush=True)
        emb = payload["embeds"][0]
        print(emb["title"], flush=True)
        print(emb["description"], flush=True)
        for f in emb["fields"]:
            print(f"— {f['name']} : {f['value']}", flush=True)
        print(f"footer: {emb['footer']['text']}", flush=True)
        # En simulation on N'ECRIT PAS l'etat : sinon un test « brulerait » la
        # semaine et le vrai run du dimanche se tairait.
        print(f"\nfeed (simulation) : semaine {cle}, "
              f"{time.time() - t0:.0f}s", flush=True)
        return 0

    mid = api.poster(WEBHOOK, THREAD, payload)
    if not mid:
        print("feed : POST refuse (plafond atteint ou erreur) — on reessaiera "
              "au prochain run du dimanche.", file=sys.stderr)
        return 1

    state["derniere_semaine"] = cle
    api.save_state(STATE_PATH, state, WEBHOOK, THREAD)
    print(f"feed : bilan de la semaine {cle} poste ({mid}).", flush=True)

    try:
        append_log(sheet_id, "discord_feed", "OK",
                   f"semaine={cle}; msg={mid}; duree={time.time() - t0:.0f}s")
    except Exception:                                       # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(run())

# FIN discord_feed.py — un bilan par dimanche, dans un salon normal, qui ne se
# repete jamais et renvoie toujours au detail.
