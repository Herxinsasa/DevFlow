from __future__ import annotations

import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "devflow.py"
MANIFEST_SCRIPT = ROOT / "scripts" / "build_manifest.py"
SPEC = importlib.util.spec_from_file_location("devflow_installer", SCRIPT)
assert SPEC and SPEC.loader
devflow = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = devflow
SPEC.loader.exec_module(devflow)
MANIFEST_SPEC = importlib.util.spec_from_file_location("devflow_manifest", MANIFEST_SCRIPT)
assert MANIFEST_SPEC and MANIFEST_SPEC.loader
build_manifest = importlib.util.module_from_spec(MANIFEST_SPEC)
sys.modules[MANIFEST_SPEC.name] = build_manifest
MANIFEST_SPEC.loader.exec_module(build_manifest)


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

    def test_manifest_excludes_local_review_artifacts(self) -> None:
        review_artifact = ROOT / ".claude" / "skills" / "spec-analyzer" / "SKILL.md.review.json"
        managed_skill = ROOT / ".claude" / "skills" / "spec-analyzer" / "SKILL.md"
        self.assertFalse(build_manifest.is_managed_path(review_artifact))
        self.assertTrue(build_manifest.is_managed_path(managed_skill))

    def test_explicit_svn_marker_wins_over_nested_git_detection(self) -> None:
        target = self.init_git()
        (target / ".svn").mkdir()
        self.assertEqual(devflow.detect_vcs(target), "svn")

    def test_no_vcs_install_omits_local_settings_and_uses_external_backup(self) -> None:
        target = self.base / "plain"
        target.mkdir()
        result = self.run_cli("install", "--target", str(target), "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Git hooks skipped for a non-Git target", result.stdout)
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

    def test_clean_check_is_concise_unless_verbose(self) -> None:
        target = self.base / "plain"
        target.mkdir()
        installed = self.run_cli("install", "--target", str(target), "--yes", "--no-hooks")
        self.assertEqual(installed.returncode, 0, installed.stderr)

        concise = self.run_cli("check", "--target", str(target), "--no-hooks")
        self.assertEqual(concise.returncode, 0, concise.stderr)
        self.assertIn("[OK] CHECK COMPLETE", concise.stdout)
        self.assertNotIn("keep=", concise.stdout)
        self.assertNotIn("KEEP", concise.stdout)

        verbose = self.run_cli("check", "--target", str(target), "--no-hooks", "--verbose")
        self.assertEqual(verbose.returncode, 0, verbose.stderr)
        self.assertIn("KEEP", verbose.stdout)
        self.assertIn("keep=", verbose.stdout)

    def test_install_preview_summarizes_files_by_default(self) -> None:
        target = self.base / "preview"
        target.mkdir()
        result = self.run_cli("install", "--target", str(target), "--dry-run", "--no-hooks")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[PLAN] INSTALL PREVIEW", result.stdout)
        self.assertIn("Files to add:", result.stdout)
        self.assertNotIn(".claude/CLAUDE.md", result.stdout)
        self.assertIn("No files were changed.", result.stdout)

    def test_invalid_progress_blocks_update_before_backup_or_changes(self) -> None:
        target = self.base / "invalid-progress"
        target.mkdir()
        installed = self.run_cli("install", "--target", str(target), "--yes", "--no-hooks")
        self.assertEqual(installed.returncode, 0, installed.stderr)
        managed = target / ".claude" / "CLAUDE.md"
        before = managed.read_bytes()
        (target / ".claude" / "progress.json").write_text(
            '{"status": "ready"\n"current_step": "test"}\n', encoding="utf-8"
        )

        result = self.run_cli("update", "--target", str(target), "--yes", "--no-hooks")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("[FAILED] UPDATE FAILED", result.stderr)
        self.assertIn("Phase: validate", result.stderr)
        self.assertIn("invalid JSON", result.stderr)
        self.assertIn("line 2", result.stderr)
        self.assertIn("Files changed: no", result.stderr)
        self.assertEqual(managed.read_bytes(), before)
        self.assertFalse((target.parent / f"{target.name}-devflow-backups").exists())

    def test_install_validation_failure_has_structured_output(self) -> None:
        target = self.base / "existing"
        (target / ".claude").mkdir(parents=True)
        result = self.run_cli("install", "--target", str(target), "--dry-run")
        self.assertEqual(result.returncode, 1)
        self.assertIn("[FAILED] INSTALL FAILED", result.stderr)
        self.assertIn("Phase: validate", result.stderr)
        self.assertIn("use update instead of install", result.stderr)
        self.assertIn("Files changed: no", result.stderr)

    def test_invalid_manifest_structure_has_structured_output(self) -> None:
        cases = {
            "array": ["bad"],
            "string": "bad",
            "managed-list": {"version": "bad", "managed_files": []},
            "legacy-list": {"version": "bad", "managed_files": {}, "legacy_hashes": []},
        }
        for name, content in cases.items():
            with self.subTest(name=name):
                target = self.base / f"invalid-manifest-{name}"
                target.mkdir()
                installed = self.run_cli("install", "--target", str(target), "--yes", "--no-hooks")
                self.assertEqual(installed.returncode, 0, installed.stderr)
                managed = target / ".claude" / "CLAUDE.md"
                before = managed.read_bytes()
                (target / ".claude" / "devflow-version.json").write_text(
                    json.dumps(content) + "\n", encoding="utf-8"
                )

                result = self.run_cli("update", "--target", str(target), "--yes", "--no-hooks")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("[FAILED] UPDATE FAILED", result.stderr)
                self.assertIn("Phase: plan", result.stderr)
                self.assertIn("invalid manifest", result.stderr)
                self.assertIn("Files changed: no", result.stderr)
                self.assertEqual(managed.read_bytes(), before)
                self.assertFalse((target.parent / f"{target.name}-devflow-backups").exists())

    def test_check_explains_modified_conflict_and_next_action(self) -> None:
        target = self.base / "modified"
        target.mkdir()
        installed = self.run_cli("install", "--target", str(target), "--yes", "--no-hooks")
        self.assertEqual(installed.returncode, 0, installed.stderr)
        managed = target / ".claude" / "CLAUDE.md"
        managed.write_text(managed.read_text(encoding="utf-8") + "\nproject customization\n", encoding="utf-8")

        result = self.run_cli("check", "--target", str(target), "--no-hooks")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("[ATTENTION] UPDATE REQUIRES REVIEW", result.stdout)
        self.assertIn("modified since the installed version; preserved", result.stdout)
        self.assertIn("Next: review the conflicts", result.stdout)

    def test_called_process_error_is_sanitized(self) -> None:
        raw = subprocess.CalledProcessError(
            128,
            ["git", "-C", "target", "rev-parse", "--git-dir"],
            stderr="fatal: not a git repository",
        )
        error = devflow.operation_error("UPDATE", "backup", self.base, raw)
        output = io.StringIO()
        with redirect_stderr(output):
            devflow.print_failure(error)
        rendered = output.getvalue()
        self.assertIn("Reason: fatal: not a git repository", rendered)
        self.assertNotIn("Command '[", rendered)
        self.assertNotIn("['git',", rendered)


if __name__ == "__main__":
    unittest.main()
