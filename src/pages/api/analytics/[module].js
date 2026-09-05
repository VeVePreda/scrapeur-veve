// ⚠️ VeVePreda/veve-sites — src/pages/api/analytics/[module].js  (NEUF)
// ═══════════════════════════════════════════════════════════════════════════
// LES MODULES ABONNÉS D'ANALYTICS — servis à la demande, jamais pré-générés
// ═══════════════════════════════════════════════════════════════════════════
// 🔴 SANS `getStaticPaths()`, LE BUILD DE vevewiki CASSE — mesuré au lot 27 sur
// `/api/historique/[uuid]`, même cause : « GetStaticPathsRequired ». Une route
// dynamique pré-générée doit dire quels chemins générer.
// ⭐ ET LA RÉPONSE HONNÊTE EST « AUCUN ». En static il n'y a pas de serveur,
// donc pas de session, donc aucun palier : ces modules n'ont pas de sens.
// ⛔ NE PAS y mettre la liste des modules « pour que ça marche aussi en
// static » : ça écrirait dans `dist/` un JSON par module, servi en clair par
// nginx à qui connaît l'adresse. Ce serait vendre un accès à une donnée déjà
// donnée — la faute exacte que `/api/historique` refuse déjà.
export function getStaticPaths() { return []; }

// ⭐ LITTERAL, ET C'EST LE POINT. Astro exige que `prerender` soit statiquement
// analysable ; une EXPRESSION retombe silencieusement sur `true`. La valeur
// réelle est posée par l'intégration `veve:routes-compte`.
export const prerender = true;

import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { ANALYTICS_DIR } from '../../../../engine/lib/reserve_analytics.mjs';
import { SETS_MCP_FICHIER, TRIS_SETS, TRI_SETS_DEFAUT, classerSets }
  from '../../../../engine/lib/sets_mcp.mjs';
import { franchit, porte } from '../../../../engine/lib/access.mjs';

const ENTETES = {
  'content-type': 'application/json; charset=utf-8',
  'cache-control': 'private, no-store',
  'vary': 'cookie',
  'x-content-type-options': 'nosniff',
};

// ⛔ LE CORPS D'UN REFUS NE DIT JAMAIS CE QU'IL REFUSE. « module inconnu » et
// « pas abonné » doivent se ressembler vus du dehors, sinon la route devient un
// oracle qui énumère le contenu réservé par différence de message.
const refus = (code, cle) =>
  new Response(JSON.stringify({ ok: false, erreur: cle }), { status: code, headers: ENTETES });

// ⭐⭐ UNE LISTE BLANCHE, ET ELLE EST LA SEULE DÉFENSE QUI COMPTE.
// `params.module` compose un CHEMIN DE FICHIER. Sans elle,
// `/api/analytics/..%2f..%2fsites%2fveveprice%2fmanifest.yml` lit ce qu'il veut.
// ⛔ Ne jamais « nettoyer » le paramètre : une liste noire se contourne, une
// liste blanche non. C'est la même règle que `uuidValide()` de `reserve.mjs`.
// ⭐ Et elle porte AUSSI la porte de chaque module : le droit est une propriété
// du module, écrite à côté de lui, pas un test dispersé dans le code.
const MODULES = {
  pulse:       { fichier: 'pulse.json',       gate: 'modules' },
  wallet_size: { fichier: 'wallet_size.json', gate: 'modules' },
  whales:      { fichier: 'whales.json',      gate: 'wallet_watch' },
  corner_top:  { fichier: 'corner_top.json',  gate: 'modules' },
  // 🔴 `modules`, PAS un palier au-dessus. ⚠️ Ces agrégats ne portent AUCUNE
  // adresse — c'est ce qui les sépare de `whales`, seul module à exiger
  // `wallet_watch`.
  // ⚠️ LOT 194 (25/08/2026) — CETTE NOTE PORTAIT UNE PRÉMISSE QUI A CESSÉ
  // D'ÊTRE VRAIE. Elle disait « `langouste` et `whale` sont INATTEIGNABLES,
  // tout module neuf sort donc à `member` ». Le service des comptes sait
  // maintenant lequel des trois niveaux a été acheté, et les trois s'accordent.
  // La règle « tout module neuf sort à `member` » n'est donc plus IMPOSÉE par
  // le code : elle redevient un arbitrage de produit, à poser avec Preda.
  // ⛔ On corrige la note en même temps que le fait — un commentaire survivant
  // à sa cause donne un ordre que plus rien ne justifie.
  profils:     { fichier: 'profils.json',     gate: 'modules' },
  meta:        { fichier: 'meta.json',        gate: 'modules' },
  // 🏆 LOT 228 — LE RENDEMENT MCP DES SETS (demande `f`).
  // ⚠️ `chemin` ET NON `fichier` : ce dépôt-ci vit à la RACINE de `.reserve/`,
  // pas dans `analytics/`, parce qu'il est écrit par `dataset()` et que
  // `reserve_analytics.ecrire()` supprime son dossier APRÈS. La route doit
  // donc savoir lire les deux emplacements — d'où les deux clés, et jamais un
  // `..` dans `fichier` : la liste blanche perdrait tout son sens.
  // 🔴 `modules`, comme ses voisins sans adresse de wallet. ⛔ Ce module porte
  // en revanche des PRIX agrégés — c'est le premier de cette route à le faire,
  // et c'est ce qui interdit qu'il descende jamais à `visitor`.
  sets_mcp:    { chemin: SETS_MCP_FICHIER,    gate: 'modules', tranche: true },
};

// ⭐ LE PLAFOND DE CE QU'UNE RÉPONSE REND. Même raison que `RENDU_MAX` de
// `marche_selection.mjs` : 5 154 sets pèsent ~1 Mo, cette route est
// `private, no-store`, donc **chaque octet est repayé à chaque visite**. Le
// filtre voit tout le corpus ; c'est le RENDU qui est coupé.
// ⛔ Et `n` vient de l'URL : quelqu'un écrira `?n=99999`.
// ⭐⭐ EXPORTÉES POUR LE BANC — il ne doit JAMAIS recopier ces deux
// nombres : un banc qui code un réglage en dur devient faux le jour où le
// réglage change, et personne ne le voit. Astro ignore les exports qu'il ne
// connaît pas ; seuls `GET`, `prerender` et `getStaticPaths` lui parlent.
export const SETS_MAX = 200;
export const SETS_DEFAUT = 50;

/** Un entier borné — `Number('abc')` rend `NaN` et `?n=-5` rendrait une
 *  tranche vide sur une page qui a l'air de marcher.
 *
 *  🔴🔴 MESURÉ EN PRODUCTION LE 05/09/2026 — CETTE ROUTE SERVAIT **1 SET SUR
 *  3 194**, et `SETS_DEFAUT` était du code mort depuis son premier jour.
 *  `searchParams.get()` rend `null` quand le paramètre est ABSENT ; `Number`
 *  d'un `null` vaut **0**, pas `NaN` ; `Number.isFinite` d'un zéro est **vrai**.
 *  Le repli sur `defaut` n'était donc pas mort : il était INATTEIGNABLE — et le
 *  zéro remontait à `min`, ici 1. Le gabarit appelle la route sans `n`, donc
 *  c'est le chemin NORMAL qui était cassé, jamais un cas limite.
 *
 *  ⭐⭐ ET LE MÊME CODE VA BIEN DANS `marche_selection.mjs` (`entier`) — PAR
 *  COÏNCIDENCE, PAS PAR SÛRETÉ : il y est appelé avec `min === defaut ===
 *  PAR_PAGE`, donc le zéro remonte pile sur le défaut. Le garde-fou n'y sert pas
 *  davantage ; il ne s'y VOIT pas.
 *  ⇒ **quand `min` vaut le défaut, la branche « défaut » n'est jamais mesurée.**
 *  Pour la juger, on appelle SANS le paramètre — pas avec une valeur bidon.
 *  ⛔ `/market/` n'est PAS corrigé ici : il n'a aucun défaut observable, et
 *  l'élargissement appartient à son propre lot. La dette est nommée, pas payée.
 *
 *  🔑 La bonne écriture existait déjà à neuf lignes de l'autre : `nb()`, dans ce
 *  même `marche_selection.mjs`, tranche AVANT la conversion. On fait pareil.
 *  ⚠️ Et on décape les blancs : une chaîne d'espaces se convertit en zéro elle
 *  aussi, et `?n=` suivi d'un espace n'est pas une demande de « une ligne ». */
const entierBorne = (v, defaut, min, max) => {
  if (v === null || v === undefined || String(v).trim() === '') return defaut;
  const n = Math.trunc(Number(v));
  if (!Number.isFinite(n)) return defaut;
  return Math.min(max, Math.max(min, n));
};

// La fiche de cornérisation d'une pièce : `/api/analytics/corner?uuid=…`
const RE_UUID = /^[0-9a-f-]{8,64}$/i;

export async function GET({ params, request, locals }) {
  const nom = String(params.module || '');

  // ── LA FICHE PAR PIÈCE ────────────────────────────────────────────────────
  if (nom === 'corner') {
    const uuid = new URL(request.url).searchParams.get('uuid') || '';
    if (!RE_UUID.test(uuid)) return refus(400, 'uuid');
    if (!franchit('modules', locals)) {
      return refus(estIdentifie(locals) ? 403 : 401, 'palier');
    }
    const f = join(ANALYTICS_DIR, 'corner', `${uuid}.json`);
    if (!existsSync(f)) return refus(404, 'absent');
    return new Response(readFileSync(f, 'utf8'), { status: 200, headers: ENTETES });
  }

  // ── LES CINQ MODULES ──────────────────────────────────────────────────────
  const mod = Object.prototype.hasOwnProperty.call(MODULES, nom) ? MODULES[nom] : null;
  if (!mod) return refus(404, 'module');

  // ⭐ LE DROIT AVANT TOUTE LECTURE DE DISQUE. Vérifier après avoir lu
  // marcherait aussi — et laisserait la porte ouverte au premier `return` mal
  // placé ajouté plus tard.
  if (!franchit(mod.gate, locals)) {
    // 401 = « connecte-toi », 403 = « ton palier ne suffit pas ». Les deux sont
    // un contrat HTTP ; ils ne détaillent pas le motif.
    return refus(estIdentifie(locals) ? 403 : 401, 'palier');
  }

  const f = mod.chemin || join(ANALYTICS_DIR, mod.fichier);
  if (!existsSync(f)) {
    // ⚠️ 503 ET PAS 404 : le module EXISTE, c'est la réserve qui n'a pas été
    // écrite (entrepôt injoignable au build). Un 404 enverrait chercher une
    // faute de frappe dans l'URL.
    return refus(503, 'reserve');
  }
  const brut = readFileSync(f, 'utf8');
  if (!mod.tranche) return new Response(brut, { status: 200, headers: ENTETES });

  // ── LE TRI ET LA TRANCHE, AU SERVEUR ──────────────────────────────────────
  // ⭐⭐ LE TRI PORTE SUR LE CORPUS ENTIER, LA COUPE VIENT APRÈS. L'inverse —
  // couper puis trier — rendrait « les 50 premiers du fichier, triés », c'est-
  // à-dire un classement qui a l'air juste et qui ne l'est pas. C'est la règle
  // du lot 68, et elle vaut ici mot pour mot.
  const sp = new URL(request.url).searchParams;
  const tri = TRIS_SETS.includes(sp.get('tri') || '') ? sp.get('tri') : TRI_SETS_DEFAUT;
  const n = entierBorne(sp.get('n'), SETS_DEFAUT, 1, SETS_MAX);
  const charge = JSON.parse(brut);
  const tous = Array.isArray(charge.sets) ? charge.sets : [];
  const classes = classerSets(tous, tri);
  return new Response(JSON.stringify({
    ...charge,
    tri,
    // ⭐ LE DÉNOMINATEUR VOYAGE AVEC LA TRANCHE. `total` et `classables`
    //   viennent du fichier ; `rendus` dit ce que CETTE réponse contient. Sans
    //   les trois, « 50 sets » se lit « le catalogue fait 50 sets ».
    rendus: Math.min(n, classes.length),
    tronque: classes.length > n,
    sets: classes.slice(0, n),
  }), { status: 200, headers: ENTETES });
}

// ⭐ « Identifié » et « autorisé » sont deux questions. Les confondre produit
// les failles d'élévation de privilège — c'est déjà écrit dans `middleware.js`,
// et c'est vrai ici aussi.
function estIdentifie(locals) {
  const p = locals?.palier;
  return typeof p === 'string' && p !== 'visitor';
}

// ⚠️ `porte` est importé pour que le jour où un module veut annoncer SON palier
// requis dans la réponse, la source soit déjà la bonne. Il n'est pas utilisé
// aujourd'hui — et je le note plutôt que de le laisser passer pour un oubli.
void porte;
