$ErrorActionPreference = 'Stop'
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$profile = Join-Path $env:TEMP ('author-phase5-' + [guid]::NewGuid().ToString('N'))
$process = Start-Process -FilePath $chrome -ArgumentList @('--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=9240',"--user-data-dir=$profile",'about:blank') -PassThru
try {
  Start-Sleep -Seconds 2
  $tabs = Invoke-RestMethod 'http://127.0.0.1:9240/json'
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
        $buffer = New-Object byte[] 2097152
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

  $result = Eval @'
(async () => {
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  await selectWorkspace('sum-test');
  await wait(500);

  notify('Phase 5 notice', 'Notification centre smoke test', { tab: 'report' });
  document.getElementById('notifications-btn').click();
  await wait(160);
  const panel = document.getElementById('notifications-panel');
  const bell = document.getElementById('notifications-btn');
  const opened = !panel.hidden && bell.getAttribute('aria-expanded') === 'true';
  const listCount = document.querySelectorAll('#notifications-list .notification-item').length;
  const badge = document.getElementById('notification-count');
  const badgeText = badge.hidden ? '' : badge.textContent;
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  await wait(120);
  const closed = panel.hidden && document.activeElement === bell;
  document.getElementById('notifications-btn').click();
  await wait(120);
  document.querySelector('#notifications-list .notification-item').click();
  await wait(250);
  const clicked = panel.hidden && document.getElementById('panel-report').classList.contains('active');

  notifyJob('Verification', 'report');
  const activeRunning = document.getElementById('status-job').textContent;
  finishJobNotification('Finished', 'success');
  const activeIdle = document.getElementById('status-job').textContent;
  const activeText = document.getElementById('notifications-active').textContent;
  const unreadBadge = document.getElementById('notification-count').textContent;
  document.getElementById('notifications-btn').click();
  await wait(100);
  document.getElementById('notifications-clear').click();
  await wait(100);
  const cleared = document.querySelectorAll('#notifications-list .notification-item').length === 0;
  document.getElementById('notifications-close').click();
  await wait(100);

  toast('phase5 dedupe');
  toast('phase5 dedupe');
  const toastCount = document.getElementById('toast').dataset.count;
  const toastText = document.getElementById('toast').textContent;

  applyTheme('light');
  const lightTheme = document.documentElement.dataset.theme;
  const lightBg = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();
  const lightLabel = document.getElementById('theme-btn').getAttribute('aria-label');
  const persisted = localStorage.getItem('author-agent-theme');
  applyTheme('dark');
  const darkTheme = document.documentElement.dataset.theme;
  const darkBg = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();

  openTour();
  await wait(160);
  const tourOpen = document.getElementById('tour-dialog').open;
  const tourTitle = document.getElementById('tour-title').textContent;
  tourNext();
  const tourStep2 = state.tourStep;
  tourNext();
  const tourStep3 = state.tourStep;
  tourNext();
  await wait(160);
  const tourClosed = !document.getElementById('tour-dialog').open;
  const tourSeen = localStorage.getItem('author-agent-tour-seen');
  openTour();
  await wait(120);
  document.getElementById('tour-dialog').dispatchEvent(new Event('cancel', { cancelable: true }));
  await wait(150);
  const tourEscape = !document.getElementById('tour-dialog').open && document.activeElement.id === 'tour-btn';

  await selectWorkspace(null);
  await wait(350);
  const emptyButton = document.querySelector('[data-empty-new]');
  const emptyState = Boolean(emptyButton);
  if (emptyButton) emptyButton.click();
  await wait(120);
  const emptyOpensNew = document.getElementById('new-dialog').open;
  document.getElementById('new-cancel').click();
  await selectWorkspace('sum-test');
  await wait(500);

  return JSON.stringify({
    opened, listCount, badgeText, closed, clicked,
    activeRunning, activeIdle, activeText, unreadBadge, cleared,
    toastCount, toastText,
    lightTheme, lightBg, lightLabel, persisted, darkTheme, darkBg,
    tourOpen, tourTitle, tourStep2, tourStep3, tourClosed, tourSeen, tourEscape,
    emptyState, emptyOpensNew,
  });
})()
'@
  Write-Output ("phase5=" + $result)
  $r = $result | ConvertFrom-Json
  if (-not $r.opened -or $r.listCount -lt 1 -or -not $r.badgeText) { throw "notification panel did not open with an item" }
  if (-not $r.closed) { throw "Escape did not close notifications and return focus" }
  if (-not $r.clicked) { throw "notification click did not open its tab" }
  if ($r.activeRunning -ne 'running') { throw "long-job status is $($r.activeRunning)" }
  if ($r.activeIdle -ne 'idle') { throw "long-job status did not return to idle" }
  if ($r.activeText -ne 'No active job') { throw "active job label is $($r.activeText)" }
  if ([int]$r.unreadBadge -lt 1) { throw "unread badge did not rise" }
  if (-not $r.cleared) { throw "clear notifications left items" }
  if ($r.toastCount -ne '2') { throw "toast dedupe count is $($r.toastCount)" }
  if ($r.toastText -ne 'phase5 dedupe') { throw "toast text changed on dedupe" }
  if ($r.lightTheme -ne 'light' -or $r.lightBg -ne '#f5f7fb') { throw "light theme did not apply: $($r.lightTheme) $($r.lightBg)" }
  if ($r.lightLabel -ne 'Switch to dark theme') { throw "theme label is $($r.lightLabel)" }
  if ($r.persisted -ne 'light') { throw "theme was not persisted" }
  if ($r.darkTheme -ne 'dark' -or $r.darkBg -ne '#0a0c10') { throw "dark theme did not restore: $($r.darkTheme) $($r.darkBg)" }
  if (-not $r.tourOpen -or $r.tourTitle -notmatch 'five-region') { throw "tour did not open at step 1" }
  if ($r.tourStep2 -ne 1 -or $r.tourStep3 -ne 2) { throw "tour steps did not advance" }
  if (-not $r.tourClosed -or $r.tourSeen -ne '1') { throw "tour did not complete/persist" }
  if (-not $r.tourEscape) { throw "tour Escape did not close and return focus" }
  if (-not $r.emptyState -or -not $r.emptyOpensNew) { throw "empty state does not offer New problem" }

  Write-Output 'PHASE 5 POLISH TESTS PASSED'
}
finally {
  try { $ws.Dispose() } catch {}
  try { Stop-Process -Id $process.Id -Force } catch {}
  Remove-Item -LiteralPath $profile -Recurse -Force -ErrorAction SilentlyContinue
}
