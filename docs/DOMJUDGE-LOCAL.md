# Local DOMjudge import

This is a **local, single-author** DOMjudge stack for validating that an
exported ICPC package imports. It is not a public contest server.

## Pinned stack

| Service | Image | Port |
|---|---|---|
| domserver | `domjudge/domserver:9.0.1` | `127.0.0.1:18080` |
| database | `mariadb:11.4` | internal |

The file is `docker-compose.domjudge.yml`. It has its own Compose project
(`icpc-domjudge`) and volume (`icpc-domjudge_icpc-domjudge-db`), so it does not
disturb the author-agent, Judge0 or Isolate stacks.

## Start / stop

```powershell
.\scripts\domjudge-up.ps1
.\scripts\domjudge-down.ps1
```

`domjudge-up.ps1` prints the URL and the generated `admin` password. The
password is also stored in the domserver container at:

```text
/opt/domjudge/domserver/etc/initial_admin_password.secret
```

Open <http://127.0.0.1:18080/> and log in as `admin`.

To remove the DOMjudge database and start fresh:

```powershell
.\scripts\domjudge-down.ps1 -Reset
```

That deletes **DOMjudge** data only. It does not touch `workspaces/` or
`.author-agent/`.

## Judgehost and full judging

The default `domjudge-up.ps1` starts only the server. To judge submissions, start
the privileged judgehost too:

```powershell
.\scripts\domjudge-judgehost-up.ps1
# or
.\scripts\domjudge-up.ps1 -WithJudgehost
```

The script reads the judgehost credentials from the domserver
`restapi.secret`, starts `domjudge/judgehost:9.0.1` with `cgroup: host`, and
waits for `judgedaemon-0-0` to appear as an enabled judgehost.

On this Windows/WSL host the judgehost needs:

```yaml
privileged: true
cgroup: host
volumes:
  - /sys/fs/cgroup:/sys/fs/cgroup:rw
```

Without `cgroup: host` the judgehost fails with “missing cgroup hierarchy
prefix under /proc/self/cgroup”. The judgehost is privileged and must remain
loopback/local only.

`DOMJUDGE_CREATE_WRITABLE_TEMP_DIR` is intentionally not set: on this
DOMjudge 9.0.1/Judgehost image the optional `write_tmp` cleanup fails under the
chroot. Normal programs that do not need a writable temp directory judge
correctly. Add a writable temp directory only if you have a problem that needs
one and can validate the fix.

### Full judging test

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\qa\test_domjudge_judging.ps1
```

Actual result:

```json
{
  "stack": "domjudge/domserver:9.0.1 + judgehost:9.0.1 + mariadb:11.4",
  "contest": "demo",
  "problem": "sum-test-qa",
  "team": "exteam",
  "accepted": {"id": "13", "verdict": "AC", "maxRunTime": 0.002},
  "wrongAnswer": {"id": "14", "verdict": "WA", "maxRunTime": 0.001},
  "timeLimit": {"id": "15", "verdict": "TLE", "maxRunTime": 1.875}
}
```

`DOMJUDGE JUDGING TEST PASSED`

This proves the complete local loop:

1. export a verified package,
2. import it into DOMjudge,
3. compile and judge a submission on a real judgehost,
4. return AC for the accepted solution,
5. return WA for the wrong solution,
6. return TLE for the slow solution.

## Import test

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\qa\test_domjudge_import.ps1
```

The test:

1. Starts the stack if needed and waits for HTTP 200.
2. Reads the generated admin password.
3. Exports the verified `sum-test` workspace with `verify.export_package`.
4. Asserts the ZIP has no CRLF in `.ans` files.
5. Creates the `sum-test-qa` problem metadata in the `demo` contest if absent.
6. Imports the ZIP through the DOMjudge API.
7. Verifies the problem through the API and asserts at least 6 test cases and a
   statement.

Actual result:

```json
{
  "stack": "domjudge/domserver:9.0.1 + mariadb:11.4",
  "url": "http://127.0.0.1:18080",
  "contest": "demo",
  "problem": "sum-test-qa",
  "name": "Sum Test",
  "shortName": "D",
  "testDataCount": 6,
  "timeLimit": 1.0,
  "statement": "D.pdf",
  "httpStatus": 200,
  "warnings": ["No jury solutions added: must associate team with your user first."],
  "danger": [],
  "crlfAns": []
}
```

The only warning is that the admin user has no team, so jury solutions in the
ZIP were not auto-submitted. That is a warning, not an import error.

## Packaging fix

DOMjudge warned that `.ans` files contained Windows newlines. The exporter now
normalizes `.in`, `.ans`, `.out`, `.interaction` and `.py` payloads to LF inside
the ZIP and hashes the normalized bytes in `problem_statement/manifest.json`.
The import test fails if any `.ans` file still contains CRLF.

## What this proves

- The exported ICPC package is accepted by DOMjudge 9.0.1.
- The statement, test data and metadata are recognized.
- The export is free of CRLF test-data warnings.
- The local stack is reproducible and isolated.

## What this does not prove

- A real multi-team contest workflow, scoreboard behaviour or contest timing.
- DOMjudge under load, multiple parallel judgehosts or resource pressure.
- Importing every possible ICPC package variant; only the verified `sum-test`
  fixture is exercised here.
- A judgment of every language/toolchain; the test uses C++.
- A writable temporary directory for programs that need one (see the judgehost
  note above).

## API notes

The DOMjudge API is at `http://127.0.0.1:18080/api/v4`. The test uses HTTP Basic
auth with the initial admin password and the endpoints:

```text
GET  /api/v4/contests/demo/problems
POST /api/v4/contests/demo/problems/add-data
POST /api/v4/contests/demo/problems
GET  /api/v4/contests/demo/problems/sum-test-qa
```

The ZIP basename must match the problem ID (`sum-test-qa.zip`). The importer
compares the ZIP external ID with the target problem's external ID and rejects a
mismatch.
