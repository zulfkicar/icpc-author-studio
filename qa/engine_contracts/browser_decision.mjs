// Rendered-browser decision-layer journey (hostile admission + exhausted budget).
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9335;
const BASE = process.env.ENGINE_UI_BASE || "http://127.0.0.1:8910";
const OUT = process.env.ENGINE_UI_SCREENSHOT_DECISION
  || join(process.cwd(), "qa", "engine_contracts", "evidence", "ui-chat-decision.png");

const profile = mkdtempSync(join(tmpdir(), "engine-ui-decision-"));
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
    await sleep(1200);
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
      if (value.includes(prefix) && (!contains || value.includes(contains))) return value;
      await sleep(150);
    }
    throw new Error("artifact body timeout " + prefix + " :: " + (body.textContent || "").slice(0, 160));
  };
`;

const journey = `(async () => {
  ${helpers}
  const errors = [];
  window.addEventListener('error', (event) => errors.push(String(event.message || event.error)));
  document.getElementById('collab-btn').click();
  await waitFor(() => !document.getElementById('collab-panel').hidden, 'panel open');

  // Hostile admission: refusals/questions must not touch the managed solution.
  await newChat();
  await send('Help me develop profitable bookings; work with me, briefly.');
  await waitFor(() => all('.collab-msg.decision').length === 1, 'decision');
  document.querySelector('.collab-msg.decision .collab-option').click();
  await waitFor(() => text('#collab-transcript').includes('independent subset oracle'), 'settled');
  await send('\\\`\\\`\\\`cpp\\n#include <bits/stdc++.h>\\nint main(){ /* BROWSER_ORIGINAL */ return 0; }\\n\\\`\\\`\\\`');
  await waitFor(() => all('#collab-artifacts button.artifact-link')
    .some((b) => (b.textContent || '').startsWith('solutions/')), 'solution');
  const before = await inspect('solutions/');
  await send("Don't apply your proposed fix.");
  await sleep(900);
  const afterRefusal = await inspect('solutions/');
  await send('Explain whether we should apply your proposed fix.');
  await sleep(900);
  const afterQuestion = await inspect('solutions/');
  await send('Apply your proposed fix.');
  await waitFor(() => all('#collab-artifacts button.artifact-link')
    .filter((b) => (b.textContent || '').startsWith('solutions/')).length >= 2, 'approval artifact');
  const afterApproval = await inspect('solutions/', 'demo repair applied');

  // Exhausted decision budget: no hidden call, no fake result, cancel still works.
  await sleep(1200);
  await newChat();
  await send('Help me develop profitable bookings.');
  await waitFor(() => all('.collab-msg.decision').length === 1, 'budget decision');
  const runId = window.localStorage.getItem('authorAgent.engineRun');
  const exhausted = await fetch('/test/exhaust', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({runId}),
  }).then((response) => response.json());
  await send('Maybe closed intervals?');
  await sleep(1200);
  const budgetTranscript = text('#collab-transcript');
  const budgetCardOpen = all('.collab-msg.decision .collab-option').length > 0;
  await send('cancel');
  await waitFor(() => text('#collab-status').toLowerCase().includes('cancel'), 'cancelled');
  const cancelledStatus = text('#collab-status');
  const composerEnabled = !document.getElementById('collab-composer').disabled;
  return { errors, before, afterRefusal, afterQuestion, afterApproval,
           exhausted, budgetTranscript, budgetCardOpen, cancelledStatus, composerEnabled,
           budgetRunId: runId };
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
  const result = await cdp.eval(journey);

  if (!result.before.includes("BROWSER_ORIGINAL")) throw new Error("original solution missing");
  if (result.afterRefusal.includes("demo repair")) throw new Error("refusal published");
  if (result.afterQuestion.includes("demo repair")) throw new Error("question published");
  if (!result.afterApproval.includes("demo repair applied")) throw new Error("approval failed");
  if (!result.exhausted || typeof result.exhausted.used !== "number")
    throw new Error("budget exhaustion hook failed");
  if (!result.budgetTranscript.toLowerCase().includes("budget")
      && !result.budgetTranscript.toLowerCase().includes("did not apply"))
    throw new Error("exhaustion not explained");
  if (!result.budgetCardOpen) throw new Error("semantic card was lost at exhaustion");
  if (!result.cancelledStatus.toLowerCase().includes("cancel"))
    throw new Error("safe cancellation did not work");
  if (!result.composerEnabled) throw new Error("composer disabled after exhaustion");
  if (result.errors.length) throw new Error("page errors: " + result.errors.join(" | "));

  const shot = await cdp.send("Page.captureScreenshot", { format: "png" });
  writeFileSync(OUT, Buffer.from(shot.data, "base64"));
  console.log(JSON.stringify({ ok: true, screenshot: OUT, ...result }, null, 2));
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: String(error && error.stack || error) }));
  process.exitCode = 1;
} finally {
  try { cdp?.ws?.close(); } catch (_) { /* ignore */ }
  child.kill();
}