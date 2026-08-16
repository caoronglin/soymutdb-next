"""Re-export the shared module tabular schema registry.

The pure validator lives in ``soymutdb_jobs.module_schema`` so the API and
the worker can share one implementation without importing each other.
"""

from __future__ import annotations

from soymutdb_jobs.module_schema import (  # noqa: F401
    MODULE_SCHEMAS,
    SUPPORTED_MODULE_FORMATS,
    ModuleTsvSchema,
    TsvColumn,
    ValidationError,
    ValidationResult,
    detect_format,
    get_schema,
    render_module_template,
    validate_module_file,
    validate_tsv,
)

__all__ = [
    "MODULE_SCHEMAS",
    "SUPPORTED_MODULE_FORMATS",
    "ModuleTsvSchema",
    "TsvColumn",
    "ValidationError",
    "ValidationResult",
    "detect_format",
    "get_schema",
    "render_module_template",
    "validate_module_file",
    "validate_tsv",
]
