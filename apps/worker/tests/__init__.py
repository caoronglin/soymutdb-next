"""Test package for the SoyMutDB worker.

Present (as in ``apps/api/tests/__init__.py``) so tests can import shared
helpers from each other by their package path -- e.g.
``from tests.test_module_tsv_postgres_integration import postgres_engine``.

Two things make the marker load-bearing rather than cosmetic:

1. Pytest's default ``prepend`` import mode puts the *test directory* on
   ``sys.path`` and imports each file as a top-level module. That is enough for
   an isolated file, but not for a cross-module import.
2. There is also a repository-root ``tests/`` directory (``tests/e2e``,
   ``tests/load``). Without this ``__init__.py`` the name ``tests`` resolves to
   that directory as a namespace package, and the worker's module is looked up
   inside it -- so the import fails even though ``apps/worker`` is on the path.

Either way collection aborts with::

    ModuleNotFoundError: No module named 'tests.test_module_tsv_postgres_integration'

A collection error aborts the whole run, so without this file the rest of the
worker suite never executes.
"""
