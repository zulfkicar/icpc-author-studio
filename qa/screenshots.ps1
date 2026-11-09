$ErrorActionPreference = 'Stop'
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$profile = Join-Path $env:TEMP ('author-shots-' + [guid]::NewGuid().ToString('N'))
$out = Join-Path $PSScriptRoot 'screenshots'
New-Item -ItemType Directory -Force -Path $out | Out-Null
$process = Start-Process -FilePath $chrome -ArgumentList @('--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=9233',"--user-data-dir=$profile",'about:blank') -PassThru
try {
  Start-Sleep -Seconds 2
  $tabs = Invoke-RestMethod 'http://127.0.0.1:9233/json'
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
      $text = [string]::Join('', $parts)
      $obj = $text | ConvertFrom-Json
      if ($obj.id -eq $id) { return $obj }
    }
  }
  function Eval([string]$expression) {
    $res = Invoke-Cdp 'Runtime.evaluate' @{ expression = $expression; awaitPromise = $true; returnByValue = $true; userGesture = $true }
    if ($res.result.exceptionDetails) { throw $res.result.exceptionDetails.exception.description }
    return $res.result.result.value
  }
  function Shot([string]$name) {
    $res = Invoke-Cdp 'Page.captureScreenshot' @{ format = 'png'; captureBeyondViewport = $false }
    [IO.File]::WriteAllBytes((Join-Path $out $name), [Convert]::FromBase64String($res.result.data))
    Write-Output ("saved " + $name)
  }
  Invoke-Cdp 'Runtime.enable' @{} | Out-Null
  Invoke-Cdp 'Emulation.setDeviceMetricsOverride' @{ width = 1440; height = 900; deviceScaleFactor = 1; mobile = $false } | Out-Null
  Invoke-Cdp 'Page.navigate' @{ url = 'http://127.0.0.1:8787/' } | Out-Null
  Start-Sleep -Seconds 3
  Eval @'
(async () => {
  await selectWorkspace('sum-test');
  await new Promise((resolve) => setTimeout(resolve, 400));
  return true;
})()
'@ | Out-Null
  Shot '01-overview.png'
  Eval @'
(async () => {
  await openFile('submissions/accepted/ref.cpp');
  enterEditMode();
  return true;
})()
'@ | Out-Null
  Start-Sleep -Milliseconds 400
  Shot '02-file-editor.png'
  Eval @'
(async () => {
  switchTab('report');
  await new Promise((resolve) => setTimeout(resolve, 300));
  return true;
})()
'@ | Out-Null
  Shot '03-report.png'
  Eval @'
(async () => {
  switchTab('diff');
  const change = state.changes.find((item) => !item.reverted);
  if (change) await openChangeDiff(change.id);
  return true;
})()
'@ | Out-Null
  Start-Sleep -Milliseconds 400
  Shot '04-diff.png'
  Eval @'
(async () => {
  switchTab('mcp');
  await new Promise((resolve) => setTimeout(resolve, 500));
  return true;
})()
'@ | Out-Null
  Shot '05-mcp.png'
  Eval @'
(async () => {
  switchTab('history');
  await new Promise((resolve) => setTimeout(resolve, 400));
  return true;
})()
'@ | Out-Null
  Shot '06-history.png'
  Eval @'
(async () => {
  await openFile('submissions/accepted/ref.cpp');
  switchSide('chats');
  const messages = document.getElementById('messages');
  messages.innerHTML = '';
  for (let i = 0; i < 24; i++) {
    const node = document.createElement('div');
    node.className = 'msg ' + (i % 2 ? 'user' : 'assistant');
    node.innerHTML = '<div class="msg-meta">' + (i % 2 ? 'YOU' : 'AGENT') + '</div><div class="bubble"><p>Step ' + i + ': the validator and reference are ready for review. This is a longer line to expose the scrollbar and keep the composer pinned.</p></div>';
    messages.appendChild(node);
  }
  messages.scrollTop = messages.scrollHeight;
  return true;
})()
'@ | Out-Null
  Start-Sleep -Milliseconds 300
  Shot '07-chat-scroll.png'
  Eval @'
(async () => {
  actionDialog({
    kicker: 'Conversation',
    title: 'Rename chat',
    description: 'Rename "Claim or Concede".',
    inputLabel: 'Chat title',
    value: 'Claim or Concede',
    confirmLabel: 'Rename'
  });
  return true;
})()
'@ | Out-Null
  Start-Sleep -Milliseconds 300
  Shot '08-rename-dialog.png'
  Eval 'document.getElementById("action-dialog").close(); true' | Out-Null

  $shellShots = @{ 1440 = '09-shell-1440.png'; 1100 = '10-shell-1100.png'; 768 = '11-shell-768.png'; 320 = '12-shell-320.png' }
  foreach ($width in @(1440, 1100, 768, 320)) {
    $height = if ($width -le 480) { 800 } else { 900 }
    Invoke-Cdp 'Emulation.setDeviceMetricsOverride' @{ width = $width; height = $height; deviceScaleFactor = 1; mobile = $false } | Out-Null
    Start-Sleep -Milliseconds 350
    Shot $shellShots[$width]
  }
  Eval @'
(async () => {
  document.getElementById('toggle-agent').click();
  await new Promise((resolve) => setTimeout(resolve, 300));
  return true;
})()
'@ | Out-Null
  Shot '13-shell-320-agent.png'
  Eval @'
(async () => {
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 250));
  document.getElementById('toggle-navigator').click();
  await new Promise((resolve) => setTimeout(resolve, 300));
  return true;
})()
'@ | Out-Null
  Shot '14-shell-320-navigator.png'
  Eval 'document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); true' | Out-Null
}
finally {
  try { $ws.Dispose() } catch {}
  try { Stop-Process -Id $process.Id -Force } catch {}
  Remove-Item -LiteralPath $profile -Recurse -Force -ErrorAction SilentlyContinue
}
