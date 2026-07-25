import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import { execFileSync } from 'node:child_process';

function chromePath() {
  const candidates = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
  ];
  for (const path of candidates) {
    try { execFileSync('test', ['-x', path]); return path; } catch {}
  }
  throw new Error('Chrome/Chromium executable not found');
}

const html = `<!doctype html><meta charset="utf-8"><input id="paragraph"><input id="cell"><script>
const params=new URLSearchParams(location.search); const clientId=params.get('client');
const channel=new BroadcastChannel('rhwp-collaboration:e2e-session'); let seq=0; const seen=new Set();
function send(kind,text){const update={version:1,updateId:clientId+':'+seq,documentFingerprint:'sha256:e2e',nodeId:kind==='paragraph'?'p1':'c1',nodeKind:kind,text,clientId,sequence:seq++};seen.add(update.updateId);channel.postMessage(update)}
paragraph.addEventListener('input',()=>send('paragraph',paragraph.value)); cell.addEventListener('input',()=>send('cell',cell.value));
channel.onmessage=(e)=>{const u=e.data;if(u.clientId===clientId||seen.has(u.updateId))return;seen.add(u.updateId);document.getElementById(u.nodeKind).value=u.text;window.remoteApplyCount=(window.remoteApplyCount||0)+1};
window.stopCollaboration=()=>channel.close(); window.remoteApplyCount=0;
</script>`;
const url='data:text/html,'+encodeURIComponent(html);
const browser=await puppeteer.launch({headless:true,executablePath:chromePath(),args:['--no-sandbox']});
try {
  const a=await browser.newPage(), b=await browser.newPage();
  await a.goto(url+'?client=a'); await b.goto(url+'?client=b');
  await a.type('#paragraph','한글 협업');
  await b.waitForFunction(()=>document.querySelector('#paragraph').value==='한글 협업');
  assert.equal(await b.$eval('#paragraph',e=>e.value),'한글 협업');
  await b.type('#cell','표 셀');
  await a.waitForFunction(()=>document.querySelector('#cell').value==='표 셀');
  assert.equal(await a.$eval('#cell',e=>e.value),'표 셀');
  const countA=await a.evaluate(()=>window.remoteApplyCount), countB=await b.evaluate(()=>window.remoteApplyCount);
  assert.ok(countA>=1 && countB>=1);
  await b.evaluate(()=>window.stopCollaboration());
  await a.type('#paragraph',' 중단후');
  await new Promise(r=>setTimeout(r,150));
  assert.equal(await b.$eval('#paragraph',e=>e.value),'한글 협업');
  console.log('two-tab collaboration e2e passed');
} finally { await browser.close(); }
