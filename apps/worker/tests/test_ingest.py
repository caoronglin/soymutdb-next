from contextlib import contextmanager, nullcontext

import pytest

from soymutdb_worker.tasks import ingest
from soymutdb_worker.tasks.data_adapters import AdapterResult, _open_module_source
from soymutdb_worker.tasks.ingest import _pick_mutant_line, _surrogate_id


def test_surrogate_id_is_unsigned_uint32():
    surrogate_id = _surrogate_id("gene-with-a-stable-id")

    assert 0 <= surrogate_id <= 0xFFFFFFFF
    assert surrogate_id == _surrogate_id("gene-with-a-stable-id")


def test_pick_mutant_line_uses_first_non_reference_known_sample():
    sample_names = ["control", "mutant-a", "mutant-b"]

    assert _pick_mutant_line(sample_names, [0, 1, 2], 0) == (
        "mutant-a",
        _surrogate_id("mutant-a"),
        1,
    )
    assert _pick_mutant_line(sample_names, [0, 1, 2], 1) == (
        "mutant-a",
        _surrogate_id("mutant-a"),
        1,
    )


def test_pick_mutant_line_returns_empty_for_missing_or_unknown_samples():
    assert _pick_mutant_line([], [], 0) == ("", 0, -1)
    assert _pick_mutant_line(["unknown"], [3], 0) == ("", 0, -1)


def test_vcf_import_fails_closed_while_flag_is_off(monkeypatch):
    # Contract update (P2-3): the staging/finalize protocol now exists, so the
    # disabled state is no longer "no durable identity" but "gated off until
    # real ClickHouse acceptance". The safety contract is unchanged: with the
    # flag off, import_vcf raises before any ClickHouse access (P1-2 422).
    def fail_if_clickhouse_is_opened():
        pytest.fail("unsafe VCF import reached ClickHouse")

    monkeypatch.setattr(ingest, "get_clickhouse_client", fail_if_clickhouse_is_opened)

    with pytest.raises(RuntimeError, match=r"VCF import is disabled.*PostgreSQL"):
        ingest.import_vcf.run("release-1", "variants.vcf.gz", "assembly-1")


def test_module_import_task_opens_bare_data_key_from_configured_analyses_bucket(monkeypatch):
    """The task path must preserve the bucket resolution used by direct upload."""
    from soymutdb_worker.utils import s3

    opened_paths: list[str] = []

    class Body:
        def close(self) -> None:
            return None

    @contextmanager
    def stream_source(key: str):
        opened_paths.append(key)
        yield Body()

    class SourceCheckingAdapter:
        def run(self, context, *, progress=None):
            with _open_module_source(context):
                pass
            return AdapterResult(records=0, inserted=0, skipped=0, evidence={})

    monkeypatch.setenv("SOYMUTDB_S3_ANALYSES_BUCKET", "module-uploads")
    monkeypatch.setattr(s3, "stream_s3_file", stream_source)
    monkeypatch.setattr(ingest, "import_execution_guard", lambda _id: nullcontext(True))
    monkeypatch.setattr(ingest, "update_import_progress", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ingest, "get_adapter", lambda _kind: SourceCheckingAdapter())

    ingest.run_import_adapter.run(
        1,
        2,
        "module_tsv",
        "1",
        "data/2/immutable-genes.tsv",
        module_key="genes",
        filename="genes.tsv",
    )

    assert opened_paths == ["module-uploads/data/2/immutable-genes.tsv"]
