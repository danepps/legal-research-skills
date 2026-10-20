#!/usr/bin/env python3
"""Exercise updater side effects using isolated files and fake OS/CLI boundaries."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location("auto_update", Path(__file__).with_name("auto_update.py"))
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lrs updater '")
        self.addCleanup(self.temporary.cleanup)
        self.user_root = Path(self.temporary.name)
        self.root = self.user_root / "codex data" / "legal-research-updater"
        self.root.parent.mkdir()
        for path in (self.user_root / "bin/codex", self.user_root / "codex"):
            path.parent.mkdir(exist_ok=True)
            path.write_text("fake executable")
        self.calls = []
        self.scheduled = False
        self.failure = None
        self.plugin = {"pluginId": updater.PLUGIN, "installed": True, "enabled": True,
                       "version": "1.2.0", "marketplaceSource": {
                           "sourceType": "git", "source": updater.REPOSITORY}}
        self.addCleanup(patch.stopall)
        patch.object(updater.Path, "home", return_value=self.user_root).start()
        patch.dict(os.environ, {"CODEX_HOME": str(self.root.parent),
                                "XDG_CONFIG_HOME": str(self.user_root / "config")}).start()
        patch.object(updater.platform, "system", return_value="Darwin").start()
        patch.object(updater, "execute", side_effect=self.execute).start()

    def execute(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if self.failure and self.failure in args:
            if kwargs.get("check", True):
                raise updater.UpdateError("simulated failure: " + self.failure)
            return subprocess.CompletedProcess(args, 1, "", "simulated failure")
        code, output, error = 0, "", ""
        if Path(args[0]).name == "codex":
            if args[1:3] == ["plugin", "list"]:
                output = json.dumps({"installed": [self.plugin] if self.plugin else []})
            elif args[1:3] == ["plugin", "add"]:
                self.plugin["version"] = "1.3.0"
        elif args[0] == "whoami":
            output = "EXAMPLE\\researcher\n"
        elif args[0] == "launchctl":
            if "print" in args:
                code = 0 if self.scheduled else 1
                error = "" if self.scheduled else 'Could not find service "updater"'
            if "bootstrap" in args:
                self.scheduled = True
            if "bootout" in args:
                self.scheduled = False
        elif args[0] == "systemctl":
            if "show" in args:
                output = "loaded" if self.scheduled else "not-found"
            if any(s in args for s in ("is-enabled", "is-active")):
                code = 0 if self.scheduled else 1
                output = ("enabled" if "is-enabled" in args else "active") if self.scheduled else "inactive"
            if "enable" in args:
                self.scheduled = True
            if "disable" in args:
                self.scheduled = False
        elif args[0] == "schtasks.exe":
            if "/Query" in args:
                code = 0 if self.scheduled else 1
                output = '<Task><Settings><Enabled>true</Enabled></Settings></Task>'
                if "/FO" in args:
                    code = 0
                    name = getattr(self, "windows_job_name", "")
                    output = f'"\\{name}","N/A","Ready"\n' if self.scheduled else ""
            if "/Create" in args:
                self.scheduled = True
                self.windows_job_name = args[args.index("/TN") + 1]
            if "/Delete" in args:
                self.scheduled = False
        return subprocess.CompletedProcess(args, code, output, error)

    def enable(self):
        return updater.enable(self.root, str(self.user_root / "bin" / "codex"))

    def mutations(self):
        return [args for args, _ in self.calls
                if "upgrade" in args or (len(args) > 2 and args[1:3] == ["plugin", "add"])]

    def test_status_and_disabled_run_create_nothing(self):
        self.assertFalse(updater.status(self.root)["enabled"])
        self.assertEqual(updater.run_update(self.root), {"status": "disabled"})
        self.assertFalse(self.root.exists())
        self.assertEqual(self.calls, [])

    def test_enable_daily_update_readback_throttle_disable(self):
        self.assertTrue(self.enable()["enabled"])
        config = updater.load_config(self.root)
        self.assertTrue(updater.status(self.root)["schedule_registered"])
        plist = plistlib.loads(next(iter(updater.scheduler_files(config).values())))
        self.assertEqual(plist["ProgramArguments"][1], str(self.root / "auto_update.py"))
        self.assertEqual(plist["ProgramArguments"][-1], "run")
        self.assertEqual((self.root / "auto_update.py").read_bytes(), Path(updater.__file__).read_bytes())
        result = updater.run_update(self.root)
        self.assertEqual(result["status"], "updated")
        self.assertEqual(result["version"], "1.3.0")
        self.assertEqual(len(self.mutations()), 2)
        self.assertEqual(updater.run_update(self.root)["status"], "not_due")
        self.assertEqual(len(self.mutations()), 2)
        self.assertEqual(updater.run_update(self.root, force=True)["status"], "up_to_date")
        self.assertEqual(len(self.mutations()), 4)
        for args, kwargs in self.calls:
            if Path(args[0]).name == "codex":
                self.assertEqual(kwargs["env"]["CODEX_HOME"], str(self.root.parent))
                self.assertEqual(kwargs["cwd"], str(self.root))
        self.assertFalse(updater.disable(self.root)["enabled"])
        self.assertFalse(self.scheduled)
        self.assertEqual(updater.run_update(self.root, force=True)["status"], "disabled")
        self.assertTrue((self.root / "auto_update.py").exists())
        self.assertFalse(any(Path(path).exists() for path in config["files"]))
        self.assertFalse(updater.disable(self.root)["enabled"])

    def test_each_supported_scheduler_can_enable_and_disable(self):
        for system in ("Darwin", "Linux", "Windows"):
            with self.subTest(system=system), patch.object(updater.platform, "system", return_value=system):
                root = self.root.parent / system
                updater.enable(root, str(self.user_root / "codex"))
                self.assertTrue(updater.status(root)["schedule_registered"])
                config = updater.load_config(root)
                if system == "Linux":
                    unit = next(data.decode() for path, data in updater.scheduler_files(config).items() if path.suffix == ".service")
                    self.assertIn('"' + str(root / "auto_update.py") + '"', unit)
                if system == "Windows":
                    tree = ET.fromstring((root / "task.xml").read_bytes())
                    self.assertEqual(tree.findtext("{*}Principals/{*}Principal/{*}LogonType"), "InteractiveToken")
                    self.assertEqual(tree.findtext("{*}Actions/{*}Exec/{*}Command"), sys.executable)
                updater.disable(root)
                self.assertFalse(self.scheduled)

    def test_removed_or_disabled_plugin_is_not_reinstalled(self):
        self.enable()
        for value in (None, {**self.plugin, "enabled": False}):
            self.plugin = value
            self.assertEqual(updater.run_update(self.root, force=True)["status"], "skipped")
            self.assertEqual(self.mutations(), [])

    def test_unsupported_sources_fail_before_mutation(self):
        for source in ({"sourceType": "local", "source": "/tmp/checkout"},
                       {"sourceType": "git", "source": "https://github.com/example/fork.git"},
                       {"sourceType": "git", "source": updater.REPOSITORY, "ref": "v1.2.0"}):
            with self.subTest(source=source):
                self.plugin["marketplaceSource"] = source
                with self.assertRaises(updater.UpdateError):
                    self.enable()
                self.assertFalse(self.scheduled)
                self.assertEqual(self.mutations(), [])

    def test_source_change_after_setup_stops_update(self):
        self.enable()
        self.plugin["marketplaceSource"]["source"] = "https://github.com/example/fork.git"
        with self.assertRaises(updater.UpdateError):
            updater.run_update(self.root)
        self.assertEqual(self.mutations(), [])

    def test_refresh_failure_stops_before_install_and_records_error(self):
        self.enable()
        self.failure = "upgrade"
        with self.assertRaises(updater.UpdateError):
            updater.run_update(self.root)
        self.assertEqual(len(self.mutations()), 1)
        result = updater.status(self.root)["last_run"]
        self.assertEqual(result["status"], "failed")
        self.assertIn("simulated failure", result["error"])
        self.assertEqual(updater.run_update(self.root)["status"], "not_due")

    def test_install_failure_is_not_success(self):
        self.enable()
        self.failure = "add"
        with self.assertRaises(updater.UpdateError):
            updater.run_update(self.root)
        self.assertEqual(updater.status(self.root)["last_run"]["status"], "failed")

    def test_scheduler_failure_keeps_configuration_disabled(self):
        self.failure = "bootstrap"
        with self.assertRaises(updater.UpdateError):
            self.enable()
        self.assertFalse(updater.load_config(self.root)["enabled"])
        self.assertEqual(updater.run_update(self.root)["status"], "disabled")

    def test_disable_failure_still_blocks_future_updates(self):
        self.enable()
        self.failure = "bootout"
        with self.assertRaises(updater.UpdateError):
            updater.disable(self.root)
        self.assertFalse(updater.load_config(self.root)["enabled"])
        self.assertEqual(updater.run_update(self.root)["status"], "disabled")

    def test_inspection_failure_is_unknown_and_does_not_claim_removal(self):
        self.enable()
        self.failure = "print"
        status = updater.status(self.root)
        self.assertIsNone(status["schedule_registered"])
        self.assertIn("scheduler_error", status)
        with self.assertRaises(updater.UpdateError):
            updater.disable(self.root)
        self.assertTrue(self.scheduled)
        self.assertFalse(updater.load_config(self.root)["enabled"])
        self.assertTrue(all(Path(path).exists() for path in updater.load_config(self.root)["files"]))

    def test_modified_scheduler_files_are_not_overwritten_or_deleted(self):
        self.enable()
        path = Path(next(iter(updater.load_config(self.root)["files"])))
        path.write_text("user customizations")
        with self.assertRaises(updater.UpdateError):
            self.enable()
        with self.assertRaises(updater.UpdateError):
            updater.disable(self.root)
        self.assertEqual(path.read_text(), "user customizations")
        self.assertFalse(updater.load_config(self.root)["enabled"])

    def test_status_reports_missing_helper_or_scheduler_files(self):
        self.enable()
        runner = self.root / "auto_update.py"
        runner.unlink()
        self.assertIn("missing", updater.status(self.root)["scheduler_error"])
        self.enable()
        path = Path(next(iter(updater.load_config(self.root)["files"])))
        path.unlink()
        self.assertIn("missing", updater.status(self.root)["scheduler_error"])

    def test_concurrent_operations_do_not_overlap(self):
        self.enable()
        with updater.lock(self.root):
            with self.assertRaises(updater.UpdateError):
                updater.run_update(self.root)
            with self.assertRaises(updater.UpdateError):
                updater.disable(self.root)
        self.assertEqual(self.mutations(), [])

    def test_reenable_is_idempotent(self):
        self.enable()
        original = updater.load_config(self.root)
        self.enable()
        self.assertEqual(updater.load_config(self.root), original)
        self.assertTrue(self.scheduled)

    def test_invalid_listing_json_is_not_treated_as_absence(self):
        self.enable()
        with patch.object(updater, "codex", return_value={}):
            with self.assertRaises(updater.UpdateError):
                updater.run_update(self.root)
        self.assertEqual(self.mutations(), [])

    def test_failed_installed_version_readback_is_not_success(self):
        self.enable()
        plugin = copy.deepcopy(self.plugin)
        with patch.object(updater, "installed_plugin", side_effect=[plugin, plugin, None]):
            with self.assertRaises(updater.UpdateError):
                updater.run_update(self.root)
        self.assertEqual(updater.status(self.root)["last_run"]["status"], "failed")

    def test_systemd_quotes_specifiers_and_shell_characters(self):
        self.assertEqual(updater.unit_quote('/a %h/$HOME/"x"'), '"/a %%h/$$HOME/\\"x\\""')


if __name__ == "__main__":
    unittest.main()
