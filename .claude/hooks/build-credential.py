#!/usr/bin/env python3
"""Create and validate DevFlow build credentials."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CODE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
    ".cs", ".go", ".java", ".js", ".jsx", ".ts", ".tsx", ".py",
    ".rs", ".swift", ".ui",
}
BUILD_FILES = {
    "CMakeLists.txt", "xmake.lua", "package.json", "package-lock.json",
    "Cargo.toml", "Cargo.lock", "go.mod", "go.sum", "pyproject.toml", "setup.py",
}


def git_lines(root: Path, *args: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), *args, "-z"], capture_output=True, check=True
    )
    return [
        item.decode("utf-8", errors="surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    ]


def is_code_path(name: str) -> bool:
    normalized = name.replace("\\", "/")
    return not normalized.startswith(".claude/") and (
        Path(name).suffix.lower() in CODE_SUFFIXES or Path(name).name in BUILD_FILES
    )


def code_names(root: Path, mode: str) -> list[str]:
    if mode == "staged":
        names = set(git_lines(root, "diff", "--cached", "--name-only", "--diff-filter=ACMRDTUXB"))
    else:
        names = set(git_lines(root, "diff", "--name-only", "HEAD", "--diff-filter=ACMRDTUXB"))
        names.update(git_lines(root, "ls-files", "--others", "--exclude-standard"))
    return sorted(name for name in names if is_code_path(name))


def code_fingerprint(root: Path, mode: str = "working") -> str | None:
    names = code_names(root, mode)
    if not names:
        return None
    digest = hashlib.sha256()
    for name in names:
        digest.update(name.replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        if mode == "staged":
            result = subprocess.run(
                ["git", "-C", str(root), "rev-parse", f":{name}"],
                capture_output=True,
                text=True,
            )
        else:
            path = root / name
            result = subprocess.run(
                ["git", "-C", str(root), "hash-object", "--", name],
                capture_output=True,
                text=True,
            ) if path.exists() else None
        blob_hash = result.stdout.strip() if result is not None and result.returncode == 0 else "<deleted>"
        digest.update(blob_hash.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def has_unstaged_code(root: Path) -> bool:
    names = set(git_lines(root, "diff", "--name-only", "--diff-filter=ACMRDTUXB"))
    names.update(git_lines(root, "ls-files", "--others", "--exclude-standard"))
    return any(is_code_path(name) for name in names)


def credential_path(root: Path) -> Path:
    return root / ".claude" / ".build-status.json"


def check(root: Path, mode: str) -> int:
    fingerprint = code_fingerprint(root, mode)
    if fingerprint is None:
        return 0
    path = credential_path(root)
    if not path.exists():
        return 10
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return 10
    valid = data.get("result") == "passed" and data.get("code_fingerprint") == fingerprint
    return 0 if valid else 10


def record(root: Path, command: str, target: str, mode: str) -> int:
    fingerprint = code_fingerprint(root, mode)
    if fingerprint is None:
        return 0
    path = credential_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": "1.1",
        "result": "passed",
        "command": command,
        "target": target,
        "fingerprint_mode": mode,
        "code_fingerprint": fingerprint,
        "built_at": datetime.now(timezone.utc).astimezone().isoformat(),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("check", "record", "verify-clean"):
        subparser = subparsers.add_parser(action)
        subparser.add_argument("--root", required=True, type=Path)
        if action in {"check", "record"}:
            subparser.add_argument("--mode", choices=("working", "staged"), default="working")
        if action == "record":
            subparser.add_argument("--command", required=True)
            subparser.add_argument("--target", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.action == "verify-clean":
        return 11 if has_unstaged_code(root) else 0
    if args.action == "check":
        return check(root, args.mode)
    return record(root, args.command, args.target, args.mode)


if __name__ == "__main__":
    sys.exit(main())
