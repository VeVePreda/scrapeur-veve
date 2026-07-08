/**
 * VeVe Tracker Builder — v4 (nettoyage minimal)
 * Exécuter la fonction : buildTracker
 *
 * Objectif : ne garder que les pages indispensables (donnée brute).
 * Onglets visibles après passage :
 *   🟢C-COMICS, 🔵C-COLLECTIBLE, PriceHistory, EditionsHistory,
 *   DropRevenue, ChainItems, ChainActivity, Pseudos, Logs
 *   (+ ChainMeta masqué : marque-page technique du scrapeur chain)
 *
 * Ce script :
 *   1. Supprime tous les onglets non indispensables (dont Stats et Marques).
 *   2. Supprime l'onglet Logs à l'ancien format (le scraper le recrée proprement).
 *   3. Splitte l'ancien "Catalogue" s'il existe encore.
 *   4. Masque ChainMeta (jamais supprimé : sa perte = re-backfill complet).
 *   5. Range l'ordre des onglets.
 * Rejouable sans risque.
 */

var COMICS_SHEET = '🟢C-COMICS';
var COLLECT_SHEET = '🔵C-COLLECTIBLE';
var DELETE_TABS = ['RunLog', 'PseudoRunLog', 'ChainRunLog', 'RevenueSummary',
  'ChainStats', 'ChainTopAccounts', 'Floor Chart', 'Dashboard', 'Top Movers',
  'Stats', 'Marques'];
var TAB_ORDER = [COMICS_SHEET, COLLECT_SHEET, 'PriceHistory', 'EditionsHistory',
  'DropRevenue', 'ChainItems', 'ChainActivity', 'Pseudos', 'Logs'];

function buildTracker() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();

  // 1. Onglets non indispensables
  DELETE_TABS.forEach(function (n) {
    var s = ss.getSheetByName(n);
    if (s) ss.deleteSheet(s);
  });

  // 2. Onglet Logs à l'ancien format (A1 commence par 🪵) -> recréé par le scraper
  var logsSheet = ss.getSheetByName('Logs');
  if (logsSheet && String(logsSheet.getRange('A1').getValue()).indexOf('🪵') === 0) {
    ss.deleteSheet(logsSheet);
  }

  // 3. Split de l'ancien Catalogue (si encore présent)
  splitCatalogue_(ss);

  // 4. ChainMeta : marque-page du scrapeur -> masqué, jamais supprimé
  var meta = ss.getSheetByName('ChainMeta');
  if (meta && !meta.isSheetHidden()) meta.hideSheet();

  // 5. Ordre des onglets
  var pos = 1;
  TAB_ORDER.forEach(function (n) {
    var s = ss.getSheetByName(n);
    if (s) { ss.setActiveSheet(s); ss.moveActiveSheet(pos); pos++; }
  });
  var home = ss.getSheetByName(COMICS_SHEET);
  if (home) ss.setActiveSheet(home);
  SpreadsheetApp.flush();
}

/* ================= Split du catalogue ================= */

function splitCatalogue_(ss) {
  var cat = ss.getSheetByName('Catalogue');
  if (!cat) return; // déjà migré (par ce script ou par le scraper)

  var data = cat.getDataRange().getValues();
  if (data.length < 2) { ss.deleteSheet(cat); return; }
  var headers = data[0].map(function (h) { return String(h).trim(); });
  var ci = headers.indexOf('category');
  if (ci === -1) throw new Error('Colonne "category" introuvable dans Catalogue');

  var comics = [], collect = [];
  for (var r = 1; r < data.length; r++) {
    if (String(data[r][ci]).toLowerCase() === 'comic') comics.push(data[r]);
    else collect.push(data[r]);
  }

  [[COMICS_SHEET, comics, '#0f9d58'], [COLLECT_SHEET, collect, '#4285f4']].forEach(function (spec) {
    var old = ss.getSheetByName(spec[0]);
    if (old) ss.deleteSheet(old);
    var sh = ss.insertSheet(spec[0]);
    sh.setTabColor(spec[2]);
    sh.getRange(1, 1, 1, headers.length).setValues([data[0]])
      .setFontWeight('bold').setBackground('#263238').setFontColor('#ffffff');
    if (spec[1].length) sh.getRange(2, 1, spec[1].length, headers.length).setValues(spec[1]);
    sh.setFrozenRows(1);
  });

  ss.deleteSheet(cat);
}
