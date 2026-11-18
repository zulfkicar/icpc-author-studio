// Rendered recovery journey: failed interpretation, reload, explicit Retry.
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9336;
const BASE = process.env.ENGINE_UI_BASE || "http://127.0.0.1:8915";
const OUT = process.env.ENGINE_UI_SCREENSHOT_RECOVERY
  || join(process.cwd(), "qa", "engine_contracts", "evidence", "ui-chat-recovery.png");

const profile = mkdtempSync(join(tmpdir(), "engine-ui-recovery-"));
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
    await waitFor(() => box.value === '', 'composer cleared');
    await sleep(250);
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
    throw new Error("artifact body timeout " + prefix);
  };
`;

const beforeReload = `(async () => {
  ${helpers}
  const errors = [];
  window.addEventListener('error', (event) => errors.push(String(event.message || event.error)));
  document.getElementById('collab-btn').click();
  await waitFor(() => !document.getElementById('collab-panel').hidden, 'panel');
  document.getElementById('collab-new').click();
  await sleep(600);
  await send('Help me develop profitable bookings; work with me, briefly.');
  await waitFor(() => all('.collab-msg.decision').length === 1, 'decision');
  document.querySelector('.collab-msg.decision .collab-option').click();
  await waitFor(() => text('#collab-transcript').includes('independent subset oracle'), 'settled');
  await send('\\\`\\\`\\\`cpp\\n#include <bits/stdc++.h>\\nint main(){ /* RECOVERY_ORIGINAL */ return 0; }\\n\\\`\\\`\\\`');
  await waitFor(() => all('#collab-artifacts button.artifact-link')
    .some((b) => (b.textContent || '').startsWith('solutions/')), 'solution');
  const before = await inspect('solutions/');
  await send('Apply your proposed fix.');
  await waitFor(() => all('.collab-msg.recovery').length === 1, 'recovery card');
  const recoveryText = text('.collab-msg.recovery');
  const afterFailure = await inspect('solutions/');
  return { errors, before, afterFailure, recoveryText,
           runId: window.localStorage.getItem('authorAgent.engineRun') };
})()`;

const afterReload = `(async () => {
  ${helpers}
  const errors = [];
  window.addEventListener('error', (event) => errors.push(String(event.message || event.error)));
  document.getElementById('collab-btn').click();
  await waitFor(() => !document.getElementById('collab-panel').hidden, 'panel after reload');
  await waitFor(() => all('.collab-msg.recovery').length === 1, 'recovery card after reload');
  const retry = document.querySelector('.collab-msg.recovery .collab-option');
  if (!retry) throw new Error('Retry control missing');
  retry.click();
  await waitFor(() => all('#collab-artifacts button.artifact-link')
    .filter((b) => (b.textContent || '').startsWith('solutions/')).length >= 2,
    'recovered artifact');
  const recovered = await inspect('solutions/', 'demo repair applied');
  const history = text('#collab-transcript');
  const status = text('#collab-status');
  return { errors, recovered, history, status,
           runId: window.localStorage.getItem('authorAgent.engineRun') };
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
  const before = await cdp.eval(beforeReload);
  await cdp.send("Page.reload");
  await sleep(2500);
  const after = await cdp.eval(afterReload);

  if (!before.before.includes("RECOVERY_ORIGINAL")) throw new Error("original missing");
  if (before.afterFailure.includes("demo repair")) throw new Error("failed turn mutated solution");
  if (!before.recoveryText.includes("Interpretation failed")) throw new Error("failure not explained");
  if (!after.recovered.includes("demo repair applied")) throw new Error("recovery did not publish");
  if (!after.history.includes("Interpretation failed")) throw new Error("failure history lost");
  if (!after.status) throw new Error("status missing");
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