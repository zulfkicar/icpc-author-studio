import assert from "node:assert/strict";
import { withStudioBrowser } from "./studio_cdp.mjs";

const runId = process.env.STUDIO_T36_RUN;
assert.match(runId || "", /^run-[a-f0-9]+$/);
await withStudioBrowser(process.env.ENGINE_UI_BASE, async ({ open, run, send }) => {
  const address = "/#problem=" + encodeURIComponent(runId);
  await open(address);
  await run(`
    await press('Run mutation matrix', '#collab-transcript');
    await wait(() => $('.studio-mutation-table tbody td[data-status="killed"]'), 'caught mutant');
    check($('.studio-mutation-table').textContent.includes('Control passed'), 'control result');
    check($('.studio-mutation-table').textContent.includes('Survived'), 'surviving mutant');
  `);
  await open(address);
  const saved = await run(`
    const matrix = await wait(() => $('.studio-mutation-table'), 'saved matrix');
    return {cases: matrix.tBodies[0].rows.length, link: $('.studio-mutation-card a').textContent,
      heads: [...matrix.tHead.rows[0].cells].map(cell => cell.textContent)};
  `);
  assert.equal(saved.cases, 1);
  assert.equal(saved.link, "Open matrix report");
  assert.ok(saved.heads.some(value => value.includes("31-bit reward total") && value.includes("Survived")));
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  const narrow = await run(`
    await wait(() => window.innerWidth === 390, 'phone viewport');
    const scroll = $('.studio-mutation-scroll');
    return {viewport: document.documentElement.clientWidth, document: document.documentElement.scrollWidth,
      matrix: scroll.clientWidth, contents: scroll.scrollWidth};
  `);
  assert.equal(narrow.document, narrow.viewport);
  assert.ok(narrow.contents > narrow.matrix, "wide results scroll inside the card");
  console.log("Chrome verified the matrix, survivor label and persisted results after reload.");
});
