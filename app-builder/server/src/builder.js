'use strict';
// Job queue + Gradle runner. One build at a time (Gradle is heavy).

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const { generate, normalizeSpec, baseFiles } = require('./generator');
const llm = require('./llm');

const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, '..', '..', 'data');
const MAX_QUEUE = Number(process.env.MAX_QUEUE || 10);
const BUILD_TIMEOUT_MS = Number(process.env.BUILD_TIMEOUT_MS || 15 * 60 * 1000);
const MAX_REPAIRS = Number(process.env.MAX_REPAIRS || 3);
const MAX_LOG_LINES = 5000;

const jobs = new Map();
const queue = [];
let running = false;

function writeProject(dir, files) {
  for (const [rel, content] of Object.entries(files)) {
    const target = path.resolve(dir, rel);
    if (!target.startsWith(path.resolve(dir) + path.sep)) throw new Error(`Bad path: ${rel}`);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, content, 'utf8');
  }
}

function log(job, line) {
  job.log.push(line);
  if (job.log.length > MAX_LOG_LINES) job.log.splice(0, job.log.length - MAX_LOG_LINES);
  for (const fn of job.listeners) fn({ type: 'log', line });
}

function setStatus(job, status, extra = {}) {
  job.status = status;
  Object.assign(job, extra);
  for (const fn of job.listeners) fn({ type: 'status', status, error: job.error || null });
}

function sdkHome() {
  return process.env.ANDROID_HOME || process.env.ANDROID_SDK_ROOT || '';
}

function runGradle(job, dir) {
  return new Promise((resolve) => {
    const bin = process.env.GRADLE_BIN || 'gradle';
    const child = spawn(bin, ['--no-daemon', '--console=plain', '--stacktrace', 'assembleDebug'], {
      cwd: dir,
      env: { ...process.env, ANDROID_HOME: sdkHome(), ANDROID_SDK_ROOT: sdkHome() },
    });
    let out = '';
    const feed = (buf) => {
      const text = buf.toString('utf8');
      out += text;
      text.split(/\r?\n/).filter(Boolean).forEach(l => log(job, l));
    };
    child.stdout.on('data', feed);
    child.stderr.on('data', feed);
    const timer = setTimeout(() => { log(job, 'Build timed out'); child.kill('SIGKILL'); }, BUILD_TIMEOUT_MS);
    child.on('error', (e) => { clearTimeout(timer); resolve({ ok: false, out: `${out}\n${e.message}` }); });
    child.on('close', (code) => { clearTimeout(timer); resolve({ ok: code === 0, out }); });
  });
}

async function execute(job) {
  const projectDir = path.join(DATA_DIR, 'work', job.id);
  job.projectDir = projectDir;
  fs.mkdirSync(projectDir, { recursive: true });
  const spec = job.spec;
  let files;

  if (job.mode === 'llm') {
    log(job, `Asking ${llm.provider()} to write the app...`);
    files = { ...baseFiles(spec), ...(await llm.llmGenerate(job.prompt, spec)) };
  } else {
    files = generate(spec).files;
  }
  writeProject(projectDir, files);
  log(job, `Project generated (${Object.keys(files).length} files).`);

  if (process.env.BUILD_DRY_RUN === '1') {
    log(job, 'BUILD_DRY_RUN=1: skipping Gradle; project source is available for download.');
    return;
  }
  if (!sdkHome() || !fs.existsSync(sdkHome())) {
    throw new Error('ANDROID_HOME is not set or does not exist. Run the server from the provided Docker image (it bundles the Android SDK).');
  }

  const maxAttempts = job.mode === 'llm' ? MAX_REPAIRS + 1 : 1;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    setStatus(job, 'building');
    log(job, `Gradle build, attempt ${attempt}/${maxAttempts}...`);
    const res = await runGradle(job, projectDir);
    const apk = path.join(projectDir, 'app/build/outputs/apk/debug/app-debug.apk');
    if (res.ok && fs.existsSync(apk)) {
      const outDir = path.join(DATA_DIR, 'apks');
      fs.mkdirSync(outDir, { recursive: true });
      job.apkPath = path.join(outDir, `${job.id}.apk`);
      fs.copyFileSync(apk, job.apkPath);
      log(job, 'APK ready.');
      return;
    }
    if (attempt === maxAttempts) throw new Error('Gradle build failed. See the log.');
    log(job, 'Build failed; asking the model to fix the errors...');
    files = await llm.llmRepair(job.prompt, spec, files, res.out);
    writeProject(projectDir, files);
  }
}

async function pump() {
  if (running) return;
  const job = queue.shift();
  if (!job) return;
  running = true;
  try {
    setStatus(job, 'building');
    await execute(job);
    setStatus(job, 'done');
  } catch (e) {
    log(job, `ERROR: ${e.message}`);
    setStatus(job, 'failed', { error: e.message });
  } finally {
    running = false;
    setImmediate(pump);
  }
}

// opts: { spec, prompt, mode: 'template' | 'llm' }
function createJob(opts) {
  if (queue.length >= MAX_QUEUE) {
    const err = new Error('Build queue is full, try again later');
    err.status = 429;
    throw err;
  }
  const mode = opts.mode === 'llm' ? 'llm' : 'template';
  if (mode === 'llm' && !llm.provider()) {
    const err = new Error('No LLM API key configured on the server');
    err.status = 400;
    throw err;
  }
  const job = {
    id: crypto.randomBytes(8).toString('hex'),
    mode,
    prompt: String(opts.prompt || '').slice(0, 2000),
    spec: normalizeSpec(opts.spec),
    status: 'queued',
    error: null,
    log: [],
    listeners: new Set(),
    apkPath: null,
    projectDir: null,
    createdAt: Date.now(),
  };
  jobs.set(job.id, job);
  queue.push(job);
  setImmediate(pump);
  return job;
}

const getJob = (id) => jobs.get(id);

function publicJob(job) {
  return {
    id: job.id,
    mode: job.mode,
    status: job.status,
    error: job.error,
    spec: job.spec,
    hasApk: Boolean(job.apkPath),
    hasProject: Boolean(job.projectDir) && fs.existsSync(job.projectDir),
    queuePosition: queue.indexOf(job) + 1,
  };
}

module.exports = { createJob, getJob, publicJob, writeProject };
