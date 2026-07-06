/**
 * VeVe Tracker Builder — v3 (migration / nettoyage)
 * Exécuter la fonction : buildTracker
 *
 * Depuis la v3, le scraper Python écrit lui-même les onglets consolidés :
 *   - "Stats"  (revenus estimés + activité on-chain, fenêtres 24h/48h/7j/30j/Total)
 *   - "Logs"   (runs catalogue / pseudos / chain, purgés à 7 jours)
 *   - "🟢C-COMICS" / "🔵C-COLLECTIBLE" (catalogue splitté)
 *   - "ChainMeta" reste mais est MASQUÉ (marque-page technique du scrapeur chain).
 *
 * Ce script ne sert donc qu'à :
 *   1. Supprimer les anciens onglets devenus inutiles.
 *   2. Splitter l'ancien "Catalogue" s'il existe encore (sinon le scraper le fera).
 *   3. Masquer ChainMeta s'il est visible.
 *   4. Reconstruire l'onglet "Marques" (formules dynamiques sur les 2 catalogues).
 *   5. Ranger l'ordre des onglets.
 * Rejouable sans risque.
 */

var COMICS_SHEET = '🟢C-COMICS';
var COLLECT_SHEET = '🔵C-COLLECTIBLE';
var DELETE_TABS = ['RunLog', 'PseudoRunLog', 'ChainRunLog', 'RevenueSummary',
  'ChainStats', 'ChainTopAccounts', 'Floor Chart', 'Dashboard', 'Top Movers'];
var TAB_ORDER = ['Stats', 'Marques', COMICS_SHEET, COLLECT_SHEET, 'PriceHistory',
  'EditionsHistory', 'DropRevenue', 'ChainItems', 'ChainActivity', 'Pseudos', 'Logs'];

function buildTracker() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();

  // 1. Anciens onglets
  DELETE_TABS.forEach(function (n) {
    var s = ss.getSheetByName(n);
    if (s) ss.deleteSheet(s);
  });

  // 2. Split de l'ancien Catalogue (si encore présent)
  splitCatalogue_(ss);

  // 3. ChainMeta : marque-page du scrapeur -> masqué, jamais supprimé
  var meta = ss.getSheetByName('ChainMeta');
  if (meta && !meta.isSheetHidden()) meta.hideSheet();

  // 4. Marques
  buildMarques_(ss);

  // 5. Ordre des onglets
  var pos = 1;
  TAB_ORDER.forEach(function (n) {
    var s = ss.getSheetByName(n);
    if (s) { ss.setActiveSheet(s); ss.moveActiveSheet(pos); pos++; }
  });
  var home = ss.getSheetByName('Stats') || ss.getSheetByName('Marques');
  if (home) ss.setActiveSheet(home);
  SpreadsheetApp.flush();
}

/* ================= Helpers ================= */

function sheetData_(ss, name) {
  var sh = ss.getSheetByName(name);
  if (!sh || sh.getLastRow() < 1) return null;
  var vals = sh.getDataRange().getValues();
  if (!vals.length) return null;
  return { headers: vals[0].map(function (h) { return String(h).trim(); }), rows: vals.slice(1) };
}

function colLetter_(n) {
  var s = '';
  while (n > 0) { var m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); }
  return s;
}

// Locale FR : convertit les virgules (hors chaînes) en points-virgules
function loc_(f) {
  var out = '', inDq = false;
  for (var i = 0; i < f.length; i++) {
    var ch = f.charAt(i);
    if (ch === '"') inDq = !inDq;
    out += (ch === ',' && !inDq) ? ';' : ch;
  }
  return out;
}

function fx_(sh, a1, formula) { sh.getRange(a1).setFormula(loc_(formula)); return sh.getRange(a1); }

function freshSheet_(ss, name, tabColor) {
  var old = ss.getSheetByName(name);
  if (old) ss.deleteSheet(old);
  var sh = ss.insertSheet(name);
  if (tabColor) sh.setTabColor(tabColor);
  return sh;
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
    var sh = freshSheet_(ss, spec[0], spec[2]);
    sh.getRange(1, 1, 1, headers.length).setValues([data[0]])
      .setFontWeight('bold').setBackground('#263238').setFontColor('#ffffff');
    if (spec[1].length) sh.getRange(2, 1, spec[1].length, headers.length).setValues(spec[1]);
    sh.setFrozenRows(1);
    ['storePrice', 'market_lowestOffer', 'allTimeLow', 'allTimeHigh'].forEach(function (h) {
      var i = headers.indexOf(h);
      if (i > -1) sh.getRange(2, i + 1, Math.max(spec[1].length, 1), 1).setNumberFormat('#,##0.00');
    });
    ['change_1d_pct', 'change_7d_pct', 'change_30d_pct'].forEach(function (h) {
      var i = headers.indexOf(h);
      if (i > -1) sh.getRange(2, i + 1, Math.max(spec[1].length, 1), 1).setNumberFormat('+0.0"%";-0.0"%"');
    });
  });

  ss.deleteSheet(cat);
}

/* ================= Onglet Marques ================= */

function buildMarques_(ss) {
  var comics = sheetData_(ss, COMICS_SHEET);
  if (!comics) return; // catalogue pas encore splitté ni resynchronisé
  var H = comics.headers;
  function C(h) { var i = H.indexOf(h); if (i === -1) throw new Error('Colonne ' + h + ' absente'); return 'Col' + (i + 1); }
  var lastCol = colLetter_(H.length);

  var sh = freshSheet_(ss, 'Marques', '#f4b400');
  var stack = "{'" + COMICS_SHEET + "'!A2:" + lastCol + ";'" + COLLECT_SHEET + "'!A2:" + lastCol + '}';
  var q = 'select ' + C('brand_name') + ', count(' + C('veve_uuid') + '), sum(' + C('market_lowestOffer') +
    '), avg(' + C('market_lowestOffer') + '), min(' + C('market_lowestOffer') + '), sum(' + C('market_totalListings') +
    '), avg(' + C('change_1d_pct') + '), avg(' + C('change_7d_pct') + '), avg(' + C('change_30d_pct') +
    ') where ' + C('veve_uuid') + ' is not null and ' + C('brand_name') + ' is not null group by ' + C('brand_name') +
    ' order by sum(' + C('market_lowestOffer') + ') desc' +
    " label " + C('brand_name') + " 'Marque', count(" + C('veve_uuid') + ") 'Nb produits', sum(" + C('market_lowestOffer') +
    ") 'Floor total', avg(" + C('market_lowestOffer') + ") 'Floor moyen', min(" + C('market_lowestOffer') +
    ") 'Floor min', sum(" + C('market_totalListings') + ") 'Listings', avg(" + C('change_1d_pct') +
    ") 'Var 1j %', avg(" + C('change_7d_pct') + ") 'Var 7j %', avg(" + C('change_30d_pct') + ") 'Var 30j %'";
  var qBase = 'select ' + C('brand_name') + ', count(' + C('veve_uuid') + '), sum(' + C('market_lowestOffer') +
    '), avg(' + C('market_lowestOffer') + '), min(' + C('market_lowestOffer') + '), sum(' + C('market_totalListings') +
    ') where ' + C('veve_uuid') + ' is not null and ' + C('brand_name') + ' is not null group by ' + C('brand_name') +
    ' order by sum(' + C('market_lowestOffer') + ') desc' +
    " label " + C('brand_name') + " 'Marque', count(" + C('veve_uuid') + ") 'Nb produits', sum(" + C('market_lowestOffer') +
    ") 'Floor total', avg(" + C('market_lowestOffer') + ") 'Floor moyen', min(" + C('market_lowestOffer') +
    ") 'Floor min', sum(" + C('market_totalListings') + ") 'Listings'";
  fx_(sh, 'A1', '=IFERROR(QUERY(' + stack + ', "' + q + '", 0), QUERY(' + stack + ', "' + qBase + '", 0))');
  SpreadsheetApp.flush();
  sh.getRange('A1:I1').setFontWeight('bold').setBackground('#1a237e').setFontColor('#ffffff');
  sh.setFrozenRows(1);
  sh.getRange('C2:E2000').setNumberFormat('#,##0.00');
  sh.getRange('G2:I2000').setNumberFormat('+0.0"%";-0.0"%"');
  var rules = [
    SpreadsheetApp.newConditionalFormatRule().whenNumberGreaterThan(0).setFontColor('#0b8043')
      .setRanges([sh.getRange('G2:I2000')]).build(),
    SpreadsheetApp.newConditionalFormatRule().whenNumberLessThan(0).setFontColor('#cc0000')
      .setRanges([sh.getRange('G2:I2000')]).build()
  ];
  sh.setConditionalFormatRules(rules);
  sh.autoResizeColumns(1, 9);
  sh.setColumnWidth(1, 220);
}
