"""Regression tests for the variants row-key source guard.

The guard exists because a stale-base branch reverted both the row key and the
two test cases that would have caught it. Vitest reported 2/2 green and the
OpenAPI gate has no opinion about frontend source, so the co-regression shipped
silently. These tests run against synthetic trees: each negative must fail.
"""
from pathlib import Path

import pytest

from scripts import check_variant_row_key_contract as guard

GOOD_SOURCE = '''
<Table<VariantSummary>
  rowKey={(row) => JSON.stringify([row.variant_id, row.assembly ?? null])}
/>
'''

# PR #99 moved the shipped table to a named `const` function and passes the
# name as `rowKey={rowKey}`. The guard must read that definition, not the
# reference: an attribute alone carries no JSON.stringify of its own.
NAMED_GOOD_SOURCE = '''
const rowKey = (row: VariantSummary) => JSON.stringify([row.variant_id, row.assembly ?? null]);
<Table<VariantSummary> rowKey={rowKey} />
'''

NAMED_BAD_SOURCE = '''
const rowKey = (row: VariantSummary) => `${row.assembly ?? ""}:${row.variant_id}`;
<Table<VariantSummary> rowKey={rowKey} />
'''

MASKED_BAD_SOURCE = '''
const rowKey = (row: VariantSummary) => JSON.stringify([row.variant_id, row.assembly ?? null]);
<Table<VariantSummary> rowKey={(row) => `${row.assembly ?? ""}:${row.variant_id}`} />
'''

UNUSED_NAMED_SOURCE = '''
const rowKey = (row: VariantSummary) => JSON.stringify([row.variant_id, row.assembly ?? null]);
<Table<VariantSummary> dataSource={rows} />
'''


BAD_SOURCE = '''
<Table<VariantSummary>
  rowKey={(row) => `${row.assembly ?? ""}:${row.variant_id}`}
/>
'''

GOOD_TEST = '''
describe("variant row keys", () => {
  it("separates rows that share an identifier and differ in assembly", () => {
    expect(keyOf(row("1", "v4"))).not.toBe(keyOf(row("1", "v5")));
  });
  it("separates an absent assembly from an empty one under a shared identifier", () => {
    expect(keyOf(row("1", null))).not.toBe(keyOf(row("1", "")));
  });
  it("keeps rows that agree on identifier and assembly in one bucket", () => {
    expect(keyOf(row("1", "v4"))).toBe(keyOf(row("1", "v4")));
  });
  it("renders duplicate identifiers without a React duplicate-key warning", () => {
    expect(seenKeys.size).toBe(rows.length);
  });
});
'''

# Emptied bodies keep four green cases while asserting nothing.
HOLLOW_TEST = '''
describe("variant row keys", () => {
  it("separates rows that share an identifier and differ in assembly", () => {});
  it("separates an absent assembly from an empty one under a shared identifier", () => {});
  it("keeps rows that agree on identifier and assembly in one bucket", () => {});
  it("renders duplicate identifiers without a React duplicate-key warning", () => {});
});
'''

SHORT_TEST = '''
describe("variant row keys", () => {
  it("gives every rendered row its own key across assemblies", () => {
    expect(keyOf(row("1", "v4"))).toBeTruthy();
  });
  it("renders duplicate identifiers without a React duplicate-key warning", () => {
    expect(seenKeys.size).toBe(rows.length);
  });
});
'''


@pytest.fixture
def tree(tmp_path):
    return tmp_path


def put(tree: Path, name: str, text: str) -> Path:
    path = tree / name
    path.write_text(text, encoding="utf-8")
    return path


def run(tree: Path, source: str, test: str) -> int:
    return guard.main([
        "--source-path", str(put(tree, "index.tsx", source)),
        "--test-path", str(put(tree, "row-key.test.tsx", test)),
    ])


def test_current_contract_is_accepted(tree):
    assert run(tree, GOOD_SOURCE, GOOD_TEST) == 0


def test_regressed_source_with_matching_short_test_is_rejected(tree, capsys):
    assert run(tree, BAD_SOURCE, SHORT_TEST) == 1
    out = capsys.readouterr().err
    assert "JSON.stringify" in out
    assert "2 cases" in out


def test_regressed_source_alone_is_rejected(tree, capsys):
    assert run(tree, BAD_SOURCE, GOOD_TEST) == 1
    assert "JSON.stringify" in capsys.readouterr().err


def test_short_test_alone_is_rejected(tree, capsys):
    assert run(tree, GOOD_SOURCE, SHORT_TEST) == 1
    out = capsys.readouterr().err
    assert "missing case" in out


def test_missing_test_file_is_rejected(tree, capsys):
    source = put(tree, "index.tsx", GOOD_SOURCE)
    assert guard.main([
        "--source-path", str(source),
        "--test-path", str(tree / "absent.test.tsx"),
    ]) == 1
    assert "missing" in capsys.readouterr().err


def test_hollowed_case_bodies_are_rejected(tree, capsys):
    """Keeping the four names while emptying the bodies must not pass."""
    assert run(tree, GOOD_SOURCE, HOLLOW_TEST) == 1
    out = capsys.readouterr().err
    assert out.count("asserts nothing") == 4


def test_named_const_row_key_is_accepted(tree):
    """The shape shipped by PR #99 must pass; it reddened the gate on live main."""
    assert run(tree, NAMED_GOOD_SOURCE, GOOD_TEST) == 0


def test_regressed_named_const_row_key_is_rejected(tree, capsys):
    assert run(tree, NAMED_BAD_SOURCE, GOOD_TEST) == 1
    assert "JSON.stringify" in capsys.readouterr().err


def test_guard_self_test_covers_both_shapes():
    assert guard.self_test() == 0


def test_good_named_const_cannot_mask_a_bad_inline_attribute(tree, capsys):
    assert run(tree, MASKED_BAD_SOURCE, GOOD_TEST) == 1
    assert "JSON.stringify" in capsys.readouterr().err


def test_unused_named_const_is_not_a_row_key(tree, capsys):
    assert run(tree, UNUSED_NAMED_SOURCE, GOOD_TEST) == 1
    assert "no rowKey expression" in capsys.readouterr().err
