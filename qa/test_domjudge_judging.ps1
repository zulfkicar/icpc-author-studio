$ErrorActionPreference = 'Stop'

# Full local DOMjudge round-trip:
# import the verified package, start a judgehost, submit accepted/wrong/slow
# programs, and assert AC/WA/TLE through the DOMjudge API.

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$base = 'http://127.0.0.1:18080'
$problemId = 'sum-test-qa'
$teamId = 'exteam'
$tempSlow = Join-Path $env:WINDIR 'Temp\domjudge-slow-src.cpp'

powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'test_domjudge_import.ps1')
if ($LASTEXITCODE -ne 0) { throw 'DOMjudge import prerequisite failed' }
powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo 'scripts\domjudge-judgehost-up.ps1')
if ($LASTEXITCODE -ne 0) { throw 'DOMjudge judgehost did not start' }

$password = ((wsl -e docker exec icpc-domjudge-server cat /opt/domjudge/domserver/etc/initial_admin_password.secret) | Out-String).Trim()
if (-not $password) { throw 'Could not read the DOMjudge admin password' }
$b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("admin:$password"))
$headers = @{ Authorization = "Basic $b64" }

function Submit-Program([string]$path, [string]$label) {
    if (-not (Test-Path $path)) { throw "Missing $label source: $path" }
    $body = curl.exe -sS -u "admin:$password" -F "problem=$problemId" -F "language=cpp" -F "team_id=$teamId" -F "code=@$path" "$base/api/v4/contests/demo/submissions"
    $submission = $body | ConvertFrom-Json
    if (-not $submission.id) { throw "$label submission failed: $body" }
    $sid = $submission.id
    for ($i = 0; $i -lt 90; $i++) {
        Start-Sleep -Seconds 1
        $judgements = Invoke-RestMethod -Uri "$base/api/v4/contests/demo/judgements?submission_id=$sid" -Headers $headers
        $items = if ($null -ne $judgements.value) { @($judgements.value) } else { @($judgements) }
        $row = $items | Where-Object { [string]$_.submission_id -eq [string]$sid } | Select-Object -First 1
        if ($row -and $row.judgement_type_id) {
            return [ordered]@{
                id = $sid
                verdict = $row.judgement_type_id
                maxRunTime = $row.max_run_time
            }
        }
    }
    throw "$label submission $sid did not finish judging"
}

$ac = Submit-Program (Join-Path $repo 'workspaces\sum-test\submissions\accepted\ref.cpp') 'accepted'
$wa = Submit-Program (Join-Path $repo 'workspaces\sum-test\submissions\wrong_answer\sub.cpp') 'wrong answer'

@'
#include <bits/stdc++.h>
using namespace std;
int main(){ volatile long long x=0; while(true){ x+=1; } }
'@ | Set-Content -Path $tempSlow -Encoding ascii
$tle = Submit-Program $tempSlow 'time limit'

if ($ac.verdict -ne 'AC') { throw "Accepted solution judged $($ac.verdict)" }
if ($wa.verdict -ne 'WA') { throw "Wrong solution judged $($wa.verdict)" }
if ($tle.verdict -ne 'TLE') { throw "Slow solution judged $($tle.verdict)" }

[ordered]@{
    stack = 'domjudge/domserver:9.0.1 + judgehost:9.0.1 + mariadb:11.4'
    contest = 'demo'
    problem = $problemId
    team = $teamId
    accepted = $ac
    wrongAnswer = $wa
    timeLimit = $tle
} | ConvertTo-Json -Compress
Write-Output 'DOMJUDGE JUDGING TEST PASSED'
exit 0
