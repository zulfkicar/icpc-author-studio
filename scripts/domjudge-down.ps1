[CmdletBinding()]
param(
    [switch]$Reset
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($repo -notmatch '^([A-Za-z]):\\(.*)$') { throw 'The repository must be on a mounted Windows drive.' }
$wslRepo = "/mnt/$($Matches[1].ToLower())/$($Matches[2] -replace '\\', '/')"

if ($Reset) {
    Write-Host 'Removing the local DOMjudge stack and database...'
    wsl -e sh -c "cd '$wslRepo' && docker compose -f docker-compose.domjudge.yml --profile judging down -v" | Out-Host
} else {
    Write-Host 'Stopping the local DOMjudge stack (database preserved)...'
    wsl -e sh -c "cd '$wslRepo' && docker compose -f docker-compose.domjudge.yml --profile judging down" | Out-Host
}
