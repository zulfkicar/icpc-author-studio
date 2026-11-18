import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const source = readFileSync(new URL("../web/studio-local.js", import.meta.url), "utf8");
function storage() {
  const data = new Map();
  return {
    get length() { return data.size; },
    key: index => [...data.keys()][index],
    getItem: key => data.get(key) ?? null,
    setItem: (key, value) => data.set(key, value),
    removeItem: key => data.delete(key),
  };
}

function tab(localStorage, sessionStorage, id) {
  const warning = { hidden: true };
  const context = { window: {}, document: { getElementById: () => warning }, localStorage, sessionStorage,
    crypto: { randomUUID: () => id } };
  runInNewContext(source, context);
  return { local: context.window.StudioLocal, warning };
}

const shared = storage();
const session = storage();
const first = tab(shared, session, "first").local;
first.write("draft:canal:file:first", { text: "a\n\n ", hash: "base-one" });
tab(shared, storage(), "second").local.write("draft:canal:file:second", { text: "b", hash: "base-one" });
const reopened = tab(shared, session, "third").local;
assert.equal(reopened.tab, "first");
assert.equal(reopened.read("draft:canal:file:first").text, "a\n\n ");
assert.equal(reopened.entries("draft:canal:").length, 2);
assert.equal(reopened.entries("draft:other:").length, 0);

Object.defineProperty(shared, "setItem", { value() { throw new Error("quota exceeded"); } });
const blocked = tab(shared, storage(), "blocked");
assert.equal(blocked.local.write("draft:canal:file:blocked", { text: "in-memory draft" }), false);
assert.equal(blocked.local.read("draft:canal:file:blocked").text, "in-memory draft");
assert.equal(blocked.local.entries("draft:canal:").length, 3);
assert.equal(blocked.warning.hidden, false);
assert.equal(blocked.local.unavailable(), true);
console.log("Studio recovery storage tests passed.");
