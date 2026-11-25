"""Ensure the public helpers remain identical except the project-file constant."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
import run_tests

class ParityTests(unittest.TestCase):
    def test_22_detects_divergence_in_each_helper(self):
        root=Path(tempfile.mkdtemp(dir=Path(__file__).resolve().parent/'.codex-memo/amendment2-tests'))
        a=root/'claude-code/skills/cite-check/scripts';b=root/'codex/cite-check/scripts'
        a.mkdir(parents=True);b.mkdir(parents=True)
        for name in ('local_sources.py','source_options.py'):
            (a/name).write_text('PROJECT_FILE = "CLAUDE.md"\nVALUE = 1\n')
            (b/name).write_text('PROJECT_FILE = "AGENTS.md"\nVALUE = 1\n')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_tests.check_local_source_parity(root),[])
            for name in ('local_sources.py','source_options.py'):
                (b/name).write_text('PROJECT_FILE = "AGENTS.md"\nVALUE = 2\n')
                self.assertTrue(any(name in e for e in run_tests.check_local_source_parity(root)))
                (b/name).write_text('PROJECT_FILE = "AGENTS.md"\nVALUE = 1\n')
if __name__=='__main__':unittest.main()
