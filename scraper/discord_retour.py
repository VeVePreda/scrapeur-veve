"""🔍 LE RETOUR SUR DROP — 24 h apres, ce qui s'est REELLEMENT passe.

Un post par drop, publie une fois la premiere journee ecoulee : prix, tirage,
ventes, taux d'ecoulement, note de classement — et, quand la carte d'annonce
existe, **le resultat du sondage D / M / ❌ confronte a la realite**.

CE QU'ON MESURE, ET AVEC QUOI
-----------------------------
* **Vendus** = les MINTS ON-CHAIN (`ChainItems`, colonne `mints`), pas une
  estimation. Un mint = quelqu'un a achete au store. C'est la seule mesure
  honnete : le catalogue, lui, ne dit pas ce qui s'est vendu.
  ⚠️ **La journee de ChainItems est une journee PT**, qui ne se ferme qu'a 09:00
  Paris. On additionne donc le jour du drop ET le lendemain (`RETOUR_JOURS` = 2
  journees PT) : la fenetre couvre les 24 premieres heures, un peu plus parfois.
  On l'ECRIT dans la carte plutot que de faire semblant d'avoir l'heure exacte.
* **Taux d'ecoulement** = vendus / tirage. **Le chiffre brut ment, le ratio non**
  (63 ventes sur 1 000, ce n'est pas 63 sur 100).
* **Marche secondaire** = colonne `market` de ChainItems : les reventes des
  premieres 24 h. Un item qui part deja en revente le 1er jour, ca se sait.
* **Note de classement** = onglet 🏆A-CLASSEMENT (chantier du 13/07). Lue par NOM
  de colonne, jamais par position — et si l'onglet ou la colonne manque, la
  ligne disparait de la carte au lieu de tout faire echouer.
* **Le sondage** : le bot relit les reactions de la carte d'annonce (le module
  `drops` a memorise son id). Le vote du bot lui-meme est deduit.

LE COMIC DU MERCREDI : GROUPE, PAS JETE (idee de Preda, 14/07)
--------------------------------------------------------------
Le VeVe Comic Book Day deverse des dizaines de comics d'un coup. On ne les
ANNONCE pas (ce serait 30 cartes et un ping), mais **on les SUIT** — et dans UN
SEUL message, RECRIT a chaque run : une ligne par serie, triee par taux
d'ecoulement. Un comic a 1 000 exemplaires ecoule a 60 % au milieu de trente
series a 60 000 qui font 2 %, c'est exactement ce qu'un humain rate et qu'une
machine voit.
Un message par COMIC DAY (donc un par semaine) : tant que la journee est dans la
fenetre, il est EDITE ; le mercredi suivant en ouvre un nouveau. Le suivi vit
donc dans le temps au lieu d'etre fige a J+1.

LES GARDE-FOUS
--------------
1. **1er run** : on memorise sans rien publier.
2. **LA DATE FAIT FOI** : on ne traite que les drops sortis il y a entre 1 et
   `RETOUR_FENETRE` (7) jours. Meme avec un etat perdu, on ne peut pas deterrer
   2021 — et un retour sur un drop d'il y a 3 mois n'interesse personne.
3. **Anti-avalanche QUI NE DETRUIT RIEN** : au-dela de `RETOUR_MAX_NEUFS` (25),
   on ne publie RIEN **et on ne memorise RIEN** — le backlog reste intact et le
   log CRIE. L'humain tranche. ⚠️ Calibre apres le 1er run reel : 41 drops en
   7 jours, et c'est NORMAL (un mercredi comic day en apporte quinze d'un coup) ;
   le seuil de 8, recopie du module d'annonce, les avait tous avales. Un
   garde-fou qui detruit ce qu'il protege n'est pas un garde-fou, c'est un bug.
   Au-dela de `RETOUR_MAX_CARTES` (8) par run, le reste attend simplement le
   prochain tour — la fenetre de 7 jours lui en laisse le temps.
4. **Aucun chiffre invente** : sans donnee on-chain pour ce drop, on SAUTE (et
   on le dit) — la carte repassera au prochain run. Un « 0 vendu » faux serait
   pire qu'un silence.
5. **Mentions bridees**, 429 respecte (cf. scraper/discord_api.py).

Env : DISCORD_RETOUR_THREAD · DISCORD_RETOUR_ROLE (vide = aucun ping)
      DISCORD_RETOUR_STATE · RETOUR_JOURS (2) · RETOUR_FENETRE (7)
      DISCORD_RETOUR_MAX_NEUFS (25) · DISCORD_RETOUR_MAX_CARTES (8)
      DISCORD_RETOUR_REJOUER (rattrapage : oublier la fenetre deja memorisee)
      DISCORD_RETOUR_PURGER  (l'inverse : marquer la fenetre comme vue, sans
                              rien publier — pour sortir d'un blocage sticky)
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
import time
from typing import Any, Dict, List

from scraper import discord_api as api
from scraper import discord_drops as dd
from scraper.sheets import _client, append_log

MODULE = "retour"
THREAD = os.environ.get("DISCORD_RETOUR_THREAD", "1526557575875924119").strip()
ROLE = os.environ.get("DISCORD_RETOUR_ROLE", "").strip()      # vide = pas de ping
STATE_PATH = os.environ.get("DISCORD_RETOUR_STATE",
                            "data/discord_retour_state.json")

ITEMS_TAB = os.environ.get("CHAIN_ITEMS_TAB", "ChainItems")
CLASSEMENT_TAB = os.environ.get("DISCORD_RETOUR_CLASSEMENT_TAB",
                                "🏆A-CLASSEMENT")

JOURS = int(os.environ.get("DISCORD_RETOUR_JOURS", "2"))       # journees PT
FENETRE = int(os.environ.get("DISCORD_RETOUR_FENETRE", "7"))   # age max du drop
# ⚠️ CALIBRE APRES LE 1er RUN REEL : 41 drops en 7 jours, et c'est NORMAL (le
# mercredi comic day en apporte quinze d'un coup). Le seuil de 8, recopie du
# module d'annonce, a donc avale les 41. **Un garde-fou ne doit jamais detruire
# ce qu'il protege** — voir plus bas : au-dela du seuil, on ne publie RIEN et on
# ne memorise RIEN, on CRIE. L'humain tranche.
MAX_NEUFS = int(os.environ.get("DISCORD_RETOUR_MAX_NEUFS", "25"))
MAX_CARTES = int(os.environ.get("DISCORD_RETOUR_MAX_CARTES", "8"))
# Rattrapage : oublier les drops de la fenetre deja memorises (le 1er run les a
# enterres). Sert une fois.
REJOUER = os.environ.get("DISCORD_RETOUR_REJOUER", "").strip().lower() in (
    "1", "true", "oui", "yes")
# L'AUTRE PORTE DE SORTIE. Un blocage anti-avalanche est STICKY : tant que le
# backlog depasse le seuil, meme les drops NEUFS restent bloques derriere lui.
# Il faut donc pouvoir dire « ce passe-la ne m'interesse pas » : PURGER memorise
# la fenetre SANS rien publier, et on repart propre a partir de maintenant.
PURGER = os.environ.get("DISCORD_RETOUR_PURGER", "").strip().lower() in (
    "1", "true", "oui", "yes")

VERT, ORANGE, ROUGE = 0x2ECC71, 0xE67E22, 0xE74C3C


# ---------------------------------------------------------------------------
# Les sources
# ---------------------------------------------------------------------------

def _records(sh, tab: str) -> List[Dict[str, Any]]:
    try:
        return sh.worksheet(tab).get_all_records()
    except Exception as e:                                  # noqa: BLE001
        print(f"lecture de {tab} impossible : {e}", file=sys.stderr)
        return []


def chaine_par_uuid(sh, jours: List[str]) -> Dict[str, Dict[str, int]]:
    """{veve_uuid: {mints, market}} sur les journees demandees (ChainItems)."""
    voulus = set(jours)
    out: Dict[str, Dict[str, int]] = {}
    for r in _records(sh, ITEMS_TAB):
        if str(r.get("date") or "")[:10] not in voulus:
            continue
        u = str(r.get("veve_uuid") or "").strip()
        if not u:
            continue
        acc = out.setdefault(u, {"mints": 0, "market": 0})
        acc["mints"] += dd._n(r.get("mints"))
        acc["market"] += dd._n(r.get("market"))
    return out


def notes_de_classement(sh) -> Dict[str, str]:
    """{cle: note}. Lue par NOM de colonne (jamais par position — une page
    reordonnee ferait glisser toutes les valeurs d'un cran).

    ⚠️ CORRIGE (run reel) : `get_all_records()` EXPLOSE si deux colonnes portent
    le meme nom (« the header row is not unique ») — et 🏆A-CLASSEMENT en a. On
    lit donc les VALEURS BRUTES et on fabrique l'index nous-memes : la 1re
    occurrence d'un nom gagne. Une page mal fichue ne doit pas faire taire tout
    le module."""
    try:
        vals = sh.worksheet(CLASSEMENT_TAB).get_all_values()
    except Exception as e:                                  # noqa: BLE001
        print(f"lecture de {CLASSEMENT_TAB} impossible : {e}", file=sys.stderr)
        return {}
    if len(vals) < 2:
        return {}
    entetes = [str(c).strip() for c in vals[0]]
    lignes = []
    for r in vals[1:]:
        d = {}
        for i, nom in enumerate(entetes):
            if nom and nom not in d:          # 1re occurrence : elle gagne
                d[nom] = r[i] if i < len(r) else ""
        lignes.append(d)
    entetes = list(dict.fromkeys(e for e in entetes if e))
    col_note = next((c for c in entetes if c.strip().lower() == "note"), "")
    col_cle = next((c for c in ("series_uuid", "veve_uuid", "uuid")
                    if c in entetes), "")
    if not col_note or not col_cle:
        print(f"{CLASSEMENT_TAB} : pas de colonne « note » et/ou de cle "
              f"(vu : {entetes[:8]}) — la note ne sera pas affichee.",
              flush=True)
        return {}
    return {str(r.get(col_cle) or "").strip(): str(r.get(col_note) or "").strip()
            for r in lignes if str(r.get(col_cle) or "").strip()
            and str(r.get(col_note) or "").strip()}


# ---------------------------------------------------------------------------
# Les drops a debriefer
# ---------------------------------------------------------------------------

def _jours_pt(jour_drop: str, n: int = None) -> List[str]:
    d = _dt.date.fromisoformat(jour_drop)
    return [(d + _dt.timedelta(days=i)).isoformat()
            for i in range(JOURS if n is None else n)]


# Les paliers de suivi. ⚠️ LE « ~ » N'EST PAS UNE COQUETTERIE : la journee de
# ChainItems est une journee PT, qui ne se ferme qu'a 09:00 Paris. Un drop de
# 17 h deborde donc sur le lendemain. « ~24 h » = les 2 premieres journees PT,
# « ~48 h » = 3, « ~72 h » = 4. On ecrit le tilde plutot que de faire semblant
# d'avoir l'heure exacte.
PALIERS = [("~24 h", 2), ("~48 h", 3), ("~72 h", 4)]


def paliers(sh, jour: str, uuids: List[str]):
    """[(label, vendus, delta_pct)] — seulement les paliers dont la journee PT
    est CLOSE (presente dans ChainItems). On n'invente pas un palier qui n'a pas
    encore de donnee."""
    connus = {str(r.get("date") or "")[:10]
              for r in _records(sh, ITEMS_TAB) if r.get("date")}
    out, precedent = [], None
    for label, n in PALIERS:
        jours = _jours_pt(jour, n)
        if jours[-1] not in connus:
            break                          # la journee n'est pas close : STOP
        ch = chaine_par_uuid(sh, jours)
        vendus = sum(ch.get(u, {}).get("mints", 0) for u in uuids)
        delta = (100.0 * (vendus - precedent) / precedent
                 if precedent else None)
        out.append((label, vendus, delta))
        precedent = vendus
    return out


def a_debriefer(sh, connus: List[str]) -> List[Dict]:
    """Les drops SORTIS il y a entre 1 et FENETRE jours, pas encore debriefes.
    On reutilise le lecteur du module `drops` : une seule facon de lire le
    catalogue, donc une seule verite."""
    vus = set(connus or [])
    aujourdhui = _dt.date.today()
    debut = (aujourdhui - _dt.timedelta(days=FENETRE)).isoformat()
    veille = (aujourdhui - _dt.timedelta(days=1)).isoformat()

    par_serie: Dict[str, Dict] = {}
    ecartes = 0
    for tab, genre in dd.TABS:
        for r in _records(sh, tab):
            jour, ts, avec_heure = dd._quand(r.get("releaseDate"))
            if not jour or not (debut <= jour <= veille):
                continue                  # trop vieux, ou pas encore 24 h
            if dd.est_comic_du_mercredi(genre, jour):
                ecartes += 1
                continue                  # VeVe Comic Book Day : du volume
            cle = (str(r.get("series_uuid") or "").strip()
                   or str(r.get("veve_uuid") or "").strip())
            if not cle or cle in vus:
                continue
            d = par_serie.setdefault(cle, {
                "cle": cle, "genre": genre, "jour": jour, "ts": ts,
                "avec_heure": avec_heure,
                "nom": str(r.get("veve_series_name") or r.get("name") or ""),
                "annee": str(r.get("start_year") or "").strip(),
                "marque": str(r.get("veve_brand") or "").strip(),
                "licence": str(r.get("veve_licensor") or "").strip(),
                "methode": str(r.get("drop_method") or "").strip(),
                "prix": r.get("store_price_gems"),
                "image": str(r.get("image_url") or "").strip(),
                "lignes": [],
            })
            d["lignes"].append({
                "rarete": str(r.get("rarity") or "").strip().upper(),
                "variante": str(r.get("edition_type") or "").strip(),
                "supply": dd._n(r.get("supply")),
                "uuid": str(r.get("veve_uuid") or "").strip(),
            })
            if not d["prix"] and r.get("store_price_gems"):
                d["prix"] = r["store_price_gems"]

    if ecartes:
        print(f"{ecartes} ligne(s) de comic du mercredi ecartee(s) (VeVe Comic "
              f"Book Day : du volume, pas de l'actualite — heuristique "
              f"debrayable par DISCORD_SANS_COMIC_DAY=false).", flush=True)
    for d in par_serie.values():
        d["lignes"].sort(key=lambda l: (dd.ORDRE_RARETE.index(l["rarete"])
                                        if l["rarete"] in dd.ORDRE_RARETE
                                        else 99))
        d["total"] = sum(l["supply"] for l in d["lignes"])
    return sorted(par_serie.values(), key=lambda d: d["jour"])


def comic_day_recent(sh):
    """Le dernier COMIC BOOK DAY de la fenetre (et ses series).

    Renvoie (jour, [series]) ou (None, []). On ne prend QUE le plus recent : le
    message de suivi est reecrit, pas empile — un par semaine suffit."""
    aujourdhui = _dt.date.today()
    debut = (aujourdhui - _dt.timedelta(days=FENETRE)).isoformat()
    veille = (aujourdhui - _dt.timedelta(days=1)).isoformat()

    par_jour: Dict[str, Dict[str, Dict]] = {}
    tab, genre = dd.TABS[0]                       # les comics, et eux seuls
    for r in _records(sh, tab):
        jour = dd._quand(r.get("releaseDate"))[0]
        if not jour or not (debut <= jour <= veille):
            continue
        try:
            if _dt.date.fromisoformat(jour).weekday() != dd.JOUR_COMIC_DAY:
                continue
        except ValueError:
            continue
        cle = (str(r.get("series_uuid") or "").strip()
               or str(r.get("veve_uuid") or "").strip())
        if not cle:
            continue
        d = par_jour.setdefault(jour, {}).setdefault(cle, {
            "cle": cle, "jour": jour,
            "nom": str(r.get("veve_series_name") or r.get("name") or ""),
            "prix": r.get("store_price_gems"), "total": 0, "uuids": [],
        })
        d["total"] += dd._n(r.get("supply"))
        u = str(r.get("veve_uuid") or "").strip()
        if u:
            d["uuids"].append(u)
        if not d["prix"] and r.get("store_price_gems"):
            d["prix"] = r["store_price_gems"]

    if not par_jour:
        return None, []
    jour = max(par_jour)
    return jour, list(par_jour[jour].values())


MAX_LIGNES = int(os.environ.get("DISCORD_RETOUR_COMIC_LIGNES", "30"))


def message_comic_day(jour: str, series: List[Dict],
                      chaine: Dict[str, Dict[str, int]],
                      suivi=None) -> Dict:
    """UN message pour tout le Comic Book Day, trie par taux d'ecoulement :
    la pepite remonte d'elle-meme.

    ⚠️ **UNE SERIE A 0 VENDU N'EST PAS AFFICHEE.** Preda est formel : un comic ne
    fait JAMAIS zero vente. Un zero n'est donc pas une information, c'est un TROU
    dans la collecte (uuid pas encore vu par la chaine). L'afficher serait
    publier un bug avec l'autorite d'un chiffre — la ligne repassera au prochain
    run, quand la donnee sera la."""
    tot_supply = 0
    for s in series:
        s["vendus"] = sum(chaine.get(u, {}).get("mints", 0) for u in s["uuids"])
        s["pct"] = _pct(s["vendus"], s["total"])
        tot_supply += s["total"]

    vus = [s for s in series if s["vendus"] > 0]
    muets = len(series) - len(vus)
    vus.sort(key=lambda s: (-s["pct"], -s["vendus"]))
    tot_vendus = sum(s["vendus"] for s in vus)

    lignes = []
    for s in vus[:MAX_LIGNES]:
        prix = dd._prix(s.get("prix"), "comic")
        prix = f" · {prix} 💎" if prix else ""
        lignes.append(
            f"`{s['pct']:5.1f} %` **{s['nom']}** — {s['total']:,} ex{prix} · "
            f"**{s['vendus']:,}** vendus".replace(",", " "))
    reste = len(vus) - MAX_LIGNES
    if reste > 0:
        lignes.append(f"*… et {reste} autre(s) série(s).*")
    if muets:
        lignes.append(f"*({muets} série(s) sans donnée de vente pour l'instant "
                      f"— elles reviendront.)*")

    entete = [f"**{len(series)} séries** · {tot_supply:,} exemplaires"
              .replace(",", " "), ""]
    for label, vendus, delta in (suivi or []):
        d = f" · **{delta:+.1f} %**" if delta is not None else ""
        entete.append(f"Ventes totales après **{label}** : "
                      f"**{vendus:,}**{d}".replace(",", " "))
    if not suivi:
        entete.append(f"Ventes totales : **{tot_vendus:,}**".replace(",", " "))

    pct = _pct(tot_vendus, tot_supply)
    return {"content": "🔍 **Suivi du Comic Book Day**",
            "embeds": [{
                "title": f"📅 Comic Book Day du {jour}",
                "color": couleur(pct),
                "description": ("\n".join(entete) + "\n\n"
                                + "\n".join(lignes))[:4000],
            }],
            "allowed_mentions": api.mentions()}


def toutes_les_cles(sh) -> List[str]:
    """Tout ce qui est HORS fenetre de debrief (le tres vieux, et le futur)."""
    aujourdhui = _dt.date.today()
    debut = (aujourdhui - _dt.timedelta(days=FENETRE)).isoformat()
    veille = (aujourdhui - _dt.timedelta(days=1)).isoformat()
    out = []
    for tab, _g in dd.TABS:
        for r in _records(sh, tab):
            jour = dd._quand(r.get("releaseDate"))[0]
            genre = "comic" if tab == dd.TABS[0][0] else "collectible"
            if (jour and debut <= jour <= veille
                    and not dd.est_comic_du_mercredi(genre, jour)):
                continue                  # dans la fenetre : on ne l'enterre pas
            cle = (str(r.get("series_uuid") or "").strip()
                   or str(r.get("veve_uuid") or "").strip())
            if cle:
                out.append(cle)
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------------------
# La carte
# ---------------------------------------------------------------------------

def _pct(vendus: int, total: int) -> float:
    return (100.0 * vendus / total) if total else 0.0


def couleur(pct: float) -> int:
    """Vert = ca s'est arrache · rouge = ca n'est pas parti. Une couleur se lit
    plus vite qu'un chiffre."""
    return VERT if pct >= 50 else (ORANGE if pct >= 15 else ROUGE)


def carte(d: Dict, chaine: Dict[str, Dict[str, int]], note: str,
          sondage: Dict[str, int]) -> Dict:
    vendus = sum(chaine.get(l["uuid"], {}).get("mints", 0) for l in d["lignes"])
    market = sum(chaine.get(l["uuid"], {}).get("market", 0) for l in d["lignes"])
    pct = _pct(vendus, d["total"])

    genre = "Comic" if d["genre"] == "comic" else "Collectible"
    licence = d.get("licence") or d.get("marque") or ""
    nom = d["nom"]
    if d.get("annee") and f"({d['annee']})" not in nom:
        nom = f"{nom} ({d['annee']})"

    style = "F" if d.get("avec_heure") else "D"
    lignes = [f"🕗 Drop : **<t:{d['ts']}:{style}>**", ""]

    prix = dd._prix(d.get("prix"))
    if prix:
        lignes.append(f"💎 **Prix drop** : {prix} gems")
    lignes.append(f"📦 **Mint total** : {d['total']:,}".replace(",", " "))
    lignes.append(f"🛒 **Vendus** : {vendus:,}".replace(",", " ")
                  + f"  ·  **{pct:.1f} %** du tirage")
    if market:
        lignes.append(f"🔁 **Revendus dès le 1er jour** : {market:,}"
                      .replace(",", " "))
    if note:
        lignes.append(f"🏆 **Classement** : {note}")

    if sondage:
        total_votes = sum(sondage.values())
        if total_votes:
            detail = " · ".join(f"{e} **{n}**" for e, n in sondage.items() if n)
            lignes += ["", f"🗳️ **Le sondage disait** : {detail}"]

    lignes += ["", f"[Page VeVe](<{dd._lien(d)}>)"]

    e = {"title": f"{licence} {genre} : {nom}".strip(),
         "color": couleur(pct),
         "description": "\n".join(lignes)[:4000],
         "footer": {"text": f"ⓘ Ventes = mints on-chain, cumulés sur {JOURS} "
                            f"journées (une journée VeVe se ferme à 09:00 "
                            f"Paris) — la fenêtre couvre les premières 24 h, "
                            f"parfois un peu plus."}}
    if d.get("image"):
        e["image"] = {"url": d["image"]}
    return e


def message(d: Dict, chaine, note: str, sondage: Dict[str, int],
            ping: bool) -> Dict:
    tete = "🔍 **Retour sur drop**"
    contenu = f"<@&{ROLE}> {tete}" if (ping and ROLE) else tete
    return {"content": contenu,
            "embeds": [carte(d, chaine, note, sondage)],
            "allowed_mentions": api.mentions([ROLE] if (ping and ROLE) else [])}


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
        state["cles"] = toutes_les_cles(sh)
        print(f"1er run -> {len(state['cles'])} series hors fenetre memorisees "
              f"(seuls les drops des {FENETRE} derniers jours sont a "
              f"debriefer).", flush=True)

    if REJOUER:
        fenetre = {d["cle"] for d in a_debriefer(sh, [])}
        avant = len(state.get("cles", []))
        state["cles"] = [c for c in state.get("cles", []) if c not in fenetre]
        print(f"REJOUER : {avant - len(state['cles'])} drop(s) de la fenetre "
              f"oublies de l'etat — ils vont etre debriefes.", flush=True)

    neufs = a_debriefer(sh, state.get("cles", []))
    print(f"{len(neufs)} drop(s) a debriefer (sortis il y a 1 a {FENETRE} j).",
          flush=True)

    if PURGER:
        state["cles"] = list(dict.fromkeys(
            list(state.get("cles", [])) + [d["cle"] for d in neufs]))
        api.save_state(STATE_PATH, state, wh, THREAD)
        print(f"PURGER : les {len(neufs)} drop(s) en attente sont marques comme "
              f"vus, SANS rien publier. On repart propre : seuls les prochains "
              f"drops seront debriefes.", flush=True)
        _log(sheet_id, "OK", {"neufs": len(neufs), "postes": 0,
                              "motif": "purge"})
        return 0

    # ANTI-AVALANCHE — version qui ne detruit RIEN. Au-dela du seuil, on ne
    # publie pas ET ON NE MEMORISE PAS : le backlog reste intact, et l'humain
    # decide (en montant DISCORD_RETOUR_MAX_NEUFS, ou en purgeant l'etat).
    # C'est la lecon du module `drops` : un garde-fou qui avale la donnee qu'il
    # protege n'est pas un garde-fou, c'est un bug.
    if len(neufs) > MAX_NEUFS:
        print(f"⚠️ {len(neufs)} drops a debriefer (> {MAX_NEUFS}) : RIEN n'est "
              f"publie, et RIEN n'est memorise — le backlog est intact.\n"
              f"   ⚠️ CE BLOCAGE EST STICKY : tant qu'il dure, meme les drops "
              f"NEUFS restent coinces derriere. Deux portes de sortie :\n"
              f"   · retour_max = 50  -> on rattrape (8 cartes par run, le "
              f"reste au tour suivant) ;\n"
              f"   · purger_retour = true -> on marque ce passe comme vu SANS "
              f"rien publier, et on repart propre.", flush=True)
        api.save_state(STATE_PATH, state, wh, THREAD)
        _log(sheet_id, "OK", {"neufs": len(neufs), "postes": 0,
                              "motif": "avalanche"})
        return 0

    if not neufs:
        api.save_state(STATE_PATH, state, wh, THREAD)
        print("Retour : rien a debriefer.", flush=True)
        _log(sheet_id, "OK", {"neufs": 0, "duree": f"{time.time() - t0:.0f}s"})
        return 0

    # Les journees PT a lire, pour TOUS les drops d'un coup (une seule lecture
    # de ChainItems : c'est un gros onglet).
    jours = sorted({j for d in neufs for j in _jours_pt(d["jour"])})
    chaine = chaine_par_uuid(sh, jours)
    notes = notes_de_classement(sh)
    # Les ids des cartes d'annonce, poses par le module `drops`.
    annonces = api.load_state(dd.STATE_PATH, api.webhook(dd.MODULE),
                              dd.THREAD).get("messages", {})

    # On ne memorise QUE ce qu'on publie : les drops au-dela de MAX_CARTES
    # repasseront au prochain run (la fenetre de 7 jours leur laisse le temps).
    ok, postes, sautes = True, [], []
    premier_ping = True
    if len(neufs) > MAX_CARTES:
        print(f"{len(neufs)} a debriefer, {MAX_CARTES} par run : les autres "
              f"passeront au prochain tour (ils restent dans la fenetre).",
              flush=True)
    for d in neufs[:MAX_CARTES]:
        vendus = sum(chaine.get(l["uuid"], {}).get("mints", 0)
                     for l in d["lignes"])
        if not d["total"]:
            sautes.append(f"{d['nom']} (aucun tirage connu)")
            continue
        if not chaine:
            sautes.append(f"{d['nom']} (aucune donnee on-chain — la journee "
                          f"n'est peut-etre pas encore close)")
            continue
        if vendus == 0:
            # Un drop ne fait JAMAIS zero vente (Preda). Un zero est un trou de
            # collecte, pas un fait : on ne le publie pas, et on ne memorise pas
            # -> la carte repassera quand la donnee sera la.
            sautes.append(f"{d['nom']} (0 vendu = donnee manquante, pas un "
                          f"resultat)")
            continue

        sondage = {}
        mid = annonces.get(d["cle"])
        if mid:
            sondage = api.lire_reactions(dd.THREAD, mid)

        note = notes.get(d["cle"], "")
        payload = message(d, chaine, note, sondage, ping=premier_ping)
        if not wh:
            print(f"\n[SIMULATION]\n{payload['embeds'][0]['title']}\n"
                  f"{payload['embeds'][0]['description']}\n", flush=True)
            nouveau = "simulation"
        else:
            nouveau = api.poster(wh, THREAD, payload)
        if not nouveau:
            ok = False
            continue
        premier_ping = False
        state.setdefault("cles", []).append(d["cle"])
        postes.append(f"{d['nom']} ({vendus}/{d['total']})")
        if wh:
            api.souffler()

    if sautes:
        print(f"⚠️ {len(sautes)} drop(s) SAUTE(S) : {'; '.join(sautes[:5])}",
              flush=True)

    state["cles"] = list(dict.fromkeys(state.get("cles", [])))
    api.save_state(STATE_PATH, state, wh, THREAD)

    # ═══ LE SUIVI DU COMIC BOOK DAY : UN message, RECRIT ═══
    comic = suivre_comic_day(sh, state, wh)

    resume = {"neufs": len(neufs), "postes": len(postes),
              "sautes": len(sautes), "comic_day": comic,
              "titres": " | ".join(postes[:3]),
              "duree": f"{time.time() - t0:.0f}s"}
    _log(sheet_id, "OK" if ok else "ECHEC", resume)
    print(f"Retour Discord : {resume}", flush=True)
    return 0 if ok else 1


def suivre_comic_day(sh, state: Dict, wh: str) -> str:
    """Poste (ou reecrit) le message de suivi du dernier Comic Book Day.
    Un message par jour de comic day : tant qu'il est dans la fenetre on
    l'EDITE ; le mercredi suivant en ouvre un nouveau."""
    jour, series = comic_day_recent(sh)
    if not jour or not series:
        return "aucun"
    chaine = chaine_par_uuid(sh, _jours_pt(jour))
    if not chaine:
        print("Comic Book Day : aucune donnee on-chain encore — on attend "
              "(un « 0 vendu » faux serait pire qu'un silence).", flush=True)
        return "sans donnee"

    uuids = [u for s in series for u in s["uuids"]]
    payload = message_comic_day(jour, series, chaine,
                                suivi=paliers(sh, jour, uuids))
    ids = state.setdefault("comic_day", {})
    if not wh:
        print(f"\n[SIMULATION]\n{payload['embeds'][0]['description']}\n",
              flush=True)
        return f"{jour} (simulation)"
    mid = ids.get(jour)
    neuf = (api.editer(wh, THREAD, mid, payload) if mid
            else api.poster(wh, THREAD, payload))
    if not neuf:
        return "echec"
    ids[jour] = neuf
    # menage : on ne garde que les 8 derniers comic days dans l'etat
    for vieux in sorted(ids)[:-8]:
        ids.pop(vieux, None)
    print(f"Comic Book Day {jour} : {len(series)} series, message "
          f"{'reecrit' if mid == neuf else 'poste'} ({neuf}).", flush=True)
    api.souffler()
    return f"{jour} ({len(series)} series)"


def _log(sheet_id: str, statut: str, resume: Dict) -> None:
    try:
        append_log(sheet_id, "discord_retour", statut,
                   "; ".join(f"{k}={v}" for k, v in resume.items()))
    except Exception:                                       # noqa: BLE001
        pass


if __name__ == "__main__":
    sys.exit(run())

# FIN discord_retour.py v6 — les ventes viennent de la CHAINE, le ratio dit ce
# que le chiffre brut cache, et le sondage est confronte a la realite.
