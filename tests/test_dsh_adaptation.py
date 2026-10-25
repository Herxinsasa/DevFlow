"""DSH/Claude adaptation invariants for the shared DevFlow layout."""

from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".agents" / "skills"
REQUIRED_SKILLS = {
    "bug-fixer",
    "code-committer",
    "code-review",
    "code-reviewer",
    "code-tester",
    "design-writer",
    "dev-builder",
    "dev-planner",
    "doc-reviewer",
    "impact-analyzer",
    "implementer",
    "spec-analyzer",
    "test-designer",
    "ui-designer",
}
WORKFLOW_REQUIRED = {
    "code-review": (
        "prompt 第一句",
        "先调用 `skill` 加载",
        "等待子 Agent 完成通知",
        "变更集",
        "基线",
        "主 Agent 不得直接加载",
    ),
    "dev-builder": (
        "prompt 第一句",
        "先调用 `skill` 加载",
        "等待子 Agent 完成通知",
        "send_message",
        "任务包",
        "主 Agent 不得直接加载",
    ),
    "spec-analyzer": (
        "prompt 第一句",
        "先调用 `skill` 加载",
        "用户原始输入原文",
        "等待完成通知",
        "主 Agent 不得直接加载",
    ),
    "design-writer": (
        "prompt 第一句",
        "先调用 `skill` 加载",
        "已确认需求规格和影响面路径",
        "子 Agent 看不到当前会话",
        "等待完成通知",
        "主 Agent 不得直接加载",
    ),
}
ROLE_SKILLS = {"code-reviewer", "doc-reviewer", "implementer"}
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8-sig")
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    if not match:
        raise AssertionError(f"{path}: missing or incomplete frontmatter")
    data: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parsed = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not parsed:
            raise AssertionError(f"{path}: unparsed frontmatter line: {line!r}")
        data[parsed.group(1)] = parsed.group(2).strip()
    return data, text[match.end():]


def skill_files() -> list[Path]:
    return sorted(SKILLS.glob("*/SKILL.md"))


class SkillFormatTests(unittest.TestCase):
    def test_all_skills_have_valid_frontmatter_and_body(self) -> None:
        files = skill_files()
        names = {path.parent.name for path in files}
        self.assertTrue(REQUIRED_SKILLS <= names, f"missing skills: {REQUIRED_SKILLS - names}")
        for path in files:
            with self.subTest(skill=path.parent.name):
                data, body = frontmatter(path)
                self.assertTrue(NAME_RE.match(data.get("name", "")), data.get("name"))
                self.assertEqual(path.parent.name, data["name"])
                self.assertTrue(1 <= len(data.get("description", "")) <= 500)
                self.assertTrue(body.strip())

    def test_role_skills_hide_user_invocation_only(self) -> None:
        for name in ROLE_SKILLS:
            with self.subTest(skill=name):
                data, body = frontmatter(SKILLS / name / "SKILL.md")
                self.assertIn("仅供", data.get("description", ""))
                self.assertIn(data.get("user-invocable", "").lower(), {"false", "no", "off", "0"})
                self.assertIn("## 运行方式", body)
                self.assertIn("subagent", body)
                self.assertIn("主 Agent 不得直接", body)
                # user-invocable only hides /name; it is not a model-side gate.
                self.assertIn("不阻止模型加载", body)
                self.assertIn("不再嵌套", body)

    def test_workflow_skills_use_subagent_dispatch(self) -> None:
        for name, phrases in WORKFLOW_REQUIRED.items():
            with self.subTest(skill=name):
                _, body = frontmatter(SKILLS / name / "SKILL.md")
                for phrase in phrases:
                    self.assertIn(phrase, body, f"{name} is missing {phrase!r}")

    def test_doc_review_dispatch_passes_original_input(self) -> None:
        _, spec = frontmatter(SKILLS / "spec-analyzer" / "SKILL.md")
        _, design = frontmatter(SKILLS / "design-writer" / "SKILL.md")
        self.assertIn("用户原始输入原文", spec)
        self.assertIn("子 Agent 看不到当前会话", design)


class EntryTests(unittest.TestCase):
    def test_agents_md_dsh_contract(self) -> None:
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        for marker in (
            "不使用继承父会话的 `subagent_fork`",
            "没有 `subagent_type`",
            "send_message",
            "子 Agent 看不到父会话",
            "主 Agent 不得直接加载角色 Skill",
            "不阻止模型加载",
            "默认委派深度为 1",
        ):
            self.assertIn(marker, text)
        # Base-profile baseline only; the effective budget is profile-dependent.
        self.assertLess(len((ROOT / "AGENTS.md").read_bytes()), 65536)

    def test_no_skill_uses_subagent_fork(self) -> None:
        for path in skill_files():
            with self.subTest(skill=path.parent.name):
                _, body = frontmatter(path)
                if "subagent_fork" in body:
                    self.assertIn("不使用 `subagent_fork`", body)

    def test_readme_dsh_prerequisites(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("DSH 运行前提", text)
        self.assertIn("安装与升级", text)
        self.assertIn("core.hooksPath", text)
        self.assertIn("不阻止模型加载", text)
        self.assertIn("默认委派深度为 1", text)
        self.assertIn("T0/简单 T1", text)

    def test_no_claude_paths_remain_in_workflow_text(self) -> None:
        paths = [ROOT / "AGENTS.md", ROOT / "README.md", *skill_files()]
        for path in paths:
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertNotIn(".claude/", path.read_text(encoding="utf-8"))


class TemplateTests(unittest.TestCase):
    def test_all_templates_and_constraints_resolve_without_confirmation(self) -> None:
        script = ROOT / ".devflow" / "scripts" / "project_config.py"
        spec = importlib.util.spec_from_file_location("devflow_project_config", script)
        if spec is None or spec.loader is None:
            raise AssertionError("cannot import project_config.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        config = {"templates": {}, "constraints": {}}
        for name in module.TEMPLATES:
            with self.subTest(template=name):
                result = module.resolve(ROOT, config, "template", name)
                self.assertFalse(result["requires_confirmation"], result["warnings"])
        for name in module.CONSTRAINTS:
            with self.subTest(constraint=name):
                result = module.resolve(ROOT, config, "constraint", name)
                self.assertEqual("default", result["mode"])


if __name__ == "__main__":
    unittest.main()
