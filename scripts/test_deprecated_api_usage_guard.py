"""Regression tests for the deprecated-API ratchet guard entry point."""
import json

import pytest

from scripts import check_deprecated_api_usage as guard


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "apps/api/app").mkdir(parents=True)
    (tmp_path / "apps/api/tests").mkdir(parents=True)
    return tmp_path


BASELINE = {
    "budgets": {
        "demo": {
            "paths": ["apps/api/app"],
            "pattern": "\\bORJSONResponse\\b",
            "max_occurrences": 1,
            "why": "self-test",
        }
    }
}


def test_under_budget_passes(tree):
    (tree / "apps/api/app/main.py").write_text("x = 1\n", encoding="utf-8")
    assert guard.check(tree, BASELINE) == []


def test_at_budget_passes(tree):
    (tree / "apps/api/app/main.py").write_text("import ORJSONResponse\n", encoding="utf-8")
    assert guard.check(tree, BASELINE) == []


def test_over_budget_fails(tree):
    (tree / "apps/api/app/main.py").write_text(
        "import ORJSONResponse\napp = ORJSONResponse\n", encoding="utf-8"
    )
    failures = guard.check(tree, BASELINE)
    assert len(failures) == 1
    assert "demo" in failures[0]
    assert "main.py:1" in failures[0] and "main.py:2" in failures[0]
    assert "self-test" in failures[0]


def test_shrinking_debt_still_passes(tree):
    target = tree / "apps/api/app/main.py"
    target.write_text("import ORJSONResponse\nimport ORJSONResponse\n", encoding="utf-8")
    assert guard.check(tree, BASELINE)
    target.write_text("import ORJSONResponse\n", encoding="utf-8")
    assert guard.check(tree, BASELINE) == []


def test_generated_trees_are_skipped(tree):
    cache = tree / "apps/api/app/__pycache__"
    cache.mkdir()
    (cache / "main.py").write_text("ORJSONResponse ORJSONResponse\n", encoding="utf-8")
    assert guard.check(tree, BASELINE) == []


def test_single_file_paths_are_supported(tree):
    (tree / "apps/api/pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tree / "apps/api/app").mkdir(parents=True, exist_ok=True)
    baseline = {
        "budgets": {
            "ini": {
                "paths": ["apps/api/pytest.ini"],
                "pattern": "\\[pytest\\]",
                "max_occurrences": 1,
                "why": "self-test",
            }
        }
    }
    assert guard.check(tree, baseline) == []


def test_checked_in_baseline_describes_the_live_tree():
    assert guard.check(guard.ROOT) == []


def test_checked_in_baseline_is_well_formed():
    data = guard.load_baseline()
    assert set(data) >= {"comment", "budgets"}
    for name, rule in data["budgets"].items():
        assert rule["max_occurrences"] >= 0, name
        assert rule["paths"], name
        assert rule.get("why"), name
        # A regex that does not compile would make the rule silently dead.
        import re

        re.compile(rule["pattern"])
    # The baseline must be stable, indented JSON so a diff stays reviewable.
    text = guard.BASELINE.read_text(encoding="utf-8")
    assert text.endswith("\n")
    parsed = json.loads(text)
    assert parsed == json.loads(json.dumps(parsed))
    assert all(
        (len(line) - len(line.lstrip(" "))) % 2 == 0
        for line in text.splitlines()
        if line.strip()
    ), "baseline must use two-space indentation"
