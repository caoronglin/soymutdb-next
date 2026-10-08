"""Contract tests for the shared protein-FASTA parser.

``blastp`` is the only executable program here, so these rules are the
definition of "a query this deployment can search". The API and the worker
both call this parser; a change here changes both boundaries, so the cases
below are the single place each edge case is pinned.

Every refusal asserts the machine-readable ``code`` as well as the message,
because the API maps it to a 422 and the worker writes it into the job's
error field.
"""

from __future__ import annotations

import pytest

from soymutdb_jobs.protein_fasta import (
    PROTEIN_ALPHABET,
    ProteinFastaError,
    parse_protein_fasta,
)

#: The canonical valid query used elsewhere in this repository. Note the
#: absence of ``U``: selenocysteine is deliberately outside the accepted
#: alphabet (see ``test_blast_validation.py``), so a "valid" fixture must not
#: contain it.
RESIDUES = "MKTIIALSYIFCLVFADYKDDDDKTRWQYNE"


class TestAcceptedShapes:
    def test_bare_sequence_gets_a_synthesized_header(self) -> None:
        parsed = parse_protein_fasta(RESIDUES)
        assert parsed.synthesized_header is True
        assert [r.record_id for r in parsed.records] == ["query"]
        assert parsed.query_length == len(RESIDUES)

    def test_single_record(self) -> None:
        parsed = parse_protein_fasta(f">q\n{RESIDUES}")
        assert parsed.synthesized_header is False
        assert parsed.records[0].record_id == "q"
        assert parsed.records[0].sequence == RESIDUES
        assert parsed.query_length == len(RESIDUES)

    def test_multi_record_sums_every_record(self) -> None:
        parsed = parse_protein_fasta(f">a\n{RESIDUES}\n>b\n{RESIDUES}")
        assert [r.record_id for r in parsed.records] == ["a", "b"]
        assert parsed.query_length == 2 * len(RESIDUES)

    def test_wrapped_lines_are_one_record(self) -> None:
        wrapped = ">q\n" + "\n".join(
            RESIDUES[start : start + 10] for start in range(0, len(RESIDUES), 10)
        )
        parsed = parse_protein_fasta(wrapped)
        assert len(parsed.records) == 1
        assert parsed.records[0].sequence == RESIDUES
        assert parsed.query_length == len(RESIDUES)

    def test_lowercase_is_normalized_so_both_callers_search_the_same_bytes(
        self,
    ) -> None:
        # DIAMOND accepts lower case, but only an upper-cased comparison can
        # assert that what the API validated is what the worker wrote out.
        parsed = parse_protein_fasta(f">q\n{RESIDUES.lower()}")
        assert parsed.records[0].sequence == RESIDUES

    def test_crlf_line_endings(self) -> None:
        assert parse_protein_fasta(f">q\r\n{RESIDUES}\r\n").query_length == (
            len(RESIDUES)
        )

    def test_header_description_is_ignored_after_the_identifier(self) -> None:
        parsed = parse_protein_fasta(f">gene.soy.1 some description here\n{RESIDUES}")
        assert parsed.records[0].record_id == "gene.soy.1"

    def test_to_fasta_round_trips(self) -> None:
        original = f">a\n{RESIDUES}\n>b desc\nMKTIIALSYI"
        once = parse_protein_fasta(original)
        twice = parse_protein_fasta(once.to_fasta)
        assert twice.to_fasta == once.to_fasta
        assert twice.query_length == once.query_length

    @pytest.mark.parametrize("separator", [" ", "\t"])
    def test_ascii_sequence_spacing(self, separator: str) -> None:
        parsed = parse_protein_fasta(f">q\nMKT{separator}IIALSYIF")
        assert parsed.records[0].sequence == "MKTIIALSYIF"

    @pytest.mark.parametrize("symbol", ["ı", "ſ", "ß", "\u00a0", "\v", "\f"])
    def test_non_residue_is_not_normalized_into_an_amino_acid(self, symbol: str) -> None:
        with pytest.raises(ProteinFastaError, match="protein_fasta_invalid_residue"):
            parse_protein_fasta(f">q\nMKT{symbol}IIALSYIF")

    def test_alphabet_covers_the_ambiguity_codes(self) -> None:
        assert set("BXZJUO") - PROTEIN_ALPHABET == {"J", "U", "O"}


class TestNucleotideLookingQueryIsNotRefused:
    """A/C/G/T are ordinary residues; only ``blastp`` is executable here."""

    def test_acgt_only_query_is_accepted(self) -> None:
        assert parse_protein_fasta("ATGCATGCATGCATGCATGC").query_length == 20


class TestTerminalStopIsNotAResidue:
    def test_trailing_stop_is_excluded_from_query_length(self) -> None:
        parsed = parse_protein_fasta(f">q\n{RESIDUES}*")
        assert parsed.records[0].sequence.endswith("*")
        assert parsed.query_length == len(RESIDUES)

    def test_internal_stop_still_counts(self) -> None:
        # Only a *terminal* stop is a translation artifact. A stop with
        # residues after it is part of the searched string and is not silently
        # trimmed, because trimming it would change what the user asked for.
        parsed = parse_protein_fasta(">q\nMKT*IIA")
        assert parsed.query_length == len("MKT*IIA")

    def test_stop_only_record_is_refused(self) -> None:
        # Nothing to search: accepting it would complete a job and report
        # query_len 0, which is indistinguishable from a failed search.
        with pytest.raises(ProteinFastaError) as excinfo:
            parse_protein_fasta(">q\n*")
        assert excinfo.value.code == "protein_fasta_record_empty"


class TestRefusals:
    @pytest.mark.parametrize("text", ["", "   ", "\n\n"])
    def test_empty_query(self, text: str) -> None:
        with pytest.raises(ProteinFastaError) as excinfo:
            parse_protein_fasta(text)
        assert excinfo.value.code == "protein_fasta_empty"

    def test_header_with_no_sequence(self) -> None:
        with pytest.raises(ProteinFastaError) as excinfo:
            parse_protein_fasta(">q")
        assert excinfo.value.code == "protein_fasta_record_empty"
        assert excinfo.value.details["record_id"] == "q"

    def test_later_empty_record_is_refused_not_passed_through(self) -> None:
        # This is the case DIAMOND used to reject only as
        # "Error: Missing fields in input line" after the job was running.
        with pytest.raises(ProteinFastaError) as excinfo:
            parse_protein_fasta(f">empty\n>q2\n{RESIDUES}")
        assert excinfo.value.code == "protein_fasta_record_empty"
        assert excinfo.value.details["record_id"] == "empty"

    def test_empty_record_between_valid_records(self) -> None:
        with pytest.raises(ProteinFastaError) as excinfo:
            parse_protein_fasta(f">a\n{RESIDUES}\n>hole\n>b\n{RESIDUES}")
        assert excinfo.value.code == "protein_fasta_record_empty"
        assert excinfo.value.details["record_id"] == "hole"

    def test_duplicate_identifier_is_refused(self) -> None:
        # DIAMOND searches both records and returns two indistinguishable hit
        # rows, so the duplicates are refused instead of being merged.
        with pytest.raises(ProteinFastaError) as excinfo:
            parse_protein_fasta(f">q\n{RESIDUES}\n>q\n{RESIDUES}")
        assert excinfo.value.code == "protein_fasta_duplicate_id"
        assert excinfo.value.details["record_id"] == "q"
        assert excinfo.value.details["first_line"] == 1
        assert excinfo.value.details["line"] == 3

    def test_same_identifier_with_different_description_is_still_a_duplicate(
        self,
    ) -> None:
        with pytest.raises(ProteinFastaError) as excinfo:
            parse_protein_fasta(f">q first\n{RESIDUES}\n>q second\n{RESIDUES}")
        assert excinfo.value.code == "protein_fasta_duplicate_id"

    @pytest.mark.parametrize("residue", ["9", "$", "U", "@"])
    def test_residue_outside_the_alphabet(self, residue: str) -> None:
        with pytest.raises(ProteinFastaError) as excinfo:
            parse_protein_fasta(f">q\nMKT{residue}IIA")
        assert excinfo.value.code == "protein_fasta_invalid_residue"
        assert excinfo.value.details["invalid"] == [residue]
        assert excinfo.value.details["line"] == 2

    @pytest.mark.parametrize("text", [">", ">\n", "> \n"])
    def test_header_without_an_identifier(self, text: str) -> None:
        with pytest.raises(ProteinFastaError) as excinfo:
            parse_protein_fasta(f"{text}\nMKTIIA")
        assert excinfo.value.code == "protein_fasta_record_id_missing"

    def test_sequence_before_any_header(self) -> None:
        with pytest.raises(ProteinFastaError) as excinfo:
            parse_protein_fasta("MKTIIA\n>q\nMKTIIA")
        assert excinfo.value.code == "protein_fasta_header_missing"

    def test_error_is_a_value_error_for_boundary_callers(self) -> None:
        # The API turns this into a 422 and the worker into a failed job; both
        # rely on it being a ValueError subclass.
        with pytest.raises(ValueError):
            parse_protein_fasta(">q")
