"""Opt-in actual NCBI index construction, not five-program search acceptance.

Fixtures are purpose-written synthetic sequences (CC0-1.0). The nucleotide
record and its explicit reverse complement exercise IUPAC DNA input, and the
protein record is a synthetic alphabet coverage peptide; none claims a gene or
assembly accession. Public biological background: NCBI FASTA format guidance,
https://www.ncbi.nlm.nih.gov/genbank/fastaformat/ (source version: 2026-11-03).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from soymutdb_worker.blast_index import BuildMetadata, build_index, verify_index


@pytest.mark.parametrize("db_type,text", [
    ("nucl", ">synthetic_forward\nACGTTGCAACGTTGCA\n>synthetic_reverse\nTGCAACGTTGCAACGT\n"),
    ("prot", ">synthetic_peptide\nMKWVTFISLLFLFSSAYSRGVFRRDTHKSEIAHRFKDLGE\n"),
])
def test_real_makeblastdb_and_blastdbcmd(tmp_path, db_type, text):
    make = os.getenv("SOYMUTDB_TEST_MAKEBLASTDB_BIN")
    cmd = os.getenv("SOYMUTDB_TEST_BLASTDBCMD_BIN")
    if not make or not cmd:
        pytest.skip("opt-in NCBI makeblastdb/blastdbcmd binaries not configured")
    source = tmp_path / "synthetic.fa"
    source.write_text(text)
    root = tmp_path / "indexes"
    root.mkdir()
    metadata = BuildMetadata(
        assembly_id="synthetic-test-assembly", assembly_version="1", release_id="test-only",
        annotation_version="synthetic-v1", source_url="https://github.com/caoronglin/soymutdb-next/blob/main/"
                   "apps/worker/tests/test_blast_index_real.py",
        source_version="2026-11-03", license="CC0-1.0",
    )
    result = build_index(source, root, db_type, metadata,
                         makeblastdb_bin=Path(make), blastdbcmd_bin=Path(cmd))
    assert result["manifest"]["request"]["sequence_count"] == text.count(">")
    assert verify_index(root, result["index_identity"], blastdbcmd_bin=cmd)["reused"]
    assert build_index(source, root, db_type, metadata,
                       makeblastdb_bin=make, blastdbcmd_bin=cmd)["reused"]

    for record in text.strip().split(">")[1:]:
        name, sequence = record.split("\n", 1)
        actual = subprocess.run(
            [cmd, "-db", str(root / result["index_prefix"]), "-dbtype", db_type,
             "-entry", name, "-outfmt", "%s"],
            env={"PATH": "/usr/bin:/bin", "BLAST_USAGE_REPORT": "false",
                 "NCBI_DONT_USE_NCBIRC": "1", "NCBI_DONT_USE_LOCAL_CONFIG": "1"},
            capture_output=True, text=True, check=True, timeout=15,
        )
        assert actual.stdout.strip() == sequence.replace("\n", "")
