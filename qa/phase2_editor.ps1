$ErrorActionPreference = 'Stop'
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$profile = Join-Path $env:TEMP ('author-phase2-' + [guid]::NewGuid().ToString('N'))
$process = Start-Process -FilePath $chrome -ArgumentList @('--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=9238',"--user-data-dir=$profile",'about:blank') -PassThru
try {
  Start-Sleep -Seconds 2
  $tabs = Invoke-RestMethod 'http://127.0.0.1:9238/json'
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
  Invoke-Cdp 'Page.navigate' @{ url = 'http://127.0.0.1:8787/workbench' } | Out-Null
  Start-Sleep -Seconds 3

  $monaco = Eval @'
(async () => {
  await selectWorkspace('sum-test');
  await new Promise((resolve) => setTimeout(resolve, 450));
  await openFile('submissions/accepted/ref.cpp');
  const began = performance.now();
  await enterEditMode();
  const loadMs = Math.round(performance.now() - began);
  const host = document.getElementById('monaco-host');
  const editor = state.monaco && state.monaco.editor;
  if (editor) {
    editor.setPosition({ lineNumber: 2, column: 3 });
    editor.revealLine(2);
    editor.focus();
  }
  await new Promise((resolve) => setTimeout(resolve, 150));
  const hostHiddenAtEdit = host.hidden;
  const hostHeightAtEdit = Math.round(host.getBoundingClientRect().height);
  const hostLeftAtEdit = Math.round(host.getBoundingClientRect().left);
  const hostTopAtEdit = Math.round(host.getBoundingClientRect().top);
  const editorEl = document.querySelector('.monaco-editor');
  const editorLeftAtEdit = editorEl ? Math.round(editorEl.getBoundingClientRect().left) : -1;
  const viewLinesEl = document.querySelector('.monaco-editor .view-lines');
  const viewLinesLeftAtEdit = viewLinesEl ? Math.round(viewLinesEl.getBoundingClientRect().left) : -1;
  const shellHeightAtEdit = Math.round(document.querySelector('.editor-shell').getBoundingClientRect().height);
  const mainHeightAtEdit = Math.round(document.querySelector('.editor-main').getBoundingClientRect().height);
  const panelClassAtEdit = document.getElementById('panel-file').className;
  const hostDisplayAtEdit = getComputedStyle(host).display;
  const hostFlexAtEdit = getComputedStyle(host).flex;
  const textareaHiddenAtEdit = document.getElementById('file-editor').hidden;
  const cursorBefore = document.getElementById('editor-cursor').textContent;
  const tabsAfterOpen = document.querySelectorAll('#editor-tabs [role="tab"]').length;

  await switchEditorTab('NOTES.md');
  const tabsAfterSwitch = document.querySelectorAll('#editor-tabs [role="tab"]').length;
  await switchEditorTab('submissions/accepted/ref.cpp');
  const restoredCursor = document.getElementById('editor-cursor').textContent;
  const activeTitle = document.querySelector('#editor-tabs [role="tab"][aria-selected="true"]');
  const activeTab = activeTitle ? activeTitle.textContent : '';
  const tabBefore = state.file.path;
  await cycleEditorTab(1);
  await new Promise((resolve) => setTimeout(resolve, 250));
  const tabAfterCycle = state.file.path;
  await cycleEditorTab(-1);
  await new Promise((resolve) => setTimeout(resolve, 250));
  const tabRestored = state.file.path === tabBefore;

  const change = state.changes.find((item) => !item.reverted);
  await openChangeDiff(change.id);
  document.getElementById('diff-mode').click();
  await new Promise((resolve) => setTimeout(resolve, 700));
  const diffVisible = !document.getElementById('monaco-diff').hidden && state.diffMonaco === true;
  const diffModel = Boolean(state.monaco && state.monaco.diffEditor && state.monaco.diffEditor.getModel());
  document.getElementById('diff-mode').click();
  const inlineRestored = !document.getElementById('diff-body').hidden && document.getElementById('monaco-diff').hidden;

  return JSON.stringify({
    engine: state.editorEngine,
    monacoLoaded: Boolean(window.monaco),
    hostHidden: hostHiddenAtEdit,
    hostHeight: hostHeightAtEdit,
    shellHeight: shellHeightAtEdit,
    mainHeight: mainHeightAtEdit,
    panelClass: panelClassAtEdit,
    hostDisplay: hostDisplayAtEdit,
    hostFlex: hostFlexAtEdit,
    hostPosition: getComputedStyle(host).position,
    hostLeft: hostLeftAtEdit,
    hostTop: hostTopAtEdit,
    editorLeftAtEdit,
    viewLinesLeftAtEdit,
    scrollLeft: editor ? editor.getScrollLeft() : -1,
    scrollTop: editor ? editor.getScrollTop() : -1,
    cursor: editor && editor.getPosition() ? editor.getPosition() : null,

    hostVisible: !hostHiddenAtEdit && hostHeightAtEdit > 100,
    textareaHidden: textareaHiddenAtEdit,
    tabsAfterOpen,
    tabsAfterSwitch,
    loadMs,
    cursorBefore,
    restoredCursor,
    activeTab,
    tabAfterCycle,
    tabRestored,
    diffVisible,
    diffModel,
    inlineRestored,
  });
})()
'@
  Write-Output ("monaco=" + $monaco)
  $m = $monaco | ConvertFrom-Json
  if ($m.engine -ne 'monaco') { throw "editor engine is not monaco" }
  if (-not $m.monacoLoaded) { throw "window.monaco is missing" }
  if ($m.loadMs -gt 2000) { throw "editor interactive time is $($m.loadMs) ms, over the 2000 ms budget" }
  if (-not $m.hostVisible) { throw "monaco host is not visible" }
  if (-not $m.textareaHidden) { throw "textarea is still visible with monaco" }
  if ($m.tabsAfterOpen -lt 1) { throw "editor tab was not created" }
  if ($m.tabsAfterSwitch -lt 2) { throw "editor tabs did not accumulate" }
  if ($m.activeTab -notmatch 'ref\.cpp') { throw "active tab did not return to ref.cpp" }
  if ($m.tabAfterCycle -eq 'submissions/accepted/ref.cpp') { throw "Ctrl+Tab cycle did not change tabs" }
  if (-not $m.tabRestored) { throw "Ctrl+Tab cycle did not return to the original tab" }
  if ($m.cursorBefore -ne $m.restoredCursor) { throw "cursor was not preserved across tabs: $($m.cursorBefore) vs $($m.restoredCursor)" }
  if (-not $m.diffVisible -or -not $m.diffModel) { throw "monaco diff did not open" }
  if (-not $m.inlineRestored) { throw "inline diff did not restore" }

  $dirty = Eval @'
(async () => {
  const path = 'phase2_save.txt';
  await api('/api/workspaces/sum-test/files', { method: 'POST', body: { path, kind: 'file' } });
  await api('/api/workspaces/sum-test/file', { method: 'POST', body: { path, content: 'line one\nline two\n' } });
  await openFile(path);
  await enterEditMode();
  await new Promise((resolve) => setTimeout(resolve, 250));
  const editor = state.monaco.editor;
  editor.getModel().setValue('line one\nline two changed\n');
  await new Promise((resolve) => setTimeout(resolve, 120));
  const dirtyDot = Boolean(document.querySelector('#editor-tabs .editor-tab.active .editor-tab-dirty'));
  const dirtyBefore = state.dirty;

  const cancelSwitch = switchEditorTab('submissions/accepted/ref.cpp');
  await new Promise((resolve) => setTimeout(resolve, 180));
  const dialogOpen = document.getElementById('action-dialog').open;
  document.getElementById('action-cancel').click();
  await cancelSwitch;
  const stayed = state.file.path === path && state.dirty;

  document.dispatchEvent(new KeyboardEvent('keydown', { key: 's', ctrlKey: true, bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 700));
  const savedClean = !state.dirty && document.getElementById('save-file').hidden;
  const savedContent = (await api('/api/workspaces/sum-test/file?path=' + encodeURIComponent(path))).content;

  await enterEditMode();
  await new Promise((resolve) => setTimeout(resolve, 250));
  state.monaco.editor.getModel().setValue('discard me\n');
  await new Promise((resolve) => setTimeout(resolve, 100));
  const confirmSwitch = switchEditorTab('submissions/accepted/ref.cpp');
  await new Promise((resolve) => setTimeout(resolve, 180));
  const discardOpen = document.getElementById('action-dialog').open;
  document.getElementById('action-confirm').click();
  await confirmSwitch;
  const switched = state.file.path === 'submissions/accepted/ref.cpp';

  await api('/api/workspaces/sum-test/files?path=' + encodeURIComponent(path), { method: 'DELETE' });
  const leftovers = (await api('/api/workspaces/sum-test/changes')).changes
    .filter((change) => change.path === path && !change.reverted);
  for (const change of leftovers.slice().reverse()) {
    try { await api('/api/workspaces/sum-test/changes/' + change.id + '/revert', { method: 'POST' }); } catch { /* keep going */ }
  }
  await refreshWorkspace();
  await openFile('problem.pdf');
  const binary = state.file.text === false && document.getElementById('edit-file').hidden;
  await enterEditMode();
  const binaryStaysOut = state.fileMode === 'view' && document.getElementById('monaco-host').hidden;

  return JSON.stringify({ dirtyDot, dirtyBefore, dialogOpen, stayed, savedClean, savedContent, discardOpen, switched, binary, binaryStaysOut });
})()
'@
  Write-Output ("dirty=" + $dirty)
  $d = $dirty | ConvertFrom-Json
  if (-not $d.dirtyDot -or -not $d.dirtyBefore) { throw "monaco edit did not mark the tab dirty" }
  if (-not $d.dialogOpen) { throw "dirty tab switch did not ask for confirmation" }
  if (-not $d.stayed) { throw "cancel did not keep the dirty tab" }
  if (-not $d.savedClean) { throw "Ctrl+S did not save and clear the dirty state" }
  if ($d.savedContent -notmatch 'line two changed') { throw "saved content is wrong: $($d.savedContent)" }
  if (-not $d.discardOpen) { throw "second dirty switch did not ask for confirmation" }
  if (-not $d.switched) { throw "confirm did not switch tabs" }
  if (-not $d.binary) { throw "binary file entered edit mode" }
  if (-not $d.binaryStaysOut) { throw "enterEditMode changed a binary file" }

  $tree = Eval @'
(async () => {
  const host = document.getElementById('file-tree');
  const rows = [...host.querySelectorAll('.tree-row')];
  const first = rows[0];
  first.focus();
  first.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
  const moved = document.activeElement !== first && document.activeElement.closest('.tree-row') === document.activeElement;
  const dir = rows.find((row) => row.dataset.kind === 'dir' && row.getAttribute('aria-expanded') === 'false');
  let expanded = false;
  if (dir) {
    dir.focus();
    dir.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve, 120));
    expanded = true;
  }
  return JSON.stringify({ moved, expanded, rows: rows.length, role: host.getAttribute('role') });
})()
'@
  Write-Output ("tree=" + $tree)
  $t = $tree | ConvertFrom-Json
  if (-not $t.moved) { throw "tree ArrowDown did not move focus" }
  if ($t.role -ne 'tree') { throw "tree role is missing" }

  Invoke-Cdp 'Page.navigate' @{ url = 'http://127.0.0.1:8787/workbench?editor=textarea' } | Out-Null
  Start-Sleep -Seconds 3
  $fallback = Eval @'
(async () => {
  await selectWorkspace('sum-test');
  await new Promise((resolve) => setTimeout(resolve, 400));
  await openFile('submissions/accepted/ref.cpp');
  await enterEditMode();
  const editor = document.getElementById('file-editor');
  return JSON.stringify({
    engine: state.editorEngine,
    textareaVisible: !editor.hidden && !editor.disabled,
    monacoHidden: document.getElementById('monaco-host').hidden,
    valueLength: editor.value.length,
  });
})()
'@
  Write-Output ("fallback=" + $fallback)
  $f = $fallback | ConvertFrom-Json
  if ($f.engine -ne 'textarea') { throw "forced fallback did not use the textarea" }
  if (-not $f.textareaVisible) { throw "fallback textarea is not editable" }
  if (-not $f.monacoHidden) { throw "monaco host is visible in fallback" }
  if ($f.valueLength -lt 10) { throw "fallback textarea is empty" }

  Write-Output 'PHASE 2 EDITOR TESTS PASSED'
}
finally {
  try { $ws.Dispose() } catch {}
  try { Stop-Process -Id $process.Id -Force } catch {}
  Remove-Item -LiteralPath $profile -Recurse -Force -ErrorAction SilentlyContinue
}
