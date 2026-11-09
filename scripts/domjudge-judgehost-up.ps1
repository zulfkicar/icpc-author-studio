[CmdletBinding()]
param(
    [int]$TimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($repo -notmatch '^([A-Za-z]):\\(.*)$') { throw 'The repository must be on a mounted Windows drive.' }
$wslRepo = "/mnt/$($Matches[1].ToLower())/$($Matches[2] -replace '\\', '/')"
$compose = 'docker-compose.domjudge.yml'
$base = 'http://127.0.0.1:18080'

wsl -e sh -c "cd '$wslRepo' && docker compose -f $compose up -d mariadb domserver" | Out-Host
for ($i = 0; $i -lt 90; $i++) {
    try {
        $response = Invoke-WebRequest "$base/" -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) { break }
    } catch { }
    Start-Sleep -Seconds 2
    if ($i -eq 89) { throw 'DOMjudge server did not become reachable' }
}

$secret = ((wsl -e docker exec icpc-domjudge-server cat /opt/domjudge/domserver/etc/restapi.secret) | Out-String)
$line = ($secret -split "`n" | Where-Object { $_ -match '^default\s' } | Select-Object -First 1)
if (-not $line) { throw 'Could not read the DOMjudge restapi.secret' }
$parts = $line.Trim() -split '\s+'
$judgehostPassword = $parts[-1]
if (-not $judgehostPassword) { throw 'Could not read the judgehost password' }

$adminPassword = ((wsl -e docker exec icpc-domjudge-server cat /opt/domjudge/domserver/etc/initial_admin_password.secret) | Out-String).Trim()
$b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("admin:$adminPassword"))
$headers = @{ Authorization = "Basic $b64" }

Write-Host 'Starting the DOMjudge judgehost...'
$env:JUDGEDAEMON_PASSWORD = $judgehostPassword
wsl -e sh -c "cd '$wslRepo' && JUDGEDAEMON_PASSWORD='$judgehostPassword' docker compose -f $compose --profile judging up -d judgehost" | Out-Host

$registered = $false
for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
    try {
        $judgehosts = @(Invoke-RestMethod -Uri "$base/api/v4/judgehosts" -Headers $headers)
        $ours = @($judgehosts | Where-Object { $_.hostname -like 'judgedaemon-0*' -and $_.enabled })
        if ($ours.Count -gt 0) {
            $registered = $true
            $judgehosts = $ours
            break
        }
    } catch { }
    Start-Sleep -Seconds 1
}
if (-not $registered) {
    wsl -e docker logs icpc-domjudge-judgehost --tail 80 2>&1 | Out-Host
    throw 'The judgehost did not register with DOMjudge'
}
Write-Output ("judgehosts=" + (($judgehosts | ForEach-Object { $_.hostname }) -join ','))
Write-Output 'DOMJUDGE JUDGEHOST READY'
