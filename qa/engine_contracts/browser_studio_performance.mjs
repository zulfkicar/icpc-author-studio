import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { withStudioBrowser } from "./studio_cdp.mjs";

const { ENGINE_UI_BASE: base, STUDIO_PERF_FIXTURES: file, STUDIO_PERF_OUT: out } = process.env;
const fixtures = JSON.parse(readFileSync(file, "utf8"));
const results = [];
await withStudioBrowser(base, async ({ browser, run, open, send }) => {
  for (const fixture of fixtures) {
    await open(`/#problem=${encodeURIComponent(fixture.runId)}`);
    const measured = await run(`
      const fixture = ${JSON.stringify(fixture)};
      await wait(() => $('#studio-title').textContent.includes(fixture.messages + ' turns') &&
        !$('#studio-new-file').hidden && $('.collab-msg'), 'timing fixture selected');
      const displayed = $$('.collab-msg').length;
      const latest = $('#collab-transcript').textContent.includes('Turn ' + fixture.messages + ' of');
      const samples = (series) => {
        const sorted = [...series].sort((a,b) => a-b);
        return {n: series.length, p50: +sorted[Math.ceil(series.length*.5)-1].toFixed(2),
          p95: +sorted[Math.ceil(series.length*.95)-1].toFixed(2)};
      };
      const box = $('#collab-composer');
      box.focus();
      type(box, 'Stable keyboard draft');
      box.setSelectionRange(3, 8);
      await delay(2200);
      check(document.activeElement === box && box.value === 'Stable keyboard draft' && box.selectionStart === 3 && box.selectionEnd === 8,
        'caret and draft survive poll');
      const frame = () => new Promise(resolve => requestAnimationFrame(resolve));
      const timings = {composerHandler: [], composerFrame: [], fileOpenHandler: [], fileFilterHandler: [], reportFilterHandler: []};
      for (let i=0; i<30; i++) {
        const start = performance.now();
        type(box, 'Stable keyboard draft ' + i);
        timings.composerHandler.push(performance.now() - start);
        await frame();
        timings.composerFrame.push(performance.now() - start);
      }
      for (let i=0; i<30; i++) {
        let start = performance.now(); click('#studio-files');
        timings.fileOpenHandler.push(performance.now() - start);
        const search = $('#studio-search-input');
        start = performance.now(); type(search, i%2 ? 'case' : 'case-00');
        timings.fileFilterHandler.push(performance.now() - start);
        $('#studio-search-dialog').close();
        await frame();
      }
      const started = performance.now();
      click('[data-operation="verify"]');
      const filter = await wait(() => $('select[aria-label="Test group"]'), 'big report');
      const reportToControl = +(performance.now() - started).toFixed(2);
      for (let i=0; i<30; i++) {
        filter.selectedIndex = i % Math.min(3, filter.options.length);
        const start = performance.now(); filter.dispatchEvent(new Event('change'));
        timings.reportFilterHandler.push(performance.now() - start);
        await frame();
      }
      return {displayed, latest, reportToControl, caretPreserved: true,
        ...Object.fromEntries(Object.entries(timings).map(([key,value]) => [key,samples(value)]))};
    `);
    let historyRestored = null;
    if (fixture.messages === 500 && measured.latest) {
      const top = await run(`
        click('[data-layout="chat"]');
        await wait(() => !$('#studio-chat-earlier').hidden, 'earlier control');
        click('#studio-chat-earlier');
        await wait(() => $('#collab-transcript').textContent.includes('Turn 301 of 500'), 'older page');
        const chat = $('#collab-transcript');
        chat.scrollTop = 520;
        chat.dispatchEvent(new Event('scroll'));
        await delay(240);
        return chat.scrollTop;
      `);
      await send("Page.reload");
      historyRestored = await run(`
        const chat = $('#collab-transcript');
        await wait(() => chat.textContent.includes('Turn 301 of 500'), 'earlier page restored');
        check(chat.textContent.includes('Turn 500 of 500'), 'latest turn retained');
        check(Math.abs(chat.scrollTop - ${top}) < 35, 'reading position restored');
        return true;
      `);
    }
    results.push({ ...fixture, ...measured, historyRestored });
  }
  assert.equal(results.length, 2);
  const summary = { browser, providerCalls: 0, fixtures: results };
  writeFileSync(out, JSON.stringify(summary, null, 2));
  console.log(JSON.stringify(summary));
});
