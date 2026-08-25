from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "devflow.py"
SPEC = importlib.util.spec_from_file_location("devflow_installer", SCRIPT)
assert SPEC and SPEC.loader
devflow = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = devflow
SPEC.loader.exec_module(devflow)


class DevFlowInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

    def git(self, target: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(target), *args],
            capture_output=True,
            text=True,
            check=True,
        )

    def init_git(self, name: str = "repo") -> Path:
        if not shutil.which("git"):
            self.skipTest("git is unavailable")
        target = self.base / name
        target.mkdir()
        self.git(target, "init")
        return target

    def test_rejects_filesystem_root(self) -> None:
        filesystem_root = Path.cwd().resolve()
        while filesystem_root.parent != filesystem_root:
            filesystem_root = filesystem_root.parent
        with self.assertRaisesRegex(ValueError, "filesystem root"):
            devflow.validate_target(filesystem_root)

    def test_explicit_svn_marker_wins_over_nested_git_detection(self) -> None:
        target = self.init_git()
        (target / ".svn").mkdir()
        self.assertEqual(devflow.detect_vcs(target), "svn")

    def test_no_vcs_install_omits_local_settings_and_uses_external_backup(self) -> None:
        target = self.base / "plain"
        target.mkdir()
        result = self.run_cli("install", "--target", str(target), "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((target / ".claude" / "settings.local.json").exists())
        backup = devflow.backup_target(target, None, "none")
        self.assertEqual(backup.parent, target.parent / f"{target.name}-devflow-backups")
        self.assertFalse(backup.is_relative_to(target))

    def test_git_root_dry_run_previews_hook_without_mutating_config(self) -> None:
        target = self.init_git()
        result = self.run_cli("install", "--target", str(target), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CONFIG", result.stdout)
        self.assertIn("core.hooksPath", result.stdout)
        current = subprocess.run(
            ["git", "-C", str(target), "config", "--get", "core.hooksPath"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(current.returncode, 0)

    def test_check_and_update_dry_run_agree_on_pending_hook_config(self) -> None:
        target = self.init_git()
        installed = self.run_cli("install", "--target", str(target), "--yes", "--no-hooks")
        self.assertEqual(installed.returncode, 0, installed.stderr)
        checked = self.run_cli("check", "--target", str(target))
        updated = self.run_cli("update", "--target", str(target), "--dry-run")
        self.assertEqual(checked.returncode, 2, checked.stdout + checked.stderr)
        self.assertEqual(updated.returncode, 2, updated.stdout + updated.stderr)
        self.assertIn("CONFIG", checked.stdout)
        self.assertIn("CONFIG", updated.stdout)

    def test_git_subdirectory_skips_repository_wide_hook_config(self) -> None:
        root = self.init_git()
        target = root / "component"
        target.mkdir()
        self.assertEqual(devflow.plan_hooks(target, "git", False)[0], "git-subdirectory")

    def test_linked_worktree_skips_shared_hook_config(self) -> None:
        root = self.init_git()
        self.git(root, "-c", "user.name=DevFlow Test", "-c", "user.email=test@example.com", "commit", "--allow-empty", "-m", "init")
        linked = self.base / "linked"
        self.git(root, "worktree", "add", "-b", "linked-test", str(linked))
        self.assertTrue(devflow.is_linked_worktree(linked))
        self.assertEqual(devflow.plan_hooks(linked, "git", False)[0], "git-linked-worktree")

    def test_git_backup_uses_git_metadata(self) -> None:
        target = self.init_git()
        (target / ".claude").mkdir()
        (target / ".claude" / "state.txt").write_text("state", encoding="utf-8")
        backup = devflow.backup_target(target, None, "git")
        git_dir = devflow.git_metadata_path(target, "--git-dir")
        assert git_dir
        self.assertTrue(backup.is_relative_to(git_dir / "devflow-backups"))
        self.assertTrue((backup / ".claude" / "state.txt").exists())


if __name__ == "__main__":
    unittest.main()
