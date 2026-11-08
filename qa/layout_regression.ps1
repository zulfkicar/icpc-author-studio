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
  results.machines = window.AuthorMachines ? window.AuthorMachines.snapshot() : null;
  results.panelAttribute = document.body.getAttribute('data-panel');
  results.sideAttribute = document.body.getAttribute('data-side');

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
  $checks = @{
    chatScrolls = $true
    chatConstrained = $true
    composerVisible = $true
    runPanelVisible = $true
    runPanelInViewport = $true
    chatActionLabels = $true
    dialogOpen = $true
    dialogLabelled = $true
    dialogFocusInside = $true
    dialogInputLabelled = $true
    dialogClosed = $true
    dialogFocusReturned = $true
    chatRenamed = $true
    chatDeleted = $true
  }
  foreach ($key in $checks.Keys) {
    if ($report.$key -ne $checks[$key]) { throw ("layout regression failed: " + $key + " = " + $report.$key) }
  }
  if ($report.scrollbarPx -le 0) { throw "chat scrollbar is not visible" }
  if ($report.dialogValue -ne 'New title') { throw "dialog did not return the edited value" }
  if (-not $report.machines -or $report.machines.turn -ne 'idle') { throw "state machine snapshot missing or turn is not idle" }
  Write-Output 'LAYOUT REGRESSION PASSED'
}
finally {
  try { $ws.Dispose() } catch {}
  try { Stop-Process -Id $process.Id -Force } catch {}
  Remove-Item -LiteralPath $profile -Recurse -Force -ErrorAction SilentlyContinue
}
