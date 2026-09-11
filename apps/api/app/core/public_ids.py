"""Public identifier issuance for mutant lines.

Engineering default (pending product-owner confirmation of the final
scheme): ``SM`` + 10 Crockford-Base32 characters drawn from a
cryptographically secure source. Public ids are stable, unique and are
never derived from the private persistence key or the internal lab
designation.
"""

from __future__ import annotations

import secrets

# Crockford Base32 alphabet (no I, L, O, U to avoid transcription errors).
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_BODY_LENGTH = 10
_PREFIX = "SM"


def generate_public_id() -> str:
    """Return a new random public id, e.g. ``SM7K3ZQ9P2A``."""
    body = "".join(secrets.choice(_ALPHABET) for _ in range(_BODY_LENGTH))
    return f"{_PREFIX}{body}"


def normalize_public_id(value: str) -> str:
    """Normalize user input: uppercase and map Crockford look-alikes.

    Only the classic transcription confusions are mapped (I/L→1, O→0).
    ``U`` is not mapped: issued ids never contain it, so mapping it could
    only create collisions, never resolve legitimate input.
    """
    cleaned = value.strip().upper().replace("-", "")
    trans = str.maketrans({"I": "1", "L": "1", "O": "0"})
    return cleaned.translate(trans)


__all__ = ["generate_public_id", "normalize_public_id"]
