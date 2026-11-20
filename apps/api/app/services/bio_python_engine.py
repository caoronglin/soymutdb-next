"""Sequence engine implemented with Biopython instead of the Rust kernel.

This module answers the *same* function surface as the compiled
``soymutdb_bio_core`` extension, so ``bio_core_bridge`` can drive either one
without the service layer or the HTTP contract knowing which ran. The shapes
and the numeric rules are not re-invented here: every function reproduces the
semantics the Rust kernel documented, because the request/response models and
the existing regression tests were written against them.

Why Biopython rather than a hand-written reimplementation:

* the operations are standard bioinformatics, and Biopython is the reference
  implementation for them, so the answer matches what a researcher gets from
  their own script;
* it ships a maintained REBASE restriction-enzyme table, codon tables, a
  nearest-neighbour Tm calculator and the tree builders, none of which belong
  in bespoke code;
* it is a pure-Python wheel for CPython 3.15 (no build toolchain in the image).

Errors are raised as :class:`BioEngineError` carrying the same machine-readable
codes the Rust kernel used, so ``bio_core_bridge.translate_error`` keeps working
unchanged and the published error vocabulary does not grow a second dialect.
"""

from __future__ import annotations

from typing import Any, NoReturn

#: Byte limits mirror the Rust kernel so a request accepted by one engine is
#: accepted by the other. They are re-exported from the schema module rather
#: than re-declared, so there is a single source of truth.
MAX_INLINE_SEQUENCE = 1_048_576

_ALPHABET_ALLOWED = {
    "dna": set(b"ACGTURYKMBVDHSWN".decode()),
    "rna": set(b"ACGUURYKMBVDHSWN".decode()),
    "protein": set(b"ACDEFGHIKLMNPQRSTVWYBXZJUO*".decode()),
}

_COMPLEMENT_DNA = {
    "A": "T", "T": "A", "U": "A", "C": "G", "G": "C",
    "R": "Y", "Y": "R", "K": "M", "M": "K", "B": "V", "V": "B",
    "D": "H", "H": "D", "S": "S", "W": "W", "N": "N",
}
_COMPLEMENT_RNA = {
    "A": "U", "U": "A", "T": "A", "C": "G", "G": "C",
    "R": "Y", "Y": "R", "K": "M", "M": "K", "B": "V", "V": "B",
    "D": "H", "H": "D", "S": "S", "W": "W", "N": "N",
}

_STOP_CODONS = frozenset({"TAA", "TAG", "TGA"})
_DNA_ONLY = frozenset("ACGT")

ENGINE = "biopython"
ENGINE_VERSION = "1.88"


class BioEngineError(Exception):
    """A rejected input, carrying the kernel's machine-readable code.

    The attribute names match the Rust extension's exception so the bridge can
    translate either one without a special case.
    """

    def __init__(self, code: str, message: str) -> None:
        # `args` must be ``(code, message)``: the bridge reads the machine code
        # from the first argument, the way it does for the compiled kernel's
        # exception. Passing only the sentence made every engine error collapse
        # into the generic validation_error fallback.
        super().__init__(code, message)
        self.code = code
        self.message = message


# The compiled kernel exposes its error type under this name, and the bridge
# catches it without assuming which engine ran. Aliasing keeps that contract:
# the Python engine raises the same type identity the bridge already handles.
BioCoreException = BioEngineError


def _fail(code: str, message: str) -> NoReturn:
    raise BioEngineError(code, message)


# Every message the published error vocabulary defines, so both engines answer
# with the same sentence for the same code.
_MESSAGES = {
    "EMPTY_SEQUENCE": "empty sequence",
    "INVALID_CHARACTER": "invalid character for the selected alphabet",
    "UNSUPPORTED_ALPHABET": "unsupported alphabet for this operation",
    "SEQUENCE_TOO_LONG": "sequence exceeds the configured size limit",
    "BUDGET_EXCEEDED": "input exceeds the configured budget",
    "INVALID_INTERVAL": "invalid coordinate: start must be >= 0 and stop must be > start",
    "COORDINATE_OVERFLOW": "integer overflow while computing coordinates",
    "UNSUPPORTED_PARAMETER": "unsupported parameter value",
    "UNKNOWN_GENETIC_CODE": "genetic code is not implemented",
    "INVALID_RECORD": "invalid FASTA/FASTQ record",
}


def _raise_code(code: str) -> NoReturn:
    raise BioEngineError(code, _MESSAGES[code])


def _validate(sequence: str, alphabet: str) -> str:
    """Validate at the same boundary the kernel used, and return upper-case."""
    if alphabet not in _ALPHABET_ALLOWED:
        _raise_code("UNSUPPORTED_ALPHABET")
    if not sequence:
        _raise_code("EMPTY_SEQUENCE")
    if len(sequence) > MAX_INLINE_SEQUENCE:
        _raise_code("SEQUENCE_TOO_LONG")
    allowed = _ALPHABET_ALLOWED[alphabet]
    upper = sequence.upper()
    if any(char not in allowed for char in upper):
        _raise_code("INVALID_CHARACTER")
    return upper


def reverse_complement(sequence: str, alphabet: str = "dna", preserve_case: bool = False) -> str:
    """Reverse complement, using the kernel's IUPAC table."""
    if alphabet == "protein":
        _raise_code("UNSUPPORTED_ALPHABET")
    _validate(sequence, alphabet)
    table = _COMPLEMENT_DNA if alphabet == "dna" else _COMPLEMENT_RNA
    if preserve_case:
        out = []
        for char in reversed(sequence):
            upper = char.upper()
            complement = table.get(upper)
            if complement is None:
                _raise_code("INVALID_CHARACTER")
            # The kernel preserves the source case: a lower-case base yields a
            # lower-case complement.
            out.append(complement.lower() if char.islower() else complement)
        return "".join(out)
    return "".join(table[char.upper()] for char in reversed(sequence))


def find_matches(
    # The argument order is the contract the service layer already calls with
    # (target first, then pattern), matching the compiled kernel's binding.
    target: str,
    pattern: str,
    alphabet: str = "dna",
    mode: str = "exact",
    both_strands: bool = True,
    max_edits: int = 0,
    max_hits: int = 100,
) -> list[dict[str, Any]]:
    """Find pattern occurrences; exact by default, bounded approximate otherwise.

    Coordinates are 1-based inclusive on the forward target, whichever strand
    the hit came from, matching the kernel's contract.
    """
    _validate(pattern, alphabet)
    target_upper = _validate(target, alphabet)
    if mode == "exact":
        return _find_exact(pattern.upper(), target_upper, both_strands, max_hits)
    if mode != "approximate":
        _raise_code("UNSUPPORTED_PARAMETER")
    return _find_approximate(
        pattern.upper(), target_upper, alphabet, both_strands, max_edits, max_hits
    )


def _find_exact(
    pattern: str, target: str, both_strands: bool, max_hits: int
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    start = target.find(pattern)
    while start != -1 and len(hits) < max_hits:
        hits.append(
            {
                "start": start + 1,
                "end": start + len(pattern),
                "strand": "+",
                "edit_distance": 0,
            }
        )
        start = target.find(pattern, start + 1)
    if both_strands and len(hits) < max_hits:
        reverse = reverse_complement(pattern, "dna", False)
        start = target.find(reverse)
        while start != -1 and len(hits) < max_hits:
            hits.append(
                {"start": start + 1, "end": start + len(reverse), "strand": "-", "edit_distance": 0}
            )
            start = target.find(reverse, start + 1)
    hits.sort(key=lambda hit: (hit["start"], hit["strand"] == "-"))
    return hits[:max_hits]


def _find_approximate(
    pattern: str,
    target: str,
    alphabet: str,
    both_strands: bool,
    max_edits: int,
    max_hits: int,
) -> list[dict[str, Any]]:
    """Bounded Hamming-distance search (substitutions only, as the kernel did)."""
    hits: list[dict[str, Any]] = []
    if max_edits < 0 or max_edits > 3:
        _raise_code("UNSUPPORTED_PARAMETER")
    patterns = [(pattern, "+")]
    if both_strands and alphabet != "protein":
        patterns.append((reverse_complement(pattern, alphabet, False), "-"))
    span = len(pattern)
    for candidate, strand in patterns:
        for offset in range(0, max(0, len(target) - span) + 1):
            window = target[offset : offset + span]
            if len(window) != span:
                break
            edits = sum(1 for left, right in zip(window, candidate) if left != right)
            if edits <= max_edits:
                hits.append(
                    {
                        "start": offset + 1,
                        "end": offset + span,
                        "strand": strand,
                        "edit_distance": edits,
                    }
                )
                if len(hits) >= max_hits:
                    break
        if len(hits) >= max_hits:
            break
    hits.sort(key=lambda hit: (hit["edit_distance"], hit["start"], hit["strand"] == "-"))
    return hits[:max_hits]


def sequence_statistics(
    sequence: str, alphabet: str = "dna", exclude_ambiguous: bool = True
) -> dict[str, Any]:
    """Base composition with the kernel's denominator rule."""
    upper = _validate(sequence, alphabet)
    counts = {"A": 0, "C": 0, "G": 0, "T": 0}
    ambiguous = 0
    for char in upper:
        if char in counts:
            counts[char] += 1
        elif char == "U":
            counts["T"] += 1
        else:
            ambiguous += 1
    gc_count = counts["C"] + counts["G"]
    at_count = counts["A"] + counts["T"]
    unambiguous = counts["A"] + counts["C"] + counts["G"] + counts["T"]
    denominator = unambiguous if exclude_ambiguous else len(upper)
    gc_fraction = 0.0 if denominator == 0 else gc_count / denominator
    return {
        "length": len(upper),
        "gc_count": gc_count,
        "at_count": at_count,
        "ambiguous_count": ambiguous,
        "a": counts["A"],
        "c": counts["C"],
        "g": counts["G"],
        "t": counts["T"],
        "denominator": denominator,
        "gc_fraction": gc_fraction,
    }


def find_orfs(sequence: str, min_len: int = 90, limit: int = 1000) -> list[dict[str, Any]]:
    """ATG..stop on all six frames, with the kernel's coordinates and order."""
    upper = _validate(sequence, "dna")
    if min_len < 3:
        _raise_code("UNSUPPORTED_PARAMETER")
    reverse = reverse_complement(upper, "dna", False)
    found: list[dict[str, Any]] = []
    for frame in range(3):
        for strand, frame_seq in (("+", upper), ("-", reverse)):
            index = 0
            while index + 3 <= len(frame_seq):
                if frame_seq[index : index + 3] == "ATG":
                    cursor = index + 3
                    while cursor + 3 <= len(frame_seq):
                        if frame_seq[cursor : cursor + 3] in _STOP_CODONS:
                            end = cursor + 3
                            if end - index >= min_len:
                                found.append(
                                    {
                                        "start0": index,
                                        "end0": end,
                                        "start": index + 1,
                                        "end": end,
                                        "strand": strand,
                                        "frame": frame,
                                    }
                                )
                            index = cursor
                            break
                        cursor += 3
                index += 3
    found.sort(key=lambda item: (item["start0"], item["strand"] == "-", item["frame"]))
    return found[: min(limit, 1000)]


def translate_sequence(sequence: str, genetic_code_id: int = 1, frame: int = 0) -> dict[str, Any]:
    """Translate with Biopython's codon tables, keeping the kernel's warnings."""

    upper = _validate(sequence, "dna")
    if frame < 0 or frame > 2:
        _raise_code("UNSUPPORTED_PARAMETER")
    try:
        table = _codon_table(genetic_code_id)
    except KeyError:
        _raise_code("UNKNOWN_GENETIC_CODE")

    trimmed = upper[frame:]
    trailing = len(trimmed) % 3
    complete = trimmed[: len(trimmed) - trailing] if trailing else trimmed
    warnings: list[str] = []
    if trailing:
        warnings.append(f"{trailing} trailing base(s) ignored (partial codon)")

    protein_chars: list[str] = []
    internal_stops = 0
    ambiguous = 0
    for offset in range(0, len(complete), 3):
        codon = complete[offset : offset + 3]
        if any(base not in _DNA_ONLY for base in codon):
            ambiguous += 1
            protein_chars.append("X")
            continue
        residue = table.get(codon, "X")
        if residue == "*" and offset + 3 < len(complete):
            internal_stops += 1
        protein_chars.append(residue)
    if internal_stops:
        warnings.append(f"{internal_stops} internal stop codon(s)")
    if ambiguous:
        warnings.append(f"{ambiguous} ambiguous codon(s) rendered as X")

    return {
        "protein": "".join(protein_chars),
        "genetic_code_id": genetic_code_id,
        "frame": frame,
        "warnings": warnings,
        "codons": len(complete) // 3,
        "trailing_bases": trailing,
    }


def _codon_table(genetic_code_id: int) -> dict[str, str]:
    """Build a Biopython codon table into a plain dict, or raise KeyError."""
    from Bio.Data import CodonTable

    tables = CodonTable.unambiguous_dna_by_id
    if genetic_code_id not in tables:
        raise KeyError(genetic_code_id)
    table = tables[genetic_code_id]
    mapping = dict(table.forward_table)
    for codon in table.stop_codons:
        mapping[codon] = "*"
    return mapping


def kmer_counts(
    sequence: str,
    k: int = 4,
    canonical: bool = True,
    ambiguity_policy: str = "skip",
    max_items: int = 1000,
) -> dict[str, Any]:
    """k-mer counts with the kernel's canonicalisation and ordering."""
    upper = _validate(sequence, "dna")
    if not 1 <= k <= 32:
        _raise_code("UNSUPPORTED_PARAMETER")
    if ambiguity_policy not in {"skip", "reject"}:
        _raise_code("UNSUPPORTED_PARAMETER")

    total_windows = max(0, len(upper) - k + 1)
    counts: dict[str, int] = {}
    valid = 0
    skipped = 0
    for offset in range(total_windows):
        window = upper[offset : offset + k]
        if any(base not in _DNA_ONLY for base in window):
            if ambiguity_policy == "reject":
                _raise_code("INVALID_CHARACTER")
            skipped += 1
            continue
        valid += 1
        key = window
        if canonical:
            reverse = reverse_complement(window, "dna", False)
            if reverse < key:
                key = reverse
        counts[key] = counts.get(key, 0) + 1

    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    limited = len(ordered) > max_items
    return {
        "k": k,
        "canonical": canonical,
        "total_windows": total_windows,
        "valid_windows": valid,
        "skipped_windows": skipped,
        "distinct_kmers": len(counts),
        "limited": limited,
        "items": [[kmer, count] for kmer, count in ordered[:max_items]],
    }


def align_pairwise(
    query: str,
    target: str,
    alphabet: str = "dna",
    mode: str = "local",
    match_score: int = 2,
    mismatch_score: int = -3,
    gap_open: int = -5,
    gap_extend: int = -1,
) -> dict[str, Any]:
    """Pairwise alignment through Biopython's PairwiseAligner.

    ``cigar`` is emitted as run-length ``<n>M``/``<n>I``/``<n>D``, the same
    spelling the kernel produced, because the response model publishes it.
    """
    from Bio import Align
    from Bio.Align import substitution_matrices

    _validate(query, alphabet)
    _validate(target, alphabet)
    if mode not in {"local", "global"}:
        _raise_code("UNSUPPORTED_PARAMETER")
    config = {
        "match": match_score,
        "mismatch": mismatch_score,
        "gap_open": gap_open,
        "gap_extend": gap_extend,
    }

    aligner = Align.PairwiseAligner()
    aligner.mode = mode
    if alphabet == "protein":
        aligner.substitution_matrix = substitution_matrices.load("BLOSUM62")
        aligner.open_gap_score = config["gap_open"]
        aligner.extend_gap_score = config["gap_extend"]
    else:
        aligner.match_score = config["match"]
        aligner.mismatch_score = config["mismatch"]
        aligner.open_gap_score = config["gap_open"]
        aligner.extend_gap_score = config["gap_extend"]

    alignments = aligner.align(query, target)
    if len(alignments) == 0:
        return {
            "score": 0,
            "query_range": (1, 1),
            "target_range": (1, 1),
            "cigar": "",
            "identity": 0.0,
            "mode": mode,
        }
    best = alignments[0]
    score = aligner.score(query, target)
    # Biopython reports alignment bounds as numpy integers; converting once
    # here keeps the JSON payload plain Python ints.
    query_start, query_end = (int(value) for value in best.aligned[0][0])
    target_start, target_end = (int(value) for value in best.aligned[1][0])
    cigar, identity = _cigar_from_alignment(str(best[0]), str(best[1]))
    return {
        "score": int(score),
        "query_range": (query_start + 1, query_end),
        "target_range": (target_start + 1, target_end),
        "cigar": cigar,
        "identity": identity,
        "mode": mode,
    }


def _cigar_from_alignment(aligned_query: str, aligned_target: str) -> tuple[str, float]:
    """Run-length CIGAR and identity over the aligned columns."""
    operations: list[tuple[str, int]] = []
    identities = 0
    columns = 0
    for left, right in zip(aligned_query, aligned_target):
        if left == "-":
            operation = "D"
        elif right == "-":
            operation = "I"
        else:
            operation = "M"
            columns += 1
            if left == right:
                identities += 1
        if operations and operations[-1][0] == operation:
            operations[-1] = (operation, operations[-1][1] + 1)
        else:
            operations.append((operation, 1))
    cigar = "".join(f"{count}{operation}" for operation, count in operations)
    identity = 0.0 if columns == 0 else identities / columns
    return cigar, identity


def capabilities() -> dict[str, Any]:
    """Advertise the engine, its version and the codon tables it carries.

    The compiled kernel implemented code 1 only; Biopython ships the full
    NCBI table set, so the list is reported from the tables rather than
    hard-coded.
    """
    from Bio.Data import CodonTable

    return {
        "engine": ENGINE,
        "engine_version": ENGINE_VERSION,
        "genetic_codes": sorted(CodonTable.unambiguous_dna_by_id),
        "programs": list(PROGRAMS),
    }


#: Every operation this engine answers. The service advertises these so a
#: client can discover the difference from the compiled kernel instead of
#: guessing from a 404.
PROGRAMS = (
    "reverse-complement",
    "match",
    "align",
    "stats",
    "orfs",
    "translate",
    "kmers",
    "inspect",
    "intervals/overlap",
    "convert",
    "restriction-sites",
    "protein-properties",
    "melting-temp",
    "multiple-alignment",
    "tree",
)


#: Region budget the interval endpoint accepts, mirroring the kernel constant.
MAX_REGIONS = 1000
MAX_HITS_LIMIT = 1000


def overlap_intervals(
    intervals: list[tuple[int, int, int]],
    regions: list[tuple[int, int]],
    max_hits: int = 1000,
) -> list[dict[str, Any]]:
    """Interval/region overlaps with the kernel's half-open semantics.

    ``intervals`` are ``(start0, end0, record_index)``; ``regions`` are
    ``(start0, end0)``. Both are half-open, and a region that merely touches an
    interval does not overlap it. ``covered_bp`` is the union length, not the
    sum, so overlapping records are not counted twice.
    """
    if len(regions) > MAX_REGIONS:
        _raise_code("BUDGET_EXCEEDED")
    cap = min(max_hits, MAX_HITS_LIMIT)

    # Sorted by start so each region can stop early and the union is cheap.
    ordered = sorted(
        ((int(start), int(end), int(record)) for start, end, record in intervals),
        key=lambda item: item[0],
    )

    results: list[dict[str, Any]] = []
    for raw_start, raw_end in regions:
        start, end = int(raw_start), int(raw_end)
        if end <= start:
            _raise_code("INVALID_INTERVAL")
        hits: list[list[int]] = []
        count = 0
        covered: list[tuple[int, int]] = []
        for interval_start, interval_end, record in ordered:
            if interval_start >= end:
                break
            if interval_end <= start:
                continue
            count += 1
            overlap_start = max(start, interval_start)
            overlap_end = min(end, interval_end)
            overlap_bp = overlap_end - overlap_start
            if overlap_bp <= 0:
                # Touching intervals are reported by the range scan but do not
                # overlap; the kernel required a strictly positive width.
                continue
            covered.append((overlap_start, overlap_end))
            if len(hits) < cap:
                hits.append([interval_start, interval_end, overlap_bp, record])
        results.append(
            {
                "overlap_count": count,
                "covered_bp": _union_length(covered),
                "limited": count > cap,
                "hits": hits,
            }
        )
    return results


def _union_length(spans: list[tuple[int, int]]) -> int:
    """Total length covered by the union of half-open spans."""
    if not spans:
        return 0
    ordered = sorted(spans)
    total = 0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
        else:
            total += current_end - current_start
            current_start, current_end = start, end
    return total + (current_end - current_start)


# ---------------------------------------------------------------------------
# Capabilities the compiled kernel never had. Each one is a thin, documented
# wrapper over the Biopython reference implementation; the response shapes are
# declared in `schemas/sequence_tools.py`.
# ---------------------------------------------------------------------------

#: Formats this engine can read and write. The list is explicit so an
#: unsupported name is a 422 instead of a stack trace from deep inside SeqIO.
READABLE_FORMATS = ("fasta", "genbank", "embl", "tab")
WRITABLE_FORMATS = ("fasta", "genbank", "embl", "tab")


def convert_format(
    data: str,
    source_format: str,
    target_format: str,
    max_records: int = 100,
) -> dict[str, Any]:
    """Convert records between the supported formats.

    Only the caller-supplied text is parsed: this never reads a file path, so
    the endpoint cannot be used to probe the filesystem. ``max_records`` bounds
    the work the same way the other endpoints' ``limit`` does.
    """
    import io

    from Bio import SeqIO

    if source_format not in READABLE_FORMATS:
        _raise_code("UNSUPPORTED_PARAMETER")
    if target_format not in WRITABLE_FORMATS:
        _raise_code("UNSUPPORTED_PARAMETER")
    if not data.strip():
        _raise_code("INVALID_RECORD")

    try:
        records = list(SeqIO.parse(io.StringIO(data), source_format))
    except Exception as exc:  # SeqIO raises a variety of parser errors
        raise BioEngineError("INVALID_RECORD", f"could not parse {source_format}: {exc}") from exc
    if not records:
        _raise_code("INVALID_RECORD")

    limited = len(records) > max_records
    kept = records[:max_records]
    # GenBank/EMBL output requires a `molecule_type` annotation; a FASTA source
    # does not carry one, so an explicit unknown value is set instead of letting
    # SeqIO raise. "DNA" is the safe default for this database.
    if target_format in {"genbank", "embl"}:
        for record in kept:
            record.annotations.setdefault("molecule_type", "DNA")
    out = io.StringIO()
    try:
        SeqIO.write(kept, out, target_format)
    except ValueError as exc:
        raise BioEngineError("INVALID_RECORD", f"could not write {target_format}: {exc}") from exc
    return {
        "source_format": source_format,
        "target_format": target_format,
        "record_count": len(kept),
        "total_records": len(records),
        "limited": limited,
        "output": out.getvalue(),
    }


#: Enzymes are resolved by name; the set is restricted to the canonical
#: REBASE entries Biopython ships so a typo is a 422 rather than an exception.
def restriction_sites(
    sequence: str,
    enzymes: list[str] | None = None,
    circular: bool = False,
    max_hits: int = 1000,
) -> dict[str, Any]:
    """Cut sites of one or more restriction enzymes on a DNA sequence.

    ``enzymes=None`` scans every enzyme Biopython knows and reports only the
    ones with a site, which is what "which enzymes cut this sequence" means.
    Coordinates are 1-based inclusive on the input sequence.
    """
    from Bio import Restriction
    from Bio.Seq import Seq

    upper = _validate(sequence, "dna")
    if any(base not in _DNA_ONLY for base in upper):
        # A degenerate base is not a physical molecule; the enzymes would
        # silently decline to cut, which reads as "no site" rather than
        # "cannot answer".
        _raise_code("INVALID_CHARACTER")
    molecule = Seq(upper)
    cap = min(max_hits, MAX_HITS_LIMIT)

    if enzymes:
        resolved = []
        for name in enzymes:
            enzyme = getattr(Restriction, name, None)
            if enzyme is None or not hasattr(enzyme, "site"):
                raise BioEngineError("UNSUPPORTED_PARAMETER", f"unknown enzyme: {name}")
            resolved.append(enzyme)
        candidates = resolved
    else:
        # `AllEnzymes` is populated at import time by the Restriction module and
        # is present at runtime, but the published stubs do not declare it, so
        # the access goes through getattr with an explicit default.
        all_enzymes = getattr(Restriction, "AllEnzymes", ())
        candidates = [e for e in all_enzymes if hasattr(e, "site")]

    results: list[dict[str, Any]] = []
    total_hits = 0
    for enzyme in candidates:
        try:
            analysis = enzyme.search(molecule, linear=not circular)
        except Exception:
            # An enzyme with a non-DNA site (e.g. a protein-only entry) cannot
            # cut this molecule; skip it rather than failing the whole scan.
            continue
        if not analysis:
            continue
        cuts = [int(position) for position in analysis]
        sites_text = str(enzyme.site)
        results.append(
            {
                "enzyme": str(enzyme),
                "site": sites_text,
                # Biopython reports the cut position; the recognition site
                # starts one base earlier for a 5' overhang enzyme, so the
                # site start is derived from the cut and the site width.
                "cut_positions": cuts[:cap],
                "site_starts": [
                    max(1, position - len(sites_text) + 1) for position in cuts[:cap]
                ],
                "count": len(cuts),
                "limited": len(cuts) > cap,
            }
        )
        total_hits += len(cuts)

    results.sort(key=lambda item: (-item["count"], item["enzyme"]))
    return {
        "sequence_length": len(upper),
        "circular": circular,
        "enzyme_count": len(results),
        "total_cut_sites": total_hits,
        "enzymes": results[:cap],
        "limited": len(results) > cap,
    }


def protein_properties(protein: str) -> dict[str, Any]:
    """Molecular weight, isoelectric point, extinction and hydrophobicity.

    The protein is validated against the amino-acid alphabet first: ProtParam
    raises on an unexpected character, and that message is not part of this
    API's error vocabulary.
    """
    from Bio.SeqUtils.ProtParam import ProteinAnalysis

    upper = _validate(protein, "protein")
    stripped = upper.rstrip("*")
    if not stripped:
        _raise_code("EMPTY_SEQUENCE")
    analysis = ProteinAnalysis(stripped)
    return {
        "length": len(stripped),
        "molecular_weight": round(analysis.molecular_weight(), 2),
        "isoelectric_point": round(analysis.isoelectric_point(), 2),
        "aromaticity": round(analysis.aromaticity(), 4),
        "instability_index": round(analysis.instability_index(), 2),
        "gravy": round(analysis.gravy(), 4),
        "extinction_coefficient": [int(value) for value in analysis.molar_extinction_coefficient()],
        "amino_acid_composition": {
            residue: round(fraction, 4)
            for residue, fraction in analysis.amino_acids_percent.items()
        },
    }


def melting_temp(
    sequence: str,
    method: str = "nearest_neighbor",
    dna_conc: float = 50.0,
    salt_conc: float = 50.0,
) -> dict[str, Any]:
    """Primer melting temperature by the requested method.

    ``wallace`` is the 2(A+T)+4(G+C) rule for short primers; ``gc`` is the
    GC-content formula; ``nearest_neighbor`` is the thermodynamic method the
    primer-design literature uses. The response reports which ran so a caller
    never compares numbers from different methods by accident.
    """
    from Bio.SeqUtils import MeltingTemp as mt

    upper = _validate(sequence, "dna")
    if any(base not in _DNA_ONLY for base in upper):
        _raise_code("INVALID_CHARACTER")
    if len(upper) > 200:
        # The thermodynamic tables are parameterised on short oligos; beyond
        # this the number is not a primer Tm and would be misleading.
        _raise_code("UNSUPPORTED_PARAMETER")

    # Biopython's stubs type the concentration parameters as int although the
    # formulas are continuous; rounding here keeps the call type-correct and is
    # far below the precision of a Tm estimate.
    salt = int(round(salt_conc))
    dna = int(round(dna_conc))
    if method == "wallace":
        value = mt.Tm_Wallace(upper)
    elif method == "gc":
        value = mt.Tm_GC(upper, Na=salt)
    elif method == "nearest_neighbor":
        value = mt.Tm_NN(upper, Na=salt, dnac1=dna, dnac2=dna)
    else:
        _raise_code("UNSUPPORTED_PARAMETER")
    return {
        "method": method,
        "length": len(upper),
        "gc_fraction": round(
            sum(1 for base in upper if base in {"G", "C"}) / len(upper), 4
        ),
        "melting_temp_c": round(float(value), 2),
        "dna_conc_nm": dna_conc,
        "salt_conc_mm": salt_conc,
    }


def multiple_alignment(
    sequences: list[str],
    alphabet: str = "dna",
    mode: str = "global",
) -> dict[str, Any]:
    """Progressively align several sequences and derive a distance matrix.

    Pairwise alignment is exact; for more than two sequences this is a
    progressive profile alignment (the same strategy ClustalW uses), not an
    optimal MSA. The response states that so a caller does not read the score
    as a global optimum.
    """
    from Bio import Align
    from Bio.Align import substitution_matrices

    if not 2 <= len(sequences) <= 50:
        _raise_code("UNSUPPORTED_PARAMETER")
    for candidate in sequences:
        _validate(candidate, alphabet)
    if mode not in {"local", "global"}:
        _raise_code("UNSUPPORTED_PARAMETER")

    # Gap penalties are real numbers in Biopython's API (some matrices use
    # fractional extension costs), so both branches must agree on the type.
    gap_open: float
    gap_extend: float
    if alphabet == "protein":
        matrix = substitution_matrices.load("BLOSUM62")
        gap_open, gap_extend = -11.0, -1.0
    else:
        matrix = substitution_matrices.load("NUC.4.4")
        gap_open, gap_extend = -10.0, -0.5

    aligner = Align.PairwiseAligner()
    aligner.mode = mode
    aligner.substitution_matrix = matrix
    aligner.open_gap_score = gap_open
    aligner.extend_gap_score = gap_extend

    aligned = list(sequences)
    # Progressive: align each remaining sequence to the current top row, which
    # is what keeps the already-aligned columns stable. Each pairwise step is
    # gap-left-aligned first, so an indel lands where the MSA convention puts
    # it instead of wherever the pairwise tie-break happened to place it.
    for index in range(1, len(aligned)):
        pairwise = aligner.align(aligned[0], aligned[index])[0]
        top, bottom = _left_align_gaps(str(pairwise[0]), str(pairwise[1]))
        previous = aligned[:index]
        aligned = [
            _graft(seq, top) if position == 0 else seq
            for position, seq in enumerate(previous)
        ] + aligned[index:]
        aligned[0] = top
        aligned[index] = bottom

    width = len(aligned[0])
    if any(len(row) != width for row in aligned):
        # A progressive pass that produced ragged rows is a bug, not a result;
        # answering with them would corrupt every downstream column position.
        raise BioEngineError("INVALID_RECORD", "progressive alignment produced ragged rows")

    identity_matrix = _identity_matrix(aligned)
    return {
        "aligned_sequences": aligned,
        "column_count": width,
        "sequence_count": len(aligned),
        "method": "progressive",
        "mode": mode,
        "distance_matrix": _distance_matrix(identity_matrix),
        "identity_matrix": identity_matrix,
    }


def _graft(existing: str, aligned_top: str) -> str:
    """Re-pad an already-aligned row onto the new column layout.

    Every column where the top row has a gap is a column the earlier rows did
    not have; they take a gap there too. The remaining columns receive the
    row's own residues in order, which cannot run out because the top row was
    derived from the same ungapped sequences.
    """
    out: list[str] = []
    source = iter(existing)
    for column_char in aligned_top:
        if column_char == "-":
            out.append("-")
        else:
            out.append(next(source, "-"))
    return "".join(out)


def _left_align_gaps(top: str, bottom: str) -> tuple[str, str]:
    """Shift each gap run as far left as the other row allows.

    This is the standard MSA post-pass: two alignments that differ only in
    where a gap sits should render the same picture, and the convention is to
    push gaps towards the start of the sequence. Runs are moved as a whole, so
    a four-base deletion reaches the first legal column in one pass.
    """
    top_chars = list(top)
    bottom_chars = list(bottom)
    for chars, other in ((top_chars, bottom_chars), (bottom_chars, top_chars)):
        index = 0
        while index < len(chars):
            if chars[index] != "-":
                index += 1
                continue
            run_end = index
            while run_end < len(chars) and chars[run_end] == "-":
                run_end += 1
            # The run may start at the first column whose predecessors in the
            # other row are all gap-free and can be shifted right.
            target = index
            while target > 0 and other[target - 1] != "-" and chars[target - 1] != "-":
                target -= 1
            if target < index:
                block = chars[index:run_end]
                del chars[index:run_end]
                chars[target:target] = block
            index = run_end
    return "".join(top_chars), "".join(bottom_chars)


def _identity_matrix(aligned: list[str]) -> list[list[float]]:
    size = len(aligned)
    matrix = [[1.0] * size for _ in range(size)]
    for row in range(size):
        for column in range(row + 1, size):
            identical = 0
            columns = 0
            for left, right in zip(aligned[row], aligned[column]):
                if left == "-" and right == "-":
                    continue
                columns += 1
                if left == right:
                    identical += 1
            score = 0.0 if columns == 0 else identical / columns
            matrix[row][column] = round(score, 4)
            matrix[column][row] = matrix[row][column]
    return matrix


def _distance_matrix(identity: list[list[float]]) -> list[list[float]]:
    return [[round(1.0 - value, 4) for value in row] for row in identity]


def neighbor_joining_tree(
    sequences: list[str],
    labels: list[str] | None = None,
    alphabet: str = "dna",
) -> dict[str, Any]:
    """Neighbour-joining tree over the sequences, as Newick text.

    The distances come from pairwise identity (p-distance). A tree built from a
    handful of short sequences is a sketch of relatedness, not a phylogeny, and
    the response field says so.
    """
    from Bio.Align import MultipleSeqAlignment
    from Bio.Phylo.TreeConstruction import DistanceCalculator, DistanceTreeConstructor
    from Bio.Seq import Seq
    from Bio.SeqRecord import SeqRecord

    if not 3 <= len(sequences) <= 50:
        # Two sequences cannot be tree-built in any meaningful way.
        _raise_code("UNSUPPORTED_PARAMETER")
    for candidate in sequences:
        _validate(candidate, alphabet)
    if labels is not None and len(labels) != len(sequences):
        _raise_code("UNSUPPORTED_PARAMETER")

    names = labels or [f"seq{index + 1}" for index in range(len(sequences))]
    if len(set(names)) != len(names):
        # Duplicate labels make the Newick text ambiguous, and the parser
        # silently merges them.
        _raise_code("UNSUPPORTED_PARAMETER")

    align = multiple_alignment(sequences, alphabet=alphabet, mode="global")
    aligned = align["aligned_sequences"]

    # DistanceCalculator consumes a MultipleSeqAlignment, not a bare record
    # list; building it directly avoids a write/read round trip through FASTA.
    alignment = MultipleSeqAlignment(
        [
            SeqRecord(Seq(row), id=name, description="")
            for name, row in zip(names, aligned)
        ]
    )

    calculator = DistanceCalculator("identity")
    distances = calculator.get_distance(alignment)
    tree = DistanceTreeConstructor().nj(distances)
    return {
        "newick": tree.format("newick").strip(),
        "leaf_count": len(tree.get_terminals()),
        "labels": names,
        "distance_model": "identity",
        "method": "neighbor-joining",
        "caveat": (
            "distances are p-distances over a progressive alignment; "
            "treat the topology as indicative"
        ),
    }


# ---------------------------------------------------------------------------
# Format validation. The compiled kernel parsed FASTA/FASTQ/BED itself; here
# Biopython's parsers do the work, and the same bounds and error codes apply.
# ---------------------------------------------------------------------------

#: Record and per-record byte budgets, mirroring the kernel's constants.
MAX_RECORDS = 100_000
MAX_RECORD_BYTES = 1_048_576


def validate_fasta(data: bytes) -> dict[str, Any]:
    """Validate FASTA bytes and return a bounded record listing."""
    import io

    from Bio import SeqIO

    if not data:
        _raise_code("INVALID_RECORD")
    try:
        handle = io.StringIO(data.decode("utf-8", errors="replace"))
        records: list[tuple[str, int]] = []
        truncated = False
        for record in SeqIO.parse(handle, "fasta"):
            if len(record.seq) > MAX_RECORD_BYTES:
                _raise_code("BUDGET_EXCEEDED")
            if len(record.seq) == 0:
                _raise_code("INVALID_RECORD")
            records.append((record.id or record.description or "", len(record.seq)))
            if len(records) >= MAX_RECORDS:
                truncated = True
                break
    except BioEngineError:
        raise
    except Exception as exc:
        raise BioEngineError("INVALID_RECORD", f"invalid FASTA: {exc}") from exc
    if not records:
        _raise_code("INVALID_RECORD")
    return {"total_records": len(records), "records": records, "truncated": truncated}


def validate_fastq(data: bytes) -> dict[str, Any]:
    """Validate FASTQ bytes. Sequence and quality lengths must match."""
    import io

    from Bio import SeqIO

    if not data:
        _raise_code("INVALID_RECORD")
    try:
        handle = io.StringIO(data.decode("utf-8", errors="replace"))
        records: list[tuple[str, int]] = []
        truncated = False
        for record in SeqIO.parse(handle, "fastq"):
            if len(record.seq) > MAX_RECORD_BYTES:
                _raise_code("BUDGET_EXCEEDED")
            if len(record.seq) == 0:
                _raise_code("INVALID_RECORD")
            quality = getattr(record, "letter_annotations", {}).get("phred_quality")
            if quality is not None and len(quality) != len(record.seq):
                # Biopython raises on this inside its own parser; the explicit
                # check documents the contract the kernel enforced.
                _raise_code("INVALID_RECORD")
            records.append((record.id or record.description or "", len(record.seq)))
            if len(records) >= MAX_RECORDS:
                truncated = True
                break
    except BioEngineError:
        raise
    except Exception as exc:
        raise BioEngineError("INVALID_RECORD", f"invalid FASTQ: {exc}") from exc
    if not records:
        _raise_code("INVALID_RECORD")
    return {"total_records": len(records), "records": records, "truncated": truncated}


def validate_bed(data: bytes) -> int:
    """Validate BED bytes and return the record count.

    BED is tab-delimited with at least three columns; the kernel counted valid
    lines rather than modelling them, and the same rule applies here.
    """
    if not data:
        _raise_code("INVALID_RECORD")
    records = 0
    for raw_line in data.decode("utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "track", "browser")):
            continue
        fields = line.split("\t")
        if len(fields) < 3:
            _raise_code("INVALID_RECORD")
        try:
            start, end = int(fields[1]), int(fields[2])
        except ValueError:
            _raise_code("INVALID_RECORD")
        if start < 0 or end < start:
            _raise_code("INVALID_INTERVAL")
        records += 1
        if records >= MAX_RECORDS:
            break
    if records == 0:
        _raise_code("INVALID_RECORD")
    return records
