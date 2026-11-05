#!/usr/bin/env python3
"""Every value domain the OpenAPI snapshot publishes must be the one the source declares.

``openapi.json`` and ``openapi.d.ts`` are both exports of ``app.main:app``, so a
guard that compares them to each other proves self-consistency, not truth.
Retype a value domain in the snapshot **and** regenerate the client from that
edited snapshot, and ``scripts/check-contract.sh``'s export==snapshot diff stays
green while the published contract advertises a value the model never declares.
The offline guards that do read the snapshot (#154's 422 guard, #168's body
guard, #169's auth surface, #171's error envelope) all stop at *which* schema a
response names; none of them looks inside a field's value domain.

The authoritative side is the Python source, read here with :mod:`ast`; the
published side is the committed snapshot. Both directions fail: a member the
source declares and the snapshot omits (a regenerated client narrows to a value
the API really sends), and a member the snapshot invents (a client branch for a
value that never arrives). Nothing here restates a member list, so adding a
member to source and snapshot together stays green.

The snapshot has three spellings for one declared ``Literal``, and a guard that
knows only one of them is a guard that mostly passes:

* ``enum`` -- a field the model makes required, or an ``anyOf``/``oneOf`` branch;
* ``const`` -- a single-member ``Literal``, which pydantic folds into a constant;
* ``$defs`` -- pydantic copies any ``$ref``-ed model into the referencing
  schema, so a constrained field can be published twice and the second copy is
  checked here too.

``StrEnum``/``Enum`` classes are read as class bodies and matched to the schema
they become; a class pydantic flattens inline instead of defining is skipped by
name, not by guess. A ``Literal`` whose members are not statically recoverable
(a comprehension over a runtime enum, an ``Annotated``/validator composition) is
reported as unverifiable rather than silently dropped.

Usage:
    python3 scripts/check_openapi_published_enums.py
    python3 scripts/check_openapi_published_enums.py --self-test
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = Path("packages/api-client/openapi.json")
SCHEMA_ROOT = Path("apps/api/app/schemas")

_LITERAL_NAMES = frozenset({"Literal"})
_ENUM_BASES = frozenset({"str", "int", "Enum", "StrEnum", "IntEnum"})
# A member the source declares through a spelling this guard cannot resolve.
UNVERIFIABLE = "<unverifiable>"

# Models whose fields reach the snapshot inline (as a request body) rather than
# as a component of their own. Verified on live `main`: no key of these names
# exists under `components.schemas`, and none of their member values appears
# anywhere else in `openapi.json` either -- so there is nothing published to
# compare against, and saying so is more honest than a green.
INLINED_MODELS = frozenset(
    {
        # Only ever used as a request body; pydantic publishes its fields inline
        # and defines no component. Verified: neither the name nor any of its
        # member values ("performance", "needs-improvement", ...) appears
        # anywhere in the committed openapi.json, so there is nothing published
        # to compare against -- named here rather than counted as a pass.
        "WebVitalEvent",
        # Abstract bases. They are published through their subclasses
        # (`EnrichmentResponse(mode="ora")`, `EnrichmentGseaResponse(mode="gsea")`)
        # and the snapshots of those subclasses ARE compared; pydantic defines no
        # component for the base itself, so its own entry has nothing to check.
        "EnrichmentCalculationResponse",
        "EnrichmentGseaCalculationResponse",
    }
)


class _Unresolvable:
    """A declared value domain the guard cannot turn into a member list."""

    def __init__(self, why: str) -> None:
        self.why = why


EnumSpec = list[Any] | _Unresolvable


def _without_none(members: list[Any]) -> list[Any]:
    """Drop the ``None`` that ``Literal[...] | None`` adds.

    The snapshot publishes an optional field as ``anyOf: [enum, {type: null}]``,
    so ``None`` is the null branch's job and never an enum member. Keeping it in
    the expected set makes every nullable Literal look like a dropped member.
    """
    return [member for member in members if member is not None]


# ---------------------------------------------------------------------------
# Source side
# ---------------------------------------------------------------------------


def _const_value(
    node: ast.AST | None, constants: dict[str, ast.AST], enums: dict[str, list[Any]] | None = None
) -> Any:
    """Resolve a bare name to a module-level constant, or ``UNVERIFIABLE``."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        target = constants.get(node.id)
        if target is None:
            return UNVERIFIABLE
        return _const_value(target, constants, enums)
    if enums is not None:
        enum_name = _all_strings(node)
        if enum_name is not None:
            return enums.get(enum_name, UNVERIFIABLE)
    if isinstance(node, (ast.Tuple, ast.List)):
        out: list[Any] = []
        for element in node.elts:
            value = _const_value(element, constants)
            if value is UNVERIFIABLE:
                return UNVERIFIABLE
            out.append(value)
        return out
    return UNVERIFIABLE


def _flatten(value: Any) -> list[Any]:
    if isinstance(value, (tuple, list)):
        out: list[Any] = []
        for item in value:
            out.extend(_flatten(item))
        return out
    return [value]


def _literal_spec(
    node: ast.AST | None,
    constants: dict[str, ast.AST],
    enums: dict[str, list[Any]] | None = None,
) -> EnumSpec | None:
    """Return the members of a ``Literal[...]`` annotation, ``None`` if it is not one."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _literal_spec(node.left, constants, enums)
        right = _literal_spec(node.right, constants, enums)
        if left is None and right is None:
            return None
        for part in (left, right):
            if isinstance(part, _Unresolvable):
                return part
        return _flatten(left) + _flatten(right)  # type: ignore[operator]
    if isinstance(node, ast.Subscript):
        value = node.value
        if isinstance(value, ast.Name) and value.id in _LITERAL_NAMES:
            elements = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            members: list[Any] = []
            for element in elements:
                resolved = _const_value(element, constants, enums)
                if resolved is UNVERIFIABLE:
                    return _Unresolvable(
                        f"`Literal[{ast.unparse(element)}]` is not a constant this guard "
                        "can resolve statically"
                    )
                members.extend(_flatten(resolved))
            return members
    return None


def _all_strings(node: ast.AST) -> list[str] | None:
    """Recover the string members of a comprehension over an enum class.

    ``AVAILABILITY_LITERALS = tuple(state.value for state in _Availability)`` is
    a spelling the codebase uses for "the literal a client receives". It is
    statically readable: a single generator whose iterable is an enum class with
    constant members. Anything else returns ``None`` so the caller reports it
    rather than guessing.
    """
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
        return None
    if node.func.id not in {"tuple", "list", "frozenset"} or not node.args:
        return None
    generator = node.args[0]
    if not isinstance(generator, ast.GeneratorExp) or len(generator.generators) != 1:
        return None
    comprehension = generator.generators[0]
    if not isinstance(comprehension.iter, ast.Name) or comprehension.ifs:
        return None
    enum_name = comprehension.iter.id
    element = generator.elt
    wanted = None
    if isinstance(element, ast.Attribute) and element.attr == "value":
        if isinstance(element.value, ast.Name) and element.value.id == comprehension.target.id:
            wanted = "value"
    if wanted is None:
        return None
    return enum_name


def _enum_class_spec(node: ast.ClassDef) -> EnumSpec | None:
    """Return the members of an ``Enum`` class body, ``None`` if it is not one."""
    bases = {ast.unparse(base) for base in node.bases}
    if not bases & _ENUM_BASES:
        return None
    members: list[Any] = []
    for statement in node.body:
        value: ast.AST | None = None
        if isinstance(statement, ast.Assign):
            if not all(isinstance(target, ast.Name) for target in statement.targets):
                continue
            value = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            value = statement.value
        else:
            continue
        if not isinstance(value, ast.Constant):
            return _Unresolvable(f"`{node.name}` members are not simple constants")
        members.append(value.value)
    if not members:
        return None
    return members


def _field_map(node: ast.ClassDef, constants: dict[str, ast.AST], enums: dict[str, list[Any]]
) -> dict[str, EnumSpec]:
    fields: dict[str, EnumSpec] = {}
    for statement in node.body:
        if not isinstance(statement, ast.AnnAssign) or not isinstance(statement.target, ast.Name):
            continue
        spec = _literal_spec(statement.annotation, constants, enums)
        if spec is not None:
            fields[statement.target.id] = spec
    return fields


def source_constraints(source_root: Path) -> dict[str, dict[str, EnumSpec]]:
    """Map ``Model -> field -> declared value domain`` across the schema modules."""
    models: dict[str, ast.ClassDef] = {}
    constants: dict[str, ast.AST] = {}
    for path in sorted(source_root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for statement in tree.body:
            if isinstance(statement, ast.ClassDef):
                models[statement.name] = statement
            elif isinstance(statement, ast.Assign):
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = statement.value
            elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                if statement.value is not None:
                    constants[statement.target.id] = statement.value

    enums: dict[str, list[Any]] = {}
    for name, node in models.items():
        if name in constants:
            continue
        spec = _enum_class_spec(node)
        if isinstance(spec, list):
            enums[name] = spec

    constraints: dict[str, dict[str, EnumSpec]] = {}
    for name, node in models.items():
        fields: dict[str, EnumSpec] = {}
        enum_spec = _enum_class_spec(node)
        if enum_spec is not None:
            fields["__enum__"] = enum_spec
        for statement in node.body:
            if not isinstance(statement, ast.AnnAssign) or not isinstance(
                statement.target, ast.Name
            ):
                continue
            spec = _literal_spec(statement.annotation, constants, enums)
            if spec is not None:
                fields[statement.target.id] = spec
        if fields:
            constraints[name] = fields

    # A subclass is published as its own component, so it inherits the literal
    # fields of every base. Without this, `EnrichmentResponse(EnrichmentCalculationResponse)`
    # drops out of the check entirely and nobody notices.
    bases = {name: {ast.unparse(base) for base in node.bases} for name, node in models.items()}
    for _ in range(4):  # depth of the schema hierarchy here is 2; bound the walk
        for name in sorted(models):
            inherited: dict[str, EnumSpec] = {}
            for base in bases[name]:
                inherited.update(constraints.get(base, {}))
            if inheritable := {
                field: spec for field, spec in inherited.items() if field != "__enum__"
            }:
                merged = {**inheritable, **constraints.get(name, {})}
                if merged != constraints.get(name):
                    constraints[name] = merged
    return constraints


# ---------------------------------------------------------------------------
# Published side
# ---------------------------------------------------------------------------


def walk_properties(node: Any, location: str) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield every object carrying ``properties``, including ``$defs`` copies."""
    if isinstance(node, dict):
        if isinstance(node.get("properties"), dict):
            yield location, node
        for key, value in node.items():
            if key == "properties":
                for field, sub in (value or {}).items():
                    yield from walk_properties(sub, f"{location}.{field}")
            elif key == "$defs":
                for defname, sub in (value or {}).items():
                    yield from walk_properties(sub, f"{location}.$defs.{defname}")
            else:
                yield from walk_properties(value, f"{location}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from walk_properties(item, f"{location}[{index}]")


def walk_field_schema(node: Any) -> Iterator[dict[str, Any]]:
    """Yield every dict inside one field schema (in place, so it is mutable)."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_field_schema(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_field_schema(value)


def published_domains(node: Any) -> list[list[Any]]:
    """Collect every value domain inside one field schema, ``enum`` and ``const``."""
    found: list[list[Any]] = []

    def walk(current: Any) -> None:
        if isinstance(current, dict):
            if isinstance(current.get("enum"), list):
                found.append(current["enum"])
            if "const" in current:
                found.append([current["const"]])
            for value in current.values():
                walk(value)
        elif isinstance(current, list):
            for value in current:
                walk(value)

    walk(node)
    return found


def field_domains(schema: dict[str, Any], field: str, label: str) -> list[tuple[str, list[Any]]]:
    out: list[tuple[str, list[Any]]] = []
    for location, node in walk_properties(schema, label):
        properties = node.get("properties")
        if not isinstance(properties, dict) or field not in properties:
            continue
        for domain in published_domains(properties[field]):
            out.append((location, domain))
    return out


def field_domain_nodes(
    schema: dict[str, Any], field: str, label: str
) -> list[tuple[str, dict[str, Any]]]:
    """The ``enum``/``const`` holders themselves, so a mutation lands in place."""
    out: list[tuple[str, dict[str, Any]]] = []
    for location, node in walk_properties(schema, label):
        properties = node.get("properties")
        if not isinstance(properties, dict) or field not in properties:
            continue
        for holder in walk_field_schema(properties[field]):
            if isinstance(holder.get("enum"), list) or "const" in holder:
                out.append((location, holder))
    return out


def _compare(label: str, spec: EnumSpec, published: list[Any]) -> list[str]:
    if isinstance(spec, _Unresolvable):
        return [f"{label}: {spec.why}; widen the guard instead of letting this pass unseen"]
    spec = _without_none(spec)
    missing = [member for member in spec if member not in published]
    invented = [member for member in published if member not in spec]
    problems: list[str] = []
    if missing:
        problems.append(
            f"{label}: source declares {missing!r} but the snapshot publishes only "
            f"{published!r} -- a regenerated client narrows to a value the API really sends"
        )
    if invented:
        problems.append(
            f"{label}: snapshot publishes {invented!r} which the source does not declare "
            f"({spec!r}) -- a client branch for a value that never arrives"
        )
    return problems


def failures(
    document: dict[str, Any], constraints: dict[str, dict[str, EnumSpec]]
) -> tuple[list[str], int]:
    """Return ``(problems, compared_enum_pairs)``."""
    found: list[str] = []
    compared = 0
    components = document.get("components", {}).get("schemas", {})
    enum_classes = [name for name, fields in constraints.items() if "__enum__" in fields]
    # A class pydantic flattens inline never gets its own schema. That is a
    # property of the source, not a regression, so it is skipped by name.
    inline_classes = [name for name in enum_classes if name not in components]

    for model, fields in sorted(constraints.items()):
        if "__enum__" in fields:
            continue
        schema = components.get(model)
        if schema is None:
            # Either pydantic inlines the model (so it publishes no component)
            # or it left the contract. An inline-only model is listed in
            # INLINED_MODELS; everything else is named, never counted as a pass.
            if model not in INLINED_MODELS:
                found.append(
                    f"openapi.json publishes no `{model}`, so its "
                    f"{len(fields)} constrained field(s) cannot be verified"
                )
            continue
        for field, spec in sorted(fields.items()):
            pairs = field_domains(schema, field, model)
            if not pairs:
                found.append(
                    f"{model}.{field}: the source constrains this field but the snapshot "
                    "publishes no `enum` or `const` for it"
                )
                continue
            for location, domain in pairs:
                compared += 1
                found.extend(_compare(f"{location}.{field}", spec, domain))

    for name in enum_classes:
        if name in inline_classes:
            continue
        domains = published_domains(components[name])
        if not domains:
            found.append(f"`{name}` is an enum class but publishes no `enum` or `const`")
            continue
        for domain in domains:
            compared += 1
            found.extend(_compare(name, constraints[name]["__enum__"], domain))

    if compared == 0:
        found.append(
            "nothing was compared: no published value domain matched a declared one"
        )
    return found, compared


def _load(root: Path) -> tuple[dict[str, Any], dict[str, dict[str, EnumSpec]]]:
    document = json.loads((root / SNAPSHOT).read_text(encoding="utf-8"))
    return document, source_constraints(root / SCHEMA_ROOT)


# ---------------------------------------------------------------------------
# Self-test: each ablation must be caught by the check it names
# ---------------------------------------------------------------------------


def _self_test(document: dict[str, Any], constraints: dict[str, dict[str, EnumSpec]]) -> int:
    target = None
    components = document["components"]["schemas"]
    for model, fields in sorted(constraints.items()):
        if "__enum__" in fields or model not in components:
            continue
        for field, spec in sorted(fields.items()):
            if not isinstance(spec, list):
                continue
            if field_domain_nodes(components[model], field, model):
                target = (model, field)
                break
        if target:
            break
    if target is None:
        print("FAIL: self-test found no published value domain to mutate")
        return 1
    model, field = target

    def holder(doc: dict[str, Any]) -> dict[str, Any]:
        return field_domain_nodes(doc["components"]["schemas"][model], field, model)[0][1]

    def _enum_of(node: dict[str, Any]) -> list[Any]:
        # A single-member ``Literal`` is published as ``const``; mutating it as
        # if it were ``enum`` would prove nothing about the real spelling.
        if "const" in node:
            return node["const"]
        return node["enum"]

    def drop_member(doc: dict[str, Any]) -> list[str]:
        node = holder(doc)
        if isinstance(node.get("const"), str):
            # Dropping the only member of a ``const`` means removing the domain.
            node.pop("const")
        else:
            node["enum"].remove(node["enum"][-1])
        return failures(doc, constraints)[0]

    def invent_member(doc: dict[str, Any]) -> list[str]:
        node = holder(doc)
        if isinstance(node.get("const"), str):
            node["enum"] = [node.pop("const"), "__never_declared__"]
        else:
            node["enum"].append("__never_declared__")
        return failures(doc, constraints)[0]

    def retype(doc: dict[str, Any]) -> list[str]:
        node = holder(doc)
        if isinstance(node.get("const"), str):
            node["const"] = "__retyped__"
        else:
            node["enum"][0] = "__retyped__"
        return failures(doc, constraints)[0]

    def retype_const(doc: dict[str, Any]) -> list[str]:
        # A single-member ``Literal`` is published as ``const``, not ``enum``;
        # mutating the wrong spelling proves nothing.
        for name, fields in sorted(constraints.items()):
            schema = doc["components"]["schemas"].get(name)
            if schema is None or "__enum__" in fields:
                continue
            for other, spec in sorted(fields.items()):
                if not isinstance(spec, list) or len(_without_none(spec)) != 1:
                    continue
                nodes = field_domain_nodes(schema, other, name)
                if nodes and "const" in nodes[0][1]:
                    nodes[0][1]["const"] = "__retyped_const__"
                    return failures(doc, constraints)[0]
        return []

    def drop_field(doc: dict[str, Any]) -> list[str]:
        for _, node in walk_properties(doc["components"]["schemas"][model], model):
            if field in node["properties"]:
                node["properties"].pop(field)
                break
        return failures(doc, constraints)[0]

    def drop_model(doc: dict[str, Any]) -> list[str]:
        doc["components"]["schemas"].pop(model, None)
        return failures(doc, constraints)[0]

    def source_adds(doc: dict[str, Any]) -> list[str]:
        mutated = copy.deepcopy(constraints)
        mutated[model][field] = _without_none(mutated[model][field]) + ["__source_only__"]
        return failures(doc, mutated)[0]

    def source_drops(doc: dict[str, Any]) -> list[str]:
        mutated = copy.deepcopy(constraints)
        mutated[model][field] = mutated[model][field][:-1]
        return failures(doc, mutated)[0]

    def source_unresolvable(doc: dict[str, Any]) -> list[str]:
        mutated = copy.deepcopy(constraints)
        mutated[model][field] = _Unresolvable("synthetic unresolvable spelling")
        return failures(doc, mutated)[0]

    def inline_model_still_checked(doc: dict[str, Any]) -> list[str]:
        # Dropping an INLINED_MODELS exemption must be loud, not silent: an
        # exempted model that vanishes from the snapshot without a note is
        # exactly the "counted as a pass" failure this guard exists to avoid.
        mutated = copy.deepcopy(constraints)
        mutated["SyntheticNotPublished"] = {"field": ["x"]}
        return failures(doc, mutated)[0]

    cases = [
        ("published domain drops a declared member", drop_member),
        ("published domain invents a member", invent_member),
        ("published domain retyped wholesale", retype),
        ("single-member Literal published as `const` retyped", retype_const),
        ("published field removed from its model", drop_field),
        ("published model removed", drop_model),
        ("source adds a member the snapshot lacks", source_adds),
        ("source drops a member the snapshot still lists", source_drops),
        ("source spelling the guard cannot resolve", source_unresolvable),
        ("model missing from the snapshot is named", inline_model_still_checked),
    ]

    result = 0
    for label, mutate in cases:
        problems = mutate(copy.deepcopy(document))
        if not problems:
            print(f"FAIL: {label} was not caught")
            result = 1
    clean, _ = failures(document, constraints)
    if clean:
        print("FAIL: clean inputs do not pass")
        for problem in clean:
            print(f"  {problem}")
        result = 1
    if result == 0:
        print(f"OK ({len(cases)} ablations)")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="mutate in-memory copies and prove each ablation is caught",
    )
    args = parser.parse_args(argv)

    try:
        document, constraints = _load(REPO_ROOT)
    except (OSError, json.JSONDecodeError, SyntaxError) as error:
        print(f"FAIL: cannot read the contract inputs: {error}")
        return 1

    if args.self_test:
        return _self_test(document, constraints)

    problems, compared = failures(document, constraints)
    if problems:
        print("FAIL: published value domains no longer match the source:")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(
        f"OK (published value domains pinned, {compared} pair(s) across "
        f"{len(constraints)} model(s))"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
