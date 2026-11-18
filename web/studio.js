(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const scene = document.querySelector(".studio-scene");
  const main = document.documentElement;
  const composer = $("collab-composer");
  const fallback = $("studio-fallback");
  const local = window.StudioLocal;
  const navigation = window.StudioNavigation;
  const models = new Map();
  const completedRuns = new Map();
  const state = { runId: null, linkState: "loading", title: null, slug: "", files: [], artifacts: [], selected: "", mode: "edit",
    layout: "chat", width: 52, output: 228, font: 17, info: null, view: null, job: null };
  const buttons = [...document.querySelectorAll("[data-operation]")];
  let editor, monacoPromise, currentOutput, alertTimer, pendingCopy, pendingCopyScope, requests = 0;
  let openRequest = 0, outputOwner = null, outputEpoch = 0, latestJob = 0;
  let restoringPlace = false, placeTimer, packageIntent, previewSequence = 0;
  let closedTabs = [], runs = [], outputInvoker, layoutVersion = 0;
  const narrow = matchMedia("(max-width: 850px)");
  const systemDark = matchMedia("(prefers-color-scheme: dark)");

  function node(tag, label, cls) {
    const element = document.createElement(tag);
    if (label !== undefined) element.textContent = String(label);
    if (cls) element.className = cls;
    return element;
  }
  function button(text, action, cls) {
    const element = node("button", text, cls);
    element.type = "button";
    element.onclick = action;
    return element;
  }
  function coerce(value, low, high, initial) {
    return Number.isFinite(Number(value)) && value !== null ? Math.min(high, Math.max(low, Number(value))) : initial;
  }
  async function api(path, payload) {
    const response = await fetch(path, payload === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.error || data.reason || "Request failed");
      error.status = response.status;
      throw error;
    }
    return data;
  }
  function showNotice(message, retry) {
    const box = $("studio-alert");
    box.replaceChildren(node("span", message));
    if (retry) box.append(button("Retry", task(retry)));
    box.hidden = false;
    clearTimeout(alertTimer);
    if (!retry) alertTimer = setTimeout(() => { box.hidden = true; }, 6500);
  }
  function task(fn) {
    return (...args) => Promise.resolve(fn(...args)).catch(error => showNotice(error.message));
  }
  const packageApi = (suffix = "", slug = state.slug) => "/api/workspaces/" + encodeURIComponent(slug) + suffix;
  const runApi = (suffix = "", runId = state.runId) => "/api/engine/runs/" + encodeURIComponent(runId) + suffix;
  const active = () => models.get(state.selected);
  const dirty = record => Boolean(record && !record.readonly && (record.hash === null || record.text !== record.saved));
  const extension = path => path.split(".").pop().toLowerCase();
  const isMarkdown = record => record && ["md", "markdown"].includes(extension(record.path));
  const runnable = path => /\.(cpp|cc|cxx|c|py|java)$/i.test(path);
  const currentProof = () => [...state.artifacts].reverse().find(item =>
    item.current && ["proof", "editorial"].includes(item.kind));
  const fileKey = path => "file:" + state.slug + ":" + path;
  const artifactKey = id => "artifact:" + state.runId + ":" + id;
  const related = record => record.slug === state.slug || Boolean(record.runId && record.runId === state.runId);
  const placeKey = () => "place:" + (state.runId || "manual") + ":";
  const fileDraftPrefix = (slug, path = "") => "draft:" + encodeURIComponent(slug) + ":" + path;
  const fileDraftKey = record => fileDraftPrefix(record.slug, encodeURIComponent(record.path) + ":") + local.tab;

  function rememberDraft(record) {
    if (!record || record.readonly) return;
    local.write(fileDraftKey(record), dirty(record) ? {
      slug: record.slug, path: record.path, text: record.text, saved: record.saved, hash: record.hash,
      generation: record.generation || 0, origin: record.origin || null, time: Date.now(),
    } : null);
  }

  function savedDraft(slug, path) {
    const key = fileDraftKey({ slug, path });
    const own = local.read(key);
    return own || local.entries(fileDraftPrefix(slug, encodeURIComponent(path) + ":"))
      .map(([, value]) => value).sort((a, b) => b.time - a.time)[0];
  }

  function captureEditor(record = active()) {
    if (!record) return;
    if (editor && editor.getModel() === record.model) record.viewState = editor.saveViewState();
    else if (!editor) record.fallbackState = {
      start: fallback.selectionStart, end: fallback.selectionEnd, top: fallback.scrollTop, left: fallback.scrollLeft,
    };
  }

  function rememberPlace() {
    if (restoringPlace || state.runId === null || state.linkState !== "ready") return;
    captureEditor();
    const tabs = [...models].filter(([, item]) => item.open && related(item) && !item.temporary).map(([key, item]) => ({
      key, path: item.path, id: item.artifactId, viewState: item.viewState, fallbackState: item.fallbackState,
      pinned: item.pinned !== false,
    }));
    const saved = { slug: state.slug, layout: state.layout, mode: state.mode, selected: state.selected,
      tabs, closedTabs, treeTop: $("studio-tree").scrollTop,
      output: !$("studio-output").hidden && outputOwner === state.slug ? currentOutput : null };
    local.write(placeKey() + local.tab, saved);
    local.write(placeKey() + "latest", saved);
  }

  function schedulePlace() {
    clearTimeout(placeTimer);
    if (!restoringPlace) placeTimer = setTimeout(rememberPlace, 160);
  }

  function edited(record, text) {
    if (record.text === text) return;
    record.text = text;
    const wasPreview = record.pinned === false;
    record.pinned = true;
    record.diagnostics = null;
    record.generation = (record.generation || 0) + 1;
    rememberDraft(record);
    if (wasPreview && active() === record) paintTabs();
  }

  function setLayout(layout, preserveIntent = false) {
    if (!preserveIntent) layoutVersion++;
    state.layout = layout;
    const effective = narrow.matches && layout === "together" ? "editor" : layout;
    scene.dataset.layout = effective;
    document.querySelectorAll("[data-layout]").forEach(item => {
      if (item instanceof HTMLButtonElement) item.setAttribute("aria-pressed", String(item.dataset.layout === effective));
    });
    syncOutputLayout();
    requestAnimationFrame(() => editor?.layout());
    schedulePlace();
  }
  function keepWorkspace() {
    if (state.layout === "chat") setLayout("together");
  }
  function setSizes() {
    main.style.setProperty("--split", state.width + "%");
    main.style.setProperty("--output", state.output + "px");
    main.style.setProperty("--reading", state.font + "px");
    $("studio-split").setAttribute("aria-valuenow", state.width);
    $("studio-output-split").setAttribute("aria-valuenow", state.output);
    main.style.setProperty("--code-size", state.codeFont + "px");
    editor?.updateOptions({ fontSize: state.codeFont });
  }
  function bindResize(element, property, vertical, min, max, fromPointer) {
    const update = value => {
      state[property] = Math.round(coerce(value, min, max, state[property]));
      setSizes();
      local.rememberLegacy("studio-" + property, state[property]);
    };
    element.onpointerdown = event => {
      if (event.button !== 0) return;
      element.focus();
      element.setPointerCapture(event.pointerId);
    };
    element.onpointermove = event => {
      if (element.hasPointerCapture(event.pointerId)) update(fromPointer(event));
    };
    element.onkeydown = event => {
      const keys = vertical ? ["ArrowLeft", "ArrowRight"] : ["ArrowUp", "ArrowDown"];
      if (!keys.includes(event.key) && event.key !== "Home" && event.key !== "End") return;
      event.preventDefault();
      update(event.key === "Home" ? (vertical ? 52 : 228) : event.key === "End" ? max :
        state[property] + (event.key === keys[0] ? 1 : -1) * (vertical ? 3 : 20));
    };
    element.ondblclick = () => update(vertical ? 52 : 228);
  }
  function theme(value) {
    value = value === "system" ? (systemDark.matches ? "dark" : "light") : value;
    main.dataset.theme = value;
    if (window.monaco) monaco.editor.setTheme("studio-" + value);
  }
  function loadEditor() {
    if (monacoPromise) return monacoPromise;
    monacoPromise = new Promise((resolve, reject) => {
      const script = node("script");
      script.src = "/vendor/monaco/vs/loader.js";
      script.onerror = () => reject(new Error("Monaco could not load."));
      script.onload = () => {
        window.MonacoEnvironment = { getWorkerUrl: () => "/monaco-worker.js" };
        window.require.config({ paths: { vs: "/vendor/monaco/vs" } });
        window.require(["vs/editor/editor.main"], resolve, reject);
      };
      document.head.append(script);
    }).then(() => {
      const light = { background: "#ffffff", foreground: "#202936", highlight: "#f0f3f6" };
      const dark = { background: "#1d2229", foreground: "#edf2f7", highlight: "#262d36" };
      for (const [name, colors] of [["light", light], ["dark", dark]]) {
        monaco.editor.defineTheme("studio-" + name, {
          base: name === "dark" ? "vs-dark" : "vs", inherit: true, rules: [],
          colors: { "editor.background": colors.background, "editor.foreground": colors.foreground,
            "editor.lineHighlightBackground": colors.highlight }
        });
      }
      editor = monaco.editor.create($("studio-monaco"), {
        model: null, automaticLayout: true, fontSize: state.codeFont, minimap: { enabled: false },
        fontFamily: "Cascadia Code, Consolas, monospace", scrollBeyondLastLine: false,
        ariaLabel: "Workspace code editor", padding: { top: 10 }, tabSize: 4
      });
      editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => $("studio-save").click());
      editor.onDidChangeCursorPosition(schedulePlace);
      editor.onDidScrollChange(schedulePlace);
      editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => openOutput("run"));
      theme(main.dataset.theme || "light");
      paintEditor();
    });
    return monacoPromise;
  }
  function ensureModel(record) {
    if (!record.model) {
      const lang = { md: "markdown", markdown: "markdown", cpp: "cpp", cc: "cpp", cxx: "cpp",
        c: "c", h: "cpp", hpp: "cpp", py: "python", json: "json", yaml: "yaml", yml: "yaml",
        java: "java", tex: "latex" }[extension(record.path)] || "plaintext";
      record.model = monaco.editor.createModel(record.text, lang);
      record.model.onDidChangeContent(() => {
        edited(record, record.model.getValue());
        monaco.editor.setModelMarkers(record.model, "studio", []);
        if (active() === record) { paintMeta(); paintMarkdown(); }
      });
    }
    return record.model;
  }
  function paintMarkdown() {
    const record = active();
    const rendered = $("studio-markdown");
    if (!isMarkdown(record) || state.mode === "edit") return;
    if (!window.marked || !window.DOMPurify) {
      rendered.textContent = record.text;
      return;
    }
    rendered.innerHTML = DOMPurify.sanitize(marked.parse(record.text, { gfm: true }), {
      USE_PROFILES: { html: true }, FORBID_TAGS: ["iframe", "form", "img", "video", "audio", "style"], FORBID_ATTR: ["style"]
    });
    for (const link of rendered.querySelectorAll("a")) { link.target = "_blank"; link.rel = "noopener noreferrer"; }
  }
  function paintMeta() {
    const record = active();
    $("studio-file-actions").hidden = !record;
    if (!record) return;
    $("studio-file-path").textContent = record.path;
    $("studio-file-state").textContent = record.readonly
      ? [record.validity || "Artifact", record.revision?.slice(0, 12)].filter(Boolean).join(" · ")
      : record.conflict ? "Saved file changed · review before saving"
        : dirty(record) ? (record.recovered ? "Draft recovered · unsaved" : "Unsaved draft")
          : record.savedAt ? "Saved at " + new Date(record.savedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "Saved";
    $("studio-save").hidden = record.readonly;
    $("studio-save").disabled = !dirty(record) || record.saving;
    $("studio-review-draft").hidden = !record.conflict;
    $("studio-copy").hidden = !record.readonly || record.binary;
    $("studio-discuss-file").disabled = Boolean(record.binary);
    for (const action of document.querySelectorAll("[data-editor-tool]")) action.disabled = record.readonly;
    for (const tab of $("studio-tabs").children) {
      const item = models.get(tab.dataset.key);
      tab.querySelector(".studio-tab-dirty").hidden = !dirty(item);
      tab.setAttribute("aria-label", tab.querySelector(".studio-tab-label").textContent + (dirty(item) ? ", unsaved draft" : ""));
    }
  }
  function paintEditor() {
    const record = active();
    const pdf = Boolean(record?.pdf);
    $("studio-file-empty").hidden = Boolean(record);
    $("studio-doc-views").hidden = !isMarkdown(record);
    $("studio-document").dataset.view = pdf ? "pdf" : isMarkdown(record) ? state.mode : "edit";
    for (const button of document.querySelectorAll("[data-doc-view]")) {
      button.setAttribute("aria-pressed", String(button.dataset.docView === state.mode));
    }
    $("studio-monaco").hidden = !record || !editor || pdf;
    fallback.hidden = !record || Boolean(editor) || pdf;
    $("studio-pdf").hidden = !pdf;
    if (pdf) paintPdf(record);
    else if ($("studio-pdf-image").hasAttribute("src")) $("studio-pdf-image").removeAttribute("src");
    if (editor) {
      editor.setModel(record && !pdf ? ensureModel(record) : null);
      editor.updateOptions({ readOnly: !record || record.readonly, wordWrap: isMarkdown(record) ? "on" : "off" });
      if (record?.viewState) editor.restoreViewState(record.viewState);
      requestAnimationFrame(() => editor.layout());
    } else if (record && !pdf) {
      fallback.value = record.text;
      fallback.readOnly = record.readonly;
      if (record.fallbackState) {
        fallback.setSelectionRange(record.fallbackState.start, record.fallbackState.end);
        fallback.scrollTop = record.fallbackState.top;
        fallback.scrollLeft = record.fallbackState.left;
      }
      loadEditor().catch(() => { /* The textarea remains usable. */ });
    }
    paintMeta();
    paintMarkdown();
  }
  function openTabs() {
    return [...models].filter(([, record]) => record.open && related(record));
  }

  function paintTabs() {
    const tabs = $("studio-tabs");
    const scroll = tabs.scrollLeft;
    tabs.replaceChildren();
    const rows = openTabs();
    const basenames = rows.map(([, item]) => item.path.split("/").at(-1));
    for (const [index, [key, record]] of rows.entries()) {
      const base = basenames[index];
      const duplicate = basenames.filter(value => value === base).length > 1;
      const parent = record.path.split("/").slice(0, -1).join("/") || "root";
      const label = base + (duplicate ? " · " + parent + (record.artifactId ? " · " + (record.revision || "conversation") : " · package") : "");
      const tab = button(undefined, () => selectFile(key, { focus: true }), "studio-tab");
      tab.dataset.key = key;
      tab.dataset.preview = String(record.pinned === false);
      tab.id = "studio-tab-" + index;
      tab.title = record.path + (record.pinned === false ? " · Preview" : "");
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", "studio-document");
      const selected = key === state.selected;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected) $("studio-document").setAttribute("aria-labelledby", tab.id);
      tab.append(node("span", label, "studio-tab-label"), node("span", "•", "studio-tab-dirty"));
      tab.ondblclick = () => pinTab(key);
      tab.onkeydown = event => {
        if (event.isComposing) return;
        if (event.key === "Delete") { event.preventDefault(); closeTab(key); return; }
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const next = event.key === "Home" ? 0 : event.key === "End" ? rows.length - 1 :
          (index + (event.key === "ArrowLeft" ? -1 : 1) + rows.length) % rows.length;
        selectFile(rows[next][0], { focus: true });
      };
      tabs.append(tab);
    }
    tabs.scrollLeft = scroll;
    const record = active();
    $("studio-pin-tab").hidden = record?.pinned !== false;
    $("studio-close-tab").hidden = !record;
    $("studio-close-tab").setAttribute("aria-label", "Close " + (record?.path || "tab"));
    $("studio-reopen-tab").hidden = !closedTabs.length;
    if (!record) $("studio-document").removeAttribute("aria-labelledby");
  }
  function pinTab(key = state.selected) {
    const record = models.get(key);
    if (!record) return;
    record.pinned = true;
    paintTabs();
    paintMeta();
    $("studio-tabs").querySelector('[aria-selected="true"]')?.focus();
    schedulePlace();
  }
  function closeTab(key = state.selected) {
    const rows = openTabs();
    const index = rows.findIndex(([id]) => id === key);
    if (index < 0) return;
    const record = rows[index][1];
    record.open = false;
    if (!record.temporary) {
      closedTabs = [...closedTabs.filter(row => row.key !== key), { key, path: record.path, id: record.artifactId }].slice(-15);
    }
    const adjacent = rows[index + 1]?.[0] || rows[index - 1]?.[0] || "";
    selectFile(state.selected === key ? adjacent : state.selected, { focus: true });
    if (dirty(record)) showNotice("Tab closed. Its unsaved draft is available in Open file.");
  }
  function selectFile(key, { focus = false, link = true } = {}) {
    const previous = active();
    captureEditor(previous);
    state.selected = key;
    if (key) active().open = true;
    keepWorkspace();
    paintTabs();
    paintEditor();
    for (const item of $("studio-tree").querySelectorAll("[data-file-key]")) {
      item.setAttribute("aria-current", String(item.dataset.fileKey === key));
    }
    if (focus) ($("studio-tabs").querySelector('[aria-selected="true"]') || openFileTrigger()).focus();
    if (key) $("studio-tabs").querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });
    if (link && state.runId) setFileAddress(active());
    schedulePlace();
  }
  function fileRows() {
    const artifacts = state.artifacts.map(artifact => ({
      key: artifactKey(artifact.id), path: artifact.path,
      group: "From conversation",
      detail: [artifact.revision, artifact.current ? "Current" : artifact.validity || "Earlier revision"].filter(Boolean).join(" · "),
      open: task(() => loadArtifact(artifact.id)),
    }));
    const saved = state.files.filter(item => item.type === "file").map(({ path }) => ({
      path, group: navigation.category(path), key: fileKey(path), open: task(() => openFile(path)),
    }));
    const drafts = state.slug
      ? [...new Set(local.entries(fileDraftPrefix(state.slug)).map(([, draft]) => draft.path))] : [];
    const savedPaths = new Set(saved.map(row => row.path));
    const openDrafts = drafts.filter(path => !savedPaths.has(path)).map(path => ({
      path, group: "Unsaved drafts", key: fileKey(path), open: task(() => openFile(path)),
    }));
    return [...artifacts, ...saved, ...openDrafts].map(row => ({
      ...row, dirty: row.group === "Unsaved drafts" || dirty(models.get(row.key)) ||
        (row.group !== "From conversation" && drafts.includes(row.path)),
    }));
  }

  function paintTree() {
    const tree = $("studio-tree");
    const top = tree.scrollTop;
    const focused = tree.contains(document.activeElement) ? document.activeElement.dataset.fileKey : null;
    const scope = "tree:" + (state.slug || state.runId || "new") + ":";
    const groups = new Map();
    for (const row of fileRows()) {
      if (!groups.has(row.group)) groups.set(row.group, []);
      groups.get(row.group).push(row);
    }
    tree.replaceChildren();
    for (const [label, rows] of groups) {
      const group = node("details", undefined, "studio-tree-group");
      group.open = local.read(scope + label, true);
      group.append(node("summary", label + " · " + rows.length));
      group.ontoggle = () => local.write(scope + label, group.open);
      for (const row of rows) {
        const short = row.path.split("/").pop();
        const item = button(short + (row.dirty ? " •" : ""), row.open);
        item.dataset.fileKey = row.key;
        item.title = row.path + (row.detail ? " · " + row.detail : "");
        item.setAttribute("aria-current", String(row.key === state.selected));
        if (row.detail || rows.filter(candidate => candidate.path.split("/").pop() === short).length > 1) {
          item.append(node("small", row.path + (row.detail ? " · " + row.detail : "")));
        }
        group.append(item);
      }
      tree.append(group);
    }
    if (!tree.childElementCount) tree.append(node("p", "Artifacts appear here as you develop the problem.", "muted"));
    tree.scrollTop = top;
    if (focused) [...tree.querySelectorAll("[data-file-key]")]
      .find(item => item.dataset.fileKey === focused)?.focus({ preventScroll: true });
  }
  async function readFileRecord(slug, path) {
    const pdf = ["problem.pdf", "problem_statement/problem.en.pdf", "statement/problem.en.pdf"].includes(path);
    if (pdf && slug === state.slug && state.files.some(item => item.type === "file" && item.path === path)) {
      return { slug, path, text: "", readonly: true, binary: true, pdf: true };
    }
    const draft = savedDraft(slug, path);
    let file;
    try { file = await api(packageApi("/file?path=" + encodeURIComponent(path), slug)); }
    catch (error) {
      if (!draft || error.status !== 404) throw error;
      file = { text: true, content: "", hash: null };
    }
    if (draft) return { ...draft, recovered: true, conflict: file.hash !== draft.hash };
    const text = file.text ? file.content : "This file uses a binary format.";
    return { slug, path, hash: file.hash, text, saved: text, readonly: !file.text, binary: !file.text, pdf };
  }

  async function openFile(path, { link = true, pinned = false } = {}) {
    const slug = state.slug;
    const key = fileKey(path);
    const request = ++openRequest;
    const plannedLayout = layoutVersion;
    try {
      if (!models.has(key)) {
        const record = await readFileRecord(slug, path);
        if (slug !== state.slug || request !== openRequest ||
            (plannedLayout !== layoutVersion && state.layout === "chat")) return;
        models.set(key, record);
      }
      openPreview(key, { link, pinned });
    } catch (error) {
      if (slug !== state.slug || request !== openRequest) return;
      showNotice("Could not open " + path + ". " + error.message, () => openFile(path));
    }
  }
  function artifactRecord(runId, artifact, previous) {
    return { ...previous, runId, path: artifact.path, text: artifact.text,
      kind: artifact.kind, readonly: true, revision: artifact.revision, validity: artifact.validity,
      artifactId: artifact.id, packageDraft: Boolean(artifact.provenance?.packageDraft) };
  }
  function openArtifact(runId, artifact, options = {}) {
    if (runId !== state.runId) return;
    ++openRequest;
    const key = artifactKey(artifact.id);
    models.set(key, artifactRecord(runId, artifact, models.get(key)));
    if (isMarkdown(models.get(key))) state.mode = "preview";
    openPreview(key, options);
  }
  async function loadArtifact(id, options = {}) {
    const runId = state.runId;
    const request = ++openRequest;
    const plannedLayout = layoutVersion;
    try {
      const artifact = await api(runApi("/artifacts/" + encodeURIComponent(id), runId));
      if (request === openRequest && runId === state.runId &&
          (plannedLayout === layoutVersion || state.layout !== "chat")) openArtifact(runId, artifact, options);
    } catch (error) {
      if (request === openRequest && runId === state.runId) showNotice("This artifact could not be opened. " + error.message,
        () => loadArtifact(id, options));
    }
  }
  function openPreview(key, { link = true, pinned = false } = {}) {
    const record = models.get(key);
    if (link && narrow.matches && !$("studio-output").hidden) closeOutput();
    captureEditor();
    if (!record.open) {
      if (!pinned && !dirty(record)) {
        for (const [id, prior] of openTabs()) {
          if (id !== key && prior.pinned === false && !dirty(prior)) prior.open = false;
        }
      }
      record.pinned = pinned || dirty(record) || record.pinned === true;
    }
    closedTabs = closedTabs.filter(row => row.key !== key);
    selectFile(key, { focus: true, link });
  }
  function reopenTab() {
    const last = closedTabs.at(-1);
    if (!last) return;
    if (models.has(last.key) && related(models.get(last.key))) openPreview(last.key, { pinned: true });
    else if (last.id) loadArtifact(last.id, { pinned: true });
    else openFile(last.path, { pinned: true });
  }

  function paintPdf(record) {
    const report = state.info?.lastReport;
    const status = $("studio-pdf-status");
    const image = $("studio-pdf-image");
    const freshness = report?.status !== "verified" || state.info?.stale
      ? "Saved PDF. Run Verify to rebuild the current statement. " : "";
    const url = new URL(packageApi("/statement-pdf?path=" + encodeURIComponent(record.path) +
      "&revision=" + encodeURIComponent(state.info?.snapshot || record.hash || ""), record.slug), location.href).href;
    $("studio-pdf-link").href = url;
    const preview = url + "&preview=first-page";
    const label = () => {
      status.textContent = freshness + (image.hidden ? "First-page preview unavailable. Open the full PDF separately." : "First page");
    };
    image.onerror = () => { if (active() === record) { image.hidden = true; label(); } };
    if (image.src !== preview) {
      image.hidden = false;
      image.src = preview;
    }
    label();
  }

  function openFileTrigger() {
    return $("studio-files");
  }

  function openProblems() {
    navigation.open("problems", () => {
      const statuses = new Map([...$("collab-run-select").options].map(item => [item.value, item.text.split(" · ")[0]]));
      const recent = [...runs].sort((a, b) => (b.updatedAt || "").localeCompare(a.updatedAt || ""));
      return recent.map(run => ({
        title: run.title || run.idea || "Untitled problem",
        keywords: run.idea,
        detail: [statuses.get(run.runId), run.updatedAt && new Date(run.updatedAt).toLocaleDateString()].filter(Boolean).join(" · "),
        run: () => window.dispatchEvent(new CustomEvent("studio-select-problem", { detail: run.runId })),
      })).concat({ title: "New problem", detail: "Start from an idea", run: () => $("collab-new").click() });
    });
  }

  function openFileSearch() {
    navigation.open("files", () => {
      const files = fileRows();
      return files.length ? files.map(row => ({
        title: row.path.split("/").at(-1),
        detail: [row.group, row.path, row.detail, row.dirty && "Unsaved draft"].filter(Boolean).join(" · "),
        run: row.open,
      })) : [{ title: "Package setup", detail: "Create or open a workspace with files", run: task(() => packageDialog()) }];
    });
  }

  async function fileAddress(record) {
    const problem = state.runId;
    if (!problem) return {};
    if (record?.artifactId) return { problem, artifact: record.artifactId };
    if (record?.slug && !record.temporary && state.files.some(file => file.path === record.path && file.type === "file")) {
      return { problem, file: await navigation.fileToken(record.slug, record.path) };
    }
    return { problem };
  }
  async function setFileAddress(record) {
    const runId = state.runId;
    const urlBefore = location.href;
    const address = await fileAddress(record).catch(() => ({ problem: runId }));
    if (state.runId === runId && active() === record && location.href === urlBefore) navigation.go(address);
  }
  async function applyAddress() {
    const target = navigation.target();
    if (!target.problem || target.problem !== state.runId || state.linkState !== "ready") return;
    const initial = location.href;
    if (target.artifact) {
      if (state.artifacts.some(item => item.id === target.artifact)) {
        if (active()?.artifactId !== target.artifact) {
          if (!$("studio-output").hidden) closeOutput();
          await loadArtifact(target.artifact, { link: false, pinned: true });
        }
        return;
      }
    } else if (target.file && state.slug) {
      const candidates = state.files.filter(item => item.type === "file");
      const slug = state.slug;
      const tokens = await Promise.all(candidates.map(item => navigation.fileToken(slug, item.path))).catch(() => []);
      if (initial !== location.href || slug !== state.slug || target.problem !== state.runId) return;
      const match = candidates[tokens.indexOf(target.file)];
      if (match) {
        if (active()?.path !== match.path || active()?.slug !== slug) {
          if (!$("studio-output").hidden) closeOutput();
          await openFile(match.path, { link: false, pinned: true });
        }
        return;
      }
    } else if (!target.file) return;
    if (initial === location.href) {
      history.replaceState(null, "", navigation.address({ problem: target.problem }));
      showNotice("That file is unavailable. The problem is still open.");
    }
  }
  async function copyFileLink() {
    const destination = await fileAddress(active());
    if (!destination.problem) { showNotice("Start a conversation to copy a problem link."); return; }
    const url = new URL(navigation.address(destination), location.href).href;
    try {
      await navigator.clipboard.writeText(url);
      showNotice(active() && !destination.file && !destination.artifact
        ? "Problem link copied. Save the file to copy a link directly to it." : "Local link copied.");
    } catch {
      navigation.go(destination);
      showNotice("The local link is in the address bar. Copy it from there.");
    }
  }
  function openStatementPdf() {
    const match = ["problem.pdf", "problem_statement/problem.en.pdf", "statement/problem.en.pdf"]
      .find(path => state.files.some(file => file.path === path && file.type === "file"));
    if (match) openFile(match);
    else {
      openOutput("verify");
      showNotice("No statement PDF yet. Verify a package with a supported statement and LaTeX.");
    }
  }
  function discussLastResult() {
    const data = recentRun();
    if (!data) {
      if (state.info?.lastReport) openOutput("verify");
      else showNotice("Run saved code or verify a package to discuss a result.");
      return;
    }
    stageDiscussion("Discuss this local run of " + data.path + " from package revision " + data.snapshot +
      ". Exit: " + (data.exitCode ?? "unavailable") + "." + (data.comparison ?
        (data.comparison.matches ? " It matched the expected output." : " It differed from the expected output.") : ""));
  }

  function openCommands() {
    navigation.open("commands", () => [
      { title: "Open problem", shortcut: "Alt+P", run: openProblems },
      { title: "Open file", shortcut: "Alt+O", run: openFileSearch },
      { title: "Rename problem", shortcut: "F2", run: () => $("studio-name-problem").click() },
      { title: "New problem", run: () => $("collab-new").click() },
      { title: "Run saved source", shortcut: "Alt+R", detail: "Choose a source and input before running", run: () => openOutput("run") },
      { title: "Build expected answers", keywords: "tests", run: () => openOutput("answers") },
      { title: "Verify package", run: () => openOutput("verify") },
      { title: "Review package changes", run: () => openOutput("review") },
      { title: "Compare solutions", run: () => openOutput("compare") },
      { title: "Setter handoff", run: () => openOutput("handoff") },
      { title: "Export ZIP", run: () => openOutput("export") },
      { title: "Open statement PDF", run: openStatementPdf },
      { title: "Discuss last result", keywords: "chat", run: discussLastResult },
      { title: "Copy local link", keywords: "file problem address", run: task(copyFileLink) },
      { title: "Package setup", run: task(() => packageDialog()) },
      { title: "Provider settings", run: () => { location.href = "/workbench#provider-settings"; } },
      { title: "Show proof", run: () => currentProof() ? $("studio-proof").click() : showNotice("Ask the agent to develop a proof or editorial first.") },
      { title: "Show activity", run: () => $("studio-ledger").click() },
      ...(closedTabs.length ? [{ title: "Reopen closed tab", shortcut: "Alt+Shift+O", run: reopenTab }] : []),
    ]);
  }
  async function loadPackage(slug = state.slug) {
    if (!slug) return;
    const info = await api(packageApi("/studio", slug));
    if (slug !== state.slug) return;
    const previous = state.files.map(file => file.path).join("\n");
    state.info = info;
    state.files = info.tree || [];
    $("studio-package-label").textContent = (state.link?.syncTitle === false ? "Package · " : "") + (info.meta.name || slug);
    $("studio-new-file").hidden = false;
    if (previous !== state.files.map(file => file.path).join("\n")) paintTree();
    if (active()?.pdf) paintPdf(active());
    return info;
  }
  async function refreshPackageTitle(slug) {
    const titlePaths = new Set(["problem.yaml", "domjudge-problem.ini", "problem_statement/problem.en.tex", "statement/problem.en.tex"]);
    const info = await loadPackage(slug);
    if (!info || slug !== state.slug) return;
    if (outputOwner === slug) markFreshness();
    await Promise.all([...models.values()].filter(record => record.slug === slug && titlePaths.has(record.path)
      && info.tree.some(file => file.path === record.path) && !dirty(record) && !record.saving).map(async record => {
      const file = await api(packageApi("/file?path=" + encodeURIComponent(record.path), slug));
      if (slug !== state.slug || dirty(record) || record.saving || record.hash === file.hash) return;
      record.hash = file.hash;
      record.saved = record.text = file.content;
      record.model?.setValue(file.content);
    }));
    if (slug === state.slug) paintEditor();
  }
  async function save(record = active()) {
    if (!dirty(record) || record.saving) return false;
    if (record.conflict) { await showSaveConflict(record); return false; }
    record.saving = true;
    paintMeta();
    const content = record.text;
    try {
      const result = await api(packageApi("/file", record.slug), { path: record.path, content, expectedHash: record.hash,
        artifactOrigin: record.origin || undefined });
      record.saved = content;
      record.hash = result.hash;
      record.savedAt = Date.now();
      record.recovered = false;
      record.conflict = false;
      record.origin = null;
      rememberDraft(record);
      await loadPackage(record.slug);
      if (outputOwner === record.slug) markFreshness();
      showNotice("Saved " + record.path);
      return true;
    } catch (error) {
      if (error.status !== 409 || active() !== record) throw error;
      if (record.origin && error.message.includes("artifact changed")) {
        showNotice(error.message);
        return false;
      }
      record.conflict = true;
      await showSaveConflict(record);
      return false;
    } finally {
      record.saving = false;
      paintMeta();
    }
  }
  function fileDraft(copy = null) {
    pendingCopy = copy;
    pendingCopyScope = { slug: state.slug, runId: state.runId };
    $("studio-file-title").textContent = copy ? "Copy artifact to package" : "New package file";
    $("studio-file-error").textContent = "";
    const origin = $("studio-file-origin");
    origin.hidden = !copy;
    if (copy) origin.textContent = `${copy.path} · conversation revision ${(copy.revision || "unknown").slice(0, 12)}. ` +
      `Destination package: ${state.info?.meta?.name || state.slug}. The copied text opens as a draft for inspection.`;
    const basename = copy?.path.split("/").pop();
    const name = copy?.kind === "test" && !basename.endsWith(".in") ? basename.replace(/\.[^.]+$/, "") + ".in" : basename;
    const folder = { solution: "submissions/accepted", test: "data/secret",
      validator: "input_validators", proof: "editorial", editorial: "editorial",
      spec: "statement" }[copy?.kind] || "";
    $("studio-new-path").value = copy?.packageDraft ? copy.path : copy ? [folder, name].filter(Boolean).join("/") : "";
    $("studio-file-dialog").showModal();
  }
  async function previewPackage() {
    const intent = packageIntent;
    const select = $("studio-package-select");
    const slug = select.value;
    const sync = $("studio-sync-title");
    const impact = $("studio-link-impact");
    const name = $("studio-package-name");
    const submit = $("studio-link-submit");
    const request = ++previewSequence;
    intent.preview = null;
    submit.disabled = Boolean(intent.runId);
    submit.textContent = slug ? (intent.runId ? "Link package" : "Open package") : "Create package";
    name.hidden = Boolean(slug);
    name.required = !slug && !state.title;
    document.querySelector('label[for="studio-package-name"]').hidden = Boolean(slug);
    $("studio-sync-title-row").hidden = !slug || !intent.runId || !state.title;
    $("studio-link-refresh").hidden = true;
    impact.hidden = false;
    if (!intent.runId) {
      impact.textContent = slug ? "Open this package for manual work." : "Create a package for manual work.";
      return;
    }
    impact.textContent = "Checking package titles…";
    try {
      const data = await api(runApi("/studio-package-preview", intent.runId), { slug: slug || null });
      if (intent !== packageIntent || request !== previewSequence || !$("studio-package-dialog").open) return;
      intent.preview = { slug, data };
      if (data.syncBlocked) sync.checked = false;
      sync.disabled = Boolean(data.syncBlocked);
      paintPackageImpact();
      submit.disabled = false;
    } catch (error) {
      if (intent !== packageIntent || request !== previewSequence) return;
      impact.textContent = error.message;
      $("studio-link-refresh").hidden = false;
    }
  }

  function paintPackageImpact() {
    const preview = packageIntent?.preview;
    if (!preview) return;
    const { slug, data } = preview;
    const title = data.basis.expectedTitle;
    const match = $("studio-sync-title").checked;
    const impact = $("studio-link-impact");
    if (!slug) {
      impact.textContent = title ? 'The new package will follow “' + title + '”.' : "This name will also name the problem.";
      return;
    }
    impact.textContent = 'Existing package: “' + data.packageTitle + '”.' + (title ? ' Problem: “' + title + '”.' : "") +
      (match ? " The package will follow the problem title. ZIP: " + data.filename + "." +
        (data.files?.length ? " Updates " + data.files.join(", ") + "." : "") +
        (data.statementSupported === false ? " Check the statement title manually." : "") +
        (data.requiresVerification ? " Verify and approve again before exporting." : "") : " Keep the existing package title.") +
      (data.syncBlocked ? " " + data.syncBlocked : "");
  }

  async function packageDialog({ copy = null, preferred = "" } = {}) {
    const dialog = $("studio-package-dialog");
    if (dialog.open) return;
    const intent = { runId: state.runId, slug: state.slug, copy, selected: state.selected };
    packageIntent = intent;
    $("studio-link-error").textContent = "";
    const select = $("studio-package-select");
    const data = await api("/api/state");
    if (packageIntent !== intent || state.runId !== intent.runId) return;
    select.replaceChildren(new Option("Create a package", ""));
    for (const item of data.workspaces || []) {
      select.append(new Option(item.name || item.meta?.name || item.slug, item.slug));
    }
    select.value = preferred || state.slug;
    if (select.selectedIndex < 0) select.value = "";
    const name = $("studio-package-name");
    name.value = state.title || $("studio-title").title;
    name.readOnly = Boolean(state.runId && state.title);
    $("studio-package-help").textContent = state.runId
      ? "Link this conversation to an existing package or create one from the problem template."
      : "Select or create a package for manual work. Start a conversation to link it.";
    $("studio-sync-title").checked = Boolean(select.value && select.value === state.slug && state.link?.syncTitle !== false);
    dialog.showModal();
    select.focus();
    await previewPackage();
  }
  function stageDiscussion(text) {
    composer.value = [composer.value, text].filter(Boolean).join("\n\n");
    composer.dispatchEvent(new Event("input", { bubbles: true }));
    setLayout("chat");
    composer.focus();
  }
  const operationNames = { run: "Run code", answers: "Build expected answers", verify: "Verify package",
    export: "Export ZIP", "measure-limits": "Measure limits", review: "Review changes",
    compare: "Compare solutions", handoff: "Setter handoff", problems: "Problems", conflict: "File changed on disk" };
  const outputBody = $("studio-output-body");
  const outputStatus = $("studio-output-status");

  function markFreshness() {
    if (currentOutput === "export" && outputOwner === state.slug && outputBody.querySelector(".studio-download") &&
        !$("studio-output").hidden && !state.job && state.info && !state.info.workflow.canExport) {
      openOutput("export", false, false);
      return;
    }
    const stateLabel = $("studio-output-freshness");
    if (stateLabel && outputOwner === state.slug) {
      const stale = stateLabel.dataset.snapshot && state.info?.snapshot !== stateLabel.dataset.snapshot;
      stateLabel.textContent = stale ? "Earlier evidence · the saved package changed" :
        "Package revision " + (stateLabel.dataset.snapshot || "").slice(0, 12);
      stateLabel.classList.toggle("warning", Boolean(stale));
      const download = outputBody.querySelector(".studio-download");
      if (download) download.hidden = Boolean(stale) || !state.info?.workflow?.canExport;
    }
  }
  function openOutput(mode, newRun = false, focus = true) {
    if ($("studio-output").hidden && focus) outputInvoker = document.activeElement;
    keepWorkspace();
    currentOutput = mode;
    outputOwner = state.slug;
    outputEpoch++;
    $("studio-output").hidden = $("studio-output-split").hidden = false;
    syncOutputLayout();
    $("studio-output-title").textContent = operationNames[mode];
    outputStatus.textContent = "";
    outputBody.replaceChildren();
    schedulePlace();
    buttons.forEach(item => item.setAttribute("aria-expanded", String(item.dataset.operation === mode)));
    if (focus) $("studio-output-title").focus();
    if (mode === "problems") { paintProblems(); return; }
    if (mode === "conflict") return;
    if (mode === "handoff") {
      const epoch = outputEpoch;
      task(async () => {
        if (state.slug) await loadPackage();
        if (epoch === outputEpoch) paintHandoff();
      })();
      return;
    }
    if (state.linkState === "loading") {
      outputStatus.textContent = "Loading the linked package…";
      return;
    }
    if (state.linkState === "error") {
      outputStatus.textContent = "Could not load the linked package.";
      outputBody.append(button("Retry package load", task(() => restorePackage(state.runId, true))));
      return;
    }
    if (!state.slug) {
      outputBody.append(node("p", "Link or create a judge package to use these tools."), button("Open package setup", task(packageDialog)));
      return;
    }
    if (state.job) {
      paintJob(state.job);
      return;
    }
    const epoch = outputEpoch;
    const load = async () => {
      const info = await loadPackage();
      if (!info || epoch !== outputEpoch) return;
      if (mode === "run") {
        const previous = recentRun();
        if (previous && !newRun) paintRunResult(previous);
        else paintRun(info);
      }
      if (mode === "verify") paintVerify(info);
      if (mode === "answers") await paintAnswers(info, epoch);
      if (mode === "export") paintExport(info);
      if (mode === "measure-limits") outputBody.append(
        node("p", "Measure time and memory from the saved reference solution and tests."),
        button("Measure saved package", task(() => launchJob(mode)), "primary")
      );
      if (mode === "review") await paintReview(info, epoch);
      if (mode === "compare") paintComparison(info);
      if (mode === "answers" || mode === "measure-limits") {
        const last = local.read("operation-result:" + info.slug + ":" + mode);
        if (last) {
          outputBody.append(node("p", last.summary), button("Open verification", () => openOutput("verify")));
          if (last.snapshot) freshness(last.snapshot);
        }
      }
    };
    load().catch(error => {
      if (epoch !== outputEpoch) return;
      outputStatus.textContent = "Could not load " + operationNames[mode].toLowerCase() + ". " + error.message;
      outputBody.append(button("Retry", () => openOutput(mode, newRun, false)));
    });
  }
  function syncOutputLayout() {
    const covered = narrow.matches && !$("studio-output").hidden;
    for (const id of ["studio-document", "studio-tabs", "studio-file-actions", "studio-doc-views"]) $(id).inert = covered;
    for (const id of ["studio-pin-tab", "studio-close-tab", "studio-reopen-tab"]) $(id).inert = covered;
  }
  function closeOutput() {
    $("studio-output").hidden = $("studio-output-split").hidden = true;
    syncOutputLayout();
    outputEpoch++;
    const invoker = buttons.find(item => item.dataset.operation === currentOutput);
    buttons.forEach(item => item.setAttribute("aria-expanded", "false"));
    schedulePlace();
    const next = [outputInvoker, invoker, $("studio-tabs").querySelector('[aria-selected="true"]'), openFileTrigger()]
      .find(item => item?.isConnected && item.getClientRects().length && !item.disabled);
    outputInvoker = null;
    next?.focus();
  }
  const runKey = () => "run-setup:" + (state.runId || "manual") + ":" + state.slug;
  const readRunSetup = () => local.read(runKey()) || {};
  const runResultKey = (runId, slug) => "run-result:" + (runId || "manual") + ":" + slug;
  function recentRun() {
    const key = runResultKey(state.runId, state.slug);
    return completedRuns.get(key) || local.read(key) || local.read("run-result:" + state.slug);
  }
  function prepareRun(setup) {
    local.write(runKey(), { ...setup, path: setup.path || readRunSetup().path });
    openOutput("run", true);
  }
  async function fetchCase(path, slug) {
    const file = await api(packageApi("/file?path=" + encodeURIComponent(path), slug));
    if (!file.text || file.size > 256 * 1024 || new TextEncoder().encode(file.content).length > 256 * 1024) {
      throw new Error("This input is too large or is not a readable text case.");
    }
    return file.content;
  }
  async function openDiagnostic(data, location) {
    const slug = state.slug;
    const file = await api(packageApi("/file?path=" + encodeURIComponent(location.path), slug));
    if (slug !== state.slug) return;
    if (file.hash !== data.sourceHash || dirty(models.get(fileKey(location.path)))) {
      showNotice("The source has changed since this diagnostic. Open the file or rerun for fresh line locations.");
      return;
    }
    await openFile(location.path, { pinned: true });
    const record = active();
    if (slug !== state.slug || record?.path !== location.path || record.hash !== data.sourceHash || dirty(record)) return;
    state.mode = "edit";
    paintEditor();
    if (editor && editor.getModel() === record.model) {
      editor.setPosition({ lineNumber: location.line, column: location.column });
      editor.revealLineInCenter(location.line);
      editor.focus();
    } else {
      const prefix = record.text.split("\n").slice(0, location.line - 1).join("\n");
      const offset = (location.line > 1 ? prefix.length + 1 : 0) + location.column - 1;
      fallback.focus();
      fallback.setSelectionRange(offset, offset);
    }
  }
  function paintRun(info) {
    const files = info.tree.filter(file => file.type === "file" && runnable(file.path));
    const setup = readRunSetup();
    const select = node("select");
    select.setAttribute("aria-label", "Saved source");
    for (const file of files) select.append(new Option(file.path, file.path));
    const preferred = setup.path || active()?.path;
    if (files.some(file => file.path === preferred)) select.value = preferred;
    else if (files.some(file => file.path.startsWith("submissions/accepted/"))) {
      select.value = files.find(file => file.path.startsWith("submissions/accepted/")).path;
    }
    const inputs = info.tree.filter(file => file.type === "file" && /^data\/.+\.in$/i.test(file.path));
    const cases = node("select");
    cases.setAttribute("aria-label", "Run case");
    cases.append(new Option("Custom input", ""));
    for (const input of inputs) cases.append(new Option(input.path, input.path));
    cases.value = inputs.some(item => item.path === setup.casePath) ? setup.casePath : "";
    const stdin = node("textarea");
    stdin.setAttribute("aria-label", "Standard input");
    stdin.value = setup.stdin || "";
    stdin.maxLength = 256 * 1024;
    let expectation = setup.expected;
    let receipt = setup.receipt;
    const note = node("p", "", "muted");
    const persist = () => local.write(runKey(), { path: select.value, casePath: cases.value || null,
      stdin: cases.value ? "" : stdin.value, expected: cases.value ? undefined : expectation,
      receipt: cases.value ? undefined : receipt });
    const runRequest = async saveFirst => {
      const slug = info.slug;
      const record = models.get(fileKey(select.value));
      const path = select.value;
      const casePath = cases.value || null;
      const input = stdin.value;
      const expected = expectation;
      if (saveFirst && (!record || !await save(record) || dirty(record))) return;
      if (slug !== state.slug || info.slug !== state.info?.slug) return;
      persist();
      await launchJob("run", { path, casePath, stdin: input, expected, asJob: true,
        expectedHash: saveFirst ? record.hash : undefined });
    };
    const run = button("Run saved source", task(() => runRequest(false)), "primary");
    const saveRun = button("Save & Run", task(() => runRequest(true)));
    let load = 0;
    const update = (loading = false, failed = false) => {
      run.disabled = loading || failed || !files.length;
      saveRun.hidden = !dirty(models.get(fileKey(select.value)));
      saveRun.disabled = run.disabled;
      note.textContent = expectation === undefined || cases.value ? "" : "Attached expected output: " + expectation +
        (receipt ? ` · ${receipt.historical ? "earlier " : ""}receipt ${receipt.id}` : "");
    };
    const loadInput = task(async () => {
      const request = ++load;
      stdin.readOnly = Boolean(cases.value);
      update(true);
      try {
        stdin.value = cases.value ? await fetchCase(cases.value, info.slug).then(body => request === load ? body : stdin.value) : "";
        if (request === load && stdin.isConnected) { persist(); update(); }
      } catch (error) {
        if (request === load && stdin.isConnected) { stdin.value = ""; update(false, true); throw error; }
      }
    });
    select.onchange = () => { persist(); update(); };
    stdin.oninput = () => { expectation = receipt = undefined; persist(); update(); };
    cases.onchange = () => { expectation = receipt = undefined; loadInput(); };
    run.disabled = !files.length;
    outputBody.append(node("p", files.length
      ? "Local runner · executes the saved source on the host. Only run code you trust."
      : "Save a C, C++, Python or Java file to run it."));
    if (files.length) {
      outputBody.append(select, cases, stdin, note, node("div", undefined, "studio-evidence-actions"));
      outputBody.lastElementChild.append(run, saveRun);
      update();
      if (cases.value) loadInput();
    }
    appendDraftNote();
  }
  function appendDraftNote() {
    const count = [...models.values()].filter(item => item.slug === state.slug && dirty(item)).length;
    if (count) outputBody.append(node("p", count + " unsaved draft(s). Operations use the saved package.", "muted"));
  }
  async function paintAnswers(info, epoch) {
    const plan = await api(packageApi("/answer-plan?snapshot=" + encodeURIComponent(info.snapshot), info.slug));
    if (epoch !== outputEpoch) return;
    outputBody.append(node("p", `${plan.counts.sample} sample · ${plan.counts.secret} secret · ${plan.references.length} reference solution(s)`),
      node("p", "Answers are generated by saved references. Multiple references must agree before that case's answer is written. Verify checks the resulting package separately.", "muted"));
    if (plan.references.length) outputBody.append(node("p", "References · " + plan.references.join(", ")));
    const outputs = node("details", undefined, "studio-test");
    outputs.append(node("summary", `${plan.outputs.length} expected output file(s)`));
    for (const entry of plan.outputs) outputs.append(node("p", `${entry.exists ? "Update" : "Create"} ${entry.answer}`));
    if (plan.outputs.length) outputBody.append(outputs);
    const build = button("Build expected answers", task(() => launchJob("answers")), "primary");
    build.disabled = !plan.outputs.length || !plan.references.length;
    if (build.disabled) outputBody.append(node("p", "Add a test input and a reference solution first.", "warning"));
    outputBody.append(build);
    appendDraftNote();
  }
  function freshness(snapshot) {
    const stamp = node("p", "", "muted");
    stamp.id = "studio-output-freshness";
    stamp.dataset.snapshot = snapshot;
    outputBody.append(stamp);
    markFreshness();
  }
  function section(title, content) {
    outputBody.append(node("h3", title), node("pre", content));
  }
  function paintRunResult(data) {
    freshness(data.snapshot);
    outputBody.append(node("p", "Local process · " + (data.casePath || "custom input"), "muted"));
    outputBody.append(node("p", data.path + " · " + (data.timedOut ? "Timed out"
      : data.stage === "compile" ? "Compile failed" : "exit " + data.exitCode + " · " + data.ms + " ms")));
    section("Standard output", data.stdout || "(empty)");
    if (data.comparison) {
      section(data.comparison.matches ? "Matches expected output" : "Output mismatch", "Expected · " +
        data.comparison.source + "\n" + (data.comparison.expected || "(empty)"));
      outputBody.append(node("p", "Manual token comparison. Use Verify for the package checker.", "muted"));
      if (data.runSetup?.receipt) outputBody.append(node("p", `Expected output attached from receipt ${data.runSetup.receipt.id}.`, "muted"));
    }
    if (data.stderr) section("Diagnostics", data.stderr);
    for (const loc of data.diagnostics || []) outputBody.append(button(`Open ${loc.path.split("/").at(-1)}:${loc.line}`,
      task(() => openDiagnostic(data, loc))));
    if (data.casePath) outputBody.append(button("Open case", task(() => openFile(data.casePath, { pinned: true }))));
    if (data.previewTruncated) outputBody.append(node("p", "Recovered a shortened copy of this output."));
    outputBody.append(button("Run again", () => data.runSetup ? prepareRun(data.runSetup) : openOutput("run", true)));
  }
  async function showSaveConflict(record) {
    openOutput("conflict");
    const epoch = outputEpoch;
    outputStatus.textContent = "The disk copy changed. Your draft is still open.";
    let file;
    try { file = await api(packageApi("/file?path=" + encodeURIComponent(record.path), record.slug)); }
    catch (error) {
      if (error.status !== 404) throw error;
      file = { text: true, content: "", hash: null };
    }
    if (epoch !== outputEpoch || active() !== record) return;
    const copyDraft = button("Copy draft text", task(async () => {
      await navigator.clipboard.writeText(record.text);
      showNotice("Draft text copied.");
    }));
    if (!file.text) {
      outputBody.append(node("p", "The saved file now uses a binary format. Copy the text draft to another file."), copyDraft);
      return;
    }
    const disk = node("details");
    disk.open = true;
    disk.append(node("summary", "Current saved copy"), node("pre", file.hash === null ? "This file is missing." : file.content));
    outputBody.append(disk, button("Keep draft against this saved copy", () => {
      record.hash = file.hash;
      record.saved = file.content;
      record.conflict = false;
      rememberDraft(record);
      paintMeta();
      outputStatus.textContent = "Draft retained. Click Save to replace the displayed saved copy.";
    }), copyDraft);
    if (file.hash !== null) outputBody.append(button("View saved copy in a separate tab", () => {
      const key = "saved:" + record.slug + ":" + record.path;
      models.set(key, { slug: record.slug, path: record.path + " (saved copy)", text: file.content, readonly: true,
        temporary: true });
      selectFile(key);
    }));
  }
  function paintVerify(info) {
    if (!info.limitsMeasured) outputBody.append(button("Measure limits", () => openOutput("measure-limits")));
    outputBody.append(button("Verify saved package", task(() => launchJob("verify", { writeAnswers: false })), "primary"));
    appendDraftNote();
    if (!info.lastReport) { outputBody.append(node("p", "No verification report yet.")); return; }
    if (info.previousVerification) outputBody.append(node("p", "Earlier verified package · " +
      revisionLabel(info.previousVerification.snapshot) + " · " + receiptDate(info.previousVerification.at), "muted"));
    paintReport(info.lastReport);
  }
  const revisionLabel = value => String(value || "unrecorded").slice(0, 12);
  const receiptDate = value => value ? new Date(value).toLocaleString() : "date unrecorded";
  const endpointLabel = value => ({ half_open: "Half-open (touching jobs are compatible)", closed: "Closed (touching jobs conflict)" })[value] || "Unrecorded";
  const privateInput = path => /(^|\/)data\/(?!sample\/)[^\s]+/i.test(path || "");
  const hasSavedFile = path => state.files.some(item => item.type === "file" && item.path === path);
  const copyText = (text, receipt) => task(async () => {
    await navigator.clipboard.writeText(text);
    showNotice(receipt);
  });
  function fileAction(label, path) {
    return hasSavedFile(path) ? button(label, task(() => openFile(path, { pinned: true }))) : null;
  }
  function testPath(test) {
    return test.path || (test.test && (hasSavedFile(test.test) ? test.test : "data/" + test.test));
  }
  function failedTest(test) {
    return test.validatorPassed === false || test.expectedAnswer?.present === false ||
      (test.solutions || []).some(solution => solution.verdict !== "AC");
  }
  function paintReport(report) {
    const current = state.info?.snapshot === report.snapshot;
    const caption = report.status === "verified" ? (current ? "Package verified" : "Earlier verification passed") : "Verification " + report.status;
    outputBody.append(node("h3", caption));
    freshness(report.snapshot);
    outputBody.append(node("p", "Package checks · " + receiptDate(report.at), "muted"));
    const failures = report.errors || [];
    const findings = [...failures, ...(report.warnings || [])];
    const tests = [...(report.tests || [])].filter(test => testPath(test));
    tests.sort((a, b) => Number(failedTest(b)) - Number(failedTest(a)));
    if (current && failures.length) {
      const first = tests.find(failedTest);
      const source = first?.solutions?.find(solution => solution.verdict !== "AC");
      const actions = node("div", undefined, "studio-evidence-actions");
      const check = failures[0];
      const related = [fileAction("Open failing case", testPath(first || {})), fileAction("Open failing source", source?.path)].filter(Boolean);
      outputBody.append(node("p", check, "warning"), actions);
      actions.append(...related);
      const location = report.sourceDiagnostics?.[source?.path]?.[0];
      if (location) actions.append(button("Open diagnostic line " + location.line,
        task(() => openDiagnostic({ sourceHash: report.sourceHashes?.[source.path] }, location))));
      if (first?.expectedAnswer?.present === false || /answer file/i.test(check)) actions.append(button("Build expected answers", () => openOutput("answers")));
      if (/limit/i.test(check)) actions.append(button("Measure limits", () => openOutput("measure-limits")));
    }
    if (findings.length) {
      const details = node("details", undefined, "studio-test");
      details.append(node("summary", `${failures.length} error(s) · ${(report.warnings || []).length} warning(s)`));
      const list = node("ul");
      for (const entry of findings.slice(0, 60)) list.append(node("li", entry));
      details.append(list);
      outputBody.append(details);
    }
    if (report.negative?.length) {
      const negative = node("details", undefined, "studio-test");
      negative.append(node("summary", `${report.negative.length} known-bad solution(s)`));
      for (const result of report.negative) {
        negative.append(node("p", `${result.path} · ${result.status === "killed" ? "caught by " + result.test : result.status}`));
        if (result.counts) negative.append(node("p", Object.entries(result.counts).filter(([, count]) => count)
          .map(([verdict, count]) => `${count} ${verdict}`).join(" · "), "muted"));
      }
      outputBody.append(negative);
    }
    if (tests.length) paintTestTable(tests, report);
    outputBody.append(button("Compare solutions", () => openOutput("compare")));
    outputBody.append(button("Discuss in chat", () => stageDiscussion(
      "What does this verification report establish, and what still needs review?\n\n" +
      caption + " for package " + state.slug + ", revision " + (report.snapshot || "unknown").slice(0, 12) +
      (state.info?.snapshot !== report.snapshot ? " (outdated)" : "") + ".\n" +
      `${failures.length} errors and ${(report.warnings || []).length} warnings. Include the limits of this evidence.`
    )));
  }
  function paintTestTable(tests, report) {
    const filters = node("div", undefined, "studio-evidence-actions");
    const group = node("select");
    const status = node("select");
    group.setAttribute("aria-label", "Test group");
    status.setAttribute("aria-label", "Test result");
    group.append(new Option("All groups", ""));
    const groupName = test => [test.kind, test.group].filter(Boolean).join(" / ");
    for (const value of [...new Set(tests.map(groupName).filter(Boolean))].sort()) group.append(new Option(value, value));
    status.append(new Option("Any result", ""), new Option("Needs attention", "failed"), new Option("Passed", "passed"),
      new Option("No result recorded", "unknown"));
    filters.append(group, status);
    const rows = node("div");
    outputBody.append(node("h3", "Tests and evidence"), filters, rows);
    const outcome = test => failedTest(test) ? "failed" : test.solutions?.length ? "passed" : "unknown";
    let limit = 30;
    const render = () => {
      const filtered = tests.filter(test => (!group.value || groupName(test) === group.value) && (!status.value || outcome(test) === status.value));
      rows.replaceChildren(node("p", `${filtered.length} of ${tests.length} cases · ${filtered.filter(failedTest).length} need attention`, "muted"));
      for (const test of filtered.slice(0, limit)) rows.append(paintTestRow(test, report, outcome(test)));
      if (filtered.length > limit) rows.append(button(`Show more (${filtered.length - limit} remaining)`, () => { limit += 30; render(); }));
    };
    group.onchange = status.onchange = () => { limit = 30; render(); };
    render();
  }
  function paintTestRow(test, report, outcome) {
    const path = testPath(test);
    const row = node("details", undefined, "studio-test");
    const verdicts = new Map();
    for (const solution of test.solutions || []) verdicts.set(solution.verdict, (verdicts.get(solution.verdict) || 0) + 1);
    row.append(node("summary", `${path} · ${[...verdicts].map(([name, count]) => count + " " + name).join(" · ") || outcome}`));
    row.append(node("p", test.validatorPassed == null ? "Input validation not reported" : test.validatorPassed ?
      "Input validator passed" : "Input validator rejected this case"));
    const answer = test.expectedAnswer;
    if (answer) row.append(node("p", !answer.present ? `Missing ${answer.path}` : `Expected answer · ${answer.path}` +
      (answer.references?.length ? ` · built by ${answer.references.join(", ")}` +
        (answer.inputMatchesBuild ? "" : " · input changed since build") : " · origin unrecorded")));
    const current = state.info?.snapshot === report.snapshot;
    if (current && hasSavedFile(path)) {
      row.append(fileAction("Open case", path), button("Copy case input (local)", task(async () => {
        const latest = await loadPackage();
        if (latest?.snapshot !== report.snapshot) throw new Error("The package changed. Verify again to copy a current case.");
        await copyText(await fetchCase(path, latest.slug), "Case input copied.")();
      })));
      if (hasSavedFile(answer?.path)) row.append(fileAction("Open answer", answer.path));
    }
    for (const solution of test.solutions || []) {
      row.append(node("p", solution.verdict + " · " + solution.path));
      if (current && hasSavedFile(solution.path)) {
        row.append(fileAction("Open solution", solution.path));
        for (const location of report.sourceDiagnostics?.[solution.path] || []) row.append(button("Open line " + location.line,
          task(() => openDiagnostic({ sourceHash: report.sourceHashes?.[solution.path] }, location))));
        if (hasSavedFile(path)) row.append(button("Run this case", () => prepareRun({ path: solution.path, casePath: path })));
      }
      if (solution.error || solution.stderr) row.append(node("pre", solution.error || solution.stderr));
      if (solution.actualPreview !== undefined) row.append(node("pre", "Expected (preview)\n" + solution.expectedPreview +
        "\nActual (preview)\n" + solution.actualPreview));
    }
    return row;
  }
  function paintExport(info) {
    const workflow = info.workflow;
    const report = info.lastReport;
    const archive = info.archive;
    const verified = workflow.verifiedSnapshot === workflow.snapshot;
    const reviewed = verified && workflow.nextAction === "export";
    const list = node("ol", undefined, "studio-release-steps");
    list.append(node("li", verified ? `Verified · ${receiptDate(report?.at)}` : "Verify saved package"),
      node("li", reviewed ? `Human review · ${receiptDate(info.lastReview)}` : "Review and approve saved changes"),
      node("li", archive?.status === "ready" ? "Archive ready to download" : "Generate archive"));
    outputBody.append(list, node("p", (archive?.filename || "Package archive") + " · DOMjudge ZIP"));
    freshness(workflow.snapshot);
    outputBody.append(button("Setter handoff", () => openOutput("handoff")));
    if (archive?.status === "stale") outputBody.append(node("p", "Earlier archive · " +
      (archive.archiveFilename || archive.filename) + " · " + revisionLabel(archive.snapshot) +
      (archive.createdAt ? " · " + receiptDate(archive.createdAt) : "") + ". Generate a new archive for the current package.", "warning"));
    if (workflow.nextAction === "verify") {
      outputBody.append(node("p", workflow.blocker, "warning"),
        button("Open verification", () => openOutput("verify")));
      return;
    }
    if (workflow.nextAction === "review") {
      outputBody.append(node("p", workflow.unreviewedChanges
        ? workflow.unreviewedChanges + " change(s) need review before export." : workflow.blocker, "warning"),
        button("Review package changes", () => openOutput("review")));
      return;
    }
    if (info.archive?.status === "ready") {
      outputBody.append(downloadLink(workflow.snapshot));
      if (archive.createdAt) outputBody.append(node("p", "Generated " + receiptDate(archive.createdAt), "muted"));
    } else {
      outputBody.append(node("p", "Generate a DOMjudge ZIP for the current verified package."));
    }
    outputBody.append(button("Generate ZIP", task(() => launchJob("export")), "primary"));
    appendDraftNote();
  }
  function downloadLink(snapshot) {
    const link = node("a", "Download ZIP", "studio-download");
    link.href = packageApi("/download?snapshot=" + encodeURIComponent(snapshot));
    return link;
  }
  async function paintReview(info, epoch) {
    const route = "/studio-review?snapshot=" + encodeURIComponent(info.snapshot);
    const result = await api(packageApi(route, info.slug));
    if (epoch !== outputEpoch) return;
    freshness(result.snapshot);
    outputBody.append(node("p", result.baseline ? `Compared with approved revision ${revisionLabel(result.baseline)}.` :
      "No approved file baseline is available. Inspect the saved files before approving this revision.", "muted"));
    const groups = new Map();
    const purposes = { data: "Tests and answers", submissions: "Solutions", statement: "Problem statement",
      problem_statement: "Problem statement", input_validators: "Checkers and validators", output_validators: "Checkers and validators" };
    for (const entry of result.files) {
      const group = purposes[entry.path.split("/")[0]] || "Package and supporting files";
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group).push(entry);
    }
    const key = "review-seen:" + info.slug + ":" + result.snapshot;
    const viewed = new Set(local.read(key) || []);
    const seen = node("p", "", "muted");
    const updateSeen = () => { seen.textContent = `${viewed.size} of ${result.files.length} files viewed`; };
    if (result.files.length) outputBody.append(seen);
    updateSeen();
    for (const [name, entries] of groups) {
      const group = node("details", undefined, "studio-test");
      group.append(node("summary", name + " · " + entries.length));
      const shown = node("div");
      group.append(shown);
      let from = 0;
      const more = button("Show more files", () => appendRows());
      const appendRows = () => {
        for (const entry of entries.slice(from, from + 40)) {
          const details = node("details", undefined, "studio-review-file");
          const heading = node("summary");
          const label = () => { heading.textContent = `${entry.path} · ${entry.kind}${viewed.has(entry.path) ? " · viewed" : ""}`; };
          label();
          details.append(heading);
          details.addEventListener("toggle", task(async () => {
            if (!details.open || details.dataset.loaded) return;
            details.dataset.loaded = "loading";
            try {
              const change = await api(packageApi(route + "&path=" + encodeURIComponent(entry.path), info.slug));
              if (epoch !== outputEpoch || !details.isConnected) return;
              details.dataset.loaded = "true";
              details.append(node("p", entry.source, "muted"));
              if (entry.artifactOrigin) details.append(node("p", `Conversation artifact ${entry.artifactOrigin.artifactId} · revision ${revisionLabel(entry.artifactOrigin.revision)}`, "muted"));
              if (change.hasDiff) details.append(node("pre", change.diff || "File bytes differ outside the text comparison."));
              else if (change.current != null) details.append(node("pre", change.current || "(empty file)"));
              else details.append(node("p", "Text comparison is unavailable for this file."));
              const open = fileAction("Open saved file", entry.path);
              if (open) details.append(open);
              const mark = () => { viewed.add(entry.path); local.write(key, [...viewed]); label(); updateSeen(); };
              if (change.hasDiff || change.current != null) mark();
              else if (open) open.onclick = task(async () => { await openFile(entry.path, { pinned: true }); if (active()?.path === entry.path) mark(); });
            } catch (error) {
              details.dataset.loaded = "";
              throw error;
            }
          }));
          shown.insertBefore(details, more);
        }
        from += 40;
        more.hidden = from >= entries.length;
      };
      shown.append(more);
      group.addEventListener("toggle", () => { if (group.open && !from) appendRows(); });
      outputBody.append(group);
    }
    if (info.workflow.nextAction === "verify") {
      outputBody.append(node("p", info.workflow.blocker, "warning"),
        button("Open verification", () => openOutput("verify")));
      return;
    }
    if (info.workflow.canExport) {
      outputBody.append(node("p", "This saved version has already been reviewed."),
        button("Open export", () => openOutput("export")));
      return;
    }
    outputBody.append(button("Approve saved snapshot", task(async () => {
      await api(packageApi("/review", info.slug), { expectedSnapshot: result.snapshot });
      if (epoch === outputEpoch) openOutput("export");
    }), "primary"));
  }
  function paintComparison(info) {
    const report = info.lastReport;
    const current = report?.snapshot === info.snapshot;
    outputBody.append(node("p", "Review the proof and the saved candidates together. Verification records execution on the test set; each complexity and invariant still needs a source.", "muted"));
    if (state.view?.profile?.includes("interval")) {
      const semantics = (state.view.collaboration?.decisions || []).filter(item => item.requirementId === "endpoint_semantics").at(-1)?.optionId;
      outputBody.append(node("p", "Interval DP · O(n log n). Each prefix stores the best reward achievable so far. Check the predecessor boundary and base case against " +
        (semantics || "the endpoint rule") + "."));
      outputBody.append(node("p", "Earliest-finish greedy · O(n log n). The unweighted exchange argument preserves job count. A higher-value overlapping job can refute its use for maximum reward."));
      const proof = currentProof();
      if (proof) outputBody.append(button("Open current proof", () => loadArtifact(proof.id, { pinned: true })));
      outputBody.append(button("Inspect predecessor obligation", () => stageDiscussion(
        `Review the predecessor and prefix optimum obligations for conversation revision ${state.view.revision}. ` +
        "Compare weighted interval DP and earliest-finish greedy. Cite the exact proof, source, or evidence record for each claim.")));
    }
    const files = info.tree.filter(file => file.type === "file" && file.path.startsWith("submissions/") && runnable(file.path));
    for (const file of files) {
      const wrong = report?.negative?.find(row => row.path === file.path);
      const accepted = report?.accepted?.find(row => row.path === file.path);
      const result = wrong?.status === "killed" ? "caught by " + wrong.test : wrong?.status ||
        (accepted ? (accepted.compiled ? "compiled in verification" : "compile failed in verification") : "no verification result");
      const hash = report?.sourceHashes?.[file.path];
      outputBody.append(node("p", file.path + " · " + result + (hash ? " · source " + revisionLabel(hash) : "") +
        (current ? "" : " · earlier or unrecorded")));
      outputBody.append(fileAction("Open " + file.path, file.path));
    }
    if (report) outputBody.append(button("Open supporting verification · " + revisionLabel(report.snapshot), () => openOutput("verify")));
  }
  function paintHandoff() {
    const { view, info } = state;
    const name = view?.title || info?.meta?.name || "Untitled problem";
    const endpoint = (view?.collaboration?.decisions || []).filter(item => item.requirementId === "endpoint_semantics").at(-1);
    const current = info?.lastReport?.snapshot === info?.snapshot;
    const evidence = Object.values(view?.evidenceCards || {});
    const newest = evidence.at(-1);
    const lines = [name,
      view ? `Conversation revision ${revisionLabel(view.revision)} · ${String(view.status).replaceAll("_", " ")}` : "Manual workspace",
      endpoint ? `Endpoint decision: ${endpointLabel(endpoint.optionId)} · author input ${endpoint.sourceId}` : "Endpoint decision: unrecorded",
      newest ? `Conversation evidence: ${evidence.length} case receipt(s); latest ${newest.id}${/simulat|fake/i.test(newest.worker || "") ? " (simulation)" : ""}.` : null,
      info ? `Package verification: ${info.lastReport?.status || "not run"}${info.lastReport?.snapshot ? " · " + revisionLabel(info.lastReport.snapshot) : ""}${info.lastReport && !current ? " (earlier revision)" : ""}.` : "Linked package: none.",
      view?.pendingDecision ? `Open: ${view.pendingDecision.kind.replaceAll("_", " ")} decision.` : null,
      (view?.handoff?.open_questions || []).length ? `Open: ${view.handoff.open_questions.length} investigation question(s).` : null,
      info?.workflow?.blocker || null,
      info?.archive?.snapshot ? `Archive revision: ${revisionLabel(info.archive.snapshot)} · ${info.archive.status === "stale" ? "earlier archive" : info.archive.status}.` : "Archive: none.",
    ].filter(Boolean);
    const summary = lines.join("\n");
    outputBody.append(node("p", "Shareable summary · includes decisions and receipt references. Case contents and drafts stay in the workspace.", "muted"),
      node("pre", summary), button("Copy handoff summary", copyText(summary, "Handoff summary copied.")));
  }
  const jobProgress = { queued: "Waiting for the workspace to be available.",
    cancel_pending: "Cancellation requested. Waiting for the job to stop.",
    timeout_pending: "Time limit reached. Waiting for the job to stop." };

  function jobVisible(job) {
    return job.sequence === latestJob && job.slug === state.slug &&
      currentOutput === job.mode && !$("studio-output").hidden;
  }

  function paintJob(job) {
    outputBody.replaceChildren();
    outputStatus.textContent = job.connectionLost ? "Could not read the job status." : job.name + "…";
    if (job.connectionLost) {
      outputBody.append(node("p", "The job may still be running. Reconnect to check its result."),
        button("Reconnect to job", task(() => watchJob(job))));
    } else if (jobProgress[job.phase]) {
      outputBody.append(node("p", jobProgress[job.phase]));
    } else {
      outputBody.append(node("p", jobVisible(job) ? "Working on the saved package." : job.name + " for " + job.slug + "."));
    }
    if (!job.connectionLost) {
      const elapsed = node("p", "", "muted");
      elapsed.dataset.jobElapsed = "";
      outputBody.append(elapsed);
      paintElapsed(job);
    }
    if (job.id && job.cancellable && !["cancel_pending", "timeout_pending"].includes(job.phase)) {
      outputBody.append(button("Cancel job", task(cancelJob)));
    }
  }
  function paintElapsed(job) {
    const time = outputBody.querySelector("[data-job-elapsed]");
    if (!time || !job.startedAt || !jobVisible(job)) return;
    const elapsed = Math.max(0, Math.floor((Date.now() - Date.parse(job.startedAt)) / 1000));
    time.textContent = elapsed >= 10 ? `Elapsed ${elapsed >= 60 ? `${Math.floor(elapsed / 60)}m ` : ""}${elapsed % 60}s` : "";
    time.hidden = elapsed < 10;
  }

  async function cancelJob() {
    const job = state.job;
    if (!job?.id) return;
    const result = await api("/api/jobs/" + job.id + "/cancel", {});
    if (state.job !== job) return;
    job.phase = result.phase;
    if (jobVisible(job)) paintJob(job);
  }
  async function launchJob(mode, params = {}) {
    if (state.job || !state.info) return;
    const slug = state.slug;
    const job = { slug, runId: state.runId, mode, name: operationNames[mode], sequence: ++latestJob,
      runSetup: mode === "run" ? readRunSetup() : null, startedAt: new Date().toISOString(),
      cancellable: ["verify", "answers", "measure-limits"].includes(mode) };
    state.job = job;
    paintJob(job);
    let started;
    try {
      started = await api(packageApi("/" + mode, slug), { ...params, expectedSnapshot: state.info.snapshot });
      job.id = started.id;
    } catch (error) {
      state.job = null;
      if (jobVisible(job)) outputStatus.textContent = error.message;
      else showNotice(error.message);
      return;
    }
    await watchJob(job, started);
  }

  async function watchJob(job, result = null) {
    if (state.job !== job || job.polling) return;
    const { mode, slug } = job;
    job.polling = true;
    job.connectionLost = false;
    if (jobVisible(job)) paintJob(job);
    let missed = 0;
    try {
      while (!result || result.state === "running") {
        if (result && job.phase !== result.phase) {
          job.phase = result.phase;
          if (jobVisible(job)) paintJob(job);
        }
        paintElapsed(job);
        await new Promise(resolve => setTimeout(resolve, 400));
        try {
          result = await api("/api/jobs/" + job.id);
          missed = 0;
        } catch (error) {
          if (error.status === 404) {
            state.job = null;
            throw new Error("The server no longer has this job. Check the saved package before starting another action.");
          }
          if (++missed < 3) continue;
          job.connectionLost = true;
          if (jobVisible(job)) paintJob(job);
          else showNotice(job.name + " lost its connection. Reopen its output to reconnect.");
          return;
        }
      }
      if (mode === "run" && result.state === "done") {
        const data = { ...result.result, runSetup: job.runSetup };
        result.result = data;
        const key = runResultKey(job.runId, slug);
        completedRuns.set(key, data);
        local.write(key, { ...data, stdout: data.stdout?.slice(0, 40000),
          stderr: data.stderr?.slice(0, 40000), previewTruncated: (data.stdout?.length || 0) > 40000 ||
            (data.stderr?.length || 0) > 40000 });
      }
      state.job = null;
      if (result.state !== "done") {
        const message = result.error || (result.state === "cancelled" ? "Job stopped." : result.state);
        if (jobVisible(job)) {
          outputBody.replaceChildren();
          outputStatus.textContent = message;
          if (result.phase === "timed_out" && result.workerActive) {
            outputBody.append(node("p", "The worker is still releasing the workspace."));
          }
        } else showNotice(job.name + " · " + message);
        return;
      }
      const info = await loadPackage(slug);
      if (job.sequence !== latestJob) return;
      if (!jobVisible(job)) {
        showNotice(job.name + " finished for " + slug + ".");
        if (state.slug === slug && !$("studio-output").hidden) openOutput(currentOutput);
        return;
      }
      outputBody.replaceChildren();
      outputStatus.textContent = "";
      const data = result.result;
      if (mode === "verify") paintVerify(info);
      if (mode === "run") paintRunResult(data);
      if (mode === "answers") {
        outputStatus.textContent = data.written + " answer file(s) written" + (data.ok ? "." : " · incomplete.");
        local.write("operation-result:" + slug + ":" + mode, { summary: outputStatus.textContent, snapshot: info?.snapshot });
        for (const error of data.errors || []) outputBody.append(node("p", error.path + " · " + error.error, "warning"));
        for (const disagreement of data.disagreements || []) outputBody.append(node("p", disagreement.test + " · reference disagreement", "warning"));
        if (data.outputs?.length) outputBody.append(node("p", "Written · " + data.outputs.slice(0, 12).map(item => item.path).join(", ") +
          (data.outputs.length > 12 ? ` and ${data.outputs.length - 12} more` : ""), "muted"));
        if (data.ok && data.references?.length > 1) outputBody.append(node("p", "The saved references agreed on all generated answers."));
        outputBody.append(button("Open verification", () => openOutput("verify")));
      }
      if (mode === "measure-limits") {
        if (data.ok === false) section("Measurement failed", (data.errors || []).map(error => JSON.stringify(error)).join("\n"));
        else outputStatus.textContent = "Limits measured for this package.";
        local.write("operation-result:" + slug + ":" + mode,
          { summary: data.ok === false ? "Measurement failed." : outputStatus.textContent, snapshot: info?.snapshot });
        outputBody.append(button("Open verification", () => openOutput("verify")));
      }
      if (mode === "export") {
        outputBody.append(node("p", data.files + " package files · " + data.size + " bytes"));
        paintExport(info);
      }
    } catch (error) {
      if (jobVisible(job)) outputStatus.textContent = error.message;
      else showNotice(error.message);
    } finally {
      job.polling = false;
    }
  }
  function paintProblems() {
    const record = active();
    const data = record?.diagnostics;
    if (!data) { outputBody.append(node("p", "Check this draft to list its diagnostics.")); return; }
    outputStatus.textContent = data.tool + " · " + data.diagnostics.length + " finding(s) in " + record.path;
    for (const finding of data.diagnostics) {
      outputBody.append(button(finding.line + ":" + finding.column + " · " + finding.message, () => {
        if (!editor) return;
        state.mode = "edit";
        paintEditor();
        editor.revealPositionInCenter({ lineNumber: finding.line, column: finding.column });
        editor.setPosition({ lineNumber: finding.line, column: finding.column });
        editor.focus();
      }));
    }
  }
  async function editorTool(operation) {
    const record = active();
    if (!record || record.readonly) return;
    const text = record.text;
    const feedback = $("studio-file-feedback");
    feedback.hidden = false;
    feedback.textContent = operation === "format" ? "Formatting the draft…" : "Checking the draft…";
    let data;
    try { data = await api("/api/studio/editor-tool", { operation, content: text, path: record.path }); }
    catch (error) {
      if (active() === record) feedback.textContent = "Could not " + operation + " " + record.path + ". " + error.message + " Try again.";
      return;
    }
    if (active() === record) feedback.hidden = true;
    if (active() !== record || text !== record.text) return;
    if (data.available === false) {
      feedback.hidden = false;
      feedback.textContent = data.reason + " You can continue editing and save your draft.";
      return;
    }
    if (operation === "format") {
      if (text === data.content) { showNotice("Already formatted · " + data.tool); return; }
      if (editor && record.model) {
        editor.pushUndoStop();
        editor.executeEdits("studio-format", [{ range: record.model.getFullModelRange(), text: data.content }]);
        editor.pushUndoStop();
      } else {
        fallback.value = data.content;
        edited(record, data.content);
        paintMeta();
        paintMarkdown();
      }
      showNotice("Formatted draft · " + data.tool);
    } else {
      record.diagnostics = data;
      if (record.model) monaco.editor.setModelMarkers(record.model, "studio", data.diagnostics.map(item => ({
        startLineNumber: item.line, startColumn: item.column, endLineNumber: item.line, endColumn: item.column + 1,
        message: item.message, severity: item.severity === "error" ? monaco.MarkerSeverity.Error : monaco.MarkerSeverity.Warning
      })));
      openOutput("problems");
    }
  }

  async function selectPackage(slug, preserveDrawer = false) {
    state.slug = slug || "";
    state.selected = "";
    state.info = null;
    state.files = [];
    $("studio-new-file").hidden = true;
    $("studio-package-label").textContent = "Conversation artifacts";
    if (!preserveDrawer) $("studio-output").hidden = $("studio-output-split").hidden = true;
    syncOutputLayout();
    outputEpoch++;
    if (!preserveDrawer) buttons.forEach(item => item.setAttribute("aria-expanded", "false"));
    paintTabs();
    paintEditor();
    paintTree();
    if (slug) await loadPackage(slug);
  }
  async function restorePlace(request, saved, requestedLayout) {
    if (!saved || saved.slug !== state.slug) return;
    const runId = state.runId, slug = state.slug, selectedAtStart = openRequest;
    const results = await Promise.allSettled((saved.tabs || []).map(async tab => {
      const previous = models.get(tab.key);
      if (previous) return [tab, previous];
      const record = tab.id && runId
        ? artifactRecord(runId, await api(runApi("/artifacts/" + encodeURIComponent(tab.id), runId)))
        : await readFileRecord(slug, tab.path);
      return [tab, record];
    }));
    if (request !== requests || selectedAtStart !== openRequest) return;
    for (const result of results) {
      if (result.status !== "fulfilled") continue;
      const [tab, record] = result.value;
      Object.assign(record, { open: true, viewState: tab.viewState, fallbackState: tab.fallbackState,
        pinned: tab.pinned !== false || dirty(record) });
      models.set(tab.key, record);
    }
    state.selected = results.some(result => result.status === "fulfilled" && result.value[0].key === saved.selected)
      ? saved.selected : results.find(result => result.status === "fulfilled")?.value[0].key || "";
    state.mode = saved.mode || "edit";
    closedTabs = Array.isArray(saved.closedTabs) ? saved.closedTabs : [];
    const restoreLayout = requestedLayout === layoutVersion;
    if (restoreLayout) setLayout(saved.layout || "chat", true);
    paintTabs();
    paintEditor();
    paintTree();
    $("studio-tree").scrollTop = saved.treeTop || 0;
    if (restoreLayout && state.layout !== "chat" && saved.output &&
        !["conflict", "problems"].includes(saved.output)) openOutput(saved.output, false, false);
    if (results.some(result => result.status === "rejected")) showNotice("Some saved tabs are unavailable. Your current problem is open.");
  }

  async function restorePackage(runId, preserveDrawer) {
    const request = ++requests;
    const requestedLayout = layoutVersion;
    const saved = local.read(placeKey() + local.tab, local.read(placeKey() + "latest"));
    restoringPlace = request;
    state.linkState = "loading";
    const refreshDrawer = () => {
      if (state.layout !== "chat" && !$("studio-output").hidden) openOutput(currentOutput, false, false);
    };
    try {
      await selectPackage("", preserveDrawer);
      refreshDrawer();
      const link = runId ? await api(runApi("/studio-package", runId)) : { slug: local.read("manual-package") };
      if (request !== requests) return;
      state.link = link;
      if (link?.slug) await selectPackage(link.slug, true);
      if (request !== requests) return;
      state.linkState = "ready";
      if (runId && !link?.slug) $("studio-link-recent").hidden = !local.read("manual-package");
      await restorePlace(request, saved, requestedLayout);
      if (request === requests && requestedLayout === layoutVersion) await applyAddress();
    } catch (error) {
      if (request !== requests) return;
      state.linkState = "error";
      showNotice(error.message);
    } finally {
      if (restoringPlace === request) restoringPlace = false;
    }
    if (request === requests) refreshDrawer();
  }
  window.addEventListener("studio-conversation", task(async event => {
    const { runId, view } = event.detail;
    runs = event.detail.runs;
    const title = view?.title || null;
    const titleChanged = state.title !== title;
    state.title = title;
    state.view = view;
    const artifacts = view?.artifacts || [];
    const changed = JSON.stringify(artifacts.map(a => [a.id, a.validity])) !== JSON.stringify(state.artifacts.map(a => [a.id, a.validity]));
    state.artifacts = artifacts;
    $("studio-proof").disabled = !currentProof();
    $("studio-proof").title = currentProof() ? "Open the current proof or editorial" : "Ask for a proof or editorial in chat";
    $("studio-context-counts").textContent = `${view?.chatMessages?.length || 0} conversation turns and ${artifacts.length} artifacts stored. Inclusion in model context varies by request.`;
    if (runId === state.runId) {
      if (changed) {
        for (const artifact of artifacts) {
          const item = models.get(artifactKey(artifact.id));
          if (item) item.validity = artifact.validity;
        }
        paintTree();
        paintMeta();
      }
      if (titleChanged && state.slug) await refreshPackageTitle(state.slug);
      return;
    }
    const firstSelection = state.runId === null;
    rememberPlace();
    closedTabs = [];
    $("studio-link-recent").hidden = true;
    state.runId = runId;
    await restorePackage(runId, firstSelection);
  }));
  window.addEventListener("popstate", () => {
    if (navigation.target().problem === state.runId) {
      const target = navigation.target();
      if (!target.file && !target.artifact) setLayout("chat");
      else applyAddress();
    }
  });
  window.addEventListener("studio-artifact", event => openArtifact(event.detail.runId, event.detail.artifact));
  window.addEventListener("studio-run-witness", event => {
    const { runId, card } = event.detail;
    if (runId !== state.runId) return;
    if (!state.slug) { showNotice("Link a package, then choose a saved source for this case."); task(packageDialog)(); return; }
    const expected = card.classification !== "shared_semantics_defect" && card.expected != null ? String(card.expected) : undefined;
    prepareRun({ stdin: card.input, expected, receipt: { id: card.id, historical: card.historical } });
  });

  $("studio-package").onclick = task(() => packageDialog());
  $("studio-link-recent").onclick = task(() => packageDialog({ preferred: local.read("manual-package") }));
  $("studio-package-select").onchange = task(async () => {
    $("studio-link-error").textContent = "";
    $("studio-sync-title").checked = $("studio-package-select").value === state.slug && Boolean(state.slug) &&
      state.link?.syncTitle !== false;
    await previewPackage();
  });
  $("studio-sync-title").onchange = paintPackageImpact;
  $("studio-link-refresh").onclick = task(previewPackage);
  $("studio-package-dialog").addEventListener("close", () => {
    packageIntent = null;
    previewSequence++;
  });
  $("studio-package-dialog").addEventListener("cancel", event => {
    if (packageIntent?.saving) event.preventDefault();
  });
  $("studio-package-form").onsubmit = task(async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const intent = packageIntent;
    if (!intent || intent.runId !== state.runId) return;
    const runId = intent.runId;
    const slug = $("studio-package-select").value;
    const name = $("studio-package-name").value.trim();
    const submit = form.querySelector('[type="submit"]');
    submit.disabled = true;
    intent.saving = true;
    const close = $("studio-package-dialog").querySelector("form[method='dialog'] button");
    close.disabled = true;
    try {
      if (!slug && !name) throw new Error("Enter a package name.");
      if (runId && (intent.preview?.slug !== slug)) throw new Error("Wait for the package preview.");
      const result = runId ? await api(runApi("/studio-package", runId), { name, slug,
        syncTitle: !slug || (!$("studio-sync-title-row").hidden && $("studio-sync-title").checked),
        ...intent.preview.data.basis })
        : slug ? { slug } : await api("/api/workspaces", { name });
      $("studio-package-dialog").close();
      if (runId === state.runId) {
        rememberPlace();
        requests++;
        state.linkState = "ready";
        state.link = result;
        if (!runId) local.write("manual-package", result.slug);
        $("studio-link-recent").hidden = true;
        if (state.slug !== result.slug) await selectPackage(result.slug);
        else await refreshPackageTitle(result.slug);
        if (runId !== state.runId || result.slug !== state.slug) return;
        if (intent.selected && models.has(intent.selected) && related(models.get(intent.selected))) selectFile(intent.selected);
        rememberPlace();
        showNotice(runId ? "Judge package linked." : "Manual package opened.");
        if (intent.copy && intent.copy.runId === state.runId) fileDraft(intent.copy);
      }
    } catch (error) {
      $("studio-link-error").textContent = error.message;
      if (error.status === 409) {
        intent.preview = null;
        $("studio-link-refresh").hidden = false;
      }
    } finally { intent.saving = false; submit.disabled = false; close.disabled = false; }
  });
  $("studio-file-form").onsubmit = task(async event => {
    event.preventDefault();
    const path = $("studio-new-path").value.trim().replaceAll("\\", "/");
    if (!path || path.startsWith("/") || path.split("/").some(part => !part || part === "." || part === "..") || path.includes(":")) {
      $("studio-file-error").textContent = "Enter a relative path such as submissions/accepted/solution.cpp.";
      return;
    }
    const copy = pendingCopy;
    const slug = state.slug;
    const runId = state.runId;
    if (slug !== pendingCopyScope?.slug || runId !== pendingCopyScope?.runId) {
      $("studio-file-error").textContent = "The destination changed. Reopen the copy or new file dialog.";
      return;
    }
    const key = fileKey(path);
    const exists = state.files.find(item => item.path.toLowerCase() === path.toLowerCase());
    if (copy?.artifactId && !state.artifacts.some(item => item.id === copy.artifactId && item.current)) {
      $("studio-file-error").textContent = "This conversation draft has been superseded.";
      return;
    }
    if (exists && copy?.packageDraft && exists.path === path) {
      if (dirty(models.get(key))) {
        $("studio-file-error").textContent = "Save your existing draft before replacing its contents.";
        return;
      }
      await openFile(path);
      if (slug !== state.slug || runId !== state.runId || copy !== pendingCopy || !models.has(key)) return;
      const record = models.get(key);
      if (record.readonly || dirty(record) || !state.artifacts.some(item => item.id === copy.artifactId && item.current)) {
        $("studio-file-error").textContent = "The file or the conversation draft changed. Reopen the copy dialog.";
        return;
      }
      record.origin = { runId, artifactId: copy.artifactId, revision: copy.revision };
      edited(record, copy.text);
      record.model?.setValue(copy.text);
    } else if (exists || models.has(key)) {
      $("studio-file-error").textContent = "This path already exists. Choose a new path or edit the existing file.";
      return;
    } else {
      const record = { path, slug, hash: null, text: copy?.text || "", saved: "", readonly: false,
        origin: copy?.artifactId ? { runId, artifactId: copy.artifactId, revision: copy.revision } : null };
      models.set(key, record);
      rememberDraft(record);
    }
    $("studio-file-dialog").close();
    state.mode = "edit";
    selectFile(key);
    showNotice(copy ? "Copied to a draft. Save to update the package." : "Draft opened. Save to add it to the package.");
  });
  $("studio-new-file").onclick = () => fileDraft();
  $("studio-copy").onclick = task(async () => {
    if (!state.slug) { await packageDialog({ copy: active() }); return; }
    fileDraft(active());
  });
  $("studio-discuss-file").onclick = () => {
    const record = active();
    const version = record.artifactId ? `artifact ${record.artifactId}, revision ${record.revision}` :
      `saved file hash ${record.hash || "none"}, package snapshot ${state.info?.snapshot || "unrecorded"}`;
    const status = dirty(record) ? " · unsaved excerpt" : record.validity === "stale" ? " · earlier artifact" : "";
    const privateCase = record.kind === "test" && !record.path.includes("/sample/") || privateInput(record.path);
    stageDiscussion(`Please review ${privateCase ? "this private test file" : record.path} (${version}${status}).\n\n` +
      (privateCase ? "[Private case contents omitted]" : record.text.slice(0, 6000) + (record.text.length > 6000 ? "\n[Excerpt truncated]" : "")));
  };
  $("studio-save").onclick = task(() => save());
  $("studio-pin-tab").onclick = () => pinTab();
  $("studio-close-tab").onclick = () => closeTab();
  $("studio-reopen-tab").onclick = reopenTab;
  $("studio-review-draft").onclick = task(() => showSaveConflict(active()));
  fallback.oninput = () => {
    const record = active();
    if (!record || record.readonly) return;
    edited(record, fallback.value);
    paintMeta();
    paintMarkdown();
  };
  for (const toggle of document.querySelectorAll("button[data-layout]")) toggle.onclick = () => setLayout(toggle.dataset.layout);
  for (const toggle of document.querySelectorAll("[data-doc-view]")) toggle.onclick = () => { state.mode = toggle.dataset.docView; paintEditor(); schedulePlace(); };
  for (const toggle of document.querySelectorAll("[data-editor-tool]")) toggle.onclick = task(() => editorTool(toggle.dataset.editorTool));
  for (const toggle of buttons) {
    toggle.onclick = () => openOutput(toggle.dataset.operation);
    toggle.disabled = false;
  }
  $("studio-files").onclick = openFileSearch;
  $("studio-skip").onclick = event => {
    event.preventDefault();
    setLayout("chat");
    composer.focus();
  };
  $("studio-commands").onclick = openCommands;
  $("studio-open-problem").onclick = openProblems;
  $("studio-nav").onclick = openProblems;
  function treeVisibility(show) {
    $("studio-workspace").dataset.tree = show ? "open" : "closed";
    $("studio-toggle-tree").textContent = show ? "Hide tree" : "Show tree";
    $("studio-toggle-tree").setAttribute("aria-expanded", String(show));
    local.write("tree-visible", show);
    requestAnimationFrame(() => editor?.layout());
  }
  $("studio-toggle-tree").onclick = () => treeVisibility($("studio-workspace").dataset.tree !== "open");
  treeVisibility(local.read("tree-visible", true));
  $("studio-proof").onclick = task(async () => {
    const proof = currentProof();
    if (!proof) return showNotice("Ask the agent to develop a proof or editorial first.");
    await loadArtifact(proof.id);
  });
  $("studio-hide-files").onclick = () => { setLayout("chat"); $("studio-files").focus(); };
  $("studio-close-output").onclick = closeOutput;
  $("studio-ledger").onclick = () => {
    const ledger = document.querySelector(".desk-ledger");
    ledger.hidden = !ledger.hidden;
    if (!ledger.hidden) { setLayout("chat"); ledger.querySelector("summary").focus(); }
    $("studio-ledger").setAttribute("aria-expanded", String(!ledger.hidden));
  };
  window.addEventListener("keydown", event => {
    if (event.defaultPrevented || event.isComposing || event.keyCode === 229 || event.repeat) return;
    const modal = document.querySelector("dialog[open]");
    if (modal && modal.id !== "studio-search-dialog") return;
    const key = event.key.toLowerCase();
    if (modal && !["k", "o", "p"].includes(key)) return;
    if (key === "escape" && !modal && $("studio-appearance").matches(":popover-open")) {
      event.preventDefault();
      $("studio-appearance").hidePopover();
      $("studio-appearance-trigger").focus();
      return;
    }
    if (key === "escape" && !modal && !document.querySelector(":popover-open") && !$("studio-output").hidden &&
        $("studio-output").contains(document.activeElement)) {
      event.preventDefault();
      closeOutput();
      return;
    }
    if (event.altKey && !event.ctrlKey && !event.metaKey) {
      const shortcuts = event.shiftKey ? { o: reopenTab } :
        { k: openCommands, p: openProblems, o: openFileSearch, r: () => openOutput("run") };
      if (shortcuts[key] && !event.target.closest?.(".find-widget")) {
        event.preventDefault();
        event.stopPropagation();
        shortcuts[key]();
      }
    } else if (event.target === fallback && (event.ctrlKey || event.metaKey) && !event.altKey) {
      if (key === "s") { event.preventDefault(); $("studio-save").click(); }
      if (key === "enter") { event.preventDefault(); openOutput("run"); }
    }
  }, true);
  const context = $("studio-context");
  const contextTrigger = $("studio-context-trigger");
  const placeContext = () => {
    const rect = contextTrigger.getBoundingClientRect();
    context.style.left = Math.max(12, Math.min(rect.left, innerWidth - 332)) + "px";
    context.style.bottom = Math.max(12, innerHeight - rect.top + 8) + "px";
  };
  context.addEventListener("beforetoggle", event => { if (event.newState === "open") placeContext(); });
  context.addEventListener("toggle", event => contextTrigger.setAttribute("aria-expanded", String(event.newState === "open")));
  window.addEventListener("resize", () => { if (context.matches(":popover-open")) placeContext(); });
  for (const [key, low, high, initial] of [["width", 28, 72, 52], ["output", 150, 550, 228], ["font", 14, 26, 18], ["codeFont", 12, 24, 15]]) {
    state[key] = coerce(local.legacy("studio-" + key), low, high, initial);
  }
  for (const [id, property] of [["studio-reading-size", "font"], ["studio-code-size", "codeFont"]]) {
    $(id).value = state[property];
    $(id).oninput = () => {
      state[property] = Number($(id).value);
      local.rememberLegacy("studio-" + property, state[property]);
      setSizes();
    };
  }
  const themeSelect = $("studio-theme");
  themeSelect.value = local.read("theme", local.legacy("author-agent-theme", "system"));
  themeSelect.onchange = () => {
    local.write("theme", themeSelect.value);
    local.rememberLegacy("author-agent-theme", themeSelect.value);
    theme(themeSelect.value);
  };
  systemDark.addEventListener("change", () => { if (themeSelect.value === "system") theme("system"); });
  $("studio-density").value = local.read("density", "comfortable");
  function density() {
    main.dataset.density = $("studio-density").value;
    local.write("density", main.dataset.density);
  }
  $("studio-density").onchange = density;
  density();
  bindResize($("studio-split"), "width", true, 28, 72, event => {
    const bounds = scene.getBoundingClientRect();
    return 100 * (bounds.right - event.clientX) / bounds.width;
  });
  bindResize($("studio-output-split"), "output", false, 150, 550, event =>
    $("studio-output").getBoundingClientRect().bottom - event.clientY);
  window.addEventListener("pagehide", rememberPlace);
  $("studio-tree").addEventListener("scroll", schedulePlace);
  fallback.addEventListener("select", schedulePlace);
  fallback.addEventListener("scroll", schedulePlace);
  narrow.addEventListener("change", () => setLayout(state.layout, true));
  setLayout("chat");
  setSizes();
  paintTree();
  theme(themeSelect.value);
})();
