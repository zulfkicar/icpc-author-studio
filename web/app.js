const $ = (id) => document.getElementById(id);

const state = {
  slug: null,
  summary: null,
  tree: [],
  changes: [],
  chats: [],
  chatId: null,
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

async function api(path, options = {}) {
  const init = { method: options.method || "GET", headers: {} };
  if (options.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, init);
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
    if (line.trim().startsWith("```")) {
      flushList();
      out.push(inCode ? "</code></pre>" : "<pre><code>");
      inCode = !inCode;
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
  const host = $("messages");
  host.scrollTop = host.scrollHeight;
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
  wrap.appendChild(meta);
  wrap.appendChild(bubble);
  $("messages").appendChild(wrap);
  scrollMessages();
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

function renderToolCall(name, args) {
  const card = document.createElement("details");
  card.className = "tool-card";
  card.innerHTML = `<summary><span class="tool-name">${escapeHtml(name)}</span><span class="tool-arg">${escapeHtml(toolSummary(args))}</span></summary><pre>${escapeHtml(JSON.stringify(args, null, 2))}</pre>`;
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
  const node = document.createElement("div");
  node.className = "event-change";
  node.innerHTML = `<span class="tag agent">write</span><span class="path">${escapeHtml(data.path || "")}</span><span class="spacer"></span><span class="muted small">open diff</span>`;
  node.addEventListener("click", () => openChangeDiff(data.changeId));
  addEventCard(node);
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

function renderTree() {
  const host = $("file-tree");
  host.innerHTML = "";
  if (!state.tree.length) {
    host.innerHTML = '<div class="pad muted">No files</div>';
    return;
  }
  const changed = new Set(state.changes.filter((c) => !c.reverted && !c.reviewed).map((c) => c.path));
  for (const row of state.tree) {
    const depth = (row.path.match(/\//g) || []).length;
    if (row.type === "dir") {
      const dir = document.createElement("div");
      dir.className = "tree-dir";
      dir.style.paddingLeft = (10 + depth * 10) + "px";
      dir.textContent = row.path.split("/").pop();
      host.appendChild(dir);
      continue;
    }
    const rowEl = document.createElement("div");
    rowEl.className = "tree-row" + (state.file && state.file.path === row.path ? " active" : "");
    rowEl.style.paddingLeft = (10 + depth * 10) + "px";
    const ext = row.path.split(".").pop();
    const glyph = row.path.endsWith(".tex") ? "T" : row.path.endsWith(".cpp") ? "C" : row.path.endsWith(".py") ? "P" : row.path.endsWith(".in") ? "i" : row.path.endsWith(".ans") ? "o" : "·";
    rowEl.innerHTML = `<span class="glyph">${glyph}</span><span>${escapeHtml(row.path.split("/").pop())}</span><span class="size">${row.size ? (row.size > 1024 ? Math.round(row.size / 1024) + "k" : row.size) : ""}</span>`;
    if (changed.has(row.path)) {
      const dot = document.createElement("span");
      dot.className = "change-dot";
      dot.title = "Unreviewed change";
      rowEl.appendChild(dot);
    }
    rowEl.addEventListener("click", () => openFile(row.path));
    host.appendChild(rowEl);
  }
}

async function openFile(path) {
  if (!state.slug) return;
  if (state.dirty && state.file && state.file.path !== path && !confirm("Discard the unsaved editor changes?")) return;
  try {
    const file = await api(`/api/workspaces/${state.slug}/file?path=${encodeURIComponent(path)}`);
    state.file = file;
    state.dirty = false;
    $("file-name").textContent = file.path;
    $("file-meta").textContent = file.text ? `${file.size} bytes` : "binary";
    const editor = $("file-editor");
    editor.disabled = !file.text;
    editor.value = file.text ? file.content : "(binary file — not editable here)";
    $("save-file").hidden = true;
    $("reload-file").hidden = false;
    switchSide("files");
    switchTab("file");
    renderTree();
  } catch (error) { toast(error.message, true); }
}

async function saveFile() {
  if (!state.slug || !state.file) return;
  try {
    await api(`/api/workspaces/${state.slug}/file`, {
      method: "POST",
      body: { path: state.file.path, content: $("file-editor").value },
    });
    state.dirty = false;
    $("save-file").hidden = true;
    toast("Saved");
    await refreshWorkspace();
    await openFile(state.file.path);
  } catch (error) { toast(error.message, true); }
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
    const data = await api(`/api/workspaces/${state.slug}/changes/${changeId}/diff`);
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
  } catch (error) { toast(error.message, true); }
}

async function revertAllUnreviewed() {
  const targets = state.changes.filter((c) => !c.reverted && !c.reviewed);
  if (!targets.length) return;
  if (!confirm(`Revert ${targets.length} unreviewed change(s)?`)) return;
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

function renderChatList() {
  const host = $("chat-list");
  host.innerHTML = "";
  if (!state.chats.length) {
    host.innerHTML = '<div class="pad muted">No conversations yet.</div>';
  }
  for (const chat of state.chats) {
    const item = document.createElement("div");
    const running = Boolean(state.jobId && state.jobChatId === chat.id);
    item.className = "chat-item" + (chat.id === state.chatId ? " active" : "") + (running ? " running" : "") + (state.jobId ? " disabled" : "");
    const title = document.createElement("div");
    title.className = "chat-item-title";
    title.textContent = chatTitle(chat);
    const meta = document.createElement("div");
    meta.className = "chat-item-meta";
    meta.innerHTML = `<span class="chat-dot"></span><span>${escapeHtml(formatTime(chat.updatedAt))}</span><span>·</span><span>${chat.messageCount || 0} msgs</span>`;
    item.appendChild(title);
    item.appendChild(meta);
    if (!state.jobId) item.addEventListener("click", () => selectChat(chat.id));
    host.appendChild(item);
  }
  $("new-chat").disabled = Boolean(state.jobId) || !state.slug;
  $("reload-chat").disabled = Boolean(state.jobId) || !state.slug || !state.chatId;
  $("stop-btn").hidden = !state.jobId;
  $("stop-btn").disabled = !state.jobId;
  const active = state.chats.find((c) => c.id === state.chatId);
  $("chat-title").textContent = active ? chatTitle(active) : "No conversation";
  $("chat-sub").textContent = active
    ? `${formatTime(active.updatedAt)} · ${active.messageCount || 0} messages${state.jobId && state.jobChatId === active.id ? " · working" : ""}`
    : "";
  $("composer-chat").textContent = active ? chatTitle(active) : "no chat";
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
  renderChatList();
  return state.chatId;
}

async function selectChat(chatId) {
  if (state.jobId) { toast("Wait for the current turn before switching chats", true); return; }
  if (!chatId || chatId === state.chatId) return;
  state.chatId = chatId;
  localStorage.setItem(`author-agent-chat-${state.slug}`, chatId);
  renderChatList();
  await loadConversation();
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
  return [
    { label: "Idea captured", done: paths.has("NOTES.md"), detail: "NOTES.md" },
    { label: "Statement written", done: paths.has("problem_statement/problem.en.tex"), detail: "problem.en.tex" },
    { label: "Statement compiles", done: statement && statement.status === "pass", fail: statement && statement.status === "fail", detail: statement ? statement.status : "not checked" },
    { label: "Input validator", done: paths.has("input_validators/validate.py"), detail: "validate.py" },
    { label: "Reference solution", done: accepted > 0, detail: `${accepted} accepted` },
    { label: "Sample + secret tests", done: sample > 0 && secret > 0, detail: `${sample} sample · ${secret} secret` },
    { label: "Negative solutions", done: negative > 0, detail: `${negative} negative` },
    { label: "Package verified", done: Boolean(verified), fail: report && report.status === "failed", detail: report ? `${report.status}${state.summary && state.summary.stale ? " · stale" : ""}` : "not run" },
  ];
}

function renderPlan() {
  const host = $("plan-body");
  const pipeline = pipelineSteps();
  const agentSteps = (state.plan && state.plan.steps) || [];
  const report = state.summary && state.summary.lastReport;
  const unreviewed = (state.summary && state.summary.unreviewed) || 0;
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
    renderChatList();
  } catch (error) { toast(error.message, true); }
}

async function selectWorkspace(slug) {
  state.slug = slug || null;
  state.summary = null;
  state.tree = [];
  state.changes = [];
  state.chats = [];
  state.chatId = null;
  state.plan = { steps: [] };
  state.file = null;
  state.dirty = false;
  state.jobId = null;
  state.jobChatId = null;
  state.jobEvents = 0;
  resetStreaming();
  $("messages").innerHTML = "";
  $("file-editor").value = "";
  $("file-editor").disabled = true;
  $("file-name").textContent = "No file selected";
  $("file-meta").textContent = "";
  $("save-file").hidden = true;
  $("reload-file").hidden = true;
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
  await refreshWorkspace();
  await loadReport();
  await loadChats();
  await loadConversation();
  renderPlan();
}

async function loadState(selectSlug) {
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
  } catch (error) { toast(error.message, true); }
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
      renderReport(data);
    } else if (event.kind === "export") {
      toast(`Exported ${data.files || 0} files`);
      window.location.href = `/api/workspaces/${state.slug}/download`;
    } else if (event.kind === "answers") {
      renderVerificationEvent({ stage: "answers", result: data });
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
      $("agent-state").textContent = "";
      $("send-btn").disabled = false;
      const wasCancelled = job.state === "cancelled";
      state.jobId = null;
      state.jobChatId = null;
      await refreshWorkspace();
      await loadReport();
      await loadChats(state.chatId);
      if (state.chatId) await loadConversation();
      else renderChatList();
      if (wasCancelled) toast("Stopped");
      if (onDone) await onDone(job);
    } catch (error) {
      $("agent-state").textContent = "";
      $("send-btn").disabled = false;
      state.jobId = null;
      state.jobChatId = null;
      toast(error.message, true);
    }
  };
  state.pollTimer = setTimeout(tick, 400);
}

async function sendMessage(override) {
  if (!state.slug) { toast("Create or select a problem first", true); return; }
  if (state.jobId) { toast("Wait for the current turn to finish", true); return; }
  const composer = $("composer");
  const message = (override ?? composer.value).trim();
  if (!message) return;
  if (!state.chatId) {
    await loadChats();
    if (!state.chatId) await newChat();
  }
  if (!state.chatId) { toast("Could not create a chat", true); return; }
  if (!override) composer.value = "";
  addMessage("user", message);
  const chat = state.chats.find((c) => c.id === state.chatId);
  if (chat && (!chat.title || chat.title === "New chat")) {
    chat.title = truncate(message, 70);
    renderChatList();
  }
  try {
    const job = await api(`/api/workspaces/${state.slug}/chat`, {
      method: "POST",
      body: { message, chatId: state.chatId },
    });
    state.jobId = job.id;
    state.jobChatId = job.chatId || state.chatId;
    state.jobEvents = 0;
    resetStreaming();
    $("send-btn").disabled = true;
    $("agent-state").textContent = "starting…";
    renderChatList();
    pollJob(job.id);
  } catch (error) {
    toast(error.message, true);
    $("send-btn").disabled = false;
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
    $("send-btn").disabled = true;
    $("agent-state").textContent = kind === "verify" ? "verifying…" : kind === "answers" ? "building answers…" : "exporting…";
    renderChatList();
    pollJob(job.id, async (finished) => {
      if (kind === "verify") {
        switchTab("report");
        if (finished.state === "done") toast(finished.result.status === "verified" ? "Package verified" : "Verification failed", finished.result.status !== "verified");
      }
      if (kind === "answers") toast("Answers generated");
      if (kind === "export") toast("Package exported");
    });
  } catch (error) { toast(error.message, true); }
}

// ---------- navigation ----------

function switchTab(tab) {
  state.activeTab = tab;
  document.querySelectorAll(".inspector-tabs button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tab);
  });
  document.querySelectorAll(".panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === "panel-" + tab);
  });
}

function switchSide(side) {
  state.activeSide = side;
  document.querySelectorAll(".side-tabs button").forEach((button) => {
    button.classList.toggle("active", button.dataset.side === side);
  });
  document.querySelectorAll(".side-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === "side-" + side);
  });
}

// ---------- dialogs ----------

function openSettings() {
  const form = $("settings-form");
  const settings = state.settings || {};
  form.baseUrl.value = settings.baseUrl || "";
  form.model.value = settings.model || "";
  form.apiKey.value = "";
  form.temperature.value = settings.temperature ?? 0.2;
  form.maxToolRounds.value = settings.maxToolRounds ?? 24;
  form.clearKey.checked = false;
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
    clearKey: form.clearKey.checked,
  };
  if (form.apiKey.value.trim()) body.apiKey = form.apiKey.value.trim();
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
        timeLimit: Number(form.timeLimit.value || 2),
        memoryMb: Number(form.memoryMb.value || 256),
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
  $("send-btn").addEventListener("click", () => sendMessage());
  $("composer").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); sendMessage(); }
  });
  $("verify-btn").addEventListener("click", () => runToolJob("verify", { writeAnswers: false }));
  $("answers-btn").addEventListener("click", () => runToolJob("answers", {}));
  $("export-btn").addEventListener("click", () => runToolJob("export", {}));
  $("approve-btn").addEventListener("click", async () => {
    if (!state.slug) return;
    try { await api(`/api/workspaces/${state.slug}/review`, { method: "POST" }); await refreshWorkspace(); toast("Changes marked reviewed"); }
    catch (error) { toast(error.message, true); }
  });
  $("revert-unreviewed").addEventListener("click", revertAllUnreviewed);
  $("new-chat").addEventListener("click", newChat);
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
  });
  $("save-file").addEventListener("click", saveFile);
  $("reload-file").addEventListener("click", () => state.file && openFile(state.file.path));
  document.querySelectorAll(".tabs button, .inspector-tabs button").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });
  document.querySelectorAll(".side-tabs button").forEach((button) => {
    button.addEventListener("click", () => switchSide(button.dataset.side));
  });
  window.addEventListener("beforeunload", (event) => {
    if (!state.dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });
}

wire();
loadState();
