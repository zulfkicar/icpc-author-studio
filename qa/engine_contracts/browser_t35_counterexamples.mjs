import assert from "node:assert/strict";
import { withStudioBrowser } from "./studio_cdp.mjs";

const runId = process.env.STUDIO_T35_RUN;
assert.match(runId || "", /^run-[a-f0-9]+$/);
await withStudioBrowser(process.env.ENGINE_UI_BASE, async ({ open, run }) => {
  const address = "/#problem=" + encodeURIComponent(runId);
  await open(address);
  const original = await run(`
    const card = await wait(() => $('.studio-case-card'), 'campaign witness');
    const original = card.querySelector('pre').textContent;
    await press('Replay original', '#collab-transcript');
    await wait(() => $('#collab-transcript').innerText.includes('reproduced the same expected and actual answers'), 'replay result');
    await press('Replay and reduce', '#collab-transcript');
    await wait(() => $$('b').some(el => el.textContent === 'Reduced input'), 'reduced result');
    return original;
  `);
  await open(address);
  const pair = await run(`
    const reduced = await wait(() => $$('.collab-msg[data-kind="counterexample"]').find(msg => msg.textContent.includes('Reduced input')), 'saved pair');
    return [...reduced.querySelectorAll('.studio-case-card')].map(card => ({label: card.querySelector('b').textContent, input: card.querySelector('pre').textContent}));
  `);
  assert.deepEqual(pair.map(item => item.label), ["Original input", "Reduced input"]);
  assert.equal(pair[0].input, original);
  assert.equal(Number(pair[1].input.split("\n")[0]), 2);
  console.log("Chrome verified replay, reduction and both saved inputs after reload.");
});
