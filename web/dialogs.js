/*
 * One dialog controller for the workbench.
 *
 * Native <dialog> provides the focus trap and Escape handling, but the app had
 * four dialogs each wiring cancel/backdrop/focus separately. That is how cancel
 * drift happens. This controller owns the lifecycle for every modal:
 *
 *   - one open path that records the invoker and restores focus on close;
 *   - one cancel path for the Cancel button, Escape and backdrop click;
 *   - one optional async beforeClose guard (dirty forms);
 *   - one close event that dispatches the dialog's result.
 *
 * It intentionally stays a classic script (no build step) and does not create
 * dialog content. Feature code passes an onOpen callback to populate fields so
 * the complex settings/new-problem forms keep their existing handlers.
 */
(function () {
  "use strict";

  const entries = new Map();
  const FOCUSABLE = [
    "button:not([disabled])",
    "a[href]",
    "input:not([disabled]):not([type='hidden'])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "[tabindex]:not([tabindex='-1'])",
  ].join(",");

  function isVisible(element) {
    return Boolean(element && element.isConnected && element.getClientRects().length);
  }

  function focusables(root) {
    return [...root.querySelectorAll(FOCUSABLE)].filter(isVisible);
  }

  function register(id, options = {}) {
    const dialog = document.getElementById(id);
    if (!dialog) throw new Error(`dialog controller: #${id} is missing`);
    if (entries.has(id)) return entries.get(id);

    const entry = { id, dialog, options, invoker: null, closing: false };
    entries.set(id, entry);

    const cancel = options.cancelId
      ? document.getElementById(options.cancelId)
      : dialog.querySelector("[data-dialog-cancel]");
    if (cancel) {
      cancel.addEventListener("click", () => { requestClose(id, "cancel"); });
    }

    // A click on the dialog element itself (not its content) is the backdrop.
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) requestClose(id, "backdrop");
    });

    // Escape fires cancel; prevent the default single-step close so a dirty
    // form can veto it through beforeClose.
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      requestClose(id, "escape");
    });

    dialog.addEventListener("close", () => {
      const value = dialog.returnValue;
      try {
        if (entry.options.onClose) entry.options.onClose(value);
      } finally {
        returnFocus(entry);
      }
    });

    return entry;
  }

  function open(id, options = {}) {
    const entry = entries.get(id);
    if (!entry) throw new Error(`dialog controller: #${id} is not registered`);
    if (entry.dialog.open) return false;

    entry.invoker = options.invoker
      || (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    entry.dialog.returnValue = "";
    if (entry.options.onOpen) entry.options.onOpen(options);
    entry.dialog.showModal();

    const selector = options.focus || entry.options.focus;
    const target = (selector && entry.dialog.querySelector(selector))
      || entry.dialog.querySelector("[autofocus]")
      || entry.dialog.querySelector("input:not([type='hidden']):not([disabled])")
      || entry.dialog.querySelector("textarea:not([disabled])")
      || focusables(entry.dialog).pop()
      || entry.dialog;
    if (target && target.focus) target.focus();
    return true;
  }

  async function requestClose(id, reason = "cancel") {
    const entry = entries.get(id);
    if (!entry || !entry.dialog.open || entry.closing) return false;
    entry.closing = true;
    try {
      const guard = entry.options.beforeClose;
      if (guard && reason !== "submit") {
        const outcome = guard(reason);
        // Keep the synchronous path synchronous: cancel without a dirty guard
        // must close before the click handler returns.
        if (outcome && typeof outcome.then === "function") {
          const allowed = await outcome;
          if (!allowed) return false;
        } else if (!outcome) {
          return false;
        }
      }
      entry.dialog.close(reason === "submit" ? "confirm" : "cancel");
      return true;
    } finally {
      entry.closing = false;
    }
  }

  // Close with a result, bypassing the cancel guard. Used by submit handlers
  // and by code that already obtained explicit confirmation.
  function submit(id, value = "confirm") {
    const entry = entries.get(id);
    if (!entry || !entry.dialog.open) return false;
    entry.dialog.close(value);
    return true;
  }

  function returnFocus(entry) {
    const fallback = entry.options.fallbackFocus
      ? document.querySelector(entry.options.fallbackFocus)
      : null;
    const target = [entry.invoker, fallback, document.querySelector(".activity-rail button")]
      .find(isVisible);
    entry.invoker = null;
    if (target && target.focus) target.focus({ preventScroll: true });
  }

  function isOpen(id) {
    const entry = entries.get(id);
    return Boolean(entry && entry.dialog.open);
  }

  function topOpen() {
    return [...entries.values()].filter((entry) => entry.dialog.open).pop() || null;
  }

  // Drawers reuse the focus-trap convention without being <dialog> elements.
  function trapTab(event) {
    const active = topOpen();
    if (!active) return false;
    const items = focusables(active.dialog);
    if (!items.length) return false;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
      return true;
    }
    if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
      return true;
    }
    return false;
  }

  window.AuthorDialogs = {
    register,
    open,
    requestClose,
    submit,
    isOpen,
    topOpen,
    trapTab,
    entries,
  };
})();
