#!/usr/bin/env python3
"""Validate and resolve project-owned DevFlow templates and constraints."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath


TEMPLATES = {
    "requirement_spec": ".claude/skills/spec-analyzer/references/需求规格_模板.md",
    "impact_analysis": ".claude/skills/impact-analyzer/references/影响面分析_模板.md",
    "requirement_design": ".claude/skills/design-writer/references/需求设计_模板.md",
    "overview_design": ".claude/skills/design-writer/references/概要设计_模板.md",
    "interface_contract": ".claude/skills/design-writer/references/接口契约_模板.md",
    "module_design": ".claude/skills/design-writer/references/模块设计_模板.md",
    "architecture": ".claude/skills/design-writer/references/软件架构_模板.md",
    "development_plan": ".claude/skills/dev-planner/references/开发计划_模板.md",
    "repair_batch": ".claude/skills/bug-fixer/references/修复批次_模板.md",
    "code_review": ".claude/skills/code-reviewer/references/代码审查报告_模板.md",
}

CONSTRAINTS = {
    "coding": ".claude/constraints/coding-req.md",
    "logging": ".claude/constraints/log-req.md",
    "document": ".claude/constraints/document-req.md",
    "directory": ".claude/constraints/directory-spec.md",
}

# Only stable workflow anchors are checked here; the authoring Skill checks meaning.
TEMPLATE_ANCHORS = {
    "requirement_spec": (("REQ-",), ("AC-",), ("状态", "Status"), ("来源", "Source")),
    "impact_analysis": (("确认", "Confirmation"), ("结论", "Conclusion"), ("影响", "Impact")),
    "requirement_design": (("状态", "Status"), ("关联需求", "Requirement"), ("验证", "Validation")),
    "overview_design": (("状态", "Status"), ("需求", "Requirement"), ("验证", "Validation")),
    "interface_contract": (("状态", "Status"), ("请求", "Request"), ("响应", "Response"), ("错误", "Error")),
    "module_design": (("职责", "Responsibility"), ("证据", "Evidence")),
    "architecture": (("边界", "Boundary"), ("决策", "Decision")),
    "development_plan": (("TASK-",), ("VERIFY-",), ("状态", "Status"), ("需求覆盖", "Coverage")),
    "repair_batch": (("BUG-",), ("基线", "Baseline"), ("状态", "Status"), ("门禁", "Gate")),
    "code_review": (("结论", "Conclusion"), ("范围", "Scope")),
}


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate config key: {key}")
        result[key] = value
    return result


def project_file(root: Path, value: object) -> tuple[str, str]:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("path must be a non-empty project-relative string")
    if "\\" in value or ":" in value:
        raise ValueError(f"use a project-relative path with '/' separators: {value}")
    relative = PurePosixPath(value)
    if relative.is_absolute() or not relative.parts or any(part in {".", ".."} for part in relative.parts):
        raise ValueError(f"path must stay inside the project: {value}")
    if relative.parts[0] == ".claude":
        raise ValueError(f"project-owned file must be outside managed .claude: {value}")
    resolved_root = root.resolve()
    path = (resolved_root / Path(*relative.parts)).resolve()
    if not path.is_relative_to(resolved_root) or not path.is_file():
        raise ValueError(f"project file is missing or outside the project: {value}")
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError(f"project file is empty: {value}")
    return relative.as_posix(), content


def template_warnings(name: str, path: str, content: str) -> list[str]:
    return [
        f"template {name} ({path}) lacks expected anchor: {' / '.join(alternatives)}; confirm equivalent semantics with the user"
        for alternatives in TEMPLATE_ANCHORS[name]
        if not any(anchor in content for anchor in alternatives)
    ]


def load_config(root: Path) -> dict[str, object]:
    path = root / "devflow.project.json"
    if not path.exists():
        return {"templates": {}, "constraints": {}}
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    if not isinstance(data, dict):
        raise ValueError("devflow.project.json must be an object")
    return data


def constraint_entry(root: Path, name: str, value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"mode", "path"}:
        raise ValueError(f"constraint {name} requires mode and path")
    if not isinstance(value["mode"], str) or value["mode"] not in {"extend", "replace"}:
        raise ValueError(f"constraint {name} mode must be extend or replace")
    project_file(root, value["path"])
    return value


def config_warnings(root: Path, config: dict[str, object]) -> list[str]:
    warnings = [f"unknown config section: {name}" for name in config if name not in {"templates", "constraints"}]
    templates = config.get("templates", {})
    constraints = config.get("constraints", {})
    if not isinstance(templates, dict):
        warnings.append("templates must be an object")
        templates = {}
    if not isinstance(constraints, dict):
        warnings.append("constraints must be an object")
        constraints = {}
    for name, value in templates.items():
        try:
            if name not in TEMPLATES:
                raise ValueError(f"unknown template key: {name}")
            relative, content = project_file(root, value)
            warnings.extend(template_warnings(name, relative, content))
        except (OSError, UnicodeError, ValueError) as exc:
            warnings.append(f"templates.{name}: {exc}")
    for name, value in constraints.items():
        try:
            if name not in CONSTRAINTS:
                raise ValueError(f"unknown constraint key: {name}")
            constraint_entry(root, name, value)
        except (OSError, UnicodeError, ValueError) as exc:
            warnings.append(f"constraints.{name}: {exc}")
    return warnings


def resolve(root: Path, config: dict[str, object], kind: str, name: str) -> dict[str, object]:
    defaults = TEMPLATES if kind == "template" else CONSTRAINTS
    if name not in defaults:
        raise ValueError(f"unknown {kind}: {name}")
    default = defaults[name]
    section = config.get("templates" if kind == "template" else "constraints", {})
    if not isinstance(section, dict):
        raise ValueError(f"{kind} configuration must be an object")
    if name not in section:
        if not (root / default).is_file():
            raise ValueError(f"DevFlow default file is missing: {default}")
        warnings = []
        if kind == "template":
            warnings = template_warnings(name, default, (root / default).read_text(encoding="utf-8"))
        return {"kind": kind, "name": name, "mode": "default", "paths": [default], "warnings": warnings, "requires_confirmation": bool(warnings)}
    configured = section[name]
    if kind == "template":
        relative, content = project_file(root, configured)
        warnings = template_warnings(name, relative, content)
        return {"kind": kind, "name": name, "mode": "replace", "paths": [relative], "warnings": warnings, "requires_confirmation": bool(warnings)}
    entry = constraint_entry(root, name, configured)
    if entry["mode"] == "extend" and not (root / default).is_file():
        raise ValueError(f"DevFlow default file is missing: {default}")
    paths = [entry["path"]] if entry["mode"] == "replace" else [default, entry["path"]]
    return {"kind": kind, "name": name, "mode": entry["mode"], "paths": paths, "warnings": [], "requires_confirmation": False}


def scan_constraints(root: Path) -> list[dict[str, object]]:
    folder = root / ".claude/constraints"
    if not folder.is_dir():
        raise ValueError("DevFlow constraints directory is missing")
    defaults = {path: name for name, path in CONSTRAINTS.items()}
    items = []
    for path in sorted(folder.rglob("*.md")):
        relative = path.relative_to(root).as_posix()
        item = {"path": relative, "title": "", "default_domain": defaults.get(relative)}
        try:
            if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
                raise ValueError("constraint file is outside the project or unreadable")
            lines = path.read_text(encoding="utf-8").splitlines()
            item["title"] = next((line.strip().lstrip("# ").strip() for line in lines if line.strip()), "")
            if not item["title"]:
                raise ValueError("constraint file is empty")
        except (OSError, UnicodeError, ValueError) as exc:
            item["warning"] = str(exc)
        items.append(item)
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="installed target project")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    subparsers.add_parser("scan")
    resolve_parser = subparsers.add_parser("resolve")
    resolve_parser.add_argument("--kind", choices=("template", "constraint"), required=True)
    resolve_parser.add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        if not root.is_dir():
            raise ValueError(f"project directory does not exist: {root}")
        if args.command == "validate":
            warnings = config_warnings(root, load_config(root))
            if warnings:
                print("[WARN] PROJECT CONFIG NEEDS ATTENTION")
                for warning in warnings:
                    print(f"[WARN] {warning}")
            else:
                print("[OK] PROJECT CONFIG VALID" if (root / "devflow.project.json").exists() else "[OK] PROJECT CONFIG DEFAULTS")
        elif args.command == "scan":
            print(json.dumps(scan_constraints(root), ensure_ascii=True))
        else:
            print(json.dumps(resolve(root, load_config(root), args.kind, args.name), ensure_ascii=True))
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"[ERROR] PROJECT CONFIG: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
