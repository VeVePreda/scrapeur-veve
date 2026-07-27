"""🐋 EXPORT DES COMPTES SUIVIS — le pont vers jetonveve (canal whale/team).

Le tag « Type de compte » (VeVe Team / Fondateur / Moderation / Publisher /
Influenceur / A suivre) vit dans l'onglet 🟣C-PSEUDOS du Sheet, donc chez preda
(PRIVE). Le module `whale_watch.py` (jetonveve, PUBLIC) ne peut pas lire le
Sheet : on lui EXPORTE les seules lignes taguees dans `data/tracked_accounts.csv`
qu'il lit en sparse-checkout. Meme mecanique que `export_elements.py`.

On n'exporte QUE les lignes AVEC un tag (une ligne sans « Type de compte » n'est
pas suivie) et on n'ecrase JAMAIS le CSV avec du vide si la lecture echoue (la
recolte est sacree). Colonnes : username, type, veve_user_id, wallet_imx,
wallet_stackr, holdings, value_floor (les deux derniers enrichissent la carte).

═══════════════════════════════════════════════════════════════════════════
⭐ 27/07/2026 — POURQUOI `veve_user_id` A ETE AJOUTE : LA CAUSE RACINE DU
   « je n'ai d'alerte que pour UN SEUL compte suivi » (Preda)
═══════════════════════════════════════════════════════════════════════════
Constat sur le CSV de prod : 7 comptes tagues, dont **5 SANS AUCUN WALLET**
(Omegatron88, SwampyNumber5, RaVeN100, DAOMIHOMIE, stellanovas). Or
`whale_watch` ne sait rapprocher un evenement d'un compte que par WALLET ou par
PSEUDO. Sans wallet, il ne restait que le pseudo.

Et c'est la que ca cassait : sonde du 27/07 sur 14 000 transactions VeVe reelles
(`publicVeve.getVeveTransactions`, 3 derniers jours), trois de ces comptes
apparaissent bel et bien — mais avec `buyer_username` / `seller_username` a
**null**. Leur seule identite dans le flux est `buyer_id` / `seller_id`,
c'est-a-dire le **veve_user_id**. Que le Sheet connait pour les 7 comptes… et
que ce pont n'exportait pas.

⭐ LA LEÇON : le pont ne transportait pas la seule cle qui matchait. Aucune
erreur, aucun log, aucune alerte — juste un silence qui ressemblait a un marche
calme. Meme famille de panne que les 15 reglages non cables du 20/07 : ce n'est
pas le code qui etait faux, c'est ce qu'on lui donnait a lire.

Wallets retrouves par cette sonde (a coller dans 🟣C-PSEUDOS, colonne
wallet_imx — verifies presents sur IMX **et** CollectChain dans les archives) :
    Omegatron88    0x7b91247f9d110b07741c9e6b42cd2a4dec4879e3
    RaVeN100       0x6131a91afc74c65b4f3e05e7367ca04623b9c008
    SwampyNumber5  0xc895c74d51cafda1d74f644dc2442ca2a74db8fe
DAOMIHOMIE et stellanovas n'ont fait AUCUNE transaction sur ces 3 jours : leur
wallet reste inconnu, et `whale_watch` le moissonnera tout seul des qu'ils
bougeront (il memorise le wallet vu en face d'un veve_user_id suivi).

Env : GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID, TRACKED_CSV.
"""

from __future__ import annotations

import csv
import os
import sys
import time
from typing import List

from scraper.sheets import _client, _open_worksheet, append_log
from scraper.stackr import PSEUDOS_TAB, PSEUDOS_HEADER

CSV_PATH = os.environ.get("TRACKED_CSV", "data/tracked_accounts.csv")
# ⚠️ L'ORDRE DES COLONNES N'A AUCUNE IMPORTANCE cote lecteur (whale_watch lit
# par NOM via csv.DictReader), mais `veve_user_id` doit y ETRE : c'est la seule
# cle qui identifie un compte suivi dans le flux VeVe quand le pseudo est null.
ENTETE = ["username", "type", "veve_user_id", "wallet_imx", "wallet_stackr",
          "holdings", "value_floor"]
TYPE_COL = "Type de compte"


def _retry(quoi, fn, essais=5):
    for i in range(1, essais + 1):
        try:
            return fn()
        except Exception as e:                                  # noqa: BLE001
            if i == essais:
                raise
            print(f"  {quoi} : {e} — nouvel essai ({i}/{essais})",
                  file=sys.stderr)
            time.sleep(min(60, 3 * 2 ** i))


def main() -> int:
    sid = os.environ.get("SHEET_ID")
    if not sid:
        print("SHEET_ID manquant.", file=sys.stderr)
        return 2
    sh = _retry("ouverture du Sheet", lambda: _client().open_by_key(sid))
    ws = _retry("ouverture 🟣C-PSEUDOS",
                lambda: _open_worksheet(sh, PSEUDOS_TAB, cols=len(PSEUDOS_HEADER)))
    rows = _retry("lecture 🟣C-PSEUDOS",
                  lambda: ws.get_all_records() if ws.row_count > 1 else [])
    if rows is None:
        print("⛔ 🟣C-PSEUDOS illisible — on ne touche pas au CSV existant.",
              file=sys.stderr)
        return 3

    out: List[List] = []
    for r in rows:
        typ = str(r.get(TYPE_COL, "")).strip()
        if not typ:
            continue                          # seul le tag fait suivre
        out.append([str(r.get("username", "")).strip(), typ,
                    str(r.get("veve_user_id", "")).strip(),
                    str(r.get("wallet_imx", "")).strip(),
                    str(r.get("wallet_stackr", "")).strip(),
                    str(r.get("holdings", "")).strip(),
                    str(r.get("value_floor", "")).strip()])

    os.makedirs(os.path.dirname(CSV_PATH) or ".", exist_ok=True)
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(ENTETE)
        w.writerows(out)

    par_type = {}
    for r in out:
        par_type[r[1]] = par_type.get(r[1], 0) + 1
    detail = " · ".join(f"{k}={v}" for k, v in sorted(par_type.items())) or "aucun"
    print(f"🐋 {len(out)} compte(s) suivi(s) exporte(s) ({detail}) -> {CSV_PATH}",
          flush=True)
    # ⭐ LE PONT DIT CE QU'IL TRANSPORTE (27/07). Un compte sans wallet NI
    # veve_user_id est INSUIVABLE, et c'est exactement ce qui passait
    # inapercu : le fichier existait, le module tournait, et personne ne
    # savait que 5 comptes sur 7 n'avaient aucune chance de matcher.
    sans_wallet = [r[0] or "(sans pseudo)" for r in out if not (r[3] or r[4])]
    muets = [r[0] or "(sans pseudo)" for r in out
             if not (r[2] or r[3] or r[4])]
    print(f"   identite : {sum(1 for r in out if r[3] or r[4])} avec wallet · "
          f"{sum(1 for r in out if r[2])} avec veve_user_id", flush=True)
    if sans_wallet:
        print(f"   ⚠️ {len(sans_wallet)} sans wallet — pas de gros transferts "
              f"on-chain pour eux (les achats/ventes marche passent quand "
              f"meme par le veve_user_id) : "
              + ", ".join(sans_wallet[:8]), flush=True)
    if muets:
        print(f"   ⛔ {len(muets)} compte(s) NI wallet NI veve_user_id : "
              f"INSUIVABLES, ils ne declencheront jamais rien. Completer "
              f"🟣C-PSEUDOS : " + ", ".join(muets[:8]), file=sys.stderr)
    try:
        append_log(sid, "export_tracked", "OK", f"{len(out)} comptes · {detail}")
    except Exception:                                           # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
