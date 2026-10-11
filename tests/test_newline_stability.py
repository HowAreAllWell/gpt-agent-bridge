import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = "server.py"


def _numstat_total(output: str) -> int:
    total = 0
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        for field in parts[:2]:
            if field.isdigit():
                total += int(field)
    return total


class NewlineStabilityTests(unittest.TestCase):
    """Prevent large transient server.py diffs caused by line-ending rewrites.

    server.py intentionally keeps a mixed CRLF/LF history.  A full-file
    rewrite that normalizes every line to one terminator can make git report
    thousands of changed lines even when the semantic diff is small.  This
    test compares the normal diff against git's whitespace-at-EOL-ignoring
    diff and fails when line-ending-only churn dominates.
    """

    def test_server_py_has_no_mass_line_ending_churn(self):
        raw = subprocess.run(
            ["git", "diff", "--numstat", "--", SERVER_PATH],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        semantic = subprocess.run(
            ["git", "diff", "--ignore-space-at-eol", "--numstat", "--", SERVER_PATH],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

        raw_total = _numstat_total(raw)
        semantic_total = _numstat_total(semantic)
        churn_only = abs(raw_total - semantic_total)
        self.assertLessEqual(
            churn_only,
            200,
            msg=(
                "server.py appears to contain mass line-ending-only churn: "
                f"raw diff has {raw_total} changed lines while semantic "
                f"diff (ignoring CR at EOL) has {semantic_total}. Keep edits "
                "to unchanged server.py lines on their existing CRLF/LF "
                "terminators instead of normalizing the whole file."
            ),
        )