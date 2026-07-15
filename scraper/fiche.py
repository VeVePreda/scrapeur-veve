"""🦊 FICHE PAR ITEM (style VeveFox) — le module INTERACTIF au bas de 📊 STATS.

Preda choisit un item dans un MENU DEROULANT (validation de donnees pointant la
colonne des noms de 🎯A-CORNERISATION) et TOUT se recalcule instantanement :
KPIs, repartition par PROFIL, ACTIVITE, TAILLE de wallet, QUANTITE detenue
(personnes ET exemplaires), et les 3 grilles croisees (heatmaps).

DISPOSITION HORIZONTALE (demande Preda) : les 4 tableaux sont COTE A COTE (ils
tiennent dans la largeur d'ecran), zebres, avec une couleur de fond par
CATEGORIE (le bandeau titre). La cellule du MENU est surlignee. Heatmaps dessous.
Chaque tableau : label · Personnes · Exemplaires · % (la colonne barre a ete
retiree — demande Preda).

  * ZERO collecte, ZERO workflow : le module n'est que des FORMULES qui lisent la
    fiche deja calculee par le ledger dans 🎯A-CORNERISATION.
  * ⚠️ LOCALE FR : separateur d'arguments = POINT-VIRGULE ";" (pas la virgule,
    sinon #ERROR!). Les "|" et ";" entre guillemets restent des delimiteurs.
  * ⚠️ FORMATS EXPLICITES : batch_clear efface les valeurs mais PAS les formats
    -> on remet tout le bloc en "#,##0" (pre), puis on surcharge les rares
    colonnes non entieres (%, scores, Gini). Sinon les comptes heritent d'un
    format % parasite ("331100,0%" au lieu de "3311").
  * Le mapping colonne -> lettre est lu de l'EN-TETE au runtime.
"""

from __future__ import annotations

from typing import Dict, List

CORNER_TAB = "🎯A-CORNERISATION"
Q = "'"

SCORES = ["Diamond-Hands", "Serious Collector", "Collector", "Trader",
          "Flipper", "Seasoned Flipper", "Aggressive Flipper"]
PROFILE_ORDER = SCORES + ["Unclassified"]
ACTIVITIES = ["Actif", "Engagé", "Somnolant", "Inactif", "Désinscrit", "Fantôme"]
ACTIVITY_ORDER = ACTIVITIES + ["Non classé"]
QTY_ORDER = ["1", "2-10", "11-50", "51-100", "101-500", "501-1k", "1001-5k",
             "5001-10k", "10001-50k", "50001-100k", "100k+"]
HOLD_ORDER = ["1", "2-5", "6-10", "11-20", "21-50", "51-100", "101-500", "500+"]

TW = 4                        # largeur d'un tableau : label + Pers + Exempl + %


def _rgb(r, g, b):
    return {"red": r, "green": g, "blue": b}


BLANC = _rgb(1, 1, 1)
VIOLET = {"backgroundColor": _rgb(0.482, 0.173, 0.749),
          "textFormat": {"bold": True, "foregroundColor": BLANC}}
BOLD = {"textFormat": {"bold": True}}
HILITE = {"backgroundColor": _rgb(1.0, 0.90, 0.46),      # or/jaune : le menu ressort
          "textFormat": {"bold": True}}
ZEBRA = _rgb(0.965, 0.955, 0.99)
FAM = {
    "profil":   (_rgb(0.80, 0.73, 0.91), _rgb(0.91, 0.88, 0.97)),
    "activite": (_rgb(0.80, 0.90, 0.78), _rgb(0.91, 0.96, 0.90)),
    "taille":   (_rgb(0.78, 0.87, 0.95), _rgb(0.90, 0.94, 0.98)),
    "quantite": (_rgb(1.0, 0.93, 0.76),  _rgb(1.0, 0.97, 0.89)),
    "heat":     (_rgb(0.86, 0.78, 0.94), _rgb(0.93, 0.90, 0.98)),
}
HEAT_MIN = _rgb(1.0, 1.0, 1.0)
HEAT_MAX = _rgb(0.86, 0.20, 0.54)


def _col(idx1: int) -> str:
    s, n = "", idx1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _build(colmap: Dict[str, str], row0: int, default_name: str):
    R0 = row0 - 1
    SEL = f"MATCH($B${row0 + 1};{Q}{CORNER_TAB}{Q}!$B:$B;0)"

    def IDX(name: str) -> str:
        c = colmap[name]
        return f"INDEX({Q}{CORNER_TAB}{Q}!${c}:${c};{SEL})"

    G: Dict[tuple, object] = {}
    titles: List[tuple] = []
    headers: List[tuple] = []
    zebra: List[tuple] = []
    numfmt: List[tuple] = []       # (r0, nr, c0, nc, pattern) — surcharges non entieres
    heat_titles: List[tuple] = []
    heat_ranges: List[tuple] = []

    def put(r, c, val):
        G[(r, c)] = val

    put(0, 0, "🦊 FICHE PAR ITEM — choisis un item dans le menu ▼   "
              "(données : 🎯A-CORNERISATION, recalculées chaque nuit)")
    put(1, 0, "Item ▼")
    put(1, 1, default_name)
    kpis = [("Supply", "circulating", "#,##0"), ("Holders", "holders", "#,##0"),
            ("Gini", "gini", "0.000"), ("Score coll. /100", "avg_collector", "0.0"),
            ("Score act. /100", "avg_activity", "0.0")]
    for i, (lbl, col, fmt) in enumerate(kpis):
        put(3, 2 * i, lbl)
        put(3, 2 * i + 1, f"={IDX(col)}")
        if fmt != "#,##0":                         # #,##0 vient du reset global
            numfmt.append((R0 + 3, 1, 2 * i + 1, 1, fmt))

    def table(top, left, fam, titre, labels, pers_pref, sup_pref):
        titles.append((R0 + top, left, TW, fam))
        put(top, left, titre)
        headers.append((R0 + top + 1, left, TW, fam))
        for j, h in enumerate(("", "Pers.", "Exempl.", "%")):
            put(top + 1, left + j, h)
        for k, lab in enumerate(labels):
            r = top + 2 + k
            row1 = row0 + r
            expl = f"{_col(left + 3)}{row1}"        # cellule Exempl. (col left+2)
            put(r, left, lab)
            put(r, left + 1, f"=IFERROR({IDX(pers_pref + lab)};0)")
            put(r, left + 2, f"=IFERROR({IDX(sup_pref + lab)};0)")
            put(r, left + 3, f"=IFERROR({expl}/{IDX('circulating')};0)")
        zebra.append((R0 + top + 2, len(labels), left, TW))
        numfmt.append((R0 + top + 2, len(labels), left + 3, 1, "0.0%"))   # colonne %

    T = 5
    table(T, 0,  "profil",   "PROFIL — COLLECTOR SCORE",      PROFILE_ORDER,
          "prof_pers_", "prof_sup_")
    table(T, 5,  "activite", "ACTIVITÉ DES DÉTENTEURS",       ACTIVITY_ORDER,
          "act_pers_", "act_sup_")
    table(T, 10, "taille",   "TAILLE DE WALLET (tous items)", QTY_ORDER,
          "ws_pers_", "ws_sup_")
    table(T, 15, "quantite", "QUANTITÉ DÉTENUE (cet item)",   HOLD_ORDER,
          "hold_pers_", "hold_sup_")
    bottom = T + 2 + max(len(PROFILE_ORDER), len(ACTIVITY_ORDER),
                         len(QTY_ORDER), len(HOLD_ORDER))

    def heatmap(top, titre, hm_col, rlabels, clabels):
        heat_titles.append((R0 + top, 0, 1 + len(clabels)))
        put(top, 0, titre)
        for j, cl in enumerate(clabels):
            put(top + 1, 1 + j, cl)
        for p, rlab in enumerate(rlabels, start=1):
            r = top + 1 + p
            put(r, 0, rlab)
            for a in range(1, len(clabels) + 1):
                put(r, a,
                    f"=IFERROR(INDEX(SPLIT(INDEX(SPLIT({IDX(hm_col)};"
                    f'"|");1;{p});";");1;{a})*1;0)')
        heat_ranges.append((R0 + top + 2, len(rlabels), 1, len(clabels)))
        return top + 2 + len(rlabels)

    h = bottom + 1
    h = heatmap(h, "CROISEMENT  PROFIL × ACTIVITÉ  (exemplaires)",
                "hm_prof_act", PROFILE_ORDER, ACTIVITY_ORDER) + 1
    h = heatmap(h, "CROISEMENT  PROFIL × TAILLE DE WALLET  (exemplaires)",
                "hm_prof_ws", PROFILE_ORDER, QTY_ORDER) + 1
    h = heatmap(h, "CROISEMENT  ACTIVITÉ × TAILLE DE WALLET  (exemplaires)",
                "hm_act_ws", ACTIVITY_ORDER, QTY_ORDER) + 1

    max_r = max(r for r, _ in G)
    max_c = max(c for _, c in G)
    grid = [["" for _ in range(max_c + 1)] for _ in range(max_r + 1)]
    for (r, c), v in G.items():
        grid[r][c] = v

    meta = {"banner": (R0, max_c + 1), "kpi_row": R0 + 3, "titles": titles,
            "headers": headers, "zebra": zebra, "numfmt": numfmt,
            "heat_titles": heat_titles, "heat_ranges": heat_ranges,
            "dropdown_row": row0 + 1, "nrows": len(grid), "width": max_c + 1,
            "area": (R0, len(grid), 0, max_c + 1)}
    return grid, meta


# ── requetes d'habillage ─────────────────────────────────────────────────────

def _rng(sid, r0, nr, c0, nc):
    return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r0 + nr,
            "startColumnIndex": c0, "endColumnIndex": c0 + nc}


def _bg(sid, r0, nr, c0, nc, fmt):
    fields = "userEnteredFormat(" + ",".join(fmt.keys()) + ")"
    return {"repeatCell": {"range": _rng(sid, r0, nr, c0, nc),
                           "cell": {"userEnteredFormat": fmt}, "fields": fields}}


def _numfmt(sid, r0, nr, c0, pattern, ncols=1):
    return {"repeatCell": {
        "range": _rng(sid, r0, nr, c0, ncols),
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER",
                                                        "pattern": pattern}}},
        "fields": "userEnteredFormat.numberFormat"}}


def _gradient(sid, r0, nr, c0, nc):
    return {"addConditionalFormatRule": {"index": 0, "rule": {
        "ranges": [_rng(sid, r0, nr, c0, nc)],
        "gradientRule": {"minpoint": {"color": HEAT_MIN, "type": "MIN"},
                         "maxpoint": {"color": HEAT_MAX, "type": "MAX"}}}}}


def _merge(sid, r0, c0, nc):
    return {"mergeCells": {"range": _rng(sid, r0, 1, c0, nc),
                           "mergeType": "MERGE_ALL"}}


def _dropdown(sid, row1):
    return {"setDataValidation": {
        "range": _rng(sid, row1 - 1, 1, 1, 1),
        "rule": {"condition": {"type": "ONE_OF_RANGE", "values": [
            {"userEnteredValue": f"={Q}{CORNER_TAB}{Q}!$B$2:$B"}]},
            "showCustomUi": True, "strict": False}}}


def write(sh, ws, row0: int) -> int:
    try:
        header = sh.worksheet(CORNER_TAB).row_values(1)
    except Exception as e:
        print(f"fiche : 🎯A-CORNERISATION illisible ({e}) — module non ecrit.",
              flush=True)
        return 0
    colmap = {name: _col(i + 1) for i, name in enumerate(header) if name}
    besoin = ["circulating", "holders", "prof_sup_Diamond-Hands",
              "act_sup_Actif", "hm_prof_act", "avg_collector"]
    manque = [b for b in besoin if b not in colmap]
    if manque:
        print(f"fiche : colonnes VeveFox absentes de 🎯A-CORNERISATION "
              f"({', '.join(manque)}) — relancer le ledger. Module non ecrit.",
              flush=True)
        return 0
    try:
        default_name = sh.worksheet(CORNER_TAB).acell("B2").value or ""
    except Exception:
        default_name = ""

    grid, meta = _build(colmap, row0, default_name)
    need = row0 + meta["nrows"] + 4
    if ws.row_count < need:
        try:
            ws.resize(rows=need)
        except Exception:
            pass
    ws.update(range_name=f"A{row0}", values=grid,
              value_input_option="USER_ENTERED")

    sid = ws.id
    ar0, anr, ac0, anc = meta["area"]
    # AVANT tout : defaire les fusions, remettre le bloc en BLANC et en "#,##0"
    # (batch_clear efface les valeurs, pas les fonds ni les formats de nombre ->
    # sinon couleurs et "%" du run precedent trainent).
    pre = [{"unmergeCells": {"range": _rng(sid, ar0, anr, ac0, anc)}},
           _bg(sid, ar0, anr, ac0, anc, {"backgroundColor": BLANC}),
           _numfmt(sid, ar0, anr, ac0, "#,##0", ncols=anc)]
    reqs: List[dict] = []
    br0, bnc = meta["banner"]
    reqs.append(_bg(sid, br0, 1, 0, bnc, VIOLET))
    reqs.append(_merge(sid, br0, 0, bnc))
    reqs.append(_bg(sid, meta["kpi_row"], 1, 0, 10, BOLD))
    # menu de l'item : surligne (demande Preda) + label en gras
    reqs.append(_bg(sid, ar0 + 1, 1, 0, 1, BOLD))
    reqs.append(_bg(sid, ar0 + 1, 1, 1, 1, HILITE))
    for r0, c0, nc, fam in meta["titles"]:
        reqs.append(_bg(sid, r0, 1, c0, nc,
                        {"backgroundColor": FAM[fam][0],
                         "textFormat": {"bold": True},
                         "horizontalAlignment": "CENTER"}))
        reqs.append(_merge(sid, r0, c0, nc))
    for r0, c0, nc, fam in meta["headers"]:
        reqs.append(_bg(sid, r0, 1, c0, nc,
                        {"backgroundColor": FAM[fam][1],
                         "textFormat": {"bold": True}}))
    for r0, nr, c0, nc in meta["zebra"]:
        for k in range(nr):
            if k % 2 == 1:
                reqs.append(_bg(sid, r0 + k, 1, c0, nc,
                                {"backgroundColor": ZEBRA}))
    for r0, nr, c0, nc, pat in meta["numfmt"]:
        reqs.append(_numfmt(sid, r0, nr, c0, pat, ncols=nc))
    for r0, c0, nc in meta["heat_titles"]:
        reqs.append(_bg(sid, r0, 1, c0, nc,
                        {"backgroundColor": FAM["heat"][0],
                         "textFormat": {"bold": True}}))
    for r0, nr, c0, nc in meta["heat_ranges"]:
        reqs.append(_gradient(sid, r0, nr, c0, nc))
    reqs.append(_dropdown(sid, meta["dropdown_row"]))

    # purge des gradients du run PRECEDENT (accumulation sinon).
    dels: List[dict] = []
    try:
        for s in sh.fetch_sheet_metadata().get("sheets", []):
            if s.get("properties", {}).get("sheetId") != sid:
                continue
            cfs = s.get("conditionalFormats", []) or []
            for i in range(len(cfs) - 1, -1, -1):
                rg = (cfs[i].get("ranges") or [{}])[0]
                if rg.get("startRowIndex", 0) >= ar0:
                    dels.append({"deleteConditionalFormatRule":
                                 {"sheetId": sid, "index": i}})
            break
    except Exception:
        pass
    try:
        sh.batch_update({"requests": dels + pre + reqs})
    except Exception as e:
        print(f"fiche : habillage refuse ({e}) — les valeurs sont posees.",
              flush=True)
    print(f"🦊 Fiche par item : {meta['nrows']} lignes × {meta['width']} col "
          f"(item par défaut « {default_name} »).", flush=True)
    return meta["nrows"]
