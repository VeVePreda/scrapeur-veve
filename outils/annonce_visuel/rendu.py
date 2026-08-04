# -*- coding: utf-8 -*-
# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : outils/annonce_visuel/rendu.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""🖼️ L'AFFICHE « RETOUR SUR <MOIS> » — la composition.

Preda fabrique ce visuel a la main chaque mois. On ne refait PAS son decor : il
fournit le **fond vide** (globe, drapeau, bandeaux « VEVE FRANCE PRESENTE » /
« VEVE FRANCE » / « Rejoins-nous », disclaimer) en PNG, et ce module pose
dessus ce qui change tous les mois :

    le mois · la piece n°1 · la carte du comic · les 5 tuiles

⭐⭐⭐ ON NE RECREE PAS UN DECOR QU'ON PEUT RECEVOIR. Refaire son globe en SVG
aurait donne « presque » son visuel — et « presque » est la pire des reponses
pour une identite de marque. Il garde la main sur le design, on prend la
composition.

⚠️ POURQUOI PILLOW ET PAS cairosvg (comme le calendrier)
--------------------------------------------------------
Le calendrier DESSINE (des cases, du texte, des traits) : le SVG y est chez
lui. Ici on COLLE des photos sur une photo. Pillow fait ca nativement, sans
passer par un encodage base64 dans un SVG ni par la lib systeme cairo — une
dependance systeme en moins sur le runner.

⚠️ CE QUI EST EMPRUNTE, PAS RECOPIE
------------------------------------
`outils.calendrier.visuels` porte deja le telechargement, le **cache disque**,
le **webp -> PNG** (VeVe sert du webp) et les recadrages. Trois lecons deja
payees. On l'appelle.

⭐⭐ LE MODE GRILLE. Mes zones sont mesurees sur une CAPTURE, pas sur le fichier
source de Preda : elles sont approximatives par construction. `grille()` dessine
les zones numerotees sur le fond — on regarde, on corrige `data/annonce_gabarit.json`,
et on recommence. **Un alignement se verifie en superposant, pas en relisant des
coordonnees.**

    python3 -m outils.annonce_visuel.rendu --grille --fond fond.png
    python3 -m outils.annonce_visuel.rendu --demo --fond fond.png
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Sequence

from PIL import Image, ImageDraw, ImageFont

from outils.annonce_visuel import gabarit as G

try:                                     # le cache/telechargement du calendrier
    from outils.calendrier import visuels as V
except Exception:                                           # noqa: BLE001
    V = None                             # rendu hors ligne : tout tombe en repli

# Le fond fourni par Preda. Absent = pas d'affiche (et on le DIT).
FOND_DEFAUT = os.path.join("outils", "annonce_visuel", "fond",
                           "retour-sur-vevefrance.png")


def chemin_fond() -> str:
    return os.environ.get("ANNONCE_VISUEL_FOND", FOND_DEFAUT)


class Journal:
    """Ce qui s'est passe, pour que le run le DISE a la fin.
    ⭐ Une case grise qui ne se signale pas est un visuel faux qu'on publie."""

    def __init__(self) -> None:
        self.posees = 0
        self.manquantes: List[str] = []

    def resume(self) -> str:
        txt = f"visuel : {self.posees} image(s) posee(s)"
        if self.manquantes:
            txt += f", {len(self.manquantes)} case(s) en repli :"
            for m in self.manquantes:
                txt += f"\n    ⚠️ {m}"
        return txt


# ---------------------------------------------------------------------------
# Les images
# ---------------------------------------------------------------------------

def _charger(url: str) -> Optional[Image.Image]:
    """Une image, par son URL (cache du calendrier) OU par un chemin local.

    ⭐ LE CHEMIN LOCAL N'EST PAS UNE COMMODITE DE TEST : la banniere VeVe du
    mois, Preda peut vouloir la deposer en fichier plutot que la pointer — et
    une image posee dans le depot ne perime pas, contrairement a une URL.

    ⚠️ NE LEVE JAMAIS : une image manquante est un incident de rendu, pas un
    echec de run. Meme doctrine que le calendrier — mieux vaut une affiche avec
    une case sombre qu'aucune affiche."""
    if not url:
        return None
    if not url.lower().startswith(("http://", "https://")):
        try:
            return Image.open(url).convert("RGBA")
        except Exception:                                   # noqa: BLE001
            return None
    if V is None:
        return None
    try:
        return V.charger(url)
    except Exception:                                       # noqa: BLE001
        return None


# 🔴 LE CACHE DU CALENDRIER PLAFONNE LES IMAGES A 480 px (`visuels.COTE_CACHE`).
# C'est le bon choix pour une vignette de calendrier ; c'est desastreux pour la
# BANNIERE, qui occupe 1 920 px de large : elle etait telechargee en 3 080,
# reduite a 480, puis re-agrandie a 1 920. Resultat : une bouillie.
# ⭐⭐ REUTILISER UN OUTIL, C'EST AUSSI HERITER DE SES COMPROMIS. Celui-ci a ete
# calibre pour un autre usage — on ne le change pas (le calendrier en depend),
# on lui met un frere pour le seul cas ou son plafond gene.
CACHE_GRAND = os.path.join("data", "annonce_bannieres_cache")


def _charger_grand(url: str) -> Optional[Image.Image]:
    """Une image SANS plafond de taille, avec son propre cache disque."""
    if not url:
        return None
    if not url.lower().startswith(("http://", "https://")):
        try:
            return Image.open(url).convert("RGBA")
        except Exception:                                   # noqa: BLE001
            return None
    import hashlib
    import urllib.request
    os.makedirs(CACHE_GRAND, exist_ok=True)
    chemin = os.path.join(CACHE_GRAND,
                          hashlib.sha1(url.encode()).hexdigest() + ".png")
    if os.path.exists(chemin):
        try:
            return Image.open(chemin).convert("RGBA")
        except Exception:                                   # noqa: BLE001
            os.remove(chemin)
    try:
        ua = getattr(V, "UA", "Mozilla/5.0 ScrapeurVeVe-annonce/1.0")
        req = urllib.request.Request(url, headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=30) as rep:
            brut = rep.read()
        import io
        img = Image.open(io.BytesIO(brut)).convert("RGBA")
        img.save(chemin, "PNG")            # ⚠️ webp -> PNG, comme le calendrier
        return img
    except Exception as e:                                  # noqa: BLE001
        print(f"⚠️ visuel : banniere indisponible ({e}).", file=sys.stderr)
        return None


def _coins_arrondis(image: Image.Image, rayon: int) -> Image.Image:
    """Le masque arrondi des tuiles. Sans lui, une vignette carree posee sur un
    fond aux cases arrondies saute aux yeux."""
    if rayon <= 0:
        return image
    masque = Image.new("L", image.size, 0)
    ImageDraw.Draw(masque).rounded_rectangle(
        (0, 0, image.width - 1, image.height - 1), radius=rayon, fill=255)
    out = image.copy()
    out.putalpha(masque)
    return out


def _poser_tuile(cadre: Image.Image, zone, url: str, rayon: int,
                 journal: Journal, nom: str, grand: bool = False) -> None:
    """Une case de la mosaique : l'image RECADREE pour remplir la case."""
    g, h, d, b = G.boite(zone, cadre.width, cadre.height)
    largeur, hauteur = d - g, b - h
    image = _charger_grand(url) if grand else _charger(url)
    if image is None:
        # 🔴 DIRE L'URL, PAS SEULEMENT LE NOM DE LA CASE. Le run du 04/08 a
        # sorti « 3 case(s) en repli (banniere, comic, tuile_2) » alors que les
        # trois URL EXISTAIENT : c'est le TELECHARGEMENT qui a echoue, pas la
        # donnee qui manquait. ⭐⭐ « Pas d'URL » et « URL morte » sont deux
        # pannes opposees ; un journal qui les confond envoie chercher au
        # mauvais endroit.
        journal.manquantes.append(f"{nom}"
                                  + (f" <{url[-58:]}>" if url else " (aucune URL)"))
        vignette = Image.new("RGBA", (largeur, hauteur), G.REPLI)
    else:
        # « couvrir » : la case est pleine, l'image deborde et se centre.
        vignette = V.recadrer(image, largeur, hauteur)      # type: ignore
        journal.posees += 1
    cadre.alpha_composite(_coins_arrondis(vignette, rayon), (g, h))


def _poser_contenu(cadre: Image.Image, zone, url: str, journal: Journal,
                   nom: str) -> None:
    """Le heros et la couverture du comic : l'image ENTIERE, centree.

    ⚠️ « contenir », pas « couvrir » : recadrer une couverture de comic lui
    couperait le titre, et recadrer le heros lui couperait la tete. Une piece
    mise en avant se montre en entier ou pas du tout."""
    g, h, d, b = G.boite(zone, cadre.width, cadre.height)
    largeur, hauteur = d - g, b - h
    image = _charger(url)
    if image is None:
        journal.manquantes.append(f"{nom}"
                                  + (f" <{url[-58:]}>" if url else " (aucune URL)"))
        return                            # rien : le fond reste visible
    petite = V.tenir_dans(image, largeur, hauteur)          # type: ignore
    journal.posees += 1
    cadre.alpha_composite(petite, (g + (largeur - petite.width) // 2,
                                   h + (hauteur - petite.height) // 2))


# ---------------------------------------------------------------------------
# Le texte
# ---------------------------------------------------------------------------

def _police(taille: int, chemin: str = "") -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(chemin or G.ttf(), taille)
    except Exception:                                       # noqa: BLE001
        return ImageFont.load_default()


def _largeur(dessin: ImageDraw.ImageDraw, texte: str, police) -> int:
    g, h, d, b = dessin.textbbox((0, 0), texte, font=police)
    return d - g


def _taille_qui_rentre(dessin, texte: str, largeur: int, depart: int,
                       mini: int = 8, ttf: str = "") -> ImageFont.FreeTypeFont:
    """La plus grande taille qui tient dans la largeur.

    ⭐ UN TEXTE QUI DEBORDE NE LEVE AUCUNE ERREUR : il sort du cadre, et on ne
    le voit qu'une fois le visuel publie. « Amazing Fantasy #15 (1962) » et
    « Hulk #1 » n'ont pas la meme longueur — c'est le texte qui s'adapte."""
    taille = depart
    while taille > mini:
        police = _police(taille, ttf)
        if _largeur(dessin, texte, police) <= largeur:
            return police
        taille -= 1
    return _police(mini, ttf)


def _logo(cadre: Image.Image, zone) -> None:
    """Le coeur VeVe France en filigrane — SEULEMENT s'il est demande.

    ⭐ Le decor de Preda le porte deja : le reposer par defaut donnerait un
    logo en double. Ca ne se voit pas dans le code, ca se voit sur le visuel
    publie."""
    chemin = G.logo()
    if not chemin or not os.path.exists(chemin):
        if chemin:
            print(f"⚠️ visuel : logo introuvable ({chemin}) — filigrane ignore.",
                  flush=True)
        return
    g, h, d, b = G.boite(zone, cadre.width, cadre.height)
    image = Image.open(chemin).convert("RGBA")
    image.thumbnail((d - g, b - h), Image.LANCZOS)
    alpha = image.getchannel("A").point(
        lambda v: v * max(0, min(255, G.LOGO_OPACITE)) // 255)
    image.putalpha(alpha)
    cadre.alpha_composite(image, (g + (d - g - image.width) // 2,
                                  h + (b - h - image.height) // 2))


def _chasse(dessin, texte: str, police, ecart: int) -> int:
    """La largeur d'un texte dessine lettre par lettre avec un interlettrage."""
    if not texte:
        return 0
    return sum(_largeur(dessin, c, police) for c in texte) + ecart * (len(texte) - 1)


def _ecrire_espace(dessin, xy, texte: str, police, ecart: int, **kw) -> int:
    """Ecrit lettre par lettre pour obtenir un interlettrage. Rend la largeur.

    ⚠️ Pillow ne sait PAS espacer les lettres : `text()` colle la chaine telle
    que la police la chasse. Le large tracking de Preda ne s'obtient qu'en
    posant chaque glyphe."""
    x, y = xy
    for c in texte:
        dessin.text((x, y), c, font=police, **kw)
        x += _largeur(dessin, c, police) + ecart
    return int(x - xy[0] - (ecart if texte else 0))


def _voile(cadre: Image.Image, zone) -> None:
    """Un voile sombre en degrade sous le titre.

    🔴 POURQUOI IL EXISTE — decouvert en rendant l'affiche pour de vrai avec une
    banniere CLAIRE : **le coeur du decor de Preda est SEMI-TRANSPARENT**. Son
    visuel de mai tenait parce que sa banniere etait sombre (l'espace) ; avec
    une banniere claire, le titre tricolore et le disclaimer deviennent
    illisibles. Ce n'est pas un bug du code, c'est une propriete du decor — mais
    un module qui publie tout seul ne peut pas dependre du hasard de la
    banniere du mois.
    ⭐ **Un rendu qui ne marche que sur l'exemple qui a servi a le concevoir
    n'est pas fini.** Reglable : `ANNONCE_VISUEL_VOILE=0` le supprime."""
    force = G.voile()
    if force <= 0:
        return
    g, h, d, b = G.boite(zone, cadre.width, cadre.height)
    # On deborde largement autour du titre : le degrade doit mourir en douceur.
    g, h = 0, 0
    d = min(cadre.width, round(d * 1.35))
    b = min(cadre.height, round(cadre.height * 0.47))
    masque = Image.new("L", (d - g, b - h), 0)
    px = masque.load()
    for x in range(masque.width):
        # opaque a gauche, transparent a droite : le titre est a gauche.
        v = int(force * max(0.0, 1.0 - (x / masque.width) ** 1.4))
        for y in range(masque.height):
            px[x, y] = v
    voile = Image.new("RGBA", masque.size, (4, 6, 12, 255))
    voile.putalpha(masque)
    cadre.alpha_composite(voile, (g, h))


def _titre(cadre: Image.Image, zone, mois: str) -> None:
    """« RET·OUR·SUR » tricolore / un filet / le mois EN CONTOUR.

    ⭐⭐ TROIS DETAILS RELEVES SUR SON VISUEL, et ce sont eux qui font « son »
    titre bien plus que la police :
      1. le titre porte le DRAPEAU (bleu / blanc / rouge), il n'est pas blanc ;
      2. le mois est en CONTOUR, pas en plein ;
      3. il est LARGEMENT interlettre.
    ⚠️ La police, elle, reste la sienne a fournir : sans son `.ttf`, on tombe
    sur celle du depot — propre, mais pas la meme."""
    g, h, d, b = G.boite(zone, cadre.width, cadre.height)
    largeur, hauteur = d - g, b - h
    dessin = ImageDraw.Draw(cadre)

    # ── « RETOUR SUR », en trois morceaux colores ──────────────────────────
    p_haut = _taille_qui_rentre(dessin, "RETOUR SUR", largeur,
                                round(hauteur * 0.40))
    espace = round(p_haut.size * G.TITRE_ESPACE)
    total = sum(_largeur(dessin, m, p_haut) for m, _ in G.TITRE_HAUT) + espace
    x = g + (largeur - total) // 2
    for i, (morceau, couleur) in enumerate(G.TITRE_HAUT):
        if i == 2:                       # l'espace avant « SUR »
            x += espace
        dessin.text((x, h), morceau, font=p_haut, fill=couleur)
        x += _largeur(dessin, morceau, p_haut)

    # ── le filet ───────────────────────────────────────────────────────────
    y = h + round(hauteur * 0.46)
    dessin.line((g, y, d, y), fill=G.BLANC, width=max(1, round(hauteur * 0.018)))

    # ── le mois, EN CONTOUR et interlettre ─────────────────────────────────
    bas = (mois or "").upper()
    fonte = G.ttf_mois()
    y += round(hauteur * 0.10)
    taille = round(hauteur * 0.36)
    while taille > 8:
        p_bas = _police(taille, fonte)
        ecart = round(taille * G.MOIS_CHASSE)
        if _chasse(dessin, bas, p_bas, ecart) <= largeur:
            break
        taille -= 1
    p_bas = _police(taille, fonte)
    ecart = round(taille * G.MOIS_CHASSE)
    x = g + (largeur - _chasse(dessin, bas, p_bas, ecart)) // 2
    if G.mois_deja_ajoure():
        # ⭐ La fonte EST ajouree : on la remplit en blanc. Lui ajouter un
        # contour ferait un DOUBLE trait — le defaut typique de qui empile un
        # effet sur un dessin qui le porte deja.
        # ⚠️ AUCUN CONTOUR ICI, MEME POUR LA LISIBILITE : le glyphe d'une fonte
        # ajouree est un ANNEAU, et le stroker BOUCHE SON TROU. On veut voir le
        # fond a travers les lettres — c'est tout l'interet de la fonte.
        halo = max(0, round(taille * G.MOIS_HALO))
        if halo:
            _ecrire_espace(dessin, (x, y), bas, p_bas, ecart,
                           fill=(255, 255, 255, 0), stroke_width=halo,
                           stroke_fill=(6, 8, 14, 190))
        gras = max(0, round(taille * G.MOIS_GRAS))
        _ecrire_espace(dessin, (x, y), bas, p_bas, ecart, fill=G.BLANC,
                       stroke_width=gras, stroke_fill=G.BLANC)
    else:
        # Repli : fonte pleine + contour simule (jambages plus epais).
        _ecrire_espace(dessin, (x, y), bas, p_bas, ecart,
                       fill=(255, 255, 255, 0),
                       stroke_width=max(1, round(taille * G.MOIS_TRAIT)),
                       stroke_fill=G.BLANC)


def lignes_carte(carte: Dict[str, Any]) -> List[str]:
    """Les lignes de la carte du comic, dans l'ordre de Preda.

    ⭐ « -/- » N'EST PAS UN BUG, C'EST SA CONVENTION : son visuel de mai porte
    « FIRST APPARENCE -/- ». Une donnee absente s'ecrit, elle ne se cache pas —
    sinon la carte change de forme d'un mois a l'autre sans qu'on sache
    pourquoi."""
    vide = "-/-"

    def dit(v) -> str:
        s = str(v).strip() if v not in (None, "") else ""
        return s or vide

    def nombre(v) -> str:
        try:
            return f"{int(float(str(v).replace(' ', '').replace(',', '.'))):,}" \
                .replace(",", " ")
        except (TypeError, ValueError):
            return vide

    return [
        dit(carte.get("nom")).upper(),
        f"DISPO DEPUIS LE {dit(carte.get('dispo'))}",
        f"COMICS DE {dit(carte.get('annee'))}",
        f"ESTIMATION IRL {nombre(carte.get('estimation'))}",
        f"FIRST APPARENCE {dit(carte.get('premiere_app'))}",
        f"SUPPLY {nombre(carte.get('supply'))}",
    ]


def _carte(cadre: Image.Image, zone, carte: Dict[str, Any]) -> None:
    g, h, d, b = G.boite(zone, cadre.width, cadre.height)
    largeur, hauteur = d - g, b - h
    dessin = ImageDraw.Draw(cadre)
    lignes = lignes_carte(carte)

    # ⚠️ RETRECI (Preda, 04/08) : le texte affleurait le cadre de la carte.
    # ⭐ Un texte qui touche son cadre a l'air d'un debordement meme quand il
    # est dedans — la marge fait partie du dessin, pas du confort.
    interligne = hauteur / (len(lignes) + 1.4)
    depart = max(10, round(interligne * 0.56))
    y = h
    for i, texte in enumerate(lignes):
        # 0.90 : on laisse une marge laterale au lieu de remplir la zone.
        police = _taille_qui_rentre(dessin, texte, round(largeur * 0.90),
                                    depart + (3 if i == 0 else 0),
                                    ttf=G.ttf_carte())
        x = g + (largeur - _largeur(dessin, texte, police)) // 2
        dessin.text((x, round(y)), texte, font=police, fill=G.BLANC)
        if i == 0:                       # le titre est SOULIGNE, comme chez lui
            base = round(y + police.size * 1.12)
            l_titre = _largeur(dessin, texte, police)
            dessin.line((x, base, x + l_titre, base), fill=G.BLANC, width=2)
            y += interligne * 1.35
        else:
            y += interligne


# ---------------------------------------------------------------------------
# L'affiche
# ---------------------------------------------------------------------------

def _fond(chemin: str = "") -> Image.Image:
    """Le fond de Preda. ABSENT = on ne bricole pas un decor de remplacement :
    on leve, et l'appelant decide de publier sans illustration.
    ⭐ Une affiche « presque » a sa charte est pire qu'une absence d'affiche."""
    chemin = chemin or chemin_fond()
    if not os.path.exists(chemin):
        raise FileNotFoundError(
            f"fond introuvable : {chemin} — depose l'export 1920x1080 de "
            f"Preda (decor SEUL, sans texte ni visuels) ou pose "
            f"ANNONCE_VISUEL_FOND.")
    return Image.open(chemin).convert("RGBA")


def composer(mois: str, banniere_url: str, tuiles_urls: Sequence[str],
             carte: Dict[str, Any], sortie: str,
             fond: str = "") -> str:
    """Fabrique l'affiche du mois et rend le chemin du PNG ecrit.

    ⭐⭐ L'ORDRE DES COUCHES EST LE COEUR DE CETTE FONCTION :

        1. un aplat sombre        (pour qu'un trou sans banniere reste propre)
        2. LA BANNIERE VeVe       <- elle passe SOUS le decor
        3. LE DECOR de Preda      <- il MASQUE : ses parties opaques cachent la
                                     banniere, son trou transparent la revele
        4. le titre, la carte, les tuiles

    Le decor n'est donc pas un fond, c'est un **calque de premier plan troue**.
    Le comprendre a l'envers donnerait une banniere posee par-dessus le cadre,
    qui recouvrirait le coeur et la barre « VEVE FRANCE »."""
    decor = _fond(fond)
    z = G.zones()
    journal = Journal()
    rayon = max(2, round(G.RAYON_TUILE * decor.width))

    cadre = Image.new("RGBA", decor.size, G.REPLI)
    # `grand=True` : la banniere echappe au plafond de 480 px du calendrier.
    _poser_tuile(cadre, z["banniere"], banniere_url, 0, journal, "banniere",
                 grand=True)
    cadre.alpha_composite(decor)         # le decor recouvre, son trou revele

    _logo(cadre, z["logo"])              # muet par defaut : le fond le porte
    _voile(cadre, z["titre"])            # le coeur du decor est semi-transparent
    _titre(cadre, z["titre"], mois)
    if carte.get("image"):
        _poser_contenu(cadre, z["comic_couverture"], carte["image"], journal,
                       "comic")
    if carte:
        _carte(cadre, z["comic_texte"], carte)

    for nom, url in zip(G.TUILES, list(tuiles_urls) + [""] * len(G.TUILES)):
        _poser_tuile(cadre, z[nom], url, rayon, journal, nom)

    os.makedirs(os.path.dirname(sortie) or ".", exist_ok=True)
    cadre.convert("RGB").save(sortie, "PNG", optimize=True)
    print(journal.resume(), flush=True)
    return sortie


def grille(sortie: str, fond: str = "") -> str:
    """LE MODE DE CONTROLE : les zones dessinees sur le fond, numerotees.

    ⭐ C'est l'outil qui remplace « je crois que c'est bien aligne ». Preda
    regarde une image, corrige `data/annonce_gabarit.json`, relance. Aucune de
    mes coordonnees mesurees a la capture n'a besoin d'etre juste du premier
    coup — elles ont juste besoin d'etre VERIFIABLES."""
    cadre = _fond(fond)
    dessin = ImageDraw.Draw(cadre, "RGBA")
    police = _police(max(12, round(cadre.height * 0.022)))
    for nom, zone in sorted(G.zones().items()):
        g, h, d, b = G.boite(zone, cadre.width, cadre.height)
        dessin.rectangle((g, h, d, b), outline=(255, 64, 96, 255), width=3)
        dessin.rectangle((g, h, min(d, g + 260), h + 34), fill=(255, 64, 96, 200))
        dessin.text((g + 6, h + 4), nom, font=police, fill=(255, 255, 255, 255))
    os.makedirs(os.path.dirname(sortie) or ".", exist_ok=True)
    cadre.convert("RGB").save(sortie, "PNG", optimize=True)
    print(f"grille de controle : {sortie} — corrige "
          f"{G.CHEMIN_SURCHARGE} et relance.", flush=True)
    return sortie


if __name__ == "__main__":                                  # pragma: no cover
    import argparse

    ap = argparse.ArgumentParser(description="L'affiche « RETOUR SUR <MOIS> »")
    ap.add_argument("--fond", default="", help="le PNG du decor")
    ap.add_argument("--sortie", default="", help="le PNG a ecrire")
    ap.add_argument("--mois", default="MAI")
    ap.add_argument("--grille", action="store_true",
                    help="dessine les zones sur le fond (controle)")
    ap.add_argument("--banniere", default="", help="l'URL de la banniere VeVe")
    a = ap.parse_args()

    if a.grille:
        grille(a.sortie or "annonce-grille.png", a.fond)
    else:
        composer(a.mois, a.banniere, [], {},
                 a.sortie or "annonce-visuel.png", a.fond)
