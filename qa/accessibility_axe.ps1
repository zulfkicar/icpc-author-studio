$ErrorActionPreference = 'Stop'
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$profile = Join-Path $env:TEMP ('author-axe-profile-' + [guid]::NewGuid().ToString('N'))
$axePath = Join-Path $PSScriptRoot '..\web\vendor\axe.min.js'
$axe = Get-Content -LiteralPath $axePath -Raw
$process = Start-Process -FilePath $chrome -ArgumentList @('--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=9232',"--user-data-dir=$profile",'about:blank') -PassThru
try {
  Start-Sleep -Seconds 2
  $tabs = Invoke-RestMethod 'http://127.0.0.1:9232/json'
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
  Invoke-Cdp 'Runtime.enable' @{} | Out-Null
  Invoke-Cdp 'Page.navigate' @{ url = 'http://127.0.0.1:8787/' } | Out-Null
  Start-Sleep -Seconds 3
  $expression = $axe + "`n;axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}}).then(r=>JSON.stringify({violations:r.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.length,help:v.help,targets:v.nodes.map(n=>n.target),details:v.nodes.slice(0,12).map(n=>({target:n.target,summary:n.failureSummary,data:n.any&&n.any[0]&&n.any[0].data}))})),passes:r.passes.length,incomplete:r.incomplete.length}))"
  $audit = Eval $expression
  Write-Output $audit
  $parsed = $audit | ConvertFrom-Json
  $blocking = @($parsed.violations | Where-Object { $_.impact -eq 'critical' -or $_.impact -eq 'serious' })
  Write-Output ("blocking=" + $blocking.Count)
  if ($blocking.Count -gt 0) {
    throw ("axe violations: " + ($blocking | ConvertTo-Json -Compress))
  }

  $opened = Eval @'
(async () => {
  const dialog = document.getElementById('settings-dialog');
  const button = document.getElementById('settings-btn');
  button.focus();
  button.click();
  await new Promise((resolve) => setTimeout(resolve, 100));
  return JSON.stringify({
    openInside: dialog.open && dialog.contains(document.activeElement),
    label: dialog.getAttribute('aria-label'),
    liveRegions: document.querySelectorAll('[aria-live]').length,
  });
})()
'@
  Invoke-Cdp 'Input.dispatchKeyEvent' @{ type = 'keyDown'; key = 'Escape'; code = 'Escape'; windowsVirtualKeyCode = 27; nativeVirtualKeyCode = 27 } | Out-Null
  Invoke-Cdp 'Input.dispatchKeyEvent' @{ type = 'keyUp'; key = 'Escape'; code = 'Escape'; windowsVirtualKeyCode = 27; nativeVirtualKeyCode = 27 } | Out-Null
  Start-Sleep -Milliseconds 200
  $closedState = Eval @'
(async () => {
  const dialog = document.getElementById('settings-dialog');
  const button = document.getElementById('settings-btn');
  return JSON.stringify({ closed: !dialog.open, focusReturned: document.activeElement === button });
})()
'@
  $keyboard = $opened.TrimEnd('}') + ',' + $closedState.TrimStart('{')
  Write-Output $keyboard
  $kb = $keyboard | ConvertFrom-Json
  if (-not $kb.openInside -or -not $kb.closed -or -not $kb.focusReturned) {
    throw ("keyboard/dialog audit failed: " + $keyboard)
  }

  # Optional light theme: reload with the saved preference and run the same
  # WCAG audit, so contrast is a gate in both themes.
  Eval 'localStorage.setItem("author-agent-theme", "light"); true' | Out-Null
  Invoke-Cdp 'Page.navigate' @{ url = 'http://127.0.0.1:8787/' } | Out-Null
  Start-Sleep -Seconds 3
  $lightTheme = Eval 'document.documentElement.dataset.theme'
  if ($lightTheme -ne 'light') { throw ("light theme did not apply: " + $lightTheme) }
  $lightAudit = Eval $expression
  Write-Output ("light=" + $lightAudit)
  $lightParsed = $lightAudit | ConvertFrom-Json
  $lightBlocking = @($lightParsed.violations | Where-Object { $_.impact -eq 'critical' -or $_.impact -eq 'serious' })
  Write-Output ("lightBlocking=" + $lightBlocking.Count)
  if ($lightBlocking.Count -gt 0) {
    throw ("light axe violations: " + ($lightBlocking | ConvertTo-Json -Compress))
  }
  Eval 'localStorage.setItem("author-agent-theme", "dark"); true' | Out-Null
  Write-Output 'AXE ACCESSIBILITY AUDIT PASSED'
}
finally {
  try { $ws.Dispose() } catch {}
  try { Stop-Process -Id $process.Id -Force } catch {}
  Remove-Item -LiteralPath $profile -Recurse -Force -ErrorAction SilentlyContinue
}
