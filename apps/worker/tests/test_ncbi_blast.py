from pathlib import Path

import pytest

import soymutdb_worker.ncbi_blast as ncbi

PROGRAMS = [
    ("blastn", "nucl"),
    ("blastp", "prot"),
    ("blastx", "prot"),
    ("tblastn", "nucl"),
    ("tblastx", "nucl"),
]


@pytest.mark.parametrize("program,db", PROGRAMS)
def test_program_database_matrix(program, db):
    assert ncbi.validate_program_database(program, db)[0] == db
    with pytest.raises(ncbi.NcbiBlastError):
        ncbi.validate_program_database(program, "prot" if db == "nucl" else "nucl")


def test_command_is_fixed_argv_and_compatibility(tmp_path):
    binary = tmp_path / "blastn"
    binary.write_text("x")
    binary.chmod(0o700)
    args = ncbi.build_command(
        "blastn",
        "nucl",
        Path("db"),
        Path("query"),
        Path("out"),
        {
            "evalue": 1e-5,
            "max_target_seqs": 20,
            "num_threads": 2,
            "dust": True,
            "perc_identity": 80,
        },
        tmp_path,
    )
    assert (
        args[0] == str(binary)
        and "-shell" not in args
        and "qseqid" in args[args.index("-outfmt") + 1]
    )
    with pytest.raises(ncbi.NcbiBlastError):
        ncbi.build_command(
            "blastp", "prot", Path("d"), Path("q"), Path("o"), {"dust": True}, tmp_path
        )
    with pytest.raises(ncbi.NcbiBlastError):
        ncbi.build_command(
            "blastp", "prot", Path("d"), Path("q"), Path("o"), {"unknown": "x"}, tmp_path
        )


def test_parse_tabular_empty_orientation_and_bounds():
    assert ncbi.parse_tabular("") == []
    hit = ncbi.parse_tabular("q\ts\t99.5\t10\t0\t0\t10\t1\t20\t11\t1e-5\t42\n")[0]
    assert (
        hit["query_id"] == "q"
        and hit["query_strand"] == "minus"
        and hit["subject_strand"] == "minus"
    )
    with pytest.raises(ncbi.NcbiBlastError):
        ncbi.parse_tabular("q\ts\tNaN\t10\t0\t0\t1\t2\t1\t2\t1e-5\t42")
    with pytest.raises(ncbi.NcbiBlastError):
        ncbi.parse_tabular("q\ts\t99\t0\t0\t0\t1\t2\t1\t2\t1e-5\t42")


def test_child_environment_is_minimal_and_limits(tmp_path):
    assert ncbi._env(tmp_path)["BLAST_USAGE_REPORT"] == "false"
    assert "AWS_SECRET_ACCESS_KEY" not in ncbi._env(tmp_path)
    with pytest.raises(ncbi.NcbiBlastError):
        ncbi.run_search(
            "blastn",
            "nucl",
            tmp_path / "db",
            tmp_path / "q",
            tmp_path / "out",
            {},
            tmp_path,
            limits=ncbi.SearchLimits(threads=2),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("percent_identity", 80),
        ("raw", "-evil"),
        ("evalue", float("nan")),
        ("num_threads", 500),
        ("word_size", 1),
        ("dust", "yes"),
    ],
)
def test_invalid_parameters_rejected(tmp_path, field, value):
    binary = tmp_path / "blastn"
    binary.write_text("x")
    binary.chmod(0o700)
    with pytest.raises(ncbi.NcbiBlastError):
        ncbi.build_command(
            "blastn",
            "nucl",
            tmp_path / "db",
            tmp_path / "q",
            tmp_path / "out",
            {field: value},
            tmp_path,
        )


@pytest.mark.parametrize(
    "body,reason",
    [
        ("import time;time.sleep(5)", "wall time"),
        ("raise SystemExit(2)", "execution failed"),
        ("print('x'*100000)", "execution failed"),
    ],
)
def test_bounded_child_failures(tmp_path, body, reason):
    import sys

    binary = tmp_path / "blastn"
    binary.write_text(f"#!{sys.executable}\n" + body + "\n")
    binary.chmod(0o700)
    with pytest.raises(ncbi.NcbiBlastError):
        ncbi._execute([str(binary)], tmp_path, ncbi.SearchLimits(wall_seconds=1, output_bytes=1024))


def test_invalid_query_fails_before_process(tmp_path, monkeypatch):
    q = tmp_path / "query.fa"
    q.write_text(">x\nINVALID!\n")
    monkeypatch.setattr(ncbi, "_execute", lambda *_: pytest.fail("invalid query executed"))
    with pytest.raises(ncbi.NcbiBlastError):
        ncbi.run_search("blastn", "nucl", tmp_path / "db", q, tmp_path / "out", {}, tmp_path)


@pytest.mark.parametrize(
    "column,value",
    [
        (0, ""),
        (1, "bad id"),
        (2, "101"),
        (3, "-1"),
        (4, "-1"),
        (5, "-1"),
        (6, "0"),
        (7, "-1"),
        (8, "0"),
        (9, "-1"),
        (10, "inf"),
        (11, "NaN"),
        (3, "9" * 400),
    ],
)
def test_parser_rejects_invalid_bounds(column, value):
    fields = ["q", "s", "100", "20", "0", "0", "1", "20", "1", "20", "1e-5", "42"]
    fields[column] = value
    with pytest.raises(ncbi.NcbiBlastError):
        ncbi.parse_tabular("\t".join(fields))


def test_no_shell_minimal_env_actual_process(tmp_path, monkeypatch):
    import sys

    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "should-not-leak")
    binary = tmp_path / "blastn"
    binary.write_text(
        f"#!{sys.executable}\nimport os\n"
        "assert 'AWS_SECRET_ACCESS_KEY' not in os.environ\n"
        "assert os.environ['NCBI_DONT_USE_NCBIRC']=='1'\nprint('ok')\n"
    )
    binary.chmod(0o700)
    assert ncbi._execute([str(binary)], tmp_path, ncbi.SearchLimits()).strip() == "ok"
