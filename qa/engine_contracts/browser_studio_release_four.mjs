// End-to-end exercise for an empty, disposable, unconfigured Studio instance.
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pause, withStudioBrowser } from "./studio_cdp.mjs";

const base = process.env.ENGINE_UI_BASE;
const out = process.env.STUDIO_RELEASE_FOUR_EVIDENCE;
assert.ok(out);
mkdirSync(out, { recursive: true });

await withStudioBrowser(base, async ({ send, run, open, shot, browser }) => {
  await open();
  const operator = await run(String.raw`
    check((await json('/api/engine/runs')).runs.length === 0, 'an empty isolated instance is required');
    $('#studio-context-trigger').focus(); click('#studio-context-trigger');
    check($('#studio-context').matches(':popover-open') && $('#studio-context-summary').innerText.includes('No context receipt'), 'unknown context');
    $('#studio-context').hidePopover();
    type($('#collab-composer'), 'Manual setter workspace for a sum problem.');
    click('#collab-send');
    await wait(() => $('#studio-title').textContent.includes('Manual setter'), 'manual conversation');
    const original = (await json('/api/engine/runs')).runs[0].runId;
    const link = await json('/api/engine/runs/' + original + '/studio-package', {name: 'Manual setter fixture', expectedSlug: null});
    type($('#collab-composer'), 'Unsaved note in the manual problem.');
    await command('open canal bookings sample');
    await wait(() => !$('#studio-sample-label').hidden && $('#studio-title').textContent.includes('Canal Bookings'), 'isolated sample selected');
    check(!$('#collab-composer').value.includes('Unsaved note'), 'sample uses different composer');
    const choice = await wait(() => $$('.collab-option').find(item => item.textContent.includes('Half-open')), 'sample choice');
    $('#studio-context-trigger').focus(); click('#studio-context-trigger');
    check($('#studio-context-summary').innerText.includes('Estimated'), 'sample estimate');
    check(!$('#studio-context-summary').innerText.includes('No context receipt'), 'has request');
    check($('#studio-context-map').children.length === 40, 'compact category map');
    return { original, manual: link.slug };
  `);
  await run(`const choice = $('#studio-context-categories button'); choice.focus();
    check(document.activeElement === choice, 'category can take keyboard focus');`);
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: " ", code: "Space", text: " ", windowsVirtualKeyCode: 32 });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: " ", code: "Space", windowsVirtualKeyCode: 32 });
  await run(`await wait(() => $('#studio-context-categories button').getAttribute('aria-pressed') === 'true', 'keyboard category selection');`);
  writeFileSync(join(out, "context.png"), await shot());
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape" });
  await run(`await wait(() => !$('#studio-context').matches(':popover-open'), 'Escape dismisses context');
    check(document.activeElement === $('#studio-context-trigger'), 'focus returned to context button');
    const choice = $$('.collab-option').find(item => item.textContent.includes('Half-open'));
    choice.scrollIntoView();`);
  writeFileSync(join(out, "choice.png"), await shot());
  const replay = await run(String.raw`
    $$('.collab-option').find(item => item.textContent.includes('Half-open')).click();
    const card = await wait(() => $('.studio-case-card'), 'counterexample');
    check(card.innerText.includes('Simulated worker'), 'labelled conversation worker');
    const roles = $('#studio-context-role');
    await wait(() => roles.options.length === 2, 'authoring and decision receipts');
    roles.value = 'Decision'; roles.dispatchEvent(new Event('change'));
    check($('#studio-context-summary').textContent.includes('Decision') && $('#studio-context-summary').textContent.includes('capacity is unknown'), 'decision size and unknown capacity');
    const sample = (await json('/api/engine/runs')).runs.find(item => item.sample);
    const linked = await json('/api/engine/runs/' + sample.runId + '/studio-package');
    return { runId: sample.runId, slug: linked.slug };
  `);
  writeFileSync(join(out, "counterexample.png"), await shot());
  const request = await run(`
    const pack = ${JSON.stringify("/api/workspaces/" + replay.slug)};
    await press('Run this case', '.studio-case-card');
    await wait(() => $('textarea[aria-label="Standard input"]')?.value.includes('0 4 13'), 'case staged');
    let accepted;
    const originalFetch = window.fetch;
    window.fetch = async (url, options) => {
      const response = await originalFetch(url, options);
      if (url === pack + '/run' && options?.method === 'POST') {
        accepted = await response.json();
        throw new TypeError('test: launch response lost after server acceptance');
      }
      return response;
    };
    await press('Run saved source');
    await wait(() => button('Reconnect to job'), 'ambiguous job launch');
    return {id: accepted.id, requestId: accepted.requestId};
  `);
  await send("Page.reload");
  await pause(700);
  await run(`
    const pack = ${JSON.stringify("/api/workspaces/" + replay.slug)};
    await wait(() => !$('#studio-sample-label').hidden, 'sample selection restored');
    const receipt = await json(pack + '/studio-job?requestId=' + ${JSON.stringify(request.requestId)});
    check(receipt.id === ${JSON.stringify(request.id)}, 'same job after missing POST response');
    click('[data-operation="run"]');
    await wait(() => output().includes('Output mismatch') && output().includes('Local process'), 'recovered real mismatch');
    await press('Load sample fix');
    await press('Save & Run');
    await wait(() => output().includes('Matches expected output') && output().includes('13'), 'fix executed');
  `);
  writeFileSync(join(out, "fixed.png"), await shot());
  const archive = await run(`
    const pack = ${JSON.stringify("/api/workspaces/" + replay.slug)};
    click('[data-operation="answers"]');
    await press('Build expected answers');
    await wait(() => output().includes('2 answer file(s) written'), 'sample answers');
    await press('Open verification');
    await press('Measure limits');
    await press('Measure saved package');
    await wait(() => output().includes('Limits measured'), 'limits');
    await press('Open verification');
    await press('Verify saved package');
    await wait(() => output().includes('Package verified'), 'sample verification');
    click('[data-operation="export"]');
    await press('Review package changes');
    const info = await json(pack + '/studio');
    check(info.workflow.nextAction === 'review' && !button('Generate ZIP'), 'human gate');
    await press('Approve saved snapshot');
    await press('Generate ZIP');
    const link = await wait(() => $('#studio-output .studio-download'), 'download ready');
    const response = await fetch(link.href);
    check(response.ok && response.headers.get('content-type') === 'application/zip', 'actual archive downloaded');
    return { snapshot: info.snapshot, url: link.href, bytes: (await response.arrayBuffer()).byteLength };
  `);
  writeFileSync(join(out, "export.png"), await shot());
  writeFileSync(join(out, "sample-domjudge.zip"), Buffer.from(await (await fetch(archive.url)).arrayBuffer()));
  await send("Emulation.setEmulatedMedia", { features: [{ name: "forced-colors", value: "active" }, { name: "prefers-reduced-motion", value: "reduce" }] });
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  const manual = await run(String.raw`
    const target = ` + JSON.stringify(operator) + String.raw`;
    window.dispatchEvent(new CustomEvent('studio-select-problem', {detail: target.original}));
    await wait(() => $('#studio-title').textContent.includes('Manual setter') && !$('#studio-package').hidden, 'return to manual problem');
    click('[data-layout="chat"]');
    check($('#collab-composer').value === 'Unsaved note in the manual problem.', 'operator draft retained');
    const pack = '/api/workspaces/' + target.manual;
    const latex = String.fromCharCode(92);
    const files = {
      'problem_statement/problem.en.tex': latex + 'documentclass{article}\n' + latex + 'begin{document}\nFind the sum.\n' + latex + 'end{document}\n',
      'submissions/accepted/sum.py': 'print(sum(map(int,input().split())))\n',
      'input_validators/validate.py': 'import sys\nvalues=list(map(int,input().split()));sys.exit(42 if len(values)==2 else 1)\n',
      'data/sample/01.in': '1 2\n', 'data/secret/01.in': '4 9\n',
      'submissions/wrong_answer/subtract.py': 'a,b=map(int,input().split());print(a-b)\n',
    };
    for (const [path, content] of Object.entries(files)) await json(pack + '/file', {path, content});
    await command('run saved source');
    const stdin = await wait(() => $('textarea[aria-label="Standard input"]'), 'manual run form');
    type(stdin, '4 9');
    await press('Run saved source');
    await wait(() => output().includes('Standard output') && output().includes('13'), 'manual run result');
    await command('build expected answers');
    await press('Build expected answers');
    await wait(() => output().includes('2 answer file(s) written'), 'manual answers');
    await press('Open verification');
    await press('Measure limits'); await press('Measure saved package');
    await wait(() => output().includes('Limits measured'), 'manual limits');
    await press('Open verification'); await press('Verify saved package');
    await wait(() => output().includes('Package verified'), 'manual package verified');
    check(document.documentElement.scrollWidth === innerWidth, 'narrow no page overflow');
    check(matchMedia('(forced-colors: active)').matches && matchMedia('(prefers-reduced-motion: reduce)').matches, 'forced colors and reduced motion');
    return { width: innerWidth, manual: 'verified', unsentDraftRestored: true };
  `);
  writeFileSync(join(out, "manual-high-contrast.png"), await shot());
  const accessibility = await send("Accessibility.getFullAXTree");
  assert.ok(accessibility.nodes.some(item => item.role?.value === "status"));
  const data = { browser, sample: replay, archive, manual, recoveredJob: request.id, accessibilityTreeStatus: true };
  writeFileSync(join(out, "journey.json"), JSON.stringify(data, null, 2));
  console.log(JSON.stringify(data));
});
