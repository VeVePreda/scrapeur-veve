"""🧬 merge_archive — UN fichier propre de bout en bout des transferts CollectChain.

Fusionne toutes les archives brutes (Release "chain-archive" du deep scan
astronema + Release "chain-archive-daily" preda) en un SEUL CSV.gz, genese ->
maintenant : deduplique par (block, log_index) — la MEME cle que le ledger — et
trie par (block, log_index) croissant.

Toutes les archives partagent l'entete :
    block,log_index,ts_utc,date_pt,kind,category,veve_uuid,edition,from,to

Usage : python -m scraper.merge_archive <dossier_entree> <sortie.csv.gz>
        (defauts : "archive"  et  "transfers_full.csv.gz")

⚠️ MEMOIRE : ~13,9 M transferts. Pour tenir dans la RAM d'un runner (~14-16 Go)
on garde en memoire la LIGNE BRUTE (str) et non une liste de champs — bien plus
compact. block et log_index n'ont jamais de virgule, donc split(",", 2) suffit a
extraire la cle sans casser les autres champs.
"""

from __future__ import annotations

import glob
import gzip
import os
import sys

HEADER = ("block,log_index,ts_utc,date_pt,kind,category,veve_uuid,edition,"
          "from,to")


def _int(x: str) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else "archive"
    out = sys.argv[2] if len(sys.argv) > 2 else "transfers_full.csv.gz"
    files = sorted(glob.glob(os.path.join(src, "transfers_*.csv.gz")))
    if not files:
        print(f"Aucune archive transfers_*.csv.gz dans {src}", file=sys.stderr)
        return 1
    print(f"{len(files)} archive(s) a fusionner.", flush=True)

    rows: dict = {}                 # (block, log_index) -> ligne brute (sans \n)
    lus, doublons = 0, 0
    for i, f in enumerate(files, 1):
        n = 0
        with gzip.open(f, "rt", encoding="utf-8", newline="") as fh:
            fh.readline()           # saute l'entete de cette archive
            for line in fh:
                line = line.rstrip("\n").rstrip("\r")
                if not line:
                    continue
                p = line.split(",", 2)
                if len(p) < 2:
                    continue
                key = (_int(p[0]), _int(p[1]))
                if key in rows:
                    doublons += 1
                else:
                    rows[key] = line
                n += 1
        lus += n
        print(f"  [{i}/{len(files)}] {os.path.basename(f)} : {n} lignes "
              f"(cumul uniques {len(rows)})", flush=True)

    print(f"Total lu {lus}, uniques {len(rows)}, doublons ecartes {doublons}.",
          flush=True)

    ordered = sorted(rows)          # trie les cles (block, log_index) croissant
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8", newline="") as fh:
        fh.write(HEADER + "\n")
        for key in ordered:
            fh.write(rows[key] + "\n")

    taille = os.path.getsize(out) / (1024 * 1024)
    print(f"✅ {out} : {len(ordered)} transferts (genese -> maintenant), "
          f"{taille:.1f} Mo.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
