// Rendered-browser repair journey for CN-R01..CN-R04.
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9334;
const BASE = process.env.ENGINE_UI_BASE || "http://127.0.0.1:8898";
const OUT = process.env.ENGINE_UI_SCREENSHOT_REPAIR
  || join(process.cwd(), "qa", "engine_contracts", "evidence", "ui-chat-repair.png");

const profile = mkdtempSync(join(tmpdir(), "engine-ui-repair-"));
const child = spawn(CHROME, [
  "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, "about:blank",
], { stdio: "ignore" });

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function target() {
  for (let i = 0; i < 60; i++) {
    try {
      const response = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const tabs = await response.json();
      const page = tabs.find((tab) => tab.type === "page");
      if (page) return page;
    } catch (_) { /* not ready */ }
    await sleep(250);
  }
  throw new Error("Chrome CDP target did not appear");
}

class Cdp {
  constructor(url) {
    this.ws = new WebSocket(url);
    this.id = 0;
    this.pending = new Map();
    this.ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(message.error.message));
        else resolve(message.result);
      }
    };
  }
  ready() {
    return new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = reject;
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }
  async eval(expression) {
    const result = await this.send("Runtime.evaluate", {
      expression, awaitPromise: true, returnByValue: true, userGesture: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description || "evaluation failed");
    }
    return result.result.value;
  }
}

const helpers = `
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const text = (selector) => (document.querySelector(selector) || {}).innerText || '';
  const all = (selector) => Array.from(document.querySelectorAll(selector));
  const waitFor = async (fn, label, timeout = 50000) => {
    const start = Date.now();
    while (Date.now() - start < timeout) {
      const value = fn();
      if (value) return value;
      await sleep(150);
    }
    throw new Error("timeout: " + label);
  };
  const send = async (message) => {
    const box = document.getElementById('collab-composer');
    box.value = message;
    document.getElementById('collab-send').click();
    await waitFor(() => box.value === '', 'composer cleared: ' + message.slice(0, 35));
    await sleep(250);
  };
  const newChat = async () => {
    document.getElementById('collab-new').click();
    await sleep(400);
  };
  const inspect = async (prefix, contains) => {
    document.getElementById('collab-artifacts-section').open = true;
    const button = await waitFor(() => all('#collab-artifacts button.artifact-link')
      .find((b) => (b.textContent || '').startsWith(prefix)), 'artifact ' + prefix);
    button.click();
    const body = document.getElementById('collab-artifact-body');
    const start = Date.now();
    while (Date.now() - start < 50000) {
      const value = body.textContent || '';
      if (value.includes(prefix) && (!contains || value.includes(contains))) {
        return value;
      }
      await sleep(150);
    }
    throw new Error("body timeout " + prefix + " body=" + (body.textContent || "").slice(0, 180)
      + " receipt=" + text('#collab-receipt')
      + " buttons=" + all('#collab-artifacts button.artifact-link')
        .map((b) => b.textContent).join('|'));
  };
`;

const journey = `(async () => {
  ${helpers}
  const errors = [];
  window.addEventListener('error', (event) => errors.push(String(event.message || event.error)));
  document.getElementById('collab-btn').click();
  await waitFor(() => !document.getElementById('collab-panel').hidden, 'panel open');

  // R01: refuse, question, then clear approval against the managed solution.
  await newChat();
  await send('Help me develop profitable bookings; work with me, briefly.');
  await waitFor(() => all('.collab-msg.decision').length === 1, 'decision card');
  document.querySelector('.collab-msg.decision .collab-option').click();
  await waitFor(() => text('#collab-transcript').includes('independent subset oracle'), 'settled');
  await send('\`\`\`cpp\\n#include <bits/stdc++.h>\\nint main(){ /* ORIGINAL_BROWSER */ return 0; }\\n\`\`\`');
  await waitFor(() => all('#collab-artifacts button.artifact-link')
    .some((b) => (b.textContent || '').startsWith('solutions/')), 'solution artifact');
  const beforeRefusal = await inspect('solutions/');
  await send("Don't apply your proposed fix.");
  await sleep(800);
  const afterRefusal = await inspect('solutions/');
  await send('Explain whether we should apply your proposed fix.');
  await waitFor(() => text('#collab-transcript').includes('Explain whether'), 'question turn');
  await sleep(800);
  const afterQuestion = await inspect('solutions/');
  const refusalTranscript = text('#collab-transcript');
  await send('Apply your proposed fix.');
  await waitFor(() => all('#collab-artifacts button.artifact-link')
    .filter((b) => (b.textContent || '').startsWith('solutions/')).length >= 2,
    'approved repair artifact projection');
  await sleep(500);
  const afterApproval = await inspect('solutions/', 'demo repair applied');

  // R02: tentative answer keeps the card; a clear answer settles it.
  await newChat();
  await send('Help me develop profitable tickets.');
  await waitFor(() => all('.collab-msg.decision').length === 1, 'second decision card');
  await send('Maybe closed intervals?');
  await sleep(1200);
  const tentativeCardOpen = all('.collab-msg.decision .collab-option').length > 0;
  const tentativeDecisions = await (async () => {
    const response = await fetch('/api/engine/runs/' + localStorage.getItem('authorAgent.engineRun') + '/view');
    return (await response.json()).collaboration.decisions || [];
  })();
  await send('closed: touching jobs conflict');
  await waitFor(() => all('.collab-msg.decision .collab-option').length === 0, 'card settled');
  const clearDecisions = await (async () => {
    const response = await fetch('/api/engine/runs/' + localStorage.getItem('authorAgent.engineRun') + '/view');
    return (await response.json()).collaboration.decisions || [];
  })();

  // R03: proof help produces request-tied work, not a lemma.
  await send('Can you explain the proof?');
  await waitFor(() => text('#collab-transcript').includes('PROOF_EXPLAIN'), 'proof explanation');
  const proofTranscript = text('#collab-transcript');

  // R04: correction makes old proof/test stale and the plan state-derived.
  await newChat();
  await send('Help me develop profitable bookings.');
  await waitFor(() => all('.collab-msg.decision').length === 1, 'fourth decision card');
  await send('Half-open; touching jobs are compatible.');
  await waitFor(() => all('.collab-msg.decision .collab-option').length === 0, 'fourth settled');
  await send('Lemma: jobs [0,1) and [1,2) can both be selected because touching jobs are compatible.');
  await send('Test case: jobs (0,1,5) and (1,2,7); expected total 12.');
  await sleep(800);
  await send('Correction: treat touching jobs as conflicting; use closed intervals.');
  await waitFor(() => all('#collab-artifacts .state.unverified').length >= 2, 'stale artifacts');
  const staleCount = all('#collab-artifacts .state.unverified').length;
  const planBody = await inspect('tests/plan.md');
  const transcriptAfterCorrection = text('#collab-transcript');
  const runId = localStorage.getItem('authorAgent.engineRun');

  document.getElementById('collab-export').click();
  await waitFor(() => text('#collab-receipt').toLowerCase().includes('refused'), 'export refusal');
  return { errors, beforeRefusal, afterRefusal, afterQuestion, afterApproval,
           refusalTranscript, tentativeCardOpen, tentativeDecisions, clearDecisions,
           proofTranscript, staleCount, planBody, transcriptAfterCorrection, runId };
})()`;

const reloadScript = `(async () => {
  ${helpers}
  const errors = [];
  window.addEventListener('error', (event) => errors.push(String(event.message || event.error)));
  document.getElementById('collab-btn').click();
  await waitFor(() => !document.getElementById('collab-panel').hidden, 'panel open after reload');
  await waitFor(() => all('#collab-artifacts button.artifact-link').length > 1, 'artifacts resumed');
  const stale = all('#collab-artifacts .state.unverified').length;
  const planBody = await inspect('tests/plan.md');
  return { stale, planBody, errors, status: text('#collab-status') };
})()`;

let cdp;
try {
  const page = await target();
  cdp = new Cdp(page.webSocketDebuggerUrl);
  await cdp.ready();
  await cdp.send("Runtime.enable");
  await cdp.send("Page.enable");
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false,
  });
  await cdp.send("Page.navigate", { url: BASE + "/workbench" });
  await sleep(2500);
  const before = await cdp.eval(journey);
  await cdp.send("Page.reload");
  await sleep(2500);
  const after = await cdp.eval(reloadScript);

  if (!before.beforeRefusal.includes("ORIGINAL_BROWSER"))
    throw new Error("original solution not rendered");
  if (before.afterRefusal.includes("demo repair"))
    throw new Error("refusal published a repair");
  if (before.afterQuestion.includes("demo repair"))
    throw new Error("question published a repair");
  if (!before.afterApproval.includes("demo repair applied"))
    throw new Error("clear approval did not publish the repair");
  if (!before.tentativeCardOpen || (before.tentativeDecisions || []).length)
    throw new Error("tentative answer settled the card");
  if ((before.clearDecisions || []).length !== 1)
    throw new Error("clear answer did not commit once");
  if (!before.proofTranscript.includes("PROOF_EXPLAIN"))
    throw new Error("proof request did not produce request-tied work");
  if (before.proofTranscript.includes("Recorded your lemma contribution"))
    throw new Error("proof request became a lemma contribution");
  if (before.staleCount < 2) throw new Error("stale proof/test not rendered");
  if (!before.planBody.includes("conflict") || before.planBody.includes("compatible"))
    throw new Error("test plan not state-derived");
  if (after.stale < 2) throw new Error("stale markers lost after reload");
  if (!after.planBody.includes("conflict")) throw new Error("plan not resumed after reload");
  if (before.errors.length || after.errors.length)
    throw new Error("page errors: " + before.errors.concat(after.errors).join(" | "));

  const shot = await cdp.send("Page.captureScreenshot", { format: "png" });
  writeFileSync(OUT, Buffer.from(shot.data, "base64"));
  console.log(JSON.stringify({ ok: true, screenshot: OUT, before, after }, null, 2));
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: String(error && error.stack || error) }));
  process.exitCode = 1;
} finally {
  try { cdp?.ws?.close(); } catch (_) { /* ignore */ }
  child.kill();
}