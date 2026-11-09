$ErrorActionPreference = 'Stop'
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$profile = Join-Path $env:TEMP ('author-phase4-' + [guid]::NewGuid().ToString('N'))
$process = Start-Process -FilePath $chrome -ArgumentList @('--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=9239',"--user-data-dir=$profile",'about:blank') -PassThru
try {
  Start-Sleep -Seconds 2
  $tabs = Invoke-RestMethod 'http://127.0.0.1:9239/json'
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
  await openFile('submissions/accepted/ref.cpp');
  const chatState = document.body.dataset.stateChat;
  const fileLoadState = document.body.dataset.stateFileLoad;
  const exportClean = exportPredicate().enabled;
  const exportCleanTitle = document.getElementById('export-btn').title;

  switchTab('report');
  await loadReport();
  await wait(200);
  const reportText = document.getElementById('report-body').textContent;
  const reportLimits = reportText.includes('Limits:');
  const reportChecks = reportText.includes('Checks');
  const realSummary = state.summary;
  let staleBanner = false;
  if (realSummary && realSummary.lastReport) {
    state.summary = { ...realSummary, stale: true };
    renderReport(realSummary.lastReport);
    staleBanner = Boolean(document.querySelector('.stale-banner'));
    state.summary = realSummary;
    renderReport(realSummary.lastReport);
  }

  const path = 'phase4_review.txt';
  await api('/api/workspaces/sum-test/files', { method: 'POST', body: { path, kind: 'file' } });
  await api('/api/workspaces/sum-test/file', { method: 'POST', body: { path, content: 'review me\n' } });
  await refreshWorkspace();
  await loadReport();
  switchSide('changes');
  const queueActive = document.getElementById('side-changes').classList.contains('active');
  const unreviewedBefore = Number(document.getElementById('unreviewed-count').textContent);
  const exportBlocked = document.getElementById('export-btn').disabled;
  const exportBlockedTitle = document.getElementById('export-btn').title;
  const changesState = document.body.dataset.stateChanges;

  switchTab('report');
  await loadReport();
  await wait(200);
  const diffButton = document.querySelector('#report-body [data-open-diff]');
  const changedButton = Boolean(diffButton);
  if (diffButton) {
    diffButton.click();
    await wait(500);
  }
  const diffTab = document.getElementById('panel-diff').classList.contains('active');
  const diffTitle = document.getElementById('diff-title').textContent;

  switchSide('changes');
  document.getElementById('approve-btn').click();
  let unreviewedAfterReview = Number(document.getElementById('unreviewed-count').textContent);
  for (let attempt = 0; attempt < 20 && unreviewedAfterReview !== 0; attempt += 1) {
    await wait(200);
    unreviewedAfterReview = Number(document.getElementById('unreviewed-count').textContent);
  }

  await api('/api/workspaces/sum-test/files?path=' + encodeURIComponent(path), { method: 'DELETE' });
  const leftovers = (await api('/api/workspaces/sum-test/changes')).changes
    .filter((change) => change.path === path && !change.reverted);
  for (const change of leftovers.slice().reverse()) {
    try { await api('/api/workspaces/sum-test/changes/' + change.id + '/revert', { method: 'POST' }); } catch { /* keep going */ }
  }
  await refreshWorkspace();
  await loadReport();
  const exportRestored = exportPredicate().enabled;
  const unreviewedRestored = Number(document.getElementById('unreviewed-count').textContent);

  setStatus('stale');
  const staleState = document.body.dataset.stateVerification;
  setStatus('verified');
  const verifiedState = document.body.dataset.stateVerification;

  const composer = document.getElementById('composer');
  composer.value = '@';
  composer.dispatchEvent(new Event('input'));
  await wait(150);
  const mentionsState = document.body.dataset.stateMentions;
  const mentionMenu = !document.getElementById('mention-menu').hidden;
  hideMentions();
  const mentionsClosed = document.body.dataset.stateMentions === 'hidden';

  setFollow(false);
  const followPaused = document.body.dataset.stateFollow;
  const followButton = !document.getElementById('follow-btn').hidden;
  setFollow(true);
  const followLive = document.body.dataset.stateFollow;

  document.getElementById('settings-btn').click();
  await wait(150);
  const settingsInput = document.querySelector('#settings-form [name="model"]');
  settingsInput.value = 'phase4-model';
  settingsInput.dispatchEvent(new Event('input', { bubbles: true }));
  await wait(80);
  const settingsDirty = document.body.dataset.stateSettings;
  document.getElementById('settings-cancel').click();
  await wait(220);
  const discardDialog = document.getElementById('action-dialog').open;
  document.getElementById('action-cancel').click();
  await wait(160);
  const settingsKept = document.getElementById('settings-dialog').open;
  document.getElementById('settings-cancel').click();
  await wait(220);
  document.getElementById('action-confirm').click();
  await wait(220);
  const settingsClosed = !document.getElementById('settings-dialog').open;

  switchTab('mcp');
  await wait(700);
  const mcpState = document.body.dataset.stateMcp;

  machineSend('tests', 'RUN');
  machineSend('tests', 'PASS');
  const testsState = document.body.dataset.stateTests;
  machineSend('restore', 'ASK');
  machineSend('restore', 'RESTORE');
  machineSend('restore', 'DONE');
  const restoreState = document.body.dataset.stateRestore;

  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }));
  await wait(220);
  const quickOpenOpen = document.getElementById('palette-dialog').open && paletteMode === 'files';
  const quickOpenFocus = document.activeElement.id === 'palette-input';
  const quickOpenItems = document.querySelectorAll('#palette-list .palette-item').length;
  renderPalette('ref.cpp');
  const quickOpenFiltered = document.querySelectorAll('#palette-list .palette-item').length;
  runPalette(0);
  await wait(500);
  const quickOpenClosed = !document.getElementById('palette-dialog').open;
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'P', ctrlKey: true, shiftKey: true, bubbles: true }));
  await wait(220);
  const commandPaletteOpen = document.getElementById('palette-dialog').open && paletteMode === 'commands';
  const commandItems = document.querySelectorAll('#palette-list .palette-item').length;
  document.getElementById('palette-cancel').click();
  await wait(120);
  const paletteClosed = !document.getElementById('palette-dialog').open;

  composer.focus();
  const activeAfterFocus = document.activeElement.id;
  const statusTop = document.querySelector('.statusbar').getBoundingClientRect().top;
  const composerRect = composer.getBoundingClientRect();
  const centerX = composerRect.left + composerRect.width / 2;
  const centerY = composerRect.top + composerRect.height / 2;
  const hit = document.elementFromPoint(centerX, centerY);
  const composerNotObscured = composerRect.bottom <= statusTop + 1
    && Boolean(hit && (hit === composer || composer.contains(hit)));

  return JSON.stringify({
    chatState, fileLoadState, exportClean, exportCleanTitle,
    reportLimits, reportChecks, staleBanner,
    queueActive, unreviewedBefore, exportBlocked, exportBlockedTitle, changesState,
    changedButton, diffTab, diffTitle,
    unreviewedAfterReview, exportRestored, unreviewedRestored,
    staleState, verifiedState,
    mentionsState, mentionMenu, mentionsClosed,
    followPaused, followButton, followLive,
    settingsDirty, discardDialog, settingsKept, settingsClosed,
    mcpState, testsState, restoreState,
    quickOpenOpen, quickOpenFocus, quickOpenItems, quickOpenFiltered, quickOpenClosed,
    commandPaletteOpen, commandItems, paletteClosed,
    activeAfterFocus, composerNotObscured,
  });
})()
'@
  Write-Output ("phase4=" + $result)
  $r = $result | ConvertFrom-Json
  if ($r.chatState -ne 'loaded') { throw "chat machine is $($r.chatState)" }
  if ($r.fileLoadState -ne 'loaded') { throw "fileLoad machine is $($r.fileLoadState)" }
  if (-not $r.exportClean) { throw "export should be enabled for the clean verified workspace" }
  if (-not $r.reportLimits -or -not $r.reportChecks) { throw "report is missing limits or checks" }
  if (-not $r.staleBanner) { throw "stale banner did not render" }
  if (-not $r.queueActive) { throw "review queue is not the active navigator panel" }
  if ($r.unreviewedBefore -lt 1) { throw "unreviewed count did not rise" }
  if (-not $r.exportBlocked) { throw "export should be blocked while unreviewed" }
  if ([string]::IsNullOrWhiteSpace($r.exportBlockedTitle) -or $r.exportBlockedTitle -notmatch 'Verify|reviewed') { throw "export reason is not textual: $($r.exportBlockedTitle)" }
  if ($r.changesState -ne 'unreviewed') { throw "changes machine is $($r.changesState)" }
  if (-not $r.changedButton) { throw "report has no changed-file button" }
  if (-not $r.diffTab) { throw "changed-file button did not open the diff tab" }
  if ([string]::IsNullOrWhiteSpace($r.diffTitle) -or $r.diffTitle -eq 'Change diff') { throw "diff title is $($r.diffTitle)" }
  if ($r.unreviewedAfterReview -ne 0) { throw "review did not clear the queue" }
  if (-not $r.exportRestored) { throw "export was not restored after cleanup" }
  if ($r.unreviewedRestored -ne 0) { throw "unreviewed changes remain after cleanup" }
  if ($r.staleState -ne 'stale' -or $r.verifiedState -ne 'verified') { throw "verification machine did not mirror status" }
  if ($r.mentionsState -notin @('filtered','open') -or -not $r.mentionMenu) { throw "mentions did not open" }
  if (-not $r.mentionsClosed) { throw "mentions did not close" }
  if ($r.followPaused -ne 'paused' -or -not $r.followButton -or $r.followLive -ne 'following') { throw "follow machine did not mirror" }
  if ($r.settingsDirty -ne 'dirty') { throw "settings machine is $($r.settingsDirty)" }
  if (-not $r.discardDialog) { throw "dirty settings did not ask to discard" }
  if (-not $r.settingsKept) { throw "cancel did not keep settings open" }
  if (-not $r.settingsClosed) { throw "discard did not close settings" }
  if ($r.mcpState -notin @('enabled','disabled')) { throw "mcp machine is $($r.mcpState)" }
  if ($r.testsState -ne 'pass') { throw "tests machine is $($r.testsState)" }
  if ($r.restoreState -ne 'done') { throw "restore machine is $($r.restoreState)" }
  if (-not $r.quickOpenOpen -or -not $r.quickOpenFocus) { throw "Ctrl+K did not open quick open with focus" }
  if ($r.quickOpenItems -lt 1) { throw "quick open has no files" }
  if ($r.quickOpenFiltered -lt 1 -or $r.quickOpenFiltered -gt $r.quickOpenItems) { throw "quick open filter did not narrow results" }
  if (-not $r.quickOpenClosed) { throw "quick open did not close after opening a result" }
  if (-not $r.commandPaletteOpen -or $r.commandItems -lt 5) { throw "Ctrl+Shift+P did not open the command palette" }
  if (-not $r.paletteClosed) { throw "palette does not cancel" }
  if ($r.activeAfterFocus -ne 'composer') { throw "composer did not receive focus" }
  if (-not $r.composerNotObscured) { throw "composer focus is obscured" }

  Write-Output 'PHASE 4 EVIDENCE/AX/STATE TESTS PASSED'
}
finally {
  try { $ws.Dispose() } catch {}
  try { Stop-Process -Id $process.Id -Force } catch {}
  Remove-Item -LiteralPath $profile -Recurse -Force -ErrorAction SilentlyContinue
}
