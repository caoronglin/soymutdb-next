"""Shared protein-FASTA contract for the ``blastp`` submission path.

Why this module exists
----------------------
``blastp`` is the only executable program in this deployment, so a submitted
query is always protein. Two callers must agree on that query *before* it
reaches the search binary:

* the API validates it at submission time (422, before a job is queued), and
* the worker validates it again on the Celery payload, because a direct or
  redelivered dispatch never passes through the API.

Measured behaviour of DIAMOND 2.1.14 that this contract exists to prevent:

======================  ==========================================
input                   real binary result
======================  ==========================================
empty record            ``rc=1`` ``Error: Missing fields in input
                        line`` — an opaque failure after queueing
duplicate record id     ``rc=0``, **both** records are searched and
                        two indistinguishable hit rows are produced
trailing ``*``          ``rc=0``, retained in engine input; project
                        query length excludes one terminal stop while
                        DIAMOND qlen includes it
lower case / CRLF /     accepted; normalized here so both callers
wrapped lines           agree on what was actually searched
======================  ==========================================

Design rules
------------
* Standard library only, no ORM, no Biopython, no engine calls: the API and
  the worker must compute identical results without a version skew between
  their environments.
* Refusing an input is always explicit and machine-readable
  (:class:`ProteinFastaError`). Nothing is silently dropped, deduplicated or
  reordered.
* ``A``/``C``/``G``/``T`` are ordinary residues here. This deployment executes
  only ``blastp``, so a nucleotide-looking query is never rejected on
  composition alone.
* Historic rows keep whatever ``query_len`` was stored with them; this module
  governs newly submitted and newly executed queries only.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Standard residues plus the ambiguity codes and gap/stop symbols that real
#: annotation and submission pipelines emit.
PROTEIN_ALPHABET = frozenset("ACDEFGHIKLMNPQRSTVWYBZX*-")

#: Identifier used when a submission is a bare sequence with no header, which
#: is what the worker previously synthesized inline.
DEFAULT_RECORD_ID = "query"


class ProteinFastaError(ValueError):
    """A query cannot be searched as submitted.

    ``code`` is a stable machine-readable reason and is also the prefix of the
    message, because the API returns the message to the submitter and the
    worker copies it into the job's error field; a reason that only existed as
    an attribute would be lost on both paths. ``details`` carries the
    offending line/identifier so an operator can fix the source file.
    """

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.details = details


@dataclass(frozen=True)
class ProteinFastaRecord:
    """One validated query record.

    ``residue_count`` is the project's sequence-position count, excluding a
    single terminal ``*``. Internal stop/gap positions still count; this is not
    DIAMOND qlen or alignment length, and the actual input retains the stop.
    """

    record_id: str
    sequence: str
    residue_count: int


@dataclass(frozen=True)
class ProteinFasta:
    """A validated query, ready to be written to a ``.fasta`` file."""

    records: tuple[ProteinFastaRecord, ...]
    #: Project sequence-position total, excluding one terminal stop per record.
    query_length: int
    #: True when the submission had no ``>`` header and ``>query`` was added.
    synthesized_header: bool

    @property
    def to_fasta(self) -> str:
        """Render the normalized query, one record per line-wrapped block."""
        return "".join(
            f">{record.record_id}\n{record.sequence}\n" for record in self.records
        )


def _residue_count(sequence: str) -> int:
    return len(sequence[:-1]) if sequence.endswith("*") else len(sequence)


def _validate_residues(sequence: str, *, record_id: str, line_number: int) -> str:
    # Check the original characters before uppercasing: Unicode case folding
    # can turn non-residues into amino acids (e.g. ß -> SS, ı -> I).
    invalid = sorted(
        {ch for ch in sequence if not ch.isascii() or ch.upper() not in PROTEIN_ALPHABET}
    )
    if invalid:
        raise ProteinFastaError(
            "protein_fasta_invalid_residue",
            "query contains characters outside the protein alphabet: "
            f"{invalid[:10]}{'…' if len(invalid) > 10 else ''}",
            record_id=record_id,
            line=line_number,
            invalid=invalid[:10],
        )
    return sequence.upper()


def parse_protein_fasta(text: str) -> ProteinFasta:
    """Validate and normalize a protein query.

    Accepts either a bare sequence or multi-record FASTA. Rejects, in this
    order: empty input, a header with no residues, any record without
    residues, a duplicate record identifier, and residues outside
    :data:`PROTEIN_ALPHABET`.
    """
    if not text or not text.strip():
        raise ProteinFastaError(
            "protein_fasta_empty", "query_sequence must not be empty"
        )

    # Only ASCII space/tab and conventional CR/LF line endings are formatting.
    # str.split()/strip() would silently discard NBSP and other Unicode input.
    lines = [
        line.strip(" \t")
        for line in text.strip(" \t\r\n").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    if not any(line.startswith(">") for line in lines):
        # A bare sequence: the caller has been synthesizing this header.
        lines = [f">{DEFAULT_RECORD_ID}", *lines]
        synthesized = True
    else:
        synthesized = False

    records: list[ProteinFastaRecord] = []
    seen: dict[str, int] = {}
    current_id: str | None = None
    current_line = 0
    chunks: list[str] = []

    def close_record() -> None:
        if current_id is None:
            return
        sequence = "".join(chunks).upper()
        if not sequence:
            raise ProteinFastaError(
                "protein_fasta_record_empty",
                f"query record {current_id!r} has no sequence",
                record_id=current_id,
                line=current_line,
            )
        if current_id in seen:
            raise ProteinFastaError(
                "protein_fasta_duplicate_id",
                f"query record id {current_id!r} appears more than once; "
                "each hit would be indistinguishable",
                record_id=current_id,
                first_line=seen[current_id],
                line=current_line,
            )
        residue_count = _residue_count(sequence)
        if residue_count == 0:
            # A record holding only a terminal stop symbol has nothing to
            # search. Refusing it is the same defect as an empty record, and
            # accepting it would report query_len 0 for a completed search.
            raise ProteinFastaError(
                "protein_fasta_record_empty",
                f"query record {current_id!r} contains only a stop symbol and "
                "no residues to search",
                record_id=current_id,
                line=current_line,
            )
        seen[current_id] = current_line
        records.append(
            ProteinFastaRecord(
                record_id=current_id,
                sequence=sequence,
                residue_count=residue_count,
            )
        )

    for line_number, line in enumerate(lines, start=1):
        if line.startswith(">"):
            close_record()
            current_id = line[1:].split()[0] if line[1:].split() else ""
            current_line = line_number
            chunks = []
            if not current_id:
                raise ProteinFastaError(
                    "protein_fasta_record_id_missing",
                    f"query header on line {line_number} has no identifier",
                    line=line_number,
                )
        elif current_id is None:
            raise ProteinFastaError(
                "protein_fasta_header_missing",
                f"query line {line_number} has sequence before any header",
                line=line_number,
            )
        else:
            residue_line = line.replace(" ", "").replace("\t", "")
            chunks.append(_validate_residues(
                residue_line, record_id=current_id, line_number=line_number
            ))

    close_record()

    if not records:
        raise ProteinFastaError(
            "protein_fasta_empty", "query_sequence contains no record"
        )
    return ProteinFasta(
        records=tuple(records),
        query_length=sum(record.residue_count for record in records),
        synthesized_header=synthesized,
    )


__all__ = [
    "DEFAULT_RECORD_ID",
    "PROTEIN_ALPHABET",
    "ProteinFasta",
    "ProteinFastaError",
    "ProteinFastaRecord",
    "parse_protein_fasta",
]
