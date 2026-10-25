from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".claude" / "scripts" / "project_config.py"


class ProjectConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project = Path(self.temp_dir.name) / "project"
        (self.project / ".claude/skills/spec-analyzer/references").mkdir(parents=True)
        (self.project / ".claude/constraints").mkdir(parents=True)
        (self.project / ".claude/skills/spec-analyzer/references/需求规格_模板.md").write_text(
            "状态 来源 REQ-001 AC-001", encoding="utf-8"
        )
        (self.project / ".claude/constraints/coding-req.md").write_text(
            "default", encoding="utf-8"
        )
        (self.project / "templates").mkdir()
        (self.project / "rules").mkdir()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_config(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.project), *args],
            capture_output=True,
            text=True,
        )

    def save_config(self, value: dict) -> None:
        (self.project / "devflow.project.json").write_text(
            json.dumps(value, ensure_ascii=False), encoding="utf-8"
        )

    def test_resolves_project_template_and_constraint_modes(self) -> None:
        (self.project / "templates/spec.md").write_text(
            "状态 来源 REQ-001 AC-001", encoding="utf-8"
        )
        (self.project / "rules/code.md").write_text("项目编码约束", encoding="utf-8")
        self.save_config({
            "templates": {"requirement_spec": "templates/spec.md"},
            "constraints": {"coding": {"mode": "extend", "path": "rules/code.md"}},
        })

        validated = self.run_config("validate")
        self.assertEqual(validated.returncode, 0, validated.stderr)
        template = self.run_config("resolve", "--kind", "template", "--name", "requirement_spec")
        self.assertEqual(template.returncode, 0, template.stderr)
        self.assertEqual(json.loads(template.stdout)["paths"], ["templates/spec.md"])
        coding = self.run_config("resolve", "--kind", "constraint", "--name", "coding")
        self.assertEqual(coding.returncode, 0, coding.stderr)
        self.assertEqual(
            json.loads(coding.stdout)["paths"],
            [".claude/constraints/coding-req.md", "rules/code.md"],
        )

        self.save_config({"constraints": {"coding": {"mode": "replace", "path": "rules/code.md"}}})
        replaced = self.run_config("resolve", "--kind", "constraint", "--name", "coding")
        self.assertEqual(replaced.returncode, 0, replaced.stderr)
        self.assertEqual(json.loads(replaced.stdout)["paths"], ["rules/code.md"])

    def test_template_anchor_warning_and_unusable_selected_path(self) -> None:
        (self.project / "templates/spec.md").write_text("状态 来源 REQ-001", encoding="utf-8")
        self.save_config({"templates": {"requirement_spec": "templates/spec.md"}})
        missing_anchor = self.run_config("resolve", "--kind", "template", "--name", "requirement_spec")
        self.assertEqual(missing_anchor.returncode, 0, missing_anchor.stderr)
        result = json.loads(missing_anchor.stdout)
        self.assertEqual(result["paths"], ["templates/spec.md"])
        self.assertTrue(result["requires_confirmation"])
        self.assertIn("AC-", result["warnings"][0])

        self.save_config({"templates": {"requirement_spec": "../outside.md"}})
        outside = self.run_config("validate")
        self.assertEqual(outside.returncode, 0, outside.stderr)
        self.assertIn("inside the project", outside.stdout)
        selected = self.run_config("resolve", "--kind", "template", "--name", "requirement_spec")
        self.assertEqual(selected.returncode, 2)
        self.assertIn("inside the project", selected.stderr)

        (self.project / "rules/code.md").write_text("项目编码约束", encoding="utf-8")
        self.save_config({"constraints": {"coding": {"mode": ["replace"], "path": "rules/code.md"}}})
        invalid_mode = self.run_config("validate")
        self.assertEqual(invalid_mode.returncode, 0, invalid_mode.stderr)
        self.assertIn("mode must be", invalid_mode.stdout)

    def test_defaults_work_without_project_config(self) -> None:
        result = self.run_config("resolve", "--kind", "template", "--name", "requirement_spec")
        self.assertEqual(result.returncode, 0, result.stderr)
        resolved = json.loads(result.stdout)
        self.assertEqual(resolved["mode"], "default")
        self.assertEqual(resolved["paths"], [".claude/skills/spec-analyzer/references/需求规格_模板.md"])

        default_template = self.project / ".claude/skills/spec-analyzer/references/需求规格_模板.md"
        default_template.write_text("状态 来源 REQ-001", encoding="utf-8")
        invalid = self.run_config("resolve", "--kind", "template", "--name", "requirement_spec")
        self.assertEqual(invalid.returncode, 0, invalid.stderr)
        self.assertTrue(json.loads(invalid.stdout)["requires_confirmation"])

    def test_unrelated_config_issue_does_not_block_selected_template_or_scan(self) -> None:
        self.save_config({
            "templates": {"architecture": "templates/missing.md"},
            "constraints": {"coding": {"mode": "replace", "path": "rules/missing.md"}},
        })
        resolved = self.run_config("resolve", "--kind", "template", "--name", "requirement_spec")
        self.assertEqual(resolved.returncode, 0, resolved.stderr)
        self.assertFalse(json.loads(resolved.stdout)["requires_confirmation"])
        scanned = self.run_config("scan")
        self.assertEqual(scanned.returncode, 0, scanned.stderr)
        self.assertEqual(len(json.loads(scanned.stdout)), 1)
        validated = self.run_config("validate")
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertIn("templates.architecture", validated.stdout)
        self.assertIn("constraints.coding", validated.stdout)
        selected = self.run_config("resolve", "--kind", "constraint", "--name", "coding")
        self.assertEqual(selected.returncode, 2)

        self.save_config({"templates": {}, "constraints": []})
        still_resolves = self.run_config("resolve", "--kind", "template", "--name", "requirement_spec")
        self.assertEqual(still_resolves.returncode, 0, still_resolves.stderr)

        self.save_config({"templates": {"requirement_spec": None}})
        explicit_null = self.run_config("resolve", "--kind", "template", "--name", "requirement_spec")
        self.assertEqual(explicit_null.returncode, 2)

        (self.project / "devflow.project.json").write_text("{invalid", encoding="utf-8")
        scanned_with_invalid_config = self.run_config("scan")
        self.assertEqual(scanned_with_invalid_config.returncode, 0, scanned_with_invalid_config.stderr)

    def test_scan_finds_added_constraint_document(self) -> None:
        added = self.project / ".claude/constraints/safety-rules.md"
        added.write_text("# 安全约束\n适用于接口修改。\n", encoding="utf-8")
        result = self.run_config("scan")
        self.assertEqual(result.returncode, 0, result.stderr)
        items = json.loads(result.stdout)
        self.assertEqual([item["path"] for item in items], [
            ".claude/constraints/coding-req.md",
            ".claude/constraints/safety-rules.md",
        ])
        self.assertEqual(items[0]["default_domain"], "coding")
        self.assertIsNone(items[1]["default_domain"])

        added.write_text("", encoding="utf-8")
        warning_items = json.loads(self.run_config("scan").stdout)
        self.assertIn("empty", warning_items[1]["warning"])


if __name__ == "__main__":
    unittest.main()
