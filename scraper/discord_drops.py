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

Env :
  DISCORD_DROPS_THREAD (id du post) · DISCORD_DROPS_ROLE (role SONDAGE)
  DISCORD_BOT_TOKEN (SECRET — pour les reactions ; sans lui : pas de reactions)
  DISCORD_DROPS_STATE · DISCORD_DROPS_MAX_NEUFS (8) · DISCORD_DROPS_MAX_CARTES (5)
  DISCORD_DROPS_EMOJI_VEVE · DISCORD_DROPS_EMOJI_MARQUES (JSON marque -> emoji)
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import time
from typing import Any, Dict, List

from scraper import discord_api as api
from scraper.sheets import _client, append_log

MODULE = "drops"
THREAD = os.environ.get("DISCORD_DROPS_THREAD", "1526540247469391952").strip()
ROLE = os.environ.get("DISCORD_DROPS_ROLE", "1104653344108191818").strip()
STATE_PATH = os.environ.get("DISCORD_DROPS_STATE",
                            "data/discord_drops_state.json")

TABS = [("🟢C-COMICS", "comic"), ("🔵C-COLLECTIBLE", "collectible")]

MAX_NEUFS = int(os.environ.get("DISCORD_DROPS_MAX_NEUFS", "8"))
# Rattrapage : oublier les drops A VENIR deja memorises, pour les (re)annoncer.
# Sert une fois — quand un 1er run trop gourmand les a avales.
REJOUER = os.environ.get("DISCORD_DROPS_REJOUER", "").strip().lower() in (
    "1", "true", "oui", "yes")
MAX_CARTES = int(os.environ.get("DISCORD_DROPS_MAX_CARTES", "5"))
MCP_BID = os.environ.get("DISCORD_DROPS_MCP_BID", "5,000")

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


def _date(x) -> str:
    s = str(x or "").strip()
    if not s:
        return ""
    if s.replace(".", "", 1).isdigit() and len(s) < 8:      # serial Google
        try:
            return (_dt.date(1899, 12, 30)
                    + _dt.timedelta(days=int(float(s)))).isoformat()
        except (ValueError, OverflowError):
            return ""
    return s[:10]


def _horodatage(r: Dict) -> int:
    """L'heure du drop en timestamp Unix, pour le `<t:…:F>` de Discord — qui
    l'affiche dans le FUSEAU DE CHAQUE LECTEUR. C'est tout l'interet : personne
    n'a a convertir quoi que ce soit."""
    brut = str(r.get("releaseDate") or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            d = _dt.datetime.strptime(brut[:len(fmt) + 2].rstrip("Z"), fmt)
            return int(d.replace(tzinfo=_dt.timezone.utc).timestamp())
        except ValueError:
            continue
    return 0


def drops_a_venir(sh, connus: List[str]) -> List[Dict]:
    """Un drop = une SERIE (les 5 raretes d'un comic sont UNE annonce).
    Seuls les drops A VENIR sont candidats : la date fait foi."""
    vus = set(connus or [])
    aujourdhui = _dt.date.today().isoformat()
    par_serie: Dict[str, Dict] = {}

    for tab, genre in TABS:
        for r in _records(sh, tab):
            jour = _date(r.get("releaseDate"))
            if not jour or jour < aujourdhui:
                continue                       # passe : ce n'est plus une news
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
                "ts": _horodatage(r),
                "lignes": [],
            })
            d["lignes"].append({
                "rarete": str(r.get("rarity") or "").strip().upper(),
                "variante": str(r.get("edition_type") or "").strip(),
                "supply": _n(r.get("supply")),
            })
            if not d["image"] and r.get("image_url"):
                d["image"] = str(r["image_url"]).strip()
            if not d["prix"] and r.get("store_price_gems"):
                d["prix"] = r["store_price_gems"]

    for d in par_serie.values():
        d["lignes"].sort(key=lambda l: (ORDRE_RARETE.index(l["rarete"])
                                        if l["rarete"] in ORDRE_RARETE else 99))
        d["total"] = sum(l["supply"] for l in d["lignes"])
    return sorted(par_serie.values(), key=lambda d: (d["jour"], d["nom"]))


def cles_du_passe(sh) -> List[str]:
    """Les series DEJA sorties — et ELLES SEULES.

    ⚠️ CORRIGE APRES LE 1er RUN REEL (14/07) : je memorisais TOUT le catalogue,
    y compris les drops A VENIR. Resultat : le garde-fou anti-avalanche avalait
    precisement ce qu'on voulait annoncer, et ces drops-la ne seraient JAMAIS
    sortis. Le 1er run doit dire « le passe, je le connais » — pas « l'avenir
    aussi ». Ce qui est a venir reste annoncable."""
    aujourdhui = _dt.date.today().isoformat()
    out = []
    for tab, _g in TABS:
        for r in _records(sh, tab):
            jour = _date(r.get("releaseDate"))
            if jour and jour >= aujourdhui:
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

def _complet(d: Dict) -> str:
    """Ce qui manque pour publier. Une carte a trous ne part pas."""
    if not d.get("nom"):
        return "pas de nom"
    if not d.get("ts"):
        return "pas d'heure de drop exploitable"
    if not d.get("lignes") or not d.get("total"):
        return "aucun supply connu (fiche pas encore enrichie ?)"
    return ""


def _prix(x) -> str:
    """Le prix d'entree, en gems. ⚠️ `storePrice` des COMICS melange deux
    echelles (vieux comics en gems : 10, 15 ; recents en CENTIMES : 699 = 6,99) —
    `store_price_gems` est deja normalise par le chantier classement, on ne
    retouche RIEN ici."""
    try:
        v = float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return ""
    return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ".")


def _titre(d: Dict) -> str:
    licence = d.get("licence") or d.get("marque") or ""
    genre = "Comic" if d["genre"] == "comic" else "Collectible"
    quoi = f"{licence} {genre}".strip()
    nom = d["nom"]
    if d.get("annee") and f"({d['annee']})" not in nom:
        nom = f"{nom} ({d['annee']})"
    return f"{quoi}: **{nom}**"


def _emoji_marque(d: Dict) -> str:
    cle = (d.get("marque") or d.get("licence") or "").strip().lower()
    return EMOJI_MARQUES.get(cle, "")


def texte(d: Dict, ping: bool) -> str:
    tete = f"{EMOJI_VEVE} "
    if ping and ROLE:
        tete += f"<@&{ROLE}> "
    lignes = [f"{tete}{_titre(d)} {_emoji_marque(d)}".rstrip(),
              f"🕗 Drop date: **<t:{d['ts']}:F>** 🕗"]

    for i, l in enumerate(d["lignes"]):
        nom = NOM_RARETE.get(l["rarete"], l["rarete"].title() or "—")
        variante = l["variante"] or "—"
        txt = f"**{nom}** | {variante} | **{l['supply']:,} Editions**"
        # La DERNIERE rarete (la plus rare) est soulignee : c'est elle qu'on
        # cherche des yeux.
        lignes.append(f"__{txt}__" if i == len(d["lignes"]) - 1 else txt)

    label = "Total Comic Editions" if d["genre"] == "comic" else "Total Editions"
    lignes.append(f"**{label}: {d['total']:,}**")

    format_ = []
    if d.get("methode"):
        format_.append(f"Format **{d['methode']}**")
    p = _prix(d.get("prix"))
    if p:
        format_.append(f"Enter **{p}** 💎")
    format_.append(f"Min. MCP Priority Bid **{MCP_BID}**")
    lignes.append(" | ".join(format_))

    lignes.append("__**Participation**__")
    lignes.append("🇩rop /  🇲arket / ❌ Pass")
    return "\n".join(lignes)


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
        state["cles"] = cles_du_passe(sh)
        print(f"1er run -> {len(state['cles'])} series DEJA SORTIES memorisees "
              f"(le passe, et rien que le passe : les drops a venir restent "
              f"annoncables).", flush=True)

    if REJOUER:
        avenir = set(cles_a_venir(sh))
        avant = len(state.get("cles", []))
        state["cles"] = [c for c in state.get("cles", []) if c not in avenir]
        print(f"REJOUER : {avant - len(state['cles'])} drop(s) a venir oublies "
              f"de l'etat — ils vont etre (re)annonces.", flush=True)

    neufs = drops_a_venir(sh, state.get("cles", []))
    tous = len(cles_a_venir(sh))
    print(f"Catalogue : {tous} serie(s) avec un drop a venir · "
          f"{len(neufs)} neuve(s) a annoncer.", flush=True)

    if len(neufs) > MAX_NEUFS:
        print(f"{len(neufs)} drops « neufs » (> {MAX_NEUFS}) -> on memorise "
              f"sans annoncer. VeVe ne sort pas 20 drops dans la nuit : si ca "
              f"arrive, c'est un bug, et on ne reveille pas le serveur pour un "
              f"bug. (Pour forcer : DISCORD_DROPS_MAX_NEUFS plus haut.)",
              flush=True)
        state["cles"] = list(dict.fromkeys(
            list(state.get("cles", [])) + [d["cle"] for d in neufs]))
        neufs = []

    if not neufs:
        api.save_state(STATE_PATH, state, wh, THREAD)
        print("Drops : aucun nouveau drop a venir a annoncer.", flush=True)
        _log(sheet_id, "OK", {"neufs": 0, "duree": f"{time.time() - t0:.0f}s"})
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
        postes.append(d["nom"])
        if wh:
            n = api.reagir(THREAD, mid, REACTIONS)
            if n < len(REACTIONS):
                print(f"⚠️ {n}/{len(REACTIONS)} reactions posees sur "
                      f"« {d['nom']} » — la carte est publiee quand meme.",
                      flush=True)
            api.souffler()

    if sautes:
        print(f"⚠️ {len(sautes)} drop(s) SAUTE(S), fiche incomplete — ils "
              f"repasseront quand le catalogue les aura enrichis : "
              f"{'; '.join(sautes[:5])}", flush=True)

    state["cles"] = list(dict.fromkeys(state.get("cles", [])))
    api.save_state(STATE_PATH, state, wh, THREAD)

    resume = {"neufs": len(neufs), "postes": len(postes),
              "sautes": len(sautes), "titres": " | ".join(postes[:3]),
              "duree": f"{time.time() - t0:.0f}s"}
    _log(sheet_id, "OK" if ok else "ECHEC", resume)
    print(f"Drops Discord : {resume}", flush=True)
    return 0 if ok else 1


def _log(sheet_id: str, statut: str, resume: Dict) -> None:
    try:
        append_log(sheet_id, "discord_drops", statut,
                   "; ".join(f"{k}={v}" for k, v in resume.items()))
    except Exception:                                       # noqa: BLE001
        pass


if __name__ == "__main__":
    sys.exit(run())

# FIN discord_drops.py v2 — une serie = une carte, une vague = un ping, et les
# reactions posees par le bot (un webhook ne sait pas reagir).
