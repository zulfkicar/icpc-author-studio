[CmdletBinding()]
param(
    [string]$Distro = "Ubuntu"
)

$ErrorActionPreference = "Stop"
$project = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ($project -notmatch '^([A-Za-z]):\\(.*)$') {
    throw "The project must be on a mounted Windows drive."
}
$drive = $Matches[1].ToLower()
$rest = ($Matches[2] -replace '\\', '/')
$wslProject = "/mnt/$drive/$rest"

$nativePreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
wsl.exe -e sh -c "cd '$wslProject' && docker compose down" 2>&1 | ForEach-Object { Write-Host $_ }
$ErrorActionPreference = $nativePreference

$pidFile = Join-Path $project ".author-agent\wsl-keepalive.pid"
if (Test-Path $pidFile) {
    $candidate = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($candidate) {
        Stop-Process -Id ([int]$candidate) -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}

Write-Host "ICPC Author Agent stopped."
