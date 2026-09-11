from sqlalchemy.dialects import postgresql

from app.core.audit import cleanup_old_audit_logs


class _Result:
    rowcount = 2


class _Session:
    def __init__(self):
        self.statement = None
        self.committed = False

    async def execute(self, statement):
        self.statement = statement
        return _Result()

    async def commit(self):
        self.committed = True


async def test_cleanup_retains_news_lifecycle_audit_records() -> None:
    session = _Session()

    assert await cleanup_old_audit_logs(session, days=1) == 2
    compiled = session.statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert set(compiled.params["action_1"]) == {
        "news_deleted",
        "news_restored",
        "news_purged",
    }
    assert compiled.params["resource_type_1"] == "news_article"
    assert "NOT" in sql
    assert session.committed
