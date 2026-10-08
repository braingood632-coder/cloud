'use strict';
// Dependency-free HTTP server: JSON API + SSE build log + static web UI.

const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { parse } = require('./parser');
const { COMPONENTS } = require('./components');
const { createJob, getJob, publicJob } = require('./builder');
const llm = require('./llm');

const PORT = Number(process.env.PORT || 3000);
const TOKEN = process.env.ACCESS_TOKEN || '';
const WEB_DIR = path.join(__dirname, '..', '..', 'web');
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' };

function send(res, status, body, headers = {}) {
  const isObj = typeof body === 'object' && !Buffer.isBuffer(body);
  res.writeHead(status, { 'content-type': isObj ? 'application/json; charset=utf-8' : 'text/plain; charset=utf-8', ...headers });
  res.end(isObj ? JSON.stringify(body) : body);
}

function readBody(req, limit = 20000) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (c) => {
      data += c;
      if (data.length > limit) { reject(Object.assign(new Error('Body too large'), { status: 413 })); req.destroy(); }
    });
    req.on('end', () => {
      try { resolve(data ? JSON.parse(data) : {}); } catch { reject(Object.assign(new Error('Invalid JSON'), { status: 400 })); }
    });
  });
}

function authorized(req, url) {
  if (!TOKEN) return true;
  const header = req.headers.authorization || '';
  return header === `Bearer ${TOKEN}` || url.searchParams.get('token') === TOKEN;
}

function serveStatic(res, pathname) {
  const rel = pathname === '/' ? 'index.html' : pathname.slice(1);
  const file = path.resolve(WEB_DIR, rel);
  if (!file.startsWith(WEB_DIR + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    return send(res, 404, 'Not found');
  }
  res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
}

async function handle(req, res) {
  const url = new URL(req.url, 'http://localhost');
  const { pathname } = url;

  if (!pathname.startsWith('/api/')) return serveStatic(res, pathname);

  if (pathname === '/api/info' && req.method === 'GET') {
    return send(res, 200, {
      authRequired: Boolean(TOKEN),
      llm: llm.provider(),
      components: Object.values(COMPONENTS).map(c => ({ id: c.id, label: c.label })),
    });
  }
  if (!authorized(req, url)) return send(res, 401, { error: 'Unauthorized' });

  if (pathname === '/api/parse' && req.method === 'POST') {
    const { prompt } = await readBody(req);
    if (!prompt || !String(prompt).trim()) return send(res, 400, { error: 'prompt is required' });
    return send(res, 200, { ...parse(prompt), llm: llm.provider() });
  }

  if (pathname === '/api/build' && req.method === 'POST') {
    const body = await readBody(req);
    const parsed = parse(body.prompt || '');
    const job = createJob({ spec: body.spec || parsed.spec, prompt: body.prompt, mode: body.mode });
    return send(res, 202, publicJob(job));
  }

  const m = pathname.match(/^\/api\/jobs\/([a-f0-9]{16})(?:\/(events|apk|project))?$/);
  if (m) {
    const job = getJob(m[1]);
    if (!job) return send(res, 404, { error: 'No such job' });

    if (!m[2]) return send(res, 200, { ...publicJob(job), log: job.log.slice(-200) });

    if (m[2] === 'events') {
      res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache', connection: 'keep-alive' });
      const emit = (ev) => res.write(`data: ${JSON.stringify(ev)}\n\n`);
      job.log.slice(-200).forEach(line => emit({ type: 'log', line }));
      emit({ type: 'status', status: job.status, error: job.error });
      job.listeners.add(emit);
      req.on('close', () => job.listeners.delete(emit));
      return;
    }

    if (m[2] === 'apk') {
      if (!job.apkPath || !fs.existsSync(job.apkPath)) return send(res, 404, { error: 'APK not available' });
      res.writeHead(200, {
        'content-type': 'application/vnd.android.package-archive',
        'content-disposition': `attachment; filename="app-${job.id}.apk"`,
      });
      return fs.createReadStream(job.apkPath).pipe(res);
    }

    if (m[2] === 'project') {
      if (!job.projectDir || !fs.existsSync(job.projectDir)) return send(res, 404, { error: 'Project not available' });
      res.writeHead(200, { 'content-type': 'application/gzip', 'content-disposition': `attachment; filename="project-${job.id}.tar.gz"` });
      const tar = spawn('tar', ['-czf', '-', '--exclude=./build', '--exclude=./app/build', '--exclude=./.gradle', '-C', job.projectDir, '.']);
      tar.stdout.pipe(res);
      return;
    }
  }

  return send(res, 404, { error: 'Not found' });
}

const server = http.createServer((req, res) => {
  handle(req, res).catch((e) => {
    if (!res.headersSent) send(res, e.status || 500, { error: e.message });
    else res.end();
  });
});

if (require.main === module) {
  server.listen(PORT, () => {
    console.log(`App Builder listening on :${PORT} (llm: ${llm.provider() || 'off'}, auth: ${TOKEN ? 'on' : 'off'})`);
  });
}

module.exports = { server };
