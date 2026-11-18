/* Conversation-first authoring UI (V0-V3).
 *
 * The transcript is the primary surface: the author types an idea, answers the
 * agent's question, pastes lemmas/tests/solutions and steers in the same box.
 * Structured cards, artifacts and received/applied state are rendered from the
 * durable ledger projection.  All text is escaped through textContent.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const panel = $("collab-panel");
  if (!panel) return;
  const studio = document.body.classList.contains("studio");
  const layout = document.querySelector("main.layout");
  if (layout && panel.parentElement !== layout) layout.append(panel);

  const STORAGE_KEY = "authorAgent.engineRun";
  const DRAFT_TITLE_KEY = "authorAgent.draftProblemTitle";
  const local = window.StudioLocal;
  const composer = $("collab-composer");
  const nameButton = $("studio-name-problem");
  function rememberedRun() {
    return studio ? local.read("conversation", local.legacy(STORAGE_KEY, ""), true) : localStorage.getItem(STORAGE_KEY);
  }
  let draftTitle = studio ? local.read("draft-title", local.legacy(DRAFT_TITLE_KEY, "", true), true) : "";
  const navigation = window.StudioNavigation;
  let currentRun = studio ? navigation.target().problem || rememberedRun() || "" : "";
  let view = null;
  let cursor = 0;
  let pollTimer = null;
  let busy = false;
  let defaultCapabilities = null;
  let optionsSignature = "";
  const providerPicker = $("studio-provider");
  const providerLabels = { custom: "Saved provider", "studio-sample": "Sample (scripted)", openrouter: "OpenRouter",
    opencode: "OpenCode Console", "opencode-go": "OpenCode Go" };
  let newPending = studio && local.read("new-problem", Boolean(draftTitle && !currentRun), true);
  let transcriptSignature = "";
  let transcriptRun = null;
  let transcriptTimer;
  let earlierRun = null, earlierMessages = [], earlierEvidence = {}, earlierBusy = false;
  let detailsSignature = "";
  let runsSignature = "";
  let refreshVersion = 0;
  let pollInFlight = false;
  const queuedMessages = [];
  const activeQueue = [];
  const requestReceipts = new Map();
  const draftPrefix = run => "composer:" + (run || "new") + ":";
  const draftKey = run => draftPrefix(run) + local.tab;

  function rememberRun(run) {
    if (studio) {
      local.write("conversation", run, true);
      local.write("new-problem", !run, true);
      local.rememberLegacy(STORAGE_KEY, run || null);
    } else if (run) localStorage.setItem(STORAGE_KEY, run);
    else localStorage.removeItem(STORAGE_KEY);
  }

  function storeComposer(run = currentRun) {
    local.write(draftKey(run), { text: composer.value, start: composer.selectionStart,
      end: composer.selectionEnd, time: Date.now() });
  }

  function restoreComposer(run) {
    const own = local.read(draftKey(run));
    const saved = own || (run ? local.entries(draftPrefix(run)).map(([, row]) => row)
      .sort((a, b) => b.time - a.time)[0] : null);
    composer.value = saved?.text || "";
    if (saved) composer.setSelectionRange(saved.start, saved.end);
    if (saved?.text) receipt("Draft recovered");
  }

  function uid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return "ui-" + Date.now() + "-" + Math.random().toString(16).slice(2);
  }

  async function api(path, options) {
    const init = Object.assign({ headers: {} }, options || {});
    if (init.body && typeof init.body !== "string") {
      init.body = JSON.stringify(init.body);
      init.headers["Content-Type"] = "application/json";
    }
    const response = await fetch(path, init);
    let data = null;
    try { data = await response.json(); } catch (_) { data = { error: "Non-JSON response" }; }
    if (!response.ok) {
      const error = new Error((data && (data.error || data.reason)) || "Request failed");
      error.status = response.status;
      error.data = data;
      throw error;
    }
    return data;
  }

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function receipt(text) {
    const node = $("collab-receipt");
    if (node) node.textContent = text || "";
  }

  const STATUS_LABELS = {
    waiting_human: "Waiting for your choice",
    awaiting_author: "Ready for you",
    waiting_worker: "Running a check",
    stage_returned: "Stage result ready",
    incomplete: "Incomplete",
    blocked: "Blocked",
    cancelled: "Cancelled",
    idle: "Idle",
    running: "Working",
    cancel_pending: "Stopping",
    error: "Needs attention",
  };

  function humanStatus(value) {
    const key = String(value || "idle").toLowerCase();
    return STATUS_LABELS[key] || String(value || "Idle");
  }

  function setStatus(value) {
    const pill = $("collab-status");
    if (!pill) return;
    const key = String(value || "idle").toLowerCase();
    if (pill.dataset.state === key) return;
    pill.textContent = humanStatus(value);
    pill.dataset.state = key;
    pill.className = "pill status-" + key.replace(/[^a-z_]/g, "");
  }

  function renderDisclosure(cap) {
    if (!cap) return;
    const node = $("collab-disclosure");
    node.textContent = "";
    const unconfigured = $("collab-unconfigured");
    const available = cap.modelConfigured || cap.demoMode;
    unconfigured.hidden = available;
    node.hidden = !available;
    const tag = document.querySelector("#collab-disclosure-details .desk-disclosure-tag");
    if (tag) tag.textContent = available ? (cap.demoMode ? "demo · simulated" : cap.model?.model || "configured") : "no model";
    if (!available) return;
    node.append(el("b", null, "Disclosure. "));
    const mode = cap.demoMode ? "an explicitly labelled demo model" : "the configured provider";
    const worker = cap.worker && cap.worker.real
      ? (cap.workerQualified ? "qualified isolated worker" : "isolated worker adapter (unqualified)")
      : "simulated worker (no C++ execution or containment)";
    node.append(document.createTextNode(
      "This conversation uses " + mode + " and a " + worker + ". "
      + "It exercises workflow mechanics; it is not autonomous judgment, compiled evidence or delivery approval. "
      + (cap.delivery && cap.delivery.supported ? "" : "Delivery, export and restore mutations are disabled in V0-V3.")
    ));
    if (cap.decisionModel) {
      const decision = cap.decisionModel;
      node.append(document.createTextNode(
        " Decision layer: " + (decision.identity || "unknown")
        + (decision.demo ? " (scripted demo)" : "")
        + "; schema " + (decision.schemaVersion || 1) + ", prompt " + (decision.promptVersion || "chat-decision-v1") + "."
      ));
    }
  }

  function showProvider(caps, runCaps = null) {
    if (!providerPicker) { renderDisclosure(runCaps || caps); return; }
    const options = [{ id: "custom" }, ...(caps.providers || [])];
    const bound = runCaps?.provider;
    if (bound && !options.some(item => item.id === bound)) options.push({ id: bound });
    const signature = options.map(item => item.id).join(",");
    if (signature !== optionsSignature) {
      optionsSignature = signature;
      providerPicker.replaceChildren(...options.map(item => new Option(providerLabels[item.id] || item.id, item.id)));
    }
    const preferred = local.legacy("authorAgent.provider");
    providerPicker.value = bound || (options.some(item => item.id === preferred) ? preferred : "custom");
    providerPicker.disabled = Boolean(runCaps);
    providerPicker.title = runCaps ? "Choose a provider when starting a new problem" : "Provider for this new conversation";
    const choice = caps.providers?.find(item => item.id === providerPicker.value);
    renderDisclosure(runCaps || (choice ? {
      ...caps, provider: choice.id, demoMode: false, modelConfigured: true,
      model: { model: choice.model }, decisionModel: null
    } : caps));
  }

  function renderRuns(runs) {
    const select = $("collab-run-select");
    const signature = JSON.stringify(runs.map(item => [item.runId, item.status, item.title, item.idea]));
    if (studio && signature === runsSignature) return;
    runsSignature = signature;
    select.textContent = "";
    const placeholder = el("option", null, runs.length ? "Select a conversation" : "No conversations yet");
    placeholder.value = "";
    select.append(placeholder);
    runs.forEach((run) => {
      const name = String(run.title || run.idea || run.runId || "");
      const option = el("option", null, humanStatus(run.status) + " · " + (studio ? name : name.slice(0, 54)));
      option.value = run.runId;
      select.append(option);
    });
    if (currentRun) select.value = currentRun;
  }

  function paintTitle(title) {
    if (!nameButton) return;
    const heading = $("studio-title");
    heading.textContent = title || "New problem";
    heading.title = title || "";
    nameButton.textContent = currentRun || title ? "Rename" : "Name";
    nameButton.setAttribute("aria-label", nameButton.textContent + " problem");
    nameButton.title = nameButton.textContent + " problem (F2)";
  }

  let titleRun, titleBasis, titlePreview, titleRequest = 0, titleTimer;
  async function previewTitle(reset = false) {
    const dialog = $("studio-title-dialog");
    const title = $("studio-title-input").value.trim();
    const impact = $("studio-title-impact");
    const request = ++titleRequest;
    titlePreview = null;
    if (!titleRun || !title) { impact.hidden = true; return; }
    impact.hidden = false;
    impact.textContent = "Checking the affected package…";
    try {
      const data = await api("/api/engine/runs/" + encodeURIComponent(titleRun) + "/title-preview", {
        method: "POST", body: { title },
      });
      if (!dialog.open || request !== titleRequest) return;
      if (titleBasis && !reset && JSON.stringify(titleBasis) !== JSON.stringify(data.basis)) {
        impact.textContent = "The saved title or package changed. Refresh the preview to see the current names.";
        $("studio-title-refresh").hidden = false;
        return;
      }
      titleBasis = data.basis;
      titlePreview = { title, data };
      $("studio-title-refresh").hidden = true;
      const name = titleBasis.expectedTitle || "Untitled problem";
      const changes = data.files?.length ? " Updates " + data.files.join(", ") + "." : "";
      impact.textContent = data.syncBlocked || (data.separate ? 'Package keeps its name “' + data.packageTitle + '”.' :
        data.packageTitle ? 'Current problem title: “' + name + '”. Package: “' + data.packageTitle + '”.' + changes +
          (data.statementSupported === false ? " Check the statement title manually." : "") +
          " ZIP: " + data.filename + "." +
          (data.requiresVerification ? " Verify and approve the new version before exporting." : "") :
          'Current title: “' + name + '”.');
    } catch (error) {
      if (request !== titleRequest) return;
      impact.textContent = error.message;
      $("studio-title-refresh").hidden = false;
    }
  }

  nameButton?.addEventListener("click", () => {
    const dialog = $("studio-title-dialog");
    const input = $("studio-title-input");
    $("studio-title-dialog-heading").textContent = nameButton.textContent + " problem";
    const heading = $("studio-title");
    input.value = currentRun ? heading.title.slice(0, input.maxLength) : draftTitle;
    titleRun = currentRun;
    titleBasis = titlePreview = null;
    $("studio-title-error").textContent = "";
    $("studio-title-refresh").hidden = true;
    dialog.showModal();
    input.select();
    previewTitle(true);
  });

  $("studio-title-refresh")?.addEventListener("click", () => {
    $("studio-title-error").textContent = "";
    previewTitle(true);
    $("studio-title-input").focus();
  });
  $("studio-title-input")?.addEventListener("input", () => {
    clearTimeout(titleTimer);
    titleTimer = setTimeout(previewTitle, 160);
  });
  document.addEventListener("keydown", (event) => {
    if (!studio || event.key !== "F2" || event.isComposing || nameButton.disabled ||
        document.querySelector("dialog[open]") || event.target.closest("input, textarea, select, [contenteditable], .monaco-editor")) return;
    event.preventDefault();
    nameButton.click();
  });

  $("studio-title-dialog")?.addEventListener("cancel", (event) => {
    if (event.currentTarget.querySelector("button[type=submit]").disabled) event.preventDefault();
  });

  $("studio-title-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const dialog = $("studio-title-dialog");
    const title = $("studio-title-input").value.trim();
    const errorText = $("studio-title-error");
    if (!title) { errorText.textContent = "Enter a problem title."; return; }
    const buttons = [...dialog.querySelectorAll("button")];
    buttons.forEach(button => { button.disabled = true; });
    try {
      if (titleRun !== currentRun) throw new Error("The active problem changed. Open Rename again.");
      if (currentRun) {
        if (!titlePreview || titlePreview.title !== title) await previewTitle();
        if (titlePreview?.title !== title || titlePreview.data.syncBlocked) {
          throw new Error("Review the current title and package preview before saving.");
        }
        const result = await api("/api/engine/runs/" + encodeURIComponent(titleRun) + "/title", {
          method: "POST", body: { title, ...titlePreview.data.basis },
        });
        paintTitle(result.title);
        receipt("Title saved. " + (titlePreview.data.requiresVerification ? "Verify the new package version before exporting." : ""));
        refresh();
      } else {
        draftTitle = title;
        local.write("draft-title", title, true);
        local.rememberLegacy(DRAFT_TITLE_KEY, null, true);
        newPending = true;
        rememberRun("");
        paintTitle(title);
        receipt("Draft title saved");
      }
      dialog.close();
    } catch (error) {
      errorText.textContent = error.message;
      if (error.status === 409) $("studio-title-refresh").hidden = false;
    } finally {
      buttons.forEach(button => { button.disabled = false; });
    }
  });

  function stateClass(value) {
    return "state " + String(value || "").replace(/[^a-z_]/g, "");
  }

  function artifactById(id) {
    return ((view && view.artifacts) || []).find((item) => item.id === id) || null;
  }

  async function openArtifact(id) {
    if (!currentRun) return;
    try {
      const runId = currentRun;
      const artifact = await api("/api/engine/runs/" + encodeURIComponent(runId)
        + "/artifacts/" + encodeURIComponent(id));
      if (runId !== currentRun) return;
      if (studio) {
        window.dispatchEvent(new CustomEvent("studio-artifact", { detail: { runId, artifact } }));
        return;
      }
      const box = $("collab-artifact-body");
      box.hidden = false;
      box.textContent = "# " + artifact.path + " · " + artifact.kind + " · " + artifact.id + "\n\n" + artifact.text;
      const section = $("collab-artifacts-section");
      if (section) section.open = true;
      box.scrollIntoView({ block: "nearest" });
    } catch (error) {
      receipt(error.message);
    }
  }

  function renderDecisionCard(message) {
    const decision = view && view.pendingDecision;
    if (!decision || decision.id !== message.interaction_id) return null;
    const card = el("div", "card-options");
    if (studio && decision.kind === "semantics") {
      const scope = new Set((view.artifacts || []).filter(artifact => artifact.current).map(artifact => artifact.kind));
      const affected = [["spec", "statement and legal inputs"], ["proof", "compatibility proof"],
        ["editorial", "editorial"], ["test", "case expectations"], ["solution", "reference and candidate code"]]
        .map(([kind, label]) => label + (scope.has(kind) ? " (draft exists)" : ""));
      card.append(el("p", "muted", "Changing the endpoint rule requires rechecking the " + affected.join(", ") +
        ". Saved package files remain available for manual review."));
    }
    (decision.evidenceBlocks || []).forEach((block) => {
      card.append(el("pre", "collab-diff", block.text + (block.truncated ? "\n… (truncated)" : "")));
    });
    (decision.options || []).forEach((option) => {
      const button = el("button", "collab-option");
      button.type = "button";
      button.append(el("b", null, option.label || option.id));
      if (option.consequence) button.append(el("span", "muted", option.consequence));
      button.addEventListener("click", () => {
        const id = String(option.id || "");
        if (decision.kind === "semantics") {
          sendMessage(option.label || id, null, false, decision.id);
        } else if (id === "read_only" || id === "reject" || id === "deny") {
          sendMessage("Reject that. Keep it read-only for now.", null, false, decision.id);
        } else if (id === "defer") {
          sendMessage("Defer this for now.", null, false, decision.id);
        } else {
          sendMessage("Approve the proposed change.", null, false, decision.id);
        }
      });
      card.append(button);
    });
    const why = el("div", "muted small");
    why.textContent = (decision.recommendation ? "Recommendation: " + decision.recommendation + ". " : "")
      + "Or answer in your own words below.";
    card.append(why);
    return card;
  }

  const witnessRequests = new Map();
  const mutationRequests = new Map();

  function mutationControls(runId, campaignId) {
    const controls = el("div", "studio-evidence-actions");
    const status = el("span", "muted");
    status.setAttribute("role", "status");
    const extras = (view?.artifacts || []).filter(item => item.current && ["current", "revalidated"].includes(item.validity) &&
      ["solution", "negative"].includes(item.kind) && item.path.endsWith(".cpp"));
    const choices = [];
    if (extras.length) {
      const targets = el("details", "studio-mutant-options");
      targets.append(el("summary", null, "Include up to two authored mutants"));
      for (const artifact of extras) {
        const option = el("input");
        option.type = "checkbox";
        option.value = artifact.id;
        const label = el("label");
        label.append(option, document.createTextNode(" " + artifact.path));
        choices.push(option);
        targets.append(label);
      }
      controls.append(targets);
    }
    const button = el("button", "quiet", "Run mutation matrix");
    button.type = "button";
    const key = `${runId}:${campaignId}`;
    button.disabled = mutationRequests.get(key)?.running || false;
    button.onclick = async () => {
      if (mutationRequests.get(key)?.running) return;
      const mutantRefs = choices.filter(option => option.checked).map(option => option.value);
      if (mutantRefs.length > 2) {
        status.textContent = "Choose at most two authored mutants.";
        return;
      }
      const selection = JSON.stringify(mutantRefs);
      const saved = mutationRequests.get(key);
      const request = saved?.selection === selection ? saved : { id: uid(), selection };
      request.running = true;
      button.disabled = true;
      choices.forEach(option => { option.disabled = true; });
      mutationRequests.set(key, request);
      status.textContent = "Checking the control and mutants…";
      try {
        const result = await api(`/api/engine/runs/${encodeURIComponent(runId)}/mutation-matrices/${encodeURIComponent(campaignId)}`, {
          method: "POST", body: { clientRequestId: request.id, mutantRefs },
        });
        mutationRequests.delete(key);
        status.textContent = result.freshness === "stale" ? "The matrix is earlier evidence." : "Result saved in chat.";
        await refresh();
      } catch (error) {
        if (error.status && error.status < 500) mutationRequests.delete(key);
        status.textContent = error.message;
      } finally {
        request.running = false;
        button.disabled = false;
        choices.forEach(option => { option.disabled = false; });
      }
    };
    controls.append(button, status);
    return controls;
  }

  function renderMutationMatrix(item, runId) {
    const matrix = item.matrix;
    const statuses = { killed: "Caught", matched: "Matched", survived: "Survived", compile_error: "Compile error",
      worker_failure: "Worker failure", not_run: "Not run", unresolved: "Unresolved", control_passed: "Control passed",
      control_partial: "Control passed on checked tests", control_failed: "Control failed", control_mismatch: "Control mismatch",
      invalid_output: "Invalid output", candidate_runtime_error: "Runtime error", time_limit: "Time limit",
      memory_limit: "Memory limit", output_limit: "Output limit" };
    const card = el("section", "studio-case-card studio-mutation-card");
    const worker = matrix.worker?.includes("simulation") ? "Simulated worker" : matrix.worker ? "Worker receipt" : "No worker receipt";
    card.append(el("b", null, "Test-by-mutant matrix"), el("p", "muted",
      `${matrix.qualifiedTests} of ${matrix.tests.length} saved tests qualified · ${matrix.semantics.replace('_', '-')} · ` +
      (item.historical ? "Earlier evidence" : matrix.termination.replaceAll('_', ' ')) + ` · ${worker}`));
    const scroll = el("div", "studio-mutation-scroll");
    scroll.tabIndex = 0;
    scroll.setAttribute("role", "region");
    scroll.setAttribute("aria-label", "Scrollable mutation results");
    const table = el("table", "studio-mutation-table");
    table.createCaption().textContent = "Per-test expected and observed outcomes";
    const head = table.createTHead().insertRow();
    for (const [label, outcome] of [["Test", null], ["Expected", null], ...matrix.columns.map(column => [column.label, column.status])]) {
      const cell = el("th", null, label);
      cell.scope = "col";
      if (outcome) cell.append(el("div", "muted small", statuses[outcome]));
      head.append(cell);
    }
    const body = table.createTBody();
    matrix.tests.forEach((test, index) => {
      const row = body.insertRow();
      const label = el("th", null, test.case_id);
      label.scope = "row";
      const input = el("details");
      input.append(el("summary", null, "Input"), el("pre", null, test.input));
      label.append(input);
      row.append(label, el("td", null, test.expected));
      for (const column of matrix.columns) {
        const check = column.cells[index];
        const cell = el("td", null, statuses[check.status] + (check.actual === null ? "" : ` · ${check.actual}`));
        cell.dataset.status = check.status;
        if (check.detail) cell.append(el("div", "muted small", check.detail.replaceAll('_', ' ')));
        row.append(cell);
      }
    });
    const report = el("a", "artifact-link quiet small", "Open matrix report");
    report.href = `/api/engine/runs/${encodeURIComponent(runId)}/mutation-matrices/${encodeURIComponent(item.reportId)}`;
    report.target = "_blank";
    report.rel = "noopener";
    scroll.append(table);
    card.append(scroll, report);
    return card;
  }

  function renderCaseCard(evidence, runId) {
    const card = el("section", "studio-case-card");
    const simulated = /simulat|fake/i.test(evidence.worker || "");
    const title = evidence.title || (evidence.classification === "shared_semantics_defect" ? "Shared assumption under review" :
      ["counterexample", "wrong_answer"].includes(evidence.classification) ? "Counterexample" : "Case evidence");
    card.append(el("b", null, title));
    card.append(el("p", "muted", (simulated ? "Simulated worker" : evidence.worker ? "Worker receipt" : "Worker source unrecorded") +
      (evidence.historical ? " · earlier evidence" : "") + " · " + evidence.id));
    if (evidence.claim) card.append(el("p", null, "Claim · " + evidence.claim));
    if (evidence.effect) card.append(el("p", null, evidence.effect));
    const facts = el("dl", "studio-case-facts");
    for (const [label, value] of [["Expected", evidence.expected], ["Actual", evidence.actual]]) {
      facts.append(el("dt", null, label), el("dd", null, value === "" ? "(empty output)" : value ?? "Not recorded"));
    }
    card.append(facts);
    if (evidence.input) {
      card.append(el("p", "muted", evidence.legal ? "Legal input for this receipt" : "Recorded input"), el("pre", null, evidence.input));
      const actions = el("div", "studio-evidence-actions");
      const copy = el("button", "quiet", "Copy input");
      copy.type = "button";
      const status = el("span", "muted");
      status.setAttribute("role", "status");
      copy.onclick = async () => {
        try { await navigator.clipboard.writeText(evidence.input); status.textContent = "Input copied."; }
        catch { status.textContent = "Clipboard unavailable. Select the input text to copy it."; }
      };
      const run = el("button", "quiet", "Run this case");
      run.type = "button";
      run.onclick = () => window.dispatchEvent(new CustomEvent("studio-run-witness", { detail: { runId, card: evidence } }));
      actions.append(copy, run);
      if (evidence.replayable && !evidence.historical) {
        const prefix = `${runId}:${evidence.id}:`;
        const buttons = [];
        const isRunning = () => ["replay", "reduce"].some(action => witnessRequests.get(prefix + action)?.running);
        for (const [action, label] of [["replay", "Replay original"], ["reduce", "Replay and reduce"]]) {
          const check = el("button", "quiet", label);
          check.type = "button";
          check.disabled = isRunning();
          check.onclick = async () => {
            if (isRunning()) return;
            const key = prefix + action;
            const request = witnessRequests.get(key) || { id: uid() };
            request.running = true;
            witnessRequests.set(key, request);
            buttons.forEach(button => { button.disabled = true; });
            status.textContent = action === "reduce" ? "Replaying and checking smaller inputs…" : "Replaying the saved input…";
            try {
              const result = await api(`/api/engine/runs/${encodeURIComponent(runId)}/counterexamples/${encodeURIComponent(evidence.id)}`, {
                method: "POST", body: { action, clientRequestId: request.id },
              });
              witnessRequests.delete(key);
              status.textContent = result.freshness === "stale" ? "The check is earlier evidence." : "Result saved in chat.";
              await refresh();
            } catch (error) {
              if (error.status && error.status < 500) witnessRequests.delete(key);
              status.textContent = error.message;
            } finally {
              request.running = false;
              buttons.forEach(button => { button.disabled = false; });
            }
          };
          buttons.push(check);
          actions.append(check);
        }
      }
      actions.append(status);
      card.append(actions);
    }
    const details = el("details");
    details.append(el("summary", null, "Diagnostics and source"));
    const raw = [evidence.comparison, evidence.assumption, evidence.candidate && "Candidate or case · " + evidence.candidate,
      evidence.sourceHash && "Source SHA-256 · " + evidence.sourceHash, evidence.worker,
      ...evidence.diagnostics.map(span => `${span.line || span.start || ""} ${span.text || ""}`)].filter(Boolean);
    details.append(el("pre", null, raw.join("\n") || "No further details recorded."));
    card.append(details);
    return card;
  }

  function renderTranscript(messages) {
    const transcript = $("collab-transcript");
    if (studio) {
      if (earlierRun !== currentRun) { earlierRun = currentRun; earlierMessages = []; earlierEvidence = {}; }
      messages = [...earlierMessages.filter(item => item.seq < (messages?.[0]?.seq || 0)), ...(messages || [])];
      $("studio-chat-earlier").hidden = !messages.length || messages[0].seq <= 1;
    }
    const inputStatuses = new Map((view?.inputs || []).map(item => [item.id, item.status]));
    const decisions = view?.collaboration?.decisions || [];
    const evidence = { ...earlierEvidence, ...(view?.evidenceCards || {}) };
    const signature = JSON.stringify([currentRun, messages, view?.pendingDecision, [...inputStatuses], requestReceipts.size,
      evidence, decisions, view?.mutationCampaigns, view?.artifacts?.map(artifact => [artifact.id, artifact.path, artifact.kind, artifact.current, artifact.validity])]);
    if (studio && signature === transcriptSignature) return;
    transcriptSignature = signature;
    const sameRun = transcriptRun === currentRun;
    const restored = studio && !sameRun
      ? local.read("transcript:" + local.tab + ":" + currentRun) : null;
    transcriptRun = currentRun;
    const previousScroll = transcript.scrollTop;
    const follow = !studio || transcript.scrollHeight - previousScroll - transcript.clientHeight < 80;
    if (!studio || !sameRun) transcript.textContent = "";
    if (!currentRun) {
      const empty = el("div", "desk-empty");
      empty.append(el("div", "desk-empty-kicker", "Start here"));
      empty.append(el("h3", null, "What problem are you setting?"));
      empty.append(el("p", null,
        studio ? "Start with an interval or scheduling idea. Develop the rules, proof, and tests in chat, or open a package for manual work."
          : "Describe an incomplete idea in a sentence. The desk will frame it, ask only the questions that change the work, and keep the statement, solution, tests and evidence together."));
      empty.append(el("p", "desk-examples-label", "Example starting points"));
      const examples = el("div", "desk-empty-examples");
      [
        "A booking problem with start and finish times and a reward for each job.",
        "Help me turn a rough interval idea into a proof and a test plan.",
      ].forEach((text) => {
        const button = el("button", "desk-example", text);
        button.type = "button";
        button.addEventListener("click", () => {
          if (composer) {
            composer.value = studio ? [composer.value, text].filter(Boolean).join("\n\n") : text;
            if (studio) storeComposer();
            composer.focus();
          }
        });
        examples.append(button);
      });
      empty.append(examples);
      if (studio) {
        const sample = el("button", "desk-example", "Try Canal Bookings sample");
        sample.type = "button";
        sample.onclick = () => window.dispatchEvent(new Event("studio-open-sample"));
        empty.append(sample);
      }
      empty.append(el("p", "desk-empty-note", "No files or fixture names needed. The desk manages the internal run."));
      transcript.replaceChildren(empty);
      if (studio) $("studio-jump-latest").hidden = true;
      return;
    }
    if (!messages || !messages.length) {
      transcript.replaceChildren(el("p", "muted", "The conversation is ready. Your first message starts the work."));
      return;
    }
    function makeMessage(message) {
      const role = message.role === "author" ? "author" : "agent";
      const kind = String(message.kind || "message");
      const node = el("div", "collab-msg " + role + " " + kind);
      node.dataset.seq = message.seq;
      node.dataset.kind = kind;
      node.append(el("span", "who", role === "author" ? "You" : "Agent · " + kind));
      const body = el("div", "body");
      let displayText = message.text || "";
      if (kind === "decision") {
        displayText = displayText.split(/\n\nOptions:/)[0];
      }
      body.textContent = displayText;
      node.append(body);
      if (kind === "campaign" && /^campaign:ev-[a-f0-9]{14}$/.test(message.dedupe_key)) {
        const link = el("a", "artifact-link quiet small", "Open campaign report");
        link.href = `/api/engine/runs/${encodeURIComponent(currentRun)}/campaigns/${message.dedupe_key.slice(9)}`;
        link.target = "_blank";
        link.rel = "noopener";
        const line = el("p", "small");
        line.append(link);
        body.append(line);
        const campaignId = message.dedupe_key.slice(9);
        if (studio && view?.mutationCampaigns?.includes(campaignId)) body.append(mutationControls(currentRun, campaignId));
      }
      if (studio && evidence[message.dedupe_key]) {
        const item = evidence[message.dedupe_key];
        if (item.matrix) body.append(renderMutationMatrix(item, currentRun));
        else if (item.versions) {
          for (const version of item.versions) body.append(renderCaseCard(version, currentRun));
          const link = el("a", "artifact-link quiet small", "Open counterexample report");
          link.href = `/api/engine/runs/${encodeURIComponent(currentRun)}/counterexamples/${encodeURIComponent(item.reportId)}`;
          link.target = "_blank";
          link.rel = "noopener";
          body.append(link);
        } else body.append(renderCaseCard(item, currentRun));
      }
      if (studio && role === "author") {
        const sent = requestReceipts.get(message.id);
        const appliedChoice = message.response_id && local.read("choice:" + currentRun + ":" + message.id);
        const status = inputStatuses.get(message.input_id);
        const label = sent || appliedChoice ? describeReceipt(sent || { choiceApplied: true })
          : message.response_id ? "Answer received" : status ? describeReceipt({ status }) : "";
        if (label) node.append(el("span", "muted small", label));
        for (const decision of decisions.filter(item => (item.sourceId === message.input_id || item.sourceId === message.response_id) &&
            item.requirementId === "endpoint_semantics")) {
          node.append(el("p", "muted small", `Endpoint rule applied · ${decision.optionId} · ${decision.id} · generation ${decision.generation}`));
        }
      }
      if (kind === "artifact") {
        const ids = message.artifact_ids || [];
        const links = el("div");
        ids.forEach((id) => {
          const artifact = artifactById(id);
          const link = el("button", "artifact-link quiet small", artifact ? artifact.path : id);
          link.type = "button";
          link.addEventListener("click", () => openArtifact(id));
          links.append(link);
        });
        body.append(links);
      }
      if (kind === "decision") {
        const card = renderDecisionCard(message);
        if (card) body.append(card);
      }
      if (kind === "recovery" && (message.artifact_ids || []).length) {
        const recoveryId = message.artifact_ids[0];
        const failed = messages.find((item) => item.role === "author"
          && item.input_id === recoveryId);
        if (failed) {
          const retry = el("button", "collab-option", "Retry this request");
          retry.type = "button";
          retry.addEventListener("click", () => sendMessage(failed.text, recoveryId));
          body.append(retry);
        }
      }
      return node;
    }
    if (!studio) {
      transcript.append(...messages.map(makeMessage));
    } else {
      const groups = [];
      for (const message of messages) {
        const previous = groups.at(-1);
        if (message.kind === "artifact" && previous?.[0].kind === "artifact") previous.push(message);
        else groups.push([message]);
      }
      const before = [...transcript.children];
      const byKey = new Map(before.filter(item => item.dataset.messageKey).map(item => [item.dataset.messageKey, item]));
      const top = transcript.getBoundingClientRect().top;
      const anchor = !follow && before.find(item => item.getBoundingClientRect().bottom > top);
      const anchorOffset = anchor && anchor.getBoundingClientRect().top - top;
      const focused = transcript.contains(document.activeElement) ? document.activeElement : null;
      const focusedRow = focused?.closest("[data-message-key]");
      const content = groups.map(group => {
        const first = group[0];
        const key = first.id || String(first.seq);
        const prior = byKey.get(key);
        const fingerprint = JSON.stringify([group, inputStatuses.get(first.input_id),
          first.kind === "decision" && [view?.pendingDecision, view?.artifacts?.map(artifact => [artifact.kind, artifact.current])],
          evidence[first.dedupe_key], decisions.filter(item => item.sourceId === first.input_id || item.sourceId === first.response_id),
          requestReceipts.get(first.id),
          group.flatMap(item => (item.artifact_ids || []).map(id => artifactById(id)?.path))]);
        if (prior?.dataset.fingerprint === fingerprint) return prior;
        let row;
        if (group.length === 1) row = makeMessage(first);
        else {
          row = el("div", "collab-msg agent artifact");
          row.dataset.seq = first.seq;
          row.append(el("span", "who", "Workspace"));
          const box = el("div", "body studio-artifact-summary");
          const ids = [...new Set(group.flatMap(message => message.artifact_ids || []))];
          box.append(el("p", null, ids.length + " artifacts updated"));
          const links = el("div", "studio-artifact-links");
          for (const id of ids) {
            const artifact = artifactById(id);
            const link = el("button", "artifact-link", artifact?.path || id);
            link.type = "button";
            link.onclick = () => openArtifact(id);
            links.append(link);
          }
          const history = el("details");
          history.open = Boolean(prior?.querySelector("details")?.open);
          history.append(el("summary", null, "Update history"));
          for (const message of group) history.append(el("p", null, message.text));
          box.append(links, history);
          row.append(box);
        }
        row.dataset.messageKey = key;
        row.dataset.fingerprint = fingerprint;
        return row;
      });
      const keep = new Set(content);
      for (const existing of before) if (!keep.has(existing)) existing.remove();
      for (const [index, row] of content.entries()) {
        const at = transcript.children[index];
        if (at !== row) transcript.insertBefore(row, at || null);
      }
      if (focusedRow && !focused.isConnected) {
        const replacement = content.find(item => item.dataset.messageKey === focusedRow.dataset.messageKey);
        const match = [...(replacement?.querySelectorAll("button, summary") || [])]
          .find(item => item.textContent === focused.textContent);
        if (match) match.focus({ preventScroll: true });
        else composer.focus({ preventScroll: true });
      }
      if (anchor) {
        const item = content.find(row => row.dataset.messageKey === anchor.dataset.messageKey);
        if (item) {
          transcript.scrollTop += item.getBoundingClientRect().top - top - anchorOffset;
          updateLatestControl();
          return;
        }
      }
    }
    transcript.scrollTop = restored ? (restored.follow ? transcript.scrollHeight : restored.top)
      : (follow ? transcript.scrollHeight : previousScroll);
    if (studio) updateLatestControl();
  }

  async function loadEarlier() {
    if (earlierBusy || !currentRun) return;
    const before = earlierMessages[0]?.seq || view?.chatMessages?.[0]?.seq;
    if (!before || before <= 1) return;
    const runId = currentRun;
    const button = $("studio-chat-earlier");
    const transcript = $("collab-transcript");
    const at = transcript.querySelector("[data-message-key]");
    earlierBusy = button.disabled = true;
    try {
      const page = await api(`/api/engine/runs/${encodeURIComponent(runId)}/chat?before=${before}`);
      if (runId !== currentRun || earlierRun !== runId) return;
      addHistory(page);
      renderTranscript(view.chatMessages);
      if (at?.isConnected) at.scrollIntoView({ block: "nearest" });
      if (button.hidden) {
        transcript.tabIndex = -1;
        transcript.focus({ preventScroll: true });
      }
      rememberTranscript();
    } catch (error) {
      receipt("Earlier messages could not be loaded. " + error.message);
    } finally { earlierBusy = button.disabled = false; }
  }
  $("studio-chat-earlier")?.addEventListener("click", loadEarlier);

  function addHistory(page) {
    earlierMessages = [...page.messages, ...earlierMessages];
    Object.assign(earlierEvidence, Object.fromEntries(Object.entries(page.evidenceCards || {}).map(([key, card]) =>
      [key, { ...card, historical: true }])));
  }

  async function restoreTranscriptPages(runId, result, version) {
    if (earlierRun === runId) {
      if (!earlierMessages.length || view?.runId !== runId) return;
      const first = result.chatMessages[0]?.seq;
      const rolledOff = view.chatMessages.filter(item => item.seq < first);
      if (rolledOff.length) {
        earlierMessages.push(...rolledOff);
        for (const message of rolledOff) {
          const card = view.evidenceCards?.[message.dedupe_key];
          if (card) earlierEvidence[message.dedupe_key] = { ...card, historical: true };
        }
      }
      return;
    }
    const place = local.read("transcript:" + local.tab + ":" + runId);
    const pages = [];
    let before = result.chatMessages[0]?.seq;
    while (!place?.follow && before > (place?.firstSeq || before) && pages.length < 5) {
      const page = await api(`/api/engine/runs/${encodeURIComponent(runId)}/chat?before=${before}`).catch(() => null);
      if (version !== refreshVersion) return;
      if (!page?.messages.length) break;
      pages.push(page);
      before = page.messages[0].seq;
    }
    earlierRun = runId;
    earlierMessages = [];
    earlierEvidence = {};
    for (const page of pages) addHistory(page);
  }

  function updateLatestControl() {
    const transcript = $("collab-transcript");
    $("studio-jump-latest").hidden = !currentRun ||
      transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 80;
  }

  function rememberTranscript() {
    if (!transcriptRun || transcriptRun !== currentRun) return;
    const transcript = $("collab-transcript");
    local.write("transcript:" + local.tab + ":" + currentRun, { top: transcript.scrollTop,
      firstSeq: Number(transcript.querySelector("[data-seq]")?.dataset.seq) || null,
      follow: transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 80 });
  }

  function renderArtifacts(items) {
    const list = $("collab-artifacts");
    list.textContent = "";
    (items || []).slice().sort((a, b) => (Number(b.current) - Number(a.current))
      || String(a.path).localeCompare(String(b.path))).forEach((artifact) => {
      const li = el("li");
      li.append(el("span", "muted", artifact.kind));
      const link = el("button", "artifact-link quiet small", artifact.path);
      link.type = "button";
      link.addEventListener("click", () => openArtifact(artifact.id));
      li.append(link);
      const status = (artifact.validity === "stale" || artifact.validity === "unresolved")
        ? artifact.validity : (artifact.current ? "current" : "superseded");
      const state = el("span", "state " + (status === "current" ? "applied"
        : status === "superseded" ? "superseded" : "unverified"), status);
      if (artifact.validityReason) state.title = artifact.validityReason;
      li.append(state);
      list.append(li);
    });
    if (!list.children.length) {
      list.append(el("li", "muted", "Artifacts appear automatically as the conversation develops."));
    }
  }

  function renderInputs(inputs) {
    const list = $("collab-inputs");
    list.textContent = "";
    (inputs || []).slice().reverse().forEach((item) => {
      const li = el("li");
      li.append(el("span", "seq muted", "#" + item.seq));
      li.append(el("span", "txt", item.kind + (item.barrier ? " · fenced" : "") + " · " + (item.text || "")));
      li.append(el("span", stateClass(item.status), item.status));
      list.append(li);
    });
    if (!list.children.length) list.append(el("li", "muted", "No author inputs yet."));
  }

  function renderContributions(items) {
    const list = $("collab-contributions");
    list.textContent = "";
    (items || []).forEach((item) => {
      const li = el("li");
      li.append(el("span", "muted", item.kind));
      li.append(el("span", "txt", item.attribution || item.actorKind + " contribution"));
      li.append(el("span", "state", item.validationStatus));
      list.append(li);
    });
    if (!list.children.length) {
      list.append(el("li", "muted", "No contributions yet. Originals remain immutable and attributed."));
    }
  }

  function renderEvidence() {
    const box = $("collab-evidence");
    box.textContent = "";
    if (!view) return;
    const explanation = view.currentExplanation;
    if (explanation) {
      box.append(el("h4", null, "Current explanation · " + explanation.audience_depth));
      box.append(el("p", null, explanation.short_answer));
      if (explanation.worked_example_ref) {
        box.append(el("div", "witness", explanation.worked_example_ref));
      }
      if (explanation.assumption_to_code_links && explanation.assumption_to_code_links.length) {
        const list = el("div");
        explanation.assumption_to_code_links.forEach((link) => {
          list.append(el("div", "muted small",
            "Assumption: " + (link.assumption || "") + " → " + (link.code_ref || "") + " " + (link.line_span || "")));
        });
        box.append(list);
      }
      if (explanation.uncertainty && explanation.uncertainty.length) {
        box.append(el("h4", null, "Remaining uncertainty"));
        const ul = el("ul", "collab-list");
        explanation.uncertainty.forEach((value) => ul.append(el("li", null, value)));
        box.append(ul);
      }
      if (explanation.next_author_actions && explanation.next_author_actions.length) {
        box.append(el("h4", null, "Next author actions"));
        const ul = el("ul", "collab-list");
        explanation.next_author_actions.forEach((value) => ul.append(el("li", null, value)));
        box.append(ul);
      }
    } else {
      box.append(el("p", "muted", "No current explanation. Evidence is attached only after a validated receipt."));
    }
    const budget = view.budget || {};
    box.append(el("p", "muted small",
      "Model attempts " + (budget.modelAttemptsUsed || 0) + "/" + (budget.modelAttemptsLimit || 0)
      + " · cases " + (budget.casesUsed || 0) + " · unknown usage: " + (budget.unknownUsage ? "yes" : "no")));
    if (view.delivery && !view.delivery.supported) {
      box.append(el("p", "muted small", "Delivery/export: unsupported in V0-V3. " + (view.delivery.reason || "")));
    }
    if (view.restoreMutations && !view.restoreMutations.supported) {
      box.append(el("p", "muted small", "Restore mutations: disabled. Current-session resume only."));
    }
  }

  function renderHandoff() {
    const box = $("collab-handoff");
    box.textContent = "";
    const handoff = view && view.handoff;
    if (!handoff) {
      box.append(el("p", "muted", "No stage handoff yet."));
      return;
    }
    if (view.delegations && view.delegations.length) {
      const delegation = view.delegations[view.delegations.length - 1];
      box.append(el("h4", null, "Stage scope · " + delegation.status));
      box.append(el("p", "muted small",
        "Return: " + delegation.returnKind
        + " · allowed: " + (delegation.permittedOperations || []).join(", ")
        + " · excluded: " + (delegation.exclusions || []).join(", ")));
    }
    box.append(el("h4", null, "Outcome: " + handoff.outcome));
    if (handoff.stage_return) {
      box.append(el("p", null,
        "Typed return " + handoff.stage_return.contract.kind + " · satisfied: " + (handoff.stage_return.satisfied ? "yes" : "no")
        + (handoff.stage_return.reason ? " · " + handoff.stage_return.reason : "")));
    }
    if (handoff.decisions && handoff.decisions.length) {
      box.append(el("h4", null, "Decisions"));
      const ul = el("ul", "collab-list");
      handoff.decisions.forEach((d) => ul.append(el("li", null,
        (d.requirementId || "") + " = " + (d.optionId || d.definitionText || "") + " (generation " + d.generation + ")")));
      box.append(ul);
    }
    if (handoff.contributions && handoff.contributions.length) {
      box.append(el("h4", null, "Contributions preserved"));
      const ul = el("ul", "collab-list");
      handoff.contributions.forEach((c) => ul.append(el("li", null,
        c.kind + " · " + (c.attribution || "") + " · " + c.validation)));
      box.append(ul);
    }
    if (handoff.open_questions && handoff.open_questions.length) {
      box.append(el("h4", null, "Open questions"));
      const ul = el("ul", "collab-list");
      handoff.open_questions.forEach((q) => ul.append(el("li", null, q)));
      box.append(ul);
    }
    if (handoff.next_actions && handoff.next_actions.length) {
      box.append(el("h4", null, "Next useful work"));
      const ul = el("ul", "collab-list");
      handoff.next_actions.forEach((a) => ul.append(el("li", null, a)));
      box.append(ul);
    }
    if (handoff.invalidations && handoff.invalidations.length) {
      box.append(el("p", "muted small", "Stale evidence retained historically: " + handoff.invalidations.length));
    }
  }

  async function refresh() {
    const version = ++refreshVersion;
    try {
      const [caps, runs] = await Promise.all([api("/api/engine/capabilities"), api("/api/engine/runs")]);
      if (version !== refreshVersion) return;
      defaultCapabilities = caps;
      renderRuns(runs.runs || []);
      if (studio && currentRun && !runs.runs?.some(run => run.runId === currentRun)) {
        if (navigation.target().problem) {
          history.replaceState(null, "", navigation.address({}));
          receipt("That problem is unavailable.");
        }
        currentRun = "";
        newPending = true;
        rememberRun("");
        restoreComposer("");
      }
      if (!currentRun && runs.runs && runs.runs.length && !newPending) {
        const saved = rememberedRun();
        const match = saved && runs.runs.some((run) => run.runId === saved);
        currentRun = match ? saved : runs.runs[runs.runs.length - 1].runId;
        $("collab-run-select").value = currentRun;
        rememberRun(currentRun);
        if (studio) restoreComposer(currentRun);
      }
      if (studio) {
        const selected = (runs.runs || []).find(run => run.runId === currentRun);
        if (selected && !location.hash) history.replaceState(null, "", navigation.address({ problem: currentRun }));
        paintTitle(currentRun ? selected?.title || selected?.idea?.trim().split("\n")[0].slice(0, 100) : draftTitle);
      }
      if (currentRun) {
        const result = await api("/api/engine/runs/" + encodeURIComponent(currentRun) + "/view" + (studio ? "?studio=1" : ""));
        if (version !== refreshVersion) return;
        if (studio) {
          await restoreTranscriptPages(currentRun, result, version);
          if (version !== refreshVersion) return;
        }
        view = result;
        showProvider(caps, view.capabilities || caps);
        setStatus(view.status);
        renderTranscript(view.chatMessages || []);
        const details = JSON.stringify([currentRun, view.artifacts, view.inputs, view.contributions,
          view.currentExplanation, view.budget, view.handoff, view.delegations]);
        if (!studio || details !== detailsSignature) {
          detailsSignature = details;
          renderArtifacts(view.artifacts || []);
          renderInputs(view.inputs);
          renderContributions(view.contributions);
          renderEvidence();
          renderHandoff();
        }
      } else {
        view = null;
        detailsSignature = "";
        showProvider(caps);
        setStatus("idle");
        renderTranscript([]);
        renderArtifacts([]);
        renderInputs([]);
        renderContributions([]);
        renderEvidence();
        renderHandoff();
      }
      if (studio) {
        renderOutbox();
        window.dispatchEvent(new CustomEvent("studio-conversation", { detail: { runId: currentRun, view, runs: runs.runs || [] } }));
      }
      const latest = view?.events?.at(-1)?.seq || cursor;
      if (currentRun && latest > cursor) {
        const events = await api("/api/engine/runs/" + encodeURIComponent(currentRun) + "/events?after=" + cursor);
        if (version !== refreshVersion) return;
        appendEvents(events.events || []);
        cursor = events.nextSeq || cursor;
      }
    } catch (error) {
      if (version !== refreshVersion) return;
      setStatus("error");
      receipt(error.message);
    }
  }

  function appendEvents(events) {
    const list = $("collab-events");
    if (!list) return;
    events.forEach((event) => {
      const li = el("li");
      li.append(el("span", "seq", event.seq));
      li.append(el("span", "type", event.type));
      const payload = event.payload || {};
      li.append(el("span", "muted", String(payload.message || payload.status || payload.reason || payload.outcome || payload.kind || "")));
      list.append(li);
    });
    while (list.children.length > 120) list.removeChild(list.firstChild);
  }

  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(async () => {
      if (busy || pollInFlight) return;
      pollInFlight = true;
      try { await refresh(); } finally { pollInFlight = false; }
    }, 1800);
  }

  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }

  function openPanel() {
    panel.hidden = false;
    document.body.classList.add("desk-open");
    $("collab-btn")?.setAttribute("aria-expanded", "true");
    refresh();
    startPolling();
    $("collab-composer").focus();
  }

  function closePanel() {
    const wasOpen = !panel.hidden;
    panel.hidden = true;
    document.body.classList.remove("desk-open");
    $("collab-btn")?.setAttribute("aria-expanded", "false");
    stopPolling();
    if (wasOpen) $("collab-btn").focus();
  }

  function selectRun(runId, updateAddress = true) {
    if (studio && busy) {
      $("collab-run-select").value = currentRun;
      receipt("Wait for the current message before switching conversations.");
      return;
    }
    if (studio) { storeComposer(); rememberTranscript(); }
    currentRun = runId || "";
    if (studio) {
      if (updateAddress) navigation.go({ problem: currentRun });
      if (!currentRun) paintTitle(draftTitle);
      restoreComposer(currentRun);
      $("collab-run-select").value = currentRun;
    }
    newPending = !currentRun;
    cursor = 0;
    $("collab-events").replaceChildren();
    rememberRun(currentRun);
    if (studio) reconcileOutbox();
    refresh();
  }

  async function lookupRequest(request) {
    const args = new URLSearchParams({ requestId: request.id });
    if (request.runId) args.set("runId", request.runId);
    return api("/api/engine/chat/receipt?" + args);
  }

  function describeReceipt(result) {
    if (result.choiceApplied) return "Choice saved";
    return { applied: "Applied", superseded: "Superseded", cancelled: "Cancelled",
      rejected: "Needs attention" }[result.status] || "Received";
  }

  function acceptRequest(request, result) {
    local.write("outbox:" + request.id, null);
    requestReceipts.set(result.messageId, result);
    if (result.choiceApplied) local.write("choice:" + result.runId + ":" + result.messageId, true);
    if (!request.runId && !currentRun) {
      currentRun = result.runId;
      storeComposer();
      local.write(draftKey(""), null);
      draftTitle = "";
      local.write("draft-title", "", true);
      newPending = false;
      cursor = 0;
      rememberRun(currentRun);
      navigation.go({ problem: currentRun });
      for (const item of outbox("").filter(row => row.tab === request.tab && row.time >= request.time)) {
        item.runId = currentRun;
        local.write("outbox:" + item.id, item);
      }
      for (const item of activeQueue) if (!item.runId) item.runId = currentRun;
    }
    renderOutbox();
    if (currentRun === result.runId) {
      receipt(describeReceipt(result) + (result.choiceApplied && composer.value ? ". Your draft is still here." : ""));
    }
  }

  function outbox(run = currentRun) {
    return local.entries("outbox:").map(([, request]) => request)
      .filter(request => request.runId === run).sort((a, b) => a.time - b.time);
  }

  let reconciling = false;
  async function reconcileOutbox() {
    if (busy || reconciling) return;
    reconciling = true;
    try {
      for (const request of outbox()) {
        if (request.runId !== currentRun) break;
        const result = await lookupRequest(request).catch(() => null);
        if (result?.accepted && request.runId === currentRun && !busy) {
          acceptRequest(request, result);
          await refresh();
        }
      }
    } finally { reconciling = false; renderOutbox(); }
  }

  let outboxSignature = "";
  function renderOutbox() {
    const host = $("studio-outbox");
    const pending = outbox();
    const signature = JSON.stringify([busy, pending]);
    if (signature === outboxSignature) return;
    outboxSignature = signature;
    host.hidden = !pending.length;
    host.replaceChildren();
    for (const request of pending) {
      const row = el("div", "studio-outbox-row");
      const label = request.state === "sending" && busy ? "Sending" : request.state === "queued" ? "Queued" : "Check delivery";
      row.append(el("span", null, label + " · " + request.message.slice(0, 88)));
      if (request.error) row.append(el("small", "warning", request.error));
      if (!busy) {
        for (const [text, action] of [
          ["Check receipt", reconcileOutbox],
          ["Retry send", () => sendQueue(request)],
          ["Copy into draft", () => {
            composer.value = [composer.value, request.raw ?? request.message].filter(Boolean).join("\n\n");
            storeComposer();
            composer.focus();
          }],
        ]) {
          const control = el("button", null, text);
          control.type = "button";
          control.onclick = action;
          row.append(control);
        }
      }
      host.append(row);
    }
  }

  async function sendQueue(request) {
    activeQueue.push(request);
    renderOutbox();
    if (busy) { receipt("Message queued"); return; }
    busy = true;
    if (!currentRun) nameButton.disabled = true;
    try {
      while (activeQueue.length) {
        const item = activeQueue.shift();
        let accepted;
        if (item.runId !== currentRun) break;
        item.state = "sending";
        local.write("outbox:" + item.id, item);
        renderOutbox();
        receipt("Sending…");
        try {
          await api(item.runId ? "/api/engine/runs/" + encodeURIComponent(item.runId) + "/messages" : "/api/engine/chat",
            { method: "POST", body: { message: item.message, clientRequestId: item.id,
              ...(item.runId ? { recoverInputId: item.recoverInputId, expectedInteractionId: item.decisionId } :
                { provider: item.provider, title: item.title }) } });
        } catch (error) {
          item.error = error.message;
        }
        accepted = await lookupRequest(item).catch(() => null);
        if (accepted?.accepted) {
          acceptRequest(item, accepted);
          await refresh();
        } else {
          item.state = "unknown";
          item.error ||= "Delivery could not be confirmed. Check the receipt or retry the same request.";
          local.write("outbox:" + item.id, item);
          receipt("Message delivery needs attention");
          break;
        }
      }
    } finally {
      busy = false;
      activeQueue.length = 0;
      nameButton.disabled = false;
      renderOutbox();
    }
  }

  async function sendMessage(text, recoverInputId, fromComposer = false, decisionId = null) {
    const message = String(text || "").trim();
    if (!message) { receipt("Write a message first."); return; }
    if (studio) {
      if (outbox().some(item => item.message === message && item.state !== "queued")) {
        receipt("This text already has a pending request. Check its receipt or retry it below.");
        return;
      }
      const request = { id: uid(), runId: currentRun, message, decisionId, recoverInputId,
        raw: fromComposer && text !== message ? text : undefined,
        provider: providerPicker?.value || "custom", title: draftTitle || undefined,
        time: Date.now(), state: "queued", tab: local.tab };
      local.write("outbox:" + request.id, request);
      if (fromComposer && composer.value === text) {
        composer.value = "";
        storeComposer();
      }
      await sendQueue(request);
      return;
    }
    if (composer) composer.value = "";
    if (busy) {
      // The composer stays usable while the current step finishes; the message
      // is queued and sent in order instead of being dropped.
      queuedMessages.push(message);
      receipt("Queued; it will send when the current step finishes.");
      return;
    }
    busy = true;
    if (nameButton && !currentRun) nameButton.disabled = true;
    receipt("Working…");
    await new Promise((resolve) => requestAnimationFrame(() => resolve()));
    try {
      let result;
      if (!currentRun) {
        result = await api("/api/engine/chat", {
          method: "POST",
          body: { message, clientRequestId: uid(), provider: providerPicker?.value || "custom",
            title: draftTitle || undefined },
        });
        currentRun = result.runId;
        draftTitle = "";
        newPending = false;
        rememberRun(currentRun);
        cursor = 0;
      } else {
        result = await api("/api/engine/runs/" + encodeURIComponent(currentRun) + "/messages", {
          method: "POST",
          body: { message, clientRequestId: uid(), recoverInputId: recoverInputId || undefined },
        });
      }
      receipt("Sent.");
      await refresh();
      const latestAuthor = ((view && view.chatMessages) || [])
        .filter((m) => m.role === "author").pop();
      const latestInput = latestAuthor && latestAuthor.input_id
        ? ((view && view.inputs) || []).find((i) => i.id === latestAuthor.input_id)
        : null;
      if (latestInput) {
        receipt(latestInput.status === "applied"
          ? "Applied · turn " + latestInput.seq
          : "Received · " + latestInput.status);
      }
    } catch (error) {
      receipt(error.message);
      if (composer && !composer.value) composer.value = message;
    } finally {
      busy = false;
      if (nameButton) nameButton.disabled = false;
      const next = queuedMessages.shift();
      if (next) sendMessage(next);
    }
  }

  async function newConversation() {
    if (studio && busy) { receipt("Wait for the current message before starting another conversation."); return; }
    if (studio) {
      if (!currentRun && composer.value.trim()) {
        composer.focus();
        receipt("Your new problem draft is open.");
        return;
      }
      draftTitle = "";
      local.write("draft-title", "", true);
    }
    selectRun("");
    receipt("New conversation. Describe the idea.");
    $("collab-composer").focus();
  }

  $("collab-btn")?.addEventListener("click", () => (panel.hidden ? openPanel() : closePanel()));
  $("collab-close")?.addEventListener("click", closePanel);
  $("collab-refresh")?.addEventListener("click", refresh);
  $("collab-new").addEventListener("click", newConversation);
  providerPicker?.addEventListener("change", () => {
    local.rememberLegacy("authorAgent.provider", providerPicker.value);
    if (defaultCapabilities) showProvider(defaultCapabilities);
  });
  $("collab-run-select").addEventListener("change", (event) => selectRun(event.target.value));
  $("collab-send").addEventListener("click", () => sendMessage(composer.value, null, true));
  $("collab-composer").addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !event.isComposing) {
      event.preventDefault();
      sendMessage(composer.value, null, true);
    }
  });
  $("collab-export").addEventListener("click", async () => {
    if (!currentRun) return;
    try {
      await api("/api/engine/runs/" + encodeURIComponent(currentRun) + "/exports", { method: "POST", body: {} });
    } catch (error) {
      receipt("Export refused with no effects: " + error.message);
    }
  });
  $("collab-restore").addEventListener("click", async () => {
    if (!currentRun) return;
    try {
      await api("/api/engine/runs/" + encodeURIComponent(currentRun) + "/restores", { method: "POST", body: {} });
    } catch (error) {
      receipt("Restore refused with no effects: " + error.message);
    }
  });

  window.addEventListener("beforeunload", stopPolling);
  if (studio) {
    restoreComposer(currentRun);
    composer.addEventListener("input", () => {
      if (!currentRun) {
        newPending = true;
        rememberRun("");
      }
      storeComposer();
    });
    for (const type of ["select", "blur"]) composer.addEventListener(type, () => storeComposer());
    $("collab-transcript").addEventListener("scroll", () => {
      updateLatestControl();
      clearTimeout(transcriptTimer);
      transcriptTimer = setTimeout(rememberTranscript, 160);
    });
    $("studio-jump-latest").onclick = () => {
      const transcript = $("collab-transcript");
      transcript.scrollTop = transcript.scrollHeight;
      updateLatestControl();
      composer.focus({ preventScroll: true });
    };
    window.addEventListener("studio-select-problem", event => {
      if (event.detail !== currentRun) selectRun(event.detail);
    });
    window.addEventListener("popstate", () => {
      if (location.hash && !new URLSearchParams(location.hash.slice(1)).has("problem")) return;
      const { problem } = navigation.target();
      if (problem !== currentRun) selectRun(problem, false);
    });
    window.addEventListener("pagehide", () => { storeComposer(); rememberTranscript(); });
    openPanel();
    reconcileOutbox();
  }
  document.addEventListener("keydown", (event) => {
    if (studio) return;
    if (event.key !== "Escape" || panel.hidden) return;
    if (document.querySelector("dialog[open]")) return;
    closePanel();
  });
})();
