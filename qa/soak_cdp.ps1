$ErrorActionPreference = 'Stop'
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$profile = Join-Path $env:TEMP ('author-soak-' + [guid]::NewGuid().ToString('N'))
$process = Start-Process -FilePath $chrome -ArgumentList @('--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=9234',"--user-data-dir=$profile",'about:blank') -PassThru
try {
  Start-Sleep -Seconds 2
  $tabs = Invoke-RestMethod 'http://127.0.0.1:9234/json'
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
  $result = Eval @'
(async () => {
  window.__soakErrors = [];
  window.addEventListener('error', (event) => window.__soakErrors.push(String(event.message)));
  window.addEventListener('unhandledrejection', (event) => window.__soakErrors.push(String(event.reason)));
  await selectWorkspace('sum-test');
  await new Promise((resolve) => setTimeout(resolve, 300));
  const before = document.getElementsByTagName('*').length;
  const started = performance.now();
  for (let i = 0; i < 30; i++) {
    for (const tab of ['plan', 'file', 'report', 'diff', 'history', 'mcp']) {
      switchTab(tab);
    }
    switchSide(i % 2 ? 'files' : 'chats');
  }
  await new Promise((resolve) => setTimeout(resolve, 200));
  const after = document.getElementsByTagName('*').length;
  return JSON.stringify({
    iterations: 30,
    elapsedMs: Math.round(performance.now() - started),
    growth: after - before,
    errors: window.__soakErrors.slice(0, 5),
  });
})()
'@
  Write-Output $result
  $parsed = $result | ConvertFrom-Json
  if ($parsed.errors.Count -gt 0) { throw ("browser errors: " + $result) }
  if ($parsed.growth -gt 1500) { throw ("DOM growth too high: " + $result) }
  if ($parsed.elapsedMs -gt 20000) { throw ("soak too slow: " + $result) }
  Write-Output 'CDP SOAK PASSED'
}
finally {
  try { $ws.Dispose() } catch {}
  try { Stop-Process -Id $process.Id -Force } catch {}
  Remove-Item -LiteralPath $profile -Recurse -Force -ErrorAction SilentlyContinue
}
