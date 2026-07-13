"""HABILLAGE de 📊 STATS — en Python, et PAR NOM DE COLONNE.

POURQUOI CE MODULE EXISTE (13/07)
  L'habillage vivait dans stats_format.gs (Apps Script), qui formatait PAR
  POSITION : 'A10:R46', pulse en 'T:AC', etc. Le jour ou j'ai insere la colonne
  💎 Gems en S et les deux colonnes OG dans le pulse, TOUT a glisse d'un cran :
  Gems $ s'affichait "15636,0%" et le NOMBRE d'OG "2898,0%".
  C'est la meme lecon que le bug des "1001 articles" du digest, sous une autre
  forme : NE JAMAIS FAIRE D'UNE POSITION LA SOURCE DE VERITE QUAND LE NOM DE LA
  COLONNE EXISTE. Ici, on lit l'en-tete et on en deduit le format. Ajouter,
  deplacer ou renommer une colonne ne peut plus rien casser.

  -> SUPPRIMER l'Apps Script stats_format.gs : il est desormais nuisible.
"""
from __future__ import annotations

from typing import Dict, List

# ── THEME CLAIR (Preda, 13/07 : "revenons aux couleurs d'origine, fond blanc")
# Le sombre est abandonne. Les 6 familles reprennent EXACTEMENT les teintes de
# l'ancien .gs : soutenue sur la ligne des GROUPES, delavee sur la ligne des
# EN-TETES. Texte gris fonce 2 sur les deux.
BLANC = {'red': 1.0, 'green': 1.0, 'blue': 1.0}
FOND = BLANC
FOND_ALT = {'red': 0.9607843137254902, 'green': 0.9294117647058824, 'blue': 0.984313725490196}      # zebrure : le lilas tres pale de l'ancien .gs
VIOLET = {'red': 0.4823529411764706, 'green': 0.17254901960784313, 'blue': 0.7490196078431373}
OR = {'red': 0.9607843137254902, 'green': 0.7019607843137254, 'blue': 0.00392156862745098}
GRIS_FONCE2 = {'red': 0.4, 'green': 0.4, 'blue': 0.4}   # le texte des groupes et des en-tetes
GRIS_TXT = {'red': 0.4, 'green': 0.4, 'blue': 0.4}
NOIR = {'red': 0.043137254901960784, 'green': 0.043137254901960784, 'blue': 0.043137254901960784}

# ligne 18 — GROUPES (teintes soutenues)
GROUPES = {
    "TRANSACTION": {'red': 0.8117647058823529, 'green': 0.8862745098039215, 'blue': 0.9529411764705882},
    "ACTIF": {'red': 0.8509803921568627, 'green': 0.9176470588235294, 'blue': 0.8274509803921568},
    "LISTING": {'red': 0.8509803921568627, 'green': 0.8235294117647058, 'blue': 0.9137254901960784},
    "REVENUE": {'red': 1.0, 'green': 0.9490196078431372, 'blue': 0.8},
    "OMI BURN": {'red': 0.9568627450980393, 'green': 0.8, 'blue': 0.8},
    "ACHAT": {'red': 0.8156862745098039, 'green': 0.8784313725490196, 'blue': 0.8901960784313725},
}
# ligne 19 — EN-TETES (les memes, delavees)
ENTETES = {
    "TRANSACTION": {'red': 0.8862745098039215, 'green': 0.9215686274509803, 'blue': 0.9529411764705882},
    "ACTIF": {'red': 0.9058823529411765, 'green': 0.9372549019607843, 'blue': 0.8941176470588236},
    "LISTING": {'red': 0.9058823529411765, 'green': 0.8901960784313725, 'blue': 0.9372549019607843},
    "REVENUE": {'red': 0.9725490196078431, 'green': 0.9529411764705882, 'blue': 0.8784313725490196},
    "OMI BURN": {'red': 0.9529411764705882, 'green': 0.8784313725490196, 'blue': 0.8784313725490196},
    "ACHAT": {'red': 0.8941176470588236, 'green': 0.9294117647058824, 'blue': 0.9372549019607843},
}
GRIS = {'red': 0.9529411764705882, 'green': 0.9529411764705882, 'blue': 0.9529411764705882}          # familles sans couleur (Date, Drop, pulse)


def _entete(fam: str) -> dict:
    return ENTETES.get(fam, GRIS)

# ── FORMATS PAR NOM ─────────────────────────────────────────────────────────
ARGENT = '#,##0" $"'
ARGENT_APPROX = '"~"#,##0" $"'      # valeur de remplacement, pas un prix paye
ENTIER = "#,##0"
POURCENT = '0.0"%"'
DECIMAL = "#,##0.00"

# noms EXACTS -> format (le reste est deduit)
FORMATS: Dict[str, str] = {
    "Total": ARGENT, "Drop": ARGENT, "Market": ARGENT,
    "Revenue drop": ARGENT, "💎 Gems $": ARGENT,
    "Global $": ARGENT_APPROX,
    "OMI→NFT": ENTIER, "OMI→GEM": ENTIER, "OMI brûlés": ENTIER,
    "Rétention %": POURCENT, "Churn %": POURCENT, "OG %": POURCENT,
    "Acc. nette moy": DECIMAL, "gini": "0.000",
    "Valeur store $": ARGENT, "Valeur floor $": ARGENT, "Critère": ENTIER,
}
# colonnes de TEXTE (jamais de format numerique, jamais centrees)
TEXTE = {"Date", "Mois", "Année", "Drop ", "Wallet", "Pseudo", "Score",
         "Activité", "Par QUANTITÉ", "source", "statut", "fraîcheur"}

# ⚠️ DEUX colonnes s'appellent "Drop" : le NOM du drop (colonne B, large) et le
# REVENUE du drop (groupe REVENUE, etroit). Une largeur par NOM seul les
# confondait — la cle est donc (FAMILLE|nom), et le nom seul en repli.
LARGEURS = {
    "|Drop": 230, "REVENUE|Drop": 95,          # les deux "Drop"
    "Date": 100, "Mois": 85, "Année": 75,
    "REVENUE|Total": 100, "REVENUE|Market": 100,
    "OMI BURN|Global $": 95, "OMI BURN|OMI→NFT": 105, "OMI BURN|OMI→GEM": 105,
    "ACHAT|Gems $": 95,
    "ACTIF|Nouveaux": 90, "ACTIF|Anciens": 85, "ACTIF|Unique": 85,
    "LISTING|Quantité": 90, "LISTING|Comptes": 95,
    "Wallet": 300, "Pseudo": 140, "Score": 140, "Activité": 95, "Rang": 55,
    "Critère": 100, "Exemplaires": 100, "Collectibles": 100,
    "Valeur store $": 110, "Valeur floor $": 110,
    "Acheteurs uniques": 115, "Vendeurs uniques": 115,
    "Minters uniques": 110, "Acc. nette moy": 105,
    "Rétention %": 95, "Churn %": 85, "OG 21-22": 90, "OG %": 75,
}
LARGEUR_DEFAUT = 88


def _largeur(famille: str, nom: str) -> int:
    return (LARGEURS.get(f"{famille}|{nom}")
            or LARGEURS.get(nom)
            or LARGEUR_DEFAUT)


def _fmt(nom: str) -> str:
    """Le format d'une colonne, deduit de son NOM."""
    n = (nom or "").strip()
    if not n or n in TEXTE:
        return ""
    if n in FORMATS:
        return FORMATS[n]
    if n.endswith("%") or n.startswith("%"):
        return POURCENT
    if "$" in n:
        return ARGENT
    return ENTIER


def _rng(sid: int, r1: int, r2: int, c1: int, c2: int) -> dict:
    """Plage 1-based inclusive -> range API (0-based, fin exclusive)."""
    return {"sheetId": sid, "startRowIndex": r1 - 1, "endRowIndex": r2,
            "startColumnIndex": c1 - 1, "endColumnIndex": c2}


def _cell(rng: dict, fmt: dict, champs: str) -> dict:
    return {"repeatCell": {"range": rng, "cell": {"userEnteredFormat": fmt},
                           "fields": champs}}


def _plages(groupes: List[str], col1: int):
    """[(famille, 1re colonne, derniere colonne)] — une famille COURT sur ses
    sous-colonnes jusqu'a la suivante."""
    out, fam, deb = [], "", 0
    for i, g in enumerate(groupes):
        if g:
            if fam:
                out.append((fam, deb, col1 + i - 1))
            fam, deb = g, col1 + i
    if fam:
        out.append((fam, deb, col1 + len(groupes) - 1))
    return out


def _familles(entetes: List[str], groupes: List[str]) -> List[str]:
    """La famille de CHAQUE colonne : la ligne de groupes ne porte le libelle
    que sur sa 1re colonne, il court jusqu'au groupe suivant."""
    out, courant = [], ""
    for i in range(len(entetes)):
        g = groupes[i] if groupes and i < len(groupes) else ""
        if g:
            courant = g
        out.append(courant)
    return out


def bloc(sid: int, entetes: List[str], ligne_entete: int, ligne1: int,
         ligne2: int, col1: int = 1, groupes: List[str] = None) -> List[dict]:
    """Habille un tableau : en-tetes, formats PAR NOM, largeurs, alignement.

    `entetes` peut contenir des "" (colonnes vides entre deux blocs) : elles
    sont simplement ignorees."""
    reqs: List[dict] = []
    n = len(entetes)
    # ligne des GROUPES : chaque famille est FUSIONNEE sur ses sous-colonnes,
    # son nom CENTRE et en MAJUSCULES (demande Preda 13/07 : "TRANSACTION" doit
    # faire toute la largeur de C18:G18, pas se tasser sur une seule case).
    if groupes:
        lg = ligne_entete - 1
        # les colonnes hors famille (Date, Drop) : un gris clair, pour que la
        # ligne des groupes soit CONTINUE (Preda : "c'est plus harmonieux")
        libres = [col1 + i for i, g in enumerate(_familles(entetes, groupes))
                  if not g]
        for c in libres:
            reqs.append(_cell(
                _rng(sid, lg, lg, c, c),
                {"backgroundColor": GRIS},
                "userEnteredFormat.backgroundColor"))
        for fam, c_deb, c_fin in _plages(groupes, col1):
            if c_fin > c_deb:
                reqs.append({"mergeCells": {
                    "range": _rng(sid, lg, lg, c_deb, c_fin),
                    "mergeType": "MERGE_ALL"}})
            reqs.append(_cell(
                _rng(sid, lg, lg, c_deb, c_fin),
                {"backgroundColor": GROUPES.get(fam, GRIS),
                 "textFormat": {"bold": True, "fontSize": 10,
                                "foregroundColor": GRIS_FONCE2},
                 "horizontalAlignment": "CENTER",
                 "verticalAlignment": "MIDDLE"},
                "userEnteredFormat(backgroundColor,textFormat,"
                "horizontalAlignment,verticalAlignment)"))
    # en-tetes : chacun prend la teinte PALE de sa famille
    familles = _familles(entetes, groupes)
    for i, nom in enumerate(entetes):
        c = col1 + i
        fam = familles[i]
        reqs.append(_cell(
            _rng(sid, ligne_entete, ligne_entete, c, c),
            {"backgroundColor": _entete(fam),
             "textFormat": {"bold": True, "fontSize": 9,
                            "foregroundColor": GRIS_FONCE2},
             "horizontalAlignment": "CENTER",
             "wrapStrategy": "WRAP",
             "verticalAlignment": "MIDDLE"},
            "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,"
            "wrapStrategy,verticalAlignment)"))
    if ligne2 < ligne1:
        return reqs
    # donnees : un format par colonne, deduit du NOM
    for i, nom in enumerate(entetes):
        c = col1 + i
        f = _fmt(nom)
        fam = familles[i]
        style = {"horizontalAlignment": "LEFT" if not f else "RIGHT",
                 "textFormat": {"fontSize": 9}}
        champs = "userEnteredFormat(horizontalAlignment,textFormat"
        if f:
            style["numberFormat"] = {"type": "NUMBER", "pattern": f}
            champs += ",numberFormat"
        champs += ")"
        reqs.append(_cell(_rng(sid, ligne1, ligne2, c, c), style, champs))
        # ⚠️ AUCUNE LARGEUR N'EST POSEE (Preda 13/07 : "ne touche pas aux
        # largeurs des colonnes, je vais les regler moi-meme"). Le module ne
        # touche QUE les couleurs, les formats et les fusions.
    # zebrure : lisible sans effort
    # zebrure : deux nuances de sombre, juste assez pour suivre une ligne
    reqs.append({"addBanding": {"bandedRange": {
        "range": _rng(sid, ligne1, ligne2, col1, col1 + n - 1),
        "rowProperties": {"firstBandColor": FOND,
                          "secondBandColor": FOND_ALT}}}})
    return reqs


def banniere(sid: int, ligne: int, c1: int, c2: int) -> List[dict]:
    """Un bandeau violet : texte BLANC, aligne a GAUCHE (Preda 13/07 — le titre
    d'un bandeau se lit au debut, pas au milieu)."""
    return [_cell(_rng(sid, ligne, ligne, c1, c2),
                  {"backgroundColor": VIOLET,
                   "textFormat": {"bold": True, "foregroundColor": BLANC,
                                  "fontSize": 10},
                   "horizontalAlignment": "LEFT",
                   "verticalAlignment": "MIDDLE"},
                  "userEnteredFormat(backgroundColor,textFormat,"
                  "horizontalAlignment,verticalAlignment)")]


def notes(sid: int, ligne: int, n: int, c2: int) -> List[dict]:
    """Les notes : une colonne LARGE, du texte qui respire, pas un mur."""
    return [
        {"mergeCells": {"range": _rng(sid, ligne, ligne, 1, c2),
                        "mergeType": "MERGE_ROWS"}},
    ] + banniere(sid, ligne, 1, c2) + [
        {"mergeCells": {"range": _rng(sid, ligne + 1, ligne + n, 1, c2),
                        "mergeType": "MERGE_ROWS"}},
        _cell(_rng(sid, ligne + 1, ligne + n, 1, c2),
              {"textFormat": {"fontSize": 9}, "wrapStrategy": "WRAP",
               "verticalAlignment": "MIDDLE"},
              "userEnteredFormat(textFormat,wrapStrategy,verticalAlignment)"),
    ]


def purger(sh, sid: int, depart: int) -> List[dict]:
    """Repart d'une page propre — MAIS SEULEMENT SOUS LA LIGNE `depart`.

    ⚠️ Les lignes 1 a depart-1 appartiennent a Preda : il y met son contenu.
    On n'y touche pas. Ni fusion defaite, ni bande supprimee, ni format ecrase.
    Sans purge sous cette limite, en revanche, chaque run empile ses zebrures
    et Google finit par refuser."""
    reqs: List[dict] = [{"unmergeCells": {"range": {
        "sheetId": sid, "startRowIndex": depart - 1}}}]
    try:
        meta = sh.fetch_sheet_metadata()
        for f in meta.get("sheets", []):
            if f.get("properties", {}).get("sheetId") != sid:
                continue
            for b in f.get("bandedRanges", []) or []:
                r = b.get("range", {})
                if r.get("startRowIndex", 0) < depart - 1:
                    continue                  # une bande de Preda : on la laisse
                reqs.append({"deleteBanding":
                             {"bandedRangeId": b["bandedRangeId"]}})
    except Exception:
        pass
    return reqs


def habiller(sh, ws, quotidien, n_jours, periode, n_mois, n_annees,
             vvf, whales, n_whales, ligne_notes, n_notes, ancres,
             bandeaux=None) -> int:
    """Habille la page SOUS la zone de Preda. Chaque bloc est decrit par SES
    EN-TETES : les formats suivent les noms, jamais les positions."""
    sid = ws.id
    L = len(quotidien)                      # 19 colonnes (A..S)
    depart = ancres["depart"]               # 14 : rien au-dessus
    entete = ancres["entete"]               # 19
    groupes = ["", "", "TRANSACTION", "", "", "", "", "ACTIF", "", "",
               "LISTING", "", "REVENUE", "", "", "OMI BURN", "", "", "ACHAT"]
    reqs = purger(sh, sid, depart)

    # bandeau semaine + KPI (plus de bandeau noir : les 13 lignes du haut sont
    # a Preda, et il ne veut pas de titre de ma part)
    reqs += banniere(sid, depart, 1, L)
    reqs.append({"mergeCells": {"range": _rng(sid, depart, depart, 1, L),
                                "mergeType": "MERGE_ROWS"}})
    reqs.append(_cell(_rng(sid, depart + 1, depart + 1, 1, 12),
                      {"textFormat": {"bold": True, "fontSize": 9,
                                      "foregroundColor": GRIS_TXT},
                       "horizontalAlignment": "CENTER", "wrapStrategy": "WRAP"},
                      "userEnteredFormat(textFormat,horizontalAlignment,"
                      "wrapStrategy)"))
    reqs.append(_cell(_rng(sid, depart + 2, depart + 2, 1, 12),
                      {"textFormat": {"bold": True, "fontSize": 12},
                       "horizontalAlignment": "CENTER"},
                      "userEnteredFormat(textFormat,horizontalAlignment)"))
    reqs.append(_cell(_rng(sid, depart + 2, depart + 2, 1, 1),
                      {"numberFormat": {"type": "NUMBER", "pattern": ARGENT}},
                      "userEnteredFormat.numberFormat"))

    # tableau QUOTIDIEN
    reqs += bloc(sid, quotidien, entete, entete + 1,
                 entete + max(1, n_jours), groupes=groupes)

    # 📅 PAR MOIS / PAR ANNEE + 📈 PULSE (memes en-tetes -> memes formats)
    for ancre, n in ((ancres["mois"], n_mois), (ancres["annee"], n_annees)):
        reqs += banniere(sid, ancre, 1, L)
        reqs += banniere(sid, ancre, 21, 20 + len(vvf))
        reqs += bloc(sid, periode, ancre + 2, ancre + 3,
                     ancre + 2 + max(1, n), groupes=groupes)
        reqs += bloc(sid, vvf, ancre + 2, ancre + 3, ancre + 2 + max(1, n),
                     col1=21)          # colonne T laissee VIDE (demande Preda)

    # Les bandeaux des MODULES de droite (💰 tailles · 🩺 sante · 🔥 burns ·
    # 🏪 univers). C'est l'Apps Script qui les posait — en le supprimant, la
    # 🩺 SANTE avait perdu le sien. Ils reviennent, en violet, texte blanc,
    # alignes a gauche comme les autres.
    for ligne, c1, c2 in (bandeaux or ()):
        reqs += banniere(sid, ligne, c1, c2)

    # ℹ️ NOTES : du texte qui respire, pas un mur
    reqs += notes(sid, ligne_notes, max(1, n_notes), L)

    # 🐋 CLASSEMENT WHALES : 3 blocs de 10 colonnes
    if n_whales:
        a = ancres["whales"]
        reqs += banniere(sid, a, 1, 32)
        for i in range(3):
            c1 = 1 + i * 11
            reqs.append(_cell(_rng(sid, a + 1, a + 1, c1, c1 + 9),
                              {"textFormat": {"bold": True, "fontSize": 10},
                               "horizontalAlignment": "CENTER"},
                              "userEnteredFormat(textFormat,"
                              "horizontalAlignment)"))
            reqs += bloc(sid, whales, a + 2, a + 3, a + 2 + n_whales, col1=c1)

    # AUCUN figeage (Preda n'en veut pas). NB : figer une COLONNE etait de
    # toute facon impossible — Google refuse de couper une cellule fusionnee
    # (le titre s'etend de A a S).
    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": sid,
                       "gridProperties": {"frozenRowCount": 0,
                                          "frozenColumnCount": 0}},
        "fields": "gridProperties(frozenRowCount,frozenColumnCount)"}})
    return _envoyer(sh, reqs)


def _envoyer(sh, reqs: List[dict], paquet: int = 60) -> int:
    """Envoie par PAQUETS, pas d'un bloc.

    Un batch_update est ATOMIQUE : une seule requete refusee et TOUT est perdu
    (leçon du 13/07 : un figeage de colonne invalide a annule 275 requetes
    d'habillage parfaitement valides). En paquets, un accident reste local —
    et on DIT lequel a echoue au lieu de perdre la page en silence."""
    ok = 0
    for i in range(0, len(reqs), paquet):
        tranche = reqs[i:i + paquet]
        try:
            sh.batch_update({"requests": tranche})
            ok += len(tranche)
        except Exception as e:
            print(f"    habillage : paquet {i // paquet + 1} refuse ({e}) — "
                  f"les autres passent quand meme.", flush=True)
    return ok
