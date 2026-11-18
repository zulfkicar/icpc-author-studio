// Local Chrome wrapper for the Studio acceptance and timing scripts.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
export async function withStudioBrowser(base, exercise) {
  assert.match(base, /^http:\/\/127\.0\.0\.1:\d+$/);
  const port = process.env.STUDIO_CDP_PORT || "9338";
  const chrome = spawn("C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", [
    "--headless=new", "--disable-gpu", "--no-first-run", "--window-size=1280,900", `--remote-debugging-port=${port}`,
    `--user-data-dir=${mkdtempSync(join(tmpdir(), "studio-qa-"))}`, "about:blank",
  ], { stdio: "ignore" });
  let ws;
  try {
    let tab;
    for (let i = 0; i < 60 && !tab; i++) {
      try { tab = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(item => item.type === "page"); }
      catch { await pause(200); }
    }
    assert.ok(tab, "Chrome target");
    ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
    const pending = new Map();
    const errors = [];
    let id = 0;
    ws.onmessage = event => {
      const msg = JSON.parse(event.data);
      if (msg.method === "Runtime.exceptionThrown") errors.push(msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text);
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
    const browser = (await send("Browser.getVersion")).product;
    const run = async source => {
      const result = await send("Runtime.evaluate", { expression: `(async()=>{${helpers}\n${source}})()`,
        awaitPromise: true, returnByValue: true, userGesture: true });
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
      return result.result.value;
    };
    const open = async (path = "/") => {
      await send("Page.navigate", { url: base + path });
      await pause(500);
      await run(`await wait(() => $('#collab-panel') && !$('#collab-panel').hidden, 'Studio open');`);
    };
    const shot = async () => Buffer.from((await send("Page.captureScreenshot", { format: "png" })).data, "base64");
    await exercise({ send, run, open, shot, browser });
    assert.deepEqual(errors, [], "page exceptions");
  } finally { ws?.close(); chrome.kill(); }
}

const helpers = String.raw`
  const $ = sel => document.querySelector(sel);
  const $$ = sel => [...document.querySelectorAll(sel)];
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  const wait = async (fn, name) => {
    for (let i = 0; i < 300; i++) { const value = fn(); if (value) return value; await delay(100); }
    throw new Error(name + ': ' + ($('#studio-output')?.innerText || '').slice(0, 700) + ' | ' + $('#studio-alert')?.innerText);
  };
  const output = () => $('#studio-output').innerText;
  const click = selector => $(selector).click();
  const button = (label, scope = '#studio-output') => $$(scope + ' button').find(el => el.textContent.trim() === label && !el.disabled);
  const press = async (label, scope) => (await wait(() => button(label, scope), label)).click();
  const check = (value, message) => { if (!value) throw new Error(message); };
  const json = async (url, body) => {
    const response = await fetch(url, body === undefined ? {} : {method: 'POST',
      headers: {'content-type': 'application/json'}, body: JSON.stringify(body) });
    const data = await response.json(); check(response.ok, url + ' ' + JSON.stringify(data)); return data;
  };
  const type = (input, text) => { input.value = text; input.dispatchEvent(new Event('input', {bubbles: true})); };
  const command = async text => {
    click('#studio-commands');
    type($('#studio-search-input'), text);
    (await wait(() => $('#studio-search-results [role="option"]'), text)).click();
  };
`;
