const $ = (id) => document.getElementById(id);

function machineSend(id, event, detail) {
  const machine = window.AuthorMachines && window.AuthorMachines.machines[id];
  if (!machine) return false;
  return machine.can(event) ? machine.send(event, detail) : false;
}

function machineSet(id, next, reason) {
  const machine = window.AuthorMachines && window.AuthorMachines.machines[id];
  return machine ? machine.set(next, reason) : false;
}

const state = {
  slug: null,
  summary: null,
  tree: [],
  expanded: new Set(),
  changes: [],
  chats: [],
  chatId: null,
  chatQuery: "",
  plan: { steps: [] },
  file: null,
  dirty: false,
  settings: null,
  tools: null,
  jobId: null,
  jobChatId: null,
  jobEvents: 0,
  pollTimer: null,
  activeTab: "plan",
  activeSide: "chats",
  selectedChange: null,
  pendingMessage: null,
  pendingApproval: null,
  selectedContext: [],
  samples: [],
  activeSample: null,
  testResults: [],
  openTabs: [],
  mentionQuery: null,
  follow: true,
  fileBusy: false,
  approvalRendered: false,
  renderedChangeIds: new Set(),
  fileMode: "view",
  streaming: { assistantEl: null, assistantText: "", reasoningEl: null, reasoningText: "" },
};

// ---------- basics ----------

function toast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.className = "toast show" + (isError ? " err" : "");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.className = "toast"; }, 3600);
}

function setConnection(online) {
  machineSend("connection", online ? "ONLINE" : "OFFLINE");
  const dot = $("connection-dot");
  if (!dot) return;
  dot.className = "conn-dot " + (online ? "online" : "offline");
  dot.title = online ? "Connected to the author agent" : "Cannot reach the author agent";
}

async function api(path, options = {}) {
  const init = { method: options.method || "GET", headers: {} };
  if (options.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch {
    setConnection(false);
    throw new Error("Cannot reach the author agent server. Is the container running?");
  }
  setConnection(true);
  let payload = null;
  try { payload = await response.json(); } catch { payload = null; }
  if (!response.ok) throw new Error((payload && payload.error) || `Request failed (${response.status})`);
  return payload;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function truncate(value, size) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length > size ? text.slice(0, size - 1) + "…" : text;
}

const LANGUAGE_BY_EXT = {
  cpp: "cpp", cc: "cpp", cxx: "cpp", c: "c", h: "cpp", hpp: "cpp",
  py: "python", java: "java", kt: "kotlin",
  tex: "latex", sty: "latex", cls: "latex",
  yaml: "yaml", yml: "yaml", json: "json", ini: "ini",
  md: "markdown", sh: "bash", js: "javascript", css: "css", html: "xml",
};

function languageForPath(path) {
  const ext = String(path || "").split(".").pop().toLowerCase();
  return LANGUAGE_BY_EXT[ext] || "plaintext";
}

function isRunnablePath(path) {
  const ext = String(path || "").split(".").pop().toLowerCase();
  return ["cpp", "cc", "cxx", "c", "py", "java", "kt"].includes(ext);
}

function highlightCodeElement(codeEl, code, language) {
  const lang = language || "plaintext";
  codeEl.textContent = code;
  codeEl.className = "";
  if (!window.hljs) {
    codeEl.className = "hljs";
    return;
  }
  try {
    if (lang !== "plaintext" && hljs.getLanguage(lang)) {
      codeEl.innerHTML = hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
      codeEl.className = "hljs language-" + lang;
      return;
    }
  } catch {
    // fall back to plain text
  }
  codeEl.className = "hljs";
}

function highlightWithin(root) {
  if (!window.hljs) return;
  root.querySelectorAll("pre code").forEach((el) => {
    try { hljs.highlightElement(el); } catch { /* ignore */ }
  });
}

function copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => toast("Copied"), () => toast("Copy failed", true));
  } else {
    toast("Copy is not available", true);
  }
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(11, 16);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) {
    return date.toTimeString().slice(0, 5);
  }
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function renderMarkdown(text) {
  const escaped = escapeHtml(text || "");
  const lines = escaped.split("\n");
  const out = [];
  let inCode = false;
  let list = [];
  const flushList = () => {
    if (list.length) { out.push("<ul>" + list.join("") + "</ul>"); list = []; }
  };
  const inline = (value) => value
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  for (const line of lines) {
    const fence = line.trim().match(/^```([A-Za-z0-9_+-]*)\s*$/);
    if (fence) {
      flushList();
      if (inCode) {
        out.push("</code></pre>");
        inCode = false;
      } else {
        const lang = (fence[1] || "plaintext").replace(/[^A-Za-z0-9_+-]/g, "");
        out.push(`<pre><code class="language-${lang}">`);
        inCode = true;
      }
      continue;
    }
    if (inCode) { out.push(line); continue; }
    const heading = line.match(/^(#{1,3})\s+(.*)$/);
    if (heading) {
      flushList();
      const level = Math.min(3, heading[1].length) + 2;
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      continue;
    }
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    if (bullet) { list.push(`<li>${inline(bullet[1])}</li>`); continue; }
    flushList();
    if (!line.trim()) { out.push(""); continue; }
    out.push(`<p>${inline(line)}</p>`);
  }
  flushList();
  if (inCode) out.push("</code></pre>");
  return out.join("\n");
}

function scrollMessages() {
  if (!state.follow) return;
  const host = $("messages");
  host.scrollTop = host.scrollHeight;
  const button = $("follow-btn");
  if (button) button.hidden = true;
}

function setFollow(value) {
  state.follow = Boolean(value);
  const button = $("follow-btn");
  if (button) button.hidden = state.follow;
  if (state.follow) scrollMessages();
}

function addMessage(role, text) {
  const wrap = document.createElement("div");
  wrap.className = "msg " + role;
  const meta = document.createElement("div");
  meta.className = "msg-meta";
  meta.textContent = role === "user" ? "you" : "agent";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerHTML = role === "assistant" ? renderMarkdown(text) : `<p>${escapeHtml(text).replace(/\n/g, "<br>")}</p>`;
  if (role === "assistant") highlightWithin(bubble);
  wrap.appendChild(meta);
  wrap.appendChild(bubble);
  $("messages").appendChild(wrap);
  scrollMessages();
  return wrap;
}

function addEventCard(node) {
  node.classList.add("event");
  $("messages").appendChild(node);
  scrollMessages();
}

// ---------- streaming ----------

function resetStreaming() {
  state.streaming = { assistantEl: null, assistantText: "", reasoningEl: null, reasoningText: "" };
}

function ensureLiveAssistant() {
  if (state.streaming.assistantEl) return state.streaming.assistantEl;
  const wrap = document.createElement("div");
  wrap.className = "msg assistant";
  const meta = document.createElement("div");
  meta.className = "msg-meta";
  meta.textContent = "agent";
  const bubble = document.createElement("div");
  bubble.className = "bubble streaming";
  wrap.appendChild(meta);
  wrap.appendChild(bubble);
  $("messages").appendChild(wrap);
  state.streaming.assistantEl = bubble;
  state.streaming.assistantText = "";
  scrollMessages();
  return bubble;
}

function appendAssistantDelta(text) {
  if (!text) return;
  const bubble = ensureLiveAssistant();
  state.streaming.assistantText += text;
  bubble.textContent = state.streaming.assistantText;
  scrollMessages();
}

function finalizeAssistant(text) {
  if (state.streaming.assistantEl) {
    const bubble = state.streaming.assistantEl;
    bubble.classList.remove("streaming");
    bubble.innerHTML = renderMarkdown(text || state.streaming.assistantText);
    highlightWithin(bubble);
    state.streaming.assistantEl = null;
    state.streaming.assistantText = "";
    scrollMessages();
    return;
  }
  if (text) addMessage("assistant", text);
}

function ensureLiveReasoning() {
  if (state.streaming.reasoningEl) return state.streaming.reasoningEl;
  const card = document.createElement("details");
  card.className = "reasoning-card";
  card.open = true;
  const summary = document.createElement("summary");
  summary.textContent = "Thinking";
  const pre = document.createElement("pre");
  pre.className = "reasoning-text";
  card.appendChild(summary);
  card.appendChild(pre);
  addEventCard(card);
  state.streaming.reasoningEl = pre;
  state.streaming.reasoningText = "";
  return pre;
}

function appendReasoningDelta(text) {
  if (!text) return;
  const pre = ensureLiveReasoning();
  state.streaming.reasoningText += text;
  pre.textContent = state.streaming.reasoningText;
  pre.scrollTop = pre.scrollHeight;
}

function finalizeReasoning(text) {
  if (!text) return;
  if (state.streaming.reasoningEl) {
    state.streaming.reasoningEl.textContent = text;
    state.streaming.reasoningEl = null;
    state.streaming.reasoningText = "";
    scrollMessages();
    return;
  }
  renderReasoning(text, true);
}

function renderReasoning(text, open = true) {
  if (!text) return;
  const card = document.createElement("details");
  card.className = "reasoning-card";
  card.open = open;
  const summary = document.createElement("summary");
  summary.textContent = "Thinking";
  const pre = document.createElement("pre");
  pre.className = "reasoning-text";
  pre.textContent = String(text).slice(0, 20000);
  card.appendChild(summary);
  card.appendChild(pre);
  addEventCard(card);
}

// ---------- tool / event cards ----------

function toolSummary(args) {
  if (!args || typeof args !== "object") return "";
  if (args.path) return args.path;
  if (args.command) return args.command;
  if (args.steps) return `${Array.isArray(args.steps) ? args.steps.length : 0} steps`;
  return Object.keys(args).slice(0, 3).join(", ");
}

function sanitizedToolArgs(name, args) {
  if (!args || typeof args !== "object") return args;
  if (name === "write_file") {
    return { path: args.path, lines: String(args.content || "").split("\n").length };
  }
  if (name === "run_command") {
    return {
      command: args.command,
      timeout_seconds: args.timeout_seconds,
      stdin: args.stdin ? `${String(args.stdin).length} chars` : undefined,
      cwd: args.cwd,
      stdout_path: args.stdout_path,
    };
  }
  if (name === "update_plan") return { steps: args.steps };
  return args;
}

function renderToolCall(name, args) {
  const card = document.createElement("details");
  card.className = "tool-card";
  const preview = name === "write_file"
    ? `${args.path || ""} · ${String(args.content || "").split("\n").length} lines`
    : toolSummary(args);
  card.innerHTML = `<summary><span class="tool-name">${escapeHtml(name)}</span><span class="tool-arg">${escapeHtml(preview)}</span></summary><pre>${escapeHtml(JSON.stringify(sanitizedToolArgs(name, args), null, 2))}</pre>`;
  addEventCard(card);
}

function renderCodeCard(path, content, language, open = true) {
  const card = document.createElement("div");
  card.className = "code-card";
  const head = document.createElement("div");
  head.className = "code-head";
  const pathEl = document.createElement("span");
  pathEl.className = "path";
  pathEl.textContent = path;
  const copy = document.createElement("button");
  copy.className = "quiet small";
  copy.textContent = "Copy";
  copy.addEventListener("click", () => copyText(content));
  head.appendChild(pathEl);
  head.appendChild(copy);
  const pre = document.createElement("pre");
  const code = document.createElement("code");
  highlightCodeElement(code, String(content || "").slice(0, 30000), language || languageForPath(path));
  pre.appendChild(code);
  card.appendChild(head);
  card.appendChild(pre);
  addEventCard(card);
}

function renderFileList(result) {
  const card = document.createElement("div");
  card.className = "code-card";
  const head = document.createElement("div");
  head.className = "code-head";
  const pathEl = document.createElement("span");
  pathEl.className = "path";
  pathEl.textContent = `Files · ${result.count ?? (result.entries || []).length}`;
  head.appendChild(pathEl);
  const list = document.createElement("div");
  list.className = "file-list";
  const entries = (result.entries || []).slice(0, 300);
  if (!entries.length) {
    list.innerHTML = '<div class="muted">empty</div>';
  } else {
    for (const entry of entries) {
      const row = document.createElement("div");
      row.className = entry.type === "dir" ? "dir" : "";
      const depth = (entry.path.match(/\//g) || []).length;
      row.style.paddingLeft = depth * 10 + "px";
      row.textContent = entry.path.split("/").pop() + (entry.type === "dir" ? "/" : "");
      list.appendChild(row);
    }
  }
  card.appendChild(head);
  card.appendChild(list);
  addEventCard(card);
}

function diffStats(diff) {
  let additions = 0;
  let deletions = 0;
  for (const line of String(diff || "").split("\n")) {
    if (line.startsWith("+++") || line.startsWith("---")) continue;
    if (line.startsWith("+")) additions += 1;
    else if (line.startsWith("-")) deletions += 1;
  }
  return { additions, deletions };
}

function renderChangeCard(data) {
  const changeId = data.changeId || data.id;
  if (changeId && state.renderedChangeIds.has(changeId)) return;
  if (changeId) state.renderedChangeIds.add(changeId);
  const stats = diffStats(data.diff);
  const card = document.createElement("div");
  card.className = "change-card";
  const path = document.createElement("span");
  path.className = "path";
  path.textContent = data.path || "file";
  const statsEl = document.createElement("span");
  statsEl.className = "change-stats";
  statsEl.innerHTML = `<span class="add">+${stats.additions}</span> <span class="del">-${stats.deletions}</span>`;
  const hint = document.createElement("span");
  hint.className = "muted small";
  hint.textContent = changeId ? "open diff" : "";
  card.appendChild(path);
  card.appendChild(statsEl);
  card.appendChild(hint);
  if (changeId) card.addEventListener("click", () => openChangeDiff(changeId));
  addEventCard(card);
}

function renderVerifySummary(result) {
  const card = document.createElement("div");
  const status = result.status || (result.ok ? "ok" : "failed");
  const ok = status === "verified";
  card.className = "event-verify " + (ok ? "ok" : "bad");
  const counts = result.counts || {};
  const errors = result.errors || [];
  card.innerHTML = `<b>${ok ? "Package verified" : "Verification " + escapeHtml(status)}</b>
    <div class="muted small" style="margin-top:4px">${counts.tests || 0} tests · ${counts.accepted || 0} accepted · ${counts.negative || 0} negative</div>
    ${errors.length ? `<ul class="report-list status-fail" style="margin-top:7px">${errors.slice(0, 5).map((e) => `<li>${escapeHtml(e)}</li>`).join("")}</ul>` : ""}
    <button class="quiet small" style="margin-top:8px">Open report</button>`;
  card.querySelector("button").addEventListener("click", () => switchTab("report"));
  addEventCard(card);
}

function renderPlanResult(result) {
  const card = document.createElement("div");
  card.className = "tool-card";
  const summary = document.createElement("div");
  summary.className = "run-label";
  summary.textContent = "Plan";
  const list = document.createElement("div");
  list.className = "agent-plan";
  for (const step of (result.steps || [])) {
    const row = document.createElement("div");
    row.className = "agent-step " + (step.status || "pending");
    row.innerHTML = `<span class="dot"></span><span>${escapeHtml(step.title)}</span>`;
    list.appendChild(row);
  }
  card.appendChild(summary);
  card.appendChild(list);
  addEventCard(card);
}

function renderLimitsResult(result) {
  const card = document.createElement("div");
  card.className = "event-verify ok";
  card.innerHTML = `<b>Limits measured</b>
    <div class="muted small" style="margin-top:4px">${escapeHtml(String(result.timeLimitSeconds))} s time · ${escapeHtml(String(result.memoryMb))} MiB memory</div>
    <div class="muted small">slowest test: ${escapeHtml(result.slowestTest || "n/a")} · ${escapeHtml(String(result.maxRuntimeMs || 0))} ms</div>`;
  addEventCard(card);
}

function renderAnswersResult(result) {
  const card = document.createElement("div");
  card.className = "event-verify " + (result.ok ? "ok" : "bad");
  const disagreements = result.disagreements || [];
  card.innerHTML = `<b>${result.ok ? "Answers generated" : "Answer generation failed"}</b>
    <div class="muted small" style="margin-top:4px">${result.written || 0}/${result.tests || 0} answers written</div>
    ${disagreements.length ? `<div class="status-warn small" style="margin-top:4px">${disagreements.length} reference disagreement(s)</div>` : ""}`;
  addEventCard(card);
}

function renderExportResult(result) {
  const card = document.createElement("div");
  card.className = "event-verify ok";
  card.innerHTML = `<b>Package exported</b>
    <div class="muted small" style="margin-top:4px">${result.files || 0} files · ${Math.round((result.size || 0) / 1024)} KiB</div>
    <button class="primary small" style="margin-top:8px">Download ZIP</button>`;
  card.querySelector("button").addEventListener("click", () => {
    window.location.href = `/api/workspaces/${state.slug}/download`;
  });
  addEventCard(card);
}

function renderToolResult(name, result, open = true) {
  if (!result || typeof result !== "object") {
    const card = document.createElement("div");
    card.className = "event-error";
    card.textContent = String(result || "No result");
    addEventCard(card);
    return;
  }
  if (result.error) {
    const card = document.createElement("div");
    card.className = "event-error";
    card.textContent = String(result.error);
    addEventCard(card);
    return;
  }
  if (name === "run_command") {
    renderRunResult(result, open);
    return;
  }
  if (name === "read_file") {
    if (result.text === false) {
      const card = document.createElement("div");
      card.className = "event-verify";
      card.textContent = `Binary file: ${result.path}`;
      addEventCard(card);
    } else {
      renderCodeCard(result.path, result.content || "", languageForPath(result.path), open);
    }
    return;
  }
  if (name === "list_files") {
    renderFileList(result);
    return;
  }
  if (name === "write_file" || name === "delete_file") {
    if (result.changed || result.deleted) {
      renderChangeCard({ path: result.path, diff: result.diff || "", changeId: result.changeId });
    } else {
      const card = document.createElement("div");
      card.className = "event-verify";
      card.textContent = `${result.path}: no change`;
      addEventCard(card);
    }
    return;
  }
  if (name === "verify_package" || name === "read_report") {
    renderVerifySummary(result);
    return;
  }
  if (name === "update_plan") {
    renderPlanResult(result);
    return;
  }
  if (name === "measure_limits") {
    renderLimitsResult(result);
    return;
  }
  if (name === "build_answers") {
    renderAnswersResult(result);
    return;
  }
  if (name === "export_package") {
    renderExportResult(result);
    return;
  }
  if (name === "search_workspace") {
    const card = document.createElement("div");
    card.className = "event-verify";
    const matches = (result.matches || []).slice(0, 12).map((m) => `<div class="mono small">${escapeHtml(m.path)}:${m.line} ${escapeHtml(m.text)}</div>`).join("");
    card.innerHTML = `<b>Search · ${escapeHtml(result.query || "")}</b><div class="muted small" style="margin-top:4px">${result.count || 0} match(es)</div>${matches}`;
    addEventCard(card);
    return;
  }
  if (name === "list_tests") {
    const card = document.createElement("div");
    card.className = "event-verify";
    card.innerHTML = `<b>Tests</b><div class="muted small" style="margin-top:4px">${result.sampleCount || 0} sample · ${result.secretCount || 0} secret</div>`;
    addEventCard(card);
    return;
  }
  if (name === "report_summary") {
    renderVerifySummary(result);
    return;
  }
  if (name === "review_package") {
    const card = document.createElement("div");
    card.className = "event-verify";
    card.innerHTML = `<b>Independent review</b><div class="bubble" style="margin-top:6px">${renderMarkdown(result.review || "")}</div>`;
    highlightWithin(card);
    addEventCard(card);
    return;
  }
  if (name === "write_todos" || name === "update_brief" || name === "record_decision" || name === "set_focus") {
    const card = document.createElement("div");
    card.className = "event-verify";
    card.textContent = result.result || "State updated.";
    addEventCard(card);
    return;
  }
  const text = JSON.stringify(result, null, 2);
  const card = document.createElement("details");
  card.className = "tool-card";
  card.open = false;
  card.innerHTML = `<summary><span class="tool-name">${escapeHtml(name)}</span><span class="tool-arg">result</span></summary><pre>${escapeHtml(text.slice(0, 16000))}</pre>`;
  addEventCard(card);
}

function renderRunResult(result, open = true) {
  const command = Array.isArray(result.command) ? result.command.join(" ") : (result.command || "command");
  const exit = result.exitCode;
  const ok = !result.timedOut && exit === 0;
  const status = result.timedOut ? "timed out" : exit === 0 ? "exit 0" : `exit ${exit}`;
  const stdout = result.stdout || "";
  const stderr = result.stderr || "";
  const hasOutput = Boolean(stdout.trim() || stderr.trim());
  const card = document.createElement("details");
  card.className = "run-card " + (ok ? "ok" : "bad");
  card.open = open && (!ok || hasOutput);
  const summary = document.createElement("summary");
  summary.innerHTML = `<span class="run-prompt">$</span><span class="run-command">${escapeHtml(command)}</span><span class="chip ${ok ? "AC" : "WA"}">${escapeHtml(status)}</span><span class="run-ms">${Math.round(result.ms || 0)} ms</span>`;
  card.appendChild(summary);
  const body = document.createElement("div");
  body.className = "run-body";
  if (!hasOutput && !result.diagnostic) {
    body.innerHTML = '<div class="muted small">No output.</div>';
  } else {
    if (stdout.trim()) {
      const label = document.createElement("div");
      label.className = "run-label";
      label.textContent = "stdout";
      const pre = document.createElement("pre");
      pre.textContent = stdout.slice(0, 16000);
      body.appendChild(label);
      body.appendChild(pre);
    }
    if (stderr.trim()) {
      const label = document.createElement("div");
      label.className = "run-label err";
      label.textContent = "stderr";
      const pre = document.createElement("pre");
      pre.textContent = stderr.slice(0, 16000);
      body.appendChild(label);
      body.appendChild(pre);
    }
    if (result.diagnostic) {
      const diag = document.createElement("div");
      diag.className = "run-diagnostic";
      diag.textContent = result.diagnostic;
      body.appendChild(diag);
    }
  }
  card.appendChild(body);
  addEventCard(card);
}

function renderToolResult(name, result, open = true) {
  if (name === "run_command" && result && typeof result === "object" && !result.error) {
    renderRunResult(result, open);
    return;
  }
  const text = typeof result === "string" ? result : JSON.stringify(result, null, 2);
  const card = document.createElement("details");
  card.className = "tool-card";
  const ok = !(result && typeof result === "object" && result.error);
  card.open = open && !ok;
  card.innerHTML = `<summary><span class="tool-name">${escapeHtml(name)}</span><span class="tool-arg">${ok ? "result" : "error"}</span></summary><pre>${escapeHtml(text.slice(0, 16000))}</pre>`;
  addEventCard(card);
}

function renderChangeEvent(data) {
  renderChangeCard(data);
}

function renderVerificationEvent(data) {
  const result = data.result || {};
  const node = document.createElement("div");
  const status = result.status || (result.ok ? "ok" : "failed");
  node.className = "event-verify " + (status === "verified" || result.ok ? "ok" : "bad");
  const errors = (result.errors || []).slice(0, 6).map((e) => `<div>${escapeHtml(e)}</div>`).join("");
  node.innerHTML = `<b>${escapeHtml(data.stage || "verification")}: ${escapeHtml(status)}</b>${errors ? `<div class="muted" style="margin-top:6px">${errors}</div>` : ""}`;
  addEventCard(node);
}

function renderErrorEvent(data) {
  const node = document.createElement("div");
  node.className = "event-error";
  node.textContent = data.error || "Unknown error";
  addEventCard(node);
}

// ---------- status / problem ----------

function updateExportButton() {
  const summary = state.summary;
  const verified = summary && summary.lastStatus === "verified" && !summary.stale;
  const reviewed = !summary || (summary.unreviewed || 0) === 0;
  $("export-btn").disabled = !(verified && reviewed);
  $("export-btn").title = !verified
    ? "Verify the package before exporting"
    : !reviewed ? "Mark changes reviewed before exporting" : "Download the verified DOMjudge package";
}

function setStatus(status) {
  const pill = $("status-pill");
  const value = status || "unverified";
  pill.className = "pill " + (["verified", "failed", "unverified", "stale"].includes(value) ? value : "unverified");
  pill.textContent = value;
  updateExportButton();
}

function renderProblemCard() {
  const meta = (state.summary && state.summary.meta) || {};
  const name = meta.name || state.slug || "No problem";
  const status = (state.summary && state.summary.lastStatus) || "unverified";
  const idea = meta.idea ? truncate(meta.idea, 90) : "No idea recorded";
  document.querySelector(".problem-name").textContent = name;
  const sub = document.querySelector(".problem-sub");
  sub.textContent = `${status}${state.summary && state.summary.unreviewed ? ` · ${state.summary.unreviewed} unreviewed` : ""} · ${idea}`;
  sub.title = idea;
}

// ---------- tree ----------

function treeExpandedKey() {
  return "author-agent-expanded-" + state.slug;
}

function loadTreeExpanded() {
  state.expanded = new Set();
  if (!state.slug) return;
  try {
    const saved = JSON.parse(localStorage.getItem(treeExpandedKey()) || "null");
    if (Array.isArray(saved)) {
      state.expanded = new Set(saved.filter((item) => typeof item === "string"));
      return;
    }
  } catch { /* default */ }
  for (const row of state.tree) {
    if (row.type === "dir" && !row.path.includes("/")) state.expanded.add(row.path);
  }
}

function saveTreeExpanded() {
  if (!state.slug) return;
  localStorage.setItem(treeExpandedKey(), JSON.stringify([...state.expanded]));
}

function treeNodes() {
  const root = { path: "", type: "dir", name: "", children: [] };
  const map = new Map([["", root]]);
  for (const row of state.tree) {
    row.children = [];
    row.name = row.path.split("/").pop();
    map.set(row.path, row);
  }
  for (const row of state.tree) {
    const parentPath = row.path.includes("/") ? row.path.slice(0, row.path.lastIndexOf("/")) : "";
    (map.get(parentPath) || root).children.push(row);
  }
  const sort = (node) => {
    node.children.sort((a, b) => (a.type === b.type ? a.name.localeCompare(b.name) : a.type === "dir" ? -1 : 1));
    node.children.forEach(sort);
  };
  sort(root);
  return root;
}

function treeAction(label, title, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "tree-action";
  button.title = title;
  button.textContent = label;
  button.addEventListener("click", (event) => { event.stopPropagation(); onClick(); });
  return button;
}

function renderTree() {
  const host = $("file-tree");
  host.innerHTML = "";
  if (!state.tree.length) {
    host.innerHTML = '<div class="pad muted">No files</div>';
    return;
  }
  const changed = new Set(state.changes.filter((c) => !c.reverted && !c.reviewed).map((c) => c.path));

  const renderNode = (node, depth) => {
    if (node.path) {
      const isDir = node.type === "dir";
      const expanded = isDir && state.expanded.has(node.path);
      const rowEl = document.createElement("div");
      rowEl.className = "tree-row" + (isDir ? " tree-dir-row" : "") + (state.file && state.file.path === node.path ? " active" : "");
      rowEl.style.paddingLeft = (8 + depth * 13) + "px";
      rowEl.tabIndex = 0;
      rowEl.setAttribute("role", "button");
      if (isDir) rowEl.setAttribute("aria-expanded", expanded ? "true" : "false");
      const toggle = document.createElement("span");
      toggle.className = "tree-toggle";
      toggle.textContent = isDir ? (expanded ? "\u25be" : "\u25b8") : "";
      const glyph = isDir ? "\u25a3"
        : node.path.endsWith(".tex") ? "T"
        : node.path.endsWith(".cpp") || node.path.endsWith(".cc") ? "C"
        : node.path.endsWith(".py") ? "P"
        : node.path.endsWith(".java") ? "J"
        : node.path.endsWith(".in") ? "i"
        : node.path.endsWith(".ans") ? "o"
        : node.path.endsWith(".md") ? "M"
        : node.path.endsWith(".yaml") || node.path.endsWith(".yml") ? "Y"
        : node.path.endsWith(".pdf") ? "D"
        : "\u00b7";
      const icon = document.createElement("span");
      icon.className = "tree-icon" + (isDir ? " folder" : "");
      icon.textContent = isDir ? "" : glyph;
      icon.title = isDir ? "Folder" : "";
      const name = document.createElement("span");
      name.className = "tree-name";
      name.textContent = node.name;
      name.title = node.path;
      const size = document.createElement("span");
      size.className = "size";
      size.textContent = !isDir && node.size ? (node.size > 1024 ? Math.round(node.size / 1024) + "k" : node.size) : "";
      const actions = document.createElement("span");
      actions.className = "tree-actions";
      if (isDir) {
        actions.appendChild(treeAction("+", "New file in this folder", () => newEntry("file", node.path)));
        actions.appendChild(treeAction("\u25a1", "New folder in this folder", () => newEntry("dir", node.path)));
      }
      actions.appendChild(treeAction("\u270e", "Rename " + node.path, () => renameEntry(node.path)));
      actions.appendChild(treeAction("\u00d7", "Delete " + node.path, () => deleteEntry(node.path, isDir)));
      rowEl.append(toggle, icon, name, size, actions);
      if (changed.has(node.path)) {
        const dot = document.createElement("span");
        dot.className = "change-dot";
        dot.title = "Unreviewed change";
        rowEl.appendChild(dot);
      }
      const activate = () => {
        if (isDir) {
          if (state.expanded.has(node.path)) state.expanded.delete(node.path);
          else state.expanded.add(node.path);
          saveTreeExpanded();
          renderTree();
        } else {
          openFile(node.path);
        }
      };
      rowEl.addEventListener("click", activate);
      rowEl.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activate();
        }
      });
      host.appendChild(rowEl);
    }
    if (node.type === "dir" && (node.path === "" || state.expanded.has(node.path))) {
      for (const child of node.children) renderNode(child, node.path ? depth + 1 : depth);
    }
  };
  renderNode(treeNodes(), 0);
}

function treeParent(path) {
  return path && path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
}

async function newEntry(kind, baseDir = "") {
  if (!state.slug || state.jobId) return;
  const label = kind === "dir" ? "New folder" : "New file";
  const suggestion = baseDir ? baseDir + "/" : "";
  const path = await actionDialog({
    kicker: "Workspace",
    title: label,
    description: "Enter a path relative to the problem workspace.",
    inputLabel: "Path",
    value: suggestion,
    placeholder: kind === "dir" ? "data/sample" : "submissions/accepted/ref.cpp",
    confirmLabel: "Create",
    validate: (value) => (!value ? "Enter a path." : value.includes("..") ? "Path cannot contain '..'." : ""),
  });
  if (!path) return;
  try {
    await api(`/api/workspaces/${state.slug}/files`, {
      method: "POST",
      body: { path: path.trim(), kind },
    });
    if (kind === "dir") state.expanded.add(treeParent(path.trim()));
    await refreshWorkspace();
    toast(kind === "dir" ? "Folder created" : "File created");
    if (kind === "file") await openFile(path.trim());
  } catch (error) { toast(error.message, true); }
}

async function renameEntry(path) {
  if (!state.slug || state.jobId) return;
  const next = await actionDialog({
    kicker: "Files",
    title: "Rename",
    description: `Rename "${path}".`,
    inputLabel: "New path",
    value: path,
    confirmLabel: "Rename",
    validate: (value) => (!value ? "Enter a path." : value.includes("..") ? "Path cannot contain '..'." : value === path ? "Enter a different path." : ""),
  });
  if (!next || next === path) return;
  try {
    await api(`/api/workspaces/${state.slug}/files`, {
      method: "PATCH",
      body: { path, newPath: next.trim() },
    });
    if (state.file && (state.file.path === path || state.file.path.startsWith(path + "/"))) {
      state.file = null;
      $("file-name").textContent = "No file selected";
      $("file-view").hidden = true;
      $("file-editor").hidden = true;
      $("run-panel").hidden = true;
    }
    await refreshWorkspace();
    toast("Renamed");
  } catch (error) { toast(error.message, true); }
}

async function deleteEntry(path, isDir) {
  if (!state.slug || state.jobId) return;
  const ok = await actionDialog({
    kicker: "Files",
    title: `Delete ${isDir ? "folder" : "file"}?`,
    description: `"${path}" will be removed.${isDir ? " Its contents will be deleted too." : ""} This cannot be undone.`,
    confirmLabel: "Delete",
    danger: true,
  });
  if (!ok) return;
  try {
    await api(`/api/workspaces/${state.slug}/files?path=${encodeURIComponent(path)}`, { method: "DELETE" });
    if (state.file && (state.file.path === path || state.file.path.startsWith(path + "/"))) {
      state.file = null;
      $("file-name").textContent = "No file selected";
      $("file-view").hidden = true;
      $("file-editor").hidden = true;
      $("run-panel").hidden = true;
    }
    await refreshWorkspace();
    toast("Deleted");
  } catch (error) { toast(error.message, true); }
}

function sampleTests() {
  const paths = new Set(state.tree.filter((row) => row.type === "file").map((row) => row.path));
  return [...paths]
    .filter((path) => /^data\/sample\/.*\.in$/.test(path) && paths.has(path.replace(/\.in$/, ".ans")))
    .sort()
    .map((path) => ({ path, name: path.split("/").pop().replace(/\.in$/, ""), answer: path.replace(/\.in$/, ".ans") }));
}

function updateEditorChrome() {
  const editor = $("file-editor");
  const gutter = $("line-numbers");
  const language = state.file ? languageForPath(state.file.path) : "text";
  $("editor-language").textContent = language;
  $("run-language").textContent = language;
  const text = editor.value || "";
  const lines = text.split("\n").length;
  $("editor-lines").textContent = `${lines} lines`;
  if (editor.hidden) {
    gutter.hidden = true;
    return;
  }
  gutter.hidden = false;
  gutter.textContent = Array.from({ length: lines }, (_, index) => index + 1).join("\n");
  gutter.scrollTop = editor.scrollTop;
  const before = text.slice(0, editor.selectionStart || 0);
  const line = before.split("\n").length;
  const column = before.length - before.lastIndexOf("\n");
  $("editor-cursor").textContent = `Ln ${line}, Col ${column}`;
}

function normalizeOutput(value) {
  return String(value || "").replace(/\r\n/g, "\n").trim().split(/\s+/).join(" ");
}

function renderTestTabs() {
  const host = $("test-tabs");
  host.innerHTML = "";
  for (const result of state.testResults) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "test-tab" + (result.name === state.activeSample ? " active" : "") + (result.pass ? " pass" : " fail");
    button.textContent = `${result.pass ? "PASS" : "FAIL"} ${result.name}`;
    button.title = result.pass ? `Passed in ${Math.round(result.ms)} ms` : "Wrong answer";
    button.addEventListener("click", () => selectTest(result));
    host.appendChild(button);
  }
  if (!state.testResults.length) {
    for (const sample of state.samples) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "test-tab" + (sample.name === state.activeSample ? " active" : "");
      button.textContent = sample.name;
      button.addEventListener("click", () => loadSampleInput(sample.path));
      host.appendChild(button);
    }
  }
}

function renderTestResults() {
  const host = $("test-results");
  host.innerHTML = "";
  host.hidden = !state.testResults.length;
  for (const result of state.testResults) {
    const row = document.createElement("div");
    row.className = "test-result " + (result.pass ? "pass" : "fail");
    const name = document.createElement("span");
    name.className = "test-name";
    name.textContent = result.name;
    const status = document.createElement("span");
    status.className = "test-status";
    status.textContent = result.pass ? `Passed \u00b7 ${Math.round(result.ms)} ms` : (result.stage === "compile" ? "Compile error" : "Wrong answer");
    row.appendChild(name);
    row.appendChild(status);
    row.addEventListener("click", () => selectTest(result));
    host.appendChild(row);
  }
}

async function selectTest(result) {
  state.activeSample = result.name;
  $("run-stdin").value = result.stdin || "";
  $("run-output").hidden = false;
  $("run-output").className = "run-output" + (result.pass ? "" : " err");
  const parts = [`${result.name}: ${result.pass ? "Passed" : "Failed"} ? ${Math.round(result.ms)} ms`];
  if (!result.pass) {
    parts.push("", "expected:", result.expected || "(none)", "", "stdout:", result.stdout || "(empty)");
    if (result.stderr) parts.push("", "stderr:", result.stderr);
  }
  $("run-output").textContent = parts.join("\n");
  renderTestTabs();
}

async function runSamples() {
  if (!state.slug || !state.file || !isRunnablePath(state.file.path)) return;
  if (state.fileBusy) return;
  setRunBusy(true);
  if (state.dirty) await saveFile();
  const samples = sampleTests();
  if (!samples.length) {
    setRunBusy(false);
    toast("Add data/sample/*.in and *.ans first", true);
    return;
  }
  state.samples = samples;
  state.testResults = [];
  $("run-output").hidden = true;
  $("test-results").hidden = false;
  $("test-results").innerHTML = '<div class="muted small">Running sample tests?</div>';
  try {
    for (const sample of samples) {
      const input = await api(`/api/workspaces/${state.slug}/file?path=${encodeURIComponent(sample.path)}`);
      const answer = await api(`/api/workspaces/${state.slug}/file?path=${encodeURIComponent(sample.answer)}`);
      const run = await api(`/api/workspaces/${state.slug}/run`, {
        method: "POST",
        body: { path: state.file.path, stdin: input.content || "" },
      });
      const pass = Boolean(run.ok) && run.stage !== "compile" && normalizeOutput(run.stdout) === normalizeOutput(answer.content);
      state.testResults.push({
        name: sample.name,
        pass,
        stdin: input.content || "",
        expected: answer.content || "",
        stdout: run.stdout || "",
        stderr: run.stderr || run.error || "",
        ms: run.ms || 0,
        stage: run.stage || "run",
      });
    }
    state.activeSample = state.testResults[0] ? state.testResults[0].name : null;
    renderTestTabs();
    renderTestResults();
    const passed = state.testResults.filter((item) => item.pass).length;
    $("run-output").hidden = false;
    $("run-output").className = "run-output" + (passed === state.testResults.length ? "" : " err");
    $("run-output").textContent = `${passed}/${state.testResults.length} sample tests passed`;
    toast(`${passed}/${state.testResults.length} sample tests passed`, passed !== state.testResults.length);
  } catch (error) {
    $("test-results").hidden = true;
    toast(error.message, true);
  } finally {
    setRunBusy(false);
  }
}

function renderFileView() {
  if (!state.file) return;
  const file = state.file;
  const view = $("file-view");
  const code = $("file-code");
  view.hidden = false;
  $("file-editor").hidden = true;
  $("edit-file").hidden = !file.text;
  $("view-file").hidden = true;
  $("save-file").hidden = true;
  $("run-panel").hidden = !(file.text && isRunnablePath(file.path));
  machineSet("run", $("run-panel").hidden ? "hidden" : "ready", "render file");
  $("judge0-run").hidden = !(state.settings && state.settings.judge0Url && file.text && isRunnablePath(file.path));
  $("isolate-run").hidden = !(state.settings && state.settings.isolateUrl && file.text && isRunnablePath(file.path));
  state.samples = file.text ? sampleTests() : [];
  renderTestTabs();
  renderTestResults();
  updateEditorChrome();
  if (file.text) {
    highlightCodeElement(code, file.content || "", languageForPath(file.path));
  } else {
    code.textContent = "(binary file)";
    code.className = "hljs";
  }
}

function enterEditMode() {
  if (!state.file || !state.file.text) return;
  machineSend("editor", "EDIT");
  state.fileMode = "edit";
  $("file-view").hidden = true;
  $("file-editor").hidden = false;
  $("edit-file").hidden = true;
  $("view-file").hidden = false;
  $("save-file").hidden = !state.dirty;
  updateEditorChrome();
  $("file-editor").focus();
}

async function enterViewMode() {
  if (!state.file || !state.file.text) return;
  if (state.dirty) {
    const discard = await actionDialog({
      kicker: "Editor",
      title: "Discard unsaved changes?",
      description: `The edits to "${state.file.path}" have not been saved.`,
      confirmLabel: "Discard changes",
      danger: true,
    });
    if (!discard) return;
  }
  if (state.dirty) {
    $("file-editor").value = state.file.content;
    state.dirty = false;
  }
  state.fileMode = "view";
  machineSend("editor", "CANCEL");
  renderFileView();
}

async function openFile(path) {
  if (!state.slug) return;
  if (state.dirty && state.file && state.file.path !== path) {
    const discard = await actionDialog({
      kicker: "Editor",
      title: "Discard unsaved changes?",
      description: `The edits to "${state.file.path}" have not been saved.`,
      confirmLabel: "Discard and open",
      danger: true,
    });
    if (!discard) return;
  }
  try {
    const file = await api(`/api/workspaces/${state.slug}/file?path=${encodeURIComponent(path)}`);
    state.file = file;
    state.dirty = false;
    state.fileMode = "view";
    machineSet("editor", file.text ? "view" : "binary", "open file");
    state.testResults = [];
    state.activeSample = null;
    state.samples = file.text ? sampleTests() : [];
    $("file-name").textContent = file.path;
    $("file-meta").textContent = file.text ? `${file.size} bytes · ${languageForPath(file.path)}` : "binary";
    const editor = $("file-editor");
    editor.disabled = !file.text;
    editor.value = file.text ? file.content : "";
    $("reload-file").hidden = false;
    $("run-output").hidden = true;
    $("run-output").textContent = "";
    $("run-output").className = "run-output";
    $("test-results").hidden = true;
    $("test-results").innerHTML = "";
    $("line-numbers").hidden = true;
    renderFileView();
    switchSide("files");
    switchTab("file");
    renderTree();
  } catch (error) { toast(error.message, true); }
}

async function saveFile() {
  if (!state.slug || !state.file) return;
  machineSend("editor", "SAVE");
  try {
    const content = $("file-editor").value;
    await api(`/api/workspaces/${state.slug}/file`, {
      method: "POST",
      body: { path: state.file.path, content },
    });
    state.file.content = content;
    state.file.size = new Blob([content]).size;
    state.dirty = false;
    $("save-file").hidden = true;
    machineSend("editor", "SAVED");
    toast("Saved");
    await refreshWorkspace();
    renderFileView();
    $("file-meta").textContent = `${state.file.size} bytes · ${languageForPath(state.file.path)}`;
  } catch (error) {
    machineSend("editor", "FAIL");
    toast(error.message, true);
  }
}

async function loadSampleInput(samplePath = null) {
  if (!state.slug || !state.file) return;
  state.samples = sampleTests();
  const sample = samplePath
    ? state.samples.find((item) => item.path === samplePath)
    : state.samples.find((item) => item.name === state.activeSample) || state.samples[0];
  if (!sample) { toast("No sample tests found", true); return; }
  try {
    const file = await api(`/api/workspaces/${state.slug}/file?path=${encodeURIComponent(sample.path)}`);
    $("run-stdin").value = file.text ? file.content : "";
    state.activeSample = sample.name;
    renderTestTabs();
    toast(`Loaded sample ${sample.name}`);
  } catch (error) { toast(error.message, true); }
}

function setRunBusy(busy) {
  state.fileBusy = busy;
  for (const id of ["run-file", "run-tests", "judge0-run", "isolate-run"]) {
    const button = $(id);
    if (button) button.disabled = busy;
  }
}

async function runIsolate() {
  if (!state.slug || !state.file || !state.settings || !state.settings.isolateUrl) return;
  if (state.fileBusy) return;
  setRunBusy(true);
  const output = $("run-output");
  output.hidden = false;
  output.className = "run-output";
  output.textContent = "Isolate\u2026";
  machineSend("run", "RUN");
  try {
    const result = await api(`/api/workspaces/${state.slug}/isolate/run`, {
      method: "POST",
      body: { path: state.file.path, stdin: $("run-stdin").value },
    });
    const parts = [result.stdout, result.stderr, result.compileOutput, result.message].filter(Boolean);
    output.className = "run-output" + (result.ok ? "" : " err");
    output.textContent = parts.join("\n") || result.status || "No output";
    machineSend("run", result.ok ? "PASS" : "FAIL");
  } catch (error) {
    output.className = "run-output err";
    output.textContent = error.message;
    machineSend("run", "FAIL");
  } finally {
    setRunBusy(false);
  }
}

async function runJudge0() {
  if (!state.slug || !state.file || !state.settings || !state.settings.judge0Url) return;
  if (state.fileBusy) return;
  setRunBusy(true);
  const output = $("run-output");
  output.hidden = false;
  output.className = "run-output";
  output.textContent = "Judge0\u2026";
  machineSend("run", "RUN");
  try {
    const result = await api(`/api/workspaces/${state.slug}/judge0/run`, {
      method: "POST",
      body: { path: state.file.path, stdin: $("run-stdin").value },
    });
    const parts = [result.stdout, result.stderr, result.compileOutput, result.message].filter(Boolean);
    output.className = "run-output" + (result.ok ? "" : " err");
    output.textContent = parts.join("\n") || result.status || "No output";
    machineSend("run", result.ok ? "PASS" : "FAIL");
  } catch (error) {
    output.className = "run-output err";
    output.textContent = error.message;
    machineSend("run", "FAIL");
  } finally {
    setRunBusy(false);
  }
}

async function runFile() {
  if (!state.slug || !state.file || !isRunnablePath(state.file.path)) return;
  if (state.fileBusy) return;
  setRunBusy(true);
  machineSend("run", "RUN");
  if (state.dirty) await saveFile();
  state.samples = sampleTests();
  renderTestTabs();
  const output = $("run-output");
  output.hidden = false;
  output.className = "run-output";
  output.textContent = "Running\u2026";
  $("test-results").hidden = true;
  try {
    const result = await api(`/api/workspaces/${state.slug}/run`, {
      method: "POST",
      body: { path: state.file.path, stdin: $("run-stdin").value },
    });
    const ok = result.ok && !result.timedOut;
    output.className = "run-output" + (ok ? "" : " err");
    const parts = [];
    if (result.stage === "compile") {
      parts.push("Compilation failed", "", result.error || "", result.stderr || "");
    } else {
      parts.push(`${result.timedOut ? "timed out" : "exit " + result.exitCode} ? ${Math.round(result.ms || 0)} ms`);
      if ((result.stdout || "").trim()) parts.push("", "stdout:", result.stdout);
      if ((result.stderr || "").trim()) parts.push("", "stderr:", result.stderr);
      if (result.diagnostic) parts.push("", result.diagnostic);
    }
    output.textContent = parts.join("\n");
    output.scrollTop = 0;
    machineSend("run", ok ? "PASS" : "FAIL");
  } catch (error) {
    output.className = "run-output err";
    output.textContent = error.message;
    machineSend("run", "FAIL");
  } finally {
    setRunBusy(false);
  }
}

// ---------- changes ----------

function renderChanges() {
  const host = $("changes-list");
  host.innerHTML = "";
  const active = state.changes.filter((c) => !c.reverted);
  const unreviewed = active.filter((c) => !c.reviewed);
  $("unreviewed-count").textContent = unreviewed.length;
  $("unreviewed-count").className = "badge" + (unreviewed.length ? "" : " zero");
  $("approve-btn").disabled = !unreviewed.length;
  $("revert-unreviewed").disabled = !unreviewed.length;
  updateExportButton();
  if (!state.changes.length) {
    host.innerHTML = '<div class="pad muted">No changes yet.</div>';
    return;
  }
  for (const change of [...state.changes].reverse()) {
    const row = document.createElement("div");
    row.className = "change-row" + (change.reverted ? " reverted" : "");
    const source = change.source === "agent" ? "agent" : change.source === "verify" ? "verify" : "you";
    const additions = change.additions || 0;
    const deletions = change.deletions || 0;
    row.innerHTML = `
      <div class="change-path">${escapeHtml(change.path)}</div>
      <div class="change-meta">
        <span class="tag ${source === "agent" ? "agent" : source === "verify" ? "verify" : "user"}">${source}</span>
        ${change.reverted ? '<span class="tag revert">reverted</span>' : change.reviewed ? "<span>reviewed</span>" : "<span>unreviewed</span>"}
        <span class="change-stats"><span class="add">+${additions}</span> <span class="del">-${deletions}</span></span>
        ${change.reverted ? "" : `<button class="quiet small" data-revert="${escapeHtml(change.id)}">revert</button>`}
      </div>`;
    row.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;
      openChangeDiff(change.id);
    });
    const revert = row.querySelector("[data-revert]");
    if (revert) revert.addEventListener("click", async (event) => {
      event.stopPropagation();
      try {
        await api(`/api/workspaces/${state.slug}/changes/${change.id}/revert`, { method: "POST" });
        toast("Change reverted");
        await refreshWorkspace();
        if (state.file) await openFile(state.file.path);
      } catch (error) { toast(error.message, true); }
    });
    host.appendChild(row);
  }
}

async function openChangeDiff(changeId) {
  if (!state.slug || !changeId) return;
  try {
    const [data, hunkData] = await Promise.all([
      api(`/api/workspaces/${state.slug}/changes/${changeId}/diff`),
      api(`/api/workspaces/${state.slug}/changes/${changeId}/hunks`),
    ]);
    state.selectedChange = changeId;
    switchTab("diff");
    const body = $("diff-body");
    body.innerHTML = "";
    const pre = document.createElement("pre");
    for (const line of (data.diff || "(no diff)").split("\n")) {
      const span = document.createElement("span");
      span.className = line.startsWith("+++") || line.startsWith("---") || line.startsWith("@@") ? "diff-hunk"
        : line.startsWith("+") ? "diff-add"
        : line.startsWith("-") ? "diff-del" : "diff-ctx";
      span.textContent = line;
      pre.appendChild(span);
      pre.appendChild(document.createTextNode("\n"));
    }
    body.appendChild(pre);
    const hunks = hunkData.hunks || [];
    if (hunks.length) {
      const tools = document.createElement("div");
      tools.className = "hunk-tools";
      const title = document.createElement("div");
      title.className = "muted small";
      title.textContent = "Select hunks to apply";
      tools.appendChild(title);
      const boxes = [];
      for (const hunk of hunks) {
        const label = document.createElement("label");
        label.className = "hunk-row";
        const box = document.createElement("input");
        box.type = "checkbox";
        box.checked = true;
        box.value = String(hunk.index);
        const code = document.createElement("code");
        code.textContent = hunk.header || `hunk ${hunk.index + 1}`;
        label.appendChild(box);
        label.appendChild(code);
        tools.appendChild(label);
        boxes.push(box);
      }
      const apply = document.createElement("button");
      apply.className = "primary small";
      apply.textContent = "Apply selected hunks";
      apply.addEventListener("click", async () => {
        const selected = boxes.filter((box) => box.checked).map((box) => Number(box.value));
        if (!selected.length) { toast("Select at least one hunk", true); return; }
        try {
          await api(`/api/workspaces/${state.slug}/changes/${changeId}/apply-hunks`, { method: "POST", body: { selected } });
          await refreshWorkspace();
          if (state.file) await openFile(state.file.path);
          toast("Selected hunks applied");
        } catch (error) { toast(error.message, true); }
      });
      tools.appendChild(apply);
      body.appendChild(tools);
    }
  } catch (error) { toast(error.message, true); }
}

async function revertAllUnreviewed() {
  const targets = state.changes.filter((c) => !c.reverted && !c.reviewed);
  if (!targets.length) return;
  const ok = await actionDialog({
    kicker: "Changes",
    title: `Revert ${targets.length} change${targets.length === 1 ? "" : "s"}?`,
    description: "Only unreviewed changes are reverted. Reviewed changes are kept.",
    confirmLabel: "Revert changes",
    danger: true,
  });
  if (!ok) return;
  let failed = 0;
  for (const change of [...state.changes].reverse()) {
    if (change.reverted || change.reviewed) continue;
    try {
      await api(`/api/workspaces/${state.slug}/changes/${change.id}/revert`, { method: "POST" });
    } catch { failed += 1; }
  }
  await refreshWorkspace();
  if (state.file) await openFile(state.file.path);
  toast(failed ? `Reverted with ${failed} conflict(s)` : "Unreviewed changes reverted", Boolean(failed));
}

// ---------- chats ----------

function chatTitle(chat) {
  return (chat && chat.title) || "New chat";
}

function tabsStorageKey() {
  return "author-agent-tabs-" + state.slug;
}

function loadChatTabs() {
  state.openTabs = [];
  if (!state.slug) return;
  try {
    const value = JSON.parse(localStorage.getItem(tabsStorageKey()) || "[]");
    if (Array.isArray(value)) state.openTabs = value.filter((id) => state.chats.some((chat) => chat.id === id));
  } catch { state.openTabs = []; }
}

function saveChatTabs() {
  if (state.slug) localStorage.setItem(tabsStorageKey(), JSON.stringify(state.openTabs));
}

function openChatTab(chatId) {
  if (!chatId) return;
  if (!state.openTabs.includes(chatId)) state.openTabs.push(chatId);
  state.openTabs = state.openTabs.slice(-8);
  saveChatTabs();
}

function closeChatTab(chatId, event) {
  if (event) event.stopPropagation();
  state.openTabs = state.openTabs.filter((id) => id !== chatId);
  saveChatTabs();
  renderChatTabs();
}

function renderChatTabs() {
  const host = $("chat-tabs");
  if (!host) return;
  host.innerHTML = "";
  for (const id of state.openTabs) {
    const chat = state.chats.find((item) => item.id === id);
    if (!chat) continue;
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "chat-tab" + (id === state.chatId ? " active" : "");
    tab.textContent = chatTitle(chat);
    tab.title = chatTitle(chat);
    tab.addEventListener("click", () => selectChat(id));
    const close = document.createElement("span");
    close.className = "chat-tab-close";
    close.textContent = "\u00d7";
    close.title = "Close tab";
    close.addEventListener("click", (event) => closeChatTab(id, event));
    tab.appendChild(close);
    host.appendChild(tab);
  }
}

function mentionCandidates(query) {
  const q = String(query || "").toLowerCase();
  return state.tree
    .filter((row) => row.type === "file" && row.text && !row.path.startsWith("data/secret/") && !row.path.endsWith(".ans"))
    .filter((row) => !q || row.path.toLowerCase().includes(q))
    .slice(0, 8);
}

function hideMentions() {
  state.mentionQuery = null;
  const menu = $("mention-menu");
  if (menu) menu.hidden = true;
}

function renderMentions() {
  const composer = $("composer");
  const menu = $("mention-menu");
  if (!composer || !menu) return;
  const before = composer.value.slice(0, composer.selectionStart || 0);
  const match = before.match(/@([A-Za-z0-9_./-]*)$/);
  if (!match) { hideMentions(); return; }
  const query = match[1];
  state.mentionQuery = { start: before.length - match[0].length, query };
  const candidates = mentionCandidates(query);
  if (!candidates.length) { hideMentions(); return; }
  menu.innerHTML = "";
  for (const row of candidates) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "mention-item";
    button.textContent = row.path;
    button.addEventListener("click", () => {
      const info = state.mentionQuery;
      if (!info) return;
      const after = composer.value.slice(composer.selectionStart || 0);
      composer.value = composer.value.slice(0, info.start) + "@" + row.path + " " + after;
      composer.focus();
      if (!state.selectedContext.includes(row.path)) {
        state.selectedContext.push(row.path);
        saveContext();
        renderContextChips();
      }
      hideMentions();
    });
    menu.appendChild(button);
  }
  menu.hidden = false;
}

function renderChatList() {
  const host = $("chat-list");
  host.innerHTML = "";
  const query = state.chatQuery.trim().toLowerCase();
  const chats = state.chats.filter((chat) => !query || chatTitle(chat).toLowerCase().includes(query));
  if (!chats.length) {
    host.innerHTML = `<div class="pad muted">${query ? "No matching conversations." : "No conversations yet."}</div>`;
  }
  for (const chat of chats) {
    const item = document.createElement("div");
    const running = Boolean(state.jobId && state.jobChatId === chat.id);
    item.className = "chat-item" + (chat.id === state.chatId ? " active" : "") + (running ? " running" : "") + (state.jobId ? " disabled" : "");
    const title = document.createElement("button");
    title.type = "button";
    title.className = "chat-item-title";
    title.textContent = chatTitle(chat);
    title.title = "Open conversation. Double-click to rename.";
    title.setAttribute("aria-current", chat.id === state.chatId ? "true" : "false");
    title.addEventListener("click", (event) => {
      event.stopPropagation();
      selectChat(chat.id);
    });
    const meta = document.createElement("div");
    meta.className = "chat-item-meta";
    meta.innerHTML = `<span class="chat-dot"></span><span>${escapeHtml(formatTime(chat.updatedAt))}</span><span>·</span><span>${chat.messageCount || 0} msgs</span>`;
    const actions = document.createElement("span");
    actions.className = "chat-actions";
    const rename = document.createElement("button");
    rename.type = "button";
    rename.title = "Rename chat";
    rename.setAttribute("aria-label", `Rename ${chatTitle(chat)}`);
    rename.textContent = "✎";
    rename.addEventListener("click", (event) => { event.stopPropagation(); renameChat(chat.id); });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.title = "Delete chat";
    remove.setAttribute("aria-label", `Delete ${chatTitle(chat)}`);
    remove.textContent = "×";
    remove.addEventListener("click", (event) => { event.stopPropagation(); deleteChat(chat.id); });
    actions.appendChild(rename);
    actions.appendChild(remove);
    title.addEventListener("dblclick", (event) => { event.stopPropagation(); renameChat(chat.id); });
    item.appendChild(title);
    item.appendChild(meta);
    item.appendChild(actions);
    if (!state.jobId) item.addEventListener("click", () => selectChat(chat.id));
    host.appendChild(item);
  }
  $("new-chat").disabled = Boolean(state.jobId) || !state.slug;
  $("reload-chat").disabled = Boolean(state.jobId) || !state.slug || !state.chatId;
  $("stop-btn").hidden = !state.jobId;
  $("stop-btn").disabled = !state.jobId;
  const active = state.chats.find((c) => c.id === state.chatId);
  const summaryName = state.summary && state.summary.meta && state.summary.meta.name;
  const problemName = summaryName || document.querySelector(".problem-name")?.textContent || "";
  const activeTitle = active ? chatTitle(active) : "No conversation";
  const displayTitle = active && activeTitle === "New chat" && problemName ? problemName : activeTitle;
  $("chat-title").textContent = displayTitle;
  $("chat-sub").textContent = active
    ? (activeTitle === "New chat" ? "Start a conversation" : `${formatTime(active.updatedAt)} · ${active.messageCount || 0} messages${state.jobId && state.jobChatId === active.id ? " · working" : ""}`)
    : "";
  $("composer-chat").textContent = active ? (activeTitle === "New chat" && problemName ? problemName : chatTitle(active)) : "no chat";
  renderChatTabs();
}

async function loadChats(preferredId) {
  if (!state.slug) { state.chats = []; state.chatId = null; renderChatList(); return null; }
  const data = await api(`/api/workspaces/${state.slug}/chats`);
  state.chats = data.chats || [];
  const remembered = localStorage.getItem(`author-agent-chat-${state.slug}`);
  const candidates = [preferredId, state.chatId, remembered, data.activeChat, state.chats[0] && state.chats[0].id];
  const id = candidates.find((value) => value && state.chats.some((chat) => chat.id === value));
  state.chatId = id || null;
  if (state.chatId) localStorage.setItem(`author-agent-chat-${state.slug}`, state.chatId);
  loadChatTabs();
  if (state.chatId) openChatTab(state.chatId);
  renderChatList();
  renderChatTabs();
  return state.chatId;
}

async function selectChat(chatId) {
  if (state.jobId) { toast("Wait for the current turn before switching chats", true); return; }
  if (!chatId || chatId === state.chatId) return;
  state.chatId = chatId;
  localStorage.setItem(`author-agent-chat-${state.slug}`, chatId);
  openChatTab(chatId);
  renderChatList();
  renderChatTabs();
  await loadConversation();
}

async function renameChat(chatId) {
  if (!state.slug || state.jobId) return;
  const chat = state.chats.find((item) => item.id === chatId);
  if (!chat) return;
  const title = await actionDialog({
    kicker: "Conversation",
    title: "Rename chat",
    description: `Rename "${chatTitle(chat)}".`,
    inputLabel: "Chat title",
    value: chatTitle(chat),
    confirmLabel: "Rename",
    validate: (value) => (!value ? "Enter a title." : value === chatTitle(chat) ? "Enter a different title." : ""),
  });
  if (title === null) return;
  if (!title || title === chatTitle(chat)) return;
  try {
    await api(`/api/workspaces/${state.slug}/chats/${chatId}`, { method: "PATCH", body: { title: title.trim() } });
    await loadChats(chatId);
    toast("Chat renamed");
  } catch (error) { toast(error.message, true); }
}

async function deleteChat(chatId) {
  if (!state.slug || state.jobId) return;
  const chat = state.chats.find((item) => item.id === chatId);
  if (!chat) return;
  const ok = await actionDialog({
    kicker: "Conversation",
    title: "Delete chat?",
    description: `"${chatTitle(chat)}" and its transcript will be removed. This cannot be undone.`,
    confirmLabel: "Delete chat",
    danger: true,
  });
  if (!ok) return;
  try {
    const data = await api(`/api/workspaces/${state.slug}/chats/${chatId}`, { method: "DELETE" });
    state.chats = data.chats || [];
    state.chatId = data.activeChat || null;
    if (state.chatId) localStorage.setItem(`author-agent-chat-${state.slug}`, state.chatId);
    await loadChats(state.chatId);
    await loadConversation();
    toast("Chat deleted");
  } catch (error) { toast(error.message, true); }
}

async function newChat() {
  if (!state.slug) { toast("Create or select a problem first", true); return; }
  if (state.jobId) { toast("Wait for the current turn before starting a new chat", true); return; }
  try {
    const chat = await api(`/api/workspaces/${state.slug}/chats`, { method: "POST", body: {} });
    await loadChats(chat.id);
    await loadConversation();
    toast("New chat created; the previous one is kept");
  } catch (error) { toast(error.message, true); }
}

async function loadConversation() {
  const host = $("messages");
  host.innerHTML = "";
  resetStreaming();
  setFollow(true);
  state.approvalRendered = false;
  state.pendingApproval = null;
  state.renderedChangeIds = new Set();
  state.plan = { steps: [] };
  if (!state.slug || !state.chatId) {
    host.innerHTML = '<div class="empty"><h2>No conversation</h2><p>Create a chat to begin.</p></div>';
    renderChatList();
    renderPlan();
    return;
  }
  try {
    const data = await api(`/api/workspaces/${state.slug}/chats/${state.chatId}`);
    state.plan = data.plan || { steps: [] };
    const messages = data.messages || [];
    if (!messages.length) {
      host.innerHTML = `<div class="empty"><h2>${escapeHtml(data.title || "Ready")}</h2>
        <p>Ask the agent to author or continue this problem. It writes files, runs compiles and tests, and shows every change.</p>
        <p class="muted">Try: “Author this problem from the idea in NOTES.md, then verify until green.”</p></div>`;
    }
    const toolNames = {};
    for (const message of messages) {
      if (message.role === "user") {
        addMessage("user", message.content || "");
        continue;
      }
      if (message.role === "assistant") {
        for (const call of message.tool_calls || []) {
          const fn = call.function || {};
          toolNames[call.id] = fn.name || "tool";
        }
        if (message.reasoning) renderReasoning(message.reasoning, false);
        if (message.content) addMessage("assistant", message.content);
        continue;
      }
      if (message.role === "tool") {
        const name = toolNames[message.tool_call_id] || "tool";
        let result = message.content || "";
        try { result = JSON.parse(result); } catch { /* keep text */ }
        renderToolResult(name, result, false);
      }
    }
    const pending = data.pending || [];
    state.pendingApproval = pending.length ? pending : null;
    if (pending.length) renderApproval(pending);
    $("send-btn").disabled = Boolean(state.jobId || state.pendingApproval);
    renderChatList();
    renderPlan();
  } catch (error) {
    host.innerHTML = `<div class="pad muted">Could not load conversation: ${escapeHtml(error.message)}</div>`;
  }
}

// ---------- plan ----------

function hasPath(path) {
  return state.tree.some((row) => row.path === path);
}

function countFiles(prefix, suffix) {
  return state.tree.filter((row) => row.type === "file" && row.path.startsWith(prefix) && row.path.endsWith(suffix)).length;
}

function pipelineSteps() {
  const paths = new Set(state.tree.filter((row) => row.type === "file").map((row) => row.path));
  const sample = [...paths].filter((p) => /^data\/sample\/.*\.in$/.test(p)).length;
  const secret = [...paths].filter((p) => /^data\/secret\/.*\.in$/.test(p)).length;
  const accepted = countFiles("submissions/accepted/", ".cpp") + countFiles("submissions/accepted/", ".cc")
    + countFiles("submissions/accepted/", ".py") + countFiles("submissions/accepted/", ".java");
  const negative = countFiles("submissions/wrong_answer/", ".cpp") + countFiles("submissions/wrong_answer/", ".py")
    + countFiles("submissions/wrong_answer/", ".java") + countFiles("submissions/time_limit_exceeded/", ".cpp")
    + countFiles("submissions/time_limit_exceeded/", ".py");
  const report = state.summary && state.summary.lastReport;
  const checks = (report && report.checks) || [];
  const statement = checks.find((c) => c.name === "Statement PDF");
  const verified = report && report.status === "verified" && !(state.summary && state.summary.stale);
  const limitsMeasured = Boolean(state.summary && state.summary.limitsMeasured);
  const measured = (state.summary && state.summary.measuredLimits) || {};
  return [
    { label: "Idea captured", done: paths.has("NOTES.md"), detail: "NOTES.md" },
    { label: "Statement written", done: paths.has("problem_statement/problem.en.tex"), detail: "problem.en.tex" },
    { label: "Statement compiles", done: statement && statement.status === "pass", fail: statement && statement.status === "fail", detail: statement ? statement.status : "not checked" },
    { label: "Input validator", done: paths.has("input_validators/validate.py"), detail: "validate.py" },
    { label: "Reference solution", done: accepted > 0, detail: `${accepted} accepted` },
    { label: "Sample + secret tests", done: sample > 0 && secret > 0, detail: `${sample} sample · ${secret} secret` },
    { label: "Negative solutions", done: negative > 0, detail: `${negative} negative` },
    { label: "Limits measured", done: limitsMeasured, detail: limitsMeasured ? `${measured.timeLimitSeconds}s / ${measured.memoryMb} MiB` : "provisional defaults" },
    { label: "Package verified", done: Boolean(verified), fail: report && report.status === "failed", detail: report ? `${report.status}${state.summary && state.summary.stale ? " · stale" : ""}` : "not run" },
  ];
}

function renderStageRail() {
  const host = $("stage-rail");
  if (!host) return;
  const summary = state.summary || {};
  const report = summary.lastReport || {};
  const stages = [
    ["Plan", Boolean((state.plan && state.plan.steps || []).length)],
    ["Generate", Boolean((state.tree || []).length)],
    ["Validate", Boolean((report.checks || []).some((c) => c.name === "Validator results" && c.status === "pass"))],
    ["Answers", Boolean(report.answers && report.answers.written)],
    ["Measure", Boolean(summary.limitsMeasured)],
    ["Verify", summary.lastStatus === "verified"],
    ["Review", !summary.unreviewed],
    ["Export", summary.lastStatus === "verified" && !summary.unreviewed],
  ];
  host.innerHTML = stages.map(([label, done], index) => `<span class="stage-chip ${done ? "done" : ""}" title="${escapeHtml(label)}: ${done ? "verified evidence present" : "not yet complete"}"><span class="stage-num">${index + 1}</span>${escapeHtml(label)}</span>`).join('<span class="stage-sep">&gt;</span>');
}

function renderPlan() {
  const host = $("plan-body");
  const pipeline = pipelineSteps();
  const agentSteps = (state.plan && state.plan.steps) || [];
  const report = state.summary && state.summary.lastReport;
  const unreviewed = (state.summary && state.summary.unreviewed) || 0;
  const limitsMeasured = Boolean(state.summary && state.summary.limitsMeasured);
  const measured = (state.summary && state.summary.measuredLimits) || {};
  host.innerHTML = `
    <div class="plan-section">
      <h3>Authoring pipeline</h3>
      <div class="pipeline">
        ${pipeline.map((step) => `<div class="pipeline-step ${step.done ? "done" : step.fail ? "fail" : ""}">
          <span class="mark">${step.done ? "✓" : step.fail ? "!" : ""}</span>
          <span class="label">${escapeHtml(step.label)}</span>
          <span class="detail">${escapeHtml(step.detail)}</span>
        </div>`).join("")}
      </div>
    </div>
    <div class="plan-section">
      <h3>Agent plan</h3>
      <div class="agent-plan">
        ${agentSteps.length ? agentSteps.map((step) => `<div class="agent-step ${escapeHtml(step.status || "pending")}">
          <span class="dot"></span><span>${escapeHtml(step.title)}</span>
        </div>`).join("") : '<div class="plan-empty">The agent publishes a plan when it starts a substantial turn.</div>'}
      </div>
    </div>
    <div class="plan-section">
      <h3>Current state</h3>
      <div class="agent-plan">
        <div class="agent-step"><span class="dot ${report && report.status === "verified" ? "completed" : ""}"></span><span>${report ? `Last verification: ${escapeHtml(report.status)}` : "No verification run yet"}</span></div>
        <div class="agent-step"><span class="dot ${unreviewed ? "in_progress" : "completed"}"></span><span>${unreviewed} unreviewed change(s)</span></div>
        <div class="agent-step"><span class="dot ${limitsMeasured ? "completed" : "in_progress"}"></span><span>${limitsMeasured ? `Limits: ${measured.timeLimitSeconds}s / ${measured.memoryMb} MiB` : "Limits not measured yet"}</span></div>
      </div>
    </div>`;
  renderPlanStrip();
}

function renderPlanStrip() {
  const strip = $("plan-strip");
  const steps = (state.plan && state.plan.steps) || [];
  if (!steps.length) { strip.hidden = true; strip.innerHTML = ""; return; }
  strip.hidden = false;
  strip.innerHTML = steps.slice(0, 8).map((step) => {
    const status = step.status || "pending";
    return `<span class="plan-step-mini ${status === "completed" ? "done" : status === "in_progress" ? "active" : ""}"><span class="dot"></span>${escapeHtml(step.title)}</span>`;
  }).join("");
}

// ---------- report ----------

function renderCheckerMatrix(selftest) {
  if (!selftest || !selftest.cases || !selftest.cases.length) return "";
  const rows = selftest.cases.map((item) => `<tr><td>${escapeHtml(item.name)}</td><td>${escapeHtml(item.expected)}</td><td class="${item.pass ? "status-pass" : "status-fail"}">${escapeHtml(item.actual)}</td><td>${escapeHtml(item.message || "")}</td></tr>`).join("");
  return `<h3>Checker self-test <span class="chip ${selftest.status === "pass" ? "AC" : "WA"}">${escapeHtml(selftest.status)}</span></h3><table class="table"><thead><tr><th>Case</th><th>Expected</th><th>Actual</th><th>Message</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderInteractiveMatrix(selftest) {
  if (!selftest || !selftest.cases || !selftest.cases.length) return "";
  const rows = selftest.cases.map((item) => {
    const transcript = (item.transcript || []).map((line) => `${line.direction}: ${line.text}`).join("\n");
    return `<tr><td>${escapeHtml(item.name)}</td><td>${escapeHtml(item.expected)}</td><td class="${item.pass ? "status-pass" : "status-fail"}">${escapeHtml(item.actual)}</td><td><pre class="inline-log">${escapeHtml(transcript)}</pre></td></tr>`;
  }).join("");
  return `<h3>Interactive self-test <span class="chip ${selftest.status === "pass" ? "AC" : "WA"}">${escapeHtml(selftest.status)}</span></h3><table class="table"><thead><tr><th>Case</th><th>Expected</th><th>Actual</th><th>Transcript</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderGroupMatrix(groups) {
  if (!groups || !groups.groups || !groups.groups.length) return "";
  const rows = groups.groups.map((item) => `<tr>
    <td>${escapeHtml(item.name)}</td>
    <td>${item.points}</td>
    <td class="${item.passed ? "status-pass" : "status-fail"}">${item.passed ? "pass" : "blocked"}</td>
    <td>${item.passedTests}/${item.tests}</td>
    <td>${escapeHtml((item.depends || []).join(", ") || "\u2014")}</td>
    <td>${escapeHtml((item.blockedBy || []).join(", ") || "\u2014")}</td>
  </tr>`).join("");
  return `<h3>Group scoring <span class="chip ${groups.allPassed ? "AC" : "WA"}">${groups.score}/${groups.maxScore}</span></h3><table class="table"><thead><tr><th>Group</th><th>Points</th><th>Status</th><th>Tests</th><th>Depends</th><th>Blocked by</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderReport(report) {
  const host = $("report-body");
  if (!report || report.status === "none") {
    host.innerHTML = `<div class="empty" style="margin:8vh auto 0"><h2>No verification yet</h2><p>Run the deterministic verifier to check the validator, references, negative solutions and statement.</p><button class="primary" data-action="verify">Run verification</button></div>`;
    host.querySelector('[data-action="verify"]').addEventListener("click", () => runToolJob("verify", { writeAnswers: false }));
    return;
  }
  const status = report.status || "unknown";
  const errors = report.errors || [];
  const warnings = report.warnings || [];
  const checks = report.checks || [];
  const tests = report.tests || [];
  const negative = report.negative || [];
  const counts = report.counts || {};
  const limits = report.limits || {};
  const stale = state.summary && state.summary.stale;
  const checkRows = checks.map((check) => `
    <tr><td>${escapeHtml(check.name)}</td><td class="status-${check.status}">${escapeHtml(check.status)}</td><td>${escapeHtml(check.detail)}</td></tr>
  `).join("");
  const testRows = tests.map((test) => {
    const verdicts = (test.solutions || []).map((s) => `<span class="chip ${escapeHtml(s.verdict)}">${escapeHtml(s.verdict)}</span> <span class="mono">${escapeHtml(s.path)}</span>`).join("<br>");
    return `<tr><td class="mono">${escapeHtml(test.test)}</td><td>${escapeHtml(test.kind)}</td><td>${verdicts || '<span class="muted">-</span>'}</td></tr>`;
  }).join("");
  const negativeRows = negative.map((item) => `
    <tr><td class="mono">${escapeHtml(item.path)}</td><td><span class="chip ${escapeHtml(item.status)}">${escapeHtml(item.status)}</span></td>
    <td class="mono">${item.test ? escapeHtml(item.test) + " / " + escapeHtml(item.verdict || "") : "-"}</td></tr>
  `).join("");
  host.innerHTML = `
    <div class="report-head">
      <span class="pill ${status === "verified" ? "verified" : "failed"}">${escapeHtml(status)}</span>
      <span class="big">${status === "verified" ? "Package verified" : "Verification failed"}</span>
    </div>
    <div class="report-sub">${escapeHtml(report.at || "")}${stale ? " · workspace changed since this run" : ""}</div>
    <div class="report-actions">
      <button class="primary small" data-action="verify">Verify again</button>
      ${errors.length ? '<button class="quiet small" data-action="fix">Fix with agent</button>' : ""}
    </div>
    ${errors.length ? `<h3>Errors</h3><ul class="report-list status-fail">${errors.map((e) => `<li>${escapeHtml(e)}</li>`).join("")}</ul>` : ""}
    ${warnings.length ? `<h3>Warnings</h3><ul class="report-list status-warn">${warnings.map((e) => `<li>${escapeHtml(e)}</li>`).join("")}</ul>` : ""}
    <h3>Evidence</h3>
    <table class="table"><tbody>
      <tr><td>Tests</td><td>${counts.tests || 0} total · ${counts.sample || 0} sample · ${counts.secret || 0} secret</td></tr>
      <tr><td>Accepted sources</td><td>${counts.accepted || 0}</td></tr>
      <tr><td>Negative sources</td><td>${counts.negative || 0}</td></tr>
      <tr><td>Time limit</td><td>${escapeHtml(String(limits.timeSeconds || "-"))} s</td></tr>
      <tr><td>Memory limit</td><td>${escapeHtml(String(limits.memoryMb || "not set"))} MiB</td></tr>
      <tr><td>Snapshot</td><td class="mono">${escapeHtml((report.snapshot || "").slice(0, 16))}</td></tr>
    </tbody></table>
    <h3>Checks</h3>
    <table class="table"><thead><tr><th>Check</th><th>Status</th><th>Detail</th></tr></thead><tbody>${checkRows || '<tr><td colspan="3" class="muted">none</td></tr>'}</tbody></table>
    ${renderCheckerMatrix(report.checkerSelftest)}
    ${renderInteractiveMatrix(report.interactiveSelftest)}
    ${renderGroupMatrix(report.groups)}
    <h3>Reference vs answers</h3>
    <table class="table"><thead><tr><th>Test</th><th>Kind</th><th>Reference verdict</th></tr></thead><tbody>${testRows || '<tr><td colspan="3" class="muted">none</td></tr>'}</tbody></table>
    <h3>Negative solutions</h3>
    <table class="table"><thead><tr><th>Program</th><th>Status</th><th>Killed by</th></tr></thead><tbody>${negativeRows || '<tr><td colspan="3" class="muted">none</td></tr>'}</tbody></table>
    ${report.validator && report.validator.some((v) => !v.valid) ? `<h3>Validator rejections</h3><ul class="report-list status-fail">${report.validator.filter((v) => !v.valid).map((v) => `<li>${escapeHtml(v.test)}: exit ${escapeHtml(String(v.exitCode))} ${escapeHtml(v.stderr || "")}</li>`).join("")}</ul>` : ""}
  `;
  const verify = host.querySelector('[data-action="verify"]');
  if (verify) verify.addEventListener("click", () => runToolJob("verify", { writeAnswers: false }));
  const fix = host.querySelector('[data-action="fix"]');
  if (fix) fix.addEventListener("click", () => {
    const message = `Verification failed. Fix these concrete issues, then re-run verify_package until the package is verified:\n\n${errors.map((e) => `- ${e}`).join("\n")}`;
    sendMessage(message);
  });
}

async function loadReport() {
  if (!state.slug) return;
  try {
    const report = await api(`/api/workspaces/${state.slug}/report`);
    renderReport(report);
    if (state.summary && state.summary.stale) setStatus("stale");
    else setStatus(report.status === "verified" || report.status === "failed" ? report.status : (state.summary && state.summary.lastStatus) || "unverified");
  } catch {
    renderReport({ status: "none" });
  }
}

// ---------- workspace ----------

async function refreshWorkspace() {
  if (!state.slug) return;
  try {
    const [summary, changeData] = await Promise.all([
      api(`/api/workspaces/${state.slug}`),
      api(`/api/workspaces/${state.slug}/changes`),
    ]);
    state.summary = summary;
    state.tree = summary.tree || [];
    state.changes = changeData.changes || [];
    setStatus(summary.lastStatus);
    renderProblemCard();
    renderTree();
    renderChanges();
    if (summary.lastReport) renderReport(summary.lastReport);
    renderPlan();
    renderStageRail();
    renderChatList();
  } catch (error) { toast(error.message, true); }
}

async function selectWorkspace(slug) {
  state.slug = slug || null;
  machineSet("editor", "empty", "workspace switch");
  machineSet("run", "hidden", "workspace switch");
  machineSet("turn", "idle", "workspace switch");
  machineSet("approval", "none", "workspace switch");
  state.summary = null;
  state.tree = [];
  state.changes = [];
  state.chats = [];
  state.chatId = null;
  state.plan = { steps: [] };
  state.file = null;
  state.dirty = false;
  state.pendingApproval = null;
  state.selectedContext = [];
  state.jobId = null;
  state.jobChatId = null;
  state.jobEvents = 0;
  resetStreaming();
  $("messages").innerHTML = "";
  state.fileMode = "view";
  $("file-editor").value = "";
  $("file-editor").disabled = true;
  $("file-editor").hidden = false;
  $("file-view").hidden = true;
  $("file-name").textContent = "No file selected";
  $("file-meta").textContent = "";
  $("save-file").hidden = true;
  $("reload-file").hidden = true;
  $("edit-file").hidden = true;
  $("view-file").hidden = true;
  $("run-panel").hidden = true;
  $("run-output").hidden = true;
  $("run-output").textContent = "";
  $("run-output").className = "run-output";
  $("diff-body").innerHTML = '<div class="pad muted">Select a change to inspect its diff.</div>';
  $("report-body").innerHTML = "";
  if (!slug) {
    document.querySelector(".problem-name").textContent = "No problem";
    document.querySelector(".problem-sub").textContent = "Create a workspace to begin";
    setStatus("unverified");
    $("messages").innerHTML = '<div class="empty"><h2>No problem selected</h2><p>Create a workspace to begin.</p></div>';
    renderPlan();
    renderChatList();
    return;
  }
  localStorage.setItem("author-agent-slug", slug);
  $("workspace-select").value = slug;
  $("mode-select").value = localStorage.getItem("author-agent-mode") || "author";
  loadTreeExpanded();
  await refreshWorkspace();
  await loadReport();
  loadContext();
  await loadChats();
  await loadConversation();
  renderPlan();
}

async function loadState(selectSlug) {
  machineSend("session", "LOAD");
  try {
    const data = await api("/api/state");
    state.settings = data.settings;
    state.tools = data.tools;
    const select = $("workspace-select");
    select.innerHTML = "";
    if (!data.workspaces.length) {
      select.innerHTML = '<option value="">No problems yet</option>';
    }
    for (const item of data.workspaces) {
      const option = document.createElement("option");
      option.value = item.slug;
      option.textContent = (item.status === "verified" ? "✓ " : "") + item.name;
      select.appendChild(option);
    }
    const remembered = selectSlug || localStorage.getItem("author-agent-slug");
    const slug = data.workspaces.some((w) => w.slug === remembered) ? remembered : (data.workspaces[0] && data.workspaces[0].slug);
    select.value = slug || "";
    await selectWorkspace(slug || null);
    machineSend("session", "READY");
  } catch (error) {
    machineSend("session", "ERROR");
    toast(error.message, true);
  }
}

// ---------- jobs ----------

function processJobEvents(job) {
  const events = job.events || [];
  for (let i = state.jobEvents; i < events.length; i += 1) {
    const event = events[i];
    const data = event.data || {};
    if (event.kind === "assistant") {
      finalizeAssistant(data.text);
      $("agent-state").textContent = "thinking…";
    } else if (event.kind === "assistant_delta") {
      appendAssistantDelta(data.text || "");
    } else if (event.kind === "reasoning") {
      finalizeReasoning(data.text || "");
    } else if (event.kind === "reasoning_delta") {
      appendReasoningDelta(data.text || "");
    } else if (event.kind === "thinking") {
      resetStreaming();
      $("agent-state").textContent = `thinking · step ${data.round || ""}`.trim();
    } else if (event.kind === "tool_call") {
      renderToolCall(data.name, data.args);
    } else if (event.kind === "tool_result") {
      renderToolResult(data.name, data.result);
      if (data.name === "update_plan" && data.result && data.result.steps) {
        state.plan = data.result;
        renderPlan();
      }
    } else if (event.kind === "change") {
      renderChangeEvent(data);
    } else if (event.kind === "verification") {
      renderVerificationEvent(data);
    } else if (event.kind === "plan") {
      state.plan = data;
      renderPlan();
    } else if (event.kind === "error") {
      renderErrorEvent(data);
    } else if (event.kind === "cancelled") {
      const node = document.createElement("div");
      node.className = "event-verify bad";
      node.textContent = "Stopped by user.";
      addEventCard(node);
      $("agent-state").textContent = "";
    } else if (event.kind === "timeout") {
      const node = document.createElement("div");
      node.className = "event-verify bad";
      node.textContent = data.message || "Job exceeded its time limit.";
      addEventCard(node);
      $("agent-state").textContent = "stopping…";
    } else if (event.kind === "report") {
      if (job.state !== "running") renderReport(data);
    } else if (event.kind === "export") {
      toast(`Exported ${data.files || 0} files`);
      window.location.href = `/api/workspaces/${state.slug}/download`;
    } else if (event.kind === "answers") {
      renderVerificationEvent({ stage: "answers", result: data });
    } else if (event.kind === "limits") {
      const node = document.createElement("div");
      node.className = "event-verify ok";
      node.textContent = `Limits measured: ${data.timeLimitSeconds}s time / ${data.memoryMb} MiB memory (slowest ${data.slowestTest || "n/a"}, ${data.maxRuntimeMs} ms).`;
      addEventCard(node);
      toast(`Limits: ${data.timeLimitSeconds}s / ${data.memoryMb} MiB`);
    } else if (event.kind === "usage") {
      renderUsage(data);
    } else if (event.kind === "approval") {
      state.pendingApproval = data.interrupts || [];
    }
  }
  state.jobEvents = events.length;
}

function pollJob(jobId, onDone) {
  if (state.pollTimer) clearTimeout(state.pollTimer);
  const jobSlug = state.slug;
  const tick = async () => {
    if (state.slug !== jobSlug) {
      $("agent-state").textContent = "";
      $("send-btn").disabled = false;
      return;
    }
    try {
      const job = await api(`/api/jobs/${jobId}`);
      processJobEvents(job);
      if (job.state === "running") {
        state.pollTimer = setTimeout(tick, 700);
        return;
      }
      if (job.state === "paused") {
        state.jobId = null;
        state.jobChatId = null;
        state.pendingApproval = (job.result && job.result.interrupts) || [];
        if (state.pendingApproval.length) {
          machineSend("approval", "ASK");
          machineSend("turn", "WAIT");
        } else {
          machineSend("turn", "DONE");
        }
        $("agent-state").textContent = "";
        $("send-btn").disabled = true;
        await refreshWorkspace();
        await loadChats(state.chatId);
        await loadConversation();
        return;
      }
      $("agent-state").textContent = "";
      $("send-btn").disabled = false;
      const wasCancelled = job.state === "cancelled";
      state.jobId = null;
      state.jobChatId = null;
      machineSend("turn", "DONE");
      machineSend("approval", "CLEAR");
      await refreshWorkspace();
      await loadReport();
      await loadChats(state.chatId);
      if (state.chatId) await loadConversation();
      else renderChatList();
      if (wasCancelled) toast("Stopped");
      if (onDone) await onDone(job);
      const pending = state.pendingMessage;
      state.pendingMessage = null;
      if (pending && !state.jobId) await sendMessage(pending);
    } catch (error) {
      $("agent-state").textContent = "";
      $("send-btn").disabled = false;
      state.jobId = null;
      state.jobChatId = null;
      machineSend("turn", "FAIL");
      machineSend("approval", "CLEAR");
      toast(error.message, true);
    }
  };
  state.pollTimer = setTimeout(tick, 400);
}

async function sendMessage(override) {
  if (!state.slug) { toast("Create or select a problem first", true); return; }
  if (state.pendingApproval) {
    toast("Approve or reject the pending action first", true);
    return;
  }
  const composer = $("composer");
  const message = (override ?? composer.value).trim();
  if (!message) return;
  if (state.jobId) {
    state.pendingMessage = message;
    if (!override) composer.value = "";
    toast("Queued; it will send when the current job finishes");
    return;
  }
  let userMessage = null;
  try {
    if (!state.chatId) {
      await loadChats();
      if (!state.chatId) await newChat();
    }
    if (!state.chatId) throw new Error("Could not create a chat");
    if (!override) composer.value = "";
    userMessage = addMessage("user", message);
    const chat = state.chats.find((c) => c.id === state.chatId);
    if (chat && (!chat.title || chat.title === "New chat")) {
      chat.title = truncate(message, 70);
      renderChatList();
    }
    $("agent-state").textContent = "sending…";
    const job = await api(`/api/workspaces/${state.slug}/chat`, {
      method: "POST",
      body: {
        message,
        chatId: state.chatId,
        mode: $("mode-select").value || "author",
        context: state.selectedContext,
      },
    });
    state.jobId = job.id;
    state.jobChatId = job.chatId || state.chatId;
    state.jobEvents = 0;
    machineSend("turn", "START");
    machineSend("approval", "CLEAR");
    resetStreaming();
    $("send-btn").disabled = true;
    $("agent-state").textContent = "starting…";
    renderChatList();
    pollJob(job.id);
  } catch (error) {
    if (userMessage && userMessage.parentNode) userMessage.remove();
    if (!override) composer.value = message;
    $("agent-state").textContent = "";
    $("send-btn").disabled = false;
    machineSend("turn", "FAIL");
    toast(error.message, true);
    renderErrorEvent({ error: "Could not send message: " + error.message });
  }
}

async function runToolJob(kind, body) {
  if (!state.slug) return;
  if (state.jobId) { toast("Wait for the current job to finish", true); return; }
  try {
    const job = await api(`/api/workspaces/${state.slug}/${kind}`, { method: "POST", body: body || {} });
    state.jobId = job.id;
    state.jobChatId = null;
    state.jobEvents = 0;
    machineSend("turn", "START");
    $("send-btn").disabled = true;
    $("agent-state").textContent = kind === "verify" ? "verifying…"
      : kind === "answers" ? "building answers…"
      : kind === "measure-limits" ? "measuring limits…"
      : "exporting…";
    renderChatList();
    pollJob(job.id, async (finished) => {
      if (kind === "verify") {
        switchTab("report");
        if (finished.state === "done") toast(finished.result.status === "verified" ? "Package verified" : "Verification failed", finished.result.status !== "verified");
      }
      if (kind === "answers") toast("Answers generated");
      if (kind === "measure-limits") {
        switchTab("plan");
        if (finished.state === "done") toast(`Limits: ${finished.result.timeLimitSeconds}s / ${finished.result.memoryMb} MiB`);
      }
      if (kind === "export") toast("Package exported");
    });
  } catch (error) { toast(error.message, true); }
}

// ---------- navigation ----------

async function loadHistory() {
  const host = $("history-body");
  if (!host) return;
  if (!state.slug || !state.chatId) { host.innerHTML = '<div class="pad muted">Open a chat first.</div>'; return; }
  host.innerHTML = '<div class="pad muted">Loading checkpoints?</div>';
  try {
    const [history, snapshots] = await Promise.all([
      api(`/api/workspaces/${state.slug}/chats/${state.chatId}/history`),
      api(`/api/workspaces/${state.slug}/snapshots?chatId=${encodeURIComponent(state.chatId)}`),
    ]);
    const rows = (history.history || []).map((item) => `<tr><td class="mono">${escapeHtml(String(item.checkpointId || "").slice(0, 18))}</td><td>${escapeHtml(item.createdAt || "")}</td><td>${item.messages}</td><td>${escapeHtml(item.lastUser || "")}</td><td><button class="quiet small" data-restore="${escapeHtml(item.checkpointId)}">Restore chat</button></td></tr>`).join("");
    const snaps = (snapshots.snapshots || []).map((item) => `<tr><td class="mono">${escapeHtml(item.id)}</td><td>${escapeHtml(item.at || "")}</td><td>${Math.round((item.size || 0) / 1024)} KiB</td><td><button class="quiet small" data-snapshot="${escapeHtml(item.id)}">Restore files</button></td></tr>`).join("");
    host.innerHTML = `<h3>Conversation checkpoints</h3><table class="table"><thead><tr><th>Checkpoint</th><th>Created</th><th>Messages</th><th>Last user</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="5" class="muted">none</td></tr>'}</tbody></table><h3>Workspace snapshots</h3><table class="table"><thead><tr><th>Snapshot</th><th>Created</th><th>Size</th><th></th></tr></thead><tbody>${snaps || '<tr><td colspan="5" class="muted">none</td></tr>'}</tbody></table>`;
    host.querySelectorAll("[data-restore]").forEach((button) => button.addEventListener("click", () => restoreCheckpoint(button.dataset.restore)));
    host.querySelectorAll("[data-snapshot]").forEach((button) => button.addEventListener("click", () => restoreFiles(button.dataset.snapshot)));
  } catch (error) { host.innerHTML = `<div class="pad status-fail">${escapeHtml(error.message)}</div>`; }
}

async function restoreCheckpoint(checkpointId) {
  const ok = await actionDialog({
    kicker: "History",
    title: "Restore conversation?",
    description: "The current checkpoint thread will be replaced by this checkpoint.",
    confirmLabel: "Restore chat",
  });
  if (!ok) return;
  try {
    await api(`/api/workspaces/${state.slug}/chats/${state.chatId}/history/${encodeURIComponent(checkpointId)}/restore`, { method: "POST", body: {} });
    await loadConversation();
    await loadHistory();
    toast("Conversation restored");
  } catch (error) { toast(error.message, true); }
}

async function restoreFiles(snapshotId) {
  const ok = await actionDialog({
    kicker: "History",
    title: "Restore workspace files?",
    description: "Current files will be replaced by this snapshot.",
    confirmLabel: "Restore files",
    danger: true,
  });
  if (!ok) return;
  try {
    await api(`/api/workspaces/${state.slug}/snapshots/restore`, { method: "POST", body: { chatId: state.chatId, snapshotId } });
    await refreshWorkspace();
    if (state.file) await openFile(state.file.path);
    toast("Workspace files restored");
  } catch (error) { toast(error.message, true); }
}

async function loadMcp() {
  const host = $("mcp-body");
  if (!host) return;
  if (!state.slug) { host.innerHTML = '<div class="pad muted">Open a workspace first.</div>'; return; }
  host.innerHTML = '<div class="pad muted">Loading MCP consent…</div>';
  try {
    const data = await api(`/api/workspaces/${state.slug}/mcp`);
    const consent = data.consent || {};
    const tools = data.tools || [];
    const rows = tools.map((tool) => {
      const granted = Boolean((consent.tools || {})[tool.name]);
      const defaultArg = tool.name === "read_file" ? "problem.yaml" : tool.name === "search_workspace" ? "problem" : "";
      const wantsArg = tool.name === "read_file" || tool.name === "search_workspace";
      const arg = wantsArg
        ? `<input class="mcp-arg" data-mcp-arg="${escapeHtml(tool.name)}" value="${escapeHtml(defaultArg)}" placeholder="relative path" aria-label="${escapeHtml(tool.name)} argument">`
        : `<span class="mcp-noarg">no argument</span>`;
      return `<div class="mcp-tool">
        <div class="mcp-tool-head">
          <span class="mcp-tool-name">${escapeHtml(tool.name)}</span>
          <label class="check"><input type="checkbox" data-mcp-tool="${escapeHtml(tool.name)}" aria-label="Allow ${escapeHtml(tool.name)}" ${granted ? "checked" : ""}> allow</label>
        </div>
        <div class="mcp-tool-desc" title="${escapeHtml(tool.description)}">${escapeHtml(tool.description)}</div>
        <div class="mcp-tool-actions">${arg}<button class="quiet small" data-mcp-test="${escapeHtml(tool.name)}" aria-label="Probe ${escapeHtml(tool.name)}">Test</button></div>
      </div>`;
    }).join("");
    host.innerHTML = `
      <div class="mcp-head">
        <div>
          <h3>MCP host consent</h3>
          <p class="muted small">The scoped server is read-only. Nothing is callable until you explicitly grant it here. Roots restrict which workspace paths the server may read.</p>
        </div>
        <span class="chip ${consent.enabled ? "AC" : "WA"}">${consent.enabled ? "enabled" : "disabled"}</span>
      </div>
      <label class="check"><input id="mcp-enabled" type="checkbox" ${consent.enabled ? "checked" : ""}> Enable the MCP server for this workspace</label>
      <label>Consented roots (comma separated, workspace-relative)
        <input id="mcp-roots" value="${escapeHtml((consent.roots || ["."]).join(", "))}" placeholder="., data/sample">
      </label>
      <div class="mcp-tools">${rows || '<div class="muted small">none</div>'}</div>
      <div class="mcp-footer">
        <button id="mcp-save" class="primary small">Save consent</button>
        <span id="mcp-test-result" class="muted small"></span>
      </div>
      <p class="muted small">Protocol ${escapeHtml(data.protocol || "")} \u00b7 ${escapeHtml(data.server || "")}. Secret test data is never exposed.</p>`;
    $("mcp-save").addEventListener("click", saveMcp);
    host.querySelectorAll("[data-mcp-test]").forEach((button) => button.addEventListener("click", () => testMcpTool(button.dataset.mcpTest)));
  } catch (error) { host.innerHTML = `<div class="pad status-fail">${escapeHtml(error.message)}</div>`; }
}

async function saveMcp() {
  if (!state.slug) return;
  const tools = {};
  document.querySelectorAll("[data-mcp-tool]").forEach((box) => { tools[box.dataset.mcpTool] = box.checked; });
  const roots = ($("mcp-roots").value || ".").split(",").map((item) => item.trim()).filter(Boolean);
  try {
    await api(`/api/workspaces/${state.slug}/mcp`, { method: "POST", body: { enabled: $("mcp-enabled").checked, tools, roots } });
    toast("MCP consent saved");
    await loadMcp();
  } catch (error) { toast(error.message, true); }
}

async function testMcpTool(tool) {
  if (!state.slug) return;
  const output = $("mcp-test-result");
  if (output) output.textContent = "Testing…";
  try {
    const result = await api(`/api/workspaces/${state.slug}/mcp/test`, { method: "POST", body: { tool, arguments: {} } });
    const text = JSON.stringify(result.response || result).slice(0, 400);
    if (output) output.textContent = (result.ok ? "OK " : "DENIED ") + text;
  } catch (error) {
    if (output) output.textContent = error.message;
  }
}

function switchTab(tab) {
  if (tab === "history") loadHistory();
  if (tab === "mcp") loadMcp();
  state.activeTab = tab;
  document.body.setAttribute("data-panel", tab);
  document.querySelectorAll(".inspector-tabs button").forEach((button) => {
    const active = button.dataset.tab === tab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === "panel-" + tab);
  });
}

function switchSide(side) {
  state.activeSide = side;
  document.body.setAttribute("data-side", side);
  document.querySelectorAll(".side-tabs button").forEach((button) => {
    const active = button.dataset.side === side;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".side-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === "side-" + side);
  });
}

// ---------- dialogs ----------

let actionDialogResolve = null;
let actionDialogOptions = {};
let actionDialogInvoker = null;

// Accessible replacement for window.prompt/window.confirm. Native <dialog>
// supplies the focus trap, Escape handling and focus return; this helper adds
// inline validation, destructive styling and a promise-based API.
function actionDialog(options = {}) {
  const dialog = $("action-dialog");
  const promptMode = options.mode === "prompt" || options.input !== undefined || options.value !== undefined || options.inputLabel !== undefined;
  if (dialog.open) return Promise.resolve(promptMode ? null : false);
  actionDialogInvoker = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  actionDialogOptions = { ...options, prompt: promptMode };
  $("action-form").reset();
  $("action-kicker").textContent = options.kicker || (promptMode ? "Edit" : "Confirm");
  $("action-title").textContent = options.title || (promptMode ? "Edit value" : "Confirm action");
  const desc = $("action-desc");
  desc.textContent = options.description || "";
  desc.hidden = !options.description;
  const field = $("action-field");
  const input = $("action-input");
  field.hidden = !promptMode;
  $("action-field-label").textContent = options.inputLabel || "Value";
  input.placeholder = options.placeholder || "";
  input.value = promptMode ? String(options.value ?? "") : "";
  const error = $("action-error");
  error.hidden = true;
  error.textContent = "";
  const confirm = $("action-confirm");
  confirm.textContent = options.confirmLabel || (promptMode ? "Save" : "Confirm");
  confirm.classList.toggle("danger", Boolean(options.danger));
  $("action-cancel").textContent = options.cancelLabel || "Cancel";
  dialog.returnValue = "";
  dialog.showModal();
  machineSend("modal", "OPEN");
  if (promptMode) {
    input.focus();
    input.select();
  } else {
    confirm.focus();
  }
  return new Promise((resolve) => {
    actionDialogResolve = resolve;
  });
}

$("action-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!$("action-field").hidden) {
    const value = $("action-input").value.trim();
    const message = actionDialogOptions.validate
      ? actionDialogOptions.validate(value)
      : (!value ? "Enter a value." : "");
    if (message) {
      const error = $("action-error");
      error.textContent = message;
      error.hidden = false;
      $("action-input").focus();
      return;
    }
  }
  $("action-dialog").close("confirm");
});

$("action-dialog").addEventListener("close", () => {
  machineSend("modal", "CLOSE");
  const resolve = actionDialogResolve;
  actionDialogResolve = null;
  if (!resolve) return;
  const confirmed = $("action-dialog").returnValue === "confirm";
  const promptMode = Boolean(actionDialogOptions.prompt);
  resolve(confirmed ? (promptMode ? $("action-input").value.trim() : true) : (promptMode ? null : false));
  const invoker = actionDialogInvoker;
  actionDialogInvoker = null;
  const focusTarget = invoker && invoker.isConnected && invoker.offsetParent !== null
    ? invoker
    : document.getElementById("composer");
  if (focusTarget && typeof focusTarget.focus === "function") {
    focusTarget.focus({ preventScroll: true });
  }
});

function openSettings() {
  const form = $("settings-form");
  const settings = state.settings || {};
  form.baseUrl.value = settings.baseUrl || "";
  form.model.value = settings.model || "";
  form.apiKey.value = "";
  form.temperature.value = settings.temperature ?? 0.2;
  form.maxToolRounds.value = settings.maxToolRounds ?? 24;
  form.contextBudgetTokens.value = settings.contextBudgetTokens ?? 500000;
  form.modelWindowTokens.value = settings.modelWindowTokens ?? 1048576;
  form.maxOutputTokens.value = settings.maxOutputTokens ?? 393216;
  form.summaryTriggerTokens.value = settings.summaryTriggerTokens ?? 500000;
  form.summaryKeepMessages.value = settings.summaryKeepMessages ?? 24;
  form.maxRetries.value = settings.maxRetries ?? 2;
  form.requestTimeoutSeconds.value = settings.requestTimeoutSeconds ?? 300;
  form.fallbackModel.value = settings.fallbackModel || "";
  form.fallbackBaseUrl.value = settings.fallbackBaseUrl || "";
  form.fallbackApiKey.value = "";
  form.judge0Url.value = settings.judge0Url || "";
  form.isolateUrl.value = settings.isolateUrl || "";
  form.judge0Token.value = "";
  form.inputPricePerMillion.value = settings.inputPricePerMillion ?? 0;
  form.outputPricePerMillion.value = settings.outputPricePerMillion ?? 0;
  form.clearKey.checked = false;
  form.reviewWrites.checked = Boolean(settings.reviewWrites);
  $("key-status").textContent = settings.hasKey ? `A key ending in ${settings.keyHint} is saved.` : "No API key saved yet.";
  $("settings-dialog").showModal();
}

async function saveSettings(event) {
  event.preventDefault();
  const form = $("settings-form");
  const body = {
    baseUrl: form.baseUrl.value.trim(),
    model: form.model.value.trim(),
    temperature: Number(form.temperature.value || 0.2),
    maxToolRounds: Number(form.maxToolRounds.value || 24),
    contextBudgetTokens: Number(form.contextBudgetTokens.value || 500000),
    modelWindowTokens: Number(form.modelWindowTokens.value || 1048576),
    maxOutputTokens: Number(form.maxOutputTokens.value || 393216),
    summaryTriggerTokens: Number(form.summaryTriggerTokens.value || 500000),
    summaryKeepMessages: Number(form.summaryKeepMessages.value || 24),
    maxRetries: Number(form.maxRetries.value || 2),
    requestTimeoutSeconds: Number(form.requestTimeoutSeconds.value || 300),
    fallbackModel: form.fallbackModel.value.trim(),
    fallbackBaseUrl: form.fallbackBaseUrl.value.trim(),
    judge0Url: form.judge0Url.value.trim(),
    isolateUrl: form.isolateUrl.value.trim(),
    inputPricePerMillion: Number(form.inputPricePerMillion.value || 0),
    outputPricePerMillion: Number(form.outputPricePerMillion.value || 0),
    reviewWrites: form.reviewWrites.checked,
    clearKey: form.clearKey.checked,
  };
  if (form.apiKey.value.trim()) body.apiKey = form.apiKey.value.trim();
  if (form.fallbackApiKey.value.trim()) body.fallbackApiKey = form.fallbackApiKey.value.trim();
  if (form.judge0Token.value.trim()) body.judge0Token = form.judge0Token.value.trim();
  try {
    state.settings = await api("/api/settings", { method: "POST", body });
    $("settings-dialog").close();
    toast("Settings saved");
  } catch (error) { toast(error.message, true); }
}

async function createProblem(event) {
  event.preventDefault();
  const form = $("new-form");
  const name = form.querySelector('[name="name"]').value.trim();
  const startNow = form.startNow.checked;
  if (!name) return;
  try {
    const created = await api("/api/workspaces", {
      method: "POST",
      body: {
        name,
        idea: form.idea.value.trim(),
        author: form.author.value.trim(),
        shortName: form.shortName.value.trim(),
      },
    });
    $("new-dialog").close();
    form.reset();
    await loadState(created.slug);
    toast("Workspace created");
    if (startNow) {
      await sendMessage("Author this problem end-to-end from the idea in NOTES.md. State your assumptions in NOTES.md, publish a plan, draft the statement, validator, reference solution, samples, secret edge cases and at least one negative solution, then generate answers and iterate with verify_package until the package is verified. Only ask me when a rule is genuinely ambiguous.");
    }
  } catch (error) { toast(error.message, true); }
}

// ---------- context / mode / approvals ----------

function renderContextChips() {
  const host = $("context-chips");
  host.innerHTML = "";
  for (const path of state.selectedContext) {
    const chip = document.createElement("span");
    chip.className = "context-chip";
    chip.textContent = path.split("/").pop();
    chip.title = path;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `Remove ${path} from context`);
    remove.addEventListener("click", () => {
      state.selectedContext = state.selectedContext.filter((item) => item !== path);
      saveContext();
      renderContextChips();
    });
    chip.appendChild(remove);
    host.appendChild(chip);
  }
}

function contextStorageKey() {
  return "author-agent-context-" + state.slug;
}

function saveContext() {
  if (state.slug) localStorage.setItem(contextStorageKey(), JSON.stringify(state.selectedContext));
}

function loadContext() {
  state.selectedContext = [];
  if (!state.slug) return;
  try {
    const value = JSON.parse(localStorage.getItem(contextStorageKey()) || "[]");
    if (Array.isArray(value)) state.selectedContext = value.filter((item) => typeof item === "string");
  } catch { state.selectedContext = []; }
  renderContextChips();
}

function openContextDialog() {
  const list = $("context-list");
  list.innerHTML = "";
  const files = state.tree.filter((row) => row.type === "file" && row.text && !row.path.startsWith("data/secret/") && !row.path.endsWith(".ans"));
  if (!files.length) {
    list.innerHTML = '<div class="muted small">No selectable text files.</div>';
  }
  for (const row of files) {
    const label = document.createElement("label");
    label.className = "context-row";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = row.path;
    box.checked = state.selectedContext.includes(row.path);
    const text = document.createElement("span");
    text.textContent = row.path;
    label.appendChild(box);
    label.appendChild(text);
    list.appendChild(label);
  }
  $("context-dialog").showModal();
}

function applyContext(event) {
  event.preventDefault();
  const checked = [...$("context-list").querySelectorAll('input[type="checkbox"]:checked')].map((box) => box.value);
  state.selectedContext = checked;
  saveContext();
  renderContextChips();
  $("context-dialog").close();
}

function renderUsage(data) {
  const card = document.createElement("div");
  card.className = "usage-card";
  const values = [];
  if (data.input_tokens) values.push(`${data.input_tokens} in`);
  if (data.output_tokens) values.push(`${data.output_tokens} out`);
  if (data.total_tokens) values.push(`${data.total_tokens} total`);
  if (data.costUsd) values.push(`$${Number(data.costUsd).toFixed(6)}`);
  card.textContent = `Tokens: ${values.join(" · ") || "provider did not report usage"}`;
  addEventCard(card);
}

function approvalActions(value) {
  if (!value || typeof value !== "object") return [{ name: "Action", args: {}, id: null }];
  if (Array.isArray(value.action_requests)) {
    return value.action_requests.map((item) => ({ name: item.name, args: item.args || {}, description: item.description, id: null }));
  }
  return [{ name: value.name || "Action", args: value.args || {}, description: value.description, id: value.tool_call_id || null }];
}

function renderApproval(interrupts) {
  if (!interrupts || !interrupts.length) return;
  const clarifications = interrupts.filter((item) => item.value && item.value.type === "clarification");
  if (clarifications.length) {
    renderClarification(clarifications);
    return;
  }
  if (state.approvalRendered || document.querySelector(".approval-card")) return;
  state.pendingApproval = interrupts;
  state.approvalRendered = true;
  const card = document.createElement("div");
  card.className = "approval-card";
  const title = document.createElement("div");
  title.className = "approval-title";
  title.textContent = interrupts.length > 1 ? "Approval required (multiple actions)" : "Approval required";
  card.appendChild(title);
  for (const item of interrupts) {
    const value = item.value || {};
    for (const action of approvalActions(value)) {
      const row = document.createElement("div");
      row.className = "approval-action";
      const label = document.createElement("div");
      label.textContent = action.name;
      const pre = document.createElement("pre");
      pre.textContent = JSON.stringify(action.args, null, 2);
      const description = document.createElement("div");
      description.className = "muted small";
      description.textContent = action.description || "";
      row.appendChild(label);
      row.appendChild(pre);
      if (description.textContent) row.appendChild(description);
      card.appendChild(row);
    }
  }
  const buttons = document.createElement("div");
  buttons.className = "approval-actions";
  const approve = document.createElement("button");
  approve.className = "primary small";
  approve.textContent = "Approve all";
  approve.addEventListener("click", () => resumeApproval("approve"));
  const reject = document.createElement("button");
  reject.className = "quiet small";
  reject.textContent = "Reject all";
  reject.addEventListener("click", () => resumeApproval("reject"));
  buttons.appendChild(approve);
  buttons.appendChild(reject);
  card.appendChild(buttons);
  addEventCard(card);
  $("send-btn").disabled = true;
}

function renderClarification(interrupts) {
  state.pendingApproval = interrupts;
  const card = document.createElement("div");
  card.className = "approval-card clarification-card";
  const title = document.createElement("div");
  title.className = "approval-title";
  title.textContent = "Clarification needed";
  card.appendChild(title);
  const inputs = [];
  for (const item of interrupts) {
    const value = item.value || {};
    if (value.context) {
      const context = document.createElement("div");
      context.className = "muted small";
      context.textContent = value.context;
      card.appendChild(context);
    }
    for (const [index, question] of (value.questions || []).entries()) {
      const label = document.createElement("label");
      label.className = "clarification-question";
      label.textContent = question;
      const area = document.createElement("textarea");
      area.rows = 2;
      area.placeholder = value.recommended ? `Recommended: ${value.recommended}` : "Your answer";
      area.value = value.recommended || "";
      area.dataset.question = String(index);
      label.appendChild(area);
      card.appendChild(label);
      inputs.push(area);
    }
    if (value.options && value.options.length) {
      const hint = document.createElement("div");
      hint.className = "muted small";
      hint.textContent = "Options: " + value.options.join(" ? ");
      card.appendChild(hint);
    }
  }
  const buttons = document.createElement("div");
  buttons.className = "approval-actions";
  const submit = document.createElement("button");
  submit.className = "primary small";
  submit.textContent = "Submit answer";
  submit.addEventListener("click", () => resumeClarification(inputs.map((input) => input.value.trim())));
  buttons.appendChild(submit);
  card.appendChild(buttons);
  addEventCard(card);
  $("send-btn").disabled = true;
}

async function resumeClarification(answers) {
  if (!state.slug || !state.chatId) return;
  try {
    const job = await api(`/api/workspaces/${state.slug}/chats/${state.chatId}/resume`, {
      method: "POST",
      body: { clarification: { answers } },
    });
    state.pendingApproval = null;
    document.querySelectorAll(".clarification-card").forEach((card) => card.remove());
    state.jobId = job.id;
    state.jobChatId = state.chatId;
    state.jobEvents = 0;
    machineSend("turn", "RESUME");
    machineSend("approval", "RESOLVE");
    $("send-btn").disabled = true;
    $("agent-state").textContent = "resuming\u2026";
    pollJob(job.id);
  } catch (error) { toast(error.message, true); }
}

async function resumeApproval(decision) {
  if (!state.slug || !state.chatId) return;
  const interrupts = state.pendingApproval || [];
  const batched = interrupts.some((item) => item.value && Array.isArray(item.value.action_requests));
  const decisions = batched
    ? { decisions: interrupts.flatMap((item) => (item.value.action_requests || []).map(() => ({ type: decision }))) }
    : Object.fromEntries(interrupts.map((item) => [item.id, { type: decision }]));
  try {
    const job = await api(`/api/workspaces/${state.slug}/chats/${state.chatId}/resume`, {
      method: "POST",
      body: { decisions },
    });
    state.pendingApproval = null;
    document.querySelectorAll(".approval-card").forEach((card) => card.remove());
    state.jobId = job.id;
    state.jobChatId = state.chatId;
    state.jobEvents = 0;
    machineSend("turn", "RESUME");
    machineSend("approval", "RESOLVE");
    $("send-btn").disabled = true;
    $("agent-state").textContent = "resuming…";
    pollJob(job.id);
  } catch (error) {
    toast(error.message, true);
  }
}

// ---------- resizable panes ----------

function applyStoredWidths() {
  const left = localStorage.getItem("author-agent-left-width");
  const right = localStorage.getItem("author-agent-right-width");
  if (left) document.documentElement.style.setProperty("--left-width", left + "px");
  if (right) document.documentElement.style.setProperty("--right-width", right + "px");
}

function initSplitters() {
  const layout = document.querySelector(".layout");
  const leftPane = document.querySelector(".left");
  const rightPane = document.querySelector(".right");
  document.querySelectorAll(".splitter").forEach((splitter) => {
    splitter.addEventListener("mousedown", (event) => {
      event.preventDefault();
      const isLeft = splitter.dataset.split === "left";
      const startX = event.clientX;
      const startLeft = leftPane.getBoundingClientRect().width;
      const startRight = rightPane.getBoundingClientRect().width;
      document.body.classList.add("resizing");
      const move = (moveEvent) => {
        const dx = moveEvent.clientX - startX;
        if (isLeft) {
          const width = Math.max(200, Math.min(520, startLeft + dx));
          document.documentElement.style.setProperty("--left-width", width + "px");
          localStorage.setItem("author-agent-left-width", String(Math.round(width)));
        } else {
          const width = Math.max(320, Math.min(820, startRight - dx));
          document.documentElement.style.setProperty("--right-width", width + "px");
          localStorage.setItem("author-agent-right-width", String(Math.round(width)));
        }
      };
      const up = () => {
        document.removeEventListener("mousemove", move);
        document.removeEventListener("mouseup", up);
        document.body.classList.remove("resizing");
      };
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", up);
    });
    splitter.addEventListener("dblclick", () => {
      if (splitter.dataset.split === "left") {
        document.documentElement.style.setProperty("--left-width", "272px");
        localStorage.removeItem("author-agent-left-width");
      } else {
        document.documentElement.style.setProperty("--right-width", "440px");
        localStorage.removeItem("author-agent-right-width");
      }
    });
  });
}

// ---------- wiring ----------

function wire() {
  $("workspace-select").addEventListener("change", (event) => selectWorkspace(event.target.value || null));
  $("new-problem").addEventListener("click", () => $("new-dialog").showModal());
  $("new-cancel").addEventListener("click", () => $("new-dialog").close());
  $("new-form").addEventListener("submit", createProblem);
  $("settings-btn").addEventListener("click", openSettings);
  $("settings-cancel").addEventListener("click", () => $("settings-dialog").close());
  $("settings-form").addEventListener("submit", saveSettings);
  $("refresh-tree").addEventListener("click", async () => { await refreshWorkspace(); toast("Refreshed"); });
  $("new-file").addEventListener("click", () => newEntry("file", ""));
  $("new-folder").addEventListener("click", () => newEntry("dir", ""));
  $("send-btn").addEventListener("click", () => sendMessage());
  $("composer").addEventListener("input", renderMentions);
  $("composer").addEventListener("click", renderMentions);
  $("composer").addEventListener("keydown", (event) => {
    if (event.key === "Escape") hideMentions();
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); sendMessage(); }
  });
  $("verify-btn").addEventListener("click", () => runToolJob("verify", { writeAnswers: false }));
  $("answers-btn").addEventListener("click", () => runToolJob("answers", {}));
  $("limits-btn").addEventListener("click", () => runToolJob("measure-limits", {}));
  $("export-btn").addEventListener("click", () => runToolJob("export", {}));
  $("approve-btn").addEventListener("click", async () => {
    if (!state.slug) return;
    try { await api(`/api/workspaces/${state.slug}/review`, { method: "POST" }); await refreshWorkspace(); toast("Changes marked reviewed"); }
    catch (error) { toast(error.message, true); }
  });
  $("revert-unreviewed").addEventListener("click", revertAllUnreviewed);
  $("new-chat").addEventListener("click", newChat);
  $("chat-search").addEventListener("input", (event) => {
    state.chatQuery = event.target.value || "";
    renderChatList();
  });
  $("mode-select").addEventListener("change", (event) => {
    localStorage.setItem("author-agent-mode", event.target.value || "author");
  });
  $("context-btn").addEventListener("click", openContextDialog);
  $("context-cancel").addEventListener("click", () => $("context-dialog").close());
  $("context-form").addEventListener("submit", applyContext);
  $("follow-btn").addEventListener("click", () => setFollow(true));
  $("messages").addEventListener("scroll", () => {
    const host = $("messages");
    const nearBottom = host.scrollHeight - host.scrollTop - host.clientHeight < 80;
    if (!nearBottom && state.follow) setFollow(false);
    else if (nearBottom && !state.follow) setFollow(true);
  });
  $("stop-btn").addEventListener("click", async () => {
    if (!state.jobId) return;
    try {
      await api(`/api/jobs/${state.jobId}/cancel`, { method: "POST", body: {} });
      $("agent-state").textContent = "stopping…";
      $("stop-btn").disabled = true;
    } catch (error) { toast(error.message, true); }
  });
  $("reload-chat").addEventListener("click", async () => { if (state.jobId) return; await loadChats(state.chatId); await loadConversation(); });
  $("plan-strip").addEventListener("click", () => switchTab("plan"));
  $("file-editor").addEventListener("input", () => {
    state.dirty = true;
    $("save-file").hidden = false;
    updateEditorChrome();
  });
  $("file-editor").addEventListener("scroll", () => {
    $("line-numbers").scrollTop = $("file-editor").scrollTop;
  });
  $("file-editor").addEventListener("keyup", updateEditorChrome);
  $("file-editor").addEventListener("click", updateEditorChrome);
  $("save-file").addEventListener("click", saveFile);
  $("reload-file").addEventListener("click", () => state.file && openFile(state.file.path));
  $("edit-file").addEventListener("click", enterEditMode);
  $("view-file").addEventListener("click", enterViewMode);
  $("run-file").addEventListener("click", runFile);
  $("judge0-run").addEventListener("click", runJudge0);
  $("isolate-run").addEventListener("click", runIsolate);
  $("run-tests").addEventListener("click", runSamples);
  $("load-sample").addEventListener("click", () => loadSampleInput());
  document.querySelectorAll(".tabs button, .inspector-tabs button").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });
  document.querySelectorAll(".side-tabs button").forEach((button) => {
    button.addEventListener("click", () => switchSide(button.dataset.side));
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest("#mention-menu") && event.target.id !== "composer") hideMentions();
  });
  window.addEventListener("beforeunload", (event) => {
    if (!state.dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });
}

applyStoredWidths();
initSplitters();
wire();
loadState();
