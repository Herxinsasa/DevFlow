#!/usr/bin/env python3
"""Create and validate project-scoped DevFlow build credentials."""

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
    ".ps1", ".rs", ".swift", ".ui",
}
BUILD_FILES = {
    "CMakeLists.txt", "xmake.lua", "package.json", "package-lock.json",
    "Cargo.toml", "Cargo.lock", "go.mod", "go.sum", "pyproject.toml", "setup.py",
}
MARKER = ".claude/devflow-version.json"


def git_bytes(root: Path, *args: str, check: bool = True) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=check
    )
    return result.stdout


def git_lines(root: Path, *args: str, check: bool = True) -> list[str]:
    command = (*args[:1], "-z", *args[1:])
    output = git_bytes(root, *command, check=check)
    return [
        item.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        for item in output.split(b"\0")
        if item
    ]


def git_root(root: Path) -> Path:
    output = git_bytes(root, "rev-parse", "--show-toplevel")
    return Path(output.decode().strip()).resolve()


def relative_prefix(root: Path, repository: Path) -> str:
    relative = root.resolve().relative_to(repository.resolve()).as_posix()
    return "" if relative == "." else relative


def marker_prefix(path: str) -> str | None:
    normalized = path.replace("\\", "/")
    if normalized == MARKER:
        return ""
    suffix = f"/{MARKER}"
    return normalized[: -len(suffix)] if normalized.endswith(suffix) else None


def changed_names(repository: Path, mode: str) -> list[str]:
    if mode == "staged":
        return sorted(set(git_lines(
            repository, "diff", "--cached", "--name-only", "--diff-filter=ACMRDTUXB"
        )))
    names = set(git_lines(
        repository, "diff", "--name-only", "HEAD", "--diff-filter=ACMRDTUXB"
    ))
    names.update(git_lines(repository, "ls-files", "--others", "--exclude-standard"))
    return sorted(names)


def unstaged_names(repository: Path) -> list[str]:
    names = set(git_lines(
        repository, "diff", "--name-only", "--diff-filter=ACMRDTUXB"
    ))
    names.update(git_lines(repository, "ls-files", "--others", "--exclude-standard"))
    return sorted(names)


def project_prefixes(repository: Path, paths: list[str]) -> set[str]:
    prefixes: set[str] = set()
    tracked = git_lines(repository, "ls-files", "--cached")
    for path in tracked:
        prefix = marker_prefix(path)
        if prefix is not None:
            prefixes.add(prefix)

    for path in paths:
        candidate = Path(path).parent
        while True:
            prefix = "" if candidate == Path(".") else candidate.as_posix()
            if (repository / prefix / MARKER).is_file():
                prefixes.add(prefix)
            if not prefix:
                break
            candidate = candidate.parent
    return prefixes


def owner_prefix(path: str, prefixes: set[str]) -> str | None:
    candidates = [
        prefix for prefix in prefixes
        if not prefix or path == prefix or path.startswith(f"{prefix}/")
    ]
    return max(candidates, key=len) if candidates else None


def is_code_path(name: str) -> bool:
    normalized = name.replace("\\", "/")
    if "/.claude/" in f"/{normalized}":
        return False
    path = Path(normalized)
    return path.suffix.lower() in CODE_SUFFIXES or path.name in BUILD_FILES


def scoped_code_names(root: Path, mode: str) -> list[str]:
    repository = git_root(root)
    names = changed_names(repository, mode)
    prefixes = project_prefixes(repository, names)
    expected = relative_prefix(root, repository)
    return sorted(
        name for name in names
        if is_code_path(name) and owner_prefix(name, prefixes) == expected
    )


def changed_scopes(root: Path, mode: str) -> list[str]:
    repository = git_root(root)
    names = changed_names(repository, mode)
    prefixes = project_prefixes(repository, names)
    owners = {
        owner_prefix(name, prefixes)
        for name in names
        if is_code_path(name)
    }
    if None in owners:
        raise ValueError("changed code exists outside every DevFlow project")
    return sorted((owner or ".") for owner in owners)


def blob_hash(repository: Path, name: str, mode: str) -> str:
    if mode == "staged":
        result = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", f":{name}"],
            capture_output=True, text=True,
        )
    else:
        path = repository / name
        result = subprocess.run(
            ["git", "-C", str(repository), "hash-object", "--", name],
            capture_output=True, text=True,
        ) if path.exists() else None
    return result.stdout.strip() if result is not None and result.returncode == 0 else "<deleted>"


def code_hashes(root: Path, mode: str) -> dict[str, str]:
    repository = git_root(root)
    return {name: blob_hash(repository, name, mode) for name in scoped_code_names(root, mode)}


def fingerprint(hashes: dict[str, str]) -> str | None:
    if not hashes:
        return None
    digest = hashlib.sha256()
    for name, value in sorted(hashes.items()):
        digest.update(name.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(value.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def has_unstaged_code(root: Path) -> bool:
    repository = git_root(root)
    names = unstaged_names(repository)
    prefixes = project_prefixes(repository, names)
    expected = relative_prefix(root, repository)
    return any(
        is_code_path(name) and owner_prefix(name, prefixes) == expected
        for name in names
    )


def credential_path(root: Path) -> Path:
    return root / ".claude" / ".build-status.json"


def check(root: Path, mode: str) -> int:
    hashes = code_hashes(root, mode)
    current_fingerprint = fingerprint(hashes)
    if current_fingerprint is None:
        return 0
    path = credential_path(root)
    if not path.exists():
        return 10
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return 10
    if data.get("result") != "passed":
        return 10

    expected_root = relative_prefix(root, git_root(root)) or "."
    if data.get("project_root") not in (None, expected_root):
        return 10
    validated = data.get("validated_file_hashes")
    if isinstance(validated, dict):
        return 0 if validated == hashes else 10
    return 0 if data.get("code_fingerprint") == current_fingerprint else 10


def record(root: Path, command: str, target: str, mode: str) -> int:
    hashes = code_hashes(root, mode)
    current_fingerprint = fingerprint(hashes)
    if current_fingerprint is None:
        return 0
    path = credential_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": "1.2",
        "project_root": relative_prefix(root, git_root(root)) or ".",
        "result": "passed",
        "command": command,
        "target": target,
        "fingerprint_mode": mode,
        "validated_file_hashes": hashes,
        "code_fingerprint": current_fingerprint,
        "built_at": datetime.now(timezone.utc).astimezone().isoformat(),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("check", "record", "verify-clean", "scopes"):
        subparser = subparsers.add_parser(action)
        subparser.add_argument("--root", required=True, type=Path)
        if action in {"check", "record", "scopes"}:
            subparser.add_argument("--mode", choices=("working", "staged"), default="working")
        if action == "record":
            subparser.add_argument("--command", required=True)
            subparser.add_argument("--target", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.action == "verify-clean":
        return 11 if has_unstaged_code(root) else 0
    if args.action == "scopes":
        print(json.dumps(changed_scopes(root, args.mode), ensure_ascii=False))
        return 0
    if args.action == "check":
        return check(root, args.mode)
    return record(root, args.command, args.target, args.mode)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"build credential error: {error}", file=sys.stderr)
        sys.exit(12)
