#!/usr/bin/env python3
"""Generate the DevFlow managed-file manifest for a release."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".claude/devflow-version.json"
EXCLUDED = {
    ".claude/devflow-version.json",
    ".claude/progress.json",
    ".claude/settings.local.json",
    ".claude/.review-status.json",
    ".claude/.build-status.json",
}
DEPRECATED = [
    ".claude/skills/design-maker/SKILL.md",
    ".claude/skills/ui-designer/references/qt-frontend.md",
    ".claude/skills/ui-designer/references/web-frontend.md",
]


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def is_managed_path(path: Path) -> bool:
    """Return whether a `.claude` path is eligible for distribution."""
    return (
        "__pycache__" not in path.parts
        and path.suffix.lower() not in {".pyc", ".pyo"}
        and not path.name.endswith(".review.json")
        and relative(path) not in EXCLUDED
    )


def is_managed_file(path: Path) -> bool:
    """Return whether an existing `.claude` file belongs in the manifest."""
    return path.is_file() and is_managed_path(path)


def legacy_content(path: str) -> bytes | None:
    result = subprocess.run(["git", "-C", str(ROOT), "show", f"main:{path}"], capture_output=True)
    return result.stdout if result.returncode == 0 else None


def main() -> None:
    files = sorted(
        path for path in (ROOT / ".claude").rglob("*")
        if is_managed_file(path)
    )
    managed = {relative(path): digest(path.read_bytes()) for path in files}
    legacy: dict[str, list[str]] = {}
    for path in sorted(set(managed) | set(DEPRECATED)):
        content = legacy_content(path)
        if content is not None:
            legacy[path] = [digest(content)]
    data = {
        "version": "1.1.2",
        "progress_schema_version": "1.1",
        "managed_files": managed,
        "deprecated_files": DEPRECATED,
        "legacy_hashes": legacy,
    }
    MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
