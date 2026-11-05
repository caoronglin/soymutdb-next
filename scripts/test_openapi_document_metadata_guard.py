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
count, the named regression cases, AND prove the pin itself would go red when
a case disappears (``test_ablation_count_pin_is_not_vacuous``).

Four wiring rows are pinned by name. The decoy-comment row proves the guard
reads the parsed ``FastAPI(...)`` call rather than whole-file text. The
in-scope-binding row proves it goes one step further: ``_kw_expr`` pins only
the *spelling* of the keyword, so binding ``OPENAPI_DESCRIPTION`` /
``OPENAPI_TAGS`` inside ``create_app`` would make the running app publish
different bytes while the call-site text, the module-level literal, the
snapshot and the golden all stay put. The in-place mutation row pins the
complementary class: mutating the module-level object without rebinding makes
``FastAPI(...)`` publish a hollow catalog while every byte stays put. The
symtable-reject row proves a compile error becomes a clean FAIL. The guard
resolves names with the stdlib symbol table; ``test_binding_contract_is_pinned``
fixes what that resolution actually accepts and rejects so the prose cannot
drift into a false map again.
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
SHADOW_LABEL = "description/tags shadowed by in-scope binding"
SHADOW_MUTATOR = "source_wiring_shadowed_by_in_scope_binding"
MUTATION_LABEL = "description/tags mutated in place"
MUTATION_MUTATOR = "source_wiring_mutated_in_place"
UNCOMPILABLE_LABEL = "create_app does not compile under symtable"
UNRUNNABLE_LABEL = "create_app would not run (compiler rejects it)"
TAG_ASSIGNMENT_LABEL = "operation tag assignment permuted"
INFO_SHAPE_LABEL = "phantom info key added"
REQUIRED_ABLATIONS = frozenset(
    (DECOY_LABEL, SHADOW_LABEL, MUTATION_LABEL, UNCOMPILABLE_LABEL,
     TAG_ASSIGNMENT_LABEL, INFO_SHAPE_LABEL)
)
EXPECTED_ABLATIONS = 29


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
    # Each registered label must be driven by its mutator, not a same-named
    # no-op: pin the wiring between label and implementation.
    source = GUARD.read_text(encoding="utf-8")
    assert DECOY_MUTATOR in source
    assert SHADOW_MUTATOR in source
    assert MUTATION_MUTATOR in source
    assert TAG_ASSIGNMENT_LABEL in labels


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


def test_in_scope_binding_of_wiring_names_is_rejected() -> None:
    """A row the old table lacked: pin what the keyword name *resolves to*.

    ``_kw_expr`` proves the FastAPI(...) keyword still reads
    ``OPENAPI_DESCRIPTION`` / ``OPENAPI_TAGS``. It does not prove those names
    still resolve to the locked module-level constants: an in-scope binding in
    ``create_app`` shadows them, so the running app exports different metadata
    while the call-site text, the 1209-char module literal, the snapshot and
    the golden are all untouched. Prove the committed guard (a) rejects that
    mutant, (b) resolves names by scope, not spelling, and (c) would be green
    under a spelling-only guard -- i.e. this test is a load-bearing control,
    not a restatement of ``problems == []``.
    """
    guard = _guard()
    snapshot, generated, golden, main, config, smoke, routers = guard._load()
    injected = (
        '    """Create and configure the FastAPI application."""\n'
        '    OPENAPI_DESCRIPTION = "(rewritten)"\n'
        '    OPENAPI_TAGS = [{"name": "x"}]\n'
        '    app = FastAPI('
    )
    original = '    """Create and configure the FastAPI application."""\n    app = FastAPI('
    mutant = main.replace(original, injected, 1)
    assert mutant != main, "create_app injection anchor changed"

    # (a) The keyword spelling is unchanged and the module literal is intact.
    kwargs = guard._fastapi_kwargs(ast.parse(mutant))
    assert guard._kw_expr(kwargs, "description") == "OPENAPI_DESCRIPTION"
    assert guard._kw_expr(kwargs, "openapi_tags") == "OPENAPI_TAGS"
    facts = guard.source_facts(mutant, config)
    assert len(facts["description"]) == 1209
    assert guard._assignments(ast.parse(mutant)).get("OPENAPI_DESCRIPTION") is not None

    # (b) The scope resolution sees exactly the two shadowed names.
    assert guard._shadowed_wiring_names(main) == []
    assert guard._shadowed_wiring_names(mutant) == ["OPENAPI_DESCRIPTION", "OPENAPI_TAGS"]

    # (c) A spelling-only guard (the pre-fix shape) stays GREEN on this mutant;
    #     only the name-resolution check makes it red. Rebuild that shape on an
    #     in-memory copy so this test cannot pass by trusting the committed code.
    spelling_only = GUARD.read_text(encoding="utf-8").replace(
        "    try:\n"
        "        shadowed = _shadowed_wiring_names(main)\n"
        "    except (SyntaxError, ValueError) as exc:\n"
        "        # ``symtable`` compiles, so it rejects a few shapes ``ast.parse``\n"
        "        # accepts (e.g. duplicate parameters). Report a clean FAIL instead of\n"
        "        # letting the exception escape the guard (the #166 StopIteration class).\n"
        '        found.append(f"main.py does not compile as a metadata source: {exc}")\n'
        "    else:\n"
        "        if shadowed:\n"
        "            found.append(\n"
        '                "create_app() binds metadata names inside its own scope ("\n'
        "                + \", \".join(shadowed)\n"
        '                + "): the FastAPI(...) call would read a different value than "\n'
        '                "the locked module-level constant"\n'
        "            )\n",
        "",
        1,
    )
    assert spelling_only != GUARD.read_text(encoding="utf-8"), "shadow block not found"
    with tempfile.TemporaryDirectory() as tmp:
        regressed_path = Path(tmp) / "check_openapi_document_metadata.py"
        regressed_path.write_text(
            spelling_only.replace(
                "ROOT = Path(__file__).resolve().parents[1]",
                f"ROOT = Path({str(Path(__file__).resolve().parents[1])!r})",
            ),
            encoding="utf-8",
        )
        regressed_guard = _guard(regressed_path)
        assert regressed_guard.failures(
            snapshot, generated, golden, mutant, config, smoke, routers
        ) == [], "spelling-only guard unexpectedly caught the shadow mutant"

    # The committed guard is RED, and self_test() exercises this exact class.
    found = guard.failures(snapshot, generated, golden, mutant, config, smoke, routers)
    assert any("binds metadata names inside its own scope" in item for item in found), found
    problems, ablations, _, labels = guard.self_test()
    assert problems == [], problems
    assert SHADOW_LABEL in labels
    assert ablations == EXPECTED_ABLATIONS

    # The defensive branch is exercised too: a duplicate-parameter create_app
    # (ast.parse-ok, symtable-reject) yields a clean FAIL, not a traceback.
    uncompilable = main.replace(
        "def create_app() -> FastAPI:", "def create_app(x, x) -> FastAPI:", 1
    )
    found = guard.failures(
        snapshot, generated, golden, uncompilable, config, smoke, routers
    )
    assert any("does not compile as a metadata source" in item for item in found), found


def test_in_place_mutation_of_wiring_names_is_rejected() -> None:
    """The complementary hole to rebinding: mutate the constant, keep the name.

    ``_shadowed_wiring_names`` reads the symbol table, which sees only
    *bindings*. ``OPENAPI_TAGS.clear()`` / ``.append(...)`` leaves the binding
    intact but changes the object ``FastAPI(...)`` receives, so the running app
    publishes a hollow catalog while the spelling, the module-level literal,
    the snapshot and the golden are all untouched. Prove (a) the committed
    guard rejects it, (b) a guard with the in-place check stripped stays green,
    and (c) the row is driven by its mutator.
    """
    guard = _guard()
    snapshot, generated, golden, main, config, smoke, routers = guard._load()
    injected = (
        '    """Create and configure the FastAPI application."""\n'
        '    OPENAPI_TAGS.clear()\n'
        '    OPENAPI_TAGS.append({"name": "x", "description": "y"})\n'
        '    app = FastAPI('
    )
    original = '    """Create and configure the FastAPI application."""\n    app = FastAPI('
    mutant = main.replace(original, injected, 1)
    assert mutant != main, "create_app injection anchor changed"

    # (a) The keyword spelling is unchanged and the module literal is intact.
    kwargs = guard._fastapi_kwargs(ast.parse(mutant))
    assert guard._kw_expr(kwargs, "description") == "OPENAPI_DESCRIPTION"
    assert guard._kw_expr(kwargs, "openapi_tags") == "OPENAPI_TAGS"
    assert len(guard._assignments(ast.parse(mutant))["OPENAPI_TAGS"].elts) > 1
    # Scope resolution alone is blind to this shape.
    assert guard._shadowed_wiring_names(mutant) == []
    assert guard._mutated_wiring_names(mutant) == [
        "OPENAPI_TAGS.append()",
        "OPENAPI_TAGS.clear()",
    ]

    # (b) A guard without the in-place check stays GREEN on this mutant.
    source = GUARD.read_text(encoding="utf-8")
    block = (
        '        mutated = _mutated_wiring_names(main)\n'
        '        if mutated:\n'
        '            found.append(\n'
        '                "create_app() mutates metadata constants in place ("\n'
        '                + ", ".join(mutated)\n'
        '                + "): the FastAPI(...) call would read a different value than "\n'
        '                "the locked module-level constant"\n'
        '            )\n'
    )
    assert block in source, "in-place check block not found"
    resolution_only = source.replace(block, "", 1)
    assert resolution_only != source
    with tempfile.TemporaryDirectory() as tmp:
        regressed_path = Path(tmp) / "check_openapi_document_metadata.py"
        regressed_path.write_text(
            resolution_only.replace(
                "ROOT = Path(__file__).resolve().parents[1]",
                f"ROOT = Path({str(Path(__file__).resolve().parents[1])!r})",
            ),
            encoding="utf-8",
        )
        regressed_guard = _guard(regressed_path)
        assert regressed_guard.failures(
            snapshot, generated, golden, mutant, config, smoke, routers
        ) == [], "resolution-only guard unexpectedly caught the mutation mutant"

    # (c) The committed guard is RED and the row is pinned by name.
    found = guard.failures(snapshot, generated, golden, mutant, config, smoke, routers)
    assert any("mutates metadata constants in place" in item for item in found), found
    problems, ablations, _, labels = guard.self_test()
    assert problems == [], problems
    assert MUTATION_LABEL in labels
    assert ablations == EXPECTED_ABLATIONS


def _regressed_guard_source() -> str:
    """Revert the AST wiring judgement to the old substring check and delete
    every wiring ablation added on top of it, on an IN-MEMORY COPY of the
    guard source. This reconstructs the pre-fix world: guard reverted to
    substring + the decoy / shadow / uncompilable cases removed, so the count
    falls back to 22. Nothing is written to the committed file."""
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
    shadow_block = (
        "        (\n"
        '            "description/tags shadowed by in-scope binding",\n'
        "            source_wiring_shadowed_by_in_scope_binding,\n"
        '            "binds metadata names inside its own scope",\n'
        "        ),\n"
    )
    assert shadow_block in source, "shadow ablation tuple not found in guard source"
    source = source.replace(shadow_block, "", 1)
    mutation_block = (
        "        (\n"
        '            "description/tags mutated in place",\n'
        "            source_wiring_mutated_in_place,\n"
        '            "mutates metadata constants in place",\n'
        "        ),\n"
    )
    assert mutation_block in source, "mutation ablation tuple not found"
    source = source.replace(mutation_block, "", 1)
    uncompilable_block = (
        "        (\n"
        '            "create_app does not compile under symtable",\n'
        "            source_wiring_uncompilable,\n"
        '            "does not compile as a metadata source",\n'
        "        ),\n"
    )
    assert uncompilable_block in source, "uncompilable ablation tuple not found"
    source = source.replace(uncompilable_block, "", 1)
    unrunnable_block = (
        "        (\n"
        '            "create_app would not run (compiler rejects it)",\n'
        "            source_wiring_unrunnable,\n"
        '            "would not run",\n'
        "        ),\n"
    )
    assert unrunnable_block in source, "unrunnable ablation tuple not found"
    source = source.replace(unrunnable_block, "", 1)
    tag_assignment_block = (
        "        (\n"
        '            "operation tag assignment permuted",\n'
        "            edit_snapshot(permute_operation_tags),\n"
        '            "published operation tag assignment drifted",\n'
        "        ),\n"
    )
    assert tag_assignment_block in source, "tag assignment ablation not found"
    source = source.replace(tag_assignment_block, "", 1)
    info_shape_block = (
        "        (\n"
        '            "phantom info key added",\n'
        "            edit_snapshot(invented_info_key),\n"
        '            "published info key set drifted",\n'
        "        ),\n"
    )
    assert info_shape_block in source, "info-shape ablation not found"
    source = source.replace(info_shape_block, "", 1)
    # The regressed guard predates the tag-assignment fixed point AND the
    # published ``info`` shape door. Strip both, so the regression really is
    # the historical one and its count really is the historical 22 instead of
    # being propped up by newer cases (which is exactly the vacuity this
    # test exists to catch).
    info_shape_check = source.find(
        "    # 0. Published ``info`` SHAPE. The golden lock below compares"
    )
    if info_shape_check >= 0:
        info_shape_end = source.find("    # 1. Published == golden.", info_shape_check)
        assert info_shape_end > info_shape_check
        source = source[:info_shape_check] + source[info_shape_end:]
    start = source.find("    # 7. The operation -> tag assignment is a fixed point")
    if start >= 0:
        end = source.find("    return found", start)
        assert end > start
        source = source[:start] + source[end:]
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
    assert SHADOW_LABEL not in labels
    assert MUTATION_LABEL not in labels
    assert UNCOMPILABLE_LABEL not in labels
    assert UNRUNNABLE_LABEL not in labels
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


def _inject(main: str, lines: str) -> str:
    """Insert ``lines`` just after ``create_app``'s docstring, before FastAPI()."""
    anchor = '    """Create and configure the FastAPI application."""\n    app = FastAPI('
    injected = (
        '    """Create and configure the FastAPI application."""\n'
        + lines
        + "    app = FastAPI("
    )
    mutant = main.replace(anchor, injected, 1)
    assert mutant != main, "create_app injection anchor changed"
    return mutant


def test_binding_contract_is_pinned() -> None:
    """Pin what the symtable check actually accepts and rejects.

    Prior prose called this "a local rebinding ... before ``FastAPI(...)``" and
    claimed a ``global`` declaration alone is rejected. Neither is true. This
    test is the executable contract, so the wording cannot drift into a false
    map of the guard again. All mutants are built on in-memory bytes.
    """
    guard = _guard()
    snapshot, generated, golden, main, config, smoke, routers = guard._load()

    def fails(src: str) -> list[str]:
        return guard.failures(snapshot, generated, golden, src, config, smoke, routers)

    def is_red(src: str) -> bool:
        return any("binds metadata names inside its own scope" in f for f in fails(src))

    # The watched set is derived from the parsed call, independent of
    # create_app's existence, and includes ``settings`` via title.
    assert guard._watched_names(main) == {
        "OPENAPI_DESCRIPTION",
        "OPENAPI_TAGS",
        "settings",
    }
    assert "settings" in guard._watched_names(
        main.replace("def create_app() -> FastAPI:", "def _retired() -> FastAPI:", 1)
    )

    # RED: a plain local assignment is an in-scope binding.
    assert is_red(_inject(main, '    OPENAPI_DESCRIPTION = "(rewritten)"\n'))
    # RED: ``global`` declaration + assignment binds in this scope too
    # (``is_assigned()`` is true); it is NOT a "local" rebinding.
    assert is_red(
        _inject(
            main,
            "    global OPENAPI_DESCRIPTION\n"
            '    OPENAPI_DESCRIPTION = "(rewritten)"\n',
        )
    )
    # RED: the check is scope-wide, not positional -- even after the call.
    assert is_red(
        main.replace(
            "    return app\n",
            '    OPENAPI_DESCRIPTION = "(rewritten)"\n    return app\n',
            1,
        )
    )
    # RED: ``settings`` is watched via title=settings.app_name.
    assert is_red(
        _inject(main, '    settings = type("S", (), {"app_name": "evil"})()\n')
    )

    # GREEN by design (a bare ``global`` declares an intent but binds nothing).
    assert fails(_inject(main, "    global OPENAPI_DESCRIPTION\n")) == []
    # GREEN: a same-name local in a nested helper is a different scope.
    assert fails(
        _inject(
            main,
            "    def _helper():\n"
            '        OPENAPI_DESCRIPTION = "(helper-local)"\n'
            "        return OPENAPI_DESCRIPTION\n"
            "    _helper()\n",
        )
    ) == []
    # GREEN via a different string: in-place mutation is not a *binding*, so
    # the symbol-table pass stays silent and ``_mutated_wiring_names`` reports
    # it by name. Keeping both assertions here pins that the two checks are
    # distinguishable, so neither can be read as covering the other.
    mutated = _inject(
        main,
        "    OPENAPI_TAGS.clear()\n"
        '    OPENAPI_TAGS.append({"name": "x"})\n',
    )
    assert not is_red(mutated), "in-place mutation must not read as an in-scope binding"
    assert any("mutates metadata constants in place" in item for item in fails(mutated))


def test_operation_tag_assignment_is_an_independent_literal() -> None:
    """A same-multiset tag permutation must move the digest, not the name set."""
    guard = _guard()
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    rows = guard._operation_tag_rows(document)
    original = guard._operation_tag_digest(rows)

    first = second = None
    for item in document["paths"].values():
        for method, operation in item.items():
            if method not in guard.METHODS or not isinstance(operation, dict):
                continue
            if first is None and operation.get("tags") == ["health"]:
                first = operation
            elif second is None and operation.get("tags") == ["auth"]:
                second = operation
    assert first is not None and second is not None
    first["tags"], second["tags"] = second["tags"], first["tags"]

    moved = guard._operation_tag_digest(guard._operation_tag_rows(document))
    assert moved != original
    # Feed the permuted snapshot in with the OLD literal: the drift is named.
    parts = list(guard._load())
    parts[0] = json.dumps(document, ensure_ascii=False)
    found = guard.failures(*parts, tag_digest=original)
    assert any("published operation tag assignment drifted" in f for f in found), found
    # A legitimate same-commit re-pin (snapshot + literal moved together) is
    # green on the same bytes.
    assert not guard.failures(*parts, tag_digest=moved)


def test_published_info_shape_is_an_independent_literal() -> None:
    """The four golden VALUES cannot see a fifth ``info`` key.

    Reproduce the fail-open cell on committed bytes: inject a client-visible
    ``license`` key with the four reviewed values untouched. The old guard
    (byte lock + source lock + generated-half absence) is GREEN on that tree;
    the committed guard is RED and names the shape. Both the shape door and
    the exact count door see the same extra key, so strip BOTH from an
    in-memory copy to prove the ablation goes back to GREEN -- stripping only
    one leaves the other door red. Finally pin that the literal is
    hand-written in the guard source, so a single-file edit cannot delete both
    the door and its own evidence.
    """
    guard = _guard()
    snapshot, generated, golden, main, config, smoke, routers = guard._load()
    document = json.loads(snapshot)
    document["info"]["license"] = {"name": "CC0-1.0", "url": "https://example.invalid"}
    drifted = json.dumps(document, ensure_ascii=False)

    # The four locked values are untouched by construction: no golden, source
    # or generated-half check can fire. Both info-shape doors fire: the set
    # door and the exact count door, on the same extra key.
    found = guard.failures(
        drifted, generated, golden, main, config, smoke, routers
    )
    assert any("published info key set drifted" in item for item in found), found
    assert not any("no longer matches the golden lock" in item for item in found), found

    # Strip BOTH info-shape doors and prove the drifted tree goes green again.
    source = GUARD.read_text(encoding="utf-8")
    door = (
        "        actual_info_keys = frozenset(info)\n"
        "        if actual_info_keys != _INFO_KEYS:\n"
    )
    assert door in source, "shape door not found in committed guard source"
    stripped = source.replace(door, "        if False:\n", 1)
    assert stripped != source
    # The count door independently sees the same drift, so it has to come out
    # too: otherwise "strip the set door" still fails, just from the other
    # door, and this assertion would be measuring the wrong thing.
    count_door = (
        "        if len(info) != _EXPECTED_INFO_KEYS:\n"
        "            found.append(\n"
        "                f\"openapi.json info carries {len(info)} key(s), \"\n"
        "                f\"_EXPECTED_INFO_KEYS pins {_EXPECTED_INFO_KEYS}: a key was \"\n"
        "                \"added or dropped without moving the fixed point\"\n"
        "            )\n"
    )
    assert count_door in source, "count door not found in committed guard source"
    stripped = stripped.replace(count_door, "", 1)
    with tempfile.TemporaryDirectory() as tmp:
        stripped_path = Path(tmp) / "check_openapi_document_metadata.py"
        stripped_path.write_text(
            stripped.replace(
                "ROOT = Path(__file__).resolve().parents[1]",
                f"ROOT = Path({str(Path(__file__).resolve().parents[1])!r})",
            ),
            encoding="utf-8",
        )
        stripped_guard = _guard(stripped_path)
        assert stripped_guard.failures(
            drifted, generated, golden, main, config, smoke, routers
        ) == [], "shape door is not the thing catching the phantom info key"

    # The literal is a module-level frozenset in the guard source, and the
    # self-test case is driven by its named mutator, not a same-named no-op.
    # A derived expectation (recompute the set from the info object under
    # guard) plus a re-pinned count door is the self-agreeing failure this
    # whole guard family exists to kill. Prove the companion's source-literal
    # pin is what stops it: the regressed guard is GREEN on the drifted tree.
    derived = source.replace(
        "        actual_info_keys = frozenset(info)\n"
        "        if actual_info_keys != _INFO_KEYS:",
        "        actual_info_keys = frozenset(info)\n"
        "        if actual_info_keys != frozenset(info):",
        1,
    ).replace("_EXPECTED_INFO_KEYS = 3", "_EXPECTED_INFO_KEYS = 4", 1)
    assert derived != source
    with tempfile.TemporaryDirectory() as tmp:
        derived_path = Path(tmp) / "check_openapi_document_metadata.py"
        derived_path.write_text(
            derived.replace(
                "ROOT = Path(__file__).resolve().parents[1]",
                f"ROOT = Path({str(Path(__file__).resolve().parents[1])!r})",
            ),
            encoding="utf-8",
        )
        assert _guard(derived_path).failures(
            drifted, generated, golden, main, config, smoke, routers
        ) == [], "a derived expectation with a re-pinned count would be vacuous"

    assert "_INFO_KEYS = frozenset(" in source
    assert "_EXPECTED_INFO_KEYS = 3" in source
    assert "invented_info_key" in source
    _problems, ablations, _positives, labels = guard.self_test()
    assert ablations == EXPECTED_ABLATIONS
    assert INFO_SHAPE_LABEL in labels


def test_info_shape_positive_control_stays_green() -> None:
    """A reviewed metadata change re-pins the literal in the same commit.

    The golden lock is a *value* lock; the shape literal is a second, separate
    authority. Prove they are orthogonal: blessing a new ``info`` key in the
    golden file alone (the four values still match, the shape literal does not)
    must stay RED, while re-pinning both the shape set and the count door to
    the new reviewed shape must go GREEN. That is the one deliberate reviewed
    act a legitimate metadata change performs.
    """
    guard = _guard()
    snapshot, generated, golden, main, config, smoke, routers = guard._load()
    document = json.loads(snapshot)
    document["info"]["contact"] = {"name": "SoyMutDB maintainers"}
    drifted = json.dumps(document, ensure_ascii=False)
    blessed_golden = json.dumps(json.loads(golden) | {"contact": "maintainers"}, ensure_ascii=False)

    # Golden-only blessing is NOT enough: the byte lock agrees, the shape does not.
    found = guard.failures(
        drifted, generated, blessed_golden, main, config, smoke, routers
    )
    assert any("published info key set drifted" in item for item in found), found

    # Both literals re-pinned to the new reviewed shape: clean.
    source = GUARD.read_text(encoding="utf-8")
    re_pinned = source.replace(
        '_INFO_KEYS = frozenset({"title", "version", "description"})',
        '_INFO_KEYS = frozenset({"title", "version", "description", "contact"})',
        1,
    ).replace("_EXPECTED_INFO_KEYS = 3", "_EXPECTED_INFO_KEYS = 4", 1)
    assert re_pinned != source
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "check_openapi_document_metadata.py"
        path.write_text(
            re_pinned.replace(
                "ROOT = Path(__file__).resolve().parents[1]",
                f"ROOT = Path({str(Path(__file__).resolve().parents[1])!r})",
            ),
            encoding="utf-8",
        )
        assert _guard(path).failures(
            drifted, generated, blessed_golden, main, config, smoke, routers
        ) == [], "re-pinning both literals should stay green"
