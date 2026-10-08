'use strict';
// Turns a free-text request (Arabic or English) into an AppSpec using keyword rules.

const crypto = require('node:crypto');
const { COMPONENTS } = require('./components');

// Arabic normalisation so "حاسبة" / "حاسبه", "أ" / "ا", tashkeel etc. all match.
function normalize(s) {
  return String(s)
    .toLowerCase()
    .replace(/[ً-ٰٟـ]/g, '')
    .replace(/[أإآ]/g, 'ا')
    .replace(/ى/g, 'ي')
    .replace(/ة/g, 'ه')
    .replace(/ؤ/g, 'و')
    .replace(/ئ/g, 'ي');
}

const COLORS = [
  [['احمر', 'red'], '#D32F2F'],
  [['ازرق', 'blue'], '#1976D2'],
  [['اخضر', 'green'], '#2E7D32'],
  [['برتقالي', 'orange'], '#F57C00'],
  [['بنفسجي', 'purple'], '#7B1FA2'],
  [['وردي', 'pink'], '#C2185B'],
  [['اصفر', 'yellow'], '#F9A825'],
  [['اسود', 'black'], '#212121'],
  [['تركوازي', 'teal'], '#00838F'],
];

function extractName(prompt) {
  const ar = prompt.match(/(?:اسمه|اسمها|باسم|اسم التطبيق|تسمى|سمّه|سمه)\s+["«“']?([^\s"»”,،.؟?!']+)/);
  if (ar) return ar[1];
  const en = prompt.match(/(?:named|called)\s+["']?([A-Za-z0-9_-]+(?:\s[A-Za-z0-9_-]+)?)/i);
  if (en) return en[1].trim();
  return null;
}

function slug(name, seed) {
  const latin = String(name).toLowerCase().replace(/[^a-z0-9]/g, '').replace(/^[^a-z]+/, '');
  const hash = crypto.createHash('sha1').update(seed).digest('hex').slice(0, 6);
  return `com.appbuilder.${latin || 'app'}${hash}`.replace(/\.([0-9])/g, '.a$1');
}

function parse(prompt) {
  const text = String(prompt || '');
  const norm = normalize(text);
  const lang = /[؀-ۿ]/.test(text) ? 'ar' : 'en';

  const found = [];
  for (const comp of Object.values(COMPONENTS)) {
    let best = -1;
    let kw = null;
    for (const k of comp.keywords) {
      const i = norm.indexOf(normalize(k));
      if (i !== -1 && (best === -1 || i < best)) { best = i; kw = k; }
    }
    if (best !== -1) found.push({ id: comp.id, pos: best, keyword: kw });
  }
  found.sort((a, b) => a.pos - b.pos);
  const components = found.map(f => f.id);

  let color = '#00796B';
  for (const [words, hex] of COLORS) {
    if (words.some(w => norm.includes(normalize(w)))) { color = hex; break; }
  }

  const name =
    extractName(text) ||
    (components.length === 1
      ? COMPONENTS[components[0]].label[lang]
      : lang === 'ar' ? 'تطبيقي' : 'My App');

  const spec = {
    name,
    packageName: slug(name, text),
    lang,
    color,
    components: components.length ? components : [],
  };
  return { spec, matched: components.length > 0, matches: found };
}

module.exports = { parse, normalize };
