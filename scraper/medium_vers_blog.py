"""
Verse l'archive Medium dans l'onglet 📝C-BLOG, aux côtés des articles veve.me.

POURQUOI
--------
`blog.py` couvre veve.me (2023 →). L'archive Medium couvre 2020 → avril 2023.
Réunies dans le même onglet, elles donnent **la chronologie complète du blog de
VeVe**, sans trou. Les deux sources ne se recouvrent pas.

⛔ CE MODULE N'ÉCRIT RIEN DE LUI-MÊME. Il prépare des lignes au format de
`blog.py` et appelle **son** `sync_blog()` : même upsert par `slug`, même
garde-fou « 0 article n'écrase rien », même tri. Réécrire un second chemin
d'écriture vers le même onglet, c'est se garantir deux comportements différents
le jour où l'un des deux change.

LES TROIS PRÉCAUTIONS (chacune répond à un risque mesuré)
---------------------------------------------------------
1. ⭐ **`slug` préfixé `medium-`.** Une collision de slug entre les deux sources
   ne ferait pas un doublon : elle ferait **fusionner deux articles différents en
   une seule ligne**, en silence. Le préfixe rend la collision impossible, et il
   se repère à l'œil dans l'onglet. `category` = `Medium` pour filtrer.
2. ⭐ **Le chrome de Medium est retiré.** 327 des 471 textes commencent par
   « VeVe Digital Collectibles / Follow / Aug 29 · 8 min read ». Sans ça on
   verse de l'habillage d'interface dans une colonne de contenu.
3. ⭐ **`--apercu` par défaut** : le module DIT ce qu'il ferait (combien de
   lignes, quelles collisions) et n'écrit qu'avec `MEDIUM_BLOG_ECRIRE=1`.

CE QUI A ÉTÉ VÉRIFIÉ AVANT D'ÉCRIRE CE MODULE
----------------------------------------------
- ✅ **Discord ne va pas déborder.** `discord_blog.py` ne poste que les articles
  parus dans les `DISCORD_BLOG_JOURS` (3) derniers jours, avec un plafond
  anti-avalanche. Les 471 articles de 2020-2023 sont hors de cette fenêtre : ils
  ne déclencheront **aucun** message. (C'est le filtre par date voulu par Preda
  qui nous sauve ici — les slugs seuls n'auraient pas suffi.)
- ✅ **Aucune troncature.** Le plus long article Medium fait 15 740 caractères,
  très loin des 45 000 auxquels `blog.py` coupe et des 50 000 d'une cellule.
- ✅ **Les lignes survivent au cron.** `sync_blog()` relit l'existant, fusionne,
  puis réécrit : les lignes Medium sont reprises à chaque run, jamais effacées.
- ⚠️ **Quota Sheets PARTAGÉ** : lancer ce module SEUL, jamais en même temps que
  le daily, une réparation ou une moisson.

ENV : SHEET_ID · GOOGLE_SERVICE_ACCOUNT_JSON · MEDIUM_BLOG_CORPUS
      (défaut data/medium_corpus.jsonl) · MEDIUM_BLOG_ECRIRE (1 = écrire)
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, List

from scraper import blog

CORPUS = os.environ.get("MEDIUM_BLOG_CORPUS", "data/medium_corpus.jsonl")
ECRIRE = os.environ.get("MEDIUM_BLOG_ECRIRE", "").strip() in ("1", "oui", "true")
PREFIXE = "medium-"
CATEGORIE = "Medium"

# Le bandeau que Medium colle en tête du corps. ⚠️ Il a des VARIANTES qu'il faut
# avoir vues pour les écrire : « VeVeFollow », « VeVe.Follow », « VeVe
# WriterFollow », « VeVe. », et la date et le temps de lecture tantôt sur deux
# lignes (« Feb 25 » puis « 2 min read »), tantôt sur une seule
# (« Oct 14 · 2 min read »). Une seule de ces formes oubliée = de l'habillage
# d'interface versé dans une colonne de contenu.
CHROME = re.compile(
    r"^[.·\s]*(?:"
    r"VeVe[\s.·]*(?:Digital\s*Collectibles|Writer)?[\s.·]*(?:Follow)?"
    r"|Follow|Share|Listen|Open in app|Sign\s?(?:in|up)|Published in .*"
    r"|\d+\s*min read"
    r"|Just now(?:\s*·\s*\d+\s*min read)?"
    r"|[A-Z][a-z]{2}\s+\d{1,2}(?:,\s*\d{4})?(?:\s*·\s*\d+\s*min read)?"
    r")[.·\s]*$", re.I)


def _nettoyer(texte: str, titre: str, auteur: str = "") -> str:
    """Ôte le bandeau d'interface en tête du corps.

    ⚠️ On ne s'ARRÊTE PAS à la première ligne non-chrome : sur certains articles
    le sous-titre passe AVANT le bandeau (« Citroën to release… » puis
    « VeVe.Follow »). On FILTRE donc les lignes de chrome sur la fenêtre de tête,
    au lieu de couper un préfixe. Au-delà de 15 lignes on ne touche plus à rien :
    le corps réel commence toujours bien avant.
    """
    lignes = texte.split("\n")
    t = (titre or "").strip().lower()
    # Le nom de la signature apparaît parfois seul (« Rhys »). On ne peut pas le
    # deviner par une forme : on le prend dans la fiche, nom entier ET prénom.
    sig = {p for p in ((auteur or "").strip().lower(),
                       (auteur or "").strip().lower().split(" ")[0]) if len(p) > 2}
    tete, garde = lignes[:15], []
    for l in tete:
        s = l.strip()
        if s and (CHROME.match(s) or (t and s.lower() == t) or s.lower() in sig):
            continue                       # chrome, titre répété, ou signature
        garde.append(l)
    return "\n".join(garde + lignes[15:]).strip()


def _temps_de_lecture(texte: str) -> str:
    m = re.search(r"(\d+)\s*min read", texte[:400], re.I)
    return "%s min" % m.group(1) if m else ""


def lignes_depuis_corpus(chemin: str) -> List[Dict[str, Any]]:
    if not os.path.exists(chemin):
        print("⛔ corpus introuvable : %s" % chemin, flush=True)
        return []
    out: List[Dict[str, Any]] = []
    with open(chemin, encoding="utf-8") as f:
        for ligne in f:
            ligne = ligne.strip()
            if not ligne:
                continue
            d = json.loads(ligne)
            titre = d.get("titre") or d.get("slug") or ""
            corps = _nettoyer(d.get("texte") or "", titre, d.get("auteur") or "")
            out.append({
                # ⭐ LE HASH FAIT PARTIE DE LA CLÉ, ce n'est pas de la décoration.
                # Mesuré : DEUX paires d'articles Medium partagent le même slug
                # (« the-rise-of-ultraman-series-1 » et
                # « cryptozoic-cryptkins-series-1 » ont chacun deux versions
                # publiées le même jour). Sans le hash, l'upsert par slug en
                # fusionnerait deux en un — et on ne le verrait jamais.
                # `medium-<slug>-<hash>` = exactement le chemin de l'URL source :
                # unique par construction, et stable d'un run à l'autre.
                "slug": PREFIXE + (d.get("slug") or "") + "-" + (d.get("hash") or ""),
                "date": (d.get("date_publication") or "")[:10],
                "title": titre,
                "category": CATEGORIE,
                "tags": ", ".join(d.get("tags") or []),
                "author": d.get("auteur") or "VeVe",
                "reading_time": _temps_de_lecture(d.get("texte") or ""),
                "excerpt": d.get("resume") or "",
                "content": corps,
                "url": d.get("url") or "",
                "image_url": d.get("image") or "",
            })
    return out


def main() -> int:
    sid = os.environ.get("SHEET_ID", "").strip()
    articles = lignes_depuis_corpus(CORPUS)
    if not articles:
        print("⛔ 0 ligne préparée — on ne touche à rien.", flush=True)
        return 1

    vides = [a for a in articles if not a["content"]]
    n_car = sum(len(a["content"]) for a in articles)
    print("📝 %d articles Medium préparés · %d k caractères · plus long %d car."
          % (len(articles), n_car // 1000,
             max(len(a["content"]) for a in articles)), flush=True)
    print("   slug préfixé « %s » · category = « %s »" % (PREFIXE, CATEGORIE))
    if vides:
        print("   ⚠️ %d au corps VIDE après nettoyage : %s"
              % (len(vides), ", ".join(a["slug"] for a in vides[:5])))
    trop = [a for a in articles if len(a["content"]) > 45000]
    print("   au-dessus de la troncature de blog.py (45 000) : %d" % len(trop))

    if not sid:
        print("\n⛔ SHEET_ID absent : aperçu seul, rien n'est comparé au Sheet.")
        return 0

    # ⭐ Le contrôle qui compte : que dit DÉJÀ l'onglet ? Une collision de slug
    #    fusionnerait deux articles en une ligne — en silence.
    _sh, ws = blog._open(sid)
    existant = blog._read_existing(ws)
    nouveaux = [a for a in articles if a["slug"] not in existant]
    connus = [a for a in articles if a["slug"] in existant]
    sans_prefixe = {a["slug"][len(PREFIXE):] for a in articles} & set(existant)
    print("\n📊 onglet %s : %d lignes déjà présentes" % (blog.BLOG_TAB, len(existant)))
    print("   à AJOUTER : %d · déjà là (mise à jour) : %d" % (len(nouveaux), len(connus)))
    print("   collisions de slug SANS le préfixe : %d %s"
          % (len(sans_prefixe), sorted(sans_prefixe)[:5] if sans_prefixe else ""))
    if sans_prefixe:
        print("   ⭐ le préfixe évite bien une fusion silencieuse de %d articles."
              % len(sans_prefixe))

    if not ECRIRE:
        print("\n👀 APERÇU — rien n'a été écrit. Relancer avec écrire = oui.")
        return 0

    res = blog.sync_blog(articles, sid)
    print("\n✅ écrit : %s" % json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
