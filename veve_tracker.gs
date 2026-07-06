/**
 * ===== VEVE TRACKER =====
 * Transforme les données brutes du scrapeur (onglets "Data" + "PriceHistory")
 * en tracker : Dashboard, Marques, GraphFloor, Fiche Produit.
 *
 * Installation : Extensions > Apps Script > coller ce code > exécuter setupTracker()
 * Ensuite : menu "🛸 VeVe Tracker" dans le sheet.
 */

var DATA = 'Catalogue';
var PH = 'PriceHistory';
var FLOOR_MAX = 1e6; // au-delà = listing troll, ignoré dans les stats

// Couleurs
var C_DARK = '#1a1a2e';
var C_ACCENT = '#e94560';
var C_HEAD = '#16213e';
var C_LIGHT = '#f4f6fb';
var C_GREEN = '#1e8e3e';
var C_RED = '#d93025';

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('🛸 VeVe Tracker')
    .addItem('🔄 Tout actualiser', 'refreshAll')
    .addItem('🛠️ Reconstruire les pages', 'setupTracker')
    .addToUi();
}

/** À exécuter UNE FOIS pour tout construire. */
function setupTracker() {
  var ss = SpreadsheetApp.getActive();
  buildLookup(ss);
  buildDailyStats(ss);
  buildDashboard(ss);
  buildMarques(ss);
  buildGraphFloor(ss);
  buildFiche(ss);
  // Ordre des onglets
  var order = ['📊 Dashboard', '🏷️ Marques', '📈 GraphFloor', '🔍 Fiche Produit', DATA, PH];
  for (var i = 0; i < order.length; i++) {
    var sh = ss.getSheetByName(order[i]);
    if (sh) { ss.setActiveSheet(sh); ss.moveActiveSheet(i + 1); }
  }
  installTrigger();
  refreshAll();
  ss.setActiveSheet(ss.getSheetByName('📊 Dashboard'));
}

/** Trigger quotidien à 10h (le scrapeur passe vers 9h20). */
function installTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'refreshAll') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('refreshAll').timeBased().everyDays(1).atHour(10).create();
}

// ---------------------------------------------------------------- helpers

function getOrCreate(ss, name) {
  var sh = ss.getSheetByName(name);
  if (!sh) sh = ss.insertSheet(name);
  return sh;
}

function resetSheet(ss, name) {
  var sh = getOrCreate(ss, name);
  sh.getCharts().forEach(function (c) { sh.removeChart(c); });
  if (sh.getFilter()) sh.getFilter().remove();
  sh.clear();
  sh.clearConditionalFormatRules();
  sh.setHiddenGridlines(true);
  return sh;
}

function median(arr) {
  if (!arr.length) return '';
  var a = arr.slice().sort(function (x, y) { return x - y; });
  var m = Math.floor(a.length / 2);
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}

function toDay(v) {
  if (v instanceof Date) return Utilities.formatDate(v, Session.getScriptTimeZone(), 'yyyy-MM-dd');
  var s = String(v);
  return s.length >= 10 ? s.substring(0, 10) : s;
}

function num(v) {
  if (typeof v === 'number') return v;
  var n = parseFloat(String(v).replace(',', '.'));
  return isNaN(n) ? 0 : n;
}

function title(sh, cell, text) {
  sh.getRange(cell).setValue(text)
    .setFontSize(16).setFontWeight('bold').setFontColor('white').setBackground(C_DARK);
}

function header(sh, range) {
  sh.getRange(range).setFontWeight('bold').setFontColor('white').setBackground(C_HEAD);
}

function readData(ss) {
  var sh = ss.getSheetByName(DATA);
  var values = sh.getDataRange().getValues();
  values.shift(); // en-têtes
  return values.filter(function (r) { return r[0]; });
}

// ---------------------------------------------------------------- _Lookup

function buildLookup(ss) {
  var sh = resetSheet(ss, '_Lookup');
  sh.getRange('A1:D1').setValues([['label', 'uuid', '', 'liste_triee']]);
  sh.getRange('A2').setFormula('=ARRAYFORMULA(IF(Catalogue!A2:A="",,Catalogue!B2:B&" ["&Catalogue!E2:E&"]"))');
  sh.getRange('B2').setFormula('=ARRAYFORMULA(IF(Catalogue!A2:A="",,Catalogue!A2:A))');
  sh.getRange('D2').setFormula('=SORT(UNIQUE(FILTER(A2:A,A2:A<>"")))');
  sh.hideSheet();
}

// ---------------------------------------------------------------- _DailyStats

function buildDailyStats(ss) {
  var sh = getOrCreate(ss, '_DailyStats');
  if (sh.getLastRow() < 1) {
    sh.getRange('A1:D1').setValues([['Date', 'Items', 'Listings totaux', 'Floor médian']]);
  }
  sh.hideSheet();
}

// ---------------------------------------------------------------- Dashboard

function buildDashboard(ss) {
  var sh = resetSheet(ss, '📊 Dashboard');
  sh.setTabColor(C_ACCENT);
  sh.getRange('A1:K1').merge();
  title(sh, 'A1', '🛸 VEVE TRACKER — DASHBOARD');
  sh.getRange('A2').setFontColor('#888888').setFontStyle('italic');

  // KPIs
  var labels = ['Items', 'Marques', 'Séries', 'Avec listing', 'Listings totaux', 'Floor médian'];
  sh.getRange(4, 1, 1, 6).setValues([labels])
    .setFontWeight('bold').setFontColor('white').setBackground(C_HEAD)
    .setHorizontalAlignment('center');
  sh.getRange(5, 1, 1, 6).setFontSize(14).setFontWeight('bold')
    .setBackground(C_LIGHT).setHorizontalAlignment('center');
  sh.getRange('F5').setNumberFormat('$#,##0.00');

  sh.getRange('A8').setValue('📈 TOP 10 HAUSSES (7j)').setFontWeight('bold').setFontColor(C_GREEN);
  sh.getRange('F8').setValue('📉 TOP 10 BAISSES (7j)').setFontWeight('bold').setFontColor(C_RED);
  sh.getRange('A9:D9').setValues([['Produit', 'Marque', 'Floor', 'Var 7j']]);
  sh.getRange('F9:I9').setValues([['Produit', 'Marque', 'Floor', 'Var 7j']]);
  header(sh, 'A9:D9'); header(sh, 'F9:I9');
  sh.getRange('C10:C19').setNumberFormat('$#,##0.00');
  sh.getRange('H10:H19').setNumberFormat('$#,##0.00');
  sh.getRange('D10:D19').setNumberFormat('+0.0"%";-0.0"%"');
  sh.getRange('I10:I19').setNumberFormat('+0.0"%";-0.0"%"');

  sh.getRange('A22').setValue('🆕 NOUVEAUTÉS (dernier scan)').setFontWeight('bold');
  sh.getRange('A23:D23').setValues([['Produit', 'Marque', 'Catégorie', 'Prix boutique']]);
  header(sh, 'A23:D23');
  sh.getRange('D24:D33').setNumberFormat('$#,##0.00');

  sh.getRange('F22').setValue('📦 PAR CATÉGORIE').setFontWeight('bold');
  sh.getRange('F23:G23').setValues([['Catégorie', 'Items']]);
  header(sh, 'F23:G23');

  sh.getRange('A36').setValue('📅 TENDANCE QUOTIDIENNE').setFontWeight('bold');

  // vert / rouge sur les colonnes de variation
  var rules = [];
  ['D10:D19', 'I10:I19'].forEach(function (a1) {
    var r = sh.getRange(a1);
    rules.push(SpreadsheetApp.newConditionalFormatRule().whenNumberGreaterThan(0)
      .setFontColor(C_GREEN).setRanges([r]).build());
    rules.push(SpreadsheetApp.newConditionalFormatRule().whenNumberLessThan(0)
      .setFontColor(C_RED).setRanges([r]).build());
  });
  sh.setConditionalFormatRules(rules);

  sh.setColumnWidths(1, 1, 260);
  sh.setColumnWidths(6, 1, 260);
  sh.setFrozenRows(2);
}

// ---------------------------------------------------------------- Marques

function buildMarques(ss) {
  var sh = resetSheet(ss, '🏷️ Marques');
  sh.setTabColor('#0f3460');
  sh.getRange('A1:H1').merge();
  title(sh, 'A1', '🏷️ MARQUES');
  sh.getRange('A2').setFontColor('#888888').setFontStyle('italic');
  var head = ['Marque', 'Items', 'Séries', 'Listings', 'Floor min', 'Floor médian', 'Var 7j méd.', 'Var 30j méd.'];
  sh.getRange(3, 1, 1, head.length).setValues([head]);
  header(sh, 'A3:H3');
  sh.setFrozenRows(3);
  sh.setColumnWidths(1, 1, 240);
}

// ---------------------------------------------------------------- GraphFloor

function buildGraphFloor(ss) {
  var sh = resetSheet(ss, '📈 GraphFloor');
  sh.setTabColor('#533483');
  sh.getRange('A1:F1').merge();
  title(sh, 'A1', '📈 ÉVOLUTION DU FLOOR — choisis jusqu\'à 5 produits');

  var lookup = ss.getSheetByName('_Lookup');
  var rule = SpreadsheetApp.newDataValidation()
    .requireValueInRange(lookup.getRange('D2:D30000'), true)
    .setAllowInvalid(false).build();

  for (var i = 0; i < 5; i++) {
    sh.getRange(3 + i, 1).setValue('Produit ' + (i + 1)).setFontWeight('bold');
    sh.getRange(3 + i, 2, 1, 3).merge().setDataValidation(rule).setBackground(C_LIGHT);
    sh.getRange(3 + i, 7).setFormula('=IFERROR(VLOOKUP($B' + (3 + i) + ',_Lookup!$A:$B,2,FALSE),"")');
  }
  sh.hideColumns(7);

  // Bloc de données du graphique
  sh.getRange('A10').setValue('Date').setFontWeight('bold');
  var cols = ['B', 'C', 'D', 'E', 'F'];
  for (var j = 0; j < 5; j++) {
    sh.getRange(10, 2 + j).setFormula('=IF($B$' + (3 + j) + '="","–",$B$' + (3 + j) + ')');
    sh.getRange(cols[j] + '11').setFormula(
      '=IF($G$' + (3 + j) + '="",,ARRAYFORMULA(IF($A$11:$A$1500="",,IFERROR(' +
      'VLOOKUP($A$11:$A$1500,QUERY(PriceHistory!$A:$E,"select A, E where B = \'"&$G$' + (3 + j) + '&"\'",0),2,FALSE)))))'
    );
  }
  sh.getRange('A11').setFormula('=IFERROR(SORT(UNIQUE(FILTER(PriceHistory!$A$2:$A,PriceHistory!$A$2:$A<>""))))');
  header(sh, 'A10:F10');
  sh.getRange('B11:F1500').setNumberFormat('$#,##0.00');
  sh.setColumnWidth(1, 110);

  var chart = sh.newChart().asLineChart()
    .addRange(sh.getRange('A10:F1500'))
    .setNumHeaders(1)
    .setOption('title', 'Floor par produit ($)')
    .setOption('interpolateNulls', true)
    .setOption('curveType', 'function')
    .setOption('legend', { position: 'top' })
    .setOption('height', 460).setOption('width', 980)
    .setPosition(9, 8, 0, 0)
    .build();
  sh.insertChart(chart);
}

// ---------------------------------------------------------------- Fiche Produit

function buildFiche(ss) {
  var sh = resetSheet(ss, '🔍 Fiche Produit');
  sh.setTabColor('#e94560');
  sh.getRange('A1:E1').merge();
  title(sh, 'A1', '🔍 FICHE PRODUIT');

  var lookup = ss.getSheetByName('_Lookup');
  var rule = SpreadsheetApp.newDataValidation()
    .requireValueInRange(lookup.getRange('D2:D30000'), true)
    .setAllowInvalid(false).build();
  sh.getRange('A2').setValue('Produit :').setFontWeight('bold');
  sh.getRange('B2:E2').merge().setDataValidation(rule).setBackground(C_LIGHT);

  sh.getRange('G2').setFormula('=IFERROR(VLOOKUP($B$2,_Lookup!$A:$B,2,FALSE),"")');
  sh.getRange('G3').setFormula('=IFERROR(MATCH($G$2,Catalogue!$A:$A,0),"")');
  sh.hideColumns(7);

  var fields = [
    ['Marque', 'W'], ['Série', 'T'], ['Catégorie', 'C'], ['Rareté', 'E'],
    ['Édition', 'D'], ['Date de sortie', 'F'], ['Tirage', 'G'], ['Disponibles', 'H'],
    ['Prix boutique', 'J'], ['Floor actuel', 'K'], ['Listings', 'L'],
    ['All-time low', 'M'], ['All-time high', 'N'],
    ['Var 1j %', 'O'], ['Var 7j %', 'P'], ['Var 30j %', 'Q']
  ];
  for (var i = 0; i < fields.length; i++) {
    var row = 4 + i;
    sh.getRange(row, 1).setValue(fields[i][0]).setFontWeight('bold').setBackground(C_LIGHT);
    sh.getRange(row, 2).setFormula('=IF($G$3="","",INDEX(Catalogue!$' + fields[i][1] + ':$' + fields[i][1] + ',$G$3))');
  }
  sh.getRange('B12:B13').setNumberFormat('$#,##0.00'); // prix boutique, floor
  sh.getRange('B15:B16').setNumberFormat('$#,##0.00'); // ATL, ATH
  sh.getRange('B17:B19').setNumberFormat('+0.0"%";-0.0"%"'); // variations
  sh.getRange(20, 1).setValue('Lien').setFontWeight('bold').setBackground(C_LIGHT);
  sh.getRange(20, 2).setFormula('=IF($G$3="","",HYPERLINK(INDEX(Catalogue!$AC:$AC,$G$3),"Ouvrir sur VeVe"))');
  sh.getRange('D4:E14').merge();
  sh.getRange('D4').setFormula('=IF($G$3="","",IMAGE(INDEX(Catalogue!$AD:$AD,$G$3),1))');

  sh.getRange('A23').setValue('📜 HISTORIQUE').setFontWeight('bold');
  sh.getRange('A24').setFormula(
    '=IF($G$2="","Sélectionne un produit ci-dessus",' +
    'QUERY(PriceHistory!$A:$G,"select A, E, G where B = \'"&$G$2&"\' order by A label A \'Date\', E \'Floor\', G \'Listings\'",1))'
  );
  sh.getRange('B25:B2000').setNumberFormat('$#,##0.00');
  sh.setColumnWidth(1, 160); sh.setColumnWidth(2, 220);

  var chart = sh.newChart().asLineChart()
    .addRange(sh.getRange('A24:B2000'))
    .setNumHeaders(1)
    .setOption('title', 'Historique du floor ($)')
    .setOption('interpolateNulls', true)
    .setOption('legend', { position: 'none' })
    .setOption('height', 380).setOption('width', 700)
    .setPosition(23, 4, 0, 0)
    .build();
  sh.insertChart(chart);
}

// ---------------------------------------------------------------- REFRESH

/** Recalcule Dashboard + Marques + _DailyStats à partir de Data. Rapide (1 lecture). */
function refreshAll() {
  var ss = SpreadsheetApp.getActive();
  var rows = readData(ss);
  var now = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'dd/MM/yyyy HH:mm');

  // ---- agrégats globaux
  var brands = {}, series = {}, cats = {};
  var floors = [], listingsTot = 0, withListing = 0;
  var lastDay = '';
  rows.forEach(function (r) {
    var floor = num(r[10]), lst = num(r[11]);
    var b = r[22] || '(sans marque)';
    if (!brands[b]) brands[b] = { n: 0, series: {}, lst: 0, floors: [], v7: [], v30: [] };
    brands[b].n++;
    if (r[21]) brands[b].series[r[21]] = 1;
    if (r[19]) series[r[21] || r[19]] = 1;
    cats[r[2] || '?'] = (cats[r[2] || '?'] || 0) + 1;
    brands[b].lst += lst;
    listingsTot += lst;
    if (floor > 0 && floor < FLOOR_MAX) {
      floors.push(floor);
      brands[b].floors.push(floor);
      if (lst > 0) withListing++;
    }
    if (r[15] !== '' && r[15] !== null) brands[b].v7.push(num(r[15]));
    if (r[16] !== '' && r[16] !== null) brands[b].v30.push(num(r[16]));
    var d = toDay(r[33]);
    if (d > lastDay) lastDay = d;
  });

  // ---- Dashboard
  var dash = ss.getSheetByName('📊 Dashboard');
  dash.getRange('A2').setValue('Dernière actualisation : ' + now + ' — scan du ' + lastDay);
  dash.getRange(5, 1, 1, 6).setValues([[
    rows.length, Object.keys(brands).length, Object.keys(series).length,
    withListing, listingsTot, median(floors)
  ]]);

  // top movers 7j (fallback 1j si vide)
  var candidates = rows.filter(function (r) {
    var f = num(r[10]);
    return f > 0 && f < FLOOR_MAX && num(r[9]) > 0;
  });
  var key = 15; // change_7d_pct
  var movers = candidates.filter(function (r) { return r[key] !== '' && r[key] !== null && num(r[key]) !== 0; });
  var moversLabel = '7j';
  if (movers.length < 5) {
    key = 14; moversLabel = '1j';
    movers = candidates.filter(function (r) { return r[key] !== '' && r[key] !== null && num(r[key]) !== 0; });
  }
  movers.sort(function (a, b) { return num(b[key]) - num(a[key]); });
  dash.getRange('A8').setValue('📈 TOP 10 HAUSSES (' + moversLabel + ')');
  dash.getRange('F8').setValue('📉 TOP 10 BAISSES (' + moversLabel + ')');
  var up = [], down = [];
  for (var i = 0; i < 10; i++) {
    var u = movers[i], d = movers[movers.length - 1 - i];
    up.push(u ? [u[1] + ' [' + u[4] + ']', u[22], num(u[10]), num(u[key])] : ['', '', '', '']);
    down.push(d && num(d[key]) < 0 ? [d[1] + ' [' + d[4] + ']', d[22], num(d[10]), num(d[key])] : ['', '', '', '']);
  }
  dash.getRange(10, 1, 10, 4).setValues(up);
  dash.getRange(10, 6, 10, 4).setValues(down);
  if (!movers.length) dash.getRange('A10').setValue('Pas encore de données de variation (l\'historique se construit).');

  // nouveautés = first_seen au dernier jour scanné
  var news = rows.filter(function (r) { return toDay(r[32]) === lastDay; })
    .slice(0, 10)
    .map(function (r) { return [r[1] + ' [' + r[4] + ']', r[22], r[2], num(r[9])]; });
  while (news.length < 10) news.push(['', '', '', '']);
  dash.getRange(24, 1, 10, 4).setValues(news);

  // catégories
  var catRows = Object.keys(cats).map(function (c) { return [c, cats[c]]; })
    .sort(function (a, b) { return b[1] - a[1]; }).slice(0, 8);
  while (catRows.length < 8) catRows.push(['', '']);
  dash.getRange(24, 6, 8, 2).setValues(catRows);

  // ---- _DailyStats (upsert du jour)
  var stats = ss.getSheetByName('_DailyStats');
  var sVals = stats.getDataRange().getValues();
  var todayRow = [lastDay, rows.length, listingsTot, median(floors)];
  var found = false;
  for (var s = 1; s < sVals.length; s++) {
    if (toDay(sVals[s][0]) === lastDay) { stats.getRange(s + 1, 1, 1, 4).setValues([todayRow]); found = true; break; }
  }
  if (!found) stats.appendRow(todayRow);

  // graphiques Dashboard (recréés à chaque refresh)
  dash.getCharts().forEach(function (c) { dash.removeChart(c); });
  dash.insertChart(dash.newChart().asPieChart()
    .addRange(dash.getRange('F23:G31')).setNumHeaders(1)
    .setOption('title', 'Répartition par catégorie')
    .setOption('height', 300).setOption('width', 420)
    .setPosition(22, 10, 0, 0).build());
  dash.insertChart(dash.newChart().asLineChart()
    .addRange(stats.getRange('A1:D400')).setNumHeaders(1)
    .setOption('title', 'Tendance quotidienne (items / listings / floor médian)')
    .setOption('interpolateNulls', true)
    .setOption('height', 340).setOption('width', 980)
    .setPosition(37, 1, 0, 0).build());

  // ---- Marques
  var mq = ss.getSheetByName('🏷️ Marques');
  mq.getRange('A2').setValue('Dernière actualisation : ' + now);
  var mRows = Object.keys(brands).map(function (b) {
    var o = brands[b];
    return [b, o.n, Object.keys(o.series).length, o.lst,
      o.floors.length ? Math.min.apply(null, o.floors) : '',
      median(o.floors), median(o.v7), median(o.v30)];
  }).sort(function (a, b) { return b[1] - a[1]; });

  var old = mq.getLastRow();
  if (old > 3) mq.getRange(4, 1, old - 3, 8).clearContent();
  if (mRows.length) {
    mq.getRange(4, 1, mRows.length, 8).setValues(mRows);
    mq.getRange(4, 5, mRows.length, 2).setNumberFormat('$#,##0.00');
    mq.getRange(4, 7, mRows.length, 2).setNumberFormat('+0.0"%";-0.0"%"');
    if (mq.getFilter()) mq.getFilter().remove();
    mq.getRange(3, 1, mRows.length + 1, 8).createFilter();
    var rules = [
      SpreadsheetApp.newConditionalFormatRule().whenNumberGreaterThan(0).setFontColor(C_GREEN)
        .setRanges([mq.getRange(4, 7, mRows.length, 2)]).build(),
      SpreadsheetApp.newConditionalFormatRule().whenNumberLessThan(0).setFontColor(C_RED)
        .setRanges([mq.getRange(4, 7, mRows.length, 2)]).build()
    ];
    mq.setConditionalFormatRules(rules);
  }
}
