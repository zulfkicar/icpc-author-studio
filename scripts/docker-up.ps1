[CmdletBinding()]
param(
    [string]$Distro = "Ubuntu",
    [int]$Port = 8787
)

$ErrorActionPreference = "Stop"
$project = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ($project -notmatch '^([A-Za-z]):\\(.*)$') {
    throw "The project must be on a mounted Windows drive."
}
$drive = $Matches[1].ToLower()
$rest = ($Matches[2] -replace '\\', '/')
$wslProject = "/mnt/$drive/$rest"

$stateDir = Join-Path $project ".author-agent"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$pidFile = Join-Path $stateDir "wsl-keepalive.pid"

$keepalive = $null
if (Test-Path $pidFile) {
    $candidate = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($candidate) {
        $keepalive = Get-Process -Id ([int]$candidate) -ErrorAction SilentlyContinue
    }
}

if (-not $keepalive) {
    # WSL stops the distro when idle, which stops dockerd and the container.
    # A hidden foreground process inside WSL keeps the distro alive.
    $keepalive = Start-Process -FilePath "wsl.exe" `
        -ArgumentList @("-d", $Distro, "-u", "root", "-e", "sh", "-c", "tail -f /dev/null") `
        -WindowStyle Hidden -PassThru
    Set-Content -Path $pidFile -Value $keepalive.Id
    Start-Sleep -Seconds 2
}

$nativePreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
wsl.exe -d $Distro -u root -e systemctl start docker 2>&1 | Out-Null

for ($i = 0; $i -lt 30; $i++) {
    wsl.exe -e docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 1
}

wsl.exe -e sh -c "cd '$wslProject' && docker compose up -d --build" 2>&1 | ForEach-Object { Write-Host $_ }
$composeCode = $LASTEXITCODE
$ErrorActionPreference = $nativePreference
if ($composeCode -ne 0) {
    throw "docker compose up failed."
}

for ($i = 0; $i -lt 60; $i++) {
    try {
        $health = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
        if ($health.ok) {
            Write-Host "ICPC Author Agent: http://127.0.0.1:$Port/"
            exit 0
        }
    } catch {
        # Container is still starting.
    }
    Start-Sleep -Seconds 1
}

throw "Container did not become healthy on port $Port."
