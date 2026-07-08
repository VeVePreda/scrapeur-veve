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
