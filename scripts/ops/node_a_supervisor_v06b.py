#!/usr/bin/env python3
"""2E-0.6B: opt-in systemd --user supervision of existing Node A processes.

Unit rendering/installation does NOT start services or stop manual processes.
No secret values are placed in units or printed. No root privileges used.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable

SERVICES = (
    "axonvertex-gemma-gateway.service",
    "axonvertex-agent-runtime-api.service",
    "axonvertex-agent-runtime-worker.service",
)
GATEWAY, API, WORKER = SERVICES
HEALTH = ((GATEWAY, 17712, "/health"), (API, 17713, "/health"))
EXPECTED_PY = "services/benchmark-runner/src/benchmark_runner/agent_studio_runtime_v06a.py"
EXPECTED_NODE = "packages/model-client/tools/start-gemma-gateway.mjs"


class SetupError(Exception):
    pass


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def check_syntax_path(p: Path) -> str:
    value = os.path.abspath(p)
    if any(c.isspace() or c in "%\\\"'" for c in value):
        raise SetupError("Unsafe service path; requires simple absolute paths without spaces/quotes/%")
    if not p.is_absolute():
        raise SetupError("Expected absolute service path")
    return value


def check_repository(root: Path, *, check_credentials: bool = True) -> dict[str, Path]:
    root = root.resolve()
    required = [root / EXPECTED_PY, root / EXPECTED_NODE,
                root / "services/benchmark-runner/src/benchmark_runner/continuous_remediation_worker_v05c.py"]
    if not all(path.is_file() for path in required):
        raise SetupError("Not the existing checkpoint 2E-0.6A repository or missing runtime components")
    env_file = root / ".env"
    if not env_file.is_file() or env_file.is_symlink():
        raise SetupError("Existing non-symlink ignored .env file required")
    mode = stat.S_IMODE(env_file.stat().st_mode)
    if check_credentials and (mode & 0o077):
        raise SetupError(".env has group/other permissions; chmod 600 .env before installing")
    if env_file.stat().st_uid != os.getuid():
        raise SetupError(".env owner does not match current user")
    for path in (root, *required, env_file):
        check_syntax_path(path)
    if os.geteuid() == 0:
        raise SetupError("Do not install root services; use axonvertex user")
    return {"root": root, "env": env_file,
            "python_app": root / EXPECTED_PY,
            "node_app": root / EXPECTED_NODE,
            "venv_python": root / "services/benchmark-runner/.venv/bin/python"}


def check_binaries(paths: dict[str, Path], *, node: str | None = None) -> tuple[Path, Path]:
    node_path = Path(node or shutil.which("node") or "/unavailable/node").resolve()
    py_path = paths["venv_python"]
    if not node_path.is_file() or not os.access(node_path, os.X_OK):
        raise SetupError("Node.js executable unavailable; activate nvm Node 22 then retry")
    if not py_path.is_file() or not os.access(py_path, os.X_OK):
        raise SetupError("Existing benchmark-runner .venv/bin/python unavailable")
    check_syntax_path(node_path)
    check_syntax_path(py_path)
    version = subprocess.run([str(node_path), "--version"], capture_output=True,
                             text=True, timeout=10, check=False)
    if version.returncode != 0 or not version.stdout.startswith("v22."):
        raise SetupError("Existing gateway requires Node.js 22")
    return node_path, py_path


def render_units(root: Path, node: Path, py: Path) -> dict[str, str]:
    root, node, py = (check_syntax_path(p) for p in (root, node, py))
    common = (
        f"WorkingDirectory={root}\n"
        "UMask=0077\n"
        "NoNewPrivileges=true\n"
        "StandardOutput=null\n"
        "StandardError=journal\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "TimeoutStopSec=30\n"
    )
    gateway = ("[Unit]\nDescription=AXONVERTEX Resident Gemma Gateway (Node A, loopback)\n"
               "StartLimitIntervalSec=120\nStartLimitBurst=5\n\n[Service]\nType=exec\n"
               + common + f"ExecStart={node} --env-file=.env --experimental-strip-types {root}/{EXPECTED_NODE}\n"
               "\n[Install]\nWantedBy=default.target\n")
    api = ("[Unit]\nDescription=AXONVERTEX Agent Studio local runtime API (Node A)\n"
           "StartLimitIntervalSec=120\nStartLimitBurst=5\n\n[Service]\nType=exec\n"
           + common + f"ExecStart={py} -u {root}/{EXPECTED_PY} api\n"
           "\n[Install]\nWantedBy=default.target\n")
    worker = ("[Unit]\nDescription=AXONVERTEX Agent Studio continuous fixture worker (Node A)\n"
              f"Requires={GATEWAY}\nAfter={GATEWAY}\n"
              "StartLimitIntervalSec=120\nStartLimitBurst=5\n\n[Service]\nType=exec\n"
              + common + f"ExecStart={py} -u {root}/{EXPECTED_PY} serve --poll-seconds 2\n"
              "\n[Install]\nWantedBy=default.target\n")
    return dict(zip(SERVICES, (gateway, api, worker)))


def unit_directory() -> Path:
    override = os.environ.get("XDG_CONFIG_HOME")
    return (Path(override) if override else Path.home() / ".config") / "systemd/user"


def install(units: dict[str, str], target: Path, *, apply: bool = False) -> list[str]:
    conflicts = [name for name, data in units.items()
                 if (target / name).exists() and (target / name).read_text() != data]
    if conflicts:
        raise SetupError("Existing different units; refusing overwrite: " + ", ".join(conflicts))
    if not apply:
        return ["DRY_RUN: would create unit " + name for name in units]
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name, data in units.items():
        path = target / name
        if path.is_symlink():
            raise SetupError("Refusing symlink unit " + name)
        # Identical files can safely be left untouched. Atomic replace prevents partial units.
        if path.is_file() and path.read_text() == data:
            continue
        temp = target / (name + ".new")
        try:
            with temp.open("x", encoding="utf-8") as out:
                out.write(data)
            os.chmod(temp, 0o600)
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()
    return ["INSTALLED: " + name for name in units]


def systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True,
                              text=True, timeout=35, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise SetupError("User systemd manager command unavailable: " + type(exc).__name__) from exc


def check_manager() -> None:
    result = systemctl("is-system-running")
    if result.returncode not in (0, 1) or result.stdout.strip() not in ("running", "degraded", "starting"):
        raise SetupError("User systemd manager unavailable; log in as axonvertex with a user session")


def unit_active(name: str) -> bool:
    result = systemctl("is-active", name)
    return result.stdout.strip() == "active"


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def health(port: int, route: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{route}", timeout=3) as r:
        data = json.load(r)
        if r.status != 200 or data.get("status") != "ok":
            raise SetupError(f"Health contract failed for localhost:{port}")
        return data


def wait_health(port: int, route: str, *, seconds: float = 20) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            health(port, route)
            return
        except (OSError, ValueError, SetupError):
            time.sleep(.5)
    raise SetupError(f"Service did not become healthy on localhost:{port}")


def status() -> None:
    for name in SERVICES:
        result = systemctl("is-active", name)
        print(f"{name}: {result.stdout.strip() or 'unknown'}")
    for _, port, route in HEALTH:
        try:
            data = health(port, route)
            print(f"localhost:{port}: {data['status']} (API health does not imply worker/model health)")
        except (OSError, ValueError, SetupError):
            print(f"localhost:{port}: unavailable")


def start() -> None:
    check_manager()
    if not all((unit_directory() / name).is_file() for name in SERVICES):
        raise SetupError("Install all three units first; no partial service startup")
    for name, port, _ in HEALTH:
        if port_open(port) and not unit_active(name):
            raise SetupError(f"Manual/unmanaged process occupies {port}; Ctrl+C its terminal; NEVER kill by PID")
    for name, port, route in HEALTH:
        if not unit_active(name):
            r = systemctl("start", name)
            if r.returncode:
                raise SetupError(f"Failed to start {name}; inspect systemctl --user status {name}")
        wait_health(port, route)
        print(f"ACTIVE {name}: localhost:{port} healthy")
    if not unit_active(WORKER):
        r = systemctl("start", WORKER)
        if r.returncode:
            raise SetupError("Worker start failed; inspect systemctl --user status " + WORKER)
    if not unit_active(WORKER):
        raise SetupError("Worker did not remain active")
    print("ACTIVE " + WORKER + ": process active (NOT end-to-end worker readiness proof)")


def stop() -> None:
    check_manager()
    if unit_active(GATEWAY):
        try:
            data = health(17712, "/health")
        except (OSError, ValueError, SetupError) as exc:
            raise SetupError("Cannot establish gateway idleness; stop manually after confirming clients idle") from exc
        scheduler = data.get("scheduler", {})
        queued = scheduler.get("queued", {})
        if scheduler.get("active") != 0 or not isinstance(queued, dict) or any(v != 0 for v in queued.values()):
            raise SetupError("Gateway has active or queued inference; refusing stop")
    for name in reversed(SERVICES):
        if unit_active(name):
            r = systemctl("stop", name)
            if r.returncode:
                raise SetupError(f"Could not stop {name}")
        print("STOPPED_OR_INACTIVE " + name)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("preflight", "install", "start", "stop", "status"))
    p.add_argument("--apply", action="store_true", help="for install: write user units; never start/enable")
    args = p.parse_args(argv)
    try:
        if args.apply and args.command != "install":
            raise SetupError("--apply only valid with install")
        if args.command in ("preflight", "install"):
            paths = check_repository(repo_root())
            node, py = check_binaries(paths)
            check_manager()
            print("REPO_OK / .env owner+permissions OK / NODE_22_OK / VENV_PYTHON_OK / USER_SYSTEMD_OK")
            print("Node:", node, "Python:", py)
            print("Linger is NOT enabled by this tool; the operator may choose loginctl separately")
            if args.command == "install":
                for result in install(render_units(paths["root"], node, py),
                                      unit_directory(), apply=args.apply):
                    print(result)
                if args.apply:
                    r = systemctl("daemon-reload")
                    if r.returncode:
                        raise SetupError("Unit files installed but systemd user daemon-reload failed")
                    print("USER_DAEMON_RELOADED: services still not started or enabled")
        elif args.apply:
            raise SetupError("--apply only valid with install")
        elif args.command == "start":
            start()
        elif args.command == "stop":
            stop()
        else:
            check_manager()
            status()
        return 0
    except SetupError as exc:
        print("SUPERVISOR_ERROR: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
