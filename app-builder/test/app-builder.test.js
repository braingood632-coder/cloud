'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { parse, normalize } = require('../server/src/parser');
const { generate, normalizeSpec, javaDir } = require('../server/src/generator');
const { COMPONENTS } = require('../server/src/components');
const { parseFileBlocks, toProjectFiles } = require('../server/src/llm');

// Cheap structural check for Kotlin sources: balanced braces/parens outside of string literals.
function balanced(src) {
  const stack = [];
  const pairs = { ')': '(', ']': '[', '}': '{' };
  let inStr = false;
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (inStr) {
      if (ch === '\\') i++;
      else if (ch === '"') inStr = false;
      continue;
    }
    if (ch === '"') { inStr = true; continue; }
    if ('([{'.includes(ch)) stack.push(ch);
    else if (pairs[ch] && stack.pop() !== pairs[ch]) return false;
  }
  return stack.length === 0 && !inStr;
}

test('normalize unifies Arabic letter variants', () => {
  assert.equal(normalize('حاسبة'), normalize('حاسبه'));
  assert.equal(normalize('أحمر'), 'احمر');
});

test('parses an Arabic request with name, color and two components', () => {
  const { spec, matched } = parse('سوي لي تطبيق قائمة مهام وعداد اسمه مهامي لونه ازرق');
  assert.equal(matched, true);
  assert.deepEqual(spec.components, ['todo', 'counter']);
  assert.equal(spec.name, 'مهامي');
  assert.equal(spec.color, '#1976D2');
  assert.equal(spec.lang, 'ar');
  assert.match(spec.packageName, /^com\.appbuilder\.[a-z][a-z0-9]*$/);
});

test('parses an English request', () => {
  const { spec } = parse('make a calculator and a stopwatch app called QuickTools');
  assert.deepEqual(spec.components, ['calculator', 'stopwatch']);
  assert.equal(spec.name, 'QuickTools');
  assert.equal(spec.lang, 'en');
});

test('unknown idea is reported as unmatched', () => {
  const { matched, spec } = parse('تطبيق لحجز المواعيد في المطاعم');
  assert.equal(matched, false);
  assert.deepEqual(spec.components, []);
});

test('normalizeSpec rejects unsafe input', () => {
  const s = normalizeSpec({ name: 'a"b$c\\d<e>', packageName: 'Bad Pkg', color: 'red', components: ['nope', 'dice', 'dice'] });
  assert.equal(s.name, 'abcde');
  assert.equal(s.packageName, 'com.appbuilder.app');
  assert.equal(s.color, '#00796B');
  assert.deepEqual(s.components, ['dice']);
});

test('every component generates structurally valid Kotlin in both languages', () => {
  for (const lang of ['ar', 'en']) {
    const { files } = generate({ name: 'Test', packageName: 'com.appbuilder.test', lang, color: '#123456', components: Object.keys(COMPONENTS) });
    const dir = javaDir({ packageName: 'com.appbuilder.test' });
    const kt = Object.entries(files).filter(([p]) => p.endsWith('.kt'));
    assert.equal(kt.length, Object.keys(COMPONENTS).length + 1);
    for (const [p, src] of kt) {
      assert.ok(p.startsWith(dir), p);
      assert.ok(src.startsWith('package com.appbuilder.test\n'), p);
      assert.ok(balanced(src), `unbalanced: ${p}`);
    }
    const main = files[`${dir}/MainActivity.kt`];
    for (const c of Object.values(COMPONENTS)) assert.ok(main.includes(`${c.fn}()`), c.fn);
    assert.ok(main.includes(lang === 'ar' ? 'LayoutDirection.Rtl' : 'LayoutDirection.Ltr'));
  }
});

test('project has the Gradle files an Android build needs', () => {
  const { files } = generate({ name: 'X', packageName: 'com.appbuilder.x', components: ['counter'] });
  for (const f of ['settings.gradle.kts', 'build.gradle.kts', 'app/build.gradle.kts', 'app/src/main/AndroidManifest.xml']) {
    assert.ok(files[f], f);
  }
  assert.match(files['app/build.gradle.kts'], /applicationId = "com\.appbuilder\.x"/);
});

test('LLM file blocks are parsed, fenced, and package-forced', () => {
  const out = [
    '=== FILE: MainActivity.kt ===',
    '```kotlin',
    'package wrong.pkg',
    'class MainActivity : ComponentActivity()',
    '```',
    '=== FILE: ../Evil.kt ===',
    'x',
    '=== FILE: Screen.kt ===',
    'fun A() {}',
    '=== END ===',
  ].join('\n');
  const blocks = parseFileBlocks(out, 'com.appbuilder.y');
  assert.deepEqual(Object.keys(blocks).sort(), ['MainActivity.kt', 'Screen.kt']);
  assert.ok(blocks['MainActivity.kt'].startsWith('package com.appbuilder.y\n'));
  assert.ok(!blocks['MainActivity.kt'].includes('wrong.pkg'));
  assert.ok(!blocks['MainActivity.kt'].includes('```'));
  const files = toProjectFiles(blocks, { packageName: 'com.appbuilder.y' });
  assert.ok(Object.keys(files).every(p => p.startsWith('app/src/main/java/com/appbuilder/y/')));
});
