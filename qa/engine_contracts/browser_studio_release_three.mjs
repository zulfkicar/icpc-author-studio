// Dedicated demo instance only. Exercises the rendered Studio and real package jobs.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { appendFileSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const base = process.env.ENGINE_UI_BASE;
assert.match(base || "", /^http:\/\/127\.0\.0\.1:\d+$/);
const root = process.env.AUTHOR_AGENT_WORKSPACES_ROOT;
assert.ok(root, "disposable workspace root required");
assert.match(root.toLowerCase().replaceAll("\\", "/"), /\/tmp\/studio-release-3-browser[^/]*\/workspaces$/);
const port = process.env.STUDIO_CDP_PORT || "9337";
const profile = mkdtempSync(join(tmpdir(), "studio-release-three-"));
const chrome = spawn("C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", [
  "--headless=new", "--disable-gpu", "--no-first-run", `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`, "about:blank",
], { stdio: "ignore" });

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
let ws;
try {
  let tab;
  for (let i = 0; i < 60 && !tab; i++) {
    try { tab = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(item => item.type === "page"); }
    catch { await pause(200); }
  }
  assert.ok(tab, "Chrome debugging target");
  ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  const pending = new Map();
  let id = 0;
  const errors = [];
  ws.onmessage = event => {
    const msg = JSON.parse(event.data);
    if (msg.method === "Runtime.exceptionThrown") errors.push(msg.params.exceptionDetails.text);
    if (!pending.has(msg.id)) return;
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) reject(new Error(msg.error.message));
    else resolve(msg.result);
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    pending.set(++id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
  await send("Runtime.enable");
  await send("Page.enable");
  await send("Page.addScriptToEvaluateOnNewDocument", { source: `
    let clipboardText = "";
    Object.defineProperty(navigator, "clipboard", { value: {
      writeText: async text => { clipboardText = text; }, readText: async () => clipboardText,
    }});
  ` });
  await send("Page.navigate", { url: base + "/" });
  await pause(1400);
  const setup = `
    const $ = sel => document.querySelector(sel);
    const $$ = sel => [...document.querySelectorAll(sel)];
    const wait = async (fn, name) => {
      for (let i = 0; i < 280; i++) {
        const value = fn();
        if (value) return value;
        await new Promise(resolve => setTimeout(resolve, 150));
      }
      throw new Error(name + ': ' + ($('#studio-output')?.innerText || '').slice(0, 1000) + ' | ' + $('#studio-alert')?.textContent);
    };
    const output = () => $('#studio-output').innerText;
    const click = sel => $(sel).click();
    const button = (label, scope = '#studio-output') => $$(scope + ' button').find(el => el.textContent.trim() === label && !el.disabled);
    const press = async (label, scope) => (await wait(() => button(label, scope), label)).click();
    const check = (value, message) => { if (!value) throw new Error(message); };
    const json = async (url, body) => {
      const response = await fetch(url, body === undefined ? {} : { method: 'POST',
        headers: {'content-type': 'application/json'}, body: JSON.stringify(body) });
      const data = await response.json();
      check(response.ok, url + ': ' + JSON.stringify(data));
      return data;
    };
    const type = (input, text) => { input.value = text; input.dispatchEvent(new Event('input', {bubbles: true})); };
  `;
  const evalBrowser = async source => {
    const result = await send("Runtime.evaluate", { expression: `(async()=>{${setup}\n${source}})()`,
      awaitPromise: true, returnByValue: true, userGesture: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    return result.result.value;
  };
  const snapshot = await evalBrowser(String.raw`
    await wait(() => $('#collab-panel') && !$('#collab-panel').hidden, 'Studio loaded');
    const existing = await json('/api/engine/runs');
    check(existing.runs.length === 0, 'Use an empty disposable Studio engine');
    type($('#collab-composer'), 'Help me develop profitable bookings; work with me, briefly.');
    click('#collab-send');
    const option = await wait(() => $$('.collab-option').find(item => item.textContent.includes('Half-open')), 'endpoint choice');
    check($('.card-options').textContent.includes('requires rechecking'), 'endpoint impact');
    option.click();
    await wait(() => $('.studio-case-card')?.textContent.includes('Simulated worker'), 'witness');
    check($$('.studio-case-facts dd').map(item => item.textContent).join(',') === '13,12', 'actual and expected');
    await wait(() => $('#collab-transcript').innerText.includes('Endpoint rule applied'), 'decision provenance');
    click('#studio-package');
    await wait(() => $('#studio-package-dialog').open && !$('#studio-link-submit').disabled, 'package form');
    check($('#studio-package-help').textContent.includes('Link this conversation'), 'package setup attached to current conversation');
    type($('#studio-package-name'), 'Evidence Browser Fixture');
    click('#studio-link-submit');
    await wait(() => !$('#studio-package-dialog').open && $('#studio-package-label').textContent === 'Evidence Browser Fixture', 'package linked');
    const run = (await json('/api/engine/runs')).runs[0].runId;
    const link = await json('/api/engine/runs/' + run + '/studio-package');
    check(link.slug, 'linked package available');
    const pack = '/api/workspaces/' + link.slug;
    const source = 'submissions/accepted/reference.py';
    const greedy = 'import sys\n_, *rows = sys.stdin.read().splitlines()\nitems = sorted((tuple(map(int, x.split())) for x in rows), key=lambda j:(j[1],j[0]))\nlast, total = -1, 0\nfor a, b, w in items:\n    if a >= last: last, total = b, total+w\nprint(total)\n';
    const reference = 'import sys,itertools\n_, *rows = sys.stdin.read().splitlines()\njobs = [tuple(map(int, row.split())) for row in rows]\nbest = 0\nfor n in range(len(jobs)+1):\n    for group in itertools.combinations(sorted(jobs), n):\n        if all(a[1] <= b[0] for a,b in zip(group,group[1:])):\n            best = max(best, sum(job[2] for job in group))\nprint(best)\n';
    const caseText = $('.studio-case-card pre').textContent;
    const writes = {
      [source]: greedy,
      'submissions/wrong_answer/greedy.py': greedy,
      'data/sample/01.in': '1\n0 2 6\n',
      'data/secret/weighted.in': caseText,
      'problem_statement/problem.en.tex': '\\documentclass{article}\n\\begin{document}\nFind the highest reward for compatible intervals.\n\\end{document}\n',
      'input_validators/validate.py': 'import sys\nn,*a=map(int,sys.stdin.read().split());sys.exit(42 if len(a)==3*n else 1)\n',
      'domjudge-problem.ini': 'name = Evidence Browser Fixture\ntimelimit = 1\nshort-name = EB\n',
    };
    for (const [path, content] of Object.entries(writes)) await json(pack + '/file', {path, content});
    await press('Copy input', '.studio-case-card');
    await wait(() => $('.studio-case-card').textContent.includes('Input copied.'), 'case copied');
    check(await navigator.clipboard.readText() === caseText, 'clipboard matches the displayed input');
    await press('Run this case', '.studio-case-card');
    await wait(() => $('textarea[aria-label="Standard input"]')?.value === caseText, 'case staged');
    const savedFetch = window.fetch;
    let disconnected = 0, runRequests = 0;
    const observations = [];
    window.fetch = (url, ...options) => {
      if (url === pack + '/run') runRequests++;
      if (typeof url === 'string' && url.startsWith('/api/jobs/')) {
        observations.push(url);
        if (++disconnected <= 3) return Promise.reject(new Error('Fixture temporarily lost connection'));
      }
      return savedFetch(url, ...options);
    };
    await press('Run saved source');
    await press('Reconnect to job');
    await wait(() => output().includes('Output mismatch') && output().includes('Local process'), 'real mismatching run');
    window.fetch = savedFetch;
    check(runRequests === 1 && new Set(observations).size === 1 && observations.length === 4, 'reconnect observes original job');
    check(output().includes('12') && output().includes('13'), 'local output values');
    await press('Run again');
    await wait(() => $('textarea[aria-label="Standard input"]')?.value === caseText, 'replay restored input');
    click('#studio-files');
    type($('#studio-search-input'), 'reference.py');
    (await wait(() => $('#studio-search-results [role="option"]'), 'find reference source')).click();
    const model = await wait(() => window.monaco?.editor.getModels().find(item => item.getValue() === greedy), 'Monaco model');
    model.setValue('def :\n');
    click('[data-operation="run"]');
    await press('Run again');
    await press('Save & Run');
    await press('Open reference.py:1');
    await wait(() => $('#studio-file-path').textContent === source, 'diagnostic opened source');
    model.setValue(reference);
    click('[data-operation="run"]');
    await press('Run again');
    await press('Save & Run');
    await wait(() => output().includes('Matches expected output'), 'run saved repair');
    check((await json(pack + '/file?path=' + encodeURIComponent(source))).content === reference, 'edited source saved');
    click('[data-operation="answers"]');
    await wait(() => output().includes('1 sample · 1 secret · 1 reference'), 'answer generation preview');
    await press('Build expected answers');
    await wait(() => output().includes('2 answer file(s) written'), 'output build');
    await press('Open verification');
    await press('Measure limits');
    await press('Measure saved package');
    await wait(() => output().includes('Limits measured'), 'real limit measurement');
    await press('Open verification');
    await press('Verify saved package');
    await wait(() => output().includes('Package verified'), 'real verification');
    check(output().includes('1 known-bad solution'), 'wrong answer baseline');
    const filter = $('select[aria-label="Test group"]');
    filter.value = [...filter.options].find(opt => opt.value.startsWith('secret')).value;
    filter.dispatchEvent(new Event('change'));
    await wait(() => output().includes('1 of 2 cases') && output().includes('weighted.in'), 'secret case filter');
    await press('Compare solutions');
    await wait(() => output().includes('Interval DP') && output().includes('greedy.py') && output().includes('source '), 'comparison with source evidence');
    click('[data-operation="export"]');
    await press('Review package changes');
    await wait(() => output().includes('No approved file baseline'), 'first review identifies unknown baseline');
    check(!button('Generate ZIP'), 'approval gate');
    await press('Approve saved snapshot');
    await press('Generate ZIP');
    const download = await wait(() => $('#studio-output .studio-download'), 'ZIP downloaded');
    const response = await fetch(download.href);
    check(response.ok && response.headers.get('Content-Type') === 'application/zip', 'download returned real ZIP');
    const studio = await json(pack + '/studio');
    return { pack, snapshot: studio.snapshot, name: studio.archive.filename, bytes: (await response.arrayBuffer()).byteLength };
  `);
  await send("Page.reload");
  await pause(1100);
  await evalBrowser(`
    await wait(() => $('#studio-package-label')?.textContent === 'Evidence Browser Fixture', 'same package restored after reload');
    click('[data-operation="run"]');
    await wait(() => output().includes('Matches expected output'), 'last run restored');
    await press('Run again');
    await wait(() => $('textarea[aria-label="Standard input"]')?.value.includes('0 4 13'), 'saved input restored');
    check($('select[aria-label="Saved source"]').value === 'submissions/accepted/reference.py', 'saved source restored');
  `);
  // Shell-side edit bypasses the workspace change journal.
  const slug = snapshot.pack.split("/").at(-1);
  appendFileSync(join(root, slug, "problem_statement", "problem.en.tex"), "\n% Edited on disk outside Studio\n");
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  const checked = await evalBrowser(`
    const {pack, snapshot} = ${JSON.stringify(snapshot)};
    click('[data-operation="export"]');
    await wait(() => output().includes('Earlier archive'), 'historical archive visible');
    check(!$('#studio-output .studio-download'), 'stale download hidden');
    for (const suffix of ['/download', '/download?snapshot=' + snapshot]) {
      check((await fetch(pack + suffix)).status === 409, 'stale download route');
    }
    await press('Open verification');
    await press('Verify saved package');
    await wait(() => output().includes('Package verified'), 'reverified changed package');
    click('[data-operation="export"]');
    await press('Review package changes');
    const group = await wait(() => $$('#studio-output details > summary').find(el => el.textContent.includes('Problem statement')), 'grouped statements');
    group.click();
    const row = await wait(() => $$('#studio-output .studio-review-file > summary').find(el => el.textContent.includes('problem.en.tex')), 'changed statement');
    row.click();
    await wait(() => output().includes('+% Edited on disk outside Studio') && output().includes('· viewed'), 'cumulative diff and viewed state');
    check(!$('#studio-output .studio-download'), 'new snapshot needs approval');
    check(document.documentElement.scrollWidth === innerWidth, 'narrow flow has no horizontal page overflow');
    const review = output().includes('outside change or unrecorded source');
    click('#studio-commands');
    type($('#studio-search-input'), 'setter handoff');
    (await wait(() => $('#studio-search-results [role="option"]'), 'handoff command')).click();
    await wait(() => output().includes('Shareable summary'), 'handoff');
    const text = $('#studio-output pre').textContent;
    check(text.includes('Endpoint decision: Half-open') && text.includes('Archive revision:'), 'handoff evidence');
    check(!text.includes('weighted.in') && !text.includes('0 4 13') && !text.includes('import sys'), 'private content omitted');
    await press('Copy handoff summary');
    await wait(() => $('#studio-alert').textContent.includes('Handoff summary copied.'), 'handoff copied');
    check(await navigator.clipboard.readText() === text, 'clipboard matches the shareable summary');
    return { review, width: innerWidth, handoff: true, clipboard: true, restoredRun: true, reconnectSameJob: true };
  `);
  assert.ok(checked.review);
  assert.deepEqual(errors, []);
  const out = process.env.STUDIO_RELEASE_THREE_EVIDENCE;
  if (out) {
    mkdirSync(out, { recursive: true });
    const shot = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(out, "release-3-handoff-390.png"), Buffer.from(shot.data, "base64"));
    writeFileSync(join(out, "release-3-browser.json"), JSON.stringify({ ...snapshot, ...checked }, null, 2));
  }
  console.log(JSON.stringify({ ...snapshot, ...checked }));
} finally {
  ws?.close();
  chrome.kill();
}
