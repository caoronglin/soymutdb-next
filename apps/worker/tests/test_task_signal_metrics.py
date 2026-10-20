"""Celery signal senders must resolve to the same routing labels as tasks."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("signal,metric", [
    ("_observe_task_success", "TASKS_TOTAL"),
    ("_observe_task_failure", "TASK_FAILURES_TOTAL"),
])
@pytest.mark.parametrize("sender,queue", [
    (SimpleNamespace(name="soymutdb_worker.tasks.export.export_variants"), "export"),
    ("soymutdb_worker.tasks.blast.run_blast", "blast"),
    (None, "unknown"),
    (SimpleNamespace(name=None), "unknown"),
    (SimpleNamespace(name="unregistered.task"), "default"),
])
def test_task_signal_counts_sender_queue(monkeypatch, signal, metric, sender, queue):
    from soymutdb_worker import main

    counter = Mock()
    monkeypatch.setattr(main.worker_metrics, metric, counter)
    getattr(main, signal)(sender=sender)
    counter.labels.assert_called_once_with(queue=queue)
    counter.labels.return_value.inc.assert_called_once_with()
