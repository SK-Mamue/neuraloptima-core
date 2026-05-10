from __future__ import annotations

from core.task_generator import SYSTEM_PROMPT


class TestPlannerSystemPrompt:
    def test_forbids_app_slash_prefix(self):
        assert 'NO "app/" package' in SYSTEM_PROMPT or 'NO "app/"' in SYSTEM_PROMPT

    def test_forbids_app_dot_import(self):
        assert '"app."' in SYSTEM_PROMPT or "app." in SYSTEM_PROMPT

    def test_flat_layout_rule_present(self):
        assert "flat layout" in SYSTEM_PROMPT.lower()

    def test_root_is_python_path(self):
        assert "Python path" in SYSTEM_PROMPT

    def test_correct_subdir_examples_present(self):
        assert "routers/" in SYSTEM_PROMPT
        assert "crud/" in SYSTEM_PROMPT

    def test_bare_path_examples_present(self):
        # Must show what correct paths look like, not just what to avoid
        assert "database.py" in SYSTEM_PROMPT
        assert "schemas.py" in SYSTEM_PROMPT

    def test_never_write_app_slash_instruction(self):
        lower = SYSTEM_PROMPT.lower()
        assert "never write" in lower or "never use" in lower
