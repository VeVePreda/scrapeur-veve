# Scrapeur VeVe → Google Sheet

Exporte l'intégralité du catalogue VeVe (~18 700 fiches produits) dans un Google Sheet,
met à jour le catalogue **chaque jour**, et **retrace l'historique du floor price** au fil
du temps. Tourne gratuitement sur **GitHub Actions** — aucun PC à laisser allumé.

---

## ⭐ Architecture v5 (2026-07-07) — froid vs dynamique

Le Sheet sépare désormais les **données froides** (qui ne varient pas dans le temps :
identité, rareté, série/brand/licensor, description, drop method, fee…) des **données
dynamiques** (floor, listings, offre, éditions vendues/brûlées…).

**Onglets :**

| Onglet | Contenu | Rythme |
|---|---|---|
| `🔵C-COLLECTIBLE` | Catalogue **froid** collectibles (1 ligne/produit). | 1×/jour, ajoute les nouveaux drops |
| `🟢C-COMICS` | Catalogue **froid** comics. | 1×/jour |
| `Marques & Licences` | Référentiel : 1 ligne par **marque** et par **licence**, avec compteurs produits. Reconstruit chaque jour. | 1×/jour |
| `Données Dynamiques` | Instantané **combiné** (collectibles + comics) des champs variables. 1 ligne/produit, écrasée à chaque run. | collectibles toutes les 3 h ; comics 1×/jour (1ʳᵉ semaine) |
| `PriceHistory` | Historique du floor (collectibles), append-only sur changement. | à chaque run dynamique |
| `EditionsHistory` | Historique des compteurs d'éditions, append-only sur changement. | à chaque run dynamique |
| `Logs` | Journal unifié (source `catalogue` / `dynamic` / `chain` / `pseudos`). | à chaque run |
| `Chain*` / `DropRevenue` | Activité on-chain CollectChain (voir plus bas). | 1×/jour |

**Colonnes froides — collectibles :** `veve_uuid, name, category, edition_type, rarity,
releaseDate, daily_mcp_points, gemsPerMcp, veve_series_name, series_uuid, veve_brand,
brand_uuid, veve_licensor, licensor_uuid, veve_url, image_url, tracker_uuid, description,
special_edition, market_fee, first_available_edition, is_blindbox, drop_method`
(+ suivi : `veve_enriched_at, first_seen, last_seen`).

**Colonnes froides — comics :** idem sans `special_edition`/`is_blindbox`, avec en plus
`noMarketListing` et `start_year` (`edition_type` conservé même s'il est souvent vide côté
comics).

**Page dynamique (combinée) :** `veve_uuid, name, category, market_lowestOffer,
market_totalListings, releaseAmount, veve_total_available, veve_store_price, sold_editions,
editions_in_circulation, burned_editions, withheld_editions, store_allocation, updated_at`.

**À noter :**
- **`market_fee` en %** : VeVe renvoie des dixièmes de pourcent (85 → **8,5 %**). Conversion
  centralisée dans `sheets.FEE_DIVISOR` (=10). *À confirmer contre le vrai taux VeVe ; si
  l'échelle diffère, changer cette seule constante.*
- **`market_lowestOffer` (floor)** a été **ajouté** à la page dynamique (non listé dans la
  demande) car c'est la métrique de prix clé et elle sert à alimenter `PriceHistory`.
  Supprimable si non voulu (retirer de `DYNAMIC_HEADER`).
- Colonnes **supprimées** (doublons ou déplacées) : `edition, storePrice, availableAmount,
  drop_date, rarity_editions, series_name, brand_name, licensor_name, veve_comic_name,
  season`. Colonnes **déduites ailleurs** (autre Sheet) et donc retirées : `allTimeLow,
  allTimeHigh, change_1d/7d/30d_pct`.
- **Plus de formatage couleur des raretés** (règles de mise en forme conditionnelle
  supprimées à chaque run). Le **surlignage des drops à venir** est conservé (bleu =
  collectibles, vert = comics).

**Workflows :**
- `daily-scrape.yml` — catalogues froids + Marques (fenêtre nouveautés), 04:11 UTC.
- `dynamic-collectibles.yml` — page dynamique collectibles, **toutes les 3 h** par défaut.
  ⚠️ **Budget minutes GitHub** (2 000 min/mois gratuites en repo privé) : toutes les 3 h ≈
  1 200 min/mois (OK) ; horaire ≈ 3 600 min/mois (dépasse → minutes payantes). Régler le
  `cron` dans le workflow (ex. `17 5,17 * * *` pour 2×/jour).
- `chain-daily.yml` — CollectChain, **journées complètes uniquement** (la journée en cours
  n'est jamais collectée ; elle est traitée le lendemain).

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

---

## Tracker on-chain CollectChain (collectscan.com)

Les collectibles/comics VeVe sont mint sur la blockchain **CollectChain**, explorable
via [collectscan.com](https://collectscan.com) (un Blockscout standard, API REST
publique `/api/v2`). Tout vit sur **un seul contrat ERC-721** :
`0xbcFEbA7A9dA14f5C9453bDA72E2098537867B3c7` (~706 000 holders).

**Reconnaissance collectible vs comic** : chaque transfert renvoyé par l'API embarque
les métadonnées du NFT (nom, rareté, série, brand, edition #) et une URL d'image
`collectible_type_image.<UUID>…` ou `comic_cover.<UUID>…`. Le préfixe donne la
catégorie, et l'UUID permet de **joindre le catalogue** du scraper (`veve_uuid`).

**Types de transferts** : `from = 0x0000…` → **mint** (drop) ; `to = 0x0000…` →
**burn** ; sinon → **marché** (wallet → wallet). Un compte est « actif » s'il a
**envoyé OU reçu** un NFT dans la période.

### Onglets ajoutés au Sheet

| Onglet | Contenu |
|---|---|
| `ChainStats` | **Le résultat principal** : pour 24h / 7j / 30j × (tout / mints / marché) × (tout / collectibles / comics) : nb de transferts NFT, **comptes uniques actifs**, **tx par compte**. Réécrit à chaque run. |
| `ChainTopAccounts` | Top 20 wallets les plus actifs par fenêtre, avec lien collectscan. |
| `ChainActivity` | Détail : 1 ligne par (jour, compte) avec compteurs mint / marché-in / marché-out / burn, séparés collectibles vs comics. Fenêtre glissante ~35 jours (purge auto). |
| `ChainItems` | **Quoi** exactement : 1 ligne par (jour, item) — nom, rareté, série, UUID — avec mints / ventes marché / burns et wallets uniques (minters, acheteurs, vendeurs). Fenêtre glissante ~35 jours. |
| `DropRevenue` | **Revenus estimés par drop** : par item, mints 24h/7j/30j × prix store du Catalogue = revenu estimé, + activité marché. Trié par revenu 30j. Colonne `match` = comment l'item a été relié au catalogue (`uuid` / `image` / `name` / `none`). |
| `RevenueSummary` | Totaux : mints et revenus estimés par fenêtre × catégorie. |
| `ChainMeta` | Checkpoint (dernier bloc traité) + totaux globaux de la chaîne. |
| `ChainRunLog` | Une ligne par run : confirmation que ça a marché. |

### Mise en route
1. **Backfill (une fois)** : Actions → **"CollectChain backfill (manual)"** → Run
   workflow (31 jours par défaut). ~5 500 tx/jour → ~165 000 transferts, comptez
   **30-60 min**.
2. **Quotidien** : le workflow **"CollectChain daily activity sync"** tourne à
   04:40 UTC, ne récupère que les nouveaux transferts depuis le checkpoint
   (~2-5 min), met à jour `ChainActivity` et recalcule `ChainStats`.

### Estimation des revenus de drop
`revenu estimé = mints on-chain × storePrice du catalogue`. Le join se fait par
**UUID** (l'UUID dans l'URL d'image on-chain = `veve_uuid` du catalogue — vérifié),
sinon par l'UUID de l'`image_url` enrichie, sinon par (nom + n° + rareté).
C'est une **estimation** : les paiements en gems, promos et claims gratuits sont
comptés au prix store ; les drops gratuits (storePrice 0) comptent 0.

### Notes
- Les fenêtres 24h/7j/30j sont à **granularité jour** (jours calendaires UTC).
- Un « transfert » = un mouvement de NFT. Un achat wallet→wallet compte pour
  **1 transfert** mais rend **2 comptes actifs** (vendeur + acheteur).
- Les rares NFTs sans métadonnées (mints très frais) sont comptés avec les
  collectibles (`category=unknown` en interne).
- Test local : `python -m scraper.collectchain --test` (2 dernières heures,
  sans écrire dans le Sheet).

---

## Pseudos VeVe ↔ wallets (stackr.world)

[StackR](https://www.stackr.world/) est la place de marché OMI officielle : chaque compte
StackR est **lié à un compte VeVe**, ce qui permet de relier une **adresse wallet** (celle
des onglets `Chain*`) au **pseudo VeVe**. Le module `scraper/stackr.py` interroge l'API
tRPC de StackR (`/api/trpc/…`) et maintient l'onglet **`Pseudos`**.

### Onglet `Pseudos`

| Colonne | Contenu |
|---|---|
| `username` | pseudo VeVe (vide si pas encore découvert) |
| `wallet_imx` | wallet VeVe historique (IMX → CollectChain) — **c'est lui qui apparaît dans `ChainActivity` / `ChainTopAccounts`**, jointure directe |
| `wallet_stackr` | smart wallet StackR (Base) utilisé pour payer en OMI |
| `veve_user_id` | UUID interne VeVe |
| `status` | `ok` (pseudo trouvé) / `no_username` (compte trouvé, pseudo pas encore vu) / `not_found` (wallet sans compte StackR) |
| `source` | `leaderboard`, `ranking`, `chain` ou `transactions` |

### Comment les pseudos sont trouvés (4 sources par run)
1. **Leaderboards** top holders (public, sans session) : wallet + pseudo directs.
2. **Classement OMI rewards** (paginé, mois courant + précédent) : pseudos garantis.
3. **Wallets CollectChain** les plus actifs (`ChainActivity`) encore inconnus :
   résolution individuelle via `getPublicUser`, puis recherche du pseudo dans les
   **listings** puis les **ventes** du compte.
4. **Contreparties** des ventes rencontrées en chemin (pseudo garanti).

Le mapping **s'enrichit au fil des jours** : chaque run consomme un budget de
`STACKR_MAX_LOOKUPS` appels (200 par défaut, ~2 min) avec une pause de politesse entre
chaque appel. Les wallets sans compte StackR sont re-testés après 30 jours, ceux sans
pseudo après 14 jours. Un run quotidien tourne à **05:10 UTC** (workflow
**"StackR pseudo sync"**) et se confirme dans **`PseudoRunLog`**.

### Notes
- L'API `verifiedVeve.*` exige un **cookie de session anonyme** (obtenu automatiquement
  en visitant la home). Si StackR durcit ce point, le run continue en mode dégradé
  (leaderboards uniquement) et le note dans `PseudoRunLog` (`verifiedVeve=OFF`).
- Seuls les collectionneurs **ayant lié leur compte VeVe à StackR** sont résolubles :
  un wallet `not_found` peut très bien être un utilisateur VeVe sans compte StackR.
- Test local : `python -m scraper.stackr --test` (moissonne les leaderboards + quelques
  résolutions, n'écrit rien dans le Sheet).
- Réglages : `STACKR_MAX_LOOKUPS`, `STACKR_RANKING_PAGES` (pages de classement par
  période, 3 par défaut), `STACKR_PAUSE` (0.35 s par défaut).
