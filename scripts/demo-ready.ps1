[CmdletBinding()]
param(
    [switch]$PrepareData,
    [switch]$OpenBrowser
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$app = 'http://127.0.0.1:8787'
$domjudge = 'http://127.0.0.1:18080'

function Test-App {
    try { return [bool](Invoke-RestMethod "$app/api/health" -TimeoutSec 3).ok } catch { return $false }
}
function Test-Domjudge {
    try { return (Invoke-WebRequest "$domjudge/" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { return $false }
}

if (-not (Test-App)) {
    Write-Host 'Starting the authoring app...'
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'docker-up.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'The authoring app did not start' }
}
if (-not (Test-Domjudge)) {
    Write-Host 'Starting DOMjudge...'
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'domjudge-up.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'DOMjudge did not start' }
}

$adminPassword = ((wsl -e docker exec icpc-domjudge-server cat /opt/domjudge/domserver/etc/initial_admin_password.secret) | Out-String).Trim()
$b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("admin:$adminPassword"))
$headers = @{ Authorization = "Basic $b64" }
function Get-Judgehosts {
    $response = Invoke-RestMethod "$domjudge/api/v4/judgehosts" -Headers $headers
    if ($response -is [System.Array]) { return @($response) }
    if ($response.PSObject.Properties.Name -contains 'value') { return @($response.value) }
    return @($response)
}
$judgehosts = Get-Judgehosts
$ourJudgehost = @($judgehosts | Where-Object { $_.hostname -like 'judgedaemon-0*' -and $_.enabled })
if ($ourJudgehost.Count -eq 0) {
    Write-Host 'Starting the DOMjudge judgehost...'
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'domjudge-judgehost-up.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'The DOMjudge judgehost did not start' }
    $judgehosts = Get-Judgehosts
    $ourJudgehost = @($judgehosts | Where-Object { $_.hostname -like 'judgedaemon-0*' -and $_.enabled })
}
if ($ourJudgehost.Count -eq 0) { throw 'No enabled judgedaemon-0 judgehost' }

if ($PrepareData) {
    Write-Host 'Preparing the import and AC/WA/TLE judging data...'
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo 'qa\test_domjudge_import.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'DOMjudge import preparation failed' }
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo 'qa\test_domjudge_judging.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'DOMjudge judging preparation failed' }
}

$state = Invoke-RestMethod "$app/api/state"
$settings = $state.settings
$workspaces = @($state.workspaces | ForEach-Object { $_.slug })

Write-Host ''
Write-Host '================ DEMO READY ================'
Write-Host "App:        $app/"
Write-Host "DOMjudge:   $domjudge/"
Write-Host "Admin:      admin"
Write-Host "Password:   $adminPassword"
Write-Host "Provider:   $($settings.model)  (hasKey=$($settings.hasKey))"
Write-Host "Workspaces: $($workspaces -join ', ')"
Write-Host "Judgehost:  $($ourJudgehost[0].hostname)"
if ($PrepareData) { Write-Host 'DOMjudge:   demo contest / sum-test-qa with AC, WA, TLE submissions' }
Write-Host ''
Write-Host 'Open the app, select sum-test, open submissions/accepted/ref.cpp,'
Write-Host 'open Report and Changes, then run the demo narrative in docs/DEMO.md.'
Write-Host 'Stop at the end with scripts\docker-down.ps1 and scripts\domjudge-down.ps1.'
Write-Host '============================================'

if ($OpenBrowser) {
    Start-Process "$app/"
    Start-Process "$domjudge/"
}
exit 0
