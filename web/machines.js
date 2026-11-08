/*
 * Explicit UI state machines for the author workbench.
 *
 * The app historically inferred state from several booleans and nullable ids
 * (jobId, pendingApproval, dirty, fileMode, fileBusy, ...). That makes illegal
 * combinations representable. This module is the small, dependency-free
 * foundation for an incremental migration: each machine names its states and
 * legal events, mirrors its current state onto the document for accessibility
 * and agent tooling, and exposes a serialisable snapshot for CDP/e2e checks.
 *
 * It is deliberately additive. Existing state fields remain the source of truth
 * until each screen is migrated, so no behaviour changes while the transition
 * tables are adopted.
 */
(function () {
  "use strict";

  const definitions = {
    connection: {
      initial: "unknown",
      states: {
        unknown: { on: { ONLINE: "online", OFFLINE: "offline" } },
        online: { on: { OFFLINE: "offline" } },
        offline: { on: { ONLINE: "online" } },
      },
    },
    session: {
      initial: "no-workspace",
      states: {
        "no-workspace": { on: { LOAD: "loading" } },
        loading: { on: { READY: "ready", ERROR: "error" } },
        ready: { on: { LOAD: "loading", RESET: "no-workspace" } },
        error: { on: { LOAD: "loading", RESET: "no-workspace" } },
      },
    },
    turn: {
      initial: "idle",
      states: {
        idle: { on: { START: "streaming" } },
        streaming: { on: { WAIT: "waiting", DONE: "idle", FAIL: "failed", CANCEL: "cancelling" } },
        waiting: { on: { RESUME: "streaming", DONE: "idle", FAIL: "failed", CANCEL: "cancelling" } },
        cancelling: { on: { DONE: "idle", FAIL: "failed" } },
        failed: { on: { START: "streaming", RESET: "idle" } },
      },
    },
    approval: {
      initial: "none",
      states: {
        none: { on: { ASK: "pending" } },
        pending: { on: { RESOLVE: "resolved", CLEAR: "none" } },
        resolved: { on: { CLEAR: "none", ASK: "pending" } },
      },
    },
    editor: {
      initial: "empty",
      states: {
        empty: { on: { OPEN: "view" } },
        view: { on: { EDIT: "editing", OPEN: "view", BINARY: "binary", CLOSE: "empty" } },
        editing: { on: { SAVE: "saving", CANCEL: "view", OPEN: "view", CLOSE: "empty" } },
        saving: { on: { SAVED: "view", FAIL: "editing", CLOSE: "empty" } },
        binary: { on: { OPEN: "view", CLOSE: "empty" } },
      },
    },
    run: {
      initial: "hidden",
      states: {
        hidden: { on: { READY: "ready" } },
        ready: { on: { RUN: "running", HIDE: "hidden" } },
        running: { on: { PASS: "passed", FAIL: "failed", CANCEL: "ready" } },
        passed: { on: { RUN: "running", RESET: "ready", HIDE: "hidden" } },
        failed: { on: { RUN: "running", RESET: "ready", HIDE: "hidden" } },
      },
    },
    modal: {
      initial: "closed",
      states: {
        closed: { on: { OPEN: "open" } },
        open: { on: { CLOSE: "closed" } },
      },
    },
  };

  const registry = {};

  function createMachine(id, definition) {
    let state = definition.initial;
    const listeners = new Set();

    function publish(previous, event) {
      if (typeof document !== "undefined" && document.body) {
        document.body.setAttribute("data-state-" + id, state);
      }
      const record = { state, previous, event, at: Date.now() };
      if (typeof window !== "undefined") {
        window.__AUTHOR_AGENT__ = window.__AUTHOR_AGENT__ || { machines: {} };
        window.__AUTHOR_AGENT__.machines[id] = record;
      }
      for (const listener of listeners) {
        try { listener({ id, ...record }); } catch { /* observers must not break the UI */ }
      }
    }

    const machine = {
      id,
      definition,
      get state() { return state; },
      can(event) {
        return Boolean(definition.states[state] && definition.states[state].on && definition.states[state].on[event]);
      },
      send(event, detail) {
        const transitions = (definition.states[state] || {}).on || {};
        const next = transitions[event];
        if (!next) {
          if (typeof console !== "undefined" && console.warn) {
            console.warn(`[fsm] ${id}: no transition for ${event} from ${state}`, detail || "");
          }
          return false;
        }
        const previous = state;
        state = next;
        publish(previous, event);
        return true;
      },
      set(next, reason) {
        if (!definition.states[next]) {
          if (typeof console !== "undefined" && console.warn) {
            console.warn(`[fsm] ${id}: unknown state ${next}`, reason || "");
          }
          return false;
        }
        if (next === state) return true;
        const previous = state;
        state = next;
        publish(previous, "RESTORE");
        return true;
      },
      subscribe(listener) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
      snapshot() {
        return { id, state };
      },
    };
    publish(state, null);
    return machine;
  }

  for (const [id, definition] of Object.entries(definitions)) {
    registry[id] = createMachine(id, definition);
  }

  if (typeof window !== "undefined") {
    window.AuthorMachines = {
      definitions,
      machines: registry,
      snapshot() {
        return Object.fromEntries(Object.entries(registry).map(([id, machine]) => [id, machine.state]));
      },
    };
  }
})();
