import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { withStudioBrowser } from "./studio_cdp.mjs";

const { ENGINE_UI_BASE: base, STUDIO_RELEASE_FOUR_EVIDENCE: evidence } = process.env;
const { sample } = JSON.parse(readFileSync(join(evidence, "journey.json"), "utf8"));
await withStudioBrowser(base, async ({ browser, send, run, open, shot }) => {
  const key = async (value, code, numeric, modifiers = 0) => {
    await send("Input.dispatchKeyEvent", { type: "keyDown", key: value, code, windowsVirtualKeyCode: numeric, modifiers,
      ...(value === "Enter" ? { text: "\r" } : {}) });
    await send("Input.dispatchKeyEvent", { type: "keyUp", key: value, code, windowsVirtualKeyCode: numeric, modifiers });
  };
  await open(`/#problem=${sample.runId}`);
  await run(`await wait(() => $('#studio-title').textContent.includes('Canal Bookings') && !$('#studio-new-file').hidden, 'saved sample');
    $('#studio-commands').focus();`);
  await key("k", "KeyK", 75, 1);
  await run(`await wait(() => document.activeElement === $('#studio-search-input'), 'command focus');`);
  await send("Input.insertText", { text: "verify package" });
  await key("ArrowDown", "ArrowDown", 40);
  await key("Enter", "Enter", 13);
  await run(`await wait(() => output().includes('Package verified'), 'keyboard opens verification');
    check(document.activeElement === $('#studio-output-title'), 'output receives focus');`);
  await key("Escape", "Escape", 27);
  await run(`await wait(() => $('#studio-output').hidden, 'keyboard closes output');
    check(document.activeElement === $('#studio-commands'), 'output returns focus');`);
  await key("o", "KeyO", 79, 1);
  await send("Input.insertText", { text: "reference.py" });
  await key("Enter", "Enter", 13);
  await run(`await wait(() => $('#studio-file-path').textContent.includes('reference.py'), 'keyboard opens saved file');
    $('#studio-commands').focus();`);
  await key("r", "KeyR", 82, 1);
  await run(`await wait(() => $('textarea[aria-label="Standard input"]'), 'keyboard opens run');`);
  await key("Escape", "Escape", 27);
  const layouts = [];
  for (const width of [320, 390, 640, 768, 1280, 1440]) {
    const scale = width === 640 ? 2 : 1;
    const mode = width < 768 ? "dark" : "light";
    await send("Emulation.setDeviceMetricsOverride", { width, height: 850, deviceScaleFactor: scale, mobile: width < 768 });
    await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: mode },
      { name: "prefers-reduced-motion", value: "reduce" }, { name: "forced-colors", value: width <= 390 ? "active" : "none" }] });
    layouts.push(await run(`
      await wait(() => innerWidth === ${width}, 'reflow width');
      check(document.documentElement.scrollWidth === innerWidth, 'page does not overflow');
      check($('#studio-commands').getBoundingClientRect().right <= innerWidth, 'commands reachable');
      check(matchMedia('(prefers-reduced-motion: reduce)').matches, 'reduced motion');
      return {width: innerWidth, pixelRatio: devicePixelRatio, theme: '${mode}', forcedColors: matchMedia('(forced-colors: active)').matches};
    `));
  }
  await send("Emulation.setDeviceMetricsOverride", {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
  await send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 1 });
  await run(`click('[data-layout="chat"]');`);
  const tap = async selector => {
    const point = await run(`const r = $(${JSON.stringify(selector)}).getBoundingClientRect();
      return {x:r.left+r.width/2,y:r.top+r.height/2};`);
    await send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [point] });
    await send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  };
  await tap("#studio-context-trigger");
  await run(`await wait(() => $('#studio-context').matches(':popover-open'), 'touch opens context');`);
  await tap("#studio-context-categories button");
  await run(`await wait(() => $('#studio-context-categories button').getAttribute('aria-pressed') === 'true', 'touch selects category');`);
  const ax = await send("Accessibility.getFullAXTree");
  assert.ok(ax.nodes.some(item => item.role?.value === "button" && item.name?.value?.startsWith("Conversation")));
  assert.ok(ax.nodes.some(item => item.role?.value === "status"));
  writeFileSync(join(evidence, "context-touch-390.png"), await shot());
  await tap("#studio-title");
  await run(`await wait(() => !$('#studio-context').matches(':popover-open'), 'tap outside dismisses context');`);
  const conflict = await run(String.raw`
    const operator = (await json('/api/engine/runs')).runs.find(item => !item.sample);
    const {slug} = await json('/api/engine/runs/' + operator.runId + '/studio-package');
    window.dispatchEvent(new CustomEvent('studio-select-problem', {detail: operator.runId}));
    await wait(() => $('#studio-package-label').textContent.includes('Manual setter fixture'), 'manual package');
    click('#studio-files');
    type($('#studio-search-input'), 'sum.py');
    (await wait(() => $('#studio-search-results [role="option"]'), 'manual source')).click();
    const model = await wait(() => window.monaco?.editor.getModels().find(item => item.getValue().startsWith('print(sum(')), 'editor model');
    const path = 'submissions/accepted/sum.py';
    const url = '/api/workspaces/' + slug + '/file';
    const initial = await json(url + '?path=' + encodeURIComponent(path));
    model.setValue(initial.content + '# retained draft\n');
    await json(url, { path, content: initial.content + '# edit from another tab\n', expectedHash: initial.hash });
    click('#studio-save');
    await wait(() => output().includes('disk copy changed'), 'save conflict shown');
    check(model.getValue().includes('# retained draft'), 'author draft remains');
    const current = await json(url + '?path=' + encodeURIComponent(path));
    check(current.content.includes('# edit from another tab'), 'saved file kept newer change');
    return true;
  `);
  const record = { browser, layouts, keyboard: true, touch: true, accessibilityTree: true, speechTested: false, conflict };
  writeFileSync(join(evidence, "accessibility.json"), JSON.stringify(record, null, 2));
  console.log(JSON.stringify(record));
});
