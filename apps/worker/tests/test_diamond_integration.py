"""DIAMOND is the only aligner: index, flag, parser and persistence contracts.

Engine selection no longer exists, so these tests assert what used to be
routing decisions — that there is nothing left to route to — plus the flag and
index contracts a fake subprocess cannot prove.
"""

from __future__ import annotations

import os
import random
import shutil
import subprocess
from pathlib import Path

import pytest
from soymutdb_jobs.protein_fasta import ProteinFastaError, parse_protein_fasta

from soymutdb_worker.tasks import blast
from tests.test_blast_task import FakeSession, FakeTask, _call_task, _fake_db, _payload

# Real hit-finding needs realistic lengths; a 21 aa protein is below the
# shortest reportable HSP, so a passing flag check would prove nothing.
PROTEIN = "M" + "".join(random.Random(17).choices("ACDEFGHIKLMNPQRSTVWY", k=199))


def _installed(tmp_path, name="diamond"):
    """An executable stand-in: existence alone must not be enough."""
    binary = tmp_path / name
    binary.touch()
    binary.chmod(0o755)
    return binary


def _command(params, *, num_threads=4):
    return blast.build_diamond_command(
        "blastp", Path("db"), Path("query.fa"), Path("out.tsv"), 1e-10, 1, num_threads, params
    )


def _index(tmp_path, name, *, size=64):
    (tmp_path / f"{name}.dmnd").write_bytes(b"x" * size)


@pytest.mark.parametrize("program", ["blastn", "blastx", "tblastn", "tblastx", "megablast", ""])
def test_only_protein_protein_is_executable(program):
    with pytest.raises(ValueError, match="Unsupported program"):
        blast.validate_program(program)


def test_diamond_executes_blastp_only():
    """DIAMOND stays protein-only; the union includes NCBI's nucleotide programs."""
    assert blast.ENGINE_PROGRAMS["diamond"] == frozenset({"blastp"})
    assert blast.DIAMOND_PROGRAMS == frozenset({"blastp"})
    assert blast.validate_program("blastp") == "blastp"
    assert blast.validate_program("blastp", "diamond") == "blastp"
    for program in ("blastn", "blastx", "tblastn", "tblastx"):
        assert program in blast.ENGINE_PROGRAMS["ncbi_blast"]
        assert blast.validate_program(program, "ncbi_blast") == program
        # The DIAMOND runner must never accept a nucleotide program.
        with pytest.raises(ValueError, match="Unsupported program"):
            blast.validate_program(program, "diamond")


def test_run_blast_command_rejects_a_non_blastp_program(monkeypatch, tmp_path):
    monkeypatch.setattr(blast, "DIAMOND_BIN", _installed(tmp_path))
    with pytest.raises(ValueError, match="Unsupported program"):
        blast.run_blast_command("tblastn", tmp_path / "db", tmp_path / "q", tmp_path / "o")


def test_the_blast_binary_is_not_consulted(monkeypatch, tmp_path):
    """A missing DIAMOND must fail loudly rather than reach for NCBI BLAST."""
    monkeypatch.setattr(blast, "DIAMOND_BIN", tmp_path / "absent")
    with pytest.raises(RuntimeError, match="not found or not executable"):
        blast._require_diamond()


@pytest.mark.parametrize("kind", ["directory", "non_executable", "missing"])
def test_a_present_but_unusable_diamond_is_rejected(monkeypatch, tmp_path, kind):
    binary = tmp_path / "diamond"
    if kind == "directory":
        binary.mkdir()
    elif kind == "non_executable":
        binary.touch()
    else:
        binary = tmp_path / "elsewhere"
    monkeypatch.setattr(blast, "DIAMOND_BIN", binary)
    with pytest.raises(RuntimeError, match="not found or not executable"):
        blast._require_diamond()


def test_engine_is_not_negotiable(monkeypatch, tmp_path):
    monkeypatch.setattr(blast, "DIAMOND_BIN", tmp_path / "absent")
    with pytest.raises(ValueError, match="Unknown aligner"):
        blast.run_blast_command("blastp", Path("d"), Path("q"), Path("o"), engine="blast")
    # auto is tolerated only so a payload queued before the reduction loads;
    # it still cannot conjure a second engine.
    with pytest.raises(RuntimeError, match="not found or not executable"):
        blast.run_blast_command("blastp", Path("d"), Path("q"), Path("o"), engine="auto")


def test_no_blast_only_symbols_remain():
    """The retired engine must not linger as a second owner."""
    for gone in (
        "resolve_engine",
        "resolve_search",
        "parse_blast_json",
        "validate_parameters",
        "ALLOWED_PARAMS",
        "BLAST_BIN_DIR",
        "BLAST_ENGINE",
    ):
        assert not hasattr(blast, gone), f"{gone} still exists after retirement"


def test_word_size_is_rejected_rather_than_ignored(monkeypatch, tmp_path):
    monkeypatch.setattr(blast, "DIAMOND_BIN", _installed(tmp_path))
    with pytest.raises(ValueError, match="retired NCBI BLAST option"):
        blast.run_blast_command(
            "blastp", tmp_path / "d", tmp_path / "q", tmp_path / "o", word_size=11
        )


def test_outfmt_cannot_be_overridden(monkeypatch, tmp_path):
    monkeypatch.setattr(blast, "DIAMOND_BIN", _installed(tmp_path))
    with pytest.raises(ValueError, match="outfmt is fixed"):
        blast.run_blast_command("blastp", tmp_path / "d", tmp_path / "q", tmp_path / "o", outfmt=5)


@pytest.mark.parametrize(
    "key", ["dust", "soft_masking", "word_size", "num_threads", "reward", "lcase_masking"]
)
def test_ncbi_only_parameters_are_rejected_by_the_worker(key):
    with pytest.raises(ValueError, match="Disallowed DIAMOND parameter"):
        blast.validate_diamond_parameters({key: "1"})


def test_id_and_quiet_have_the_verified_arity():
    cmd = _command({"id": 30, "quiet": True})
    assert cmd[cmd.index("--id") + 1] == "30"
    assert "--quiet" in cmd
    assert "--quiet=1" not in cmd and "--quiet true" not in cmd


def test_quiet_false_emits_nothing():
    assert "--quiet" not in _command({"quiet": False})


@pytest.mark.parametrize("value", [-1, 101, "nan", "inf", float("nan"), float("inf"), True])
def test_id_must_be_a_finite_percentage(value):
    with pytest.raises(ValueError, match=r"id must be a percentage"):
        blast.validate_diamond_parameters({"id": value})


def test_quiet_must_be_boolean():
    with pytest.raises(ValueError, match="quiet must be a boolean"):
        blast.validate_diamond_parameters({"quiet": "yes"})


def test_command_pins_twelve_columns_and_one_bin():
    cmd = _command({})
    fmt = cmd.index("--outfmt")
    assert cmd[fmt + 1] == "6"
    assert cmd[fmt + 2 : fmt + 14] == list(blast.DIAMOND_OUTFMT6_COLUMNS)
    # 2.1.14 reserves ~1 GiB per hit buffer; one bin fits the 4 GiB budget.
    assert cmd[cmd.index("--bin") + 1] == "1"


def test_no_primary_flag_is_emitted_twice():
    cmd = _command({"evalue": 1e-3, "max_target_seqs": 5, "threads": 2})
    for flag in ("--evalue", "--max-target-seqs", "--threads"):
        assert cmd.count(flag) == 1, flag
    assert cmd[cmd.index("--evalue") + 1] == "0.001"
    assert cmd[cmd.index("--max-target-seqs") + 1] == "5"
    assert cmd[cmd.index("--threads") + 1] == "2"


@pytest.mark.parametrize("value", [0, -1, 10_000, "0", "-1", "many", 1.5, True, None])
def test_thread_budget_rejects_unusable_values(value):
    with pytest.raises(ValueError, match="threads"):
        blast._positive_threads(value)


def test_parameter_threads_may_lower_but_not_raise_the_budget():
    assert blast._thread_budget(4, {"threads": "2"}, "threads") == 2
    assert blast._thread_budget(4, {}, "threads") == 4
    with pytest.raises(ValueError, match="exceeds submitted thread budget"):
        blast._thread_budget(1, {"threads": 3}, "threads")


def test_deployment_thread_ceiling_is_enforced(monkeypatch):
    monkeypatch.setattr(blast, "MAX_THREADS", 8)
    assert blast._positive_threads(8) == 8
    with pytest.raises(ValueError, match="BLAST_MAX_THREADS=8"):
        blast._positive_threads(9)


def test_command_emits_one_thread_flag_under_both_owners():
    assert _command({"threads": 2}).count("--threads") == 1
    with pytest.raises(ValueError, match="threads must be between 1 and"):
        _command({"threads": 10_000})


def test_versioned_basename_is_preserved(monkeypatch, tmp_path):
    _index(tmp_path, "wm82.a2.v1")
    monkeypatch.setattr(blast, "BLAST_DATABASE_PATHS", {"wm82.a2.v1": str(tmp_path / "wm82.a2.v1")})
    assert blast.get_blast_db_path("wm82.a2.v1") == tmp_path / "wm82.a2.v1"


def test_a_makeblastdb_product_is_not_accepted(monkeypatch, tmp_path):
    for suffix in (".pin", ".phr", ".psq"):
        (tmp_path / f"wm82.a2.v1{suffix}").write_text("index")
    monkeypatch.setattr(blast, "BLAST_DATABASE_PATHS", {"wm82.a2.v1": str(tmp_path / "wm82.a2.v1")})
    with pytest.raises(blast.DatabaseIndexUnavailable):
        blast.get_blast_db_path("wm82.a2.v1")


def test_a_zero_length_index_is_not_ready(monkeypatch, tmp_path):
    _index(tmp_path, "wm82.a2.v1", size=0)
    monkeypatch.setattr(blast, "BLAST_DATABASE_PATHS", {"wm82.a2.v1": str(tmp_path / "wm82.a2.v1")})
    with pytest.raises(blast.DatabaseIndexUnavailable):
        blast.get_blast_db_path("wm82.a2.v1")


def test_cached_index_is_reused_without_touching_s3(monkeypatch, tmp_path):
    _index(tmp_path, "williams82_prot")
    monkeypatch.setattr(blast, "BLAST_DATABASE_PATHS", {})
    monkeypatch.setattr(blast, "BLAST_CACHE_DIR", tmp_path)

    def no_s3(*args, **kwargs):
        raise AssertionError("S3 must not be contacted for a cached index")

    monkeypatch.setattr(blast, "get_s3_client", no_s3)
    assert blast.get_blast_db_path("williams82_prot") == tmp_path / "williams82_prot"


def _fake_s3(monkeypatch, keys, payload=b"index", log=None):
    log = [] if log is None else log

    class _S3:
        class _Paginator:
            def paginate(self, Bucket, Prefix):
                return [{"Contents": [{"Key": k} for k in keys]}]

        def get_paginator(self, name):
            return self._Paginator()

        def download_file(self, bucket, key, dest):
            log.append(key)
            Path(dest).write_bytes(payload)

    monkeypatch.setattr(blast, "get_s3_client", lambda: _S3())
    return log


def test_s3_download_accepts_only_the_exact_dmnd_name(monkeypatch, tmp_path):
    monkeypatch.setattr(blast, "BLAST_DATABASE_PATHS", {})
    monkeypatch.setattr(blast, "BLAST_CACHE_DIR", tmp_path)
    log = _fake_s3(monkeypatch, ["blast-dbs/williams82_prot.pin", "blast-dbs/williams82_prot.dmnd"])
    assert blast.get_blast_db_path("williams82_prot") == tmp_path / "williams82_prot"
    assert log == ["blast-dbs/williams82_prot.dmnd"]


def test_wrong_format_after_download_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(blast, "BLAST_DATABASE_PATHS", {})
    monkeypatch.setattr(blast, "BLAST_CACHE_DIR", tmp_path)
    _fake_s3(monkeypatch, ["blast-dbs/williams82_prot.dmnd"], payload=b"")
    with pytest.raises(blast.DatabaseIndexUnavailable):
        blast.get_blast_db_path("williams82_prot")


def test_an_interrupted_download_publishes_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(blast, "BLAST_DATABASE_PATHS", {})
    monkeypatch.setattr(blast, "BLAST_CACHE_DIR", tmp_path)

    class _S3:
        class _Paginator:
            def paginate(self, Bucket, Prefix):
                return [{"Contents": [{"Key": "blast-dbs/williams82_prot.dmnd"}]}]

        def get_paginator(self, name):
            return self._Paginator()

        def download_file(self, bucket, key, dest):
            raise RuntimeError("connection reset")

    monkeypatch.setattr(blast, "get_s3_client", lambda: _S3())
    with pytest.raises(RuntimeError):
        blast.get_blast_db_path("williams82_prot")
    assert not (tmp_path / "williams82_prot.dmnd").exists()
    assert not list(tmp_path.glob("tmp*"))


def test_unlisted_database_is_rejected_before_any_io(monkeypatch, tmp_path):
    monkeypatch.setattr(blast, "BLAST_DATABASE_PATHS", {"wm82.a2.v1": str(tmp_path)})

    def no_s3(*args, **kwargs):
        raise AssertionError("whitelist must reject before S3")

    monkeypatch.setattr(blast, "get_s3_client", no_s3)
    with pytest.raises(ValueError, match="not in the allowed database"):
        blast.get_blast_db_path("other")


def test_invalid_database_paths_setting_fails_at_import():
    assert blast.load_database_paths('{"a": "b"}') == {"a": "b"}
    for bad in ("", "not json", "[]", '{"": "b"}', '{"a": ""}', '{"a": 1}'):
        with pytest.raises(ValueError, match="BLAST_DATABASE_PATHS"):
            blast.load_database_paths(bad)


def test_task_uses_one_engine_for_index_command_and_parser(monkeypatch, tmp_path):
    _index(tmp_path, "williams82_prot")
    monkeypatch.setattr(
        blast, "BLAST_DATABASE_PATHS", {"williams82_prot": str(tmp_path / "williams82_prot")}
    )
    monkeypatch.setattr(blast, "BLAST_CACHE_DIR", tmp_path)
    monkeypatch.setattr(blast, "DIAMOND_BIN", _installed(tmp_path))
    monkeypatch.setattr(blast, "upload_file", lambda *a, **k: None)
    monkeypatch.setattr(blast, "generate_presigned_url", lambda *a, **k: "https://s3.example/x")

    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        Path(cmd[cmd.index("--out") + 1]).write_text(
            "query\tsubject\t100.0\t200\t0\t0\t1\t200\t1\t200\t1e-50\t400.0\n"
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(blast.subprocess, "run", fake_run)
    session = FakeSession(status="pending")
    monkeypatch.setattr(blast, "get_db", lambda: _fake_db(session))

    payload = _payload()
    payload["payload"]["sequence"] = PROTEIN
    result = _call_task(blast.run_blast, FakeTask(), payload=payload)

    assert seen["cmd"][0] == str(tmp_path / "diamond")
    assert seen["cmd"][1] == "blastp"
    # The output extension must name the format that was actually written.
    assert seen["cmd"][seen["cmd"].index("--out") + 1].endswith("results.txt")
    assert result["total_hits"] == 1
    assert result["query_len"] == len(PROTEIN)
    assert result["result_s3_path"].endswith(".txt")


def test_task_marks_a_retired_program_failed(monkeypatch):
    payload = _payload()
    payload["payload"]["program"] = "tblastn"
    session = FakeSession(status="pending")
    monkeypatch.setattr(blast, "get_db", lambda: _fake_db(session))
    monkeypatch.setattr(blast, "get_blast_db_path", lambda db, **kw: Path("/tmp/db"))
    with pytest.raises(ValueError, match="Unsupported program"):
        _call_task(blast.run_blast, FakeTask(), payload=payload)


@pytest.fixture
def diamond_runtime(monkeypatch):
    binary = os.environ.get("SOYMUTDB_TEST_DIAMOND_BIN") or shutil.which("diamond")
    if not binary:
        if os.environ.get("SOYMUTDB_REQUIRE_DIAMOND_SMOKE") == "1":
            pytest.fail("DIAMOND smoke is required but no binary was found")
        pytest.skip("DIAMOND absent; opt-in smoke")
    monkeypatch.setattr(blast, "DIAMOND_BIN", Path(binary))
    return Path(binary).parent


def _real_index(diamond_runtime, tmp_path, sequence, name="subject"):
    fasta = tmp_path / f"{name}.fa"
    fasta.write_text(f">{name}\n{sequence}\n")
    index = tmp_path / f"{name}.dmnd"
    subprocess.run(
        [
            str(diamond_runtime / "diamond"),
            "makedb",
            "--in",
            str(fasta),
            "-d",
            str(index),
            "-p",
            "1",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return index


def test_real_diamond_reports_a_protein_hit(diamond_runtime, tmp_path):
    index = _real_index(diamond_runtime, tmp_path, PROTEIN)
    query = tmp_path / "query.fa"
    query.write_text(f">query\n{PROTEIN}\n")
    output = tmp_path / "out.tsv"
    blast.run_blast_command(
        "blastp", index, query, output, evalue=1e-5, max_target_seqs=1, num_threads=1
    )
    parsed = blast.parse_diamond_tabular(output)
    assert parsed["total_hits"] == 1
    assert parsed["hits"][0]["subject_id"] == "subject"
    assert parsed["hits"][0]["percent_identity"] == pytest.approx(100.0, abs=0.1)


class TestRealDiamondAcceptsTheNormalizedQuery:
    """The task's normalized bytes must be searchable by the real binary.

    A fake subprocess cannot prove this: normalizing only matters if the engine
    accepts the result, so the engine is the one asked. Lives here rather than
    in test_blast_protein_fasta.py so the ``diamond_runtime`` fixture that
    enforces the required-smoke policy has a single definition.
    """

    @pytest.mark.parametrize(
        "label,query",
        [
            ("bare_sequence", f">query\n{PROTEIN}\n"),
            ("lowercase", f">query_1\n{PROTEIN.lower()}\n"),
            ("crlf", f">query_1\r\n{PROTEIN}\r\n"),
            (
                "wrapped",
                ">query_1\n"
                + "\n".join(PROTEIN[i : i + 10] for i in range(0, len(PROTEIN), 10))
                + "\n",
            ),
            ("trailing_stop", f">query_1\n{PROTEIN}*\n"),
        ],
        ids=["bare_sequence", "lowercase", "crlf", "wrapped", "trailing_stop"],
    )
    def test_normalized_query_is_searchable(
        self, diamond_runtime, tmp_path, label: str, query: str
    ):
        index = _real_index(diamond_runtime, tmp_path, PROTEIN, name="subject_1")
        query_path = tmp_path / f"query_{label}.fa"
        # Exactly what the task writes: normalized through the shared contract.
        query_path.write_text(parse_protein_fasta(query).to_fasta)
        output = tmp_path / f"out_{label}.tsv"
        blast.run_blast_command(
            "blastp", index, query_path, output, evalue=1e-5, max_target_seqs=1,
            num_threads=1,
        )
        parsed = blast.parse_diamond_tabular(output)
        assert parsed["total_hits"] >= 1
        assert parsed["hits"][0]["subject_id"] == "subject_1"

    def test_contract_rejects_empty_records_independently_of_engine_version(
        self, diamond_runtime, tmp_path
    ):
        """Older engines fail; DIAMOND 2.2.8 silently ignores the empty record.

        The application must reject it consistently before enqueueing a job.
        """
        index = _real_index(diamond_runtime, tmp_path, PROTEIN, name="subject_1")
        query_path = tmp_path / "query_empty_record.fa"
        query = f">empty\n>query_2\n{PROTEIN}\n"
        with pytest.raises(ProteinFastaError) as rejected:
            parse_protein_fasta(query)
        assert rejected.value.code == "protein_fasta_record_empty"
        query_path.write_text(query)
        output = tmp_path / "out_empty_record.tsv"
        try:
            blast.run_blast_command(
                "blastp", index, query_path, output, evalue=1e-5, max_target_seqs=1,
                num_threads=1,
            )
        except RuntimeError as error:
            assert "Missing fields in input line" in str(error)
        else:
            parsed = blast.parse_diamond_tabular(output)
            assert parsed["total_hits"] >= 1
            assert {hit["query_id"] for hit in parsed["hits"]} == {"query_2"}
