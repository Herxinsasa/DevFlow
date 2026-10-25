from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


CHECKER = Path(__file__).resolve().parents[1] / ".claude" / "scripts" / "check-source-file.py"


class SourceFileCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        self.file = self.root / "source.cpp"

    def check_file(
        self, *, bom: str = "forbid", eol: str = "lf",
        baseline: Path | None = None, baseline_encoding: str | None = None,
    ):
        command = [
            sys.executable, str(CHECKER), "--root", str(self.root),
            "--file", "source.cpp", "--encoding", "utf-8",
            "--bom", bom, "--eol", eol,
        ]
        if baseline:
            command.extend(["--baseline", str(baseline)])
        if baseline_encoding:
            command.extend(["--baseline-encoding", baseline_encoding])
        return subprocess.run(command, capture_output=True, text=True)

    def test_valid_utf8_and_crlf_profile(self) -> None:
        self.file.write_bytes(b"int value = 1;\r\n")
        self.assertEqual(self.check_file(eol="crlf").returncode, 0)
        self.assertNotEqual(self.check_file(eol="lf").returncode, 0)

    def test_invalid_encoding_and_bom_mismatch_fail(self) -> None:
        self.file.write_bytes(b"\xff\n")
        self.assertIn("decode", self.check_file().stderr)
        self.file.write_bytes(b"\xef\xbb\xbfint value = 1;\n")
        self.assertNotEqual(self.check_file(bom="forbid").returncode, 0)
        self.assertEqual(self.check_file(bom="require").returncode, 0)

    def test_mixed_line_endings_and_missing_final_newline_fail(self) -> None:
        self.file.write_bytes(b"a\r\nb\n")
        self.assertNotEqual(self.check_file(eol="crlf").returncode, 0)
        self.file.write_bytes(b"a")
        self.assertIn("final newline", self.check_file().stderr)

    def test_preexisting_replacement_allowed_but_new_replacement_fails(self) -> None:
        baseline = Path(self.temp.name) / "before.cpp"
        baseline.write_bytes("bad=\ufffd\n".encode("utf-8"))
        self.file.write_bytes("bad=\ufffd\nok=1\n".encode("utf-8"))
        self.assertEqual(self.check_file(baseline=baseline).returncode, 0)
        self.file.write_bytes("bad=\ufffd\nnew=\ufffd\n".encode("utf-8"))
        self.assertIn("new U+FFFD", self.check_file(baseline=baseline).stderr)

    def test_gbk_baseline_can_be_checked_after_utf8_bom_conversion(self) -> None:
        baseline = Path(self.temp.name) / "before.cpp"
        baseline.write_bytes("// 中文\n".encode("gbk"))
        self.file.write_bytes(b"\xef\xbb\xbf" + "// 中文\n".encode("utf-8"))
        result = self.check_file(bom="require", baseline=baseline, baseline_encoding="gbk")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_file_outside_project_is_rejected(self) -> None:
        outside = Path(self.temp.name) / "outside.cpp"
        outside.write_text("x\n", encoding="utf-8")
        command = [
            sys.executable, str(CHECKER), "--root", str(self.root),
            "--file", str(outside), "--encoding", "utf-8",
            "--bom", "forbid", "--eol", "lf",
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertIn("outside project root", result.stderr)


if __name__ == "__main__":
    unittest.main()
