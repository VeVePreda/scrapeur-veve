# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_export_elements_v3.py
"""Tests du pont v3 (catalogue depuis la chaine).

Fixtures = deux transferts REELS sondes sur CollectScan le 23/07 (le comic
Star Wars, le collectible TMNT) + les lignes correspondantes de l'elements.csv
officiel. On verifie que le collapse re-derive l'identite on-chain a l'identique
et reporte proprement les colonnes off-chain.
"""

# Le module vit dans scraper/ (le test dans tests/) : import par le PAQUET,
# comme les autres tests du repo (`from scraper import ...`). pytest lance
# depuis la racine du depot.
from scraper import export_elements_v3 as v3


# --- transferts BRUTS reels (metadata telle que rendue par l'API) -----------

TMNT_UUID = "262ca5c3-d806-421d-aa0a-05207e5ea59c"
SW_UUID = "94c5804e-dfba-4734-a453-27e2a3617671"


def _transfer(block, log_index, image, metadata):
    return {
        "block_number": block, "log_index": log_index,
        "timestamp": "2026-07-15T06:06:31.000000Z",
        "total": {"token_instance": {"image_url": image, "metadata": metadata}},
    }


COLLECTIBLE_TMNT = _transfer(
    56705921, 0,
    "https://d11unjture0ske.cloudfront.net/collectible_type_image."
    "262ca5c3-d806-421d-aa0a-05207e5ea59c.bc2a8637-8aa9-4ea9-bb60-82abbd2530f2.full.jpeg",
    {"brand": "Teenage Mutant Ninja Turtles", "licensor": "Paramount Pictures",
     "name": "Donatello - IncogNinja", "rarity": "Ultra Rare",
     "editionType": "FA", "totalEditions": 487, "series": "TMNT - Donatello",
     "dropDate": "2026-07-04", "edition": 139},
)

COMIC_STARWARS = _transfer(
    56705925, 0,
    "https://d11unjture0ske.cloudfront.net/comic_cover."
    "94c5804e-dfba-4734-a453-27e2a3617671.89fd37af-ec27-44f4-9010-c3d7c678e435.full.webp",
    {"artists": "Phil Noto", "comicNumber": "4", "name": "Star Wars",
     "publisher": "Marvel", "rarity": "Rare", "series": "Star Wars Vol. 4",
     "startYear": 2025, "totalEditions": 1000, "edition": 451},
)

# lignes officielles (source des colonnes off-chain reportees)
OFFICIEL = {
    TMNT_UUID: {
        "veve_uuid": TMNT_UUID, "series_uuid": "93b9e171-1310-4914-b468-b659f1a554c0",
        "first_public": "21", "listings": "27", "note": "",
        "atl": "29", "atl_date": "2026-07-04", "ath": "45", "ath_date": "2026-07-05",
    },
    SW_UUID: {
        "veve_uuid": SW_UUID, "series_uuid": "edb6d1ba-8aab-446c-a70f-fcf557bdbbfd",
        "first_public": "", "listings": "0", "note": "",
        "atl": "18", "atl_date": "2025-09-15", "ath": "22222", "ath_date": "2025-09-24",
    },
}


def _row(rows, uid):
    return next(r for r in rows if r[0] == uid)


# --- extraction on-chain ----------------------------------------------------

def test_collectible_identite_on_chain():
    c = v3.catalogue_from_instance(
        COLLECTIBLE_TMNT["total"]["token_instance"])
    assert c["veve_uuid"] == TMNT_UUID
    assert c["category"] == "collectible"
    assert c["name"] == "Donatello - IncogNinja"
    assert c["rarity"] == "ULTRA_RARE"          # 'Ultra Rare' normalise
    assert c["edition_type"] == "FA"
    assert c["supply"] == 487
    assert c["brand"] == "Teenage Mutant Ninja Turtles"
    assert c["licensor"] == "Paramount Pictures"


def test_comic_identite_on_chain():
    c = v3.catalogue_from_instance(COMIC_STARWARS["total"]["token_instance"])
    assert c["veve_uuid"] == SW_UUID
    assert c["category"] == "comic"
    assert c["name"] == "Star Wars Vol. 4 #4 (2025)"   # {serie} #{num} ({annee})
    assert c["rarity"] == "RARE"
    assert c["edition_type"] == "4"             # comics : edition_type = comicNumber
    assert c["brand"] == "Star Wars Vol. 4"     # comics : brand = serie
    assert c["licensor"] == "Marvel"            # comics : licensor = publisher
    assert c["supply"] == 1000


def test_edition_type_zero_devient_vide():
    inst = {"image_url": "x/collectible_type_image."
            "00000000-0000-0000-0000-000000000001.a.full.jpeg",
            "metadata": {"name": "Z", "rarity": "Common", "editionType": "0",
                         "totalEditions": 1, "brand": "B", "licensor": "L"}}
    assert v3.catalogue_from_instance(inst)["edition_type"] == ""


# --- collapse : derniere metadata par item ----------------------------------

def test_collapse_garde_le_plus_recent():
    vieux = _transfer(
        100, 0, COLLECTIBLE_TMNT["total"]["token_instance"]["image_url"],
        {**COLLECTIBLE_TMNT["total"]["token_instance"]["metadata"],
         "rarity": "Common"})            # ancienne metadata (fausse rarete)
    recent = COLLECTIBLE_TMNT           # block 56705921 > 100
    cat = v3.collapse([vieux, recent])
    assert cat[TMNT_UUID]["rarity"] == "ULTRA_RARE"   # le recent gagne
    cat2 = v3.collapse([recent, vieux])               # ordre inverse
    assert cat2[TMNT_UUID]["rarity"] == "ULTRA_RARE"


# --- construction + report off-chain ----------------------------------------

def test_construire_reporte_offchain():
    cat = v3.collapse([COLLECTIBLE_TMNT, COMIC_STARWARS])
    rows = v3.construire_v3(cat, OFFICIEL)
    assert all(len(r) == len(v3.ENTETE) for r in rows)

    t = _row(rows, TMNT_UUID)
    d = dict(zip(v3.ENTETE, t))
    assert d["series_uuid"] == "93b9e171-1310-4914-b468-b659f1a554c0"  # reporte
    assert d["first_public"] == "21"        # reporte (NUMERO, pas dropDate)
    assert d["listings"] == "27"
    assert d["atl"] == "29" and d["ath_date"] == "2026-07-05"
    assert d["supply"] == 487
    assert d["brand"] == "Teenage Mutant Ninja Turtles"

    s = dict(zip(v3.ENTETE, _row(rows, SW_UUID)))
    assert s["series_uuid"] == "edb6d1ba-8aab-446c-a70f-fcf557bdbbfd"
    assert s["name"] == "Star Wars Vol. 4 #4 (2025)"
    assert s["edition_type"] == "4"
    assert s["atl"] == "18"


def test_item_hors_officiel_sans_prix():
    """Un item on-chain absent de l'officiel : identite OK, off-chain vide."""
    cat = v3.collapse([COLLECTIBLE_TMNT])
    rows = v3.construire_v3(cat, {})          # aucun officiel
    d = dict(zip(v3.ENTETE, rows[0]))
    assert d["name"] == "Donatello - IncogNinja"
    assert d["series_uuid"] == "" and d["first_public"] == "" and d["atl"] == ""


def test_accumulation_conserve_les_types_absents(tmp_path):
    """Un run qui ne revoit qu'un item ne doit pas reperdre l'autre (graine)."""
    graine = tmp_path / "elements_v3.csv"
    rows_prec = v3.construire_v3(v3.collapse([COMIC_STARWARS]), OFFICIEL)
    v3.ecrire(rows_prec, str(graine))                       # run precedent : le comic
    rows_now = v3.construire_v3(v3.collapse([COLLECTIBLE_TMNT]), OFFICIEL)  # run courant : le collectible
    fusion = v3._accumuler(rows_now, str(graine))
    uids = {r[0] for r in fusion}
    assert SW_UUID in uids and TMNT_UUID in uids           # les deux survivent


class _FauxCC:
    """Faux client chaine : sert `pages` pages puis du vide. Permet de tester
    l'arret-couverture de harvest() sans reseau."""
    TRANSFERS_URL = "x"
    PAUSE_BETWEEN_PAGES = 0
    def __init__(self, pages):
        self._pages = list(pages)
        self._i = 0
    def _session(self):
        return None
    def _parse_ts(self, x):
        return None                       # jamais avant cutoff (cutoff ignore)
    def _get(self, session, url, params):
        if self._i >= len(self._pages):
            return {"items": []}
        page = self._pages[self._i]
        self._i += 1
        nxt = {"p": self._i} if self._i < len(self._pages) else None
        return {"items": page, "next_page_params": nxt}


def test_harvest_arret_sur_plateau():
    import datetime as _dt
    # page 0 : le collectible (1 nouveau type) ; puis 5 pages qui REVOIENT le
    # meme item (0 nouveau). Plateau=3 -> doit s'arreter avant d'epuiser.
    p_new = [COLLECTIBLE_TMNT]
    p_repeat = [COLLECTIBLE_TMNT]
    cc = _FauxCC([p_new] + [p_repeat] * 5)
    cat = v3.harvest(cc, _dt.datetime(2000, 1, 1), plateau_pages=3)
    assert TMNT_UUID in cat
    assert cc._i <= 4        # arrete au plateau, n'a pas lu les 6 pages


def test_harvest_arret_sur_budget_temps_et_flush(tmp_path):
    """Deadline dans le passe -> arret propre au 1er tour ; le flush a bien
    sauvegarde le partiel (garantie anti-timeout)."""
    import datetime as _dt, time as _time
    cc = _FauxCC([[COLLECTIBLE_TMNT]] * 50)     # bien plus que ce qu'on lira
    flushes = []
    def flush(best):
        flushes.append(len(best))
    cat = v3.harvest(cc, _dt.datetime(2000, 1, 1), plateau_pages=0,
                     deadline=_time.monotonic() - 1,   # deja depassee
                     flush=flush, flush_every=1)
    assert TMNT_UUID in cat          # ce qui a ete vu est conserve
    assert cc._i <= 2                # arret quasi immediat, pas les 50 pages
    assert flushes and flushes[0] >= 1   # le flush de secours a tourne


def test_comic_supply_max_par_serie():
    """Deux couvertures de la meme serie : supply = MAX (regle v1/v2)."""
    c1 = COMIC_STARWARS
    c2 = _transfer(
        56705926, 0, "x/comic_cover."
        "11111111-1111-1111-1111-111111111111.b.full.webp",
        {"comicNumber": "5", "series": "Star Wars Vol. 4", "startYear": 2025,
         "publisher": "Marvel", "rarity": "Common", "totalEditions": 3000})
    rows = v3.construire_v3(v3.collapse([c1, c2]), {})
    for r in rows:
        assert dict(zip(v3.ENTETE, r))["supply"] == 3000   # MAX de la serie (repli libelle)


def test_comic_supply_groupe_par_series_uuid_officiel():
    """Deux comics au MEME libelle chaine mais series_uuid officiels DIFFERENTS
    ne doivent PAS fusionner (sinon MAX gonfle : le bug 30000 vs 7500 du 23/07)."""
    a = _transfer(1, 0, "x/comic_cover."
                  "aaaaaaaa-0000-0000-0000-000000000001.z.full.webp",
                  {"comicNumber": "1", "series": "Amazing Spider-Man Vol. 1",
                   "publisher": "Marvel", "rarity": "Common", "totalEditions": 7500})
    b = _transfer(2, 0, "x/comic_cover."
                  "bbbbbbbb-0000-0000-0000-000000000002.z.full.webp",
                  {"comicNumber": "9", "series": "Amazing Spider-Man Vol. 1",
                   "publisher": "Marvel", "rarity": "Common", "totalEditions": 30000})
    off = {"aaaaaaaa-0000-0000-0000-000000000001": {"series_uuid": "SERIE-A"},
           "bbbbbbbb-0000-0000-0000-000000000002": {"series_uuid": "SERIE-B"}}
    rows = v3.construire_v3(v3.collapse([a, b]), off)
    d = {r[0]: dict(zip(v3.ENTETE, r)) for r in rows}
    assert d["aaaaaaaa-0000-0000-0000-000000000001"]["supply"] == 7500   # pas 30000
    assert d["bbbbbbbb-0000-0000-0000-000000000002"]["supply"] == 30000
