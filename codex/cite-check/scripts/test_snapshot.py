#!/usr/bin/env python3
"""Cite-check binds its extraction to a frozen draft, including missing-file checks."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent

class SnapshotTests(unittest.TestCase):
    def test_live_edits_do_not_change_review_and_missing_snapshot_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            draft = root / 'draft.md'
            original = '# Draft\n\nA proposition.[^1]\n\n[^1]: Original source.\n'
            draft.write_text(original)
            run = root / '.run'
            result = subprocess.run([sys.executable, str(HERE/'init_run.py'), str(draft), '--run-dir', str(run)],capture_output=True,text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((run/'run-manifest.json').read_text())
            snapshot = Path(manifest['draft_path'])
            self.assertEqual(manifest['original_draft_path'], str(draft))
            self.assertEqual(snapshot.parent, run)
            self.assertEqual(snapshot.read_text(), original)
            self.assertEqual(manifest['draft_sha256'], hashlib.sha256(snapshot.read_bytes()).hexdigest())
            draft.write_text('The live draft changed during the run.')
            result = subprocess.run([sys.executable,str(HERE/'validate_run.py'),str(run)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            snapshot.unlink()
            result = subprocess.run([sys.executable,str(HERE/'validate_run.py'),str(run)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('snapshot/source file is missing',result.stdout+result.stderr)

if __name__ == '__main__':
    unittest.main()
