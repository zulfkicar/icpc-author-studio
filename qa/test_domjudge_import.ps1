$ErrorActionPreference = 'Stop'

# Local DOMjudge import acceptance test.
# Starts the pinned DOMjudge stack if needed, exports a verified workspace,
# creates the problem metadata if absent, imports the ZIP, and verifies the
# resulting problem through the DOMjudge API.

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($repo -notmatch '^([A-Za-z]):\\(.*)$') { throw 'The repository must be on a mounted Windows drive.' }
$wslRepo = "/mnt/$($Matches[1].ToLower())/$($Matches[2] -replace '\\', '/')"
$compose = 'docker-compose.domjudge.yml'
$base = 'http://127.0.0.1:18080'
$problemId = 'sum-test-qa'
$contestId = 'demo'
$tempZip = Join-Path $env:WINDIR 'Temp\sum-test-qa.zip'
$tempYaml = Join-Path $env:WINDIR 'Temp\domjudge-problems.yaml'
$tempBody = Join-Path $env:WINDIR 'Temp\domjudge-import-response.json'

function Wait-Domjudge {
    for ($i = 0; $i -lt 90; $i++) {
        try {
            $response = Invoke-WebRequest "$base/" -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Seconds 2
    }
    throw 'DOMjudge did not become reachable on 127.0.0.1:18080'
}

Write-Host 'Starting the local DOMjudge stack...'
wsl -e sh -c "cd '$wslRepo' && docker compose -f $compose up -d" | Out-Host
Wait-Domjudge

$password = ((wsl -e docker exec icpc-domjudge-server cat /opt/domjudge/domserver/etc/initial_admin_password.secret) | Out-String).Trim()
if (-not $password) { throw 'Could not read the DOMjudge admin password' }
$b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("admin:$password"))
$headers = @{ Authorization = "Basic $b64" }

$existing = @(Invoke-RestMethod -Uri "$base/api/v4/contests/$contestId/problems" -Headers $headers)
$target = $existing | Where-Object { $_.id -eq $problemId } | Select-Object -First 1
if (-not $target) {
    $usedLabels = @($existing | ForEach-Object { $_.label })
    $freeLabel = [char[]](65..90) | ForEach-Object { [string]$_ } | Where-Object { $usedLabels -notcontains $_ } | Select-Object -First 1
    if (-not $freeLabel) { throw 'No free problem label in the demo contest' }
    $yaml = "- id: $problemId`n  label: $freeLabel`n  name: Sum Test QA`n  color: '#3d55d6'`n  rgb: '#3D55D6'`n"
    [IO.File]::WriteAllText($tempYaml, $yaml, [Text.UTF8Encoding]::new($false))
    $addStatus = curl.exe -sS -o $tempBody -w '%{http_code}' -u "admin:$password" -F "data=@$tempYaml" "$base/api/v4/contests/$contestId/problems/add-data"
    if ($LASTEXITCODE -ne 0 -or $addStatus -ne '200') {
        throw ("Problem metadata failed (HTTP $addStatus): " + (Get-Content $tempBody -Raw -ErrorAction SilentlyContinue))
    }
}

Write-Host 'Exporting the verified sum-test package...'
$exportJson = wsl -e docker exec icpc-author-agent python -c "import verify,json; print(json.dumps(verify.export_package('sum-test')))"
$export = $exportJson | ConvertFrom-Json
if (-not $export.absolute) { throw "Export failed: $exportJson" }
$sourceZip = Join-Path $repo 'workspaces\sum-test\.agent\export\sum-test-domjudge.zip'
if (-not (Test-Path $sourceZip)) { throw "Export ZIP is missing: $sourceZip" }
Copy-Item -LiteralPath $sourceZip -Destination $tempZip -Force

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($tempZip)
$crlfAnswers = @()
try {
    foreach ($entry in $zip.Entries) {
        if (-not $entry.FullName.EndsWith('.ans')) { continue }
        $reader = New-Object IO.StreamReader($entry.Open())
        try { $text = $reader.ReadToEnd() } finally { $reader.Dispose() }
        if ($text.Contains("`r`n")) { $crlfAnswers += $entry.FullName }
    }
} finally { $zip.Dispose() }
if ($crlfAnswers.Count -gt 0) { throw ("Export still contains CRLF .ans files: " + ($crlfAnswers -join ', ')) }

Write-Host "Importing $problemId into contest $contestId..."
$importStatus = curl.exe -sS -o $tempBody -w '%{http_code}' -u "admin:$password" -F "problem=$problemId" -F "zip=@$tempZip" "$base/api/v4/contests/$contestId/problems"
$bodyText = Get-Content $tempBody -Raw
if ($LASTEXITCODE -ne 0 -or $importStatus -ne '200') {
    throw ("DOMjudge import failed (HTTP $importStatus): $bodyText")
}
$import = $bodyText | ConvertFrom-Json
if ($import.code) { throw "DOMjudge import error: $bodyText" }
if ($import.messages.danger.Count -gt 0) { throw "DOMjudge import danger: $($import.messages.danger -join '; ')" }

$problem = Invoke-RestMethod -Uri "$base/api/v4/contests/$contestId/problems/$problemId" -Headers $headers
if ($problem.id -ne $problemId) { throw "Imported problem id is $($problem.id)" }
if ([int]$problem.test_data_count -lt 6) { throw "Expected at least 6 test cases, got $($problem.test_data_count)" }
if (-not $problem.statement -or $problem.statement.Count -lt 1) { throw 'Imported problem has no statement' }

$summary = [ordered]@{
    stack = 'domjudge/domserver:9.0.1 + mariadb:11.4'
    url = $base
    contest = $contestId
    problem = $problem.id
    name = $problem.name
    shortName = $problem.short_name
    testDataCount = $problem.test_data_count
    timeLimit = $problem.time_limit
    statement = $problem.statement[0].filename
    httpStatus = [int]$importStatus
    warnings = @($import.messages.warning)
    danger = @($import.messages.danger)
    crlfAns = @($crlfAnswers)
}
Write-Output ($summary | ConvertTo-Json -Compress)
Write-Output 'DOMJUDGE IMPORT TEST PASSED'
exit 0
