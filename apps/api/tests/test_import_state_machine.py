import pytest

from app.models.data_publishing import ImportStatus
from app.services.import_state_machine import InvalidStateTransition, assert_transition


def test_import_transitions_reject_skipping_validation():
    with pytest.raises(InvalidStateTransition, match="uploading -> ingesting"):
        assert_transition(ImportStatus.UPLOADING, ImportStatus.INGESTING)


def test_failed_import_can_retry_from_validation_but_published_cannot():
    assert_transition(ImportStatus.FAILED, ImportStatus.VALIDATING)
    with pytest.raises(InvalidStateTransition):
        assert_transition(ImportStatus.PUBLISHED, ImportStatus.INGESTING)
