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

NOIR = {"red": 0.043, "green": 0.043, "blue": 0.043}
OR = {"red": 0.96, "green": 0.70, "blue": 0.00}
VIOLET = {"red": 0.482, "green": 0.173, "blue": 0.749}
BLANC = {"red": 1, "green": 1, "blue": 1}
GRIS = {"red": 0.95, "green": 0.95, "blue": 0.96}
GRIS_TXT = {"red": 0.4, "green": 0.4, "blue": 0.4}
LILAS = {"red": 0.973, "green": 0.957, "blue": 0.988}

# Teintes de GROUPE (une famille = une couleur, du quotidien au mensuel)
GROUPES = {
    "TRANSACTION": {"red": 0.886, "green": 0.922, "blue": 0.953},
    "ACTIF": {"red": 0.906, "green": 0.937, "blue": 0.894},
    "LISTING": {"red": 0.906, "green": 0.890, "blue": 0.937},
    "REVENUE": {"red": 0.973, "green": 0.953, "blue": 0.878},
    "OMI BURN": {"red": 0.953, "green": 0.878, "blue": 0.878},
}

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

LARGEURS = {"Date": 90, "Mois": 80, "Année": 70, "Drop": 210, "Wallet": 300,
            "Pseudo": 130, "Score": 130, "Activité": 90, "Rang": 50}
LARGEUR_DEFAUT = 78


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


def bloc(sid: int, entetes: List[str], ligne_entete: int, ligne1: int,
         ligne2: int, col1: int = 1, groupes: List[str] = None) -> List[dict]:
    """Habille un tableau : en-tetes, formats PAR NOM, largeurs, alignement.

    `entetes` peut contenir des "" (colonnes vides entre deux blocs) : elles
    sont simplement ignorees."""
    reqs: List[dict] = []
    n = len(entetes)
    # ligne de groupes (couleur par famille)
    if groupes:
        for i, g in enumerate(groupes):
            if not g:
                continue
            c = col1 + i
            reqs.append(_cell(
                _rng(sid, ligne_entete - 1, ligne_entete - 1, c, c),
                {"backgroundColor": GROUPES.get(g, GRIS),
                 "textFormat": {"bold": True, "fontSize": 9},
                 "horizontalAlignment": "CENTER"},
                "userEnteredFormat(backgroundColor,textFormat,"
                "horizontalAlignment)"))
    # en-tetes
    reqs.append(_cell(
        _rng(sid, ligne_entete, ligne_entete, col1, col1 + n - 1),
        {"backgroundColor": GRIS,
         "textFormat": {"bold": True, "fontSize": 9},
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
        style = {"horizontalAlignment": "LEFT" if not f else "RIGHT",
                 "textFormat": {"fontSize": 9}}
        champs = "userEnteredFormat(horizontalAlignment,textFormat"
        if f:
            style["numberFormat"] = {"type": "NUMBER", "pattern": f}
            champs += ",numberFormat"
        champs += ")"
        reqs.append(_cell(_rng(sid, ligne1, ligne2, c, c), style, champs))
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS",
                      "startIndex": c - 1, "endIndex": c},
            "properties": {"pixelSize": LARGEURS.get(nom, LARGEUR_DEFAUT)},
            "fields": "pixelSize"}})
    # zebrure : lisible sans effort
    reqs.append({"addBanding": {"bandedRange": {
        "range": _rng(sid, ligne1, ligne2, col1, col1 + n - 1),
        "rowProperties": {"firstBandColor": BLANC,
                          "secondBandColor": LILAS}}}})
    return reqs


def banniere(sid: int, ligne: int, c1: int, c2: int) -> List[dict]:
    return [_cell(_rng(sid, ligne, ligne, c1, c2),
                  {"backgroundColor": VIOLET,
                   "textFormat": {"bold": True, "foregroundColor": BLANC,
                                  "fontSize": 10}},
                  "userEnteredFormat(backgroundColor,textFormat)")]


def titre(sid: int, c2: int) -> List[dict]:
    return [
        {"mergeCells": {"range": _rng(sid, 1, 1, 1, c2), "mergeType":
                        "MERGE_ROWS"}},
        _cell(_rng(sid, 1, 1, 1, c2),
              {"backgroundColor": NOIR,
               "textFormat": {"bold": True, "fontSize": 15,
                              "foregroundColor": OR},
               "horizontalAlignment": "CENTER"},
              "userEnteredFormat(backgroundColor,textFormat,"
              "horizontalAlignment)"),
        {"mergeCells": {"range": _rng(sid, 2, 2, 1, c2), "mergeType":
                        "MERGE_ROWS"}},
        _cell(_rng(sid, 2, 2, 1, c2),
              {"backgroundColor": NOIR,
               "textFormat": {"italic": True, "fontSize": 9,
                              "foregroundColor": {"red": 0.8, "green": 0.8,
                                                  "blue": 0.8}},
               "horizontalAlignment": "CENTER"},
              "userEnteredFormat(backgroundColor,textFormat,"
              "horizontalAlignment)"),
    ]


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


def purger(sh, sid: int) -> List[dict]:
    """Repart d'une page propre : les bandes et fusions de la passe precedente.
    Sans ca, chaque run empile ses zebrures et Google finit par refuser."""
    reqs: List[dict] = [{"unmergeCells": {"range": {"sheetId": sid}}}]
    try:
        meta = sh.fetch_sheet_metadata()
        for f in meta.get("sheets", []):
            if f.get("properties", {}).get("sheetId") != sid:
                continue
            for b in f.get("bandedRanges", []) or []:
                reqs.append({"deleteBanding":
                             {"bandedRangeId": b["bandedRangeId"]}})
    except Exception:
        pass
    return reqs


def habiller(sh, ws, quotidien, n_jours, periode, n_mois, n_annees,
             vvf, whales, n_whales, ligne_notes, n_notes, ancres) -> int:
    """Habille toute la page. Chaque bloc est decrit par SES EN-TETES : les
    formats suivent les noms, jamais les positions."""
    sid = ws.id
    L = len(quotidien)                      # 19 colonnes (A..S)
    groupes = ["", "", "TRANSACTION", "", "", "", "", "ACTIF", "", "",
               "LISTING", "", "REVENUE", "", "", "OMI BURN", "", "", ""]
    reqs = purger(sh, sid)
    reqs += titre(sid, L)

    # bandeau semaine + KPI
    reqs += banniere(sid, 4, 1, L)
    reqs.append({"mergeCells": {"range": _rng(sid, 4, 4, 1, L),
                                "mergeType": "MERGE_ROWS"}})
    reqs.append(_cell(_rng(sid, 5, 5, 1, 12),
                      {"textFormat": {"bold": True, "fontSize": 9,
                                      "foregroundColor": GRIS_TXT},
                       "horizontalAlignment": "CENTER", "wrapStrategy": "WRAP"},
                      "userEnteredFormat(textFormat,horizontalAlignment,"
                      "wrapStrategy)"))
    reqs.append(_cell(_rng(sid, 6, 6, 1, 12),
                      {"textFormat": {"bold": True, "fontSize": 12},
                       "horizontalAlignment": "CENTER"},
                      "userEnteredFormat(textFormat,horizontalAlignment)"))
    reqs.append(_cell(_rng(sid, 6, 6, 1, 1),
                      {"numberFormat": {"type": "NUMBER", "pattern": ARGENT}},
                      "userEnteredFormat.numberFormat"))

    # tableau QUOTIDIEN
    reqs += bloc(sid, quotidien, 9, 10, 9 + max(1, n_jours), groupes=groupes)

    # 📅 PAR MOIS / PAR ANNEE + 📈 PULSE (memes en-tetes -> memes formats)
    for ancre, n in ((ancres["mois"], n_mois), (ancres["annee"], n_annees)):
        reqs += banniere(sid, ancre, 1, L)
        reqs += banniere(sid, ancre, 20, 19 + len(vvf))
        reqs += bloc(sid, periode, ancre + 2, ancre + 3,
                     ancre + 2 + max(1, n), groupes=groupes)
        reqs += bloc(sid, vvf, ancre + 2, ancre + 3, ancre + 2 + max(1, n),
                     col1=20)

    # ℹ️ NOTES : du texte qui respire, pas un mur
    reqs += notes(sid, ligne_notes, max(1, n_notes), L)

    # 🐋 CLASSEMENT WHALES : 3 blocs de 10 colonnes
    if n_whales:
        a = ancres["whales"]
        reqs += banniere(sid, a, 1, 32)
        for i in range(3):
            c1 = 1 + i * 11
            reqs.append(_cell(_rng(sid, a + 1, a + 1, c1, c1 + 9),
                              {"textFormat": {"bold": True, "fontSize": 10}},
                              "userEnteredFormat.textFormat"))
            reqs += bloc(sid, whales, a + 2, a + 3, a + 2 + n_whales, col1=c1)

    # figer l'en-tete du quotidien + la colonne des dates
    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": sid,
                       "gridProperties": {"frozenRowCount": 9,
                                          "frozenColumnCount": 1}},
        "fields": "gridProperties(frozenRowCount,frozenColumnCount)"}})
    sh.batch_update({"requests": reqs})
    return len(reqs)
