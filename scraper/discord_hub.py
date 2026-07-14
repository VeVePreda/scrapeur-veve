"""🎛️ LE HUB DISCORD — UN workflow, N modules.

Demande de Preda (14/07) : « on a encore beaucoup de choses a integrer, il ne
faut pas 50 workflows, essaye de reunir sur le meme avec une option manuelle
pour activer qu'une partie ».

C'est ici que ca se joue : `DISCORD_MODULES` (l'input du workflow) dit QUI
tourne. Ajouter un module demain = une ligne dans `MODULES`, zero workflow de
plus.

    DISCORD_MODULES=stats,blog      (par defaut : tout)
    DISCORD_MODULES=blog            (ne reveiller que le blog)

DEUX PRINCIPES, et ils comptent autant que le code
--------------------------------------------------
1. **UN MODULE QUI TOMBE N'EN FAIT PAS TOMBER UN AUTRE.** Chaque module est
   appele dans son propre try : si le blog plante, les stats sont quand meme
   publiees, et le hub sort en erreur A LA FIN (pour que l'echec soit visible
   dans Actions, pas etouffe).
2. **LES GARDE-FOUS SONT DANS `discord_api`, PAS RECOPIES.** 429 respecte,
   mentions bridees, etat par module, thread_id sur chaque appel. Un module
   nouveau en herite gratuitement — c'est tout l'interet de ne pas eparpiller.
"""

from __future__ import annotations

import os
import sys
import traceback
from typing import Callable, Dict

from scraper import discord_blog, discord_stats

# Le registre. Ajouter un module = ajouter une ligne ICI (et rien d'autre).
MODULES: Dict[str, Callable[[], int]] = {
    "stats": discord_stats.run,
    "blog": discord_blog.run,
}

DEMANDES = [m.strip() for m in
            os.environ.get("DISCORD_MODULES", ",".join(MODULES)).split(",")
            if m.strip()]


def main() -> int:
    inconnus = [m for m in DEMANDES if m not in MODULES]
    if inconnus:
        print(f"Modules inconnus : {inconnus} — connus : {list(MODULES)}",
              file=sys.stderr)
    a_faire = [m for m in DEMANDES if m in MODULES]
    if not a_faire:
        print("Aucun module a lancer.", file=sys.stderr)
        return 2

    print(f"Hub Discord — modules : {', '.join(a_faire)}", flush=True)
    codes = {}
    for m in a_faire:
        print(f"\n──────── {m.upper()} ────────", flush=True)
        try:
            codes[m] = MODULES[m]()
        except Exception:                                   # noqa: BLE001
            # Un module qui tombe ne doit pas emporter les autres avec lui.
            traceback.print_exc()
            codes[m] = 1

    print(f"\nHub Discord : {codes}", flush=True)
    return 0 if all(c == 0 for c in codes.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
