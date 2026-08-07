# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : scraper/sentinelle_absence.py
"""🛰️ sentinelle_absence — « qui aurait du tourner aujourd'hui, et n'a rien fait ? »

POURQUOI CE MODULE EXISTE
-------------------------
Le grand livre est reste gele du 24/07 au 07/08/2026 sans que personne le voie.
`ledger-writer` (cron hebdo) consommait `analytics.yml`, qui etait en
`workflow_dispatch` SEUL. Un consommateur programme branche sur un producteur
manuel ne se referme que quand quelqu'un y pense.

⭐⭐⭐ LA PANNE LA PLUS DANGEREUSE NE PRODUIT AUCUN RUN ROUGE. analytics ne
tournait pas, donc n'echouait pas : AUCUN `if: failure()` ne l'aurait vue. C'est
la difference entre les deux etages, et ce module est le second :

    alerte d'echec      « ce run est-il tombe ? »       -> if: failure()
    sentinelle d'absence« qui n'a rien fait ? »         -> CE MODULE

⛔ ET C'EST POUR CA QU'ELLE LIT UNE **DECLARATION**, PAS LES RUNS EXISTANTS.
Un balayage des workflows presents ne verrait jamais celui qui a disparu ni
celui qui n'a jamais tourne. « Zero parce que c'est casse » et « zero parce
qu'il n'y a rien » se ressemblent sur le disque et sont l'inverse.

LES QUATRE QUESTIONS QU'ELLE POSE
---------------------------------
  1. AGE DU RUN   — dernier run REUSSI plus vieux que `fenetre_h` ?
  2. AGE DE L'ECRIT — la cible declaree dans `ecrit` a-t-elle bouge ?
                    (seulement quand `preuve: ecriture` — voir ci-dessous)
  3. ORDRE        — un consommateur est-il plus VIEUX que son producteur ?
  4. AVEUGLEMENT  — y a-t-il un depot que je n'ai pas pu lire ?

⭐⭐⭐ (3) EST LE POINT QUE TOUT LE MONDE OUBLIE : L'AGE NE SUFFIT PAS, L'ORDRE
COMPTE. `ledger-writer` (jeudi, VeVePreda/scrapeur-veve) consomme `analytics`
(mercredi, fanablefrance/jetonveve). `workflow_run` NE FRANCHIT PAS la frontiere
d'un depot : le jeudi, ledger-writer part a l'heure quel que soit l'etat
d'analytics. Si analytics glisse ou tombe, le ledger s'ecrit depuis un derive
perime — ET LE RUN EST VERT. Les deux sont frais au sens de l'age, et le
resultat est faux. D'ou : date(consommateur) > date(producteur).

🔴🔴 POURQUOI DEUX PREUVES, ET PAS UNE SEULE (mesure du 07/08/2026)
------------------------------------------------------------------
12 des 25 workflows a cron finissent par :

    git diff --cached --quiet && { echo "Rien a committer."; exit 0; }

Quand rien ne change, ils NE LAISSENT AUCUNE TRACE D'ECRITURE. Une sentinelle
branchee sur les seules dates d'ecriture les declarerait morts alors qu'ils vont
tres bien — et CINQ d'entre eux sont critiques (`daily`, `hprix-bridge`,
`floor-watch`, `rebuild-daily`, `price-history`).

⭐⭐⭐ DE FAUSSES ALERTES SUR LES LIGNES CRITIQUES SONT PIRES QUE PAS D'ALERTE :
elles apprennent a ignorer exactement ce qu'il fallait lire. La sentinelle serait
nee en se decredibilisant sur ses lignes les plus importantes.

  preuve: ecriture -> on lit la date de la cible (commit ou release)
  preuve: run      -> on lit le dernier run REUSSI, et RIEN D'AUTRE

⚠️ `preuve: run` EST LE MAILLON FAIBLE, ET IL FAUT LE SAVOIR : `success()` dit
« le run a-t-il fini », pas « le travail a-t-il avance » (lecon d'astronema).
Le vrai correctif, plus tard : un battement de coeur ecrit a CHAQUE tour, diff
ou pas. En attendant, la sentinelle le DIT dans son rapport plutot que de le
laisser croire.

⭐⭐ ELLE POSTE AUSSI QUAND TOUT VA BIEN, une ligne par jour. Une sentinelle
morte ne produit aucune alerte, ce qui est indistinguable de « tout va bien » :
sans battement quotidien, son propre silence serait rassurant.

⭐⭐⭐ ET ELLE ANNONCE CE QU'ELLE NE SAIT PAS. Un manifeste a moitie rempli qui
ne le dit pas est pire qu'un vide : complet, il devient credible, donc jamais
relu — le mecanisme exact qui a laisse le ledger geler quinze jours. Elle compte
donc chaque jour les fenetres non validees et les cibles illisibles.

⛔ AUCUN RESEAU HORS DE `_http_json`. Tout le raisonnement est pur et se teste
sans toucher a GitHub : une sentinelle doit etre plus fiable que ce qu'elle
surveille.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import yaml

API = "https://api.github.com"

# ⚠️ QUI POSSEDE QUOI. Ce n'est PAS devinable depuis le manifeste, et une erreur
# ici ne produit pas une exception mais un 404 -> qui ressemble a « n'a jamais
# tourne ». Un depot dont le proprietaire vaut "?" est declare AVEUGLE, jamais
# silencieusement saute.
PROPRIETAIRE = {
    "scrapeur-veve": "VeVePreda",
    "veve-sites": "VeVePreda",
    "jetonveve": "fanablefrance",
    "astronema": "?",   # 🔴 A RENSEIGNER — tant que c'est "?", la sentinelle le dit
    "paolo": "?",       # 🔴 A RENSEIGNER
}

# ⭐⭐⭐ TROIS SORTES DE CIBLES, ET LES CONFONDRE SERAIT LE PIRE DES DEUX MONDES.
#   git:… / release:…  -> verifiables par l'API GitHub
#   sheet / discord    -> **HORS DE PORTEE** : ce sont de vraies ecritures (26
#                         vers le Sheet, 8 vers Discord) que l'API GitHub NE
#                         PEUT PAS voir. Ce n'est pas une saleté de manifeste,
#                         c'est une limite de l'instrument.
#   le reste           -> ILLISIBLE : miettes de shell tirees des YAML par le
#                         script du v0 ("release:--clobber", "git:2>/dev/null").
# Les ranger ensemble ferait passer une limite connue pour une erreur a corriger
# — ou l'inverse, ce qui est pire : une erreur pour une fatalite.
HORS_PORTEE = {"sheet", "discord"}


def genre_cible(c: str) -> str:
    if c in HORS_PORTEE:
        return "hors_portee"
    if ":" not in c:
        return "illisible"
    genre, ref = c.split(":", 1)
    if genre not in ("git", "release") or not ref:
        return "illisible"
    if ref.startswith("-") or any(x in ref for x in (">", "<", "|", "$", "*", " ")):
        return "illisible"
    return genre


@dataclass
class Constat:
    """Ce que la sentinelle sait d'UNE entree du manifeste."""
    depot: str
    fichier: str
    critique: bool
    fenetre_h: float
    preuve: str
    vu_le: datetime | None = None      # date retenue comme preuve de vie
    aveugle: str = ""                  # motif si on n'a rien pu lire
    illisibles: list = field(default_factory=list)
    hors_portee: list = field(default_factory=list)

    @property
    def age_h(self) -> float | None:
        if self.vu_le is None:
            return None
        return (datetime.now(timezone.utc) - self.vu_le).total_seconds() / 3600

    @property
    def en_retard(self) -> bool:
        a = self.age_h
        return a is not None and a > self.fenetre_h

    @property
    def cle(self) -> str:
        return f"{self.depot}/{self.fichier}"


# ─────────────────────────────────────────────────────────────────────────────
# LA SEULE PARTIE QUI TOUCHE LE RESEAU
# ─────────────────────────────────────────────────────────────────────────────
def _http_json(url: str, jeton: str) -> tuple[dict | list | None, str]:
    """Rend (donnees, erreur). ⭐⭐⭐ UNE ERREUR N'EST PAS UN RESULTAT VIDE.
    Un 404 (jeton sans portee sur le depot) et « aucun run » se ressemblent
    trait pour trait dans un `try/except: return []` — et le second declenche
    une alerte, le premier ne le devrait pas. On les separe ici, une fois."""
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {jeton}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "sentinelle-absence",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r), ""
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:                       # reseau, DNS, timeout
        return None, type(e).__name__


def _date(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class Source:
    """Lit GitHub. Remplacee par un double dans les tests."""

    def __init__(self, jeton: str):
        self.jeton = jeton

    def dernier_run_reussi(self, owner, depot, fichier) -> tuple[datetime | None, str]:
        u = (f"{API}/repos/{owner}/{depot}/actions/workflows/{fichier}"
             f"/runs?status=success&per_page=1")
        d, err = _http_json(u, self.jeton)
        if err:
            return None, err
        runs = (d or {}).get("workflow_runs") or []
        if not runs:
            return None, ""          # ⭐ pas une erreur : vraiment aucun run reussi
        return _date(runs[0].get("updated_at") or runs[0].get("created_at")), ""

    def dernier_commit(self, owner, depot, chemin) -> tuple[datetime | None, str]:
        u = f"{API}/repos/{owner}/{depot}/commits?path={chemin}&per_page=1"
        d, err = _http_json(u, self.jeton)
        if err:
            return None, err
        if not d:
            return None, ""
        return _date(d[0]["commit"]["committer"]["date"]), ""

    def derniere_release(self, owner, depot, tag) -> tuple[datetime | None, str]:
        d, err = _http_json(f"{API}/repos/{owner}/{depot}/releases/tags/{tag}", self.jeton)
        if err:
            return None, err
        dates = [_date(d.get("published_at")), _date(d.get("created_at"))]
        dates += [_date(a.get("updated_at")) for a in (d.get("assets") or [])]
        dates = [x for x in dates if x]
        return (max(dates) if dates else None), ""


# ─────────────────────────────────────────────────────────────────────────────
# LE RAISONNEMENT — pur, hors reseau, entierement testable
# ─────────────────────────────────────────────────────────────────────────────
def ausculter(entree: dict, source: Source) -> Constat:
    depot, fichier = entree["depot"], entree["fichier"]
    c = Constat(depot=depot, fichier=fichier,
                critique=bool(entree.get("critique")),
                fenetre_h=float(entree["fenetre_h"]),
                preuve=entree.get("preuve", "run"))

    owner = PROPRIETAIRE.get(depot, "?")
    if owner == "?":
        c.aveugle = "proprietaire du depot non declare"
        return c

    # (1) l'age du dernier run reussi — toujours, quelle que soit la preuve
    vu, err = source.dernier_run_reussi(owner, depot, fichier)
    if err:
        c.aveugle = f"API runs: {err}"
        return c
    c.vu_le = vu

    # (2) l'age de l'ecrit — SEULEMENT si le workflow ecrit a chaque tour.
    #     ⛔ Sur un workflow a garde de diff, l'absence d'ecriture est NORMALE :
    #        l'exiger fabriquerait une fausse alerte quotidienne.
    if c.preuve == "ecriture":
        dates = []
        for cible in entree.get("ecrit") or []:
            genre = genre_cible(cible)
            if genre == "hors_portee":
                c.hors_portee.append(cible)
                continue
            if genre == "illisible":
                c.illisibles.append(cible)
                continue
            ref = cible.split(":", 1)[1]
            d, err = (source.dernier_commit(owner, depot, ref) if genre == "git"
                      else source.derniere_release(owner, depot, ref))
            if err:
                c.illisibles.append(f"{cible} ({err})")
                continue
            if d:
                dates.append(d)
        # ⭐ On retient la cible la PLUS RECENTE : plusieurs cibles veulent dire
        #    « le travail atterrit a plusieurs endroits », pas « toutes doivent
        #    bouger ». Exiger la plus vieille ferait crier sur un fichier qui,
        #    lui, a une garde de diff.
        if dates:
            c.vu_le = max(dates) if c.vu_le is None else max(max(dates), c.vu_le)
    return c


def desordres(constats: dict, manifeste: list) -> list:
    """⭐⭐⭐ L'ORDRE : un consommateur doit etre PLUS FRAIS que son producteur.
    Les deux peuvent etre dans leur fenetre et le resultat etre faux quand meme."""
    out = []
    for e in manifeste:
        cle = f"{e['depot']}/{e['fichier']}"
        for prod in e.get("depend_de") or []:
            a, b = constats.get(cle), constats.get(prod)
            if not a or not b or a.vu_le is None or b.vu_le is None:
                continue
            if a.vu_le < b.vu_le:
                out.append((cle, prod, b.vu_le - a.vu_le))
    return out


def rapport(constats: dict, manifeste: list, non_validees: int) -> tuple[str, bool]:
    """Rend (message, y_a_t_il_un_probleme). ⭐ Le message existe TOUJOURS."""
    en_retard = [c for c in constats.values() if c.en_retard]
    jamais    = [c for c in constats.values() if c.vu_le is None and not c.aveugle]
    aveugles  = [c for c in constats.values() if c.aveugle]
    illisibles = [(c.cle, x) for c in constats.values() for x in c.illisibles]
    hors = {c.cle for c in constats.values() if c.hors_portee}
    ordre = desordres(constats, manifeste)
    faibles = sum(1 for c in constats.values() if c.preuve == "run")

    alarme = bool(en_retard or jamais or ordre or aveugles)
    L = []

    if not alarme:
        L.append(f"🟢 **Sentinelle — RAS.** {len(constats)} workflows surveilles, "
                 f"tous ont donne signe de vie dans leur fenetre.")
    else:
        L.append(f"🔴 **Sentinelle — {len(en_retard) + len(jamais) + len(ordre) + len(aveugles)} "
                 f"point(s) a voir** sur {len(constats)} workflows.")

    for c in sorted(en_retard, key=lambda c: (not c.critique, -(c.age_h or 0))):
        L.append(f"{'🔥' if c.critique else '🟠'} `{c.cle}` — rien depuis "
                 f"**{c.age_h:.0f} h** (fenetre {c.fenetre_h:.0f} h, preuve : {c.preuve})")
    for c in jamais:
        L.append(f"{'🔥' if c.critique else '🟠'} `{c.cle}` — **aucun run reussi**, jamais.")
    for cle, prod, ecart in ordre:
        L.append(f"🔥 `{cle}` a ete vu **{ecart.total_seconds()/3600:.0f} h AVANT** son "
                 f"producteur `{prod}` : il a donc travaille sur du perime, "
                 f"**avec un run vert**.")
    # ⭐⭐⭐ ON REGROUPE L'AVEUGLEMENT. Un jeton qui expire rend 401 sur les 25
    # lignes d'un coup : les lister une par une noierait le canal sous 25
    # messages identiques, et la vraie panne du lendemain passerait dedans.
    # Vingt-cinq symptomes d'une seule cause sont UNE ligne, pas vingt-cinq.
    motifs = {}
    for c in aveugles:
        motifs.setdefault(c.aveugle, []).append(c)
    for motif, lot in motifs.items():
        if len(lot) > 3:
            depots = sorted({c.depot for c in lot})
            L.append(f"⚫ **Rien pu lire sur {len(lot)} workflows** ({', '.join(depots)}) "
                     f"— {motif}. ⛔ Ce n'est pas {len(lot)} pannes : "
                     f"c'est UNE cause, probablement le jeton ou sa portee.")
        else:
            for c in lot:
                L.append(f"⚫ `{c.cle}` — **je n'ai rien pu lire** ({motif}). "
                         f"⛔ Ce n'est pas « il n'a pas tourne ».")

    # ⭐⭐⭐ CE QU'ELLE NE SAIT PAS, ELLE LE DIT — tous les jours, RAS ou pas.
    coda = []
    if non_validees:
        coda.append(f"{non_validees} fenetre(s) jamais validee(s)")
    if faibles:
        coda.append(f"{faibles} surveille(s) sur le run seul (`success()` dit "
                    f"« fini », pas « avance »)")
    if hors:
        coda.append(f"{len(hors)} workflow(s) ecrivent dans le Sheet ou Discord, "
                    f"**que l'API GitHub ne voit pas** — leur ecriture n'est pas verifiee")
    if illisibles:
        coda.append(f"{len(illisibles)} cible(s) d'ecriture illisible(s) A CORRIGER "
                    "dans le manifeste : "
                    + ", ".join(f"`{k}` -> `{v}`" for k, v in illisibles[:3]))
    if coda:
        L.append("_Angles morts connus : " + " · ".join(coda) + "._")

    return "\n".join(L), alarme


# ─────────────────────────────────────────────────────────────────────────────
def poster(msg: str, hook: str) -> None:
    if not hook:
        print("⚠️ DISCORD_ALERTE_TECH_WEBHOOK absent — rien n'est poste.")
        return
    for bloc in [msg[i:i + 1900] for i in range(0, len(msg), 1900)]:
        req = urllib.request.Request(
            hook, data=json.dumps({"content": bloc}).encode(),
            headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=20).read()
        except Exception as e:
            print(f"⚠️ Envoi Discord en echec : {e}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Sentinelle d'absence des workflows")
    p.add_argument("--manifeste", default="data/manifeste_sentinelles.yml")
    p.add_argument("--a-blanc", action="store_true",
                   help="calcule et affiche, ne poste rien")
    a = p.parse_args(argv)

    manifeste = yaml.safe_load(open(a.manifeste, encoding="utf-8"))["workflows"]
    surveilles = [e for e in manifeste
                  if e.get("cadence") != "manuel" and e.get("fenetre_h")]
    non_validees = sum(1 for e in surveilles if e.get("valide_fenetre") is False)

    jeton = os.environ.get("SENTINELLE_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    if not jeton:
        # ⛔ Pas de sortie silencieuse : sans jeton elle est aveugle sur TOUT,
        #    et c'est exactement ce qu'il faut crier.
        msg = ("⚫ **Sentinelle aveugle** : aucun `SENTINELLE_TOKEN`. "
               "Elle n'a rien pu lire — ⛔ ne pas confondre avec « tout va bien ».")
        print(msg)
        if not a.a_blanc:
            poster(msg, os.environ.get("DISCORD_ALERTE_TECH_WEBHOOK", ""))
        return 1

    src = Source(jeton)
    constats = {}
    for e in surveilles:
        c = ausculter(e, src)
        constats[c.cle] = c

    msg, alarme = rapport(constats, manifeste, non_validees)
    print(msg)
    if not a.a_blanc:
        poster(msg, os.environ.get("DISCORD_ALERTE_TECH_WEBHOOK", ""))
    # ⭐ On sort 0 meme en alarme : une alerte n'est pas un echec de la
    #   sentinelle, et un run rouge ici ferait croire que c'est ELLE qui casse.
    return 0


if __name__ == "__main__":
    sys.exit(main())
