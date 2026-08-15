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
INSTALL_SEED_FILES = {".claude/progress.json", ".claude/settings.local.json"}


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


def validate_target(target: Path, install: bool = False) -> None:
    if not target.exists() or not target.is_dir():
        raise ValueError(f"target directory does not exist: {target}")
    if not (target / ".git").exists():
        raise ValueError(f"target is not a Git repository: {target}")
    result = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise ValueError(f"target is not a valid Git worktree: {target}")
    if install and (target / ".claude").exists():
        raise ValueError(".claude already exists; use update instead of install")


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


def backup_target(target: Path, backup_dir: Path | None) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if backup_dir:
        base = backup_dir.resolve()
    else:
        result = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--path-format=absolute", "--git-dir"],
            capture_output=True,
            text=True,
            check=True,
        )
        base = Path(result.stdout.strip()) / "devflow-backups"
    claude_dir = (target / ".claude").resolve()
    if base == claude_dir or claude_dir in base.parents:
        raise ValueError("backup directory cannot be inside target .claude")
    destination = base / f"devflow-{timestamp}"
    counter = 1
    while destination.exists():
        destination = base / f"devflow-{timestamp}-{counter}"
        counter += 1
    destination.parent.mkdir(parents=True, exist_ok=True)
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


def configure_hooks(target: Path) -> None:
    subprocess.run(["git", "-C", str(target), "config", "core.hooksPath", ".claude/hooks"], check=True)


def command_check(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    validate_target(target)
    source = source_root()
    manifest = read_manifest(source)
    changes = classify(target, source, manifest, force=False)
    hooks_path = subprocess.run(
        ["git", "-C", str(target), "config", "--get", "core.hooksPath"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    if hooks_path.replace("\\", "/") != ".claude/hooks":
        changes.append(Change("config", "core.hooksPath", f"current value: {hooks_path or 'unset'}"))
    print_changes(changes, args.verbose)
    return 2 if any(change.action in {"conflict", "config"} for change in changes) else 0


def command_install(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    validate_target(target, install=True)
    source = source_root()
    manifest = read_manifest(source)
    changes = [Change("add", path) for path in sorted(manifest["managed_files"]) if path not in STATE_FILES]
    for path in sorted(INSTALL_SEED_FILES):
        changes.append(Change("add", path, "initialized"))
    print_changes(changes, args.verbose)
    if args.dry_run:
        return 0
    if not args.yes:
        answer = input(f"Install DevFlow {manifest['version']} into {target}? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            return 1
    managed_changes = [change for change in changes if change.path not in INSTALL_SEED_FILES]
    apply_changes(target, source, manifest, managed_changes)
    settings_target = target / ".claude/settings.local.json"
    settings_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / ".claude/settings.local.json", settings_target)
    migrate_progress(source, target)
    configure_hooks(target)
    print("Installation complete. Restart Claude Code before using DevFlow.")
    return 0


def command_update(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    validate_target(target)
    source = source_root()
    manifest = read_manifest(source)
    changes = classify(target, source, manifest, force=args.force)
    print_changes(changes, args.verbose)
    conflicts = [change for change in changes if change.action == "conflict"]
    if args.dry_run:
        return 2 if conflicts else 0
    if not args.yes:
        answer = input(f"Back up and update DevFlow in {target}? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            return 1
    backup = backup_target(target, args.backup_dir)
    apply_changes(target, source, manifest, changes)
    migrate_progress(source, target)
    configure_hooks(target)
    print(f"Backup: {backup}")
    if conflicts:
        print("Update completed with conflicts. Customized files were preserved; resolve them manually or rerun with --force.")
        return 2
    print("Update complete. Restart Claude Code before continuing.")
    return 0


def add_common_options(parser: argparse.ArgumentParser, *, changes: bool) -> None:
    parser.add_argument("--target", required=True, type=Path, help="target Git project root")
    parser.add_argument("--dry-run", action="store_true", help="show actions without modifying files")
    parser.add_argument("--yes", action="store_true", help="skip the interactive confirmation")
    parser.add_argument("--verbose", action="store_true", help="show unchanged managed files")
    if changes:
        parser.add_argument("--force", action="store_true", help="back up and overwrite conflicting managed files; runtime state remains protected")
        parser.add_argument("--backup-dir", type=Path, help="custom backup parent directory")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install or update DevFlow with a conservative, hash-based strategy.",
        epilog="Recommended: check, then update --dry-run, then update. The default update preserves customized and runtime files.",
    )
    subparsers = parser.add_subparsers(dest="command")
    check_parser = subparsers.add_parser("check", help="inspect update actions and conflicts")
    check_parser.add_argument("--target", required=True, type=Path)
    check_parser.add_argument("--verbose", action="store_true")
    check_parser.set_defaults(handler=command_check)
    install_parser = subparsers.add_parser("install", help="install DevFlow into a Git project")
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
