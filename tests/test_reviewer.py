from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.models import OutputType, ProjectBrief, ReviewResult, Session
from agents.reviewer import ReviewAgent


def _make_session(project_dir: str = "/tmp/fake") -> Session:
    brief = ProjectBrief(
        title="Test Project",
        description="A simple test project",
        output_type=OutputType.API,
        tech_stack=[],
        requirements=[],
        project_dir=project_dir,
    )
    return Session(brief=brief)


# ── _parse ────────────────────────────────────────────────────────────────

class TestParse:
    def _agent(self) -> ReviewAgent:
        return ReviewAgent(_make_session())

    def test_clean_json(self):
        agent = self._agent()
        raw = json.dumps({
            "architecture_notes": ["Good separation"],
            "bugs_found": ["Off-by-one in loop"],
            "missing_files": ["tests/"],
            "security_issues": ["No auth middleware"],
            "production_notes": ["Add logging"],
            "severity": "warning",
            "summary": "Minor issues found",
        })
        result = agent._parse(raw)
        assert result.severity == "warning"
        assert result.summary == "Minor issues found"
        assert result.bugs_found == ["Off-by-one in loop"]
        assert result.security_issues == ["No auth middleware"]
        assert result.missing_files == ["tests/"]
        assert result.architecture_notes == ["Good separation"]
        assert result.production_notes == ["Add logging"]

    def test_strips_markdown_fences(self):
        agent = self._agent()
        raw = "```json\n" + json.dumps({"severity": "ok", "summary": "All good"}) + "\n```"
        result = agent._parse(raw)
        assert result.severity == "ok"
        assert result.summary == "All good"

    def test_empty_arrays_default(self):
        agent = self._agent()
        raw = json.dumps({"severity": "ok", "summary": "Clean"})
        result = agent._parse(raw)
        assert result.bugs_found == []
        assert result.security_issues == []
        assert result.missing_files == []

    def test_invalid_json_raises(self):
        agent = self._agent()
        with pytest.raises(json.JSONDecodeError):
            agent._parse("not valid json")


# ── _collect_files ────────────────────────────────────────────────────────

class TestCollectFiles:
    def test_collects_existing_files(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")
        (tmp_path / "models.py").write_text("class Foo: pass", encoding="utf-8")

        session = _make_session(str(tmp_path))
        agent = ReviewAgent(session)
        files = agent._collect_files(tmp_path)

        assert "main.py" in files
        assert "models.py" in files
        assert files["main.py"] == "print('hello')"

    def test_skips_missing_files(self, tmp_path: Path):
        session = _make_session(str(tmp_path))
        agent = ReviewAgent(session)
        files = agent._collect_files(tmp_path)
        assert files == {}

    def test_partial_file_set(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("# main", encoding="utf-8")
        session = _make_session(str(tmp_path))
        agent = ReviewAgent(session)
        files = agent._collect_files(tmp_path)
        assert set(files.keys()) == {"main.py"}

    def test_collects_crud_subdir_files(self, tmp_path: Path):
        (tmp_path / "crud").mkdir()
        (tmp_path / "crud" / "__init__.py").write_text("")
        (tmp_path / "crud" / "expenses.py").write_text("def get(): pass", encoding="utf-8")
        session = _make_session(str(tmp_path))
        agent = ReviewAgent(session)
        files = agent._collect_files(tmp_path)
        assert "crud/expenses.py" in files
        assert "__init__.py" not in " ".join(files.keys())

    def test_collects_routers_subdir_files(self, tmp_path: Path):
        (tmp_path / "routers").mkdir()
        (tmp_path / "routers" / "categories.py").write_text("router = None", encoding="utf-8")
        session = _make_session(str(tmp_path))
        agent = ReviewAgent(session)
        files = agent._collect_files(tmp_path)
        assert "routers/categories.py" in files

    def test_large_file_truncated(self, tmp_path: Path):
        from agents.reviewer import _MAX_FILE_CHARS
        big = "x = 1\n" * (_MAX_FILE_CHARS // 6 + 100)
        (tmp_path / "main.py").write_text(big, encoding="utf-8")
        session = _make_session(str(tmp_path))
        agent = ReviewAgent(session)
        files = agent._collect_files(tmp_path)
        assert len(files["main.py"]) <= _MAX_FILE_CHARS + 80  # cap + truncation note
        assert "truncated" in files["main.py"]


# ── _build_prompt ─────────────────────────────────────────────────────────

class TestBuildPrompt:
    def test_includes_project_title(self):
        session = _make_session()
        agent = ReviewAgent(session)
        prompt = agent._build_prompt({"main.py": "x = 1"})
        assert "Test Project" in prompt

    def test_includes_file_content(self):
        session = _make_session()
        agent = ReviewAgent(session)
        prompt = agent._build_prompt({"main.py": "SECRET = 'abc'"})
        assert "SECRET = 'abc'" in prompt

    def test_includes_all_required_fields(self):
        session = _make_session()
        agent = ReviewAgent(session)
        prompt = agent._build_prompt({"main.py": ""})
        for field in ("architecture_notes", "bugs_found", "missing_files",
                      "security_issues", "production_notes", "severity", "summary"):
            assert field in prompt

    def test_file_tree_injected_when_project_dir_given(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("app = None")
        (tmp_path / "utils.py").write_text("pass")
        session = _make_session(str(tmp_path))
        agent = ReviewAgent(session)
        prompt = agent._build_prompt({"main.py": "app = None"}, project_dir=tmp_path)
        assert "utils.py" in prompt
        assert "do NOT" in prompt  # ground-truth instruction present

    def test_file_tree_absent_without_project_dir(self):
        session = _make_session()
        agent = ReviewAgent(session)
        prompt = agent._build_prompt({"main.py": "app = None"})
        assert "ground truth" not in prompt

    def test_truncation_note_in_prompt(self):
        session = _make_session()
        agent = ReviewAgent(session)
        prompt = agent._build_prompt({"main.py": "x = 1"})
        assert "truncated" in prompt
        assert "cannot verify" in prompt


# ── review() integration (mocked LLM) ────────────────────────────────────

class TestReview:
    def _fake_response(self, severity: str = "ok") -> tuple[str, object]:
        payload = json.dumps({
            "architecture_notes": [],
            "bugs_found": [],
            "missing_files": [],
            "security_issues": [],
            "production_notes": [],
            "severity": severity,
            "summary": "Looks fine.",
        })
        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 50
        return payload, usage

    def test_review_no_files_returns_ok(self, tmp_path: Path):
        session = _make_session(str(tmp_path))
        agent = ReviewAgent(session)
        result = agent.review()
        assert result.severity == "ok"
        assert session.review_result is not None

    def test_review_saves_to_session(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("app = None", encoding="utf-8")
        session = _make_session(str(tmp_path))

        with patch("agents.reviewer.ask_claude", return_value=self._fake_response("warning")) as mock_ask, \
             patch("agents.reviewer.compute_cost", return_value=0.001):
            agent = ReviewAgent(session)
            result = agent.review()

        assert session.review_result is result
        assert result.severity == "warning"
        mock_ask.assert_called_once()

    def test_review_adds_cost_to_session(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("x=1", encoding="utf-8")
        session = _make_session(str(tmp_path))
        initial_cost = session.total_cost_usd

        with patch("agents.reviewer.ask_claude", return_value=self._fake_response()), \
             patch("agents.reviewer.compute_cost", return_value=0.0042):
            ReviewAgent(session).review()

        assert session.total_cost_usd == pytest.approx(initial_cost + 0.0042)

    def test_review_llm_failure_returns_warning(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("x=1", encoding="utf-8")
        session = _make_session(str(tmp_path))

        with patch("agents.reviewer.ask_claude", side_effect=RuntimeError("API down")):
            result = ReviewAgent(session).review()

        assert result.severity == "warning"
        assert "API down" in result.summary
        assert session.review_result is result
