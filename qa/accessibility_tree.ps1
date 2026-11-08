$ErrorActionPreference = 'Stop'
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$profile = Join-Path $env:TEMP ('author-axtree-' + [guid]::NewGuid().ToString('N'))
$process = Start-Process -FilePath $chrome -ArgumentList @('--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=9235',"--user-data-dir=$profile",'about:blank') -PassThru
try {
  Start-Sleep -Seconds 2
  $tabs = Invoke-RestMethod 'http://127.0.0.1:9235/json'
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
  Invoke-Cdp 'Accessibility.enable' @{} | Out-Null
  Invoke-Cdp 'Page.navigate' @{ url = 'http://127.0.0.1:8787/' } | Out-Null
  Start-Sleep -Seconds 3
  Eval @'
(async () => {
  await selectWorkspace('sum-test');
  await new Promise((resolve) => setTimeout(resolve, 500));
  return true;
})()
'@ | Out-Null
  $tree = Invoke-Cdp 'Accessibility.getFullAXTree' @{}
  $nodes = $tree.result.nodes
  $summary = [ordered]@{ buttons = 0; emptyButtons = @(); textboxes = 0; emptyTextboxes = @(); roles = @{}; names = @() }
  foreach ($node in $nodes) {
    $role = $node.role.value
    $name = $node.name.value
    if ($role -eq 'button') {
      $summary.buttons++
      if (-not $name) { $summary.emptyButtons += $node.nodeId }
    }
    if ($role -in @('textbox','combobox','searchbox')) {
      $summary.textboxes++
      if (-not $name) { $summary.emptyTextboxes += $node.nodeId }
    }
    if ($role -in @('button','tab','textbox','log','combobox','dialog','heading','status')) {
      $summary.names += ("$role=" + $name)
    }
  }
  Write-Output ($summary | ConvertTo-Json -Compress)
  $names = $summary.names -join "`n"
  foreach ($required in @('combobox=Problem workspace','log=Conversation','button=Verify','button=Build answers','button=Limits','button=Provider settings','textbox=Message the agent','heading=New chat')) {
    if ($names -notmatch [regex]::Escape($required)) { throw ("missing AX node: " + $required) }
  }
  if ($summary.emptyButtons.Count -gt 0) { throw ("buttons without names: " + ($summary.emptyButtons -join ',')) }
  if ($summary.emptyTextboxes.Count -gt 0) { throw ("text controls without names: " + ($summary.emptyTextboxes -join ',')) }
  Write-Output 'ACCESSIBILITY TREE AUDIT PASSED'
}
finally {
  try { $ws.Dispose() } catch {}
  try { Stop-Process -Id $process.Id -Force } catch {}
  Remove-Item -LiteralPath $profile -Recurse -Force -ErrorAction SilentlyContinue
}
