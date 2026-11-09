$ErrorActionPreference = 'Stop'
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$profile = Join-Path $env:TEMP ('author-layout-regression-' + [guid]::NewGuid().ToString('N'))
$process = Start-Process -FilePath $chrome -ArgumentList @('--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=9237',"--user-data-dir=$profile",'about:blank') -PassThru
try {
  Start-Sleep -Seconds 2
  $tabs = Invoke-RestMethod 'http://127.0.0.1:9237/json'
  $target = $tabs | Where-Object { $_.type -eq 'page' } | Select-Object -First 1
  $ws = [System.Net.WebSockets.ClientWebSocket]::new()
  $ct = [Threading.CancellationToken]::None
  $ws.ConnectAsync([Uri]$target.webSocketDebuggerUrl, $ct).Wait()
  $script:nextId = 0
  function Invoke-Cdp([string]$method, $params) {
    $script:nextId++
    $id = $script:nextId
    $body = @{ id = $id; method = $method; params = $params } | ConvertTo-Json -Depth 12 -Compress
    $bytes = [Text.Encoding]::UTF8.GetBytes($body)
    $ws.SendAsync([System.ArraySegment[byte]]::new($bytes), [Net.WebSockets.WebSocketMessageType]::Text, $true, $ct).Wait()
    while ($true) {
      $parts = New-Object System.Collections.Generic.List[string]
      do {
        $buffer = New-Object byte[] 1048576
        $segment = [System.ArraySegment[byte]]::new($buffer)
        $result = $ws.ReceiveAsync($segment, $ct).Result
        $parts.Add([Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count))
      } while (-not $result.EndOfMessage)
      $obj = ([string]::Join('', $parts)) | ConvertFrom-Json
      if ($obj.id -eq $id) { return $obj }
    }
  }
  function Eval([string]$expression) {
    $res = Invoke-Cdp 'Runtime.evaluate' @{ expression = $expression; awaitPromise = $true; returnByValue = $true; userGesture = $true }
    if ($res.result.exceptionDetails) { throw $res.result.exceptionDetails.exception.description }
    return $res.result.result.value
  }
  Invoke-Cdp 'Runtime.enable' @{} | Out-Null
  Invoke-Cdp 'Emulation.setDeviceMetricsOverride' @{ width = 1440; height = 900; deviceScaleFactor = 1; mobile = $false } | Out-Null
  Invoke-Cdp 'Page.navigate' @{ url = 'http://127.0.0.1:8787/' } | Out-Null
  Start-Sleep -Seconds 3
  $report = Eval @'
(async () => {
  await selectWorkspace('sum-test');
  await new Promise((resolve) => setTimeout(resolve, 600));
  const messages = document.getElementById('messages');
  messages.innerHTML = '';
  for (let i = 0; i < 60; i++) {
    const node = document.createElement('div');
    node.className = 'msg user';
    node.innerHTML = '<div class="msg-meta">YOU</div><div class="bubble"><p>Message ' + i + ' ' + 'x'.repeat(100) + '</p></div>';
    messages.appendChild(node);
  }
  const box = (selector) => {
    const el = document.querySelector(selector);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { top: Math.round(r.top), bottom: Math.round(r.bottom), height: Math.round(r.height) };
  };
  const composer = box('.composer');
  const chat = box('.chat-pane');
  const results = {
    viewport: { w: innerWidth, h: innerHeight },
    chatScrolls: messages.scrollHeight > messages.clientHeight,
    scrollbarPx: messages.offsetWidth - messages.clientWidth,
    chatConstrained: chat.height <= innerHeight - 58,
    composerVisible: Boolean(composer && composer.bottom <= innerHeight && composer.height > 0),
  };
  await openFile('submissions/accepted/ref.cpp');
  await new Promise((resolve) => setTimeout(resolve, 400));
  const panel = document.getElementById('run-panel');
  const stdin = box('#run-stdin');
  results.runPanelVisible = !panel.hidden && Boolean(stdin && stdin.bottom <= innerHeight && stdin.height > 0);
  results.runPanelInViewport = Boolean(box('#run-panel') && box('#run-panel').bottom <= innerHeight);
  results.chatActionLabels = [...document.querySelectorAll('.chat-actions button')].every((button) => Boolean(button.getAttribute('aria-label')));
  results.chatTitleButtons = document.querySelectorAll('.chat-item-title').length;
  results.machines = window.AuthorMachines ? window.AuthorMachines.snapshot() : null;
  results.panelAttribute = document.body.getAttribute('data-panel');
  results.sideAttribute = document.body.getAttribute('data-side');

  const rect = (selector) => {
    const el = document.querySelector(selector);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top), bottom: Math.round(r.bottom), width: Math.round(r.width), height: Math.round(r.height) };
  };
  const regions = {
    rail: rect('.activity-rail'),
    navigator: rect('.navigator'),
    editor: rect('.editor-group'),
    agent: rect('.agent-panel'),
    status: rect('.statusbar'),
  };
  results.regions = regions;
  results.regionsPresent = Object.values(regions).every((r) => r && r.width > 0 && r.height > 0);
  results.regionsOrdered = regions.rail.right <= regions.navigator.left + 1
    && regions.navigator.right <= regions.editor.left + 1
    && regions.editor.right <= regions.agent.left + 1;
  results.agentIsChat = Boolean(document.querySelector('.agent-panel #messages')) && Boolean(document.querySelector('.agent-panel #composer'));
  results.editorIsCentre = regions.editor.width > regions.navigator.width && regions.editor.width > regions.agent.width;
  results.statusbarAtBottom = regions.status.bottom <= innerHeight + 1 && regions.status.top > innerHeight - 60;
  results.noHorizontalOverflow = document.documentElement.scrollWidth <= innerWidth;
  results.statusLanguage = document.getElementById('status-language').textContent;
  results.statusCursor = document.getElementById('status-cursor').textContent;
  results.statusVerify = document.getElementById('status-verify').textContent;
  results.breadcrumb = document.getElementById('breadcrumbs').textContent;

  const rail = (section) => document.querySelector('.activity-rail [data-activity="' + section + '"]');
  const clickRail = async (section) => {
    rail(section).click();
    await new Promise((resolve) => setTimeout(resolve, 120));
    return rail(section).getAttribute('aria-current');
  };
  results.railEvidence = (await clickRail('evidence')) === 'page' && document.getElementById('panel-report').classList.contains('active');
  results.railHistory = (await clickRail('history')) === 'page' && document.getElementById('panel-history').classList.contains('active');
  results.railRun = (await clickRail('run')) === 'page' && document.getElementById('panel-file').classList.contains('active');
  results.railFiles = (await clickRail('files')) === 'page' && document.getElementById('side-files').classList.contains('active');
  results.railChats = (await clickRail('chats')) === 'page' && document.getElementById('side-chats').classList.contains('active');

  const invoker = document.getElementById('verify-btn');
  invoker.focus();
  const pending = actionDialog({
    kicker: 'QA',
    title: 'Rename chat',
    description: 'Accessible dialog regression check.',
    inputLabel: 'Chat title',
    value: 'Old title',
    confirmLabel: 'Rename',
  });
  await new Promise((resolve) => setTimeout(resolve, 120));
  const dialog = document.getElementById('action-dialog');
  results.dialogOpen = dialog.open;
  results.dialogLabelled = dialog.getAttribute('aria-labelledby') === 'action-title' && dialog.getAttribute('aria-describedby') === 'action-desc';
  results.dialogFocusInside = dialog.contains(document.activeElement);
  results.dialogInputLabelled = Boolean(document.getElementById('action-field-label').textContent);
  document.getElementById('action-input').value = 'New title';
  document.getElementById('action-confirm').click();
  results.dialogValue = await pending;
  results.dialogClosed = !dialog.open;
  results.dialogFocusReturned = document.activeElement === invoker;

  const cancelPending = actionDialog({
    kicker: 'QA',
    title: 'Cancel check',
    description: 'Cancel must close and resolve without applying.',
    inputLabel: 'Value',
    value: 'unchanged',
  });
  await new Promise((resolve) => setTimeout(resolve, 120));
  results.dialogCancelOpen = dialog.open;
  document.getElementById('action-cancel').click();
  results.dialogCancelValue = await cancelPending;
  results.dialogCancelClosed = !dialog.open;

  document.getElementById('new-problem').click();
  await new Promise((resolve) => setTimeout(resolve, 80));
  results.newDialogOpen = document.getElementById('new-dialog').open;
  document.getElementById('new-cancel').click();
  results.newDialogCancelClosed = !document.getElementById('new-dialog').open;

  document.getElementById('settings-btn').click();
  await new Promise((resolve) => setTimeout(resolve, 80));
  results.settingsDialogOpen = document.getElementById('settings-dialog').open;
  document.getElementById('settings-cancel').click();
  results.settingsDialogCancelClosed = !document.getElementById('settings-dialog').open;

  document.getElementById('context-btn').click();
  await new Promise((resolve) => setTimeout(resolve, 80));
  results.contextDialogOpen = document.getElementById('context-dialog').open;
  document.getElementById('context-cancel').click();
  results.contextDialogCancelClosed = !document.getElementById('context-dialog').open;

  // Every dialog must also cancel on Escape and on a backdrop click.
  const escapeChecks = {};
  for (const [id, opener] of [['new-dialog', 'new-problem'], ['settings-dialog', 'settings-btn'], ['context-dialog', 'context-btn']]) {
    const dialog = document.getElementById(id);
    document.getElementById(opener).click();
    await new Promise((resolve) => setTimeout(resolve, 80));
    const opened = dialog.open;
    dialog.dispatchEvent(new Event('cancel', { cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 140));
    escapeChecks[id] = opened && !dialog.open;
    document.getElementById(opener).click();
    await new Promise((resolve) => setTimeout(resolve, 80));
    dialog.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve, 140));
    escapeChecks[id + 'Backdrop'] = !dialog.open;
  }
  results.newEscape = escapeChecks['new-dialog'];
  results.newBackdrop = escapeChecks['new-dialogBackdrop'];
  results.settingsEscape = escapeChecks['settings-dialog'];
  results.settingsBackdrop = escapeChecks['settings-dialogBackdrop'];
  results.contextEscape = escapeChecks['context-dialog'];
  results.contextBackdrop = escapeChecks['context-dialogBackdrop'];

  const actionEscapePending = actionDialog({ title: 'Escape check', inputLabel: 'Value', value: 'x' });
  await new Promise((resolve) => setTimeout(resolve, 100));
  document.getElementById('action-dialog').dispatchEvent(new Event('cancel', { cancelable: true }));
  results.actionEscapeValue = await actionEscapePending;
  results.actionEscapeClosed = !document.getElementById('action-dialog').open;

  const actionBackdropPending = actionDialog({ title: 'Backdrop check', inputLabel: 'Value', value: 'y' });
  await new Promise((resolve) => setTimeout(resolve, 100));
  document.getElementById('action-dialog').dispatchEvent(new MouseEvent('click', { bubbles: true }));
  results.actionBackdropValue = await actionBackdropPending;
  results.actionBackdropClosed = !document.getElementById('action-dialog').open;

  // Dirty settings must not close on cancel; the discard dialog decides.
  document.getElementById('settings-btn').click();
  await new Promise((resolve) => setTimeout(resolve, 80));
  document.querySelector('#settings-form [name="model"]').value = 'qa-dirty-model';
  document.getElementById('settings-cancel').click();
  await new Promise((resolve) => setTimeout(resolve, 160));
  results.settingsDirtyGuard = document.getElementById('settings-dialog').open && document.getElementById('action-dialog').open;
  document.getElementById('action-cancel').click();
  await new Promise((resolve) => setTimeout(resolve, 160));
  results.settingsDirtyKept = document.getElementById('settings-dialog').open && !document.getElementById('action-dialog').open;
  document.getElementById('settings-cancel').click();
  await new Promise((resolve) => setTimeout(resolve, 160));
  document.getElementById('action-confirm').click();
  await new Promise((resolve) => setTimeout(resolve, 160));
  results.settingsDirtyDiscarded = !document.getElementById('settings-dialog').open;

  const originalChat = state.chatId;
  const created = await api('/api/workspaces/sum-test/chats', { method: 'POST', body: {} });
  await loadChats(created.id);
  const renameDone = renameChat(created.id);
  await new Promise((resolve) => setTimeout(resolve, 120));
  document.getElementById('action-input').value = 'QA temporary chat';
  document.getElementById('action-confirm').click();
  await renameDone;
  results.chatRenamed = (state.chats.find((chat) => chat.id === created.id) || {}).title === 'QA temporary chat';
  const deleteDone = deleteChat(created.id);
  await new Promise((resolve) => setTimeout(resolve, 120));
  document.getElementById('action-confirm').click();
  await deleteDone;
  results.chatDeleted = !state.chats.some((chat) => chat.id === created.id);
  if (originalChat && state.chatId !== originalChat) await selectChat(originalChat);

  return results;
})()
'@
  Write-Output ($report | ConvertTo-Json -Compress)

  $widthReport = @()
  foreach ($width in @(1440, 1100, 768, 320)) {
    $height = if ($width -le 480) { 800 } else { 900 }
    Invoke-Cdp 'Emulation.setDeviceMetricsOverride' @{ width = $width; height = $height; deviceScaleFactor = 1; mobile = $false } | Out-Null
    Start-Sleep -Milliseconds 300
    $raw = Eval @'
JSON.stringify((() => {
  const rect = (selector) => {
    const el = document.querySelector(selector);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width), height: Math.round(r.height) };
  };
  const editor = rect('.editor-group');
  const agent = rect('.agent-panel');
  const navigator = rect('.navigator');
  return {
    width: innerWidth,
    overflow: document.documentElement.scrollWidth > innerWidth,
    editorVisible: Boolean(editor && editor.width > 0 && editor.height > 0),
    agentVisible: Boolean(agent && agent.width > 0 && agent.left >= 0 && agent.right <= innerWidth + 1),
    navigatorVisible: Boolean(navigator && navigator.width > 0 && navigator.left >= 0),
    agentToggle: getComputedStyle(document.getElementById('toggle-agent')).display !== 'none',
    navToggle: getComputedStyle(document.getElementById('toggle-navigator')).display !== 'none',
  };
})())
'@
    $widthReport += ($raw | ConvertFrom-Json)
  }
  Write-Output ("widths=" + ($widthReport | ConvertTo-Json -Compress))

  $drawer = $null
  Invoke-Cdp 'Emulation.setDeviceMetricsOverride' @{ width = 320; height = 800; deviceScaleFactor = 1; mobile = $false } | Out-Null
  Start-Sleep -Milliseconds 300
  $drawerRaw = Eval @'
(async () => {
  document.getElementById('toggle-agent').click();
  await new Promise((resolve) => setTimeout(resolve, 260));
  const panel = document.getElementById('agent-panel');
  const composer = document.querySelector('.composer');
  const p = panel.getBoundingClientRect();
  const c = composer.getBoundingClientRect();
  const open = document.body.classList.contains('agent-open') && p.left >= 0 && p.right <= innerWidth + 1;
  const composerVisible = c.bottom <= innerHeight && c.height > 0;
  const focusAfterOpen = document.activeElement.id || document.activeElement.tagName;
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 260));
  const focusAfterClose = document.activeElement.id || document.activeElement.tagName;
  return JSON.stringify({ open, composerVisible, closed: !document.body.classList.contains('agent-open'), focusReturned: focusAfterClose === 'toggle-agent', focusAfterOpen, focusAfterClose });
})()
'@
  $drawer = $drawerRaw | ConvertFrom-Json
  Write-Output ("drawer=" + $drawerRaw)

  $checks = @{
    chatScrolls = $true
    chatConstrained = $true
    composerVisible = $true
    runPanelVisible = $true
    runPanelInViewport = $true
    chatActionLabels = $true
    regionsPresent = $true
    regionsOrdered = $true
    agentIsChat = $true
    editorIsCentre = $true
    statusbarAtBottom = $true
    noHorizontalOverflow = $true
    railEvidence = $true
    railHistory = $true
    railRun = $true
    railFiles = $true
    railChats = $true
    dialogOpen = $true
    dialogLabelled = $true
    dialogFocusInside = $true
    dialogInputLabelled = $true
    dialogClosed = $true
    dialogFocusReturned = $true
    dialogCancelOpen = $true
    dialogCancelClosed = $true
    newDialogOpen = $true
    newDialogCancelClosed = $true
    settingsDialogOpen = $true
    settingsDialogCancelClosed = $true
    contextDialogOpen = $true
    contextDialogCancelClosed = $true
    newEscape = $true
    newBackdrop = $true
    settingsEscape = $true
    settingsBackdrop = $true
    contextEscape = $true
    contextBackdrop = $true
    actionEscapeClosed = $true
    actionBackdropClosed = $true
    settingsDirtyGuard = $true
    settingsDirtyKept = $true
    settingsDirtyDiscarded = $true
    chatRenamed = $true
    chatDeleted = $true
  }
  foreach ($key in $checks.Keys) {
    if ($report.$key -ne $checks[$key]) { throw ("layout regression failed: " + $key + " = " + $report.$key) }
  }
  if ($report.scrollbarPx -le 0) { throw "chat scrollbar is not visible" }
  if ($report.dialogValue -ne 'New title') { throw "dialog did not return the edited value" }
  if ($report.dialogCancelValue -ne $null) { throw "cancel should resolve to null for a prompt" }
  if ($report.actionEscapeValue -ne $null) { throw "Escape should resolve a prompt to null" }
  if ($report.actionBackdropValue -ne $null) { throw "backdrop should resolve a prompt to null" }
  if (-not $report.machines -or $report.machines.turn -ne 'idle') { throw "state machine snapshot missing or turn is not idle" }
  if ($report.chatTitleButtons -lt 1) { throw "chat titles are not buttons" }
  if (-not $report.statusLanguage -or -not $report.statusCursor -or -not $report.statusVerify) { throw "status bar is incomplete" }
  if ($report.breadcrumb -notmatch 'ref\.cpp') { throw "breadcrumb does not show the open file" }
  if ($report.regions.editor.width -le 500) { throw "editor region is too narrow at 1440" }
  foreach ($row in $widthReport) {
    if ($row.overflow) { throw ("horizontal overflow at " + $row.width) }
    if (-not $row.editorVisible) { throw ("editor hidden at " + $row.width) }
    if ($row.width -ge 1100 -and -not $row.agentVisible) { throw ("agent panel missing at " + $row.width) }
    if ($row.width -ge 1100 -and ($row.agentToggle -or $row.navToggle)) { throw ("drawer toggles should be hidden at " + $row.width) }
    if ($row.width -eq 768 -and (-not $row.agentToggle -or -not $row.navigatorVisible)) { throw "768 should be navigator + agent drawer" }
    if ($row.width -eq 320 -and (-not $row.agentToggle -or -not $row.navToggle)) { throw "320 should offer both drawers" }
  }
  if (-not $drawer.open -or -not $drawer.composerVisible -or -not $drawer.closed -or -not $drawer.focusReturned) { throw ("agent drawer failed: " + $drawerRaw) }
  Write-Output 'LAYOUT REGRESSION PASSED'
}
finally {
  try { $ws.Dispose() } catch {}
  try { Stop-Process -Id $process.Id -Force } catch {}
  Remove-Item -LiteralPath $profile -Recurse -Force -ErrorAction SilentlyContinue
}
