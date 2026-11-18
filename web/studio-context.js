(() => {
  "use strict";
  const byId = id => document.getElementById(id);
  const popup = byId("studio-context");
  const trigger = byId("studio-context-trigger");
  const role = byId("studio-context-role");
  const map = byId("studio-context-map");
  const legend = byId("studio-context-categories");
  const summary = byId("studio-context-summary");
  const detail = byId("studio-context-detail");
  const number = new Intl.NumberFormat();
  let receipts = [], fingerprint = "", activeRole = "", selected = "", runId = null;

  function selectCategory(id) {
    selected = selected === id ? "" : id;
    for (const item of legend.children) item.setAttribute("aria-pressed", String(item.dataset.category === selected));
    for (const item of map.children) item.classList.toggle("context-dim", Boolean(selected) && item.dataset.category !== selected);
    const entry = [...legend.children].find(item => item.dataset.category === selected);
    detail.textContent = entry ? entry.dataset.detail : "";
  }

  function paint() {
    const receipt = receipts.find(item => item.role === activeRole) || receipts[0];
    const focusId = popup.contains(document.activeElement) ? document.activeElement?.dataset.category : null;
    selected = "";
    map.replaceChildren();
    legend.replaceChildren();
    detail.textContent = "";
    const percent = receipt?.capacity ? 100 * receipt.tokens / receipt.capacity : null;
    trigger.querySelector(".context-track > span").style.width = percent === null ? "0" : Math.min(100, percent) + "%";
    trigger.title = !receipt ? "No context receipt yet" : percent === null ? "Context capacity unknown" :
      `${receipt.source === "estimated" ? "Estimated " : ""}${number.format(Math.round(percent))}% of context capacity`;
    if (!receipt) {
      summary.textContent = "No context receipt has been recorded for this problem. A receipt appears after a model request.";
      return;
    }
    const source = receipt.source === "reported" ? "Provider-reported" : "Estimated";
    const cap = receipt.capacity ? ` of ${number.format(receipt.capacity)} tokens. ${receipt.capacitySource || "Configured capacity"}.` :
      " input tokens. Model capacity is unknown.";
    summary.textContent = `${receipt.role} · ${receipt.model}${receipt.demo ? " · scripted" : ""}\n` +
      `${source}: ${number.format(receipt.tokens)}${cap}\n` +
      new Date(receipt.requestedAt).toLocaleString();
    const total = receipt.categories.reduce((sum, item) => sum + item.tokens, 0);
    if (receipt.unallocated !== null) detail.textContent = "The provider reports a total. Category sizes are separate estimates.";
    let shown = 0;
    for (const [i, category] of receipt.categories.entries()) {
      const item = document.createElement("button");
      item.type = "button";
      item.dataset.category = category.id;
      item.dataset.detail = `${category.label} · approximately ${number.format(category.tokens)} tokens, estimated from serialized text.`;
      item.style.setProperty("--category", `var(--context-${category.id})`);
      item.setAttribute("aria-pressed", "false");
      item.textContent = `${category.label} · ~${number.format(category.tokens)}`;
      item.onclick = () => selectCategory(category.id);
      legend.append(item);
      shown += category.tokens;
      const until = i === receipt.categories.length - 1 ? 40 : Math.round(40 * shown / total);
      while (map.childElementCount < until) {
        const cell = document.createElement("span");
        cell.dataset.category = category.id;
        cell.style.background = `var(--context-${category.id})`;
        map.append(cell);
      }
    }
    if (receipt.unallocated !== null) {
      const note = document.createElement("p");
      note.textContent = `${number.format(receipt.unallocated)} reported tokens have no provider category attribution.`;
      legend.after(note);
      note.className = "context-unallocated";
    }
    if (focusId) [...legend.children].find(item => item.dataset.category === focusId)?.focus({ preventScroll: true });
  }

  function redraw() {
    popup.querySelector(".context-unallocated")?.remove();
    paint();
  }
  role.onchange = () => { activeRole = role.value; redraw(); };
  window.addEventListener("studio-conversation", event => {
    const next = event.detail.view?.requestContext || [];
    const key = JSON.stringify([event.detail.runId, next]);
    if (key === fingerprint) return;
    if (runId !== event.detail.runId) activeRole = "";
    runId = event.detail.runId;
    fingerprint = key;
    receipts = next;
    activeRole = receipts.some(item => item.role === activeRole) ? activeRole :
      (receipts.find(item => item.role === "Authoring") || receipts[0])?.role || "";
    role.replaceChildren(...receipts.map(item => new Option(item.role, item.role)));
    role.value = activeRole;
    role.hidden = receipts.length < 2;
    popup.querySelector("label").hidden = role.hidden;
    redraw();
  });
})();
