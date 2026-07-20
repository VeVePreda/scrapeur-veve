# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/discord_drops_sortis.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""📦 Marquer les fiches dont le drop est PASSE.

⚠️ CE FICHIER VA DANS LE DEPOT `scrapeur-veve`, dans `scraper/`.
   PAS dans jetonveve, PAS dans Predabot.

═══ LE PROBLEME ═══

Le post 📦 DROP accumule les cartes des drops a venir. Une fois la date
passee, rien ne les distingue de celles qui arrivent : il faut lire la date
de chaque carte pour savoir ou on en est. On ajoute donc une marque visible
d'un coup d'oeil, et la carte devient grise.

═══ POURQUOI CE N'EST PAS DANS LE BOT DISCORD ═══

Les cartes de drop sont postees par WEBHOOK (`api.poster`). Discord interdit
a un BOT d'editer le message d'un webhook — le bot always-on n'aurait donc
jamais pu les toucher, et on l'aurait appris en production, sur une carte
qui refuse silencieusement de se mettre a jour.
Un webhook, lui, peut rediter SES PROPRES messages : c'est deja ce que fait
`annoncer_comic_day()`. Ce module reprend exactement ce chemin.

═══ CE QU'IL NE FAIT JAMAIS ═══

Il ne peut pas faire echouer un run : tout est en try/except, et le pire
qui puisse arriver est qu'une carte reste non marquee jusqu'au tour suivant.
Il ne re-pingue personne : `allowed_mentions` est vide a l'edition — une
carte reecrite ne doit pas re-sonner (regle deja posee pour le Comic Day).
"""
import time
from typing import Callable, Dict, List, Optional, Tuple

# La marque. En tete de message : c'est la premiere chose qu'on lit en
# faisant defiler le post.
MARQUE = "✅ **DROP SORTI**"
# Gris Discord : la carte s'efface visuellement sans disparaitre.
GRIS = 0x99AAB5
# Combien de cartes au maximum par run. Sans plafond, le premier passage
# rattraperait des mois d'un coup et taperait dans les limites d'API.
PLAFOND_DEFAUT = 5
# Limite dure d'un message Discord.
MAX_CONTENU = 2000


# --------------------------------------------------------------- pur (testable)

def est_passe(ts, maintenant: float) -> bool:
    """Le drop a-t-il eu lieu ?

    Un ts absent ou illisible rend False : dans le doute, on ne marque pas.
    Marquer a tort une carte a venir serait pire que de ne rien marquer —
    on croirait le drop passe et on ne le regarderait plus.
    """
    if ts in (None, ""):
        return False
    try:
        return float(ts) <= maintenant
    except (TypeError, ValueError):
        return False


def deja_marque(contenu: str) -> bool:
    """La carte porte-t-elle deja la marque ?

    Garde-fou EN PLUS de l'etat : si l'etat se perd ou est reconstruit, on
    ne veut pas empiler dix marques sur la meme carte.
    """
    return MARQUE in (contenu or "")


def contenu_marque(contenu: str) -> str:
    """Prefixe le contenu de la marque, sans jamais depasser la limite.

    Si l'ajout ferait deborder, on rogne LA FIN. Perdre la derniere ligne
    d'un drop deja sorti est sans consequence ; se faire refuser l'edition
    entiere par Discord en aurait une.
    """
    contenu = contenu or ""
    if deja_marque(contenu):
        return contenu
    tete = f"{MARQUE}\n"
    place = MAX_CONTENU - len(tete)
    return tete + contenu[:place]


def embeds_gris(embeds: Optional[List[Dict]]) -> List[Dict]:
    """Rend les embeds passes en gris. Ne touche a rien d'autre :
    l'illustration et le lien doivent survivre intacts."""
    sortie = []
    for e in embeds or []:
        copie = dict(e)
        copie["color"] = GRIS
        sortie.append(copie)
    return sortie


def a_marquer(messages: Dict[str, str], dates: Dict, deja,
              maintenant: float = None,
              plafond: int = PLAFOND_DEFAUT) -> List[Tuple[str, str]]:
    """Les (cle, message_id) a marquer ce tour-ci.

    `messages` : {cle_serie: message_id} — l'etat de discord_drops.
    `dates`    : {cle_serie: ts} — releve dans le Sheet a chaque run.
    `deja`     : les cles deja marquees.

    Une cle sans date connue est ignoree SANS BRUIT : la serie a pu sortir
    du catalogue, et ce n'est pas une anomalie.
    """
    maintenant = time.time() if maintenant is None else maintenant
    deja = set(deja or [])
    sortie = []
    for cle, mid in (messages or {}).items():
        if cle in deja or not mid or mid == "simulation":
            continue
        if not est_passe(dates.get(cle), maintenant):
            continue
        sortie.append((cle, mid))
        if len(sortie) >= plafond:
            break
    return sortie


def payload(contenu: str, embeds: Optional[List[Dict]],
            mentions_vides: Dict) -> Dict:
    """La charge d'edition complete.

    ⚠️ Une edition Discord REMPLACE : n'envoyer que le contenu ferait
    disparaitre l'illustration. On renvoie donc toujours les deux.
    """
    charge = {"content": contenu_marque(contenu),
              "allowed_mentions": mentions_vides}
    if embeds:
        charge["embeds"] = embeds_gris(embeds)
    return charge


# --------------------------------------------------------------- orchestration

def marquer(messages: Dict[str, str], dates: Dict, state: Dict,
            lire: Callable, editer: Callable, mentions_vides: Dict,
            souffler: Callable = None, plafond: int = PLAFOND_DEFAUT,
            journal: Callable = print, maintenant: float = None) -> int:
    """Marque les cartes dont le drop est passe. Rend le nombre marque.

    Les acces reseau arrivent par `lire` et `editer`, et l'HORLOGE par
    `maintenant` : ce module ne connait ni Discord, ni le Sheet, ni la date
    du jour. Il se teste donc entierement a sec — y compris les cas qui, en
    production, n'arrivent qu'une fois tous les six mois.

    N'EMET AUCUNE EXCEPTION.
    """
    sortis = list(state.setdefault("sortis", []))
    candidats = a_marquer(messages, dates, sortis, maintenant=maintenant,
                          plafond=plafond)

    # ⭐ ON PARLE MEME QUAND ON NE FAIT RIEN (defaut corrige le 19/07).
    # Avant, ce module se taisait quand il n'y avait rien a marquer — donc
    # « il a tourne et n'avait rien a faire » et « il n'est pas installe »
    # produisaient EXACTEMENT la meme sortie. Impossible de savoir lequel
    # on regardait. Un garde-fou muet est un mur.
    connues = len(messages or {})
    journal(f"📦 marquage des drops sortis : {connues} carte(s) connue(s) · "
            f"{len(sortis)} deja marquee(s) · {len(candidats)} a traiter.")
    if connues == 0:
        journal("   (l'etat ne contient aucune carte : seules celles postees "
                "APRES l'arrivee de state['messages'] ont un identifiant "
                "conserve — le marquage demarrera aux prochains drops.)")
    if not candidats:
        return 0

    marques = 0
    for cle, mid in candidats:
        try:
            message = lire(mid)
            if message is None:
                # Message illisible (supprime a la main ?). On note la cle
                # comme traitee : sans cela on la retenterait a chaque run
                # jusqu'a la fin des temps.
                journal(f"  carte {mid} illisible — notee comme traitee.")
                sortis.append(cle)
                continue

            contenu = message.get("content") or ""
            if deja_marque(contenu):
                sortis.append(cle)
                continue

            neuf = editer(mid, payload(contenu, message.get("embeds"),
                                       mentions_vides))
            if neuf:
                sortis.append(cle)
                marques += 1
                journal(f"  ✅ drop sorti marque : {cle}")
            else:
                # Echec d'edition : on NE note rien, la carte repassera au
                # prochain run. Une marque manquante se rattrape ; une cle
                # notee a tort ne se rattrape jamais.
                journal(f"  ⚠️ marquage refuse pour {cle} — on reessaiera.")
            if souffler:
                souffler()
        except Exception as err:                            # noqa: BLE001
            journal(f"  ⚠️ marquage impossible pour {cle} ({err}) — "
                    "on reessaiera.")

    # L'etat ne doit pas gonfler indefiniment : on garde les 400 dernieres
    # cles, largement de quoi couvrir la fenetre d'annonce.
    state["sortis"] = list(dict.fromkeys(sortis))[-400:]
    return marques
