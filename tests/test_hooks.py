from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVIEW_HOOK = ROOT / ".claude" / "hooks" / "review-check.ps1"
BUILD_TOOL = ROOT / ".claude" / "hooks" / "build-credential.py"
BUILD_HOOK = ROOT / ".claude" / "hooks" / "pre-commit-check.ps1"


class DevFlowHookScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        if shutil.which("git") is None or shutil.which("powershell.exe") is None:
            self.skipTest("Git and Windows PowerShell are required")
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.git("init")
        self.git("config", "user.name", "DevFlow Test")
        self.git("config", "user.email", "devflow@example.invalid")

        self.install_project(self.repo)
        self.install_project(self.repo / "tool")
        self.write(self.repo / "root.py", "ROOT = 1\n")
        self.write(self.repo / "tool" / "a.py", "A = 1\n")
        self.write(self.repo / "tool" / "b.py", "B = 1\n")
        self.git("add", ".")
        self.git("commit", "-m", "initial")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            capture_output=True,
            text=True,
            check=check,
        )

    @staticmethod
    def write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def install_project(self, project: Path) -> None:
        hooks = project / ".claude" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REVIEW_HOOK, hooks / "review-check.ps1")
        shutil.copy2(BUILD_TOOL, hooks / "build-credential.py")
        shutil.copy2(BUILD_HOOK, hooks / "pre-commit-check.ps1")
        self.write(project / ".claude" / "devflow-version.json", '{"version":"test"}\n')

    def snapshot(self, project: Path) -> dict[str, object]:
        result = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(project / ".claude" / "hooks" / "review-check.ps1"),
                "-Snapshot",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    def write_review(self, project: Path, snapshot: dict[str, object]) -> None:
        snapshot.update({
            "status": "passed",
            "conclusion": "passed",
            "reviewer": "code-reviewer",
            "scope": "full",
            "accepted_risks": [],
            "uncovered_scope": [],
        })
        self.write(
            project / ".claude" / ".review-status.json",
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        )

    def run_root_review_hook(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(self.repo / ".claude" / "hooks" / "review-check.ps1"),
            ],
            capture_output=True,
            text=True,
        )

    def run_root_build_hook(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(self.repo / ".claude" / "hooks" / "pre-commit-check.ps1"),
            ],
            capture_output=True,
            text=True,
        )

    def run_build_tool(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [shutil.which("python") or "python", str(BUILD_TOOL), *args],
            capture_output=True,
            text=True,
        )

    def test_child_review_can_cover_a_staged_subset(self) -> None:
        self.write(self.repo / "tool" / "a.py", "A = 2\n")
        self.write(self.repo / "tool" / "b.py", "B = 2\n")
        snapshot = self.snapshot(self.repo / "tool")
        self.assertEqual(snapshot["project_root"], "tool")
        self.assertEqual(snapshot["reviewed_files"], ["tool/a.py", "tool/b.py"])
        self.write_review(self.repo / "tool", snapshot)

        self.git("add", "tool/a.py")
        result = self.run_root_review_hook()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("1 DevFlow project", result.stdout)

    def test_root_project_review_remains_supported(self) -> None:
        self.write(self.repo / "root.py", "ROOT = 5\n")
        self.write_review(self.repo, self.snapshot(self.repo))
        self.git("add", "root.py")

        result = self.run_root_review_hook()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("1 DevFlow project", result.stdout)

    def test_nearest_nested_projects_require_their_own_credentials(self) -> None:
        nested = self.repo / "tool" / "plugin"
        self.install_project(nested)
        self.write(nested / "nested.py", "NESTED = 1\n")
        self.git("add", "tool/plugin")
        self.git("commit", "-m", "nested project")

        self.write(self.repo / "tool" / "a.py", "A = 3\n")
        self.write(nested / "nested.py", "NESTED = 2\n")
        self.write_review(self.repo / "tool", self.snapshot(self.repo / "tool"))
        self.write_review(nested, self.snapshot(nested))
        self.git("add", "tool/a.py", "tool/plugin/nested.py")

        passed = self.run_root_review_hook()
        self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
        self.assertIn("2 DevFlow project", passed.stdout)

        (nested / ".claude" / ".review-status.json").unlink()
        failed = self.run_root_review_hook()
        self.assertEqual(failed.returncode, 1)
        self.assertIn("tool/plugin: missing", failed.stdout)

    def test_build_scope_ignores_unstaged_code_in_other_projects(self) -> None:
        self.write(self.repo / "tool" / "a.py", "A = 4\n")
        self.git("add", "tool/a.py")
        self.write(self.repo / "root.py", "ROOT = 2\n")

        scopes = self.run_build_tool("scopes", "--root", str(self.repo), "--mode", "staged")
        self.assertEqual(scopes.returncode, 0, scopes.stderr)
        self.assertEqual(json.loads(scopes.stdout), ["tool"])

        clean = self.run_build_tool("verify-clean", "--root", str(self.repo / "tool"))
        self.assertEqual(clean.returncode, 0, clean.stderr)

        self.write(self.repo / "tool" / "b.py", "B = 4\n")
        dirty = self.run_build_tool("verify-clean", "--root", str(self.repo / "tool"))
        self.assertEqual(dirty.returncode, 11, dirty.stderr)

    def test_nested_claude_code_is_not_product_code(self) -> None:
        workflow_code = self.repo / "tool" / ".claude" / "local.py"
        self.write(workflow_code, "VALUE = 1\n")
        self.git("add", "-f", "tool/.claude/local.py")

        review = self.run_root_review_hook()
        self.assertEqual(review.returncode, 0, review.stdout + review.stderr)
        self.assertIn("No staged code files", review.stdout)

        scopes = self.run_build_tool("scopes", "--root", str(self.repo), "--mode", "staged")
        self.assertEqual(scopes.returncode, 0, scopes.stderr)
        self.assertEqual(json.loads(scopes.stdout), [])

    def test_deleted_nested_project_falls_back_to_surviving_parent(self) -> None:
        nested = self.repo / "tool" / "plugin"
        self.install_project(nested)
        self.write(nested / "nested.py", "NESTED = 1\n")
        self.git("add", "tool/plugin")
        self.git("commit", "-m", "nested project")
        self.git("rm", "-r", "tool/plugin")

        scopes = self.run_build_tool("scopes", "--root", str(self.repo), "--mode", "staged")
        self.assertEqual(scopes.returncode, 0, scopes.stderr)
        self.assertEqual(json.loads(scopes.stdout), ["tool"])

        snapshot = self.snapshot(self.repo / "tool")
        self.assertIn("tool/plugin/nested.py", snapshot["reviewed_files"])
        self.write_review(self.repo / "tool", snapshot)
        review = self.run_root_review_hook()
        self.assertEqual(review.returncode, 0, review.stdout + review.stderr)

        build = self.run_root_build_hook()
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        self.assertTrue((self.repo / "tool" / ".claude" / ".build-status.json").is_file())

    def test_build_credential_requires_the_exact_staged_set(self) -> None:
        self.write(self.repo / "tool" / "a.py", "A = 6\n")
        self.write(self.repo / "tool" / "b.py", "B = 6\n")
        self.git("add", "tool/a.py", "tool/b.py")
        recorded = self.run_build_tool(
            "record", "--root", str(self.repo / "tool"), "--mode", "staged",
            "--command", "manual-test", "--target", "project",
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)

        self.git("reset", "--", "tool/b.py")
        checked = self.run_build_tool(
            "check", "--root", str(self.repo / "tool"), "--mode", "staged"
        )
        self.assertEqual(checked.returncode, 10, checked.stderr)

        self.git("restore", "--worktree", "tool/b.py")
        rebuilt = self.run_root_build_hook()
        self.assertEqual(rebuilt.returncode, 0, rebuilt.stdout + rebuilt.stderr)
        credential = json.loads(
            (self.repo / "tool" / ".claude" / ".build-status.json").read_text(encoding="utf-8")
        )
        self.assertEqual(list(credential["validated_file_hashes"]), ["tool/a.py"])

    def test_build_hook_records_credential_in_the_owning_child_project(self) -> None:
        self.write(self.repo / "tool" / "a.py", "A = 7\n")
        self.git("add", "tool/a.py")

        result = self.run_root_build_hook()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.repo / "tool" / ".claude" / ".build-status.json").is_file())
        self.assertFalse((self.repo / ".claude" / ".build-status.json").exists())


if __name__ == "__main__":
    unittest.main()
