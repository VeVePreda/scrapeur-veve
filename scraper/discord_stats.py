"""📊 LES STATS DANS LE POST FORUM DISCORD — 3 messages permanents, REECRITS.

Le post « 📊 STATS » du forum « 📁⎮hub-actu-test » porte TROIS messages, et
seulement trois : Stats Années, Stats Mois, Stats Jours. Ils sont postes une
fois, puis EDITES a chaque run.

POURQUOI TROIS MESSAGES EDITES, ET PAS UN MESSAGE PAR JOUR
----------------------------------------------------------
Preda voulait « un systeme qui supprime petit a petit les stats journalieres et
mensuelles pour ne laisser que celles des années ». Un webhook Discord peut
EDITER ses propres messages : trois messages reecrits chaque matin font ce
menage TOUT SEULS, sans jamais rien supprimer —
  * un jour qui sort des 7 derniers est deja compte dans SON mois ;
  * un mois clos est deja compte dans SON année ;
  * l'année, elle, ne bouge plus.
Le post reste propre en permanence, et l'historique n'est jamais perdu : il
remonte d'un cran de granularite.

ORDRE DE CREATION : ANNEES, puis MOIS, puis JOURS — dans un fil Discord le
dernier message est en BAS, donc le tableau qu'on lit tous les matins (les
jours) tombe sous les yeux en ouvrant le post.

v6 — LA FORME, APRES QUATRE ALLERS-RETOURS AVEC PREDA
-----------------------------------------------------
* **MARKDOWN** (choix de Preda apres comparaison). Le tableau monospace alignait
  les colonnes, mais imposait sa loi : un bloc de code Discord n'est pas coupe,
  il est ENROULE — donc peu de colonnes, des chiffres arrondis, des barres
  serrees. En markdown il n'y a PLUS DE LARGEUR : on peut tout dire, en toutes
  lettres, avec les chiffres COMPLETS. Le prix a payer : rien n'est aligne, donc
  **chaque nombre porte son etiquette** (« Global **3 421** ») — sinon on ne
  saurait plus lire une colonne.
* **CINQ PARTIES** (les memes groupes que la page 📊 STATS, separes par une ligne
  vide) : TRANSACTION · ACTIFS · REVENUE · LISTING · ACHAT.
* **☑ / ☐** en tete de chaque jour : case cochee = jour de drop. Uniquement sur
  les JOURS (sur un mois ou une année, il y a forcement eu des drops).
* `[MAJ 14/07 a 11h]` en code inline dans le message.
* L'avertissement dans le PIED DE LA CARTE : Discord le rend tout petit et
  gris — precede d'un ⓘ, sans matricule ni ⚠️.

LES DEUX PIEGES DISCORD (payes une fois, plus jamais)
-----------------------------------------------------
1. **Poster dans un post de forum** = poster dans un THREAD : le webhook
   appartient au SALON, on lui ajoute `?thread_id=<id du post>`.
2. **Pour EDITER, il faut l'id du message** : on ne peut pas relire un salon
   avec un webhook (il faudrait un vrai bot). L'id est donc memorise dans
   l'etat (`data/discord_stats_state.json`, commite par le workflow). Si un
   message est supprime a la main, le PATCH renvoie 404 -> on le RECREE.

Env :
  SHEET_ID, GOOGLE_SERVICE_ACCOUNT_JSON  (lecture du Sheet)
  DISCORD_STATS_WEBHOOK   (SECRET ; sans lui : simulation dans les logs)
  DISCORD_STATS_THREAD    (id du post « 📊 STATS »)
  DISCORD_STATS_STATE     (data/discord_stats_state.json)
  DISCORD_STATS_JOURS (7) · DISCORD_STATS_MOIS (5) · DISCORD_STATS_ANNEES (4)
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
N = {"jours": int(os.environ.get("DISCORD_STATS_JOURS", "7")),
     "mois": int(os.environ.get("DISCORD_STATS_MOIS", "5")),
     "annees": int(os.environ.get("DISCORD_STATS_ANNEES", "4"))}
BLOCS = [b.strip() for b in
         os.environ.get("DISCORD_STATS_BLOCS", "annees,mois,jours").split(",")
         if b.strip()]

# Sert uniquement a nommer les messages dans les LOGS (cote Discord, plus aucun
# matricule n'est affiche : Preda n'en voulait pas).
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

# ☑ / ☐ : cases a cocher (demande de Preda). Ce sont des CARACTERES, pas des
# emojis — discrets, et ils ne deforment pas la ligne.
DROP_OUI = os.environ.get("DISCORD_STATS_DROP_OUI", "☑")
DROP_NON = os.environ.get("DISCORD_STATS_DROP_NON", "☐")

# LES CINQ PARTIES, dans l'ordre voulu par Preda. Ce sont exactement les groupes
# de colonnes de la page 📊 STATS : ce qui est vrai dans le Sheet l'est ici.
SECTIONS = [
    ("TRANSACTION", [("tx", "Global"), ("mint", "Mint"),
                     ("market", "Market")]),
    ("ACTIFS", [("actifs", "Unique"), ("nouveaux", "Nouveaux"),
                ("anciens", "Anciens")]),
    ("REVENUE", [("revenue", "Total"), ("rev_drop", "Drop"),
                 ("rev_market", "Market")]),
    ("LISTING", [("qte", "Quantité"), ("comptes", "Comptes uniques")]),
    ("ACHAT", [("cours_omi", "Cours OMI"), ("gems_usd", "Gems")]),
]

# Les colonnes en dollars (le $ est colle au chiffre, pas mis en legende : en
# markdown rien n'est aligne, donc chaque nombre doit se suffire a lui-meme).
DOLLARS = {"revenue", "rev_drop", "rev_market", "gems_usd", "cours_omi"}

# L'avertissement va dans le PIED DE LA CARTE : c'est la seule zone que Discord
# rend nativement en tout petit et en gris, avec la garantie qu'elle ne prendra
# jamais la parole. (Le sous-texte « -# » du markdown n'est pas garanti dans une
# description d'embed ; s'il ne passait pas, on lirait « -# » en clair — on ne
# parie pas la mise en forme sur une incertitude.) Le ⓘ ouvre la ligne, et il
# n'y a plus ni matricule ni ⚠️, comme demande.
AVERTISSEMENT = ("ⓘ Chiffres indicatifs, issus de sources publiques — ce n'est "
                 "PAS un conseil financier et des erreurs sont possibles.")

MAX_DESC = 4000                      # Discord refuse au-dela de 4096


# ---------------------------------------------------------------------------
# Mise en forme
# ---------------------------------------------------------------------------

def _fr(x) -> str:
    """En markdown il n'y a pas de contrainte de largeur : on donne le chiffre
    COMPLET (c'est le tableau monospace qui obligeait a arrondir)."""
    n = stats_read.nombre(x)
    return f"{n:,}".replace(",", " ") if n else "—"


def _cours(x) -> str:
    """Le cours OMI vaut ~0,000168 $ : `nombre()` le raboterait a 0."""
    try:
        v = float(str(x).replace(",", ".").replace(" ", "").replace("$", ""))
    except (TypeError, ValueError):
        return "—"
    if not v:
        return "—"
    return f"{v:.6f}".rstrip("0").replace(".", ",") + " $"


def _valeur(cle_col: str, r: Dict) -> str:
    if cle_col == "cours_omi":
        return _cours(r.get(cle_col))
    v = _fr(r.get(cle_col))
    return v + " $" if v != "—" and cle_col in DOLLARS else v


def _date(brut) -> Optional[_dt.date]:
    try:
        return _dt.date.fromisoformat(str(brut or "").strip()[:10])
    except ValueError:
        return None


def _periode(cle: str, brut) -> str:
    """Jours -> « lun. 13/07 » ; mois -> « 2026-07 » ; années -> « 2026 »."""
    if cle != "jours":
        return str(brut or "").strip()
    d = _date(brut)
    if not d:
        return str(brut or "").strip()
    jours = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
    return f"{jours[d.weekday()]}. {d.strftime('%d/%m')}"


def _case(cle: str, r: Dict) -> str:
    """☑ jour de drop · ☐ jour sans drop — uniquement sur les JOURS."""
    if cle != "jours":
        return ""
    return (DROP_OUI if str(r.get("drop") or "").strip() else DROP_NON) + " "


def corps(cle: str, lignes: List[Dict[str, Any]]) -> str:
    """Cinq parties, separees par une ligne vide. Chaque nombre porte son
    etiquette : en markdown rien n'est aligne, donc rien ne doit dependre de la
    position."""
    blocs: List[str] = []
    for titre, colonnes in SECTIONS:
        lines = [f"**{titre}**"]
        for r in lignes:
            chiffres = " · ".join(f"{nom} **{_valeur(c, r)}**"
                                  for c, nom in colonnes)
            lines.append(f"{_case(cle, r)}`{_periode(cle, r.get('periode'))}`"
                         f" — {chiffres}")
        blocs.append("\n".join(lines))
    return "\n\n".join(blocs)


def _maj() -> str:
    """Le format voulu par Preda, en code inline : `[MAJ 14/07 à 11h]`."""
    h = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=2)  # Paris
    return h.strftime("`[MAJ %d/%m à %Hh]`")


def carte(cle: str, lignes: List[Dict]) -> Dict:
    texte = corps(cle, lignes)
    if len(texte) > MAX_DESC:
        print(f"⚠️ {CODES[cle]} : {len(texte)} caracteres — Discord plafonne a "
              f"4096, il faut reduire le nombre de periodes.", file=sys.stderr)
        texte = texte[:MAX_DESC]
    return {"title": CARTES[cle], "color": COULEURS[cle],
            "description": texte,
            "footer": {"text": AVERTISSEMENT}}


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
    contenus = {cle: page[cle][:N[cle]] for cle in ("annees", "mois", "jours")}

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
        if publier(cle, message(cle, lignes), state):
            faits.append(cle)
        else:
            ok = False

    save_state(state)
    resume = {"jours": len(contenus["jours"]), "mois": len(contenus["mois"]),
              "annees": len(contenus["annees"]),
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

# FIN discord_stats.py v6 — markdown, 5 parties, cases ☑/☐, chiffres complets.
