"""Test package for the SoyMutDB worker.

Present so cross-module imports resolve as ``tests.<module>`` in every
invocation: pytest's rootdir rule puts ``apps/worker`` on ``sys.path``, and a
namespace package there would otherwise lose to the repository-root ``tests``
directory (``tests/e2e``, ``tests/load``), which has no matching module.

Mirrors ``apps/api/tests/__init__.py``. Removing this file breaks
``pytest apps/worker/tests`` collection with
``ModuleNotFoundError: No module named 'tests.test_module_tsv_postgres_integration'``.
"""
