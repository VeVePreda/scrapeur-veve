# Scrapeur VeVe → Google Sheet

Exporte l'intégralité du catalogue VeVe (~18 700 fiches produits) dans un Google Sheet,
met à jour le catalogue **chaque jour**, et **retrace l'historique du floor price** au fil
du temps. Tourne gratuitement sur **GitHub Actions** — aucun PC à laisser allumé.

---

## Comment ça marche

Le site VeVe est protégé par Cloudflare (403 aux robots) et son API GraphQL n'accepte que
des *persisted queries* : impossible à scraper directement. La solution passe par
**my-nft-tracker.com**, un tracker communautaire qui agrège tout le catalogue VeVe et
l'expose via une **API REST publique** :

```
https://my-nft-tracker-backend.azurewebsites.net/api/Nfts
```

Le scraper pagine cette API (pas de navigateur, pas de proxy). Chaque produit revient en
JSON structuré : nom, edition, catégorie, rareté, date de sortie, quantités mint/dispo,
prix store, floor marché, série, brand, licensor, images, et l'UUID VeVe
(`externalReference`) pour le lien direct vers la fiche.

---

## Deux onglets dans le Sheet

### `Catalogue` — snapshot courant
Une ligne par produit (dédupliqué par `veve_uuid`). Colonnes clés en tête : `name`,
`category`, `edition`, `rarity`, `releaseDate`, `releaseAmount`, `availableAmount`,
`storePrice`, `market_lowestOffer` (floor actuel), `allTimeLow`, `allTimeHigh`,
`series_name`, `brand_name`, `licensor_name`, `veve_url`, `image_url`. Deux colonnes de
suivi : `first_seen` (première détection — les nouveautés remontent en haut) et `last_seen`.

### `PriceHistory` — historique du floor (append-only)
À chaque run, pour chaque produit ayant un floor marché, une ligne est ajoutée
**uniquement si le floor a changé** depuis le dernier run (ou à la première détection).
Colonnes : `snapshot_date`, `veve_uuid`, `name`, `category`, `floor`, `storePrice`,
`totalListings`. Tu obtiens ainsi la courbe du floor par produit, sans gonfler le Sheet
avec des valeurs identiques.

> Pour tracer un graphe : filtre `PriceHistory` sur un `veve_uuid`, puis trace `floor`
> en fonction de `snapshot_date`.

---

## Mise en place (une seule fois)

Le code est déjà dans ton repo GitHub. Il reste **2 secrets à ajouter** puis à lancer.

### 1. Partager le Google Sheet (déjà fait ✅)
Service account partagé en Éditeur :
`scrapeur-veve@scraper-veve.iam.gserviceaccount.com`

### 2. Ajouter les secrets GitHub
Repo → **Settings → Secrets and variables → Actions → New repository secret** :

| Nom du secret                  | Valeur                                                    |
|--------------------------------|-----------------------------------------------------------|
| `GOOGLE_SERVICE_ACCOUNT_JSON`  | Le contenu **complet** du fichier JSON du service account |
| `SHEET_ID`                     | `1YMsK90zwxdmRuYiThVcDsJ2re_Rx_Nz1v5KlLGxnUHA`           |

> ⚠️ La clé du service account ne doit jamais être committée : elle vit uniquement dans
> les secrets GitHub (chiffrés).

### 3. Lancer
Onglet **Actions** → workflow **"VeVe daily catalogue sync"** → **Run workflow**.
Les logs affichent `added=… updated=… total=… price_history_rows=…`. Ensuite le run est
**quotidien à 05:30 UTC**.

---

## Tester en local (optionnel)

```bash
pip install -r requirements.txt

# Test rapide (300 fiches, sans écrire dans le Sheet) :
python -m scraper.veve_scraper --test

# Run complet + écriture :
export GOOGLE_SERVICE_ACCOUNT_JSON="$(cat service_account.json)"
export SHEET_ID="1YMsK90zwxdmRuYiThVcDsJ2re_Rx_Nz1v5KlLGxnUHA"
python -m scraper.run
```

---

## Réglages

- **Heure du run** : ligne `cron` dans `.github/workflows/daily-scrape.yml`.
- **Taille de page / politesse** : `PAGE_SIZE`, `PAUSE_BETWEEN_PAGES` dans
  `scraper/veve_scraper.py`.
- **Catégorie** : `scrape_catalogue(category="comic")` / `"collectible"` ; `None` = tout.

---

## Notes & limites

- Source tierce (my-nft-tracker). Si son API change, ajuster `NFTS_URL` / le parsing.
- Si un run ne récolte aucun produit (API down), le script s'arrête **sans vider** le Sheet.
- Les prix sont indicatifs (fournis par le tracker), pas un conseil financier.

---

## Enrichissement VeVe (collectibles)

En plus des données my-nft-tracker, le pipeline récupère des champs **directement depuis
l'API GraphQL de VeVe** (`web.api.prod.veve.me`) pour les **collectibles et les comics**. Colonnes ajoutées :
`description`, `special_edition`, `edition_type`, `is_blindbox`, `season`, `drop_method`,
`drop_date`, `daily_mcp_points`, `market_fee`, `veve_store_price`, `rarity_editions`
(totalIssued), `editions_in_circulation`, `sold_editions`, `burned_editions`,
`withheld_editions`, `store_allocation`, `first_available_edition`, `veve_series_name`,
`veve_brand`, `veve_licensor`, `veve_enriched_at`.

**Comment :** l'API VeVe est appelable directement (en-têtes maison faisant office de jeton
CSRF ; ni navigateur ni cookies). Par défaut le job quotidien enrichit seulement les
**nouveaux** collectibles (`ENRICH_MODE=new`).

### Premier remplissage (backfill) — à faire une fois
Onglet **Actions → "VeVe enrichment backfill (manual)" → Run workflow** (mode `all`).
Ça enrichit les ~2 630 collectibles existants (quelques minutes). Tu peux le relancer
quand tu veux pour rafraîchir les compteurs dynamiques (sold/circulation/burned).

### Egress via proxy résidentiel Apify (optionnel)
Si tu ajoutes le secret **`APIFY_PROXY_PASSWORD`** (Apify Console → Proxy → mot de passe),
les appels VeVe passent par le proxy résidentiel Apify (robustesse anti-blocage). Sans ce
secret, les appels partent en direct (fonctionne aussi). Réglé par `ENRICH_MODE` /
`APIFY_PROXY_PASSWORD`, aucun changement de code.

### Comics — enrichis aussi ✅
Les comics utilisent un type VeVe distinct (`publicComicType`). La clé du mapping :
**l'id VeVe d'un comic = `series.externalReference` du tracker** (colonne `series_uuid`).
Un comic regroupe toutes ses raretés sous un seul id ; on enrichit donc une fois par
comic (~4 200 comics uniques) et on applique les champs au niveau comic à chaque ligne
de rareté. Colonnes récupérées : `description` (synopsis complet, mentionne souvent les
variantes par rareté), `market_fee`, `daily_mcp_points`, `drop_method`, `drop_date`,
`start_year`, `rarity_editions` (total du comic), `editions_in_circulation`,
`sold_editions`, `burned_editions`, `withheld_editions`, `first_available_edition`,
`veve_comic_name`.

> Note : pour les comics, les compteurs d'éditions sont au **niveau comic** (somme de
> toutes les raretés). Le détail par rareté (release/available) reste fourni par le
> tracker (`releaseAmount` / `availableAmount`).

### Blind Box Odds
Non exposé comme champ par l'API VeVe. Pour les comics, la `description` mentionne
souvent les variantes/raretés en texte libre.

---

## Confort & robustesse (mise à jour)

### Horaire
Le job tourne à **04:00 UTC = 06:00 en France l'été** (CEST). En hiver (CET) ce sera 05:00
en France — GitHub ne gère que l'UTC, il ne suit pas le changement d'heure automatiquement.
Pour forcer 06:00 en hiver, mets `cron: "0 5 * * *"`.

### Onglet `RunLog` — confirmation quotidienne
Chaque run ajoute une ligne : date, **statut**, nombre de lignes, **nouveaux produits**
(collectibles / comics), drops à venir cette semaine, lignes d'historique ajoutées, et les
**noms des nouveautés**. C'est ta confirmation que tout a fonctionné et ce qui a changé.
GitHub t'envoie aussi un e-mail automatiquement si un run **échoue**.

### Protection de tes données
- Le Sheet repart **toujours** des lignes existantes : rien n'est jamais supprimé, même si
  un produit disparaît du tracker ou si l'enrichissement échoue.
- Si my-nft-tracker est **en panne** (0 produit) ou renvoie une récolte **anormalement
  petite** (< 50 % de l'existant), le run **s'arrête sans réécrire** le Sheet et le note
  dans `RunLog` (`FAILED_NO_DATA` / `ABORTED_LOW_COUNT`). Tu ne perds rien.

### Onglet `EditionsHistory` — suivi des données variables
Les champs qui **évoluent** (`sold_editions`, `editions_in_circulation`, `burned_editions`,
`withheld_editions`, `veve_total_available`) sont rafraîchis **chaque jour** pour tout le
catalogue et historisés dans `EditionsHistory` **uniquement quand une valeur change**
(collectibles par produit, comics une fois par comic). Tu peux ainsi suivre et comparer
l'évolution dans le temps. Réglable via `REFRESH_DYNAMIC` (`true` par défaut).

### Surlignage des drops à venir (7 prochains jours)
Dans `Catalogue`, les produits qui sortent dans les 7 prochains jours sont surlignés :
**bleu clair = collectibles**, **vert clair = comics**. Le reste est remis en blanc à
chaque run.

---

## Architecture quotidienne allégée (v2)

Pour éviter de re-télécharger 18 680 fiches chaque jour (≈780 requêtes vers
my-nft-tracker), le run quotidien est désormais **incrémental et discret** :

1. **Fenêtre** : ne récupère que les **drops à venir + sortis dans les 8 derniers jours**
   (tri par date décroissante, on s'arrête dès qu'on dépasse la fenêtre). ~30-40 requêtes.
2. **Floor collectibles** : récupère le floor de **tous les collectibles** (~110 requêtes)
   pour alimenter `PriceHistory`.
3. **Nouveautés** : compare à ce qui est déjà dans le Sheet ; **seuls les nouveaux**
   produits sont enrichis depuis VeVe (description, etc.).
4. **Ventes / circulation** : rafraîchies **uniquement pour les items de leur première
   semaine** (≤ 8 jours), historisées dans `EditionsHistory` quand ça change.

Total : **~150 requêtes/jour** vers my-nft-tracker (au lieu de ~780), run de ~5-8 min.
Le **catalogue complet reste intact** dans le Sheet (rien n'est supprimé, on part toujours
des lignes existantes). Le **backfill complet** reste disponible à la demande
(*Actions → VeVe enrichment backfill → mode `all`*).

### Quotas GitHub
Repo **privé** = 2 000 min/mois gratuites (Free plan). Le run allégé consomme
~150-250 min/mois : large marge. Un repo **public** aurait des minutes **illimitées**.

### Suivis
- **`PriceHistory`** : floor, **collectibles uniquement**.
- **`EditionsHistory`** : `sold_editions` / `editions_in_circulation` / etc., **items de la
  première semaine uniquement** (collectibles + comics). `snapshot_date` inclut l'**heure**.

### Surlignage
Tous les **drops encore à venir** (date de sortie > maintenant) sont surlignés :
**bleu = collectibles**, **vert = comics**. Une fois la date passée, plus de surlignage.
