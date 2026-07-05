# Scrapeur VeVe → Google Sheet

Exporte l'intégralité du catalogue VeVe (~18 700 fiches produits) dans un Google Sheet,
puis le met à jour **automatiquement chaque jour** en ajoutant les nouveaux produits.

Tourne gratuitement sur **GitHub Actions** — aucun PC à laisser allumé.

---

## Comment ça marche

Le site VeVe lui-même est protégé par Cloudflare (il renvoie une erreur 403 aux robots)
et son API GraphQL n'accepte que des *persisted queries* pré-enregistrées : impossible
de le scraper directement.

La solution : **my-nft-tracker.com**, un tracker communautaire qui agrège déjà tout le
catalogue VeVe et l'expose via une **API REST publique, propre et non protégée** :

```
https://my-nft-tracker-backend.azurewebsites.net/api/Nfts
```

Le scraper pagine simplement cette API — pas de navigateur, pas de proxy, pas de lutte
anti-bot. Chaque produit revient en JSON structuré : nom, edition, catégorie, rareté,
date de sortie, quantités mint/dispo, prix store, série, brand, licensor, images, et
l'**UUID VeVe** (`externalReference`) qui permet de reconstruire le lien direct vers la
fiche VeVe. Au moment de l'écriture : **2 630 collectibles + 16 051 comics = 18 681 fiches**.

Chaque produit devient une ligne, dédupliquée par UUID VeVe. Colonnes clés :
`veve_uuid`, `name`, `category`, `edition`, `rarity`, `releaseDate`, `releaseAmount`,
`availableAmount`, `storePrice`, `market_lowestOffer`, `series_name`, `brand_name`,
`licensor_name`, `veve_url` (lien direct fiche VeVe), `image_url`, plus `first_seen` /
`last_seen` pour repérer les nouveautés.

---

## Mise en place (une seule fois, ~10 min)

### 1. Créer le repo GitHub
Crée un nouveau dépôt (privé de préférence) sur github.com, par ex. `scrapeur-veve`,
puis pousse ce dossier :

```bash
cd ScrapeurVeVe
git init
git add .
git commit -m "Scrapeur VeVe initial"
git branch -M main
git remote add origin https://github.com/<ton-compte>/scrapeur-veve.git
git push -u origin main
```

### 2. Partager le Google Sheet avec le service account
Le compte de service est :
```
scrapeur-veve@scraper-veve.iam.gserviceaccount.com
```
Ouvre ton Google Sheet → **Partager** → colle cette adresse → rôle **Éditeur**.
(Sans ça, le script ne pourra pas écrire.)

Ton Sheet actuel :
`https://docs.google.com/spreadsheets/d/1YMsK90zwxdmRuYiThVcDsJ2re_Rx_Nz1v5KlLGxnUHA/edit`
→ son **ID** est `1YMsK90zwxdmRuYiThVcDsJ2re_Rx_Nz1v5KlLGxnUHA`.

### 3. Ajouter les secrets GitHub
Dans le repo → **Settings → Secrets and variables → Actions → New repository secret**.
Crée deux secrets :

| Nom du secret                  | Valeur                                                        |
|--------------------------------|--------------------------------------------------------------|
| `GOOGLE_SERVICE_ACCOUNT_JSON`  | Le contenu **complet** du fichier JSON du service account    |
| `SHEET_ID`                     | `1YMsK90zwxdmRuYiThVcDsJ2re_Rx_Nz1v5KlLGxnUHA`               |

> ⚠️ La clé du service account ne doit **jamais** être committée dans le repo.
> Elle vit uniquement dans les secrets GitHub (chiffrés). Le `.gitignore` bloque
> déjà `service_account.json` par sécurité.

### 4. Lancer une première fois
Onglet **Actions** → workflow **"VeVe daily catalogue sync"** → **Run workflow**.
Regarde les logs : nombre de produits récoltés, puis `added=… updated=… total=…`.
Ton Sheet se remplit (~18 700 lignes, quelques minutes).

Ensuite ça tourne **tout seul chaque jour à 05:30 UTC** : nouveaux produits ajoutés,
anciens mis à jour.

---

## Le Google Sheet

Onglet **`Catalogue`**, une ligne par produit (dédupliqué par `veve_uuid`). Les lignes
sont triées par `first_seen` décroissant : **les nouveaux drops apparaissent en haut**.

- **`first_seen`** — date de première détection (trie/filtre dessus pour les nouveautés).
- **`last_seen`** — dernière fois vu lors d'un run.
- **`veve_url`** — lien cliquable vers la fiche VeVe officielle.

---

## Tester en local (optionnel)

```bash
pip install -r requirements.txt

# Test rapide sans toucher au Sheet (récupère ~300 fiches et affiche les colonnes) :
python -m scraper.veve_scraper --test

# Run complet + écriture dans le Sheet :
export GOOGLE_SERVICE_ACCOUNT_JSON="$(cat service_account.json)"
export SHEET_ID="1YMsK90zwxdmRuYiThVcDsJ2re_Rx_Nz1v5KlLGxnUHA"
python -m scraper.run
```

---

## Réglages

- **Heure du run** : ligne `cron` dans `.github/workflows/daily-scrape.yml`
  (`30 5 * * *` = 05:30 UTC ; format : minute heure jour mois jour-semaine).
- **Taille de page / politesse** : `PAGE_SIZE`, `PAUSE_BETWEEN_PAGES` en haut de
  `scraper/veve_scraper.py`.
- **Catégorie** : `scrape_catalogue(category="comic")` pour ne prendre que les comics,
  `"collectible"` pour les collectibles ; `None` (défaut) = tout.

---

## Notes & limites

- La source est my-nft-tracker (tiers). Si son API change de forme ou d'URL, il faudra
  ajuster `NFTS_URL` / le parsing dans `scraper/veve_scraper.py`.
- Si un run ne récolte **aucun** produit (API down), le script s'arrête **sans vider**
  le Sheet, pour ne pas perdre les données existantes.
- Les prix (`storePrice`, `market_lowestOffer`) sont fournis par le tracker à titre
  indicatif ; ce n'est pas un conseil financier.
- `externalReference` = l'UUID VeVe : il permet de croiser avec l'API/le site VeVe si
  besoin plus tard.
