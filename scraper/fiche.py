"""🦊 FICHE PAR ITEM (style VeveFox) — le module INTERACTIF au bas de 📊 STATS.

Preda choisit un item dans un MENU DEROULANT (validation de donnees pointant la
colonne des noms de 🎯A-CORNERISATION) et TOUT se recalcule instantanement :
KPIs, repartition par PROFIL, par ACTIVITE, par TAILLE de wallet, par QUANTITE
detenue (personnes ET exemplaires), et les 3 grilles croisees (heatmaps).

  * ZERO collecte, ZERO workflow : le module n'est que des FORMULES qui lisent la
    fiche deja calculee par le ledger dans 🎯A-CORNERISATION. Changer d'item =
    changer une cellule -> toutes les formules se rafraichissent.
  * Le mapping colonne -> lettre est lu de l'EN-TETE au runtime (pas de position
    en dur) : si un jour l'ordre des colonnes bouge, le module suit.
  * Les comptes 1-D (profil/activite/taille/quantite) sont des colonnes SIMPLES
    de la cornerisation -> INDEX direct. Les heatmaps sont ENCODEES (";" cellules,
    "|" lignes) -> on les re-explose cellule par cellule avec SPLIT/INDEX.

Ecrit en USER_ENTERED (les formules doivent etre interpretees, pas stockees en
texte). L'habillage (couleurs/gradients/validation) part en batch_update.
"""

from __future__ import annotations

from typing import Dict, List

CORNER_TAB = "🎯A-CORNERISATION"
Q = "'"                       # apostrophe pour citer le nom d'onglet (emoji)

# Ordres d'affichage — memes libelles que le ledger (colonnes act_/prof_/ws_/hold_).
SCORES = ["Diamond-Hands", "Serious Collector", "Collector", "Trader",
          "Flipper", "Seasoned Flipper", "Aggressive Flipper"]
PROFILE_ORDER = SCORES + ["Unclassified"]
ACTIVITIES = ["Actif", "Engagé", "Somnolant", "Inactif", "Désinscrit", "Fantôme"]
ACTIVITY_ORDER = ACTIVITIES + ["Non classé"]
QTY_ORDER = ["1", "2-10", "11-50", "51-100", "101-500", "501-1k", "1001-5k",
             "5001-10k", "10001-50k", "50001-100k", "100k+"]
HOLD_ORDER = ["1", "2-5", "6-10", "11-20", "21-50", "51-100", "101-500", "500+"]

VIOLET = {"backgroundColor": {"red": 0.482, "green": 0.173, "blue": 0.749},
          "textFormat": {"bold": True,
                         "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}
BOLD = {"textFormat": {"bold": True}}
# gradient des heatmaps : blanc -> rose VeveFox (comme la page 5 du PDF)
HEAT_MIN = {"red": 1.0, "green": 1.0, "blue": 1.0}
HEAT_MAX = {"red": 0.86, "green": 0.20, "blue": 0.54}


def _col(idx1: int) -> str:
    """1-based -> lettre(s) de colonne (1->A, 27->AA)."""
    s, n = "", idx1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# ── construction de la grille de formules ────────────────────────────────────

def _build(colmap: Dict[str, str], row0: int, default_name: str):
    """(grille de formules, meta) ancree en A{row0}. colmap : nom -> lettre."""
    SEL = f"MATCH($B${row0 + 1},{Q}{CORNER_TAB}{Q}!$B:$B,0)"

    def IDX(name: str) -> str:
        c = colmap[name]
        return f"INDEX({Q}{CORNER_TAB}{Q}!${c}:${c},{SEL})"

    grid: List[List] = []
    titles: List[int] = []
    headers: List[int] = []
    pct_ranges: List[tuple] = []
    heat_ranges: List[tuple] = []

    def add(*cells) -> int:
        grid.append(list(cells))
        return row0 + len(grid) - 1          # 1-based row de cette ligne

    banner = add("🦊 FICHE PAR ITEM — choisis un item dans le menu ▼   "
                 "(données : 🎯A-CORNERISATION, recalculées chaque nuit)")
    add("Item ▼", default_name)              # B{row0+1} = cellule du menu
    add("")
    kpi = add("Supply", f"={IDX('circulating')}",
              "Holders", f"={IDX('holders')}",
              "Gini", f"={IDX('gini')}",
              "Score collector /100", f"={IDX('avg_collector')}",
              "Score activité /100", f"={IDX('avg_activity')}")
    headers.append(kpi)

    def table(titre, labels, pers_pref, sup_pref):
        add("")
        titles.append(add(titre))
        headers.append(add("", "Personnes", "%", "Exemplaires", "% supply",
                           "▐ part de la supply"))
        first = row0 + len(grid)             # 1re ligne de donnees (1-based)
        for lab in labels:
            r = row0 + len(grid)
            add(lab,
                f"=IFERROR({IDX(pers_pref + lab)},0)",
                f"=IFERROR(B{r}/{IDX('holders')},0)",
                f"=IFERROR({IDX(sup_pref + lab)},0)",
                f"=IFERROR(D{r}/{IDX('circulating')},0)",
                f'=IFERROR(REPT("█",ROUND(E{r}*40)),"")')
        pct_ranges.append((first - 1, len(labels), 2))    # colonne C
        pct_ranges.append((first - 1, len(labels), 4))    # colonne E

    table("PROFIL — COLLECTOR SCORE", PROFILE_ORDER, "prof_pers_", "prof_sup_")
    table("ACTIVITÉ DES DÉTENTEURS", ACTIVITY_ORDER, "act_pers_", "act_sup_")
    table("TAILLE DE WALLET (quantité détenue, tous items confondus)", QTY_ORDER,
          "ws_pers_", "ws_sup_")
    table("QUANTITÉ DÉTENUE DE CET ITEM", HOLD_ORDER, "hold_pers_", "hold_sup_")

    def heatmap(titre, hm_col, rlabels, clabels):
        add("")
        titles.append(add(titre))
        headers.append(add("", *clabels))
        first = row0 + len(grid)
        for p, rlab in enumerate(rlabels, start=1):
            cells = [rlab]
            for a in range(1, len(clabels) + 1):
                cells.append(
                    f"=IFERROR(INDEX(SPLIT(INDEX(SPLIT({IDX(hm_col)},"
                    f'"|"),1,{p}),";"),1,{a})*1,0)')
            add(*cells)
        heat_ranges.append((first - 1, len(rlabels), 1, len(clabels)))

    heatmap("CROISEMENT  PROFIL × ACTIVITÉ  (exemplaires)", "hm_prof_act",
            PROFILE_ORDER, ACTIVITY_ORDER)
    heatmap("CROISEMENT  PROFIL × TAILLE DE WALLET  (exemplaires)", "hm_prof_ws",
            PROFILE_ORDER, QTY_ORDER)
    heatmap("CROISEMENT  ACTIVITÉ × TAILLE DE WALLET  (exemplaires)", "hm_act_ws",
            ACTIVITY_ORDER, QTY_ORDER)

    # rectangulaire : aucun spill (heatmaps ecrites cellule par cellule) -> on
    # peut remplir de "" sans rien bloquer.
    w = max(len(r) for r in grid)
    for r in grid:
        r += [""] * (w - len(r))
    return grid, {"banner": banner, "titles": titles, "headers": headers,
                  "pct": pct_ranges, "heat": heat_ranges,
                  "dropdown_row": row0 + 1, "width": w, "nrows": len(grid)}


# ── requetes d'habillage ─────────────────────────────────────────────────────

def _rng(sid, r0, nr, c0, nc):
    return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r0 + nr,
            "startColumnIndex": c0, "endColumnIndex": c0 + nc}


def _fmt_row(sid, row1, w, fmt):
    fields = "userEnteredFormat(" + ",".join(fmt.keys()) + ")"
    return {"repeatCell": {"range": _rng(sid, row1 - 1, 1, 0, w),
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


def _dropdown(sid, row1):
    return {"setDataValidation": {
        "range": _rng(sid, row1 - 1, 1, 1, 1),          # cellule B{row1}
        "rule": {"condition": {"type": "ONE_OF_RANGE", "values": [
            {"userEnteredValue": f"={Q}{CORNER_TAB}{Q}!$B$2:$B"}]},
            "showCustomUi": True, "strict": False}}}


def write(sh, ws, row0: int) -> int:
    """Ecrit la fiche interactive a partir de la ligne row0 de 📊 STATS.
    Ne fait RIEN si la cornerisation n'a pas encore les colonnes VeveFox."""
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
    reqs: List[dict] = [_fmt_row(sid, meta["banner"], meta["width"], VIOLET)]
    for r in meta["titles"] + meta["headers"]:
        reqs.append(_fmt_row(sid, r, meta["width"], BOLD))
    for r0, n, c in meta["pct"]:
        reqs.append(_numfmt(sid, r0, n, c, "0.0%"))
    for r0, nr, c0, nc in meta["heat"]:
        reqs.append(_numfmt(sid, r0, nr, c0, "#,##0", ncols=nc))
        reqs.append(_gradient(sid, r0, nr, c0, nc))
    reqs.append(_dropdown(sid, meta["dropdown_row"]))

    # purge des gradients de la fiche du run PRECEDENT (sinon accumulation :
    # ws.update efface les VALEURS, pas les regles conditionnelles). On supprime
    # celles ancrees dans la zone de la fiche, index DESCENDANT (sinon decalage).
    dels: List[dict] = []
    try:
        for s in sh.fetch_sheet_metadata().get("sheets", []):
            if s.get("properties", {}).get("sheetId") != sid:
                continue
            cfs = s.get("conditionalFormats", []) or []
            for i in range(len(cfs) - 1, -1, -1):
                rg = (cfs[i].get("ranges") or [{}])[0]
                if rg.get("startRowIndex", 0) >= row0 - 1:
                    dels.append({"deleteConditionalFormatRule":
                                 {"sheetId": sid, "index": i}})
            break
    except Exception:
        pass
    try:
        sh.batch_update({"requests": dels + reqs})
    except Exception as e:
        print(f"fiche : habillage refuse ({e}) — les valeurs sont posees.",
              flush=True)
    print(f"🦊 Fiche par item : {meta['nrows']} lignes écrites "
          f"(item par défaut « {default_name} »).", flush=True)
    return meta["nrows"]
