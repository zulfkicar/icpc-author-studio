(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const dialog = $("studio-search-dialog");
  const input = $("studio-search-input");
  const list = $("studio-search-results");
  const labels = { commands: "Commands", problems: "Open problem", files: "Open file" };
  let source, results = [], selected = 0, invoker;

  function highlight(scroll) {
    for (const [index, option] of [...list.children].entries()) {
      option.setAttribute("aria-selected", String(index === selected));
    }
    const active = list.children[selected];
    if (active) {
      input.setAttribute("aria-activedescendant", active.id);
      if (scroll) active.scrollIntoView({ block: "nearest" });
    } else input.removeAttribute("aria-activedescendant");
  }

  function render() {
    const words = input.value.normalize("NFKC").toLocaleLowerCase().trim().split(/\s+/);
    const matches = source().filter(row => {
      const body = [row.title, row.detail, row.keywords].filter(Boolean).join(" ").normalize("NFKC").toLocaleLowerCase();
      return words.every(word => body.includes(word));
    });
    results = matches.slice(0, 200);
    selected = 0;
    list.replaceChildren();
    for (const [index, row] of results.entries()) {
      const option = document.createElement("div");
      option.id = "studio-search-hit-" + index;
      option.setAttribute("role", "option");
      const title = document.createElement("span");
      title.textContent = row.title;
      const detail = document.createElement("small");
      detail.textContent = row.detail || "";
      option.append(title, detail);
      if (row.shortcut) {
        const key = document.createElement("kbd");
        key.textContent = row.shortcut;
        option.append(key);
      }
      option.addEventListener("pointerdown", event => event.preventDefault());
      option.addEventListener("click", () => choose(row));
      list.append(option);
    }
    $("studio-search-count").textContent = matches.length > results.length ? "Showing 200 matches. Type to narrow the results."
      : matches.length ? matches.length + (matches.length === 1 ? " match" : " matches") : "No matches.";
    highlight(false);
  }

  function choose(row) {
    if (!row) return;
    dialog.close();
    row.run();
  }

  function open(mode, rows) {
    if (!dialog.open) invoker = document.activeElement;
    source = rows;
    $("studio-search-title").textContent = labels[mode];
    input.setAttribute("aria-label", mode === "commands" ? "Search commands" : mode === "files" ? "Search files" : "Search problems");
    input.value = "";
    if (!dialog.open) dialog.showModal();
    input.setAttribute("aria-expanded", "true");
    render();
    input.focus();
  }
  input.addEventListener("input", render);
  input.addEventListener("keydown", event => {
    if (event.isComposing || event.keyCode === 229) return;
    if (event.key === "Enter") {
      event.preventDefault();
      choose(results[selected]);
    } else if (["ArrowDown", "ArrowUp"].includes(event.key) && results.length) {
      event.preventDefault();
      selected = (selected + (event.key === "ArrowDown" ? 1 : -1) + results.length) % results.length;
      highlight(true);
    }
  });
  dialog.addEventListener("keydown", event => {
    if (event.key === "Escape" && !event.isComposing && event.keyCode !== 229) {
      event.preventDefault();
      dialog.close();
    }
  });
  dialog.addEventListener("close", () => {
    // A result can open another modal before the native close event is delivered.
    if (dialog.open) return;
    input.setAttribute("aria-expanded", "false");
    if (document.activeElement === document.body && invoker?.isConnected && invoker.getClientRects().length) invoker.focus();
  });

  function target() {
    const fields = new URLSearchParams(location.hash.slice(1));
    const problem = fields.get("problem") || "", file = fields.get("file") || "";
    const artifact = fields.get("artifact") || "";
    return { problem: /^run-[0-9a-f]{12}$/.test(problem) ? problem : "",
      file: /^[0-9a-f]{24}$/.test(file) ? file : "",
      artifact: /^[a-zA-Z0-9-]{1,100}$/.test(artifact) ? artifact : "" };
  }

  function address({ problem, file, artifact }) {
    const fields = new URLSearchParams();
    if (problem) fields.set("problem", problem);
    if (file) fields.set("file", file);
    if (artifact) fields.set("artifact", artifact);
    return location.pathname + location.search + (fields.size ? "#" + fields : "");
  }

  function go(destination) {
    const url = address(destination);
    if (url !== location.pathname + location.search + location.hash) history.pushState(null, "", url);
  }

  async function fileToken(slug, path) {
    if (!crypto.subtle) throw new Error("File links require a secure browser context such as localhost.");
    const bytes = new TextEncoder().encode(JSON.stringify([slug, path]));
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return [...new Uint8Array(digest).slice(0, 12)].map(b => b.toString(16).padStart(2, "0")).join("");
  }

  function category(path) {
    if (/^data\/sample\//i.test(path)) return "Sample cases";
    if (/^data\/secret\//i.test(path)) return "Secret cases";
    if (/^data\//i.test(path)) return "Other case files";
    if (/^(problem_statement\/|statement\/|problem\.pdf$)/i.test(path)) return "Statement";
    if (/^(editorial\/|proofs?\/)/i.test(path)) return "Proof and editorial";
    if (/^submissions\//i.test(path)) return "Solutions";
    if (/^(input(_format)?_validators?|output_validators?|validators?)\//i.test(path)) return "Validators";
    return "Package files";
  }

  window.StudioNavigation = { open, target, address, go, fileToken, category };
})();
