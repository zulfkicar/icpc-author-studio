[CmdletBinding()]
param(
    [switch]$Reset
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($repo -notmatch '^([A-Za-z]):\\(.*)$') { throw 'The repository must be on a mounted Windows drive.' }
$wslRepo = "/mnt/$($Matches[1].ToLower())/$($Matches[2] -replace '\\', '/')"

wsl -e sh -c "cd '$wslRepo' && docker compose -f docker-compose.domjudge.yml up -d" | Out-Host
for ($i = 0; $i -lt 90; $i++) {
    try {
        $response = Invoke-WebRequest 'http://127.0.0.1:18080/' -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            $password = ((wsl -e docker exec icpc-domjudge-server cat /opt/domjudge/domserver/etc/initial_admin_password.secret) | Out-String).Trim()
            Write-Host ''
            Write-Host 'DOMjudge is ready: http://127.0.0.1:18080/'
            Write-Host "Admin user: admin"
            Write-Host "Admin password: $password"
            Write-Host 'Stop with scripts\domjudge-down.ps1 (add -Reset to delete the DOMjudge database).'
            exit 0
        }
    } catch { }
    Start-Sleep -Seconds 2
}
throw 'DOMjudge did not become reachable on 127.0.0.1:18080'
