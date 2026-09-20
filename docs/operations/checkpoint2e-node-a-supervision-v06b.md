# AXONVERTEX Secure Agent Studio — Checkpoint 2E-0.6B

## Boundary and known working checkpoint

Based on Node A commit `b3f4c29` (0.6A), Python tests 77/77, live API read
401 without a token and 200 with the independent API token. Golden live run
`v05c-full-auto-live-001` reached `VERIFIED_CANDIDATE_AWAITING_APPROVAL`.
This package is **process supervision only**: it does not alter the runtime,
queue, models, task state machine, policy, Python dependencies, SGLang, Docker,
Node B, or Node C. It adds one Python operator tool, 12 offline tests, and this
runbook. Existing manual services continue to run during inspection/installation.

## Observed Node A environment (2026-09-19)

- Ubuntu 22.04 user manager: `systemctl --user is-system-running` -> `running`.
- `loginctl show-user axonvertex -p Linger` -> `Linger=no`.
- Node `/home/axonvertex/.nvm/versions/node/v22.23.2/bin/node`.
- Node gateway loopback 17712, resident SGLang loopback/Tailscale 11433.
- API loopback 17713; Node A venv Python used for worker and API, not conda base Python.
- `.env` ignored, private, already contains an independent `AGENT_STUDIO_API_KEY`
  and existing model lane keys. No keys appear in unit files or command arguments.

## Service topology and operational constraints

`axonvertex-gemma-gateway.service` runs the existing gateway via
`node --env-file=.env --experimental-strip-types` and binds **127.0.0.1:17712**.
`axonvertex-agent-runtime-api.service` runs 0.6A `api` and binds
**127.0.0.1:17713**. `axonvertex-agent-runtime-worker.service` invokes the
existing 0.6A `serve --poll-seconds 2` and scans the existing durable queue
without exit-on-idle. The worker requires/starts after the gateway; API works
independently for read-only observation. No duplicate worker versions or new
inference schedulers are introduced.

Units run as the **existing axonvertex user** with `UMask=0077`,
`NoNewPrivileges=true`, `Restart=on-failure`, rate-limited restart, working
directory pinned to repo, and fixed node/venv Python absolute paths. No
`EnvironmentFile=`: node reads `.env` with its already tested `--env-file`
option; Python modules read the same ignored `.env` from the working directory.
Worker stdout is sent to `/dev/null` through `StandardOutput=null` because
legacy stages may print source analysis/model output. Operational facts remain
in the durable SQLite ledger. Stderr goes to the user journal: **do not paste
raw journal output without reviewing for private details**.

No claim of distributed mutual exclusion, complete end-to-end health monitoring,
production-grade service security, approval, patch application, or general
repository processing. The same fixture-limited CWE-89 workflow is supervised.
`/health` on 17713 tests the API only. systemd `active` for the worker means the
process exists, not that Node B, Node C, Docker or SGLang are healthy.

**Linger is deliberately NOT enabled.** With `Linger=no`, the user manager and
its services need an active user session and generally terminate on final
logout. The operator may decide separately whether boot/logout persistence is
appropriate. This package does not use `sudo`, enable boot startup, open a
public port, kill an existing PID, or override existing unit files.

## Install and offline acceptance — NO downtime

From Node B:

```bash
scp ~/Downloads/AXONVERTEX_Checkpoint_2E06B_Node_A_Supervision.zip \
  axonvertex@100.82.103.57:/tmp/
```

On Node A with nvm Node 22 available (`command -v node`):

```bash
cd /mnt/axonvertexstorage/development/projects/axonvertex-secure-agent-studio
unzip -n /tmp/AXONVERTEX_Checkpoint_2E06B_Node_A_Supervision.zip -d .
source services/benchmark-runner/.venv/bin/activate
OPS=scripts/ops/node_a_supervisor_v06b.py
python -m py_compile "$OPS"
python -m unittest discover -s services/benchmark-runner/tests \
  -p 'test_node_a_supervisor_v06b.py' -v
python -m unittest discover -s services/benchmark-runner/tests -p 'test_*.py'
python "$OPS" preflight
python "$OPS" install                  # DRY RUN, writes nothing
python "$OPS" install --apply          # writes only user units; DOES NOT start
python "$OPS" status                   # manual ports can still be healthy
```

Expect 12 focused tests and approximately **89** full tests if exactly 77
prior tests are still discoverable; check the actual `OK` result. The tool
refuses an .env file readable by group/others; correct permissions with
`chmod 600 .env` (do not print its contents). It also refuses missing pinned
node binary, missing venv Python, pre-existing conflicting unit files, root
install, wrong repository and unavailable user systemd. Service install is
idempotent if units match exactly. `install --apply` uses atomic unit writes and
`systemctl --user daemon-reload` but does NOT start or enable services.

If `install --apply` reports a conflicting existing user unit, stop and inspect
that unit locally. The tool intentionally has **no overwrite flag**.

## Golden-run preservation BEFORE switching processes

Do this when no worker is processing a run; leave the existing API and gateway
running if needed for inspection. SQLite online backup avoids copying active
WAL/SHM files as if they were complete databases. Preserve the full synthetic
fixture, receipts and auxiliary files, not just the verification JSON. This
creates an ignored local directory containing internal evidence: do not upload
or commit the archive. Example:

```bash
python - <<'PY'
import os, shutil, sqlite3
from datetime import datetime, timezone
from pathlib import Path
root = Path('benchmarks/results/checkpoint2e')
run = 'v05c-full-auto-live-001'
src = root / 'durable-live' / run
queue = root / 'continuous-worker-v05a' / 'jobs.sqlite3'
if not (src / 'runtime.sqlite3').is_file() or not queue.is_file():
    raise SystemExit('Known live DBs missing; snapshot aborted')
archive = root / 'archives' / ('supervision-v06b-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
archive.mkdir(parents=True, mode=0o700, exist_ok=False)
os.chmod(archive, 0o700)
for original, target in ((queue, archive/'jobs.sqlite3'),
                         (src/'runtime.sqlite3', archive/'runtime.sqlite3')):
    with sqlite3.connect(f'file:{original.resolve()}?mode=ro', uri=True) as db:
        with sqlite3.connect(str(target)) as dest:
            db.backup(dest)
    os.chmod(target, 0o600)
shutil.copytree(src, archive/'run-files', symlinks=True,
                ignore=shutil.ignore_patterns('runtime.sqlite3','runtime.sqlite3-wal',
                                              'runtime.sqlite3-shm'))
print('LOCAL_GOLDEN_SNAPSHOT_CREATED:', archive)
PY
```

The live SQLite stores are left untouched. Retain the original run in place.

## Manual -> supervised handover (planned short downtime)

1. Keep SGLang running on **11433**. Check gateway scheduler is idle:
   `curl --noproxy '*' -fsS http://127.0.0.1:17712/health | jq .`;
   `scheduler.active` must be `0`, every queued lane must be `0`.
2. In the two manual gateway and API terminals, use **Ctrl+C**, not `kill -9`.
   The worker from 0.5C `serve --stop-when-idle` should already have exited;
   do not leave any manual continuous `serve` instance running.
3. Confirm ports freed:

   ```bash
   ss -ltnp | grep -E ':(17712|17713)\b' || echo 'SERVICE_PORTS_FREE'
   ```

4. From the repo root with venv active:

   ```bash
   python scripts/ops/node_a_supervisor_v06b.py start
   python scripts/ops/node_a_supervisor_v06b.py status
   curl --noproxy '*' -fsS http://127.0.0.1:17712/health | jq .
   curl --noproxy '*' -fsS http://127.0.0.1:17713/health | jq .
   python services/benchmark-runner/src/benchmark_runner/agent_studio_runtime_v06a.py \
     inspect --run-id v05c-full-auto-live-001 \
     | jq '{job,bridge_status,artifacts}'
   ```

`start` rejects manual/unmanaged ports rather than trying to kill them. It
starts gateway then checks gateway HTTP health, starts API then checks API
HTTP health, then starts worker and confirms its systemd process is active.
The worker never performs an inference merely by starting when the queue has
no unfinished jobs. If an older job is pending, it **will** resume: inspect
queue before activating supervision.

## Restart / stop / enable policies

- `python "$OPS" status` — unit states and loopback checks, never model readiness proof.
- `python "$OPS" stop` — worker -> API -> gateway; refuses to stop an active
  or queued Gemma inference. Does not stop SGLang, Docker, Node B or Node C.
- `systemctl --user restart axonvertex-agent-runtime-api.service` is a narrow
  API recovery test. Re-query the golden run after restart.
- `systemctl --user is-active axonvertex-agent-runtime-worker.service` tests
  only process presence.
- `systemctl --user list-unit-files 'axonvertex-*.service'` inspects enablement.

**Only if the operator wants automatic start with their user manager:**

```bash
systemctl --user enable \
  axonvertex-gemma-gateway.service \
  axonvertex-agent-runtime-api.service \
  axonvertex-agent-runtime-worker.service
```

With the observed `Linger=no`, enabling does **not** make services survive final
logout or boot unattended. Boot/logout persistence requires a separate explicit
admin action (Ubuntu example: `sudo loginctl enable-linger axonvertex`), which
should be decided after reviewing whether unattended GPU use is desired. Do
not run this command as part of test or unit installation. To undo startup
registration:

```bash
systemctl --user disable \
  axonvertex-gemma-gateway.service \
  axonvertex-agent-runtime-api.service \
  axonvertex-agent-runtime-worker.service
```

For supervisor errors, inspect `systemctl --user is-active` or `systemctl --user
status --no-pager <unit>` **locally**, and redact any log details before
sharing. Do not edit/remove SQLite data, source fixtures, `.env` or inference
credentials as a troubleshooting shortcut.

## Acceptance and Git checkpoint

Before committing: all offline tests pass; preflight and dry-run install pass;
units are installed with no manual-service interruption; then at an agreed
handover, supervised gateway/API/worker are active, local health returns `ok`,
the old golden-run metadata is unchanged, and the API still returns 401 for
missing credentials and 200 with the independent credential. Worker must not
automatically approve or apply anything.

Stage only:

```bash
git add -- scripts/ops/node_a_supervisor_v06b.py \
  services/benchmark-runner/tests/test_node_a_supervisor_v06b.py \
  docs/operations/checkpoint2e-node-a-supervision-v06b.md
git diff --cached --check
git diff --cached --stat
```

Do not stage the existing untracked root README, `.pre-scout-recovery` backup,
`.env`, or `benchmarks/results` / golden snapshot. No tag or merge into frozen
`main` is implied by the feature-branch commit.
