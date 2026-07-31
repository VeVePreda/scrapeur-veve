/* ═══════════════════════════════════════════════════════════════════════════
   CSS MORT — les règles qui ne s'appliqueront JAMAIS, et ne le diront jamais
   ═══════════════════════════════════════════════════════════════════════════
   ⭐⭐ ÉCRIT LE 31/07/2026, APRÈS AVOIR LIVRÉ UN SITE DONT TOUTE LA GRAMMAIRE
   RESPONSIVE ÉTAIT MORTE DEPUIS LE PREMIER JOUR.

   Trois défauts, la même signature : le navigateur fait exactement ce qu'on lui
   a écrit, donc rien n'échoue, donc rien ne le dit.

   1. `@container X (...)` sans que rien ne déclare `container-name: X`.
      34 blocs inertes. Aucune erreur, aucun log, aucun build rouge.
   2. Une classe que le moteur ÉMET et pour laquelle le thème n'a AUCUNE règle.
      `body`, `header.site`, `nav.main`, `footer.site` avaient disparu : le blog,
      les mentions légales et la 404 étaient en HTML brut en production.
   3. `var(--x)` sans `--x` défini nulle part : la déclaration est ignorée.

   ⛔ MON COMPARATEUR DE FIDÉLITÉ NE POUVAIT VOIR AUCUN DES TROIS. Il vérifiait
   que la classe était dans le GABARIT — jamais qu'une RÈGLE existait pour elle.
   Il contrôlait le mauvais côté du contrat, et notait 92,9 % pendant que le
   site s'affichait en Times.

   Usage :  node outils/css-mort.mjs [racine]
*/
import fs from 'node:fs';
import path from 'node:path';

const R = process.argv[2] || '.';
const lire = (p) => fs.readFileSync(p, 'utf8');
const sansCommentaires = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '');

function fichiers(d, re, acc = []) {
  if (!fs.existsSync(d)) return acc;
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name.startsWith('.')) continue;
    const p = path.join(d, e.name);
    if (e.isDirectory()) fichiers(p, re, acc);
    else if (re.test(e.name)) acc.push(p);
  }
  return acc;
}

const themes = fichiers(path.join(R, 'themes'), /\.css$/);
const gabarits = fichiers(path.join(R, 'src'), /\.astro$/);
const gabaritsSrc = gabarits.map(lire).join('\n');
let griefs = 0;

for (const t of themes) {
  const brut = lire(t);
  const css = sansCommentaires(brut);
  const nom = path.relative(R, t);

  // ── 1 · un @container dont le conteneur n'est déclaré nulle part ────────
  const declares = new Set([...css.matchAll(/container-name\s*:\s*([\w-]+)/g)].map((m) => m[1]));
  // le raccourci `container: nom / type`
  for (const m of css.matchAll(/[^-]container\s*:\s*([\w-]+)\s*\//g)) declares.add(m[1]);
  const demandes = new Map();
  for (const m of css.matchAll(/@container\s+([\w-]+)\s*\(/g))
    demandes.set(m[1], (demandes.get(m[1]) || 0) + 1);
  for (const [c, n] of demandes) {
    if (!declares.has(c)) {
      griefs++;
      console.log(`⛔ ${nom}`);
      console.log(`   ${n} bloc(s) « @container ${c} » — RIEN ne declare container-name:${c}`);
      console.log(`   → ces ${n} bloc(s) ne s'appliqueront JAMAIS, sans une seule erreur.`);
    }
  }

  // ── 2 · var(--x) jamais defini ──────────────────────────────────────────
  // ⚠️ Les variables posees par un gabarit en style="--i:3" sont legitimes :
  // on les cherche donc AUSSI dans les .astro avant de crier.
  const definies = new Set([...css.matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]));
  const FOURNIES = ['--primary','--accent','--danger','--bg','--surface','--text',
                    '--muted','--font-heading','--font-body'];  // injectees par Base.astro
  FOURNIES.forEach((v) => definies.add(v));
  for (const m of gabaritsSrc.matchAll(/(--[\w-]+)\s*:/g)) definies.add(m[1]);
  // ⚠️ `var(--x, 2600)` est VALIDE meme si --x n'existe pas : le repli s'applique.
  // Un controle qui ignore le repli crie sur du code correct — et on finit par
  // ne plus l'ecouter. On ne retient que les lectures SANS repli.
  const sansRepli = new Set();
  for (const m of css.matchAll(/var\(\s*(--[\w-]+)\s*([,)])/g))
    if (m[2] === ')') sansRepli.add(m[1]);
  const orphelines = [...sansRepli].filter((v) => !definies.has(v));
  if (orphelines.length) {
    griefs++;
    console.log(`⛔ ${nom}`);
    console.log(`   ${orphelines.length} variable(s) lue(s) mais jamais definie(s) : ${orphelines.join(' ')}`);
    console.log(`   → chaque declaration qui les lit est ignoree, en silence.`);
  }
}

// ── 3 · une classe emise par le moteur, sans aucune regle dans le theme ────
// ⭐ C'EST LE CONTROLE QUI MANQUAIT. Le LISEZ-MOI disait « 27 classes, et c'est
// tout le contrat » — personne ne verifiait que le contrat etait tenu.
const SOCLE = ['wrap','card','grid','item','tag','stats','stat','lead','muted','up','down',
               'num','hide','crumbs','searchbox','chart','avertis','alerte','post','prose','legal'];
const BALISES = ['header.site','nav.main','footer.site','body','html'];
for (const t of themes) {
  const css = sansCommentaires(lire(t));
  const nom = path.relative(R, t);
  const absents = [
    ...SOCLE.filter((c) => !new RegExp(`\\.${c}[^\\w-]`).test(css)).map((c) => '.' + c),
    ...BALISES.filter((b) => !new RegExp(b.replace('.', '\\.') + '\\s*[,{]').test(css)),
  ];
  if (absents.length) {
    griefs++;
    console.log(`⛔ ${nom}`);
    console.log(`   ${absents.length} element(s) du socle SANS AUCUNE REGLE : ${absents.join(' ')}`);
    console.log(`   → les pages qui ne s'en servent que de ca (blog, legal, 404) sortent NUES.`);
  }
}

console.log(griefs
  ? `\n⛔ ${griefs} grief(s) — du CSS qui ne s'appliquera jamais et ne le dira pas.`
  : `\n✅ ${themes.length} theme(s) : aucun @container orphelin, aucune variable fantome, socle complet.`);
process.exit(griefs ? 1 : 0);
