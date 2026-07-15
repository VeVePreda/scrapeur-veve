"""
Mise en forme des onglets analytiques (confort visuel).

Pose des REGLES DE MISE EN FORME CONDITIONNELLE (par valeur de texte) + des
formats de nombres, en detectant les colonnes par leur nom d'en-tete. Les regles
se re-appliquent a chaque run et survivent aux reecritures (ws.clear() n'efface
pas les regles). Palette : CollectorScore violet->rouge, activite vert->rouge,
Gini en heatmap vert->rouge.

Usage : format_tab(sh, tab_name, header, header_rows=1)
  header = liste des noms de colonnes (la ligne d'en-tete des DONNEES).
  header_rows = nb de lignes d'en-tete avant les donnees (2 pour 🐋A-WHALES).
"""

from __future__ import annotations

from typing import Dict, List


def _rgb(r, g, b):
    return {"red": r, "green": g, "blue": b}


# CollectorScore : violet fonce (diamant) -> bordeaux (aggressive flipper)
SCORE_COLORS: Dict[str, dict] = {
    "Diamond-Hands":      _rgb(0.55, 0.45, 0.78),
    "Serious Collector":  _rgb(0.67, 0.58, 0.85),
    "Collector":          _rgb(0.80, 0.73, 0.91),
    "Trader":             _rgb(0.90, 0.86, 0.95),
    "Flipper":            _rgb(0.98, 0.85, 0.89),
    "Seasoned Flipper":   _rgb(0.93, 0.62, 0.71),
    "Aggressive Flipper": _rgb(0.85, 0.42, 0.52),
}
# activityStatus : vert (actif) -> rouge (fantome). Bareme FRANCAIS
# (Preda 2026-07-10) — les anciens libelles EN sont gardes en secours le temps
# que ledger reecrive les onglets.
ACTIVITY_COLORS: Dict[str, dict] = {
    "Actif":      _rgb(0.72, 0.88, 0.78),
    "Engagé":     _rgb(0.82, 0.92, 0.80),
    "Somnolant":  _rgb(0.92, 0.93, 0.74),
    "Inactif":    _rgb(0.99, 0.90, 0.73),
    "Désinscrit": _rgb(0.97, 0.80, 0.72),
    "Fantôme":    _rgb(0.90, 0.66, 0.62),
    # legacy EN (transitoire)
    "Active":   _rgb(0.72, 0.88, 0.78),
    "Engaged":  _rgb(0.82, 0.92, 0.80),
    "Dormant":  _rgb(0.92, 0.93, 0.74),
    "Lapsed":   _rgb(0.99, 0.90, 0.73),
    "Inactive": _rgb(0.97, 0.80, 0.72),
    "Ghost":    _rgb(0.90, 0.66, 0.62),
}

# Engagement (part des semaines actives) : bleu fonce (fidele) -> gris clair
ENGAGEMENT_COLORS: Dict[str, dict] = {
    "Fidèle":      _rgb(0.61, 0.76, 0.90),
    "Régulier":    _rgb(0.74, 0.84, 0.94),
    "Occasionnel": _rgb(0.86, 0.91, 0.96),
    "Sporadique":  _rgb(0.93, 0.94, 0.96),
    "Unique":      _rgb(0.88, 0.88, 0.88),
}

SCORE_NAMES = {"score", "collectorscore", "score_dominant"}
ACT_NAMES = {"activity", "activitystatus", "activity_dominant"}
ENG_NAMES = {"engagement", "engagementlevel", "engagement_dominant"}
GINI_NAMES = {"gini"}
PCT_EXACT = {"retention"}
# scores 0-100 (fiche VeveFox) : format "0.0", surtout PAS un pourcentage.
SCORE0_100 = {"avg_collector", "avg_activity"}
# colonnes numeriques a formater avec separateur de milliers
THOUSAND_HINTS = ("value", "omi", "holdings", "circulating", "cumulative",
                  "total", "acquired", "sold", "transactions", "metric",
                  "wallets", "tokens", "new_wallets",
                  # fiche VeveFox de 🎯A-CORNERISATION : les comptes par
                  # categorie (act_/prof_/ws_/hold_ * _pers_/_sup_) sont des
                  # ENTIERS. Sans ca, ces colonnes n'etaient rattrapees par
                  # aucune regle et heritaient d'un format % parasite ("1188,0%").
                  "_pers_", "_sup_")


def _is_pct(name: str) -> bool:
    return "pct" in name or name in PCT_EXACT


def _is_thousand(name: str) -> bool:
    return any(h in name for h in THOUSAND_HINTS)


def _text_rule(rng, value, color):
    return {"addConditionalFormatRule": {"index": 0, "rule": {
        "ranges": [rng],
        "booleanRule": {
            "condition": {"type": "TEXT_EQ",
                          "values": [{"userEnteredValue": value}]},
            "format": {"backgroundColor": color}}}}}


def _gradient_rule(rng):
    # 2 points (min vert -> max rouge) ; le midpoint NUMBER 0.5 etait rejete par
    # l'API (Invalid InterpolationPoint.value). MIN/MAX auto-echelle sur la colonne.
    return {"addConditionalFormatRule": {"index": 0, "rule": {
        "ranges": [rng],
        "gradientRule": {
            "minpoint": {"color": _rgb(0.72, 0.88, 0.78), "type": "MIN"},
            "maxpoint": {"color": _rgb(0.95, 0.55, 0.50), "type": "MAX"}}}}}


def _numfmt(rng, pattern):
    return {"repeatCell": {
        "range": rng,
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER",
                                                        "pattern": pattern}}},
        "fields": "userEnteredFormat.numberFormat"}}


def build_requests(sid: int, header: List[str], header_rows: int) -> List[dict]:
    reqs: List[dict] = []
    for idx, name in enumerate(header):
        key = str(name).strip().lower()
        if not key:
            continue
        rng = {"sheetId": sid, "startRowIndex": header_rows,
               "startColumnIndex": idx, "endColumnIndex": idx + 1}
        if key in SCORE_NAMES:
            for tier, color in SCORE_COLORS.items():
                reqs.append(_text_rule(rng, tier, color))
        elif key in ACT_NAMES:
            for tier, color in ACTIVITY_COLORS.items():
                reqs.append(_text_rule(rng, tier, color))
        elif key in ENG_NAMES:
            for tier, color in ENGAGEMENT_COLORS.items():
                reqs.append(_text_rule(rng, tier, color))
        elif key in GINI_NAMES:
            reqs.append(_gradient_rule(rng))
        elif key in SCORE0_100:
            reqs.append(_numfmt(rng, "0.0"))
        elif _is_pct(key):
            reqs.append(_numfmt(rng, '0.0"%"'))
        elif _is_thousand(key):
            # #,##0 entier (fix demande Preda : les decimales .## paraissaient
            # etre des virgules de milliers en locale FR)
            reqs.append(_numfmt(rng, "#,##0"))
    return reqs


def format_tab(sh, tab_name: str, header: List[str], header_rows: int = 1) -> int:
    """Applique couleurs + formats a un onglet. Retourne le nb de requetes."""
    try:
        ws = sh.worksheet(tab_name)
    except Exception:
        return 0
    sid = ws.id
    reqs: List[dict] = []
    # purge des regles conditionnelles existantes (evite l'accumulation)
    try:
        meta = sh.fetch_sheet_metadata()
        for sheet in meta.get("sheets", []):
            if sheet.get("properties", {}).get("sheetId") == sid:
                n = len(sheet.get("conditionalFormats", []) or [])
                for _ in range(n):
                    reqs.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}})
                break
    except Exception:
        pass
    reqs += build_requests(sid, header, header_rows)
    if reqs:
        try:
            sh.batch_update({"requests": reqs})
        except Exception as e:
            print(f"    formatting warning ({tab_name}): {e}", flush=True)
    return len(reqs)
