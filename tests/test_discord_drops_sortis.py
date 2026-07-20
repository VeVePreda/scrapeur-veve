# ⚠️ DEPOT : VeVePreda/scrapeur-veve   ·   CHEMIN : tests/test_discord_drops_sortis.py
# Le projet vit sur 6 depots et DEUX comptes GitHub. Un fichier
# depose au mauvais endroit ne provoque aucune erreur : il dort.

"""Le marquage « drop sorti » — teste A SEC, sans Discord ni Sheet.

Le module ne fait aucun acces reseau lui-meme : il recoit `lire` et
`editer`. C'est ce qui permet de verifier ici les cas qui, en production,
n'arrivent qu'une fois tous les six mois — le message supprime a la main,
l'edition refusee, l'etat perdu.

A deposer dans `tests/` du depot scrapeur-veve.
"""
import unittest

from scraper import discord_drops_sortis as ds

MENTIONS = {"parse": []}
MAINTENANT = 1_800_000_000.0
HIER = MAINTENANT - 86400
DEMAIN = MAINTENANT + 86400


class FauxDiscord:
    """Un salon en memoire : {mid: message}."""

    def __init__(self, messages=None, refuser=False, illisibles=()):
        self.messages = messages or {}
        self.refuser = refuser
        self.illisibles = set(illisibles)
        self.editions = []

    def lire(self, mid):
        if mid in self.illisibles:
            return None
        return self.messages.get(mid)

    def editer(self, mid, payload):
        self.editions.append((mid, payload))
        if self.refuser:
            return None
        self.messages[mid] = {"content": payload["content"],
                              "embeds": payload.get("embeds")}
        return mid


def carte(contenu="🔵 **Spider-Man**\n🕗 Drop date: **<t:1:F>** 🕗",
          couleur=0x1F8BF0):
    return {"content": contenu,
            "embeds": [{"image": {"url": "http://x/i.png"}, "color": couleur,
                        "url": "http://veve/serie"}]}


class TestEstPasse(unittest.TestCase):
    def test_hier_est_passe(self):
        self.assertTrue(ds.est_passe(HIER, MAINTENANT))

    def test_demain_ne_l_est_pas(self):
        self.assertFalse(ds.est_passe(DEMAIN, MAINTENANT))

    def test_pile_a_l_heure_compte_comme_passe(self):
        self.assertTrue(ds.est_passe(MAINTENANT, MAINTENANT))

    def test_une_date_absente_ne_marque_RIEN(self):
        # Dans le doute on ne marque pas : marquer a tort une carte a venir
        # ferait croire le drop passe, et on ne le regarderait plus.
        for valeur in (None, "", "bientot", [], {}):
            with self.subTest(valeur=valeur):
                self.assertFalse(ds.est_passe(valeur, MAINTENANT))

    def test_un_timestamp_en_texte_est_accepte(self):
        self.assertTrue(ds.est_passe(str(int(HIER)), MAINTENANT))


class TestContenu(unittest.TestCase):
    def test_la_marque_est_en_tete(self):
        rendu = ds.contenu_marque("Spider-Man")
        self.assertTrue(rendu.startswith(ds.MARQUE))
        self.assertIn("Spider-Man", rendu)

    def test_marquer_deux_fois_n_empile_pas(self):
        une = ds.contenu_marque("Spider-Man")
        self.assertEqual(ds.contenu_marque(une), une)

    def test_un_contenu_deja_a_la_limite_ne_deborde_pas(self):
        # Discord refuse au-dela de 2000 : un message refuse, c'est une
        # carte qui perd son texte.
        rendu = ds.contenu_marque("x" * 2000)
        self.assertLessEqual(len(rendu), ds.MAX_CONTENU)
        self.assertTrue(rendu.startswith(ds.MARQUE))

    def test_un_contenu_vide_ne_casse_rien(self):
        self.assertTrue(ds.contenu_marque("").startswith(ds.MARQUE))
        self.assertTrue(ds.contenu_marque(None).startswith(ds.MARQUE))


class TestEmbeds(unittest.TestCase):
    def test_la_couleur_passe_au_gris(self):
        sortie = ds.embeds_gris([{"color": 0x1F8BF0}])
        self.assertEqual(sortie[0]["color"], ds.GRIS)

    def test_l_illustration_et_le_lien_survivent(self):
        entree = [{"image": {"url": "http://x/i.png"}, "url": "http://veve/s",
                   "color": 1}]
        sortie = ds.embeds_gris(entree)
        self.assertEqual(sortie[0]["image"], {"url": "http://x/i.png"})
        self.assertEqual(sortie[0]["url"], "http://veve/s")

    def test_l_original_n_est_pas_modifie(self):
        entree = [{"color": 123}]
        ds.embeds_gris(entree)
        self.assertEqual(entree[0]["color"], 123)

    def test_sans_embed(self):
        self.assertEqual(ds.embeds_gris(None), [])


class TestPayload(unittest.TestCase):
    def test_l_edition_renvoie_TOUJOURS_les_embeds(self):
        # Une edition Discord REMPLACE : n'envoyer que le contenu ferait
        # disparaitre l'illustration.
        charge = ds.payload("x", [{"color": 1}], MENTIONS)
        self.assertIn("embeds", charge)

    def test_aucune_mention_n_est_reparsee(self):
        # Une carte reecrite ne doit pas re-sonner.
        charge = ds.payload("<@&123> coucou", None, MENTIONS)
        self.assertEqual(charge["allowed_mentions"], {"parse": []})


class TestAMarquer(unittest.TestCase):
    def test_seuls_les_drops_passes_sortent(self):
        cibles = ds.a_marquer({"a": "1", "b": "2"},
                              {"a": HIER, "b": DEMAIN}, [],
                              maintenant=MAINTENANT)
        self.assertEqual(cibles, [("a", "1")])

    def test_une_cle_deja_marquee_est_ignoree(self):
        cibles = ds.a_marquer({"a": "1"}, {"a": HIER}, ["a"],
                              maintenant=MAINTENANT)
        self.assertEqual(cibles, [])

    def test_une_cle_sans_date_est_ignoree_sans_bruit(self):
        # La serie a pu sortir du catalogue : ce n'est pas une anomalie.
        cibles = ds.a_marquer({"a": "1"}, {}, [], maintenant=MAINTENANT)
        self.assertEqual(cibles, [])

    def test_les_simulations_ne_sont_jamais_editees(self):
        cibles = ds.a_marquer({"a": "simulation"}, {"a": HIER}, [],
                              maintenant=MAINTENANT)
        self.assertEqual(cibles, [])

    def test_le_plafond_est_tenu(self):
        messages = {f"c{i}": str(i) for i in range(20)}
        dates = {f"c{i}": HIER for i in range(20)}
        cibles = ds.a_marquer(messages, dates, [], maintenant=MAINTENANT,
                              plafond=5)
        self.assertEqual(len(cibles), 5)


class TestMarquer(unittest.TestCase):
    def setUp(self):
        self.dis = FauxDiscord({"m1": carte(), "m2": carte()})
        self.state = {}
        self.muet = lambda *_: None

    def lancer(self, messages, dates, **kw):
        kw.setdefault("maintenant", MAINTENANT)
        return ds.marquer(messages, dates, self.state, self.dis.lire,
                          self.dis.editer, MENTIONS, journal=self.muet, **kw)

    def test_une_carte_passee_est_marquee_et_grisee(self):
        n = self.lancer({"a": "m1"}, {"a": HIER})
        self.assertEqual(n, 1)
        self.assertTrue(self.dis.messages["m1"]["content"].startswith(ds.MARQUE))
        self.assertEqual(self.dis.messages["m1"]["embeds"][0]["color"], ds.GRIS)
        self.assertEqual(self.state["sortis"], ["a"])

    def test_une_carte_a_venir_n_est_pas_touchee(self):
        self.assertEqual(self.lancer({"a": "m1"}, {"a": DEMAIN}), 0)
        self.assertEqual(self.dis.editions, [])

    def test_deux_runs_ne_marquent_qu_une_fois(self):
        self.lancer({"a": "m1"}, {"a": HIER})
        self.lancer({"a": "m1"}, {"a": HIER})
        self.assertEqual(len(self.dis.editions), 1)

    def test_meme_avec_un_etat_PERDU_on_ne_remarque_pas(self):
        # Le vrai garde-fou : l'etat peut etre reconstruit, la carte non.
        self.lancer({"a": "m1"}, {"a": HIER})
        self.state = {}
        self.lancer({"a": "m1"}, {"a": HIER})
        self.assertEqual(self.dis.messages["m1"]["content"].count(ds.MARQUE), 1)

    def test_une_edition_REFUSEE_ne_note_rien(self):
        # Une marque manquante se rattrape au run suivant ; une cle notee a
        # tort ne se rattrape jamais.
        self.dis.refuser = True
        self.assertEqual(self.lancer({"a": "m1"}, {"a": HIER}), 0)
        self.assertEqual(self.state["sortis"], [])

    def test_un_message_supprime_a_la_main_est_note_comme_traite(self):
        # Sinon on le retenterait a chaque run jusqu'a la fin des temps.
        self.dis.illisibles = {"m1"}
        self.lancer({"a": "m1"}, {"a": HIER})
        self.assertEqual(self.state["sortis"], ["a"])
        self.assertEqual(self.dis.editions, [])

    def test_une_carte_qui_plante_n_empeche_pas_les_autres(self):
        def lire_capricieux(mid):
            if mid == "m1":
                raise RuntimeError("boum")
            return carte()
        n = ds.marquer({"a": "m1", "b": "m2"}, {"a": HIER, "b": HIER},
                       self.state, lire_capricieux, self.dis.editer,
                       MENTIONS, journal=self.muet, maintenant=MAINTENANT)
        self.assertEqual(n, 1)
        self.assertEqual(self.state["sortis"], ["b"])

    def test_ON_PARLE_MEME_QUAND_ON_NE_FAIT_RIEN(self):
        # Sans cette ligne, « il a tourne et n'avait rien a faire » et « il
        # n'est pas installe » donnent la meme sortie : du silence.
        dits = []
        ds.marquer({"a": "m1"}, {"a": DEMAIN}, self.state, self.dis.lire,
                   self.dis.editer, MENTIONS, journal=dits.append,
                   maintenant=MAINTENANT)
        self.assertTrue(dits, "le module doit toujours dire ce qu'il a vu")
        self.assertIn("1 carte(s) connue(s)", dits[0])
        self.assertIn("0 a traiter", dits[0])

    def test_un_etat_vide_explique_pourquoi(self):
        dits = []
        ds.marquer({}, {}, self.state, self.dis.lire, self.dis.editer,
                   MENTIONS, journal=dits.append, maintenant=MAINTENANT)
        self.assertIn("0 carte(s) connue(s)", dits[0])
        self.assertIn("prochains drops", " ".join(dits))

    def test_rien_a_faire_ne_coute_aucun_appel(self):
        appels = []
        ds.marquer({"a": "m1"}, {"a": DEMAIN}, self.state,
                   lambda m: appels.append(m), self.dis.editer, MENTIONS,
                   journal=self.muet, maintenant=MAINTENANT)
        self.assertEqual(appels, [])

    def test_le_souffle_est_respecte_entre_deux_editions(self):
        souffles = []
        ds.marquer({"a": "m1", "b": "m2"}, {"a": HIER, "b": HIER},
                   self.state, self.dis.lire, self.dis.editer, MENTIONS,
                   souffler=lambda: souffles.append(1), journal=self.muet,
                   maintenant=MAINTENANT)
        self.assertEqual(len(souffles), 2)

    def test_l_etat_ne_gonfle_pas_indefiniment(self):
        self.state["sortis"] = [f"vieux{i}" for i in range(500)]
        self.lancer({"a": "m1"}, {"a": HIER})
        self.assertLessEqual(len(self.state["sortis"]), 400)
        self.assertIn("a", self.state["sortis"], "la plus recente est gardee")

    def test_une_carte_deja_marquee_a_la_main_est_reconnue(self):
        self.dis.messages["m1"] = carte(f"{ds.MARQUE}\nSpider-Man")
        self.assertEqual(self.lancer({"a": "m1"}, {"a": HIER}), 0)
        self.assertEqual(self.dis.editions, [])
        self.assertEqual(self.state["sortis"], ["a"])


if __name__ == "__main__":
    unittest.main()
