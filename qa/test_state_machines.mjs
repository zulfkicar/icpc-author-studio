import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../web/machines.js", import.meta.url), "utf8");
const attributes = {};
const warnings = [];
const context = {
  window: {},
  document: { body: { setAttribute(key, value) { attributes[key] = value; } } },
  console: { warn(...args) { warnings.push(args.join(" ")); } },
  Date,
};
vm.createContext(context);
vm.runInContext(source, context);
const { definitions, machines, snapshot } = context.window.AuthorMachines;

const ids = [
  "connection", "session", "turn", "approval", "editor", "run", "modal",
  "fileLoad", "chat", "verification", "changes", "mcp", "settings",
  "mentions", "follow", "tree", "tests", "restore",
];
assert.deepEqual(Object.keys(machines).sort(), [...ids].sort(), "machine registry is complete");

// One legal path per machine. Every step asserts the resulting state and the
// mirrored data-state-* attribute.
const paths = {
  connection: [["ONLINE", "online"], ["OFFLINE", "offline"], ["ONLINE", "online"]],
  session: [["LOAD", "loading"], ["READY", "ready"], ["RESET", "no-workspace"]],
  turn: [["START", "streaming"], ["WAIT", "waiting"], ["RESUME", "streaming"], ["DONE", "idle"]],
  approval: [["ASK", "pending"], ["RESOLVE", "resolved"], ["CLEAR", "none"]],
  editor: [["OPEN", "view"], ["EDIT", "editing"], ["SAVE", "saving"], ["SAVED", "view"], ["CLOSE", "empty"]],
  run: [["READY", "ready"], ["RUN", "running"], ["PASS", "passed"], ["RESET", "ready"], ["HIDE", "hidden"]],
  modal: [["OPEN", "open"], ["CLOSE", "closed"]],
  fileLoad: [["LOAD", "loading"], ["READY", "loaded"], ["STALE", "stale"], ["LOAD", "loading"], ["READY", "loaded"], ["RESET", "none"]],
  chat: [["SELECT", "loading"], ["LOAD", "loaded"], ["RENAME", "loaded"], ["DELETE", "loading"], ["ERROR", "error"], ["LOAD", "loading"], ["LOAD", "loaded"], ["RESET", "no-chat"]],
  verification: [["VERIFY", "verifying"], ["PASS", "verified"], ["STALE", "stale"], ["VERIFY", "verifying"], ["FAIL", "failed"], ["RESET", "unverified"]],
  changes: [["CHANGE", "unreviewed"], ["REVIEW", "reviewing"], ["CONFLICT", "conflict"], ["CHANGE", "unreviewed"], ["REVERT", "reverted"], ["CLEAR", "clean"]],
  mcp: [["GRANT", "enabled"], ["EDIT", "dirty"], ["SAVE", "saving"], ["SAVED", "enabled"], ["PROBE", "probing"], ["ERROR", "error"], ["REVOKE", "disabled"]],
  settings: [["EDIT", "dirty"], ["SAVE", "saving"], ["SAVED", "saved"], ["EDIT", "dirty"], ["RESET", "clean"]],
  mentions: [["TRIGGER", "open"], ["FILTER", "filtered"], ["PICK", "picked"], ["CLOSE", "hidden"]],
  follow: [["PAUSE", "paused"], ["FOLLOW", "following"]],
  tree: [["TOGGLE", "expanded"], ["SELECT", "selected"], ["REFRESH", "collapsed"], ["SELECT", "selected"]],
  tests: [["RUN", "running"], ["PASS", "pass"], ["RUN", "running"], ["FAIL", "fail"]],
  restore: [["ASK", "confirming"], ["RESTORE", "restoring"], ["DONE", "done"], ["ASK", "confirming"], ["CLEAR", "idle"]],
};

function attributeId(id) {
  return id.replace(/[A-Z]/g, (letter) => "-" + letter.toLowerCase());
}

for (const id of ids) {
  const machine = machines[id];
  const definition = definitions[id];
  assert.ok(machine && definition, `machine ${id} exists`);

  // An illegal event is a no-op and does not change the visible state.
  const events = new Set();
  for (const state of Object.values(definition.states)) {
    for (const event of Object.keys(state.on || {})) events.add(event);
  }
  const legalAtStart = new Set(Object.keys((definition.states[definition.initial] || {}).on || {}));
  const illegal = [...events].find((event) => !legalAtStart.has(event));
  if (illegal) {
    const before = machine.state;
    assert.equal(machine.send(illegal), false, `${id}: ${illegal} is illegal from ${before}`);
    assert.equal(machine.state, before, `${id}: illegal ${illegal} is a no-op`);
  }

  for (const [event, expected] of paths[id]) {
    assert.equal(machine.can(event), true, `${id}: ${event} should be legal from ${machine.state}`);
    assert.equal(machine.send(event), true, `${id}: ${event} should transition`);
    assert.equal(machine.state, expected, `${id}: after ${event}`);
    assert.equal(attributes[`data-state-${attributeId(id)}`], expected, `${id}: mirrored state`);
  }

  // Hydration is a set(), not an invented transition.
  const stateList = Object.keys(definition.states);
  const restored = stateList.find((state) => state !== machine.state) || definition.initial;
  assert.equal(machine.set(restored, "test"), true, `${id}: set accepts a known state`);
  assert.equal(machine.state, restored, `${id}: set hydrates`);
  assert.equal(machine.set("__not_a_state__", "test"), false, `${id}: set rejects unknown state`);
}

const state = snapshot();
assert.deepEqual(Object.keys(state).sort(), [...ids].sort());
for (const id of ids) assert.equal(state[id], machines[id].state, `snapshot reflects ${id}`);
assert.equal(JSON.stringify(JSON.parse(JSON.stringify(state))), JSON.stringify(state), "snapshot is serialisable");
assert.ok(warnings.length > 0, "illegal transitions warn in development");
console.log("STATE MACHINE TESTS PASSED");
