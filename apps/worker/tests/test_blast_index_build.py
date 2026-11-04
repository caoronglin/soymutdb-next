"""Worker-only index build lifecycle; no mocked BLAST search is claimed here.

The fake binaries mirror the makeblastdb/blastdbcmd interface (as in
test_blast_index.py) and never perform a sequence search. These tests assert
the state-machine, failure cleanup and publication guards. Real binary
acceptance lives in test_blast_index_build_real.py.
"""
from __future__ import annotations

import json
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

from soymutdb_worker.tasks import blast_index as build_module

METADATA = {
    "assembly_id": "GCF_000001735.4", "assembly_version": "TAIR10.1",
    "release_id": "test-release", "annotation_version": "synthetic-v1",
    "source_url": "https://www.ncbi.nlm.nih.gov/nuccore/NC_003070.9",
    "source_version": "NC_003070.9", "license": "CC0-1.0",
}


class _Result:
    def __init__(self, rows, rowcount=1):
        self._rows = rows
        self.rowcount = rowcount

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


def _value(v):
    while hasattr(v, "value") and not isinstance(v, str):
        v = v.value
    return v


class BuildSession:
    """Narrow in-memory mirror of blast_index_builds + catalog publication."""

    def __init__(self, state="pending", *, catalog_status="pending", identity=None):
        self.state = state
        self.catalog_status = catalog_status
        self.identity = identity
        self.updates: list[dict] = []
        self.error = None
        self.transitions: list[tuple[str, str]] = []

    def execute(self, stmt, params=None):
        table = getattr(stmt, "table", None)
        name = getattr(table, "name", None)
        if name == "blast_index_builds" and hasattr(stmt, "_values"):
            values = {getattr(k, "name", k): _value(v)
                      for k, v in dict(stmt._values or {}).items()}
            if values:
                self.updates.append(values)
                if "state" in values:
                    self.transitions.append((self.state, values["state"]))
                    self.state = values["state"]
                if "error_message" in values:
                    self.error = values["error_message"]
                if "index_identity" in values:
                    self.identity = values["index_identity"]
            return _Result([], rowcount=1)
        if name == "blast_databases" and hasattr(stmt, "_values"):
            values = {getattr(k, "name", k): _value(v)
                      for k, v in dict(stmt._values or {}).items()}
            self.updates.append(values)
            if "build_status" in values:
                self.catalog_status = values["build_status"]
            return _Result([], rowcount=1)
        # SELECTs
        text_repr = str(stmt)
        columns = [str(c) for c in getattr(stmt, "_raw_columns", [])]
        if "blast_databases" in text_repr and "SELECT" in text_repr.upper():
            return _Result([(self.catalog_status,)])
        if any("started_at" in c for c in columns):
            from datetime import UTC, datetime

            return _Result([(self.state, datetime.now(UTC))])
        if "blast_index_builds" in text_repr:
            return _Result([(self.state, METADATA, "blast-sources/synthetic.fa",
                             "nucl", self.identity, 1)])
        return _Result([], rowcount=1)


class FakeTask:
    def __init__(self):
        self.states = []

    def update_state(self, **kwargs):
        self.states.append(kwargs)


@contextmanager
def _fake_db(session):
    yield session


@pytest.fixture
def binaries(tmp_path):
    make = tmp_path / "makeblastdb"
    cmd = tmp_path / "blastdbcmd"
    make.write_text(f"#!{sys.executable}\n" + '''import json,pathlib,sys
if sys.argv[1:] == ['-version']:
    print('makeblastdb: 2.17.0+'); raise SystemExit
args=sys.argv[1:]
text=pathlib.Path('input.fasta').read_text()
lengths=[len(r.split('\\n',1)[1].replace('\\n','')) for r in text.split('>')[1:]]
kind=args[args.index('-dbtype')+1]
pathlib.Path('db.'+('nin' if kind=='nucl' else 'pin')).write_text(
    json.dumps({'type':kind,'lengths':lengths}))
''')
    cmd.write_text(f"#!{sys.executable}\n" + '''import json,pathlib,sys
if sys.argv[1:] == ['-version']:
    print('blastdbcmd: 2.17.0+'); raise SystemExit
args=sys.argv[1:]
kind=args[3]
data=json.loads(pathlib.Path('db.'+('nin' if kind=='nucl' else 'pin')).read_text())
if args[4:]==['-info']:
    print(f"{len(data['lengths'])} sequences; {sum(data['lengths'])} total letters")
else:
    print('\\n'.join(map(str,data['lengths'])))
''')
    make.chmod(0o700)
    cmd.chmod(0o700)
    return make, cmd


@pytest.fixture
def setup(monkeypatch, tmp_path, binaries):
    session = BuildSession()
    root = tmp_path / "indexes"
    root.mkdir()
    monkeypatch.setattr(build_module, "INDEX_ROOT", root)
    monkeypatch.setattr(build_module, "MAKEBLASTDB_BIN", binaries[0])
    monkeypatch.setattr(build_module, "BLASTDBCMD_BIN", binaries[1])
    monkeypatch.setattr(build_module, "get_db", lambda: _fake_db(session))
    fasta = ">synthetic\nACGTTGCAACGTTGCA\n"
    monkeypatch.setattr(
        build_module, "_download_source",
        lambda key, destination: (
            destination.write_text(fasta),
            __import__("hashlib").sha256(fasta.encode()).hexdigest(),
        )[1],
    )
    return session, root, fasta


def _call(build_id):
    return build_module.build_index.run.__func__(FakeTask(), build_id=build_id)


def test_build_publishes_only_after_validation_and_cleans_staging(setup, tmp_path):
    session, root, _ = setup
    build_id = str(uuid.uuid4())
    result = _call(build_id)
    assert result["state"] == "published"
    assert len(result["index_identity"]) == 64
    assert session.transitions == [
        ("pending", "building"), ("building", "validating"),
        ("validating", "publishing"), ("publishing", "published"),
    ]
    assert session.catalog_status == "published"
    assert session.error is None
    # Only the published immutable index remains; no staging leaked.
    assert not list(tmp_path.glob(".blast-build-*"))
    assert len(list(root.iterdir())) == 1
    assert (root / result["index_identity"] / "manifest.json").is_file()
    manifest = json.loads((root / result["index_identity"] / "manifest.json").read_text())
    assert manifest["request"]["metadata"] == METADATA


def test_failed_build_records_reason_and_never_publishes(setup, monkeypatch):
    session, root, _ = setup
    build_id = str(uuid.uuid4())

    def fail(*args, **kwargs):
        raise build_module.IndexBuildError("synthetic binary failure")

    monkeypatch.setattr(build_module, "build_immutable_index", fail)
    with pytest.raises(build_module.IndexBuildError):
        _call(build_id)
    assert session.state == "failed"
    assert session.error == "synthetic binary failure"
    assert session.catalog_status == "pending"
    assert list(root.iterdir()) == []
    assert not list(root.parent.glob(".blast-build-*"))


@pytest.mark.parametrize("state", ["building", "validating", "published", "failed", "ready"])
def test_redelivery_never_starts_a_second_builder(setup, monkeypatch, state):
    session, root, _ = setup
    session.state = state
    build_id = str(uuid.uuid4())
    monkeypatch.setattr(
        build_module, "build_immutable_index",
        lambda *a, **k: pytest.fail("redelivery must not rebuild"),
    )
    assert _call(build_id) == {"build_id": build_id, "skipped": True, "state": state}
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("bad", ["", "not-a-uuid", "../etc", "x" * 300])
def test_forged_build_id_is_rejected_before_any_filesystem_work(setup, monkeypatch, bad):
    session, root, _ = setup
    monkeypatch.setattr(
        build_module, "get_db",
        lambda: pytest.fail("invalid build_id must not reach the database"),
    )
    with pytest.raises(build_module.BuildRequestError):
        _call(bad)


def test_source_key_must_stay_under_the_reviewed_prefix(setup, monkeypatch):
    session, root, _ = setup
    monkeypatch.setattr(
        build_module, "_download_source",
        lambda *a, **k: pytest.fail("unreviewed source must not be downloaded"),
    )
    original = build_module._validate_source_key
    assert original("blast-sources/a.fa") == "blast-sources/a.fa"
    for bad in ["data/a.fa", "blast-sources/../etc/passwd", "s3://other/a.fa",
                "blast-sources/a\\b.fa", "blast-sources/a\n.fa"]:
        with pytest.raises(build_module.BuildRequestError):
            original(bad)


def test_error_text_never_leaks_paths_or_child_stderr():
    assert build_module._sanitize_error(
        RuntimeError("/data/blast/private/db.pin failed: <query>ACGT</query>")
    ) == "RuntimeError: index build failed"
    assert build_module._sanitize_error(
        build_module.IndexBuildError("database info count mismatch")
    ) == "database info count mismatch"


@pytest.mark.parametrize("state", ["building", "validating"])
def test_stale_claim_is_closed_explicitly_not_rebuilt(setup, monkeypatch, state):
    from datetime import UTC, datetime, timedelta

    session, root, _ = setup
    session.state = state
    stale = datetime.now(UTC) - timedelta(seconds=7200)

    class StaleSession(BuildSession):
        def execute(self, stmt, params=None):
            columns = [str(c) for c in getattr(stmt, "_raw_columns", [])]
            if any("started_at" in c for c in columns):
                return _Result([(state, stale)])
            return super().execute(stmt, params)

    stale_session = StaleSession(state=state)
    monkeypatch.setattr(build_module, "get_db", lambda: _fake_db(stale_session))
    monkeypatch.setattr(
        build_module, "build_immutable_index",
        lambda *a, **k: pytest.fail("stale claim must never restart a build"),
    )
    build_id = str(uuid.uuid4())
    assert _call(build_id) == {"build_id": build_id, "skipped": True, "state": "failed"}
    assert list(root.iterdir()) == []


def test_rejected_catalog_update_fails_the_build_instead_of_half_publishing(setup, monkeypatch):
    """A catalog UPDATE rejected by the guard must not leave a published build."""
    _, root, _ = setup

    class RejectedCatalogSession(BuildSession):
        """Simulate a concurrent publisher winning the guarded catalog UPDATE."""

        def execute(self, stmt, params=None):
            table = getattr(stmt, "table", None)
            name = getattr(table, "name", None)
            if name == "blast_databases" and hasattr(stmt, "_values"):
                return _Result([], rowcount=0)
            return super().execute(stmt, params)

    session = RejectedCatalogSession()

    @contextmanager
    def reused_db():
        yield session

    monkeypatch.setattr(build_module, "get_db", reused_db)
    build_id = str(uuid.uuid4())

    with pytest.raises(ValueError):
        _call(build_id)

    # The catalog guard runs before the build row is published, so the task's
    # exception handler can close it as failed instead of stranding it in
    # validating/published with an unsearchable index directory.
    assert session.state == "failed"
    assert session.catalog_status != "published"
    assert session.error is not None
    assert list(root.iterdir()) == []
    assert not list(root.parent.glob(".blast-build-*"))


def test_failed_reused_index_is_never_deleted(setup, monkeypatch):
    """A reused identity belongs to another published build and must survive a failure here."""
    _, root, _ = setup
    published = _call(str(uuid.uuid4()))
    directory = root / published["index_identity"]
    assert (directory / "manifest.json").is_file()

    class RejectedCatalogSession(BuildSession):
        def execute(self, stmt, params=None):
            table = getattr(stmt, "table", None)
            if getattr(table, "name", None) == "blast_databases" and hasattr(stmt, "_values"):
                return _Result([], rowcount=0)
            return super().execute(stmt, params)

    session = RejectedCatalogSession()

    @contextmanager
    def reused_db():
        yield session

    monkeypatch.setattr(build_module, "get_db", reused_db)
    with pytest.raises(ValueError, match="catalog row missing or already published"):
        _call(str(uuid.uuid4()))
    # The second attempt reused the existing directory, so it owns nothing to
    # remove. Deleting it here would break the already-published index.
    assert (directory / "manifest.json").is_file()


def test_validation_failure_rolls_back_materialized_index(setup, monkeypatch):
    """A failure after the index dir is materialized must not leave it behind.

    The catalog guard is only one of several post-materialization failure
    points; a source-checksum mismatch during validation takes the same
    cleanup path.
    """
    _, root, _ = setup
    original = build_module.verify_index

    def mismatched(*args, **kwargs):
        result = original(*args, **kwargs)
        result["manifest"]["request"]["source_sha256"] = "0" * 64
        return result

    monkeypatch.setattr(build_module, "verify_index", mismatched)
    with pytest.raises(build_module.BuildRequestError):
        _call(str(uuid.uuid4()))

    assert list(root.iterdir()) == []
    assert not list(root.parent.glob(".blast-build-*"))


def test_skipped_validating_transition_rolls_back_materialized_index(setup, monkeypatch):
    """An early return before publication takes the same cleanup path.

    A guarded transition that loses the race returns ``skipped`` rather than
    raising; the materialized but unpublished index must still be removed.
    """
    _, root, _ = setup

    class StuckBuildingSession(BuildSession):
        def execute(self, stmt, params=None):
            table = getattr(stmt, "table", None)
            if getattr(table, "name", None) == "blast_index_builds" and hasattr(stmt, "_values"):
                values = {getattr(k, "name", k): _value(v)
                          for k, v in dict(stmt._values or {}).items()}
                if values.get("state") == "validating":
                    return _Result([], rowcount=0)
            return super().execute(stmt, params)

    session = StuckBuildingSession()

    @contextmanager
    def reused_db():
        yield session

    monkeypatch.setattr(build_module, "get_db", reused_db)
    result = _call(str(uuid.uuid4()))

    assert result["skipped"] is True
    assert result["state"] == "building"
    assert list(root.iterdir()) == []
    assert not list(root.parent.glob(".blast-build-*"))


def test_cleanup_failure_is_fatal_not_silently_swallowed(setup, monkeypatch):
    """A leftover unpublished index is worse than a build failure: cleanup must die.

    Staging cleanup is best-effort (``ignore_errors=True``), but removing a
    materialized index is strict. If ``rmtree`` fails, the task must raise
    instead of reporting a clean failure while the artifact stays on disk.
    """
    _, root, _ = setup
    real_rmtree = build_module.shutil.rmtree

    def failing_rmtree(target, *args, **kwargs):
        # Fail only for the materialized <identity> directory (64 hex chars).
        # Staging and verification temp dirs must still be cleaned normally.
        if len(Path(target).name) == 64 and not kwargs.get("ignore_errors"):
            raise OSError("synthetic cleanup failure")
        return real_rmtree(target, *args, **kwargs)

    class RejectedCatalogSession(BuildSession):
        def execute(self, stmt, params=None):
            table = getattr(stmt, "table", None)
            if getattr(table, "name", None) == "blast_databases" and hasattr(stmt, "_values"):
                return _Result([], rowcount=0)
            return super().execute(stmt, params)

    session = RejectedCatalogSession()

    @contextmanager
    def reused_db():
        yield session

    monkeypatch.setattr(build_module, "get_db", reused_db)
    monkeypatch.setattr(build_module.shutil, "rmtree", failing_rmtree)

    with pytest.raises(OSError, match="synthetic cleanup failure"):
        _call(str(uuid.uuid4()))

    assert session.state == "failed"
    # The dir survives because cleanup failed: the task died loudly instead of
    # pretending the build was cleanly rolled back.
    assert len(list(root.iterdir())) == 1
