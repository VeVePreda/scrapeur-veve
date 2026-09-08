# ⚠️ DEPOT : VeVePreda/scrapeur-veve
# CHEMIN : tests/test_catalog_export_colonnes.py

"""Pipeline 2 : AUCUNE colonne lue ne se perd entre le Sheet et le catalogue.

═══════════════════════════════════════════════════════════════════════════════
POURQUOI CE FICHIER EXISTE — LE MEME DEFAUT S'EST PRODUIT **SIX FOIS**
═══════════════════════════════════════════════════════════════════════════════
`image`, `ath_date`, `description`, `veve_url`, les six champs du lot 78, et
maintenant `series_uuid` : a chaque fois, la donnee etait collectee par
`veve_detail`, ecrite dans les onglets froids par `sheets.py`, portee jusqu'au
writer... et jetee a la derniere etape parce que personne n'avait ajoute la
ligne. `catalog_export.py` le dit lui-meme, deux fois, dans ses commentaires :

    « CE N'EST PAS UNE DONNEE MANQUANTE, C'EST UNE LIGNE MANQUANTE. »

⛔⛔ ET RIEN NE TOMBE. `csv.DictWriter(extrasaction="ignore")` jette une cle
absente de `fieldnames` **sans un mot**. Le symptome n'est pas une erreur : c'est
un tiret sur 19 000 fiches, ou — pire — un site qui groupe par le mauvais champ
et publie un classement faux a 88 % sans que rien ne rougisse.

⭐⭐⭐ CE QUE CE BANC MESURE, ET C'EST LA LECON DU FICHIER LUI-MEME : il RELIT
L'EN-TETE PRODUIT, pas la liste source. Un banc qui verifierait « `series_uuid`
est dans COLD_MAP » serait tautologique — c'est exactement la ligne qu'on vient
d'ecrire. La question est : **est-ce que ce que je declare ARRIVE ?**
"""
import csv
import gzip
import io

from scraper.catalog_export import COLD_MAP, DYN_MAP, HEADER


# --- 1. le contrat general : rien de ce qui est lu ne se perd ---------------

def test_toute_colonne_de_cold_map_atteint_l_entete():
    """⭐ LE BANC QUI AURAIT ATTRAPE LES SIX FOIS PRECEDENTES.

    `HEADER` s'est deja construit avec `COLD_MAP[:11]` — un nombre magique qui
    voulait dire « tout sauf ath/atl » et qui faisait disparaitre en silence
    toute colonne ajoutee ensuite. La regle ne porte donc pas sur UNE colonne :
    elle porte sur l'invariant.
    """
    manquantes = [o for o, _ in COLD_MAP if o not in HEADER]
    assert not manquantes, (
        f"{len(manquantes)} colonne(s) lues dans le Sheet et absentes de "
        f"l'en-tete : {manquantes}. `DictWriter(extrasaction='ignore')` les "
        f"jettera SANS ERREUR — la donnee est lue, portee, puis abandonnee."
    )


def test_les_colonnes_chaudes_aussi():
    """`floor` et `listings` viennent de `_DynState`, pas de COLD_MAP, et ils
    passent par le meme writer. Le meme oubli les frapperait pareil."""
    manquantes = [o for o, _ in DYN_MAP if o not in HEADER]
    assert not manquantes, f"colonnes chaudes perdues : {manquantes}"


def test_l_entete_n_a_aucun_doublon():
    """Un doublon dans `fieldnames` fait ecrire la meme valeur deux fois et
    decale la lecture par POSITION en aval — plusieurs modules relisent ces
    fichiers ainsi."""
    assert len(HEADER) == len(set(HEADER)), \
        f"doublon(s) dans l'en-tete : {[c for c in HEADER if HEADER.count(c) > 1]}"


# --- 2. `series_uuid` : la clef de set ---------------------------------------

def test_series_uuid_est_exporte():
    """🎯 LA CLEF DE SET DE TOUT LE PROJET.

    Mesure du 08/09/2026 sur les 19 415 lignes d'`elements_v3.csv` : groupes par
    `series_uuid`, les comics ne font **jamais plus de 5 pieces**, et **2 075
    groupes de 5 sur 2 075** portent 5 raretes DISTINCTES — la regle metier de
    Preda au chiffre pres. Cote collectibles : 924 groupes contre les 936 Sets
    que VeVe publie via `getSets`, deux sources qui concordent.

    ⛔ Sans cette colonne dans le catalogue, `veve-sites` groupe par
    `veve_series_name` et accorde le bonus de set MCP a des objets qui n'en sont
    pas : mesure en production le meme jour, **176 des 200 premiers** du
    classement `$/MCP` sont des numeros de comics.
    """
    assert "series_uuid" in HEADER


def test_series_uuid_vient_bien_du_sheet_et_pas_d_ailleurs():
    """⭐⭐ ON EXERCE LA MEME EXPRESSION QUE L'EXPORT, pas une paraphrase.

    `main()` construit chaque ligne par `{o: (r.get(c) or "") for o, c in
    COLD_MAP}`. Si la paire etait ecrite a l'envers — `("series_uuid",
    "series")`, une faute de frappe plausible — le banc precedent resterait VERT
    et la colonne porterait le NOM de la serie au lieu de son identifiant. On
    verifie donc la valeur, sur une ligne en forme d'onglet froid.
    """
    ligne_sheet = {
        "veve_uuid": "aaaa-1111",
        "series_uuid": "bbbb-2222",          # l'identifiant du set
        "veve_series_name": "Storm Vol. 5",  # le LIBELLE, a ne pas confondre
        "name": "Storm Vol. 5 #2 (2024)",
        "category": "comic", "rarity": "COMMON",
    }
    rec = {o: (ligne_sheet.get(c) or "") for o, c in COLD_MAP}
    assert rec["series_uuid"] == "bbbb-2222", (
        "la paire de COLD_MAP ne lit pas la bonne colonne du Sheet — "
        f"attendu « bbbb-2222 », obtenu « {rec['series_uuid']} »"
    )
    # ⛔ Et le libelle reste ou il doit etre : les deux ne se remplacent pas.
    assert rec["series"] == "Storm Vol. 5"


def test_la_colonne_survit_a_l_ecriture_gzip():
    """🔴 LE SEUL CONTROLE QUI COMPTE VRAIMENT : relire le fichier PRODUIT.

    C'est ici que les six oublis precedents devenaient visibles — et nulle part
    ailleurs. On ecrit avec le MEME writer et les MEMES options que l'export
    (`DictWriter`, `extrasaction="ignore"`, gzip), puis on relit.
    """
    rec = {o: "" for o, _ in COLD_MAP}
    rec.update({o: "" for o, _ in DYN_MAP})
    rec["uuid"] = "aaaa-1111"
    rec["series_uuid"] = "bbbb-2222"

    tampon = io.BytesIO()
    with gzip.GzipFile(fileobj=tampon, mode="wb") as gz:
        fh = io.TextIOWrapper(gz, encoding="utf-8", newline="")
        w = csv.DictWriter(fh, fieldnames=list(HEADER), extrasaction="ignore")
        w.writeheader()
        w.writerow(rec)
        fh.flush()
        fh.detach()

    tampon.seek(0)
    with gzip.GzipFile(fileobj=tampon, mode="rb") as gz:
        lignes = list(csv.DictReader(io.TextIOWrapper(gz, encoding="utf-8")))

    assert lignes, "aucune ligne relue — le fichier produit est vide"
    assert "series_uuid" in lignes[0], (
        "la colonne n'a pas survecu a l'ecriture : elle est declaree, remplie, "
        "et `extrasaction='ignore'` l'a jetee sans un mot"
    )
    assert lignes[0]["series_uuid"] == "bbbb-2222"


def test_le_banc_saurait_voir_une_colonne_perdue():
    """⭐⭐⭐ CONTRE-EPREUVE — « sait-il trouver ce qu'il cherche ? »

    Un banc qui ne peut rougir sur aucune faute ne mesure rien. On lui donne un
    en-tete AMPUTE — exactement l'etat que produisait `COLD_MAP[:11]` — et on
    exige qu'il perde bien la colonne. Sans cette epreuve, les quatre tests
    ci-dessus pourraient etre verts parce que le mecanisme de perte n'existe
    plus, et non parce qu'on l'a corrige.
    """
    entete_ampute = [c for c in HEADER if c != "series_uuid"]
    tampon = io.StringIO()
    w = csv.DictWriter(tampon, fieldnames=entete_ampute, extrasaction="ignore")
    w.writeheader()
    w.writerow({"uuid": "aaaa-1111", "series_uuid": "bbbb-2222"})
    relu = list(csv.DictReader(io.StringIO(tampon.getvalue())))
    assert "series_uuid" not in relu[0], (
        "l'epreuve ne mord pas : `extrasaction='ignore'` devrait jeter la "
        "colonne absente de l'en-tete. Si elle passe, ce fichier ne prouve rien."
    )
