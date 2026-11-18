// Rendered-browser journey for the conversation-first authoring UI.
// No external dependencies: headless Chrome + CDP over the built-in WebSocket.
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9333;
const BASE = process.env.ENGINE_UI_BASE || "http://127.0.0.1:8898";
const OUT = process.env.ENGINE_UI_SCREENSHOT || join(process.cwd(), "qa", "engine_contracts", "evidence", "ui-chat.png");

const profile = mkdtempSync(join(tmpdir(), "engine-ui-profile-"));
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
  const waitFor = async (fn, label, timeout = 45000) => {
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
    await waitFor(() => box.value === '' , 'composer cleared for: ' + message.slice(0, 30));
  };
`;

const journeyScript = `(async () => {
  ${helpers}
  const errors = [];
  window.addEventListener('error', (event) => errors.push(String(event.message || event.error)));
  document.getElementById('collab-btn').click();
  await waitFor(() => !document.getElementById('collab-panel').hidden, 'panel open');
  await waitFor(() => (document.getElementById('collab-disclosure')?.textContent || '').includes('explicitly labelled demo'), 'demo disclosure');
  const disclosure = document.getElementById('collab-disclosure')?.textContent || '';

  document.getElementById('collab-new').click();
  await sleep(300);
  await send('Help me develop profitable bookings; work with me, briefly.');
  await waitFor(() => all('.collab-msg.decision').length === 1, 'inline decision card');
  const question = text('.collab-msg.decision .body');
  const decisionCards = all('.collab-msg.decision').length;

  const option = await waitFor(() => document.querySelector('.collab-msg.decision .collab-option'), 'option button');
  option.click();
  await waitFor(() => text('#collab-transcript').includes('independent subset oracle'), 'explanation after answer');
  await waitFor(() => all('#collab-artifacts button.artifact-link').length >= 3, 'derived artifacts');
  const artifactsAfterAnswer = all('#collab-artifacts button.artifact-link').map((b) => b.textContent);
  const statusAfterAnswer = text('#collab-status');

  await send('Lemma: sorting by finish time and taking the best compatible prefix is optimal.');
  await waitFor(() => all('#collab-artifacts button.artifact-link').some((b) => b.textContent.startsWith('proof/')), 'proof artifact');
  const proofVisible = all('.collab-msg.artifact').some((m) => m.innerText.includes('proof/'));

  await send('Correction: treat touching jobs as conflicting; use closed intervals.');
  await waitFor(() => text('#collab-transcript').includes('closed'), 'correction rendered');
  const staleArtifact = all('#collab-artifacts .state.unverified').length\n    + all('#collab-artifacts .state.superseded').length;

  await send('Why did we choose the endpoint rule?');
  await waitFor(() => text('#collab-transcript').includes('endpoint_semantics'), 'why answer');

  const artifactButton = all('#collab-artifacts button.artifact-link')[0];
  artifactButton.click();
  await waitFor(() => !document.getElementById('collab-artifact-body').hidden, 'artifact body');
  const artifactBody = text('#collab-artifact-body');
  document.getElementById('collab-export').click();
  await waitFor(() => text('#collab-receipt').toLowerCase().includes('refused'), 'export refusal');
  const receipt = text('#collab-receipt');
  return { disclosure, question, decisionCards, artifactsAfterAnswer, statusAfterAnswer,
           proofVisible, staleArtifact, artifactBody, receipt, errors,
           runId: window.localStorage.getItem('authorAgent.engineRun') };
})()`;

const reloadScript = `(async () => {
  ${helpers}
  const errors = [];
  window.addEventListener('error', (event) => errors.push(String(event.message || event.error)));
  document.getElementById('collab-btn').click();
  await waitFor(() => !document.getElementById('collab-panel').hidden, 'panel open after reload');
  await waitFor(() => all('.collab-msg.author').length >= 1, 'transcript resumed');
  const resumed = {
    idea: all('.collab-msg.author').length,
    decisions: all('.collab-msg.decision').length,
    proof: all('#collab-artifacts button.artifact-link').some((b) => b.textContent.startsWith('proof/')),
    transcript: text('#collab-transcript').slice(-1200), lemma: text('#collab-transcript').includes('Lemma'),
  };
  await send('continue');
  await waitFor(() => all('.collab-msg.handoff').length >= 1, 'continued handoff');
  return { resumed, errors, status: text('#collab-status') };
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
  const before = await cdp.eval(journeyScript);
  await cdp.send("Page.reload");
  await sleep(2500);
  const after = await cdp.eval(reloadScript);

  if (!before.question.toLowerCase().includes("both run")) throw new Error("decision question missing");
  if (before.decisionCards !== 1) throw new Error("decision card not inline or duplicated");
  if (!before.artifactsAfterAnswer.some((p) => p.startsWith("spec/"))) throw new Error("spec artifact missing");
  if (!before.proofVisible) throw new Error("proof artifact update not in transcript");
  if (!before.artifactBody.includes("half_open") && !before.artifactBody.includes("endpoint"))
    throw new Error("artifact inspection did not show content");
  if (!before.receipt.toLowerCase().includes("refused")) throw new Error("export refusal not rendered");
  if (!before.staleArtifact) throw new Error("correction did not mark superseded artifacts");
  if (!after.resumed.decisions) throw new Error("decision card missing after reload");
  if (!after.resumed.proof) throw new Error("proof artifact missing after reload");
  if (!after.resumed.lemma) throw new Error("transcript not resumed after reload");
  if (!after.status) throw new Error("status missing after continue");
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