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
* **Le sondage — DEUX LIGNES depuis le 28/07** : la carte d'annonce vit
  desormais dans DEUX salons, le post 📦DROP (partie INVESTISSEUR) et
  📘⎮sondage-drop (PUBLIC). Le bot relit les VOTANTS des deux (pas les
  compteurs : voir `fusionner_votes`), et affiche une ligne par population.
  **Une personne qui a vote des deux cotes ne compte que cote investisseur** —
  elle disparait du decompte public, et le nombre de retires est ECRIT sur la
  carte. Les votes des bots sont exclus a la source (`user.bot`).

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
GRIS = 0x95A5A6

# Les illustrations des messages groupes. ⚠️ Une URL de pièce jointe Discord est
# SIGNEE et EXPIRE (parametres ex/is/hm) : au bout de quelques heures, l'image
# ne s'affiche plus. Pour du durable, heberger l'image ailleurs (ex. le repo
# PUBLIC jetonveve -> raw.githubusercontent.com) et poser l'URL ici.
IMAGE_COMIC_DAY = os.environ.get("DISCORD_RETOUR_IMAGE_COMIC_DAY", "").strip()
IMAGE_FAIBLES = os.environ.get("DISCORD_RETOUR_IMAGE_FAIBLES", "").strip()

# La signature de la maison.
SIGNATURE = os.environ.get("DISCORD_RETOUR_SIGNATURE", "— Maow")


def total_serie(genre: str, supplies: List[int]) -> int:
    """LE TIRAGE D'UNE SERIE. ⚠️ PIEGE MAJEUR, deja paye au chantier classement
    et repaye ici :

    **Pour un COMIC, `supply` (= totalIssued) est le tirage de la SERIE, recopie
    sur CHACUNE des lignes de rarete.** L'additionner donne 5 x 1 000 = 5 000 —
    et Captain America #7, qui a fait SOLD OUT a 1 000, s'affichait a 20 % du
    tirage. On prend donc le MAXIMUM, pas la somme.

    Pour un COLLECTIBLE, `supply` est bien propre a chaque element (Phoenix
    Five : 75 / 1 975 / 475) : la somme est juste.
    Additionner ou maximiser n'est pas un detail de calcul, c'est une question
    de MODELE : que represente une ligne ?"""
    supplies = [s for s in supplies if s]
    if not supplies:
        return 0
    return max(supplies) if genre == "comic" else sum(supplies)


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
    """{cle: note} depuis 🏆A-CLASSEMENT.

    ⚠️ DEUX PIEGES, tous deux payes sur le run reel :
    1. `get_all_records()` EXPLOSE si deux colonnes portent le meme nom (« the
       header row is not unique ») — la page en a.
    2. **LES EN-TETES NE SONT PAS EN LIGNE 1** : la page commence par une
       banniere (« 🆕 À NOTER — COMICS : 3 … »). Chercher les colonnes en
       ligne 1 revient a lire un titre et a conclure qu'il n'y a pas de note.
    → On ANCRE : on balaie les premieres lignes jusqu'a en trouver une qui porte
    A LA FOIS une cle (`series_uuid`/`veve_uuid`) ET une colonne `note`. Meme
    lecon que la page 📊 STATS : **on cherche la donnee, on ne suppose pas ou
    elle est**. Si rien ne colle, la note disparait de la carte — elle ne fait
    echouer personne."""
    try:
        vals = sh.worksheet(CLASSEMENT_TAB).get_all_values()
    except Exception as e:                                  # noqa: BLE001
        print(f"lecture de {CLASSEMENT_TAB} impossible : {e}", file=sys.stderr)
        return {}

    CLES = ("series_uuid", "veve_uuid", "uuid")
    for i, ligne in enumerate(vals[:40]):
        noms = [str(c).strip() for c in ligne]
        bas = [n.lower() for n in noms]
        if "note" not in bas:
            continue
        cle = next((c for c in CLES if c in bas), "")
        if not cle:
            continue
        i_note = bas.index("note")
        i_cle = bas.index(cle)
        out = {}
        for r in vals[i + 1:]:
            if len(r) <= max(i_note, i_cle):
                continue
            k, note = str(r[i_cle]).strip(), str(r[i_note]).strip()
            if k and note and k not in out:       # la 1re occurrence gagne
                out[k] = note
        print(f"{CLASSEMENT_TAB} : en-tetes trouves en ligne {i + 1} "
              f"({len(out)} notes).", flush=True)
        return out

    print(f"{CLASSEMENT_TAB} : aucune ligne d'en-tetes portant « note » ET une "
          f"cle dans les 40 premieres lignes — la note ne sera pas affichee.",
          flush=True)
    return {}


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
    """[(label, valeur, croissance_pct)] pour les paliers dont la journee PT est
    CLOSE.

    ⚠️ **LE 1er PALIER EST UN CUMUL, LES SUIVANTS SONT DES TRANCHES** (demande de
    Preda, et il a raison) : « ~24 h : 263 » puis « ~48 h : 23 » = ce qui s'est
    vendu PENDANT la 2e journee, pas le total. Repeter le cumul a chaque ligne
    noie l'information : ce qu'on veut voir, c'est si la vague retombe. Le
    pourcentage, lui, reste la CROISSANCE (+8.7 %) — il repond a « de combien le
    total a-t-il monte », l'autre chiffre a « combien de plus se sont vendus »."""
    connus = {str(r.get("date") or "")[:10]
              for r in _records(sh, ITEMS_TAB) if r.get("date")}
    out, cumul = [], None
    for label, n in PALIERS:
        jours = _jours_pt(jour, n)
        if jours[-1] not in connus:
            break                          # la journee n'est pas close : STOP
        ch = chaine_par_uuid(sh, jours)
        total = sum(ch.get(u, {}).get("mints", 0) for u in uuids)
        if cumul is None:
            out.append((label, total, None))          # le 1er : un cumul
        else:
            croissance = 100.0 * (total - cumul) / cumul if cumul else None
            out.append((label, total - cumul, croissance))   # les suivants
        cumul = total
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
        d["total"] = total_serie(d["genre"],
                                 [l["supply"] for l in d["lignes"]])
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
            "prix": r.get("store_price_gems"), "supplies": [], "uuids": [],
        })
        d["supplies"].append(dd._n(r.get("supply")))
        u = str(r.get("veve_uuid") or "").strip()
        if u:
            d["uuids"].append(u)
        if not d["prix"] and r.get("store_price_gems"):
            d["prix"] = r["store_price_gems"]

    if not par_jour:
        return None, []
    jour = max(par_jour)
    series = list(par_jour[jour].values())
    for s_ in series:                       # ⚠️ un comic : le MAX, pas la somme
        s_["total"] = total_serie("comic", s_.pop("supplies"))
    return jour, series


# 10 series par message : au-dela, le message devient un mur. Le suivi d'un
# comic day tient donc sur PLUSIEURS messages, tous reecrits a chaque passage.
MAX_LIGNES = int(os.environ.get("DISCORD_RETOUR_COMIC_LIGNES", "10"))
# En dessous de ce nombre de ventes, une serie n'a pas droit a son detail : elle
# rejoint la liste des « faibles ventes », en colonne, sans chiffres. Un comic a
# 3 ventes n'a pas d'histoire a raconter — mais il ne doit pas disparaitre non
# plus (l'absence d'une serie serait, elle, une information fausse).
SEUIL_DETAIL = int(os.environ.get("DISCORD_RETOUR_SEUIL_DETAIL", "15"))


def _classer(series: List[Dict], chaine) -> tuple:
    """(detaillees, faibles, muettes) — tout le monde est quelque part.

    ⚠️ **ZERO VENDU = UN TROU, PAS UN RESULTAT** (Preda est formel : un comic ne
    fait jamais zero vente). On ne les affiche pas, mais on DIT combien il y en
    a — sinon leur absence passerait pour un fait."""
    for s_ in series:
        s_["vendus"] = sum(chaine.get(u, {}).get("mints", 0)
                           for u in s_["uuids"])
        s_["pct"] = _pct(s_["vendus"], s_["total"])
    detail = sorted([s_ for s_ in series if s_["vendus"] >= SEUIL_DETAIL],
                    key=lambda s_: (-s_["pct"], -s_["vendus"]))
    faibles = sorted([s_ for s_ in series
                      if 0 < s_["vendus"] < SEUIL_DETAIL],
                     key=lambda s_: -s_["vendus"])
    muettes = [s_ for s_ in series if s_["vendus"] == 0]
    return detail, faibles, muettes


def messages_comic_day(jour: str, series: List[Dict], chaine, suivi=None):
    """La LISTE des messages du suivi : le detail par paquets de 10, puis les
    faibles ventes en colonne. Tous sont REECRITS a chaque passage."""
    detail, faibles, muettes = _classer(series, chaine)
    tot_supply = sum(s_["total"] for s_ in series)
    tot_vendus = sum(s_["vendus"] for s_ in series)
    pct = _pct(tot_vendus, tot_supply)

    entete = [f"**{len(series)} séries** · {tot_supply:,} exemplaires"
              .replace(",", " "), ""]
    for label, v, croissance in (suivi or []):
        q = f" · **{croissance:+.1f} %**" if croissance is not None else ""
        entete.append(f"Ventes totales après **{label}** : **{v:,}**"
                      .replace(",", " ") + q)

    out = []
    paquets = [detail[i:i + MAX_LIGNES]
               for i in range(0, len(detail), MAX_LIGNES)] or [[]]
    for i, paquet in enumerate(paquets):
        lignes = []
        for s_ in paquet:
            lignes.append(f"**{s_['nom']}**")
            lignes.append(f"`{s_['pct']:5.1f} %` · {s_['total']:,} ex · "
                          f"**{s_['vendus']:,}** vendus".replace(",", " "))
            lignes.append("")                     # de l'air entre chaque comic
        corps = ("\n".join(entete) + "\n\n" if i == 0 else "") \
            + "\n".join(lignes).rstrip()
        titre = (f"📅 Comic Book Day du {jour}" if i == 0
                 else f"📅 Comic Book Day du {jour} — suite {i + 1}")
        e = {"title": titre, "color": couleur(pct),
             "description": corps[:4000] or "—"}
        if i == 0 and IMAGE_COMIC_DAY:      # l'illustration, sur le 1er seul
            e["image"] = {"url": IMAGE_COMIC_DAY}
        out.append({"content": ("🔍 **Suivi du Comic Book Day**" if i == 0
                                else ""),
                    "embeds": [e], "allowed_mentions": api.mentions()})

    if faibles:
        noms = "\n".join(f"• {s_['nom']}" for s_ in faibles)
        note = (f"*Ces séries ont fait moins de {SEUIL_DETAIL} ventes sur la "
                f"période : trop peu pour qu'un taux d'écoulement veuille dire "
                f"quelque chose. Elles sont listées pour mémoire, sans "
                f"chiffres.*")
        if muettes:
            note += (f"\n*({len(muettes)} autre(s) série(s) sans aucune donnée "
                     f"de vente {SIGNATURE})*")
        e = {"title": f"🌱 Faibles ventes — {len(faibles)} série(s)",
             "color": GRIS,
             "description": (noms + "\n\n" + note)[:4000]}
        if IMAGE_FAIBLES:
            e["image"] = {"url": IMAGE_FAIBLES}
        out.append({"content": "", "embeds": [e],
                    "allowed_mentions": api.mentions()})
    return out


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
# LE SONDAGE — DEUX SALONS, DEUX POPULATIONS, UNE SEULE VOIX PAR PERSONNE
# ---------------------------------------------------------------------------
# La carte d'annonce vit maintenant a DEUX endroits : le post 📦DROP (partie
# INVESTISSEUR du serveur) et le salon 📘sondage-drop (PUBLIC). Preda est clair
# sur ce qu'il veut en tirer :
#   * DEUX LIGNES SEPAREES dans le retour — les investisseurs et le public ne
#     sont pas le meme monde, et melanger leurs pronostics detruirait justement
#     l'information qu'on cherche (« qui a vu juste ? ») ;
#   * UNE PERSONNE, UNE VOIX — celui qui vote des deux cotes ne compte QUE cote
#     investisseur, et disparait du decompte public.
#
# ⚠️ CE CALCUL EST IMPOSSIBLE AVEC DES COMPTEURS. Additionner « 12 » et « 7 »
# ne dira jamais combien de personnes sont dans les deux. D'ou `lire_votants`
# (discord_api), qui rend des IDENTITES. Un total dedoublonne a partir de
# compteurs serait un chiffre faux qui a l'air juste.

ORDRE_VOTES = [e.strip() for e in
               os.environ.get("DISCORD_DROPS_REACTIONS", "🇩,🇲,❌").split(",")
               if e.strip()]


def _ranger(votes: Dict[str, int]) -> Dict[str, int]:
    """Les emojis dans l'ordre du sondage (🇩 / 🇲 / ❌), les inconnus a la fin.
    Un ordre d'affichage qui change d'une carte a l'autre se lit mal."""
    connus = {e: votes[e] for e in ORDRE_VOTES if e in votes}
    autres = {e: n for e, n in votes.items() if e not in connus}
    return {**connus, **autres}


def fusionner_votes(prive: Dict[str, Any], public: Dict[str, Any]) -> Dict:
    """{emoji: votants} x2 -> {'prive': {emoji: n}, 'public': {emoji: n},
    'doublons': n}.

    FONCTION PURE (aucun reseau) : c'est elle qui porte la regle, donc c'est
    elle qu'on teste. Le cote PRIVE est compte tel quel ; le cote PUBLIC est
    ampute de **tous** ceux qui ont vote cote investisseur — quel que soit
    l'emoji choisi la-bas. Voter 🇩 en prive et ❌ en public n'ajoute donc pas
    une voix au public : la personne s'est deja exprimee.
    """
    deja: set = set()
    for gens in (prive or {}).values():
        deja |= set(gens or ())

    v_prive = {e: len(set(g or ())) for e, g in (prive or {}).items()}
    v_public, doublons = {}, set()
    for e, g in (public or {}).items():
        g = set(g or ())
        doublons |= (g & deja)
        v_public[e] = len(g - deja)

    return {"prive": _ranger(v_prive), "public": _ranger(v_public),
            "doublons": len(doublons)}


def normaliser_sondage(s: Any) -> Dict:
    """Un sondage memorise -> la forme a deux lignes.

    ⚠️ COMPATIBILITE ASCENDANTE : l'etat en production contient des sondages de
    l'ANCIEN format (`{emoji: nombre}`, le post investisseur seul). Les relire
    comme la nouvelle forme rendrait des lignes vides — les cartes deja posees
    perdraient leur sondage a la premiere reecriture. Un ancien format est donc
    lu comme « tout en investisseur », ce qu'il est.
    """
    if not isinstance(s, dict):
        return {"prive": {}, "public": {}, "doublons": 0}
    if "prive" in s or "public" in s:
        return {"prive": _ranger(s.get("prive") or {}),
                "public": _ranger(s.get("public") or {}),
                "doublons": int(s.get("doublons") or 0)}
    return {"prive": _ranger({e: int(n or 0) for e, n in s.items()}),
            "public": {}, "doublons": 0}


def lire_sondage(mid_prive: str, mid_public: str) -> Dict:
    """Les deux cartes relues par le bot, fusionnees. Sans token de bot ou sans
    carte, on rend des lignes vides — jamais une exception."""
    prive = (api.lire_votants(dd.THREAD, mid_prive) if mid_prive else {})
    public = (api.lire_votants(dd.salon_miroir(), mid_public)
              if mid_public else {})
    fusion = fusionner_votes(prive, public)
    if fusion["doublons"]:
        print(f"  🗳️ {fusion['doublons']} votant(s) present(s) dans les DEUX "
              f"salons — comptes cote investisseur uniquement.", flush=True)
    return fusion


# ---------------------------------------------------------------------------
# La carte
# ---------------------------------------------------------------------------

def _pct(vendus: int, total: int) -> float:
    return min(100.0, 100.0 * vendus / total) if total else 0.0


def est_epuise(vendus: int, total: int) -> bool:
    """SOLD OUT. Un drop epuise n'a plus d'histoire : il n'y a plus rien a
    vendre, donc plus rien a suivre. (On tolere un leger depassement : la chaine
    compte parfois un mint de plus que le tirage declare — mieux vaut dire
    « sold out » que « 100,2 % ».)"""
    return bool(total) and vendus >= total


def couleur(pct: float) -> int:
    """Vert = ca s'est arrache · rouge = ca n'est pas parti. Une couleur se lit
    plus vite qu'un chiffre."""
    return VERT if pct >= 50 else (ORANGE if pct >= 15 else ROUGE)


def lignes_sondage(sondage: Any) -> List[str]:
    """Les DEUX lignes du sondage — investisseurs, puis public.

    Une ligne sans le moindre vote ne s'affiche pas : « 🇩 0 · 🇲 0 · ❌ 0 »
    n'apprend rien et fait croire a un desinteret alors que, le plus souvent,
    c'est simplement que le salon n'existait pas encore quand la carte est
    partie. Le nombre de votants retires du public est ECRIT : un dedoublonnage
    silencieux ferait passer un chiffre ampute pour un chiffre brut.
    """
    s = normaliser_sondage(sondage)
    out = []
    if sum(s["prive"].values()):
        detail = " · ".join(f"{e} **{n}**" for e, n in s["prive"].items() if n)
        out.append(f"🗳️ **Sondage investisseurs** : {detail}")
    if sum(s["public"].values()):
        detail = " · ".join(f"{e} **{n}**" for e, n in s["public"].items() if n)
        ligne = f"🗳️ **Sondage public** : {detail}"
        if s["doublons"]:
            ligne += (f"\n*({s['doublons']} votant(s) déjà compté(s) côté "
                      f"investisseurs, retirés d'ici — une personne, une voix)*")
        out.append(ligne)
    return out


def carte(d: Dict, chaine: Dict[str, Dict[str, int]], note: str,
          sondage: Any, suivi=None) -> Dict:
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

    prix = dd._prix(d.get("prix"), d["genre"])
    if prix:
        lignes.append(f"💎 **Prix drop** : {prix} gems")
    lignes.append(f"📦 **Mint total** : {d['total']:,}".replace(",", " "))
    epuise = est_epuise(vendus, d["total"])
    if epuise:
        # SOLD OUT : le stock est parti. Continuer a montrer des paliers serait
        # absurde — il n'y a plus rien a vendre. La carte est CLOSE.
        lignes.append(f"🛒 **Vendus** : {vendus:,}".replace(",", " ")
                      + "  ·  🔥 **SOLD OUT**")
    else:
        lignes.append(f"🛒 **Vendus** : {vendus:,}".replace(",", " ")
                      + f"  ·  **{pct:.1f} %** du tirage")

        # LES PALIERS. La carte est REECRITE a 48 h puis 72 h pour les
        # completer : un retour fige a J+1 ne dit pas si la vague retombe ou si
        # elle continue. Le 1er palier est un CUMUL, les suivants des TRANCHES.
        if suivi:
            lignes.append("")
            for label, v, croissance in suivi:
                queue = (f" · **{croissance:+.1f} %**" if croissance is not None
                         else f" · **{_pct(v, d['total']):.1f} %** du tirage")
                lignes.append(f"Drop après **{label}** : **{v:,}**"
                              .replace(",", " ") + queue)

    bas = []
    if note:
        bas.append(f"🏆 **Classement** : {note}")
    bas += lignes_sondage(sondage)
    if bas:
        lignes += [""] + bas

    lignes += ["", f"[Page VeVe](<{dd._lien(d)}>)"]

    e = {"title": f"{licence} {genre} : {nom}".strip(),
         "color": 0xF1C40F if epuise else couleur(pct),
         "description": "\n".join(lignes)[:4000]}
    if d.get("image"):
        e["image"] = {"url": d["image"]}
    return e


def message(d: Dict, chaine, note: str, sondage: Any,
            ping: bool, suivi=None) -> Dict:
    tete = "🔍 **Retour sur drop**"
    contenu = f"<@&{ROLE}> {tete}" if (ping and ROLE) else tete
    return {"content": contenu,
            "embeds": [carte(d, chaine, note, sondage, suivi)],
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

    # ═══ LE SUIVI DU COMIC BOOK DAY : TOUJOURS (hors purger/avalanche), MEME
    # sans drop regulier a debriefer — sinon un jour sans drop le SAUTAIT. L'etat
    # est sauve JUSTE APRES pour que les ids de ses messages soient persistes :
    # au run suivant on EDITE au lieu de republier. (Le vrai fix du 7h59/11h35 =
    # ceci + le push d'etat fiabilise cote discord.yml : un `push || true` seul
    # perdait l'etat quand un autre workflow avait pousse entre-temps.)
    comic = suivre_comic_day(sh, state, wh)
    api.save_state(STATE_PATH, state, wh, THREAD)

    if not neufs:
        print("Retour : rien a debriefer (comic day traite).", flush=True)
        _log(sheet_id, "OK", {"neufs": 0, "comic_day": comic,
                              "duree": f"{time.time() - t0:.0f}s"})
        return 0

    # Les journees PT a lire, pour TOUS les drops d'un coup (une seule lecture
    # de ChainItems : c'est un gros onglet).
    jours = sorted({j for d in neufs for j in _jours_pt(d["jour"], 4)})
    chaine = chaine_par_uuid(sh, jours)
    notes = notes_de_classement(sh)
    # Les ids des cartes d'annonce, poses par le module `drops`. DEUX jeux
    # depuis le 28/07 : le post investisseur (`messages`) et le miroir du salon
    # public (`miroir`). Une cle absente du miroir = une carte anterieure au
    # salon public : sa ligne « Sondage public » sera simplement absente.
    etat_drops = api.load_state(dd.STATE_PATH, api.webhook(dd.MODULE),
                                dd.THREAD)
    annonces = etat_drops.get("messages", {})
    miroirs = etat_drops.get("miroir", {})
    # Les cartes EN COURS : posees, mais dont les paliers ne sont pas tous la.
    # Elles seront REECRITES a 48 h puis 72 h.
    cartes = state.setdefault("cartes", {})

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

        deja = cartes.get(d["cle"]) or {}

        # ⚠️ LE SONDAGE EST FIGE A LA CREATION. Il dit ce que le groupe pensait
        # AVANT de savoir — le relire a chaque reecriture le contaminerait par
        # ce qui s'est passe depuis. Un pronostic qu'on corrige apres coup n'est
        # plus un pronostic.
        if "sondage" in deja:
            sondage = normaliser_sondage(deja["sondage"])
        else:
            sondage = lire_sondage(annonces.get(d["cle"]),
                                   miroirs.get(d["cle"]))

        note = notes.get(d["cle"], "")
        suivi = paliers(sh, d["jour"], [l["uuid"] for l in d["lignes"]])
        payload = message(d, chaine, note, sondage, ping=premier_ping,
                          suivi=suivi)

        if not wh:
            print(f"\n[SIMULATION]\n{payload['embeds'][0]['title']}\n"
                  f"{payload['embeds'][0]['description']}\n", flush=True)
            nouveau = "simulation"
        elif deja.get("mid"):
            nouveau = api.editer(wh, THREAD, deja["mid"], payload)
        else:
            nouveau = api.poster(wh, THREAD, payload)
        if not nouveau:
            ok = False
            continue

        if not deja.get("mid"):
            premier_ping = False
        cartes[d["cle"]] = {"mid": nouveau, "sondage": sondage,
                            "paliers": len(suivi), "jour": d["jour"]}

        # La carte est FINIE quand ses trois paliers sont la — ou quand le drop
        # est SOLD OUT : il n'y a plus rien a suivre.
        if len(suivi) >= len(PALIERS) or est_epuise(vendus, d["total"]):
            state.setdefault("cles", []).append(d["cle"])
            cartes.pop(d["cle"], None)

        etat = ("posté" if not deja.get("mid")
                else f"réécrit ({len(suivi)}/{len(PALIERS)} paliers)")
        postes.append(f"{d['nom']} ({vendus}/{d['total']}, {etat})")
        if wh:
            api.souffler()

    if sautes:
        print(f"⚠️ {len(sautes)} drop(s) SAUTE(S) : {'; '.join(sautes[:5])}",
              flush=True)

    state["cles"] = list(dict.fromkeys(state.get("cles", [])))
    api.save_state(STATE_PATH, state, wh, THREAD)
    # (le suivi comic day a deja tourne plus haut, avant le early-return — `comic`
    # est deja calcule et repris dans le resume ci-dessous.)

    resume = {"neufs": len(neufs), "postes": len(postes),
              "sautes": len(sautes), "comic_day": comic,
              "titres": " | ".join(postes[:3]),
              "duree": f"{time.time() - t0:.0f}s"}
    _log(sheet_id, "OK" if ok else "ECHEC", resume)
    print(f"Retour Discord : {resume}", flush=True)
    return 0 if ok else 1


def suivre_comic_day(sh, state: Dict, wh: str) -> str:
    """Poste (ou reecrit) LES messages de suivi du dernier Comic Book Day.
    Un jeu de messages par comic day : tant que la journee est dans la fenetre
    ils sont EDITES ; le mercredi suivant en ouvre de nouveaux."""
    jour, series = comic_day_recent(sh)
    if not jour or not series:
        return "aucun"
    chaine = chaine_par_uuid(sh, _jours_pt(jour, 4))
    if not chaine:
        print("Comic Book Day : aucune donnee on-chain encore — on attend "
              "(un « 0 vendu » faux serait pire qu'un silence).", flush=True)
        return "sans donnee"

    uuids = [u for s_ in series for u in s_["uuids"]]
    payloads = messages_comic_day(jour, series, chaine,
                                  suivi=paliers(sh, jour, uuids))

    ids = state.setdefault("comic_day", {})
    anciens = ids.get(jour) or []
    if isinstance(anciens, str):          # etat des versions precedentes
        anciens = [anciens]

    if not wh:
        for p in payloads:
            print(f"\n[SIMULATION]\n{p['embeds'][0]['description']}\n",
                  flush=True)
        return f"{jour} (simulation, {len(payloads)} messages)"

    neufs = []
    for i, p in enumerate(payloads):
        mid = anciens[i] if i < len(anciens) else None
        r = (api.editer(wh, THREAD, mid, p) if mid
             else api.poster(wh, THREAD, p))
        if not r:
            break                     # plafond atteint : le reste au prochain
        neufs.append(r)
        api.souffler()
    if neufs:
        ids[jour] = neufs + anciens[len(neufs):]
    for vieux in sorted(ids)[:-8]:
        ids.pop(vieux, None)
    print(f"Comic Book Day {jour} : {len(series)} series, "
          f"{len(neufs)}/{len(payloads)} message(s) ecrits.", flush=True)
    return f"{jour} ({len(series)} series, {len(neufs)} msg)"


def _log(sheet_id: str, statut: str, resume: Dict) -> None:
    try:
        append_log(sheet_id, "discord_retour", statut,
                   "; ".join(f"{k}={v}" for k, v in resume.items()))
    except Exception:                                       # noqa: BLE001
        pass


if __name__ == "__main__":
    sys.exit(run())

# FIN discord_retour.py v11 — les ventes viennent de la CHAINE, le ratio dit ce
# que le chiffre brut cache, et le sondage est confronte a la realite — en DEUX
# lignes (investisseurs / public), une personne ne comptant jamais deux fois.
