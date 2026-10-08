'use strict';
// Optional LLM layer (Claude or Gemini) for ideas the keyword parser cannot map to templates.
// Selected by environment: ANTHROPIC_API_KEY or GEMINI_API_KEY. Without either, this module reports unavailable.

const { javaDir } = require('./generator');

const SYSTEM = `You are an expert Android developer writing Kotlin with Jetpack Compose (Material3).
Write a complete, compilable single-module app. Rules:
- Allowed dependencies ONLY: androidx.core, androidx.activity:activity-compose, compose ui, foundation, material3, kotlinx.coroutines (via Compose). No Material icons library, no navigation library, no ViewModel library, no network libraries.
- Persist data with SharedPreferences if needed.
- Use only these Kotlin files; the entry point is "class MainActivity : ComponentActivity()" in MainActivity.kt.
- Output ONLY file blocks, no commentary, in exactly this format:
=== FILE: MainActivity.kt ===
<kotlin source>
=== FILE: OtherScreen.kt ===
<kotlin source>
=== END ===
- Do not write build files or the manifest. Put the user's package name on the first line of each file.
- Prefer small, simple code that surely compiles over fancy features.`;

function provider() {
  if (process.env.ANTHROPIC_API_KEY) return 'claude';
  if (process.env.GEMINI_API_KEY) return 'gemini';
  return null;
}

async function postJson(url, headers, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...headers },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(180000),
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`LLM HTTP ${res.status}: ${text.slice(0, 300)}`);
  return JSON.parse(text);
}

async function callClaude(system, user) {
  const data = await postJson(
    'https://api.anthropic.com/v1/messages',
    { 'x-api-key': process.env.ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01' },
    {
      model: process.env.ANTHROPIC_MODEL || 'claude-sonnet-5-5',
      max_tokens: 12000,
      system,
      messages: [{ role: 'user', content: user }],
    }
  );
  return (data.content || []).filter(b => b.type === 'text').map(b => b.text).join('');
}

async function callGemini(system, user) {
  const model = process.env.GEMINI_MODEL || 'gemini-2.0-flash';
  const data = await postJson(
    `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent`,
    { 'x-goog-api-key': process.env.GEMINI_API_KEY },
    {
      systemInstruction: { parts: [{ text: system }] },
      contents: [{ role: 'user', parts: [{ text: user }] }],
      generationConfig: { maxOutputTokens: 12000, temperature: 0.3 },
    }
  );
  const parts = data.candidates?.[0]?.content?.parts || [];
  return parts.map(p => p.text || '').join('');
}

function callLlm(system, user) {
  const p = provider();
  if (p === 'claude') return callClaude(system, user);
  if (p === 'gemini') return callGemini(system, user);
  throw new Error('No LLM API key configured');
}

// Parses "=== FILE: X.kt ===" blocks into { "X.kt": source }, forcing the right package line.
function parseFileBlocks(text, pkg) {
  const out = {};
  const re = /=== FILE: ([A-Za-z0-9_]+\.kt) ===\r?\n([\s\S]*?)(?=\r?\n=== (?:FILE: |END)|$)/g;
  let m;
  while ((m = re.exec(text))) {
    let src = m[2].replace(/^```[a-z]*\r?\n/, '').replace(/\r?\n```\s*$/, '');
    src = src.replace(/^\s*package\s+[\w.]+\s*$/m, '').trimStart();
    out[m[1]] = `package ${pkg}\n\n${src}\n`;
  }
  return out;
}

// Maps parsed blocks to project paths (basename only, so a model can never write outside the source dir).
function toProjectFiles(blocks, spec) {
  const dir = javaDir(spec);
  const files = {};
  for (const [name, src] of Object.entries(blocks)) files[`${dir}/${name}`] = src;
  return files;
}

function validate(files, spec) {
  if (!files[`${javaDir(spec)}/MainActivity.kt`]) {
    throw new Error('Model output has no MainActivity.kt');
  }
  if (!/class\s+MainActivity\s*:\s*ComponentActivity/.test(files[`${javaDir(spec)}/MainActivity.kt`])) {
    throw new Error('MainActivity.kt does not declare MainActivity : ComponentActivity');
  }
}

async function llmGenerate(prompt, spec) {
  const user = `Package name: ${spec.packageName}\nApp name: ${spec.name}\nUI language: ${spec.lang === 'ar' ? 'Arabic (RTL)' : 'English'}\nPrimary color: ${spec.color}\n\nBuild this app:\n${prompt}`;
  const text = await callLlm(SYSTEM, user);
  const files = toProjectFiles(parseFileBlocks(text, spec.packageName), spec);
  validate(files, spec);
  return files;
}

async function llmRepair(prompt, spec, currentFiles, buildLog) {
  const dir = javaDir(spec);
  const sources = Object.entries(currentFiles)
    .filter(([p]) => p.startsWith(dir))
    .map(([p, c]) => `=== FILE: ${p.slice(dir.length + 1)} ===\n${c}`)
    .join('\n');
  const tail = buildLog.split('\n').slice(-60).join('\n');
  const user = `Package name: ${spec.packageName}\nOriginal request: ${prompt}\n\nThe build FAILED. Current sources:\n${sources}\n=== END ===\n\nBuild log (tail):\n${tail}\n\nReturn the COMPLETE corrected files in the same block format (all files that need changes, full contents).`;
  const text = await callLlm(SYSTEM, user);
  const fixed = toProjectFiles(parseFileBlocks(text, spec.packageName), spec);
  const merged = { ...currentFiles, ...fixed };
  validate(merged, spec);
  return merged;
}

module.exports = { provider, llmGenerate, llmRepair, parseFileBlocks, toProjectFiles };
