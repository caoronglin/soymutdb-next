"""Residue digests: one spelling for the two places that publish them.

``transcript_sequences.sha256`` is written once by the residue importer, and the
gene sequence loader computes a digest for the residues it *derives* (the
reference slice and the spliced transcript). Both end up in the same
``checksum`` field of the gene detail contract, so both must hash the same
bytes: the residue string exactly as served -- uppercase ASCII, no whitespace.
Two independent hashes would eventually disagree, and the contract would be
publishing a checksum that verifies nothing.
"""

from __future__ import annotations

import hashlib


def residue_digest(sequence: str) -> str:
    """Hex sha256 of a residue string, as the ``checksum`` field publishes it."""
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


__all__ = ["residue_digest"]
