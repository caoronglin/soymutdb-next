"""Keep import capability flags and worker adapters in mechanical agreement.

A capability flag may only claim an import type that has a registered adapter,
and a flag that defaults ON must not be backed by an adapter whose ``run`` is an
unconditional ``UnsupportedImportError``. Conversely, an OFF flag whose adapter
is already a real writer (or a protocol-gated implementation like vcf) is a
review candidate: this test does not forbid it, but it keeps the mismatch
visible instead of letting the flag and the code drift.

The modules are parsed with ``ast`` rather than imported: the plain CI
interpreter has no celery/sqlalchemy, and the contract must run in the smoke
contracts layer.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "apps/api/app/core/features.py"
ADAPTERS = ROOT / "apps/worker/src/soymutdb_worker/tasks/data_adapters.py"

# OFF flags whose adapters are intentionally protocol-gated behind their own
# environment switch (the capability flip alone is not enough). Review-only:
# adding a name here means a human re-read ADR-0005's activation checklist.
PROTOCOL_GATED_OFF_FLAGS = {"imports.vcf"}


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _dict_node(tree: ast.Module, name: str) -> ast.Dict:
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if not any(
            isinstance(target, ast.Name) and target.id == name for target in targets
        ):
            continue
        value = node.value
        if isinstance(value, ast.Dict):
            return value
    raise AssertionError(f"{name} is not a literal dict")


def _literal_dict(tree: ast.Module, name: str) -> dict[str, object]:
    node = _dict_node(tree, name)
    return {
        ast.literal_eval(key): ast.literal_eval(value)
        for key, value in zip(node.keys, node.values)
    }


def _feature_defaults(tree: ast.Module) -> dict[str, bool]:
    node = _dict_node(tree, "FEATURES")
    defaults: dict[str, bool] = {}
    for key, value in zip(node.keys, node.values):
        if isinstance(value, ast.Call) and len(value.args) >= 2:
            defaults[ast.literal_eval(key)] = bool(ast.literal_eval(value.args[1]))
    return defaults


def _adapter_classes(tree: ast.Module) -> dict[str, str]:
    node = _dict_node(tree, "_ADAPTERS")
    registry: dict[str, str] = {}
    for key, value in zip(node.keys, node.values):
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            registry[ast.literal_eval(key)] = value.func.id
    return registry


def _class_definitions(tree: ast.Module) -> dict[str, ast.ClassDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}


def _run_status(class_node: ast.ClassDef) -> str:
    run = next(
        (
            node
            for node in class_node.body
            if isinstance(node, ast.FunctionDef) and node.name == "run"
        ),
        None,
    )
    if run is None:
        return "no_run"
    raises_unsupported = any(
        isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and isinstance(node.exc.func, ast.Name)
        and node.exc.func.id == "UnsupportedImportError"
        for node in ast.walk(run)
    )
    if raises_unsupported:
        return "fail_closed"
    names = {node.id for node in ast.walk(run) if isinstance(node, ast.Name)}
    if "import_vcf" in names:
        return "protocol_gated"
    return "writer"


def test_capability_flags_match_adapter_implementations() -> None:
    features_tree = _module(FEATURES)
    adapters_tree = _module(ADAPTERS)
    defaults = _feature_defaults(features_tree)
    mapping = _literal_dict(features_tree, "IMPORT_TYPE_FEATURES")
    registry = _adapter_classes(adapters_tree)
    classes = _class_definitions(adapters_tree)

    problems: list[str] = []
    for import_type, flag in mapping.items():
        assert isinstance(import_type, str) and isinstance(flag, str)
        default = defaults.get(flag)
        assert default is not None, f"{flag} is missing from FEATURES"
        class_name = registry.get(import_type)
        if class_name is None:
            problems.append(f"{import_type}: no adapter registered for {flag}")
            continue
        status = _run_status(classes[class_name])
        if default and status == "fail_closed":
            problems.append(
                f"{import_type}: {flag} defaults ON but {class_name}.run only raises "
                "UnsupportedImportError"
            )
        if not default and status == "writer" and flag not in PROTOCOL_GATED_OFF_FLAGS:
            problems.append(
                f"{import_type}: {flag} defaults OFF but {class_name}.run is a real "
                "writer; either flip the flag with activation evidence or record the "
                "deferral here"
            )
    assert not problems, "\n".join(problems)


def test_protocol_gated_off_flags_are_still_gated() -> None:
    """An OFF flag listed as protocol-gated must keep its environment switch."""
    adapters_text = ADAPTERS.read_text(encoding="utf-8")
    ingest_text = (
        ROOT / "apps/worker/src/soymutdb_worker/tasks/ingest.py"
    ).read_text(encoding="utf-8")
    for flag in PROTOCOL_GATED_OFF_FLAGS:
        import_type = next(
            key
            for key, value in _literal_dict(_module(FEATURES), "IMPORT_TYPE_FEATURES").items()
            if value == flag
        )
        assert import_type == "vcf"
        assert "import_vcf" in adapters_text
        assert "SOYMUTDB_ENABLE_VCF_IMPORT" in ingest_text
