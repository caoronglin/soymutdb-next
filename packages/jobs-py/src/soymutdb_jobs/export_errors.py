"""Public variant-export failure vocabulary, independent of diagnostics.

Never echo exception strings, SQL, parameters, paths, or identifiers. Details
belong in access-controlled worker logs, correlated by the export id.
"""

EXPORT_FAILED_MESSAGE = "Export failed. Please submit a new export or contact support."


def public_export_error(message: str | None) -> str | None:
    """Hide even legacy stored diagnostics behind a fixed public message."""
    return EXPORT_FAILED_MESSAGE if message else None
