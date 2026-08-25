#!/usr/bin/env python3
"""Install, inspect, and safely update DevFlow in an existing project."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

VERSION_FILE = Path(".claude/devflow-version.json")
STATE_FILES = {
    ".claude/progress.json",
    ".claude/.review-status.json",
    ".claude/.build-status.json",
    ".claude/settings.local.json",
}
INSTALL_SEED_FILES = {".claude/progress.json"}


@dataclass
class Change:
    action: str
    path: str
    reason: str = ""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path, default: object | None = None) -> object:
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_manifest(root: Path) -> dict:
    data = load_json(root / VERSION_FILE)
    if not isinstance(data, dict) or "managed_files" not in data:
        raise ValueError(f"invalid manifest: {root / VERSION_FILE}")
    return data


def detect_vcs(target: Path) -> str:
    target = target.resolve()
    if (target / ".svn").exists():
        return "svn"
    if (target / ".git").exists():
        return "git"
    if shutil.which("svn"):
        result = subprocess.run(["svn", "info", str(target)], capture_output=True, text=True)
        if result.returncode == 0:
            return "svn"
    if shutil.which("git"):
        result = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip() == "true":
            return "git"
    return "none"


def git_worktree_root(target: Path) -> Path | None:
    if not shutil.which("git"):
        return None
    result = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip()).resolve()


def git_metadata_path(target: Path, option: str) -> Path | None:
    if not shutil.which("git"):
        return None
    result = subprocess.run(
        ["git", "-C", str(target), "rev-parse", option],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    path = Path(result.stdout.strip())
    return path.resolve() if path.is_absolute() else (target / path).resolve()


def is_linked_worktree(target: Path) -> bool:
    git_dir = git_metadata_path(target, "--git-dir")
    common_dir = git_metadata_path(target, "--git-common-dir")
    return bool(git_dir and common_dir and git_dir != common_dir)


def validate_target(target: Path, install: bool = False) -> str:
    if not target.exists() or not target.is_dir():
        raise ValueError(f"target directory does not exist: {target}")
    if target.resolve().parent == target.resolve():
        raise ValueError("target directory cannot be a filesystem root")
    if install and (target / ".claude").exists():
        raise ValueError(".claude already exists; use update instead of install")
    return detect_vcs(target)


def target_previous_hash(path: str, target: Path, target_manifest: dict | None, source_manifest: dict) -> str | None:
    if target_manifest:
        value = target_manifest.get("managed_files", {}).get(path)
        if isinstance(value, str):
            return value
        current = target / path
        legacy = target_manifest.get("legacy_hashes", {}).get(path, [])
        if current.exists() and sha256(current) in legacy:
            return sha256(current)
        return None
    legacy = source_manifest.get("legacy_hashes", {}).get(path, [])
    current = target / path
    if current.exists() and sha256(current) in legacy:
        return sha256(current)
    return None


def classify(target: Path, source: Path, source_manifest: dict, force: bool = False) -> list[Change]:
    target_manifest_path = target / VERSION_FILE
    target_manifest = load_json(target_manifest_path) if target_manifest_path.exists() else None
    changes: list[Change] = []
    for path, expected_hash in sorted(source_manifest["managed_files"].items()):
        src = source / path
        dst = target / path
        if path in STATE_FILES:
            continue
        if not dst.exists():
            changes.append(Change("add", path))
            continue
        current_hash = sha256(dst)
        if current_hash == expected_hash:
            changes.append(Change("keep", path, "already current"))
            continue
        previous_hash = target_previous_hash(path, target, target_manifest, source_manifest)
        if force or (previous_hash and current_hash == previous_hash):
            changes.append(Change("update", path, "forced" if force else "unmodified managed file"))
        else:
            changes.append(Change("conflict", path, "project customization or unknown legacy file"))

    for path in source_manifest.get("deprecated_files", []):
        dst = target / path
        if not dst.exists():
            continue
        previous_hash = target_previous_hash(path, target, target_manifest, source_manifest)
        current_hash = sha256(dst)
        if force or (previous_hash and current_hash == previous_hash):
            changes.append(Change("delete", path, "deprecated"))
        else:
            changes.append(Change("conflict", path, "deprecated but customized"))
    return changes


def migrate_progress(source: Path, target: Path) -> Change:
    src_data = load_json(source / ".claude/progress.json")
    dst_path = target / ".claude/progress.json"
    if not dst_path.exists():
        write_json(dst_path, src_data)
        return Change("add", ".claude/progress.json", "initialized")

    old = load_json(dst_path, {})
    if not isinstance(old, dict):
        raise ValueError("target progress.json is not an object")
    merged = dict(src_data)
    for key in (
        "current_iteration", "current_requirement_input", "current_skill", "current_step",
        "status", "documents", "current_task", "iteration_history",
    ):
        if key in old:
            merged[key] = old[key]
    merged["updated_at"] = old.get("updated_at") or old.get("last_session")
    merged["blocked_items"] = old.get("blocked_items", [])
    merged["milestones"] = migrate_milestones(old.get("milestones", {}))
    merged["pending_inputs"] = old.get("pending_inputs", [])
    history = merged.get("iteration_history", [])
    merged["iteration_history"] = history[-10:] if isinstance(history, list) else []
    write_json(dst_path, merged)
    return Change("migrate", ".claude/progress.json", "runtime state preserved")


def migrate_milestones(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if not isinstance(value, list):
        return {}

    milestones: dict[str, object] = {}
    for index, item in enumerate(value, start=1):
        if isinstance(item, dict):
            base = next(
                (str(item[key]) for key in ("stage", "skill", "name", "id") if item.get(key)),
                f"legacy_{index}",
            )
            entry: object = dict(item)
        else:
            base = f"legacy_{index}"
            entry = {"status": str(item)}
        key = base
        suffix = 2
        while key in milestones:
            key = f"{base}_{suffix}"
            suffix += 1
        milestones[key] = entry
    return milestones


def backup_target(target: Path, backup_dir: Path | None, vcs: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if backup_dir:
        base = backup_dir.resolve()
    elif vcs == "git":
        result = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            check=True,
        )
        git_dir = Path(result.stdout.strip())
        if not git_dir.is_absolute():
            git_dir = (target / git_dir).resolve()
        base = git_dir / "devflow-backups" / target.name
    else:
        base = target.parent / f"{target.name}-devflow-backups"
    claude_dir = (target / ".claude").resolve()
    if base == claude_dir or claude_dir in base.parents:
        raise ValueError("backup directory cannot be inside target .claude")
    destination = base / f"devflow-{timestamp}"
    counter = 1
    while destination.exists():
        destination = base / f"devflow-{timestamp}-{counter}"
        counter += 1
    destination.mkdir(parents=True, exist_ok=False)
    if (target / ".claude").exists():
        shutil.copytree(target / ".claude", destination / ".claude")
    return destination


def print_changes(changes: list[Change], verbose: bool) -> None:
    counts: dict[str, int] = {}
    for change in changes:
        counts[change.action] = counts.get(change.action, 0) + 1
        if verbose or change.action not in {"keep"}:
            suffix = f" ({change.reason})" if change.reason else ""
            print(f"{change.action.upper():8} {change.path}{suffix}")
    print("Summary: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))


def apply_changes(target: Path, source: Path, manifest: dict, changes: list[Change]) -> None:
    for change in changes:
        dst = target / change.path
        if change.action in {"add", "update"}:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / change.path, dst)
        elif change.action == "delete":
            dst.unlink()
            parent = dst.parent
            while parent != target / ".claude" and parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
    write_json(target / VERSION_FILE, manifest)


def plan_hooks(target: Path, vcs: str, disabled: bool) -> tuple[str, str]:
    if disabled:
        return "disabled", ""
    if vcs != "git":
        return "non-git", ""
    if git_worktree_root(target) != target.resolve():
        return "git-subdirectory", ""
    if is_linked_worktree(target):
        return "git-linked-worktree", ""
    current = subprocess.run(
        ["git", "-C", str(target), "config", "--get", "core.hooksPath"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    if current.replace("\\", "/") == ".claude/hooks":
        return "current", current
    return "configure", current


def hook_change(plan: tuple[str, str]) -> Change | None:
    status, current = plan
    if status == "configure":
        return Change("config", "core.hooksPath", f"current value: {current or 'unset'}")
    return None


def apply_hook_plan(target: Path, plan: tuple[str, str]) -> str:
    status, _ = plan
    if status != "configure":
        return status
    subprocess.run(["git", "-C", str(target), "config", "core.hooksPath", ".claude/hooks"], check=True)
    return "configured"


def print_hook_result(result: str) -> None:
    messages = {
        "configured": "Git hooks configured: core.hooksPath=.claude/hooks",
        "configure": "Git hooks would be configured: core.hooksPath=.claude/hooks",
        "current": "Git hooks already configured: core.hooksPath=.claude/hooks",
        "disabled": "Git hook configuration skipped by --no-hooks.",
        "non-git": "Git hooks skipped for a non-Git target; workflow checks remain available without commit-hook enforcement.",
        "git-subdirectory": "Git hooks skipped because the target is inside a larger Git worktree; repository-wide hook configuration was left unchanged.",
        "git-linked-worktree": "Git hooks skipped for a linked worktree because core.hooksPath may be shared with other worktrees.",
    }
    print(messages[result])


def command_check(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    vcs = validate_target(target)
    source = source_root()
    manifest = read_manifest(source)
    changes = classify(target, source, manifest, force=False)
    hook_plan = plan_hooks(target, vcs, args.no_hooks)
    planned_change = hook_change(hook_plan)
    if planned_change:
        changes.append(planned_change)
    print(f"Target mode: {vcs}")
    print_changes(changes, args.verbose)
    if not planned_change:
        print_hook_result(hook_plan[0])
    return 2 if any(change.action in {"conflict", "config"} for change in changes) else 0


def command_install(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    vcs = validate_target(target, install=True)
    source = source_root()
    manifest = read_manifest(source)
    changes = [Change("add", path) for path in sorted(manifest["managed_files"]) if path not in STATE_FILES]
    for path in sorted(INSTALL_SEED_FILES):
        changes.append(Change("add", path, "initialized"))
    hook_plan = plan_hooks(target, vcs, args.no_hooks)
    planned_change = hook_change(hook_plan)
    if planned_change:
        changes.append(planned_change)
    print(f"Target mode: {vcs}")
    print_changes(changes, args.verbose)
    if args.dry_run:
        if not planned_change:
            print_hook_result(hook_plan[0])
        return 0
    if not args.yes:
        answer = input(f"Install DevFlow {manifest['version']} into {target}? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            return 1
    managed_changes = [
        change for change in changes
        if change.action in {"add", "update", "delete"} and change.path not in INSTALL_SEED_FILES
    ]
    apply_changes(target, source, manifest, managed_changes)
    migrate_progress(source, target)
    hook_result = apply_hook_plan(target, hook_plan)
    print_hook_result(hook_result)
    print("Installation complete. Review local tool permissions if needed, then restart Claude Code.")
    return 0


def command_update(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    vcs = validate_target(target)
    source = source_root()
    manifest = read_manifest(source)
    changes = classify(target, source, manifest, force=args.force)
    hook_plan = plan_hooks(target, vcs, args.no_hooks)
    planned_change = hook_change(hook_plan)
    if planned_change:
        changes.append(planned_change)
    print(f"Target mode: {vcs}")
    print_changes(changes, args.verbose)
    conflicts = [change for change in changes if change.action == "conflict"]
    if args.dry_run:
        if not planned_change:
            print_hook_result(hook_plan[0])
        return 2 if conflicts or planned_change else 0
    if not args.yes:
        answer = input(f"Back up and update DevFlow in {target}? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            return 1
    backup = backup_target(target, args.backup_dir, vcs)
    file_changes = [change for change in changes if change.action in {"add", "update", "delete"}]
    apply_changes(target, source, manifest, file_changes)
    migrate_progress(source, target)
    hook_result = apply_hook_plan(target, hook_plan)
    print(f"Backup: {backup}")
    print_hook_result(hook_result)
    if conflicts:
        print("Update completed with conflicts. Customized files were preserved; resolve them manually or rerun with --force.")
        return 2
    print("Update complete. Restart Claude Code before continuing.")
    return 0


def add_common_options(parser: argparse.ArgumentParser, *, changes: bool) -> None:
    parser.add_argument("--target", required=True, type=Path, help="target project directory (Git, SVN, or no VCS)")
    parser.add_argument("--dry-run", action="store_true", help="show actions without modifying files")
    parser.add_argument("--yes", action="store_true", help="skip the interactive confirmation")
    parser.add_argument("--verbose", action="store_true", help="show unchanged managed files")
    parser.add_argument("--no-hooks", action="store_true", help="do not configure Git hooks when the target is a Git worktree")
    if changes:
        parser.add_argument("--force", action="store_true", help="back up and overwrite conflicting managed files; runtime state remains protected")
        parser.add_argument("--backup-dir", type=Path, help="custom backup parent directory")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install or update DevFlow with a conservative, hash-based strategy.",
        epilog="Recommended: preview install with --dry-run; for upgrades run check, then update. Customized and runtime files are preserved by default.",
    )
    subparsers = parser.add_subparsers(dest="command")
    check_parser = subparsers.add_parser("check", help="inspect update actions and conflicts")
    check_parser.add_argument("--target", required=True, type=Path)
    check_parser.add_argument("--verbose", action="store_true")
    check_parser.add_argument("--no-hooks", action="store_true", help="do not report Git hook configuration")
    check_parser.set_defaults(handler=command_check)
    install_parser = subparsers.add_parser("install", help="install DevFlow into a project directory")
    add_common_options(install_parser, changes=False)
    install_parser.set_defaults(handler=command_install)
    update_parser = subparsers.add_parser("update", help="back up and conservatively update DevFlow")
    add_common_options(update_parser, changes=True)
    update_parser.set_defaults(handler=command_update)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, "handler"):
        parser.print_help()
        return 0
    try:
        return args.handler(args)
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
