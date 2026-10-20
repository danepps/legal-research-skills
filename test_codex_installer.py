#!/usr/bin/env python3
"""Exercise Codex installer updates without network or user configuration writes."""

from pathlib import Path
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent


class CodexInstallerTests(unittest.TestCase):
    def exercise(self, native=True, refresh_status=0):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            binaries = directory / "bin"
            binaries.mkdir()
            log = directory / "calls.txt"
            codex = binaries / "codex"
            codex.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n" "$*" >> "$CODEX_INSTALLER_TEST_LOG"\n'
                'case "$*" in\n'
                f'  "plugin --help") exit {0 if native else 1} ;;\n'
                '  "plugin marketplace list") echo danepps-legal-research-codex ;;\n'
                f'  "plugin marketplace upgrade danepps-legal-research-codex") exit {refresh_status} ;;\n'
                'esac\n'
            )
            codex.chmod(0o755)
            checkout = directory / "checkout"
            (checkout / ".git").mkdir(parents=True)
            git = binaries / "git"
            git.write_text("#!/bin/sh\nexit 1\n")
            git.chmod(0o755)
            result = subprocess.run(
                ["/bin/sh", str(ROOT / "install.sh"), "--codex"],
                text=True, capture_output=True,
                env={**os.environ, "PATH": str(binaries) + os.pathsep + os.defpath,
                     "CODEX_INSTALLER_TEST_LOG": str(log), "LRS_HOME": str(checkout)},
            )
            return result, log.read_text()

    def test_failed_marketplace_refresh_does_not_install_stale_cache(self):
        result, calls = self.exercise(refresh_status=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refresh failed", result.stderr)
        self.assertNotIn("plugin add", calls)
        self.assertNotIn("Done.", result.stdout)

    def test_successful_refresh_installs_current_plugin(self):
        result, calls = self.exercise()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("plugin add legal-research@danepps-legal-research-codex", calls)
        self.assertIn("Done.", result.stdout)

    def test_failed_manual_checkout_update_stops_before_linking(self):
        result, _ = self.exercise(native=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not be updated", result.stderr)
        self.assertNotIn("Codex skills ->", result.stdout)
        self.assertNotIn("Done.", result.stdout)


if __name__ == "__main__":
    unittest.main()
