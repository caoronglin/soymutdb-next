import pytest

from app.services.media_service import list_media_assets


class _Rows:
    def all(self):
        return []


class _CountingSession:
    def __init__(self):
        self.scalar_calls = []
        self.execute_calls = []

    async def scalar(self, statement):
        self.scalar_calls.append(statement)
        return 0

    async def execute(self, statement):
        self.execute_calls.append(statement)
        return _Rows()


@pytest.mark.asyncio
async def test_media_list_uses_constant_query_count_and_grouped_usage_join():
    """A page must not issue one usage-count query per media asset."""
    db = _CountingSession()
    rows, total = await list_media_assets(db, page=1, page_size=100)

    assert rows == []
    assert total == 0
    assert len(db.scalar_calls) == 1
    assert len(db.execute_calls) == 1
    sql = str(db.execute_calls[0])
    assert "LEFT OUTER JOIN" in sql
    assert "count(" in sql.lower()
    assert "GROUP BY media_assets.id" in sql
    assert "ORDER BY media_assets.created_at DESC, media_assets.id DESC" in sql
