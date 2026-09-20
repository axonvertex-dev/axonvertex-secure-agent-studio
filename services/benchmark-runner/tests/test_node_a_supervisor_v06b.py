"""Offline 0.6B contract checks; no systemd, ports, credentials or models are accessed."""
from __future__ import annotations

import importlib.util
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[3] / "scripts/ops/node_a_supervisor_v06b.py"
spec = importlib.util.spec_from_file_location("node_a_supervisor_v06b", SOURCE)
assert spec and spec.loader
supervisor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervisor)


class SupervisionContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        for rel in (supervisor.EXPECTED_PY, supervisor.EXPECTED_NODE,
                    "services/benchmark-runner/src/benchmark_runner/continuous_remediation_worker_v05c.py"):
            p = self.root / rel
            p.parent.mkdir(exist_ok=True, parents=True)
            p.write_text("# fixture\n")
        (self.root / ".env").write_text("SECRET=not-a-real-secret\n")
        (self.root / ".env").chmod(0o600)

    def test_render_three_distinct_units_no_secrets(self):
        units = supervisor.render_units(self.root, Path("/usr/local/bin/node"),
                                        self.root / "services/benchmark-runner/.venv/bin/python")
        self.assertEqual(tuple(units), supervisor.SERVICES)
        self.assertIn("--env-file=.env", units[supervisor.GATEWAY])
        self.assertIn(" serve --poll-seconds 2", units[supervisor.WORKER])
        self.assertIn(" api\n", units[supervisor.API])
        self.assertIn("Requires=" + supervisor.GATEWAY, units[supervisor.WORKER])
        self.assertIn("WorkingDirectory=" + str(self.root), units[supervisor.WORKER])
        self.assertIn("NoNewPrivileges=true", units[supervisor.WORKER])
        self.assertIn("StandardOutput=null", units[supervisor.WORKER])
        self.assertNotIn("EnvironmentFile=", "".join(units.values()))
        self.assertNotIn("SECRET=", "".join(units.values()))
        self.assertNotIn(".env\n", "".join(units.values()))

    def test_venv_execstart_preserves_symlink_name(self):
        interpreter = self.root / "services/benchmark-runner/.venv/bin/python"
        interpreter.parent.mkdir(exist_ok=True, parents=True)
        interpreter.symlink_to("/usr/bin/python3")
        units = supervisor.render_units(self.root, Path("/usr/bin/node"), interpreter)
        self.assertIn("ExecStart=" + str(interpreter) + " -u ", units[supervisor.API])

    def test_check_repository_validates_existing_checkpoint_and_private_env(self):
        with patch.object(supervisor.os, "geteuid", return_value=1234), \
             patch.object(supervisor.os, "getuid", return_value=os.getuid()):
            paths = supervisor.check_repository(self.root)
        self.assertEqual(paths["root"], self.root)

    def test_reject_insecure_env(self):
        (self.root / ".env").chmod(0o644)
        with patch.object(supervisor.os, "geteuid", return_value=1234):
            with self.assertRaisesRegex(supervisor.SetupError, "chmod 600"):
                supervisor.check_repository(self.root)

    def test_reject_env_symlink(self):
        env = self.root / ".env"
        actual = self.root / "secret.config"
        env.rename(actual)
        env.symlink_to(actual)
        with patch.object(supervisor.os, "geteuid", return_value=1234):
            with self.assertRaisesRegex(supervisor.SetupError, "non-symlink"):
                supervisor.check_repository(self.root)

    def test_preflight_does_not_write_units(self):
        target = self.root / "user-units"
        units = supervisor.render_units(self.root, Path("/usr/bin/node"), Path("/usr/bin/python3"))
        result = supervisor.install(units, target, apply=False)
        self.assertEqual(len(result), 3)
        self.assertFalse(target.exists())

    def test_explicit_install_and_identical_reinstall(self):
        target = self.root / "user-units"
        units = supervisor.render_units(self.root, Path("/usr/bin/node"), Path("/usr/bin/python3"))
        supervisor.install(units, target, apply=True)
        for name in supervisor.SERVICES:
            self.assertEqual((target / name).read_text(), units[name])
            self.assertEqual(stat.S_IMODE((target / name).stat().st_mode), 0o600)
        supervisor.install(units, target, apply=True)

    def test_conflicting_unit_is_not_overwritten(self):
        target = self.root / "user-units"
        target.mkdir()
        (target / supervisor.GATEWAY).write_text("OLD UNIT\n")
        units = supervisor.render_units(self.root, Path("/usr/bin/node"), Path("/usr/bin/python3"))
        with self.assertRaisesRegex(supervisor.SetupError, "refusing overwrite"):
            supervisor.install(units, target, apply=True)
        self.assertEqual((target / supervisor.GATEWAY).read_text(), "OLD UNIT\n")
        self.assertFalse((target / supervisor.API).exists())

    def test_manual_gateway_refuses_supervised_start_before_any_unit_start(self):
        with patch.object(supervisor, "check_manager"), \
             patch.object(supervisor, "unit_directory", return_value=self.root), \
             patch.object(supervisor, "port_open", side_effect=lambda port: port == 17712), \
             patch.object(supervisor, "unit_active", return_value=False), \
             patch.object(supervisor, "systemctl") as sc:
            for name in supervisor.SERVICES:
                (self.root / name).write_text("UNIT")
            with self.assertRaisesRegex(supervisor.SetupError, "Manual/unmanaged process occupies 17712"):
                supervisor.start()
            sc.assert_not_called()

    def test_busy_gateway_refuses_stop(self):
        with patch.object(supervisor, "check_manager"), \
             patch.object(supervisor, "unit_active", return_value=True), \
             patch.object(supervisor, "health", return_value={"scheduler": {"active": 1, "queued": {"workflow": 0}}}), \
             patch.object(supervisor, "systemctl") as sc:
            with self.assertRaisesRegex(supervisor.SetupError, "active or queued"):
                supervisor.stop()
            sc.assert_not_called()

    def test_idle_gateway_stop_reverse_dependency_order(self):
        calls = []
        def fake_ctl(action, name):
            calls.append((action, name))
            return type("Result", (), {"returncode": 0})()
        with patch.object(supervisor, "check_manager"), \
             patch.object(supervisor, "unit_active", return_value=True), \
             patch.object(supervisor, "health", return_value={"scheduler": {"active": 0, "queued": {"workflow": 0,"chat": 0,"background": 0}}}), \
             patch.object(supervisor, "systemctl", side_effect=fake_ctl):
            supervisor.stop()
        self.assertEqual(calls, [("stop", name) for name in reversed(supervisor.SERVICES)])

    def test_unsafe_service_path_rejected(self):
        with self.assertRaises(supervisor.SetupError):
            supervisor.render_units(Path("/tmp/with space"), Path("/usr/bin/node"), Path("/usr/bin/python3"))


if __name__ == "__main__":
    unittest.main()
