"""Collect the OpenAPI document-metadata guard for the contracts smoke layer.

The guard itself is ``scripts/check_openapi_document_metadata.py``, kept
runnable directly (stdlib only) so pre-commit and a bare checkout can use it
without pytest. This module is the thin pytest face: one case on the committed
tree, one case proving the ablations are caught, and one case proving the
catalog-completeness invariant (as opposed to the golden byte lock) is what
closes the three-way bless channel for invented tags.

The ablation-count pin is NOT a ``>=`` floor. A floor from an older world
(``ablations >= 22``) stays green when the one ablation that catches the
AST-vs-substring wiring regression is deleted together with the guard it
protects, because the count merely returns to the old value. Pin the exact
count, the named regression case, AND prove the pin itself would go red when
that case disappears (``test_ablation_count_pin_is_not_vacuous``).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

GUARD = Path(__file__).with_name("check_openapi_document_metadata.py")

# The regression this PR closes: unwiring the real FastAPI kwargs while leaving
# the literals as an inert comment. Only this ablation distinguishes a guard
# that reads the parsed call from one that greps the whole file.
DECOY_LABEL = "description/tags unwired with decoy comment"
DECOY_MUTATOR = "source_wiring_unwired_with_decoy_comment"
REQUIRED_ABLATIONS = frozenset((DECOY_LABEL,))
EXPECTED_ABLATIONS = 23


def _guard(path: Path = GUARD):
    spec = importlib.util.spec_from_file_location("_openapi_document_metadata", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_committed_document_metadata_matches_the_golden() -> None:
    assert _guard().run() == []


def test_every_ablation_is_caught() -> None:
    problems, ablations, positives, labels = _guard().self_test()
    assert problems == [], "\n".join(problems)
    # Exact count, not a floor: 22 (the old world) must not pass as 23.
    assert ablations == EXPECTED_ABLATIONS, ablations
    assert positives >= 1
    # The specific regression, by name, cannot quietly vanish from the table.
    assert REQUIRED_ABLATIONS <= labels, labels - REQUIRED_ABLATIONS
    # The registered label must be driven by the decoy mutator, not a
    # same-named no-op: pin the wiring between label and implementation.
    assert DECOY_MUTATOR in GUARD.read_text(encoding="utf-8")


def test_decoy_wiring_ablation_really_rejects_a_substring_guard() -> None:
    """The decoy case is the ONLY case that separates AST from substring.

    Rebuild the unwired-with-decoy-comment mutant on in-memory bytes and prove
    the committed guard rejects it, while the literals it relies on are present
    ONLY as a comment. This is the live negative control for the named pin: if
    the decoy case is deleted or hollowed, this test fails independently of
    the count pin.
    """
    guard = _guard()
    snapshot, generated, golden, main, config, smoke, routers = guard._load()

    main = main.replace(
        "description=OPENAPI_DESCRIPTION,", 'description="A rewritten description",', 1
    ).replace(
        "openapi_tags=OPENAPI_TAGS,", 'openapi_tags=[{"name": "x", "description": "y"}],', 1
    )
    main = main.replace(
        "    app = FastAPI(",
        "    # description=OPENAPI_DESCRIPTION, openapi_tags=OPENAPI_TAGS,\n"
        "    app = FastAPI(",
        1,
    )
    # The decoy literals are present as whole-file text ...
    assert "description=OPENAPI_DESCRIPTION" in main
    assert "openapi_tags=OPENAPI_TAGS" in main
    # ... but the parsed FastAPI(...) call no longer carries either kwarg.
    kwargs = guard._fastapi_kwargs(ast.parse(main))
    assert guard._kw_expr(kwargs, "description") in (
        "'A rewritten description'", '"A rewritten description"'
    )
    assert guard._kw_expr(kwargs, "openapi_tags") not in (None, "OPENAPI_TAGS")

    found = guard.failures(snapshot, generated, golden, main, config, smoke, routers)
    assert any("OPENAPI_DESCRIPTION as description" in item for item in found), found
    assert any("OPENAPI_TAGS as openapi_tags" in item for item in found), found


def _regressed_guard_source() -> str:
    """Revert the AST wiring judgement to the old substring check and delete
    the decoy ablation, on an IN-MEMORY COPY of the guard source. This is the
    exact regression deepseek materialized on the merge tree: guard reverted +
    new ablation removed. Nothing is written to the committed file."""
    source = GUARD.read_text(encoding="utf-8")
    source = source.replace(
        '        "description_expr": _kw_expr(kwargs, "description"),\n'
        '        "tags_expr": _kw_expr(kwargs, "openapi_tags"),',
        '        "passes_description": "description=OPENAPI_DESCRIPTION" in main,\n'
        '        "passes_tags": "openapi_tags=OPENAPI_TAGS" in main,',
    ).replace(
        '    if facts["description_expr"] != "OPENAPI_DESCRIPTION":',
        '    if not facts["passes_description"]:',
    ).replace(
        '    if facts["tags_expr"] != "OPENAPI_TAGS":',
        '    if not facts["passes_tags"]:',
    )
    block = (
        "        (\n"
        '            "description/tags unwired with decoy comment",\n'
        "            source_wiring_unwired_with_decoy_comment,\n"
        '            "OPENAPI_DESCRIPTION as description",\n'
        "        ),\n"
    )
    assert block in source, "decoy ablation tuple not found in guard source"
    source = source.replace(block, "", 1)
    return source


def test_ablation_count_pin_is_not_vacuous() -> None:
    """Prove the exact-count + named-label pin turns RED on the regression.

    Materialize the failure mode (revert guard to substring + delete the decoy
    ablation), import that regressed guard from a temp file, run its own
    ``self_test()``, and show the new assertions reject it. A ``>= 22`` floor
    would not. The regressed guard lives in a temp dir and reads the committed
    repo bytes via its ROOT, so no committed file is modified.
    """
    committed = _guard()
    clean_problems, clean_ablations, _, clean_labels = committed.self_test()
    assert clean_ablations == EXPECTED_ABLATIONS
    assert clean_problems == []
    assert DECOY_LABEL in clean_labels

    with tempfile.TemporaryDirectory() as tmp:
        regressed_path = Path(tmp) / "check_openapi_document_metadata.py"
        # ROOT is derived from __file__; point the temp copy at the real repo
        # root so _load() reads the committed golden/snapshot/main bytes.
        regressed = _regressed_guard_source()
        regressed = regressed.replace(
            "ROOT = Path(__file__).resolve().parents[1]",
            f"ROOT = Path({str(Path(__file__).resolve().parents[1])!r})",
        )
        regressed_path.write_text(regressed, encoding="utf-8")
        regressed_guard = _guard(regressed_path)
        problems, ablations, _positives, labels = regressed_guard.self_test()

    # The regressed guard's own self-test is green (22 ablations): this is the
    # hole -- a vacuous self-test that no longer exercises the decoy case.
    assert problems == [], problems
    assert ablations == 22, ablations
    assert DECOY_LABEL not in labels
    # The fossil floor would have stayed green:
    assert ablations >= 22
    # The new pin would NOT: both the count and the named-label assertions fire.
    assert ablations != EXPECTED_ABLATIONS
    assert not (REQUIRED_ABLATIONS <= labels)
    assert not (
        ablations == EXPECTED_ABLATIONS and REQUIRED_ABLATIONS <= labels
    )


def test_invented_tag_blessed_in_all_three_artifacts_is_rejected() -> None:
    """The golden lock is green by design on a three-way co-edit; only the
    router-derived completeness invariant can see a tag no router emits."""
    guard = _guard()
    snapshot, generated, golden, main, config, smoke, routers = guard._load()
    entry = {"name": "made-up", "description": "x"}
    main = main.replace(
        "OPENAPI_TAGS = [\n",
        'OPENAPI_TAGS = [\n    {"name": "made-up", "description": "x"},\n',
        1,
    )
    document = json.loads(snapshot)
    document["tags"].insert(0, entry)
    snapshot = json.dumps(document, ensure_ascii=False)
    lock = json.loads(golden)
    lock["tags"].insert(0, entry)
    golden = json.dumps(lock, ensure_ascii=False)

    found = guard.failures(snapshot, generated, golden, main, config, smoke, routers)
    assert any("phantom entries" in item and "made-up" in item for item in found), found
    assert not any("golden lock" in item for item in found), found
