// ⚠️ VeVePreda/veve-sites — engine/tools/test_sets_mcp.mjs   (NEUF — lot 228)
// ═══════════════════════════════════════════════════════════════════════════
//  LE BANC DU RENDEMENT MCP DES SETS — demande `f` de Preda
// ═══════════════════════════════════════════════════════════════════════════
// ⛔ IL N'IMPORTE PAS `dataset.mjs` : un banc qui l'importe recalcule la
// vitrine et VIDE `.reserve/cote/`. Il importe le module PUR et lit le TEXTE
// des deux fichiers qui le branchent.
//
// ⭐⭐ CE QU'IL SURVEILLE VRAIMENT, ET QU'AUCUN AUTRE BANC NE PEUT VOIR :
// **la PLACE du dépôt dans `dataset.mjs`.** Descendu sous `projeterCote()`, il
// sommerait des `undefined`, rendrait `cout: null` sur les 5 154 sets et
// servirait un tableau vide — build vert, journal fier, zéro erreur. C'est
// exactement la famille de pannes que ce dépôt paie le plus cher.
//
// 🔬 IL A ÉTÉ JUGÉ EN LUI INJECTANT LE MAUVAIS CODE (05/09/2026) : dépôt
// descendu sous la projection ⇒ ROUGE ; plafond de set porté à 40 ⇒ ROUGE ;
// pièce sans barème comptée 0 ⇒ ROUGE ; `null` triés en tête ⇒ ROUGE.

import { readFileSync } from 'node:fs';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { pointsDeSet, agregerSet, classerSets, construireSetsMcp,
         SET_POINTS_MAX, SETS_MCP_FICHIER, TRIS_SETS } from '../lib/sets_mcp.mjs';

const ICI = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(ICI, '..', '..');

let ko = 0;
const verifie = (titre, ok, detail = '') => {
  console.log(`  ${ok ? '✅' : '❌'} ${titre}${detail ? `   — ${detail}` : ''}`);
  if (!ok) ko++;
};

// 📝 DÉCAPER LES COMMENTAIRES AVANT DE CHERCHER UN NOM. Cinquième fois que ce
// piège se paie : `projeterCote` et `deposerSetsMcp` sont tous deux CITÉS dans
// la prose de `dataset.mjs`, et un banc qui lit le fichier brut mesurerait la
// position de deux commentaires.
// ⛔ `//` sauf après `:` — sinon on décape le `https://` des URL.
const decape = (src) => src
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .split('\n').map((l) => l.replace(/(^|[^:])\/\/.*$/, '$1')).join('\n');

console.log('\n🏆 LE RENDEMENT MCP DES SETS\n');

// ── ① LE BARÈME, ET SON PLAFOND ───────────────────────────────────────────
console.log('① le barème de set — source VeVe, plafond à 5');
verifie('la table est 1→1, 2→2, 3→3, 4→4, 5→5',
  [1, 2, 3, 4, 5].every((n) => pointsDeSet(n) === n),
  [1, 2, 3, 4, 5].map(pointsDeSet).join(' '));
// ⭐ LE TERME À ZÉRO EST ATTEIGNABLE : porter SET_POINTS_MAX à 40 fait rougir
//   cette ligne, et c'est la seule qui morde sur le plafond.
verifie('il PLAFONNE : un set de 40 pièces rapporte le même bonus qu\'un set de 5',
  pointsDeSet(40) === SET_POINTS_MAX && SET_POINTS_MAX === 5,
  `pointsDeSet(40) = ${pointsDeSet(40)} · SET_POINTS_MAX = ${SET_POINTS_MAX}`);
// 🕳️ `Number('')` VAUT 0 — le piège qui a déjà coûté au projet.
verifie('une taille vide, nulle ou non entière rend `null`, JAMAIS 0',
  ['', null, undefined, 0, -3, 2.5, 'x'].every((v) => pointsDeSet(v) === null),
  ['', null, undefined, 0, -3, 2.5, 'x'].map((v) => String(pointsDeSet(v))).join(' '));

// ── ② LES TROIS REFUS DE L'AGRÉGAT ────────────────────────────────────────
console.log('\n② les refus — un chiffre absent vaut mieux qu\'un chiffre inventé');
const piece = (floor, rarity = 'COMMON', type = 'collectible') => ({ floor, rarity, type });
const set = (items) => ({ slug: 's', name: 'S', brand: '', licensor: '', items });

const complet = agregerSet(set([piece(100), piece(50, 'RARE')]));
verifie('un set complet : coût = somme des planchers, points = bonus + pièces',
  complet.cout === 150 && complet.bonusSet === 2 && complet.pointsPieces === 2.25
  && complet.points === 4.25,
  `cout=${complet.cout} bonus=${complet.bonusSet} pieces=${complet.pointsPieces} pts=${complet.points}`);
verifie('… et son ratio est le quotient EXACT, sans arrondi',
  complet.gemsParMcp === 150 / 4.25, String(complet.gemsParMcp));

// REFUS ① — une seule pièce sans plancher suffit.
const troue = agregerSet(set([piece(100), piece(null, 'RARE')]));
verifie('REFUS ① une pièce sans plancher ⇒ `cout` ET `gemsParMcp` sont `null`',
  troue.cout === null && troue.gemsParMcp === null && troue.couvert === 1,
  `cout=${troue.cout} ratio=${troue.gemsParMcp} couvert=${troue.couvert}/${troue.taille}`);
// ⭐ Et le zéro n'est pas un plancher : un `floor` à 0 ne couvre pas la pièce.
verifie('… et un plancher à 0 ne compte pas comme couvert (0 n\'est pas un prix)',
  agregerSet(set([piece(100), piece(0)])).cout === null);

// REFUS ② — une pièce hors barème ne vaut pas zéro point.
const horsBareme = agregerSet(set([piece(100), piece(50, 'ARTIST_PROOF', 'comic')]));
verifie('REFUS ② une pièce sans barème ⇒ `points` est `null`, pas un total gonflé',
  horsBareme.points === null && horsBareme.sansBareme === 1 && horsBareme.gemsParMcp === null,
  `pts=${horsBareme.points} sansBareme=${horsBareme.sansBareme}`);

// ── ③ LE CLASSEMENT — LES `null` EN DERNIER, DANS LES DEUX SENS ───────────
console.log('\n③ le classement');
const corpus = [
  { nom: 'cher', gemsParMcp: 900, points: 5, cout: 900, taille: 1 },
  { nom: 'muet', gemsParMcp: null, points: null, cout: null, taille: 2 },
  { nom: 'bon', gemsParMcp: 10, points: 9, cout: 90, taille: 3 },
];
const asc = classerSets(corpus, 'gpm-asc').map((a) => a.nom);
const desc = classerSets(corpus, 'gpm-desc').map((a) => a.nom);
verifie('croissant : le moins cher par point d\'abord, le muet EN DERNIER',
  asc.join(',') === 'bon,cher,muet', asc.join(','));
verifie('décroissant : l\'ordre s\'inverse, le muet reste EN DERNIER',
  desc.join(',') === 'cher,bon,muet', desc.join(','));
verifie('un tri inconnu retombe sur le défaut, il ne lève pas',
  classerSets(corpus, 'n-importe-quoi').map((a) => a.nom).join(',') === asc.join(','));
verifie(`les ${TRIS_SETS.length} tris déclarés rendent tous ${corpus.length} lignes — aucun n'en perd`,
  TRIS_SETS.every((t) => classerSets(corpus, t).length === corpus.length),
  TRIS_SETS.join(' '));

// ── ④ LA CHARGE DIT SON DÉNOMINATEUR ──────────────────────────────────────
console.log('\n④ la charge');
const charge = construireSetsMcp([set([piece(100)]), set([piece(null)])]);
verifie('elle porte `total`, `classables` et `personnalise`',
  charge.total === 2 && charge.classables === 1 && charge.personnalise === false,
  `total=${charge.total} classables=${charge.classables} perso=${charge.personnalise}`);
verifie('`personnalise` est FAUX — aucune étiquette ne peut promettre l\'exclusion des sets possédés',
  charge.personnalise === false);

// ── ⑤ 🔴🔴 LA PLACE DU DÉPÔT DANS `dataset.mjs` ───────────────────────────
console.log('\n⑤ la place du dépôt — le seul contrôle qu\'aucun autre banc ne fait');
const ds = decape(readFileSync(join(ROOT, 'engine', 'lib', 'dataset.mjs'), 'utf8'));
const iDepot = ds.indexOf('deposerSetsMcp(');
const iProj = ds.indexOf('projeterCote(items)');
verifie('les deux appels existent dans le CODE (et pas seulement dans la prose)',
  iDepot > 0 && iProj > 0, `depot@${iDepot} · projeterCote@${iProj}`);
verifie('🔴 `deposerSetsMcp()` vient AVANT `projeterCote()` — sinon il somme des `undefined`',
  iDepot > 0 && iProj > 0 && iDepot < iProj,
  iDepot < iProj ? 'ordre correct' : 'DÉPÔT TOMBÉ SOUS LA PROJECTION');

// ── ⑥ LE FICHIER N'EST DANS AUCUN DES DEUX DOSSIERS BALAYÉS ───────────────
console.log('\n⑥ l\'emplacement de la réserve');
const chemin = SETS_MCP_FICHIER.replace(/\\/g, '/');
verifie('il vit dans `.reserve/`, HORS de `cote/` (vidé par projeter()) et hors de `analytics/` (rmSync au build:done)',
  chemin.includes('/.reserve/')
  && !chemin.includes('/.reserve/cote/') && !chemin.includes('/.reserve/analytics/'),
  chemin);

// ── ⑦ LA ROUTE TRIE LE CORPUS AVANT DE LE COUPER ──────────────────────────
console.log('\n⑦ la route');
const rt = decape(readFileSync(join(ROOT, 'src', 'pages', 'api', 'analytics', '[module].js'), 'utf8'));
const iClasse = rt.indexOf('classerSets(tous');
const iCoupe = rt.indexOf('.slice(0, n)');
verifie('🔴 elle CLASSE le corpus entier AVANT de couper — l\'inverse rendrait « les 50 premiers du fichier, triés »',
  iClasse > 0 && iCoupe > 0 && iClasse < iCoupe, `classe@${iClasse} · coupe@${iCoupe}`);
verifie('le module est derrière une porte, et ce n\'est pas `visitor`',
  /sets_mcp:\s*\{[^}]*gate:\s*'modules'/.test(rt),
  rt.includes('sets_mcp:') ? 'déclaré' : 'ABSENT de MODULES');
verifie('la réponse rend `total`, `rendus` et `tronque` — le dénominateur voyage avec la tranche',
  rt.includes('rendus:') && rt.includes('tronque:'));

// ── ⑧ L'AFFICHAGE — BRANCHÉ, ÉTIQUETÉ, ET SANS CLASSE NEUVE ──────────────
console.log('\n⑧ l\'affichage');
const AS = readFileSync(join(ROOT, 'src', 'components', 'pages', 'AnalyticsSujet.astro'), 'utf8');
const ASnu = decape(AS);
// 🧩 UN FICHIER DÉPOSÉ N'EST PAS BRANCHÉ. La réserve peut être écrite, la
// route servir, et la page ne rien demander — trois pièces justes, zéro
// affichage, et aucun rouge nulle part.
verifie('🔴 le module est BRANCHÉ dans le sujet `collections` (réserve + route ne suffisent pas)',
  /collections:\s*\{[\s\S]{0,400}?cible:\s*'sets_mcp'/.test(ASnu),
  ASnu.includes("'sets_mcp'") ? 'déclaré' : 'ABSENT de SUJETS.collections.led');
verifie('… et il a une fonction de rendu du même nom que son `id`',
  /\bsets:\s*function\s*\(d\)/.test(ASnu),
  'sans elle, `rendus[cle]` est `undefined` et la section reste au verrou, EN SILENCE');
// ⭐⭐ L'ÉTIQUETTE EST UN LIVRABLE, PAS UN ORNEMENT : sans elle le tableau
// promet un revenu qu'on ne tient pas.
verifie('🔑 l\'étiquette `led.sets.note` est passée au script ET rendue',
  /sNote:\s*t\(lang, 'led\.sets\.note'\)/.test(ASnu) && /ech\(L\.sNote\)/.test(ASnu));
// ⛔ Un zéro à la place d'un tiret dirait « ce set est gratuit ».
verifie('⛔ un chiffre absent rend un TIRET, jamais un zéro',
  /v == null \? '—'/.test(ASnu));

// 🎨 AUCUNE CLASSE NEUVE — le rework du design est en vol ailleurs.
{
  const bloc = (ASnu.match(/sets: function \(d\)[\s\S]*?\n    \},/) || [''])[0];
  const classes = [...bloc.matchAll(/class="([^"]+)"/g)].flatMap((m) => m[1].split(/\s+/)).filter(Boolean);
  const connues = ['etiq', 'muted', 'tbl-hote'];
  const neuves = [...new Set(classes)].filter((c) => !connues.includes(c));
  verifie('🎨 le bloc n\'introduit AUCUNE classe neuve — le rework l\'emportera avec le reste',
    neuves.length === 0, neuves.length ? `🔴 ${neuves.join(', ')}` : classes.join(' ') || 'aucune classe');
}

// ── ⑨ LES CLÉS i18n, DANS LES CINQ LANGUES ───────────────────────────────
console.log('\n⑨ les clés i18n');
// ⛔ `t()` retombe sur la CLÉ quand elle manque : une langue oubliée n'affiche
// pas un vide, elle affiche `led.sets.ratio` dans un en-tête de colonne.
const CLES = ['led.sets', 'led.sets.d', 'led.sets.set', 'led.sets.size',
              'led.sets.cost', 'led.sets.pts', 'led.sets.ratio', 'led.sets.note'];
for (const lg of ['en', 'fr', 'es', 'de', 'it']) {
  const dico = JSON.parse(readFileSync(join(ROOT, 'engine', 'i18n', `${lg}.json`), 'utf8'));
  const manquantes = CLES.filter((k) => !dico[k]);
  verifie(`${lg} : les ${CLES.length} clés du module existent`,
    manquantes.length === 0, manquantes.length ? `🔴 ${manquantes.join(', ')}` : 'toutes présentes');
  // ⭐ Et la note DIT les quatre choses qu'elle doit dire. Une étiquette qui
  //   rétrécit d'une traduction à l'autre promet plus dans une langue que dans
  //   l'autre — sur un chiffre d'argent, c'est le pire des écarts.
  const note = String(dico['led.sets.note'] || '');
  verifie(`${lg} : la note porte le 100, le 7 et le 30 % — les trois chiffres qui bornent la promesse`,
    note.includes('100') && note.includes('7') && note.includes('30'),
    `${note.length} car.`);
}


// ── ⑩ LA ROUTE, EXÉCUTÉE POUR DE VRAI ─────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════
// 🔴🔴🔴 CE BLOC EXISTE PARCE QUE TOUT LE RESTE DE CE BANC ÉTAIT VERT PENDANT
// QUE LA PRODUCTION SERVAIT **1 SET SUR 3 194**. Le module pur était juste, le
// dépôt était au bon endroit, les cinq langues disaient la vérité — et la
// ROUTE, elle, n'avait jamais été appelée par personne.
//
// ⭐⭐ ET UN BANC QUI LIT LE TEXTE DE LA ROUTE NE L'AURAIT PAS VU NON PLUS : le
// fichier DIT `SETS_DEFAUT = 50`, en toutes lettres, et c'est lisible et faux.
// `searchParams.get()` rend `null` pour un paramètre absent, `Number(null)`
// vaut 0, `Number.isFinite(0)` est vrai — le défaut était INATTEIGNABLE.
// ⇒ **seul un banc qui EXÉCUTE pouvait mordre.** C'est le patron de
// `test_reserve.mjs`, qui importe `/api/historique/[uuid]` et l'appelle.
//
// 🧪 IL TOURNE DANS UN SOUS-PROCESSUS, et c'est délibéré : `SETS_MCP_FICHIER`
// est figé à l'import de `sets_mcp.mjs`, déjà chargé en tête de ce banc. Poser
// `RESERVE_SETS_MCP` ici n'aurait plus aucun effet, et écrire dans la vraie
// `.reserve/` polluerait les bancs qui suivent. Un process neuf coûte 0,2 s et
// ne laisse rien derrière lui.
//
// 🔬 JUGÉ EN LUI INJECTANT LE MAUVAIS CODE (05/09/2026) : garde-fou retiré de
// `entierBorne` ⇒ ROUGE sur « absent » et sur les trois vides ; `trim()` retiré
// ⇒ ROUGE sur la seule ligne des espaces ; plafond ignoré ⇒ ROUGE sur 99999.
console.log('\n⑩ la route /api/analytics/sets_mcp — EXÉCUTÉE, pas relue');
{
  const { execFileSync } = await import('node:child_process');
  const { writeFileSync, mkdtempSync } = await import('node:fs');
  const { tmpdir } = await import('node:os');

  // ⭐ LA CHARGE D'ESSAI DOIT ÊTRE PLUS GRANDE QUE LE PLAFOND. Avec 60 sets,
  //   « sans n » et « n=99999 » rendraient le même nombre : le banc serait vert
  //   sans distinguer le défaut du plafond. On en met franchement plus.
  const boite = mkdtempSync(join(tmpdir(), 'banc-sets-'));
  const reserve = join(boite, 'sets_mcp.json');
  const faux = { calcule: new Date().toISOString(), total: 500, classables: 500,
    personnalise: false, baremeSetMax: SET_POINTS_MAX,
    sets: Array.from({ length: 500 }, (_, i) => ({
      slug: 's' + i, nom: 'Set ' + i, marque: 'M', licence: 'L', taille: 1,
      cout: i + 1, couvert: 1, bonusSet: 1, pointsPieces: 1, sansBareme: 0,
      points: 2, gemsParMcp: (i + 1) / 2 })) };
  writeFileSync(reserve, JSON.stringify(faux), 'utf8');

  // ⛔ PAS DE TEMPLATE LITTÉRAL DANS CE CODE INJECTÉ : il traverse un argument
  //    de ligne de commande, et un `$` y aurait deux lecteurs.
  const CODE = [
    "import { pathToFileURL } from 'node:url';",
    "import { join } from 'node:path';",
    "const R = process.env.PROJECT_ROOT;",
    "const url = (f) => pathToFileURL(join(R, f)).href;",
    "const route = await import(url('src/pages/api/analytics/[module].js'));",
    "const acces = await import(url('engine/lib/access.mjs'));",
    // ⭐⭐ LE PALIER SE LIT DANS LE MANIFESTE, IL NE S'ÉCRIT PAS ICI. vevewiki
    //    déclare un seul palier : la porte y est INACTIVE et tout le monde
    //    franchit. Un banc qui coderait `member` en dur casserait le build de
    //    l'autre site sur un moteur parfaitement sain — c'est déjà arrivé le
    //    02/08 avec `test_reserve`, et c'est écrit là-bas en toutes lettres.
    "const P = acces.porte('modules');",
    "const locals = P.actif ? { palier: P.tier } : {};",
    "const appel = async (q) => {",
    "  const r = await route.GET({ params: { module: 'sets_mcp' },",
    "    request: new Request('https://banc.test/api/analytics/sets_mcp' + q), locals });",
    "  const t = await r.text();",
    "  let j = null; try { j = JSON.parse(t); } catch (e) { j = null; }",
    "  return { status: r.status, rendus: j && j.rendus,",
    "           lignes: j && Array.isArray(j.sets) ? j.sets.length : null,",
    "           tri: j && j.tri, corps: t.slice(0, 120) };",
    "};",
    "const out = { defaut: route.SETS_DEFAUT, max: route.SETS_MAX, porte: P.actif ? P.tier : 'inactive' };",
    "for (const q of ['', '?n=', '?n=%20%20', '?n=10', '?n=abc', '?n=-5', '?n=99999'])",
    "  out[q === '' ? 'absent' : q] = await appel(q);",
    "console.log(JSON.stringify(out));",
  ].join('\n');

  let R = null; let erreur = '';
  try {
    const brut = execFileSync(process.execPath, ['--input-type=module', '-e', CODE],
      { cwd: ROOT, encoding: 'utf8', timeout: 30000,
        env: { ...process.env, PROJECT_ROOT: ROOT, RESERVE_SETS_MCP: reserve } });
    R = JSON.parse(brut.trim().split('\n').pop());
  } catch (e) {
    erreur = String(e.stderr || e.message).split('\n').slice(-4).join(' | ');
  }

  // 🔴 UN BANC QUI N'A RIEN PU INSPECTER N'A RIEN PROUVÉ. S'il n'a pas tourné,
  //    il rougit — il ne se tait pas.
  verifie('la route se charge et répond', R !== null, erreur || `porte : ${R && R.porte}`);

  if (R) {
    verifie('elle rend 200 au palier que le manifeste exige',
      R.absent.status === 200, `status ${R.absent.status} — ${R.absent.corps}`);

    // ⭐⭐⭐ LE CONTRÔLE QUI AURAIT ÉVITÉ LE DÉFAUT. `rendus` est comparé à la
    //   constante EXPORTÉE par la route, jamais à un 50 recopié ici.
    verifie('🎯 SANS `n`, elle rend LE DÉFAUT — pas 1, pas 0',
      R.absent.rendus === R.defaut && R.absent.lignes === R.defaut,
      `rendus=${R.absent.rendus} lignes=${R.absent.lignes} · défaut déclaré=${R.defaut}`);

    // 🕳️ Les trois façons d'écrire « rien », qui valent toutes 0 une fois
    //    converties. La troisième (des espaces) est la seule que `trim()` sauve.
    for (const [q, nom] of [['?n=', '`n` présent mais VIDE'], ['?n=%20%20', '`n` fait de deux ESPACES'],
                            ['?n=abc', '`n` illisible']]) {
      verifie(`${nom} ⇒ le défaut, jamais 1`,
        R[q] && R[q].rendus === R.defaut, `rendus=${R[q] && R[q].rendus}`);
    }

    verifie('une valeur explicite est respectée (`n=10`)',
      R['?n=10'].rendus === 10, `rendus=${R['?n=10'].rendus}`);
    verifie('un `n` négatif ne rend pas une tranche vide (il est remonté au minimum)',
      R['?n=-5'].rendus >= 1, `rendus=${R['?n=-5'].rendus}`);
    // ⭐ Le plafond protège une route `private, no-store` : chaque octet est
    //   repayé à chaque visite. Il doit mordre AVANT que la charge parte.
    verifie('un `n` démesuré est PLAFONNÉ au maximum déclaré',
      R['?n=99999'].rendus === R.max && R['?n=99999'].lignes === R.max,
      `rendus=${R['?n=99999'].rendus} · plafond déclaré=${R.max}`);
    verifie('le défaut déclaré est strictement sous le plafond — sinon rien ne distingue les deux',
      R.defaut < R.max, `${R.defaut} < ${R.max}`);
  }
}

console.log(ko === 0 ? '\n✅ SETS MCP — tout est conforme\n'
                     : `\n❌ SETS MCP — ${ko} contrôle(s) en échec\n`);
process.exit(ko === 0 ? 0 : 1);
