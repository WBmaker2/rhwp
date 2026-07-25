import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createServer as createNetServer } from 'node:net';

const HTML = `<!doctype html>
<meta charset="utf-8">
<title>rhwp collaboration two-tab E2E</title>
<input id="paragraph" aria-label="paragraph">
<input id="cell" aria-label="cell">
<script>
const params = new URLSearchParams(location.search);
const clientId = params.get('client');
const channel = new BroadcastChannel('rhwp-collaboration:e2e-session');
const seen = new Set();
let sequence = 0;
let lastUpdate = null;
window.remoteApplyCount = 0;
window.localSendCount = 0;

function send(nodeKind, text) {
  const update = {
    version: 1,
    updateId: clientId + ':' + sequence,
    documentFingerprint: 'sha256:e2e',
    nodeId: nodeKind === 'paragraph' ? 'p1' : 'c1',
    nodeKind,
    text,
    clientId,
    sequence,
  };
  sequence += 1;
  seen.add(update.updateId);
  lastUpdate = update;
  window.localSendCount += 1;
  channel.postMessage(update);
}

document.querySelector('#paragraph').addEventListener('input', (event) => {
  send('paragraph', event.currentTarget.value);
});
document.querySelector('#cell').addEventListener('input', (event) => {
  send('cell', event.currentTarget.value);
});

channel.addEventListener('message', (event) => {
  const update = event.data;
  if (!update || update.clientId === clientId || seen.has(update.updateId)) return;
  seen.add(update.updateId);
  document.querySelector('#' + update.nodeKind).value = update.text;
  window.remoteApplyCount += 1;
});

window.resendLastUpdate = () => {
  if (lastUpdate) channel.postMessage(lastUpdate);
};
window.stopCollaboration = () => channel.close();
window.__ready = true;
</script>`;

class CdpClient {
  constructor(url) {
    this.nextId = 1;
    this.pending = new Map();
    this.socket = new WebSocket(url);
    this.ready = new Promise((resolve, reject) => {
      this.socket.addEventListener('open', resolve, { once: true });
      this.socket.addEventListener('error', reject, { once: true });
    });
    this.socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      if (!message.id) return;
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message));
      else pending.resolve(message.result);
    });
  }

  async send(method, params = {}) {
    await this.ready;
    const id = this.nextId++;
    const response = new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
    this.socket.send(JSON.stringify({ id, method, params }));
    return response;
  }

  async evaluate(expression) {
    const response = await this.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (response.exceptionDetails) {
      throw new Error(response.exceptionDetails.text ?? 'Runtime.evaluate failed');
    }
    return response.result.value;
  }

  close() {
    this.socket.close();
  }
}

const chromePath = resolveChromePath();
const fixturePort = await reservePort();
const debuggingPort = await reservePort();
const fixtureServer = createServer((_request, response) => {
  response.writeHead(200, {
    'content-type': 'text/html; charset=utf-8',
    'cache-control': 'no-store',
  });
  response.end(HTML);
});
await listen(fixtureServer, fixturePort);

const profileDirectory = mkdtempSync(join(tmpdir(), 'rhwp-collaboration-e2e-'));
const chrome = spawn(chromePath, [
  '--headless=new',
  `--remote-debugging-port=${debuggingPort}`,
  `--user-data-dir=${profileDirectory}`,
  '--no-first-run',
  '--no-default-browser-check',
  '--disable-background-networking',
  '--disable-component-update',
  '--disable-gpu',
  '--no-sandbox',
  'about:blank',
], { stdio: ['ignore', 'ignore', 'pipe'] });

let stderr = '';
chrome.stderr.setEncoding('utf8');
chrome.stderr.on('data', (chunk) => { stderr += chunk; });

const clients = [];
try {
  await waitForDevTools(debuggingPort, chrome, () => stderr);
  const a = await openPage(debuggingPort, `http://127.0.0.1:${fixturePort}/?client=a`);
  const b = await openPage(debuggingPort, `http://127.0.0.1:${fixturePort}/?client=b`);
  clients.push(a, b);
  await Promise.all([
    waitFor(a, 'window.__ready === true'),
    waitFor(b, 'window.__ready === true'),
  ]);

  await setInput(a, '#paragraph', '한글 협업');
  await waitFor(b, `document.querySelector('#paragraph').value === '한글 협업'`);
  assert.equal(await valueOf(b, '#paragraph'), '한글 협업');
  assert.equal(await b.evaluate('window.remoteApplyCount'), 1);
  assert.equal(await a.evaluate('window.remoteApplyCount'), 0);
  assert.equal(await a.evaluate('window.localSendCount'), 1);

  await a.evaluate('window.resendLastUpdate()');
  await delay(120);
  assert.equal(await b.evaluate('window.remoteApplyCount'), 1, 'duplicate updateId must be ignored');

  await setInput(b, '#cell', '표 셀');
  await waitFor(a, `document.querySelector('#cell').value === '표 셀'`);
  assert.equal(await valueOf(a, '#cell'), '표 셀');
  assert.equal(await a.evaluate('window.remoteApplyCount'), 1);
  assert.equal(await b.evaluate('window.remoteApplyCount'), 1);
  assert.equal(await b.evaluate('window.localSendCount'), 1, 'remote apply must not echo as a local send');

  await b.evaluate('window.stopCollaboration()');
  await setInput(a, '#paragraph', '한글 협업 중단 후');
  await delay(180);
  assert.equal(await valueOf(b, '#paragraph'), '한글 협업');

  console.log('two-tab collaboration e2e passed');
} finally {
  for (const client of clients) client.close();
  fixtureServer.close();
  chrome.kill('SIGTERM');
  await Promise.race([
    new Promise((resolve) => chrome.once('exit', resolve)),
    delay(2_000),
  ]);
  if (chrome.exitCode === null) chrome.kill('SIGKILL');
  rmSync(profileDirectory, { recursive: true, force: true });
}

function resolveChromePath() {
  const candidates = [
    process.env.CHROME_PATH,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
  ].filter(Boolean);
  const path = candidates.find((candidate) => existsSync(candidate));
  if (!path) {
    throw new Error(`Chrome/Chromium executable not found. Checked: ${candidates.join(', ')}`);
  }
  return path;
}

async function reservePort() {
  const server = createNetServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  assert(address && typeof address !== 'string');
  const port = address.port;
  await new Promise((resolve) => server.close(resolve));
  return port;
}

function listen(server, port) {
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, '127.0.0.1', resolve);
  });
}

async function waitForDevTools(port, process, stderrReader) {
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    if (process.exitCode !== null) {
      throw new Error(`Chrome exited before DevTools was ready.\n${stderrReader()}`);
    }
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (response.ok) return;
    } catch {}
    await delay(50);
  }
  throw new Error(`Timed out waiting for Chrome DevTools.\n${stderrReader()}`);
}

async function openPage(port, url) {
  const response = await fetch(
    `http://127.0.0.1:${port}/json/new?${encodeURIComponent(url)}`,
    { method: 'PUT' },
  );
  if (!response.ok) throw new Error(`Failed to create CDP target: HTTP ${response.status}`);
  const target = await response.json();
  const client = new CdpClient(target.webSocketDebuggerUrl);
  await client.send('Runtime.enable');
  return client;
}

async function setInput(client, selector, value) {
  await client.evaluate(`(() => {
    const input = document.querySelector(${JSON.stringify(selector)});
    input.value = ${JSON.stringify(value)};
    input.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
}

async function valueOf(client, selector) {
  return client.evaluate(`document.querySelector(${JSON.stringify(selector)}).value`);
}

async function waitFor(client, expression, timeoutMs = 3_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await client.evaluate(`Boolean(${expression})`)) return;
    await delay(20);
  }
  throw new Error(`Timed out waiting for: ${expression}`);
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
