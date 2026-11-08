$ErrorActionPreference = 'Stop'
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$profile = Join-Path $env:TEMP 'author-cdp-profile'
$repo = Split-Path $PSScriptRoot -Parent
Remove-Item -LiteralPath $profile -Recurse -Force -ErrorAction SilentlyContinue

$setup = @"
import sys
sys.path.insert(0, r'$repo')
import workspace, graph_agent
from qa.stress_agent import FakeChat, use_model
created = workspace.create('QA CDP Workflow', 'cdp workflow')
slug = created['slug']
chat = workspace.ensure_chats(slug)['activeChat']
use_model(FakeChat(auto_text='cdp history'))
graph_agent.run_turn(slug, chat, 'seed checkpoint', lambda *_: None)
workspace.save_pending(slug, chat, [{"id": "cdp-clar", "value": {"type": "clarification", "questions": ["Which format?"], "options": ["a", "b"], "recommended": "a"}}])
workspace.write_text(slug, 'notes.txt', 'a\nb\nc\nd\ne\nf\ng\nh\ni\nj\n', source='test')
workspace.write_text(slug, 'notes.txt', 'a\nB\nc\nd\ne\nf\ng\nh\ni\nJ\n', source='test')
workspace.write_text(slug, 'hello.cpp', 'int main(){return 0;}\n', source='test')
print(slug + ' ' + chat)
"@
$setupResult = $setup | python -
$slug, $chat = $setupResult.Trim().Split(' ')
if (-not $slug) { throw 'setup failed' }
$process = Start-Process -FilePath $chrome -ArgumentList @('--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=9231',"--user-data-dir=$profile",'about:blank') -PassThru
try {
  Start-Sleep -Seconds 2
  $tabs = Invoke-RestMethod 'http://127.0.0.1:9231/json'
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
      $buffer = New-Object byte[] 2097152
      $segment = [System.ArraySegment[byte]]::new($buffer)
      $result = $ws.ReceiveAsync($segment, $ct).Result
      $text = [Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count)
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
  $result = Eval @"
(async () => {
  await selectWorkspace('$slug');
  await openFile('notes.txt');
  const change = state.changes.find((item) => !item.reverted);
  if (!change) throw new Error('no change');
  await openChangeDiff(change.id);
  const hunkRows = document.querySelectorAll('.hunk-row').length;
  switchTab('history');
  await loadHistory();
  const historyRows = document.querySelectorAll('#history-body tbody tr').length;
  document.getElementById('composer').value = '@notes';
  document.getElementById('composer').dispatchEvent(new Event('input'));
  setFollow(false);
  const followPaused = !document.getElementById('follow-btn').hidden;
  setFollow(true);
  state.fileBusy = true;
  runFile();
  const busyGuard = state.fileBusy;
  state.fileBusy = false;
  const oldFile = state.file;
  state.file = { path: 'missing.cpp', text: true, content: '', size: 0 };
  await runFile();
  const errorShown = document.getElementById('run-output').classList.contains('err') && Boolean(document.getElementById('run-output').textContent);
  state.file = oldFile;
  const clarificationVisible = !!document.querySelector('.clarification-card');
  document.querySelectorAll('.approval-card').forEach((card) => card.remove());
  const fake = [{ id: 'fake', value: { action_requests: [{ name: 'test_action', args: {}, description: 'test' }] } }];
  renderApproval(fake);
  const approvalBefore = document.querySelectorAll('.approval-card').length;
  renderApproval(fake);
  const approvalAfter = document.querySelectorAll('.approval-card').length;
  switchTab('mcp');
  await new Promise((resolve) => setTimeout(resolve, 500));
  const mcpRows = document.querySelectorAll('[data-mcp-tool]').length;
  const mcpToggle = !!document.getElementById('mcp-enabled');
  const mcpSave = !!document.getElementById('mcp-save');
  const treeGlyphs = Array.from(document.querySelectorAll('.tree-icon')).map((node) => node.textContent);
  await api('/api/settings', { method: 'POST', body: { judge0Url: 'http://127.0.0.1:2358' } });
  state.settings = (await api('/api/state')).settings;
  await openFile('hello.cpp');
  const judge0Visible = !document.getElementById('judge0-run').hidden;
  await api('/api/settings', { method: 'POST', body: { judge0Url: '' } });
  return {
    judge0Visible,
    mcpRows,
    mcpToggle,
    mcpSave,
    treeGlyphsOk: treeGlyphs.length > 0 && treeGlyphs.every((glyph) => glyph !== '?'),
    busyGuard,
    errorShown,
    approvalBefore,
    approvalAfter,
    approvalDedupe: approvalBefore === 1 && approvalAfter === 1,
    clarificationVisible,
    xssEscaped: !escapeHtml('<img src=x onerror=1>').includes('<img'),
    composerFocusable: (() => { const c = document.getElementById('composer'); c.focus(); return document.activeElement.id === 'composer'; })(),
    followPaused,
    hunkRows,
    historyRows,
    mentionVisible: !document.getElementById('mention-menu').hidden,
    stage: document.getElementById('stage-rail').textContent.slice(0, 80),
    charts: document.querySelectorAll('.hunk-row').length,
    diffVisible: !document.getElementById('panel-diff').hidden || document.getElementById('panel-diff').classList.contains('active'),
  };
})()
"@
  Invoke-Cdp 'Emulation.setDeviceMetricsOverride' @{ width = 320; height = 800; deviceScaleFactor = 1; mobile = $false } | Out-Null
  $reflow = Eval 'document.documentElement.scrollWidth <= 320'
  Invoke-Cdp 'Emulation.clearDeviceMetricsOverride' @{} | Out-Null
  $result | Add-Member -NotePropertyName reflow320 -NotePropertyValue $reflow
  Eval 'document.getElementById("composer").focus()' | Out-Null
  $focus = @()
  for ($i = 0; $i -lt 6; $i++) {
    Invoke-Cdp 'Input.dispatchKeyEvent' @{ type = 'keyDown'; key = 'Tab'; code = 'Tab'; windowsVirtualKeyCode = 9; nativeVirtualKeyCode = 9 } | Out-Null
    Invoke-Cdp 'Input.dispatchKeyEvent' @{ type = 'keyUp'; key = 'Tab'; code = 'Tab'; windowsVirtualKeyCode = 9; nativeVirtualKeyCode = 9 } | Out-Null
    $focus += Eval '(document.activeElement && (document.activeElement.id || document.activeElement.tagName)) || "body"'
  }
  $result | Add-Member -NotePropertyName keyboardFocus -NotePropertyValue $focus
  $result | ConvertTo-Json -Compress
}
finally {
  try { $ws.Dispose() } catch {}
  try { Stop-Process -Id $process.Id -Force } catch {}
  @"
import sys, shutil
sys.path.insert(0, r'$repo')
import workspace
shutil.rmtree(workspace.ws_path('$slug'), ignore_errors=True)
"@ | python -
}
