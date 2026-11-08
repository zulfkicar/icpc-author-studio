import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../web/machines.js", import.meta.url), "utf8");
const context = {
  window: {},
  document: { body: { setAttribute() {} } },
  console: { warn() {} },
  Date,
};
vm.createContext(context);
vm.runInContext(source, context);
const { machines, snapshot } = context.window.AuthorMachines;

assert.equal(machines.turn.state, "idle");
assert.equal(machines.turn.send("WAIT"), false, "WAIT is not legal from idle");
assert.equal(machines.turn.state, "idle");
assert.equal(machines.turn.send("START"), true);
assert.equal(machines.turn.state, "streaming");
assert.equal(machines.turn.send("WAIT"), true);
assert.equal(machines.turn.state, "waiting");
assert.equal(machines.turn.send("DONE"), true);
assert.equal(machines.turn.state, "idle");

assert.equal(machines.editor.send("SAVE"), false, "cannot save an empty editor");
assert.equal(machines.editor.send("OPEN"), true);
assert.equal(machines.editor.state, "view");
assert.equal(machines.editor.send("EDIT"), true);
assert.equal(machines.editor.send("SAVE"), true);
assert.equal(machines.editor.state, "saving");
assert.equal(machines.editor.send("SAVED"), true);
assert.equal(machines.editor.state, "view");

assert.equal(machines.modal.send("CLOSE"), false);
assert.equal(machines.modal.send("OPEN"), true);
assert.equal(machines.modal.send("CLOSE"), true);

const state = snapshot();
assert.deepEqual(Object.keys(state).sort(), [
  "approval", "connection", "editor", "modal", "run", "session", "turn",
]);
assert.equal(state.turn, "idle");
assert.equal(state.editor, "view");

console.log("STATE MACHINE TESTS PASSED");
