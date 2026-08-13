from app.models.content import ReleaseStatus
from app.models.data_publishing import ImportStatus
from app.models.import_task import ImportTask


def test_release_and_dataset_states_are_exactly_the_approved_vocabulary():
    assert {state.value for state in ImportStatus} == {
        "uploading", "validating", "ingesting", "ready", "published", "failed", "rolled_back"
    }
    assert {state.value for state in ReleaseStatus} == {
        "draft", "validated", "ready", "published", "rolled_back"
    }


def test_import_task_has_idempotency_and_dataset_foreign_key():
    table = ImportTask.__table__
    assert {"data_set_id", "idempotency_key", "error_detail", "failed_batch"} <= set(table.c.keys())
    assert any(fk.target_fullname == "data_sets.id" for fk in table.c.data_set_id.foreign_keys)
