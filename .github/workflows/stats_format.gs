/**
 * HABILLAGE de la page 📊 STATS — Apps Script (Extensions → Apps Script).
 * v10 (12/07) : + bloc 🔥 SYNTHÈSE BURNS en T37.
 * v9 (12/07) : reorganisation demandee par Preda —
 *   T8   : 💰 TAILLE DES PORTEFEUILLES (3 blocs cote a cote, T-AD)
 *   T22  : 🩺 SANTÉ DES SOURCES (sous les tailles)
 *   49   : 📅 PAR MOIS (A-R) || 📈 PULSE mois (T-AC)   [+ colonne Rétention %]
 *   116  : 📅 PAR ANNÉE (A-R) || 📈 PULSE année (T-AC)
 *   132  : ℹ️ NOTES & LÉGENDES (colonne A)
 *   Les blocs 🔄 RÉTENTION (mois et année) sont SUPPRIMES (infos dans PULSE).
 * A re-executer apres l'upload v14.
 */

var STATS_TAB = '📊 STATS';

function formatStatsPage() {
  var sh = SpreadsheetApp.getActive().getSheetByName(STATS_TAB);
  if (!sh) throw new Error('Onglet "' + STATS_TAB + '" introuvable.');

  sh.clearFormats();
  sh.getRange(1, 1, sh.getMaxRows(), sh.getMaxColumns()).breakApart();
  sh.getBandings().forEach(function (b) { b.remove(); });
  sh.setFrozenRows(0);

  var NOIR = '#0b0b0b', OR = '#f5b301', VIOLET = '#7b2cbf',
      VIOLET_PALE = '#f5edfb', GRIS = '#f3f3f3',
      BLEU = '#cfe2f3', VERT = '#d9ead3', MAUVE = '#d9d2e9',
      JAUNE = '#fff2cc', ROUGE = '#f4cccc';
  var P_TX = '#E2EBF3', P_ACT = '#e7efe4', P_LST = '#e7e3ef',
      P_REV = '#F8F3E0', P_OMI = '#F3E0E0';

  // ---- Titre + bandeau semaine + 12 KPI ----
  sh.getRange('A1:R1').merge().setBackground(NOIR).setFontColor(OR)
    .setFontWeight('bold').setFontSize(15).setHorizontalAlignment('center');
  sh.getRange('A2:R2').merge().setBackground(NOIR).setFontColor('#cccccc')
    .setFontStyle('italic').setFontSize(9).setHorizontalAlignment('center');
  sh.getRange('A4:R4').merge().setBackground(VIOLET).setFontColor('#ffffff')
    .setFontWeight('bold').setHorizontalAlignment('center');
  sh.getRange('A5:L5').setFontWeight('bold').setFontColor('#666666')
    .setFontSize(9).setHorizontalAlignment('center');
  sh.getRange('A6:L6').setFontWeight('bold').setFontSize(12)
    .setHorizontalAlignment('center');
  sh.getRange('A6').setNumberFormat('#,##0 $');
  sh.getRange('B6:L6').setNumberFormat('#,##0');

  // ---- Quotidien : groupes (8) + en-tetes (9) + donnees (10-46) ----
  groupes_(sh, 8, BLEU, VERT, MAUVE, JAUNE, ROUGE);
  entetes_(sh, 9, P_TX, P_ACT, P_LST, P_REV, P_OMI, GRIS);
  formatsData_(sh, 10, 46);
  var banding = sh.getRange('A10:R46')
    .applyRowBanding(SpreadsheetApp.BandingTheme.LIGHT_GREY, false, false);
  banding.setFirstRowColor('#ffffff').setSecondRowColor(VIOLET_PALE);
  sh.getRange('A10:A46').setHorizontalAlignment('center');
  sh.getRange('B10:B46').setFontSize(9).setHorizontalAlignment('left');

  // ---- 💰 TAILLE DES PORTEFEUILLES : T8 (banniere) / T9 (en-tetes) / 10-20 --
  sh.getRange('T9:AD9').setBackground(GRIS).setFontWeight('bold')
    .setFontSize(9).setHorizontalAlignment('center');
  sh.getRange('T10:T20').setFontSize(9);
  sh.getRange('X10:X20').setFontSize(9);
  sh.getRange('AB10:AB20').setFontSize(9);
  sh.getRange('U10:U20').setNumberFormat('#,##0');
  sh.getRange('Y10:Y20').setNumberFormat('#,##0');
  sh.getRange('AC10:AC20').setNumberFormat('#,##0');
  sh.getRange('V10:V20').setNumberFormat('0.0"%"');
  sh.getRange('Z10:Z20').setNumberFormat('0.0"%"');
  sh.getRange('AD10:AD20').setNumberFormat('0.0"%"');

  // ---- 🩺 SANTÉ DES SOURCES : T22 (titre) / T23 (en-tetes) / 24-35 ----
  sh.getRange('T22:W22').merge().setBackground(VIOLET).setFontColor('#ffffff')
    .setFontWeight('bold');
  sh.getRange('T23:W23').setBackground(GRIS).setFontWeight('bold');
  sh.getRange('U24:U35').setHorizontalAlignment('center');

  // ---- 🔥 SYNTHÈSE BURNS : T37 (titre) / T38 (en-tetes) / 39-49 ----
  sh.getRange('T37:W37').merge().setBackground(VIOLET).setFontColor('#ffffff')
    .setFontWeight('bold');
  sh.getRange('T38:W38').setBackground(GRIS).setFontWeight('bold');
  sh.getRange('U39:U49').setNumberFormat('#,##0.###')
    .setHorizontalAlignment('right');
  sh.getRange('V39:V49').setFontSize(9).setFontColor('#666666');

  // ---- 📅 PAR MOIS : groupes (50) + en-tetes (51) + donnees (52-115) ----
  groupes_(sh, 50, BLEU, VERT, MAUVE, JAUNE, ROUGE);
  entetes_(sh, 51, P_TX, P_ACT, P_LST, P_REV, P_OMI, GRIS);
  formatsData_(sh, 52, 115);
  sh.getRange('A52:A115').setHorizontalAlignment('center');
  sh.getRange('B52:B115').setFontSize(9).setHorizontalAlignment('center');
  pulse_(sh, 51, 115, GRIS);

  // ---- 📅 PAR ANNÉE : groupes (117) + en-tetes (118) + donnees (119-130) ----
  groupes_(sh, 117, BLEU, VERT, MAUVE, JAUNE, ROUGE);
  entetes_(sh, 118, P_TX, P_ACT, P_LST, P_REV, P_OMI, GRIS);
  formatsData_(sh, 119, 130);
  sh.getRange('A119:A130').setHorizontalAlignment('center')
    .setFontWeight('bold');
  sh.getRange('B119:B130').setFontSize(9).setHorizontalAlignment('center');
  pulse_(sh, 118, 130, GRIS);

  // ---- ℹ️ NOTES & LÉGENDES (A132, sous le tableau annuel) ----
  sh.getRange('A133:A160').setFontSize(9).setFontColor('#444444')
    .setWrapStrategy(SpreadsheetApp.WrapStrategy.OVERFLOW);

  // ---- Largeurs ----
  sh.setColumnWidth(1, 92);
  sh.setColumnWidth(2, 170);
  for (var c = 3; c <= 18; c++) sh.setColumnWidth(c, 70);
  sh.setColumnWidth(19, 24);                 // S : gouttiere
  sh.setColumnWidth(20, 260);                // T : sante / tranches / Mois
  sh.setColumnWidth(21, 130);
  sh.setColumnWidth(22, 90);
  sh.setColumnWidth(23, 110);
  for (var c2 = 24; c2 <= 30; c2++) sh.setColumnWidth(c2, 90);   // X-AD

  SpreadsheetApp.getActive().toast('Habillage 📊 STATS v10 pose ✔');
}

function groupes_(sh, row, bleu, vert, mauve, jaune, rouge) {
  groupe_(sh, 'C' + row + ':G' + row, bleu);
  groupe_(sh, 'H' + row + ':J' + row, vert);
  groupe_(sh, 'K' + row + ':L' + row, mauve);
  groupe_(sh, 'M' + row + ':O' + row, jaune);
  groupe_(sh, 'P' + row + ':R' + row, rouge);
}

function groupe_(sh, a1, couleur) {
  sh.getRange(a1).merge().setBackground(couleur)
    .setFontWeight('bold').setHorizontalAlignment('center');
}

function entetes_(sh, row, pTx, pAct, pLst, pRev, pOmi, gris) {
  sh.getRange('A' + row + ':R' + row).setFontWeight('bold')
    .setHorizontalAlignment('center').setBackground(gris);
  sh.getRange('C' + row + ':G' + row).setBackground(pTx);
  sh.getRange('H' + row + ':J' + row).setBackground(pAct);
  sh.getRange('K' + row + ':L' + row).setBackground(pLst);
  sh.getRange('M' + row + ':O' + row).setBackground(pRev);
  sh.getRange('P' + row + ':R' + row).setBackground(pOmi);
}

function formatsData_(sh, r1, r2) {
  sh.getRange('C' + r1 + ':L' + r2).setNumberFormat('#,##0');
  sh.getRange('M' + r1 + ':N' + r2).setNumberFormat('#,##0 $');
  sh.getRange('O' + r1 + ':O' + r2).setNumberFormat('"~"#,##0 $');
  sh.getRange('P' + r1 + ':P' + r2).setNumberFormat('"~"#,##0 $');
  sh.getRange('Q' + r1 + ':R' + r2).setNumberFormat('#,##0');
}

/** 📈 PULSE (T-AC) : en-tetes ligne `head`, donnees jusqu'a `r2`. */
function pulse_(sh, head, r2, gris) {
  var r1 = head + 1;
  sh.getRange('T' + head + ':AC' + head).setFontWeight('bold')
    .setBackground(gris).setFontSize(9).setHorizontalAlignment('center');
  sh.getRange('T' + r1 + ':T' + r2).setHorizontalAlignment('center');
  sh.getRange('U' + r1 + ':X' + r2).setNumberFormat('#,##0');
  sh.getRange('Y' + r1 + ':Y' + r2).setNumberFormat('0.00');
  sh.getRange('Z' + r1 + ':AA' + r2).setNumberFormat('#,##0');
  sh.getRange('AB' + r1 + ':AC' + r2).setNumberFormat('0.0"%"');
}
// FIN stats_format.gs v10
