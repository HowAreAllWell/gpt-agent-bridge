"""Keep unchanged server line endings stable across the root-to-src migration."""
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = "src/gpt_agent_bridge/server.py"


def _numstat_total(output):
    return sum(int(value) for line in output.splitlines()
               for value in line.split("\t")[:2] if value.isdigit())


class NewlineStabilityTests(unittest.TestCase):
    def test_server_py_has_no_mass_line_ending_churn(self):
        # At migration HEAD the old path exists; later commits use the new path.
        original = subprocess.run(["git", "show", "HEAD:" + SERVER_PATH],
                                  cwd=REPO_ROOT, capture_output=True)
        if original.returncode:
            original = subprocess.run(["git", "show", "HEAD:server.py"],
                                      cwd=REPO_ROOT, capture_output=True, check=True)
        with tempfile.TemporaryDirectory() as folder:
            before = Path(folder) / "before.py"
            before.write_bytes(original.stdout)
            totals = []
            for options in ([], ["--ignore-space-at-eol"]):
                result = subprocess.run(["git", "diff", "--no-index", "--numstat",
                                         *options, str(before), str(REPO_ROOT / SERVER_PATH)],
                                        capture_output=True, text=True)
                self.assertIn(result.returncode, (0, 1), result.stderr)
                totals.append(_numstat_total(result.stdout))
        self.assertLessEqual(abs(totals[0] - totals[1]), 200,
                             "Unchanged server lines must retain their original terminators")
