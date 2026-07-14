"""📊 LES STATS DANS LE POST FORUM DISCORD — 3 messages permanents, REECRITS.

Demande de Preda (14/07) : « 1 message qui recap les années, 1 message qui
recap les mois, 1 message qui recap les jours », dans le post « 📊 STATS » du
forum « 📁⎮hub-actu-test ».

POURQUOI TROIS MESSAGES EDITES, ET PAS UN MESSAGE PAR JOUR
----------------------------------------------------------
Preda voulait au depart « un systeme qui supprime petit a petit les stats
journalieres et mensuelles pour ne laisser que celles des années ». Un webhook
Discord peut EDITER ses propres messages : trois messages reecrits chaque matin
font ce menage TOUT SEULS, sans jamais rien supprimer —
  * un jour qui sort du tableau est deja compte dans SON mois ;
  * un mois clos est deja compte dans SON année ;
  * l'année, elle, ne bouge plus.
Le post reste donc propre en permanence (3 messages, jamais 400), et
l'historique n'est jamais perdu : il remonte d'un cran de granularite.

ORDRE DE CREATION : ANNEES, puis MOIS, puis JOURS — dans un fil Discord le
dernier message est en BAS, donc le tableau qu'on lit tous les matins (les
jours) tombe sous les yeux en ouvrant le post.

⚠️ LA LARGEUR EST LE VRAI ENNEMI (leçon du 1er run reel). Un bloc de code
Discord ne COUPE pas les lignes trop longues : il les ENROULE. Avec 9 colonnes
et des nombres complets (« 899 721 216 801 »), chaque ligne s'affichait sur
deux : illisible. D'ou la regle : peu de colonnes, nombres compacts
(1,47 M · 2,31 Md), largeur <= LARGEUR_MAX — et un garde-fou qui previent dans
les logs si on la depasse.

v3 (retour de Preda) : plus de burn OMI ni de gems (3 colonnes : transactions,
actifs, revenue), **des barres verticales entre les colonnes** pour l'oeil, une
**ligne vide entre chaque semaine** dans le tableau des jours, et 4 années /
5 mois / 14 jours. Le nom de code quitte le corps du message (il reste dans le
pied de la carte) : a sa place, la DATE DE DERNIERE MISE A JOUR.

LES DEUX PIEGES DISCORD (payes une fois, plus jamais)
-----------------------------------------------------
1. **Poster dans un post de forum** = poster dans un THREAD : le webhook
   appartient au SALON, on lui ajoute `?thread_id=<id du post>`.
2. **Pour EDITER, il faut l'id du message** : on ne peut pas relire le salon
   avec un webhook (il faudrait un vrai bot). L'id est donc memorise dans
   l'etat (`data/discord_stats_state.json`, commite par le workflow). Si un
   message est supprime a la main, le PATCH renvoie 404 -> on le RECREE.

Env :
  SHEET_ID, GOOGLE_SERVICE_ACCOUNT_JSON  (lecture du Sheet)
  DISCORD_STATS_WEBHOOK   (SECRET ; sans lui : simulation dans les logs)
  DISCORD_STATS_THREAD    (id du post « 📊 STATS »)
  DISCORD_STATS_STATE     (data/discord_stats_state.json)
  DISCORD_STATS_JOURS (14) · DISCORD_STATS_MOIS (5) · DISCORD_STATS_ANNEES (4)
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
N = {"jours": int(os.environ.get("DISCORD_STATS_JOURS", "14")),
     "mois": int(os.environ.get("DISCORD_STATS_MOIS", "5")),
     "annees": int(os.environ.get("DISCORD_STATS_ANNEES", "4"))}
BLOCS = [b.strip() for b in
         os.environ.get("DISCORD_STATS_BLOCS", "annees,mois,jours").split(",")
         if b.strip()]

# Le nom de code ne sert plus qu'a IDENTIFIER le message (pied de carte) : dans
# le corps, Preda veut voir la date de derniere mise a jour, pas un matricule.
CODES = {"annees": "VEVE-STATS-ANNEES",
         "mois": "VEVE-STATS-MOIS",
         "jours": "VEVE-STATS-JOURS"}

TITRES = {"annees": f"🏛️ **Les {N['annees']} dernières années**",
          "mois": f"📅 **Les {N['mois']} derniers mois**",
          "jours": f"📊 **Les {N['jours']} derniers jours**"}

CARTES = {"annees": "🏛️ Stats Années",
          "mois": "📅 Stats Mois",
          "jours": "📊 Stats Jours"}

COULEURS = {"annees": 0xF1C40F, "mois": 0x7B2CBF, "jours": 0x3498DB}

ENTETE_PERIODE = {"annees": "Année", "mois": "Mois", "jours": "Jour"}

# LES COLONNES VOULUES PAR PREDA (v3 : burn OMI et gems retires).
COLONNES = [("tx", "Tx"),             # TRANSACTION / Global
            ("actifs", "Actifs"),     # ACTIF / Unique
            ("revenue", "Revenue")]   # REVENUE / Total

SEP = " | "                            # les barres aident vraiment l'oeil
DROP = os.environ.get("DISCORD_STATS_DROP", "🎉")   # le symbole des jours de drop

# STYLE : "code" (tableau monospace aligne) ou "markdown" (une ligne par
# periode, en gras/code inline). Le markdown est plus joli mais N'ALIGNE RIEN :
# Discord rend les chiffres en police proportionnelle, donc les colonnes
# dansent. Preda tranche apres avoir vu les deux.
STYLE = os.environ.get("DISCORD_STATS_STYLE", "code").strip().lower()

LEGENDE = "*Tx = transactions · Actifs = wallets uniques · Revenue en $.*"

AVERTISSEMENT = ("*Chiffres indicatifs, issus de sources publiques — ce n'est "
                 "PAS un conseil financier et des erreurs sont possibles.*")

LARGEUR_MAX = int(os.environ.get("DISCORD_STATS_LARGEUR", "46"))


# ---------------------------------------------------------------------------
# Mise en forme
# ---------------------------------------------------------------------------

def _fr(x) -> str:
    """COMPACT : un nombre complet (« 899 721 216 801 ») fait enrouler la ligne."""
    n = stats_read.nombre(x)
    if not n:
        return "—"
    if abs(n) < 1_000_000:
        return f"{n:,}".replace(",", " ")                    # 41 450
    if abs(n) < 1_000_000_000:
        return f"{n / 1e6:.2f}".replace(".", ",") + " M"     # 1,47 M
    return f"{n / 1e9:.2f}".replace(".", ",") + " Md"        # 2,31 Md


def _date(brut) -> Optional[_dt.date]:
    try:
        return _dt.date.fromisoformat(str(brut or "").strip()[:10])
    except ValueError:
        return None


def _periode(cle: str, brut) -> str:
    """Jours -> « 13/07 » ; mois -> « 2026-07 » ; années -> « 2026 »."""
    if cle != "jours":
        return str(brut or "").strip()
    d = _date(brut)
    return d.strftime("%d/%m") if d else str(brut or "").strip()


def _drop(r) -> bool:
    return bool(str(r.get("drop") or "").strip())


def _lignes(cle: str, lignes: List[Dict]) -> List[Optional[tuple]]:
    """(cellules, jour_de_drop) — avec une LIGNE VIDE entre chaque semaine
    (demande de Preda). La coupe se fait sur la semaine ISO, pas tous les
    7 jours : un jour manquant (journee PT pas encore close) ne decale rien."""
    out: List[Optional[tuple]] = []
    prec = None
    for r in lignes:
        cells = [_periode(cle, r.get("periode"))] + \
                [_fr(r.get(c)) for c, _n in COLONNES]
        if cle == "jours":
            d = _date(r.get("periode"))
            sem = d.isocalendar()[:2] if d else None
            if prec is not None and sem != prec:
                out.append(None)                 # respiration entre 2 semaines
            prec = sem
        out.append((cells, _drop(r)))
    return out


def tableau(cle: str, lignes: List[Dict[str, Any]]) -> str:
    """Un tableau ALIGNE dans un bloc de code — la seule facon d'avoir des
    colonnes droites sur Discord (les embeds n'alignent rien). Le symbole de
    drop est pose APRES la derniere colonne : un emoji n'a pas la largeur d'un
    caractere monospace, il ne doit donc jamais tomber au milieu du tableau."""
    entetes = [ENTETE_PERIODE[cle]] + [nom for _c, nom in COLONNES]
    corps = _lignes(cle, lignes)
    remplies = [it[0] for it in corps if it]
    larg = [max([len(entetes[i])] + [l[i] and len(l[i]) or 0
                                     for l in remplies])
            for i in range(len(entetes))]

    def _l(cells: List[str]) -> str:
        return (cells[0].ljust(larg[0]) + SEP +
                SEP.join(cells[i].rjust(larg[i])
                         for i in range(1, len(cells))))

    lines = [_l(entetes), "-+-".join("-" * w for w in larg)]
    for item in corps:
        if not item:
            lines.append("")
            continue
        cells, drop = item
        lines.append(_l(cells) + (f" {DROP}" if drop else ""))
    return "```\n" + "\n".join(lines) + "\n```"


def markdown(cle: str, lignes: List[Dict[str, Any]]) -> str:
    """La variante MARKDOWN (proposition a Preda) : plus jolie, mais Discord la
    rend en police PROPORTIONNELLE — donc rien ne s'aligne. On compense en
    mettant chaque chiffre dans du code inline et en nommant les colonnes."""
    noms = [nom for _c, nom in COLONNES]
    out: List[str] = []
    for item in _lignes(cle, lignes):
        if not item:
            out.append("")
            continue
        cells, drop = item
        chiffres = " · ".join(f"{noms[i]} `{cells[i + 1]}`"
                              for i in range(len(noms)))
        out.append(f"**{cells[0]}**{' ' + DROP if drop else ''} — {chiffres}")
    return "\n".join(out)


def corps(cle: str, lignes: List[Dict[str, Any]]) -> str:
    return (markdown if STYLE == "markdown" else tableau)(cle, lignes)


def _maj() -> str:
    """Le format voulu par Preda : « [MAJ 14/07 à 10h] »."""
    h = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=2)  # Paris
    return h.strftime("[MAJ %d/%m à %Hh]")


def carte(cle: str, lignes: List[Dict]) -> Dict:
    """Plus de pied de carte : Preda n'y voulait ni matricule ni ⚠️ — l'
    avertissement descend dans le corps, en italique."""
    return {
        "title": CARTES[cle],
        "color": COULEURS[cle],
        "description": (corps(cle, lignes) + "\n" + LEGENDE + "\n" +
                        AVERTISSEMENT)[:4000],
    }


def message(cle: str, lignes: List[Dict]) -> Dict:
    return {"content": f"{TITRES[cle]}  ·  {_maj()}",
            "embeds": [carte(cle, lignes)],
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
    if not any(page.values()):
        print("📊 STATS illisible — AUCUN message poste (mieux vaut rien "
              "qu'un tableau faux).", file=sys.stderr)
        return 1

    state = load_state()
    # Plus de ligne « Total » sur les jours (demande de Preda) : le cumul se lit
    # deja dans le message des MOIS.
    contenus = {"annees": page["annees"][:N["annees"]],
                "mois": page["mois"][:N["mois"]],
                "jours": page["jours"][:N["jours"]]}

    # ORDRE : annees -> mois -> jours (le dernier poste est en BAS du fil).
    ok, faits = True, []
    for cle in ("annees", "mois", "jours"):
        if cle not in BLOCS:
            continue
        lignes = contenus[cle]
        if not lignes:
            print(f"{CODES[cle]} : aucune donnee dans 📊 STATS — on ne touche "
                  f"pas au message existant.", flush=True)
            continue
        if STYLE != "markdown":
            larg = max(len(l) for l in tableau(cle, lignes).splitlines())
            if larg > LARGEUR_MAX:
                print(f"⚠️ {CODES[cle]} : tableau large de {larg} caracteres "
                      f"(> {LARGEUR_MAX}) — Discord va enrouler les lignes.",
                      flush=True)
        if publier(cle, message(cle, lignes), state):
            faits.append(cle)
        else:
            ok = False

    save_state(state)
    resume = {"style": STYLE, "jours": len(contenus["jours"]),
              "mois": len(contenus["mois"]), "annees": len(contenus["annees"]),
              "publies": ",".join(faits) or "aucun",
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

# FIN discord_stats.py v4 — 🎉 sur les jours de drop, plus de total, [MAJ ..],
# pied de carte supprime, avertissement en italique, et un STYLE markdown en
# option (DISCORD_STATS_STYLE=markdown) pour comparer.
