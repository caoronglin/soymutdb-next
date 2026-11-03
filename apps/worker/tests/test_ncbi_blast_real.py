"""Actual NCBI2.17 searches using synthetic CC0 ORF fixtures, not biological claims.

``BLAST_USAGE_REPORT=false`` is not optional here. Without it, every NCBI
executable tries to phone home on startup and burns ~31 s per invocation in a
network-isolated environment, which turns a fast unit suite into a hang. The
worker's own runner (:func:`soymutdb_worker.ncbi_blast._env`) already sets it;
this fixture pins the same contract for the binaries the test spawns itself.
"""

import os
import subprocess
from pathlib import Path

import pytest

from soymutdb_worker.ncbi_blast import run_search

BIN = Path(
    os.getenv("SOYMUTDB_TEST_NCBI_BIN_DIR", ".cache/blast-catalog-pr/tools/ncbi-blast-2.17.0+/bin")
).absolute()

# Mirrors ``ncbi_blast._env``: no usage reporting, no user/system rc files.
# Fixture-only ``makeblastdb`` calls must disable the same telemetry and local
# config discovery as the runner, otherwise a real binary blocks on telemetry
# DNS for ~30s and exceeds the test timeout. A minimal environment (rather than
# ``**os.environ``) also keeps any host NCBI configuration out of the fixture.
OFFLINE_BLAST_ENV = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
    "BLAST_USAGE_REPORT": "false",
    "NCBI_DONT_USE_NCBIRC": "1",
    "NCBI_DONT_USE_LOCAL_CONFIG": "1",
}
DNA = (
    "ATG" + "GCTGAAAAGGTTCTGGATGGTGACTTTGCTAAGAAGATTGGTGAAAAGGTTGATGCTGGTGTTGATGTTGCT"
    "GAAAAGGTTGATGGTGCTAAGGCTGTTGAAAAGGCTGATGTTGGTGCTGATGAAAAGGTTGCTGATGTTGAAAAG"
    "GCTGGT" * 3
)
# Translation according to standard genetic code; generated fixture remains synthetic.
CODONS = {
    "ATG": "M",
    "GCT": "A",
    "GAA": "E",
    "AAG": "K",
    "GTT": "V",
    "CTG": "L",
    "GAT": "D",
    "GGT": "G",
    "GAC": "D",
    "TTT": "F",
    "ATT": "I",
}
PROTEIN = "".join(CODONS[DNA[i : i + 3]] for i in range(0, len(DNA), 3))


@pytest.mark.parametrize(
    "program,dbtype,query",
    [
        ("blastn", "nucl", DNA),
        ("blastp", "prot", PROTEIN),
        ("blastx", "prot", DNA),
        ("tblastn", "nucl", PROTEIN),
        ("tblastx", "nucl", DNA),
    ],
)
def test_real_all_five_known_hit(tmp_path, program, dbtype, query):
    if not (BIN / program).exists():
        pytest.skip("official NCBI binaries not configured")
    source = tmp_path / "source.fa"
    source.write_text(">subject\n" + (DNA if dbtype == "nucl" else PROTEIN) + "\n")
    subprocess.run(
        [
            str(BIN / "makeblastdb"),
            "-in",
            str(source),
            "-dbtype",
            dbtype,
            "-out",
            str(tmp_path / "db"),
            "-blastdb_version",
            "4",
        ],
        check=True,
        capture_output=True,
        timeout=20,
        env=OFFLINE_BLAST_ENV,
    )
    q = tmp_path / "query.fa"
    q.write_text(">query\n" + query + "\n")
    result = run_search(program, dbtype, tmp_path / "db", q, tmp_path / "result.tsv", {}, BIN)
    assert result["total_hits"] > 0
    assert result["hits"][0]["query_id"] == "query"
    assert result["binary"]["sha256"]
    best = max(result["hits"], key=lambda hit: hit["bit_score"])
    if program in {"blastx", "tblastx"}:
        assert abs(best["query_end"] - best["query_start"]) + 1 >= 3 * best["alignment_length"]
    if program in {"tblastn", "tblastx"}:
        assert abs(best["subject_end"] - best["subject_start"]) + 1 >= 3 * best["alignment_length"]


def test_real_reverse_blastn_and_no_hit(tmp_path):
    if not (BIN / "blastn").exists():
        pytest.skip("official NCBI binaries not configured")
    import random

    rng = random.Random(457)
    target = "".join(rng.choice("ACGT") for _ in range(480))
    reverse = target.translate(str.maketrans("ACGT", "TGCA"))[::-1]
    source = tmp_path / "source.fa"
    source.write_text(">subject\n" + target + "\n")
    subprocess.run(
        [
            str(BIN / "makeblastdb"),
            "-in",
            str(source),
            "-dbtype",
            "nucl",
            "-out",
            str(tmp_path / "db"),
            "-blastdb_version",
            "4",
        ],
        check=True,
        capture_output=True,
        timeout=20,
        env=OFFLINE_BLAST_ENV,
    )
    query = tmp_path / "query.fa"
    query.write_text(">reverse\n" + reverse + "\n")
    result = run_search("blastn", "nucl", tmp_path / "db", query, tmp_path / "reverse.tsv", {}, BIN)
    assert any(
        h["subject_strand"] == "minus" or h["query_strand"] == "minus" for h in result["hits"]
    )
    query.write_text(">absent\n" + "N" * 480 + "\n")
    result = run_search("blastn", "nucl", tmp_path / "db", query, tmp_path / "none.tsv", {}, BIN)
    assert result["total_hits"] == 0
