"""GFF3 structure parsing — the parts of a gene model that search never needed.

The importer this covers exists because the schema had no way to store a CDS or
a UTR. These tests run without a database on purpose: the database-backed
importer is exercised against a real PostgreSQL, which this suite cannot start
(no Docker daemon in CI here), so everything provable without a connection is
proved here instead.

The regression that matters most is ``test_eof_transcript_still_has_its_parts``:
an early implementation yielded each transcript on its ``mRNA`` line, which
handed the caller a feature whose ``parts`` list was still empty — the generator
only appended to it after the caller had moved on. Every gene model would have
rendered as a bare box, with no CDS and no UTR, and the counts would still have
looked plausible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.gene_structure_import_service import (
    parse_structure_features,
    sha256_of_file,
)

HEADER = "##gff-version 3\n"


def write_gff3(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "annotation.gff3"
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def feature(
    chromosome: str,
    kind: str,
    start: int,
    end: int,
    *,
    strand: str = "+",
    attributes: str,
) -> str:
    return f"{chromosome}\tphytozomev13\t{kind}\t{start}\t{end}\t.\t{strand}\t0\t{attributes}\n"


def test_parts_are_attached_to_their_transcript(tmp_path: Path) -> None:
    path = write_gff3(
        tmp_path,
        feature("Gm01", "gene", 100, 900, attributes="ID=Glyma.01G000100")
        + feature("Gm01", "mRNA", 100, 900, attributes="ID=tx1;Parent=Glyma.01G000100")
        + feature("Gm01", "CDS", 200, 300, attributes="ID=tx1.CDS.1;Parent=tx1")
        + feature("Gm01", "five_prime_UTR", 100, 199, attributes="Parent=tx1")
        + feature("Gm01", "three_prime_UTR", 800, 900, attributes="Parent=tx1"),
    )

    transcripts = list(parse_structure_features(path))

    assert len(transcripts) == 1
    transcript = transcripts[0]
    assert transcript.transcript_id == "tx1"
    assert transcript.gene_accession == "Glyma.01G000100"
    assert [part.part_type for part in transcript.parts] == [
        "cds",
        "five_prime_utr",
        "three_prime_utr",
    ]


def test_eof_transcript_still_has_its_parts(tmp_path: Path) -> None:
    """The last transcript in the file is the one the streaming bug dropped."""
    path = write_gff3(
        tmp_path,
        feature("Gm01", "mRNA", 100, 900, attributes="ID=tx_first;Parent=G1")
        + feature("Gm01", "CDS", 200, 300, attributes="Parent=tx_first")
        + feature("Gm01", "mRNA", 2000, 2900, attributes="ID=tx_last;Parent=G2")
        + feature("Gm01", "CDS", 2100, 2200, attributes="Parent=tx_last")
        + feature("Gm01", "CDS", 2400, 2500, attributes="Parent=tx_last"),
    )

    transcripts = {t.transcript_id: t for t in parse_structure_features(path)}

    assert set(transcripts) == {"tx_first", "tx_last"}
    assert len(transcripts["tx_first"].parts) == 1
    assert len(transcripts["tx_last"].parts) == 2


def test_minus_strand_keeps_file_order(tmp_path: Path) -> None:
    """CDS order is file order, not coordinate order.

    A minus-strand gene lists its CDS boxes from the high coordinate down. The
    only thing testable here is that the parser preserves what the file says —
    re-sorting by start would reverse the reading frame of every such gene.
    """
    path = write_gff3(
        tmp_path,
        feature("Gm01", "mRNA", 1000, 2000, strand="-", attributes="ID=tx_minus;Parent=G1")
        + feature("Gm01", "CDS", 1800, 1900, strand="-", attributes="Parent=tx_minus")
        + feature("Gm01", "CDS", 1500, 1600, strand="-", attributes="Parent=tx_minus")
        + feature("Gm01", "CDS", 1100, 1200, strand="-", attributes="Parent=tx_minus"),
    )

    transcript = list(parse_structure_features(path))[0]

    assert transcript.strand == "-"
    assert [(p.start, p.end) for p in transcript.parts] == [
        (1800, 1900),
        (1500, 1600),
        (1100, 1200),
    ]


def test_exon_spans_are_the_union_of_the_parts(tmp_path: Path) -> None:
    """An exon is what an exon always was: CDS and UTR merged.

    The CDS box abuts the 5' UTR at 199/200, so they form one exon; the 3' UTR
    is separated by a real intron (301-799) and survives as a second one.
    """
    path = write_gff3(
        tmp_path,
        feature("Gm01", "mRNA", 100, 900, attributes="ID=tx1;Parent=G1")
        + feature("Gm01", "CDS", 200, 300, attributes="Parent=tx1")
        + feature("Gm01", "five_prime_UTR", 100, 199, attributes="Parent=tx1")
        + feature("Gm01", "three_prime_UTR", 800, 900, attributes="Parent=tx1"),
    )

    transcript = list(parse_structure_features(path))[0]

    assert transcript.exon_spans() == [(100, 300), (800, 900)]


def test_transcript_without_parts_falls_back_to_its_own_body(tmp_path: Path) -> None:
    """Some annotations ship exons only; the transcript must still render once."""
    path = write_gff3(
        tmp_path,
        feature("Gm01", "mRNA", 500, 1500, attributes="ID=tx_bare;Parent=G1"),
    )

    transcript = list(parse_structure_features(path))[0]

    assert transcript.parts == []
    assert transcript.exon_spans() == [(500, 1500)]


def test_part_from_an_unknown_parent_is_dropped(tmp_path: Path) -> None:
    """Attaching it to the open transcript would fabricate a gene model."""
    path = write_gff3(
        tmp_path,
        feature("Gm01", "mRNA", 100, 900, attributes="ID=tx1;Parent=G1")
        + feature("Gm01", "CDS", 200, 300, attributes="Parent=tx1")
        + feature("Gm01", "CDS", 400, 500, attributes="Parent=some_other_transcript"),
    )

    transcript = list(parse_structure_features(path))[0]

    assert [(p.start, p.end) for p in transcript.parts] == [(200, 300)]


def test_non_structural_feature_rows_are_ignored(tmp_path: Path) -> None:
    path = write_gff3(
        tmp_path,
        feature("Gm01", "gene", 100, 900, attributes="ID=Glyma.01G000100")
        + feature("Gm01", "exon", 100, 300, attributes="Parent=tx1")
        + feature("Gm01", "mRNA", 100, 900, attributes="ID=tx1;Parent=Glyma.01G000100")
        + feature("Gm01", "CDS", 200, 300, attributes="Parent=tx1"),
    )

    transcripts = list(parse_structure_features(path))

    assert [t.transcript_id for t in transcripts] == ["tx1"]
    assert len(transcripts[0].parts) == 1


def test_malformed_rows_do_not_abort_the_file(tmp_path: Path) -> None:
    """A short or unparsable line is skipped, not fatal: an 845k-line GFF3 from
    an external pipeline must not lose every later transcript to one bad row."""
    path = write_gff3(
        tmp_path,
        "Gm01\tphytozomev13\tCDS\t1\t2\n"
        + feature("Gm01", "mRNA", 100, 900, attributes="ID=tx1;Parent=G1")
        + feature("Gm01", "CDS", 200, 300, attributes="Parent=tx1")
        + feature("Gm01", "CDS", 500, 400, attributes="Parent=tx1"),
    )

    transcript = list(parse_structure_features(path))[0]

    # The inverted row (500 > 400) is dropped; the valid one survives.
    assert [(p.start, p.end) for p in transcript.parts] == [(200, 300)]


def test_sha256_is_stable_and_content_addressed(tmp_path: Path) -> None:
    first = write_gff3(tmp_path, feature("Gm01", "CDS", 1, 9, attributes="Parent=tx1"))
    digest = sha256_of_file(first)
    assert len(digest) == 64
    assert sha256_of_file(first) == digest

    second = tmp_path / "other.gff3"
    second.write_text(first.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert sha256_of_file(second) != digest


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ID=tx1;Parent=G1", {"ID": "tx1", "Parent": "G1"}),
        ("Parent=tx1", {"Parent": "tx1"}),
    ],
)
def test_attribute_parsing_shapes(raw: str, expected: dict[str, str]) -> None:
    from app.services.gene_structure_import_service import _parse_attributes

    assert _parse_attributes(raw) == expected
