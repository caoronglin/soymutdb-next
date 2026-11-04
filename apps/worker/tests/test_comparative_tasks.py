"""Worker side of comparative artifacts: frozen input, allowlist, no invention.

The worker is the last place where an alignment could quietly become a
relationship claim, so the tests here are mostly about refusal:

* an unknown method never reaches a subprocess;
* a payload whose member list does not match its frozen hash is rejected
  instead of being labelled with an input it was not computed from;
* a family whose members have no stored residues fails with
  ``no_sequence_store`` rather than aligning placeholders;
* re-delivered messages skip a terminal artifact instead of producing a second
  one.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest

from soymutdb_worker.tasks import comparative as module


class _Result:
    def __init__(self, rows=(), rowcount=1):
        self._rows = list(rows)
        self.rowcount = rowcount

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _Session:
    """Narrow stand-in for the worker's SQLAlchemy Core session."""

    def __init__(self, state="pending", members=None):
        self.state = state
        self.values: list[dict] = []
        self.rows = [("Glyma.01G000100",)]
        #: The frozen member list the row claims it was created with. It must
        #: match the payload hash, otherwise the claim is rejected as a stale
        #: request (which is what the real guard is for).
        self.members = members or ["m1", "m2", "m3"]

    def execute(self, stmt, params=None):
        name = getattr(getattr(stmt, "table", None), "name", None)
        if name == "comparative_artifacts" and hasattr(stmt, "_values"):
            # ``_values`` holds bind parameters, not literals; comparing the
            # criterion to "failed" is only possible after rendering them.
            values = {
                getattr(column, "name", str(column)): getattr(bound, "value", bound)
                for column, bound in dict(stmt._values or {}).items()
            }
            self.values.append(values)
            if "state" in values:
                self.state = values["state"]
            return _Result(rowcount=1)
        if name == "gene_family_members":
            return _Result(self.rows)
        # The claim SELECT.
        return _Result(
            [
                (
                    uuid.uuid4(),
                    self.state,
                    "msa",
                    "mafft",
                    module.input_fingerprint(self.members),
                    list(self.members),
                )
            ]
        )


@contextmanager
def _db(session):
    yield session


def _payload(**overrides):
    members = ["m1", "m2", "m3"]
    payload = {
        "artifact_id": str(uuid.uuid4()),
        "artifact_type": "msa",
        "method": "mafft",
        "input_sha256": module.input_fingerprint(members),
        "member_ids": members,
        "release_id": 7,
        "assembly_id": 1,
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("method", ["", "blastn", "muscle; rm -rf /", "MAFFT"])
def test_unknown_methods_are_refused(method):
    with pytest.raises(module.ArtifactInputError):
        module.validate_payload(_payload(method=method))


def test_input_hash_must_match_the_member_list():
    """A family that changed after the request is not silently re-labelled."""
    payload = _payload(input_sha256="b" * 64)
    with pytest.raises(module.ArtifactInputError, match="hash"):
        module.validate_payload(payload)


def test_tree_requires_at_least_three_members():
    """Two sequences give a distance, not a phylogeny."""
    members = ["m1", "m2"]
    with pytest.raises(module.ArtifactInputError, match="three"):
        module.validate_payload(
            _payload(
                artifact_type="tree",
                method="iqtree",
                member_ids=members,
                input_sha256=module.input_fingerprint(members),
            )
        )


def test_member_ceiling_is_enforced():
    members = [f"m{i}" for i in range(module.MAX_MEMBERS + 1)]
    with pytest.raises(module.ArtifactInputError, match="exceeds"):
        module.validate_payload(
            _payload(member_ids=members, input_sha256=module.input_fingerprint(members))
        )


def test_fingerprint_matches_the_api_side():
    """The API and the worker must compute byte-identical hashes.

    The API module is imported by file rather than through ``app.*``: the worker
    environment does not install the API's own dependencies, and the two hash
    implementations are what must agree, not the two applications.
    """
    from pathlib import Path

    source = Path(__file__).resolve().parents[3] / "apps/api/app/services/comparative_service.py"
    tree = source.read_text(encoding="utf-8")
    # Extract the function body and execute it standalone: importing the module
    # would pull SQLAlchemy models and the API settings stack for one hash.
    namespace: dict = {"hashlib": __import__("hashlib")}
    start = tree.index("def input_fingerprint(")
    end = tree.index("class ComparativeService")
    exec(compile(tree[start:end], str(source), "exec"), namespace)  # noqa: S102
    api_fingerprint = namespace["input_fingerprint"]

    assert api_fingerprint(["a", "b"]) == module.input_fingerprint(["a", "b"])
    assert api_fingerprint(["b", "a"]) != module.input_fingerprint(["a", "b"])


@pytest.mark.parametrize(
    ("method", "artifact_type"),
    [
        ("mafft", "tree"),
        ("muscle", "tree"),
        ("iqtree", "msa"),
        ("fasttree", "msa"),
    ],
)
def test_a_tool_cannot_produce_the_wrong_artifact_kind(method, artifact_type):
    from pathlib import Path

    with pytest.raises(module.ArtifactInputError):
        module.build_command(method, artifact_type, Path("in.fasta"), Path("."))


def test_commands_are_argument_arrays_never_shell_strings():
    from pathlib import Path

    command = module.build_command("mafft", "msa", Path("/tmp/members.fasta"), Path("/tmp"))
    assert isinstance(command, list)
    assert command[0] == "mafft"
    assert not any(";" in part or "|" in part for part in command)


def test_terminal_artifacts_are_not_rebuilt(monkeypatch):
    session = _Session(state="succeeded")

    @contextmanager
    def _guarded():
        yield session

    monkeypatch.setattr(module, "get_db", _guarded)
    monkeypatch.setattr(
        module, "_run", lambda *a, **k: pytest.fail("a terminal artifact must not rerun")
    )
    result = module.build_artifact.run.__func__(  # type: ignore[attr-defined]
        type("Task", (), {"request": None})(), {"payload": _payload()}
    )
    assert result == {"artifact_id": result["artifact_id"], "skipped": True}


def test_missing_residues_fail_instead_of_aligning_placeholders(monkeypatch):
    """The platform stores coordinates, not residues.

    Ablation: inventing placeholder sequences would publish an alignment that
    is not an alignment of anything.
    """
    session = _Session()

    @contextmanager
    def _guarded():
        yield session

    monkeypatch.setattr(module, "get_db", _guarded)
    monkeypatch.setattr(module, "_member_sequences", lambda *a, **k: {})
    monkeypatch.setattr(
        module, "_run", lambda *a, **k: pytest.fail("nothing to align must not run a tool")
    )
    with pytest.raises(module.ArtifactInputError, match="no_sequence_store"):
        module.build_artifact.run.__func__(  # type: ignore[attr-defined]
            type("Task", (), {"request": None})(), {"payload": _payload()}
        )
    assert any(value.get("state") == "failed" for value in session.values)


def test_payload_must_come_from_the_outbox_shape():
    with pytest.raises(module.ArtifactInputError):
        module.build_artifact.run.__func__(  # type: ignore[attr-defined]
            type("Task", (), {"request": None})(), {}
        )


def test_task_is_registered_on_the_analyses_queue():
    from soymutdb_worker.main import celery_app

    celery_app.loader.import_task_module("soymutdb_worker.tasks.comparative")
    assert module.COMPARATIVE_ARTIFACT_TASK in celery_app.tasks
    assert celery_app.conf.task_routes["soymutdb_worker.tasks.comparative.*"] == {
        "queue": "analyses"
    }
