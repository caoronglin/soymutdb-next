"""Export cleanup must see every S3 page, not just the first 1000 keys.

``list_objects_v2`` pages at 1000 keys. A cleanup that reads one page reports
a partial result and leaves every older artifact after the first page on
disk forever, while still logging a successful run. These tests pin the
paginated listing and the cleanup built on it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from soymutdb_worker.tasks import export as export_task
from soymutdb_worker.utils import s3 as s3_utils


class _FakeS3:
    """A paged list_objects_v2 client that records every request."""

    def __init__(self, pages: list[dict]) -> None:
        self.pages = list(pages)
        self.list_calls: list[dict] = []
        self.deleted: list[tuple[str, str]] = []

    def list_objects_v2(self, **kwargs):
        self.list_calls.append(kwargs)
        return self.pages.pop(0)

    def delete_object(self, *, Bucket: str, Key: str):
        self.deleted.append((Bucket, Key))
        return {}


def _page(keys: list[str], *, token: str | None = None) -> dict:
    page = {"Contents": [{"Key": key} for key in keys]}
    if token is not None:
        page["IsTruncated"] = True
        page["NextContinuationToken"] = token
    else:
        page["IsTruncated"] = False
    return page


def test_list_objects_follows_continuation_tokens(monkeypatch):
    fake = _FakeS3([_page(["a"], token="next"), _page(["b", "c"])])
    monkeypatch.setattr(s3_utils, "get_s3_client", lambda: fake)

    objects = s3_utils.list_objects("exports/exports/")

    assert [obj["Key"] for obj in objects] == ["a", "b", "c"]
    assert fake.list_calls == [
        {"Bucket": "exports", "Prefix": "exports/", "MaxKeys": 1000},
        {
            "Bucket": "exports",
            "Prefix": "exports/",
            "MaxKeys": 1000,
            "ContinuationToken": "next",
        },
    ]


def test_list_objects_honours_a_total_cap(monkeypatch):
    fake = _FakeS3([_page(["a"], token="next"), _page(["b", "c"])])
    monkeypatch.setattr(s3_utils, "get_s3_client", lambda: fake)

    objects = s3_utils.list_objects("exports/exports/", max_keys=2)

    assert [obj["Key"] for obj in objects] == ["a", "b"]
    assert fake.list_calls[1]["MaxKeys"] == 1


def test_cleanup_deletes_old_artifacts_from_every_page(monkeypatch):
    old = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    old_page = {
        "Contents": [
            {"Key": "exports/old-a.tsv.gz", "LastModified": datetime.fromisoformat(old)},
        ],
        "IsTruncated": True,
        "NextContinuationToken": "next",
    }
    now = datetime.now(UTC)
    new_page = {
        "Contents": [
            {"Key": "exports/new.tsv.gz", "LastModified": now},
        ],
        "IsTruncated": False,
    }
    oldest = (now - timedelta(days=30)).replace(tzinfo=None)  # naive on purpose
    old_page["Contents"].append(
        {"Key": "exports/old-b.tsv.gz", "LastModified": oldest}
    )
    fake = _FakeS3([old_page, new_page])
    monkeypatch.setattr(s3_utils, "get_s3_client", lambda: fake)
    monkeypatch.setattr(export_task, "get_setting", lambda *a, **k: "exports")

    result = export_task.cleanup_old_exports.run()

    assert result == {"deleted": 2}
    assert sorted(key for _, key in fake.deleted) == [
        "exports/old-a.tsv.gz",
        "exports/old-b.tsv.gz",
    ]