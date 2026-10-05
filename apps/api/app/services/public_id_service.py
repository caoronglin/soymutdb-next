"""Public identifier issuance for mutant lines.

Issuance is the only sanctioned way to assign ``public_id`` values. Rules:

- An existing ``public_id`` is never changed, reassigned or overwritten.
- New identifiers come from :func:`app.core.public_ids.generate_public_id`
  (crypto-secure Crockford-Base32), never from the private persistence key
  or the lab designation.
- A candidate collision with an already-issued identifier triggers a retry
  with a fresh candidate, bounded by ``MAX_ISSUANCE_ATTEMPTS``; exhaustion
  surfaces an explicit :class:`PublicIdConflictError` instead of silently
  reassigning someone else's id.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.public_ids import generate_public_id
from ..models.variant import MutantLine

MAX_ISSUANCE_ATTEMPTS = 5


class PublicIdConflictError(RuntimeError):
    """Raised when unique public-id issuance exhausts its retry budget."""


async def ensure_public_id(db: AsyncSession, mutant_line: MutantLine) -> str:
    """Return the line's public id, issuing one only when it is missing.

    The caller owns the transaction: this helper flushes so the unique
    constraint is exercised, and rolls back to the enclosing savepoint on a
    collision before retrying with a fresh candidate.
    """
    if mutant_line.public_id:
        return mutant_line.public_id

    for _ in range(MAX_ISSUANCE_ATTEMPTS):
        try:
            # A nested savepoint bounds the failure: a collision rolls back
            # only the failed assignment, never enclosing seeded state.
            async with db.begin_nested():
                mutant_line.public_id = generate_public_id()
        except IntegrityError:
            # Unique conflict with an already-issued id (or a concurrent
            # issuer): discard the candidate and retry with a fresh one.
            continue
        return mutant_line.public_id

    raise PublicIdConflictError(
        "could not issue a unique public_id after "
        f"{MAX_ISSUANCE_ATTEMPTS} attempts"
    )


__all__ = ["PublicIdConflictError", "ensure_public_id"]
