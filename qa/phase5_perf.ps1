$ErrorActionPreference = 'Stop'
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$profile = Join-Path $env:TEMP ('author-phase5-perf-' + [guid]::NewGuid().ToString('N'))
$process = Start-Process -FilePath $chrome -ArgumentList @('--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=9241',"--user-data-dir=$profile",'about:blank') -PassThru
try {
  Start-Sleep -Seconds 2
  $tabs = Invoke-RestMethod 'http://127.0.0.1:9241/json'
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
  await enterEditMode();
  await wait(300);
  await enterViewMode();
  await wait(120);
  const warmStart = performance.now();
  await enterEditMode();
  const editorWarmMs = Math.round(performance.now() - warmStart);
  await wait(150);

  const messages = document.getElementById('messages');
  messages.innerHTML = '';
  const appendStart = performance.now();
  for (let index = 0; index < 100; index += 1) addMessage('assistant', `perf message ${index}`);
  const appendAvgMs = Math.round(((performance.now() - appendStart) / 100) * 100) / 100;
  await loadConversation();
  await wait(150);

  const shifts = [];
  let observer = null;
  if (window.PerformanceObserver) {
    observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (!entry.hadRecentInput) shifts.push(entry.value);
      }
    });
    observer.observe({ type: 'layout-shift', buffered: false });
  }
  document.getElementById('run-stdin').value = '1 2\n';
  const panelBefore = document.getElementById('run-panel').getBoundingClientRect().top;
  const runStart = performance.now();
  await runFile();
  const runMs = Math.round(performance.now() - runStart);
  await wait(900);
  if (observer) observer.disconnect();
  const panelAfter = document.getElementById('run-panel').getBoundingClientRect().top;
  const runPanelShiftPx = Math.abs(Math.round(panelAfter - panelBefore));
  const layoutShift = Math.round(shifts.reduce((total, value) => total + value, 0) * 10000) / 10000;
  const runOk = state.runHistory.length > 0 && state.runHistory[0].ok;

  const big = 'x'.repeat(1024 * 1024);
  const renderStart = performance.now();
  pushRunHistory({ ok: true, status: 'OK', stdout: big, stderr: '', compileOutput: '', ms: 1, memory: 1024 }, 'local');
  const render1MbMs = Math.round(performance.now() - renderStart);
  state.runHistory = [];
  saveRunHistory();
  resetRunOutput();
  showRunPane('stdin');

  return JSON.stringify({ editorWarmMs, appendAvgMs, layoutShift, runPanelShiftPx, runMs, runOk, render1MbMs });
})()
'@
  Write-Output ("perf=" + $result)
  $p = $result | ConvertFrom-Json
  if ($p.editorWarmMs -ge 2000) { throw "editor warm time is $($p.editorWarmMs) ms" }
  if ($p.appendAvgMs -ge 16) { throw "transcript append is $($p.appendAvgMs) ms/frame" }
  if ($p.layoutShift -ge 0.1) { throw "layout shift on run start is $($p.layoutShift)" }
  if ($p.runPanelShiftPx -gt 2) { throw "run panel shifted $($p.runPanelShiftPx) px" }
  if (-not $p.runOk) { throw "local run did not succeed" }
  if ($p.render1MbMs -ge 50) { throw "1 MB output rendered in $($p.render1MbMs) ms" }
  Write-Output 'PHASE 5 PERFORMANCE BUDGETS PASSED'
}
finally {
  try { $ws.Dispose() } catch {}
  try { Stop-Process -Id $process.Id -Force } catch {}
  Remove-Item -LiteralPath $profile -Recurse -Force -ErrorAction SilentlyContinue
}
