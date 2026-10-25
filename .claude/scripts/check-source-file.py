#!/usr/bin/env python3
"""Check one changed text file against its confirmed encoding profile."""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

UTF8_BOM = b"\xef\xbb\xbf"


def force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")


def read_text(path: Path, encoding: str) -> tuple[str, bool, bytes]:
    content = path.read_bytes()
    has_bom = content.startswith(UTF8_BOM)
    payload = content[len(UTF8_BOM):] if has_bom else content
    if has_bom and encoding.lower().replace("_", "-") not in {"utf-8", "utf8"}:
        raise ValueError("UTF-8 BOM conflicts with target encoding")
    return payload.decode(encoding, errors="strict"), has_bom, content


def new_replacement_character(before: str, after: str) -> bool:
    if "\ufffd" not in after:
        return False
    if "\ufffd" not in before:
        return True
    old_lines = before.splitlines(keepends=True)
    new_lines = after.splitlines(keepends=True)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, old_lines, new_lines, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            continue
        old_block = "".join(old_lines[i1:i2])
        new_block = "".join(new_lines[j1:j2])
        if "\ufffd" not in new_block:
            continue
        if "\ufffd" not in old_block:
            return True
        if any(
            part != "equal" and "\ufffd" in new_block[b1:b2]
            for part, _, _, b1, b2 in difflib.SequenceMatcher(
                None, old_block, new_block, autojunk=False
            ).get_opcodes()
        ):
            return True
    return False


def check_eol(content: bytes, expected: str) -> None:
    crlf = content.count(b"\r\n")
    lf = content.count(b"\n")
    lone_cr = content.count(b"\r") - crlf
    if lone_cr or (crlf and lf != crlf):
        raise ValueError("mixed or bare-CR line endings")
    if expected == "lf" and crlf:
        raise ValueError("expected LF line endings")
    if expected == "crlf" and lf != crlf:
        raise ValueError("expected CRLF line endings")
    if content and not content.endswith(b"\n"):
        raise ValueError("missing final newline")


def within(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError("file is outside project root") from error
    if not path.is_file():
        raise ValueError("file does not exist")
    return path


def main() -> int:
    force_utf8_output()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--file", required=True)
    parser.add_argument("--encoding", required=True)
    parser.add_argument("--bom", choices=("require", "forbid"), required=True)
    parser.add_argument("--eol", choices=("lf", "crlf"), required=True)
    parser.add_argument("--baseline", help="pre-edit file snapshot, for allowing unchanged U+FFFD")
    parser.add_argument("--baseline-encoding", help="original encoding when different from target")
    args = parser.parse_args()

    try:
        root = args.root.resolve(strict=True)
        path = within(root, args.file)
        after, has_bom, content = read_text(path, args.encoding)
        if (args.bom == "require") != has_bom:
            raise ValueError(f"expected BOM: {args.bom}")
        if b"\x00" in content:
            raise ValueError("NUL byte in text source")
        check_eol(content, args.eol)
        before = ""
        if args.baseline:
            original = Path(args.baseline).resolve(strict=True)
            before, _, _ = read_text(original, args.baseline_encoding or args.encoding)
        if new_replacement_character(before, after):
            raise ValueError("new U+FFFD replacement character")
    except (OSError, UnicodeError, LookupError, ValueError) as error:
        print(f"[FAIL] {args.file}: {error}", file=sys.stderr)
        return 1

    print(f"[OK] {args.file}: {args.encoding}, BOM={args.bom}, EOL={args.eol}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
