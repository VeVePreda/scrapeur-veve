/* ═══════════════════════════════════════════════════════════════════════════
   IMPORTS ORPHELINS — tout `import` doit désigner un fichier qui EXISTE
   ═══════════════════════════════════════════════════════════════════════════
   ⭐⭐ ÉCRIT APRÈS UN DÉPLOIEMENT CASSÉ, LE 31/07/2026.
   J'ai fait supprimer `src/components/Piece.astro` — à juste titre, il appelait
   une API disparue. Mais `CollectionPage.astro` l'importait encore, et le build
   a échoué en production, à l'étape 18 sur 21, après 17 bancs verts.
   ⛔ SUPPRIMER UN FICHIER EST UNE OPÉRATION À DEUX FACES : retirer le fichier,
   et retirer ceux qui le nomment. Je n'avais fait que la première.
   ⚠️ Aucun des 17 bancs ne regardait les imports — `test:gabarits` vérifie la
   FORME d'un .astro, pas ses dépendances. Un défaut qui passe 17 contrôles
   n'est pas un défaut sournois : c'est un contrôle qui manque.
   ⭐ Celui-ci coûte 40 ms et lit tout le dépôt.

   Usage :  node outils/imports-orphelins.mjs
*/
import fs from 'node:fs';
import path from 'node:path';

const RACINE = process.argv[2] || '.';
const EXT = new Set(['.astro', '.mjs', '.js', '.ts']);

function fichiers(d, acc = []) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name.startsWith('.')) continue;
    const p = path.join(d, e.name);
    if (e.isDirectory()) fichiers(p, acc);
    else if (EXT.has(path.extname(e.name))) acc.push(p);
  }
  return acc;
}

let ko = 0, vus = 0;
for (const f of fichiers(path.join(RACINE, 'src')).concat(fichiers(path.join(RACINE, 'engine')))) {
  const src = fs.readFileSync(f, 'utf8');
  // ⚠️ On ne regarde QUE les chemins relatifs : les paquets npm ont leur propre
  // résolution, et `npm ci` les garantit. Ici on traque nos propres fichiers.
  for (const m of src.matchAll(/(?:^|\n)\s*import\s+[^'"]*?from\s+['"](\.[^'"]+)['"]/g)) {
    vus++;
    const cible = path.resolve(path.dirname(f), m[1]);
    if (!fs.existsSync(cible)) {
      ko++;
      console.log(`⛔ ${path.relative(RACINE, f)}`);
      console.log(`   importe « ${m[1]} » — CE FICHIER N'EXISTE PAS`);
    }
  }
}
console.log(ko
  ? `\n⛔ ${ko} import(s) orphelin(s) sur ${vus} — le build ÉCHOUERA.`
  : `\n✅ ${vus} imports relatifs, tous résolus.`);
process.exit(ko ? 1 : 0);
