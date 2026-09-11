"""Test package for the SoyMutDB worker.

Present (as in ``apps/api/tests/__init__.py``) so that tests can import shared
helpers from each other by their package path -- e.g.
``from tests.test_module_tsv_postgres_integration import postgres_engine``.
Without it, ``tests`` is not an importable name and collection of any module
that reuses a fixture dies with::

    ModuleNotFoundError: No module named 'tests.test_module_tsv_postgres_integration'

Pytest's default ``prepend`` import mode puts the test directory itself on
``sys.path`` and imports each file as a top-level module. That works for
isolated modules but not for cross-module imports, and it also silently
mis-collects when two files share a basename. The package marker makes the
imports explicit and stable.
"""
