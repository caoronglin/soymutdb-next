"""The gene list must search literally, and must not eager-load what it drops.

Two defects are pinned here.

**P1 — user text became a SQL LIKE program.** ``list_genes`` interpolated the
raw search string into ``f"%{params.search}%"`` and matched it with ``ILIKE``.
A ``LIKE`` pattern is a *program*, not a string: ``%`` matches any run of
characters and ``_`` matches exactly one. A search for ``%`` therefore matched
*every* gene, and a one-character search degenerated into a full scan of
``genes`` -- a pattern made only of wildcards carries no trigram, so the
trigram indexes of migrations 0027/0046 cannot serve it either.
``docs/dev/database-core-contract.md`` §6 item 6 asks for a literal ``%`` / ``_``
fixture for exactly this reason.

**P2 — the list endpoint loaded thousands of rows it threw away.**
``Gene.transcripts`` and ``Gene.aliases`` are ``selectin`` relationships, and
``Transcript.exons`` / ``Transcript.parts`` are ``selectin`` as well. The list
response (``GeneResponse``) carries none of that data, yet a 200-row page
eager-loaded every transcript, exon, transcript part and alias of those genes
-- plus the joined back-references they drag along -- and then discarded all
of it. The detail endpoint must keep returning exactly what it returns today.
"""

from __future__ import annotations

import contextlib

import pytest
from sqlalchemy import event, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import Release, ReleaseStatus
from app.models.genomic import (
    Assembly,
    Chromosome,
    Exon,
    Gene,
    GeneAlias,
    Transcript,
    TranscriptPart,
)
from app.schemas.genomic import GeneListParams
from app.services.gene_service import GeneService
from app.services.release_context import ReleaseContext
from app.services.sql_like import (
    LIKE_ESCAPE_CHARACTER,
    contains_pattern,
    literal_like_fragment,
)

# --------------------------------------------------------------------------- #
# The escaping helper (pure, no database)
# --------------------------------------------------------------------------- #


class TestLiteralLikeFragment:
    def test_percent_is_escaped(self):
        assert literal_like_fragment("%") == "\\%"
        assert literal_like_fragment("100%") == "100\\%"

    def test_underscore_is_escaped(self):
        assert literal_like_fragment("_") == "\\_"
        assert literal_like_fragment("snake_case") == "snake\\_case"

    def test_escape_character_itself_is_doubled(self):
        assert literal_like_fragment("\\") == "\\\\"
        assert literal_like_fragment("a\\b") == "a\\\\b"

    def test_ordinary_text_is_untouched(self):
        assert literal_like_fragment("Glyma.01G000100") == "Glyma.01G000100"

    def test_replacements_do_not_re_escape_each_other(self):
        """The backslash is doubled *first*, so the escapes stay single.

        If ``%`` and ``_`` were escaped before the backslash, the backslashes
        introduced for them would be doubled as well and the pattern would no
        longer describe the text the user typed.
        """
        assert literal_like_fragment("%_") == "\\%\\_"
        assert literal_like_fragment("\\%") == "\\\\\\%"


class TestContainsPattern:
    def test_pattern_is_a_literal_substring(self):
        assert contains_pattern("Glyma") == "%Glyma%"

    def test_wildcards_in_the_user_text_are_escaped(self):
        assert contains_pattern("%") == "%\\%%"
        assert contains_pattern("_") == "%\\_%"
        assert contains_pattern("a%b_c") == "%a\\%b\\_c%"

    def test_escape_character_matches_the_sql_clause(self):
        """The helper and the SQL side have to agree on one escape character.

        The escaped pattern is meaningless unless the query also says which
        character escapes: without ``ESCAPE '\\'`` the backslashes would be
        matched literally and the ``%`` would still be a wildcard.
        """
        assert LIKE_ESCAPE_CHARACTER == "\\"
        assert contains_pattern("%").count(LIKE_ESCAPE_CHARACTER) == 1


# --------------------------------------------------------------------------- #
# The compiled statement (no database)
# --------------------------------------------------------------------------- #


class _EmptyResult:
    """Stand-in for a SQLAlchemy result that matched nothing."""

    def all(self) -> list:
        return []

    def scalars(self):
        return self

    def scalar_one_or_none(self):
        return None


class _RecordingSession:
    """AsyncSession stand-in that records the statements it is handed."""

    def __init__(self) -> None:
        self.statements: list = []

    async def execute(self, stmt, params=None):
        self.statements.append(stmt)
        return _EmptyResult()

    async def scalar(self, stmt):
        self.statements.append(stmt)
        return 0


async def _recorded_search_statement(search: str):
    """Return the statement ``list_genes`` builds for ``search``."""
    session = _RecordingSession()
    await GeneService().list_genes(
        session,
        GeneListParams(search=search, limit=10),
        release_context=ReleaseContext(release_id=7, assembly_id=1),
    )
    assert session.statements
    return session.statements[-1]


class TestCompiledSearchStatement:
    async def test_pattern_is_escaped_and_not_a_bare_wildcard(self):
        statement = await _recorded_search_statement("%")
        compiled = statement.compile(dialect=postgresql.dialect())
        params = compiled.construct_params()

        # The pattern that reaches PostgreSQL is the escaped one, not "%%%".
        patterns = [value for value in params.values() if isinstance(value, str)]
        assert patterns == ["%\\%%"] * 3
        assert "%%%" not in patterns

    async def test_the_escape_clause_is_part_of_the_query(self):
        """Without ``ESCAPE`` the backslashes are literal and ``%`` still wins."""
        statement = await _recorded_search_statement("_")
        sql = str(statement.compile(dialect=postgresql.dialect()))

        assert sql.count("ILIKE") == 3
        assert sql.count("ESCAPE '\\'") == 3

    async def test_the_predicate_stays_on_the_raw_indexed_columns(self):
        """The trigram indexes are on ``accession`` / ``name`` / ``description``.

        ``lower(col) LIKE ...`` would not be served by those indexes; the
        PostgreSQL dialect renders ``ilike`` as ``col ILIKE ...``, which is.
        """
        statement = await _recorded_search_statement("Glyma")
        sql = str(statement.compile(dialect=postgresql.dialect()))

        assert "lower(genes.accession)" not in sql
        assert "genes.accession ILIKE" in sql
        assert "genes.name ILIKE" in sql
        assert "genes.description ILIKE" in sql


# --------------------------------------------------------------------------- #
# The real read path
# --------------------------------------------------------------------------- #

#: The corpus. Exactly one row carries a literal ``%``, exactly one carries a
#: literal ``_``, and the remaining rows carry neither -- so a search that
#: behaved like a wildcard program would return all of them.
CORPUS = (
    ("Glyma.01G000100", "Percent Marker", "confers 100% resistance"),
    ("Glyma.01G000200", "Snake_Case Gene", "named snake_case in the source"),
    ("Glyma.01G000300", "Plain Gene", "no wildcard character at all"),
    ("Glyma.01G000400", "Second Plain", "another ordinary annotation"),
    ("Glyma.01G000500", "Bare Gene", "no transcripts and no aliases"),
)


@pytest.fixture
async def corpus(db_session: AsyncSession) -> ReleaseContext:
    """Seed one published release with the corpus above."""
    release = Release(
        name="Literal search corpus",
        version="lit-1",
        status=ReleaseStatus.PUBLISHED.value,
    )
    db_session.add(release)
    await db_session.flush()
    assembly = Assembly(
        name="Wm82 lit-1", species="Glycine max", version="lit-1", release_id=release.id
    )
    db_session.add(assembly)
    await db_session.flush()
    chromosome = Chromosome(
        assembly_id=assembly.id, name="Gm01", length=1_000_000, order=0
    )
    db_session.add(chromosome)
    await db_session.flush()

    genes: list[Gene] = []
    for index, (accession, name, description) in enumerate(CORPUS):
        gene = Gene(
            accession=accession,
            assembly_id=assembly.id,
            chromosome_id=chromosome.id,
            start=1000 * (index + 1),
            end=1000 * (index + 1) + 500,
            strand="+",
            name=name,
            description=description,
            biotype="protein_coding",
        )
        db_session.add(gene)
        genes.append(gene)
    await db_session.flush()

    # One gene with a transcript, an exon, a transcript part and an alias, so
    # the eager-loading assertions have something to load.
    transcript = Transcript(
        id="lit-tx-1",
        gene_id=genes[0].gene_pk,
        name="Glyma.01G000100.1",
        biotype="mRNA",
        start=1000,
        end=1500,
        strand="+",
        is_canonical=True,
    )
    db_session.add(transcript)
    await db_session.flush()
    db_session.add(Exon(transcript_id=transcript.id, start=1000, end=1200, order=1))
    db_session.add(
        TranscriptPart(
            transcript_id=transcript.id,
            part_type="cds",
            start=1000,
            end=1200,
            order=1,
        )
    )
    db_session.add(GeneAlias(gene_id=genes[0].gene_pk, alias="PM1", source="test"))
    await db_session.flush()

    return ReleaseContext(release_id=release.id, assembly_id=assembly.id)


async def _search(
    db: AsyncSession, context: ReleaseContext, term: str, **kwargs
) -> list[str]:
    """Return the accessions a gene-list search matches."""
    page = await GeneService().list_genes(
        db,
        GeneListParams(search=term, limit=50, **kwargs),
        release_context=context,
    )
    return [item.gene_id for item in page.items]


class TestLiteralSearch:
    async def test_percent_matches_only_rows_that_contain_a_percent(self, db_session, corpus):
        matches = await _search(db_session, corpus, "%")

        assert matches == ["Glyma.01G000100"]
        # The whole point: a wildcard program would have matched every row.
        assert len(matches) < len(CORPUS)

    async def test_underscore_matches_only_rows_that_contain_an_underscore(
        self, db_session, corpus
    ):
        matches = await _search(db_session, corpus, "_")

        assert matches == ["Glyma.01G000200"]
        assert len(matches) < len(CORPUS)

    async def test_underscore_is_not_a_single_character_wildcard(self, db_session, corpus):
        """``"Plain Gene"`` has a space where the underscore is.

        A ``_`` wildcard would match it; a literal underscore must not.
        """
        matches = await _search(db_session, corpus, "_")

        assert "Glyma.01G000300" not in matches
        assert "Glyma.01G000400" not in matches

    async def test_the_filtered_total_uses_the_same_escaped_predicate(
        self, db_session, corpus
    ):
        """The paged count is a second statement and must not drift.

        The count is derived from the filtered statement, so a raw pattern
        there would report "every gene" while the page showed one row.
        """
        page = await GeneService().list_genes(
            db_session,
            GeneListParams(search="%", page=1, page_size=10),
            release_context=corpus,
        )

        assert [item.gene_id for item in page.items] == ["Glyma.01G000100"]
        assert page.total == 1

    async def test_a_normal_search_still_matches_case_insensitively(
        self, db_session, corpus
    ):
        lower = await _search(db_session, corpus, "plain")
        upper = await _search(db_session, corpus, "PLAIN")
        mixed = await _search(db_session, corpus, "PlAiN")

        assert lower == ["Glyma.01G000300", "Glyma.01G000400"]
        assert upper == lower
        assert mixed == lower

    async def test_a_normal_search_still_matches_the_accession(self, db_session, corpus):
        matches = await _search(db_session, corpus, "Glyma.01G0003")

        assert matches == ["Glyma.01G000300"]

    async def test_a_search_without_wildcards_is_unaffected(self, db_session, corpus):
        """The fix must not narrow what an ordinary search finds."""
        matches = await _search(db_session, corpus, "Glyma")

        assert matches == [accession for accession, _name, _description in CORPUS]


# --------------------------------------------------------------------------- #
# The loader behaviour of the list path
# --------------------------------------------------------------------------- #

#: The relationship tables the list response never serialises.
EAGER_TABLES = ("transcripts", "exons", "transcript_parts", "gene_aliases")


@contextlib.asynccontextmanager
async def _capture_statements(session: AsyncSession):
    """Collect the SQL every statement of ``session`` produces."""
    captured: list[str] = []

    @event.listens_for(session.sync_session, "do_orm_execute")
    def _record(execute_state) -> None:
        captured.append(str(execute_state.statement))

    try:
        yield captured
    finally:
        event.remove(session.sync_session, "do_orm_execute", _record)


class TestListDoesNotEagerLoad:
    async def test_list_genes_issues_no_relationship_query(self, db_session, corpus):
        async with _capture_statements(db_session) as captured:
            page = await GeneService().list_genes(
                db_session,
                GeneListParams(limit=50),
                release_context=corpus,
            )

        assert len(page.items) == len(CORPUS)
        # One statement: the genes and the joined assembly/chromosome columns.
        assert len(captured) == 1
        for sql in captured:
            for table in EAGER_TABLES:
                assert f"FROM {table}" not in sql, sql
                assert f"JOIN {table}" not in sql, sql

    async def test_the_paged_list_issues_no_relationship_query(self, db_session, corpus):
        async with _capture_statements(db_session) as captured:
            await GeneService().list_genes(
                db_session,
                GeneListParams(page=1, page_size=10),
                release_context=corpus,
            )

        # The count and the page -- and nothing else.
        assert len(captured) == 2
        for sql in captured:
            for table in EAGER_TABLES:
                assert f"FROM {table}" not in sql, sql
                assert f"JOIN {table}" not in sql, sql

    async def test_the_list_response_is_unchanged(self, db_session, corpus):
        """The observable response must not change: same rows, same fields."""
        page = await GeneService().list_genes(
            db_session,
            GeneListParams(limit=50),
            release_context=corpus,
        )

        assert [item.gene_id for item in page.items] == [
            accession for accession, _name, _description in CORPUS
        ]
        first = page.items[0]
        assert first.name == "Percent Marker"
        assert first.description == "confers 100% resistance"
        assert first.chromosome == "Gm01"
        assert first.biotype == "protein_coding"
        assert first.variant_count == 0
        # The list response has never carried transcripts or aliases.
        assert not hasattr(first, "transcripts")
        assert not hasattr(first, "aliases")


class TestDetailStillLoads:
    async def test_get_gene_still_returns_transcripts_and_aliases(self, db_session, corpus):
        async with _capture_statements(db_session) as captured:
            detail = await GeneService().get_gene(
                db_session,
                "Glyma.01G000100",
                release_context=corpus,
            )

        assert [transcript.id for transcript in detail.transcripts] == [
            "Glyma.01G000100.1"
        ]
        assert detail.transcripts[0].exons[0].start == 1000
        assert detail.aliases == ["PM1"]
        # The detail path is untouched: it still eager-loads the relationships.
        assert any("FROM transcripts" in sql for sql in captured)

    async def test_a_gene_without_transcripts_still_serialises(self, db_session, corpus):
        detail = await GeneService().get_gene(
            db_session,
            "Glyma.01G000500",
            release_context=corpus,
        )

        assert detail.gene_id == "Glyma.01G000500"
        assert detail.transcripts == []
        assert detail.aliases == []
        assert detail.chromosome == "Gm01"

    async def test_a_gene_without_transcripts_is_listed_like_any_other(
        self, db_session, corpus
    ):
        page = await GeneService().list_genes(
            db_session,
            GeneListParams(limit=50),
            release_context=corpus,
        )

        bare = [item for item in page.items if item.gene_id == "Glyma.01G000500"]
        assert len(bare) == 1
        assert bare[0].name == "Bare Gene"
        assert bare[0].variant_count == 0


# --------------------------------------------------------------------------- #
# Planner layer: the trigram indexes must stay reachable
# --------------------------------------------------------------------------- #

#: Migrations 0027 and 0046 index exactly these three columns of ``genes``
#: with ``gin_trgm_ops``. The search predicate has to stay on those raw
#: columns for the indexes to be usable at all.
TRIGRAM_INDEXES = (
    "ix_genes_accession_trgm",
    "ix_genes_name_trgm",
    "ix_genes_description_trgm",
)
#: The same indexes with the column each one covers.
TRIGRAM_INDEX_COLUMNS = (
    ("ix_genes_accession_trgm", "accession"),
    ("ix_genes_name_trgm", "name"),
    ("ix_genes_description_trgm", "description"),
)
SEARCH_TERM = "Glyma.05G0421"
SEED_ROWS = 5_000
MATCHING_ROWS = 5
PLAN_RELEASE_ID = 9001
PLAN_ASSEMBLY_ID = 9001


@pytest.fixture
async def planner_corpus(db_session: AsyncSession) -> ReleaseContext:
    """Seed a gene table that carries the production trigram indexes.

    PostgreSQL has transactional DDL, so the indexes are created inside the
    test's own transaction and disappear with it -- the shared test database
    is left exactly as it was found. The seed rows are ordinary rows of the
    same table, so the planner sees the same statistics it sees in
    production.
    """
    await db_session.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    await db_session.execute(
        text(
            "INSERT INTO releases (id, version, name, status, variant_count, "
            "gene_count, mutant_line_count) "
            "VALUES (:id, 'plan-1', 'Plan release', 'published', 0, 0, 0)"
        ),
        {"id": PLAN_RELEASE_ID},
    )
    await db_session.execute(
        text(
            "INSERT INTO assemblies (id, name, species, version, is_default, release_id) "
            "VALUES (:id, 'Plan assembly', 'Glycine max', 'plan-1', true, :id)"
        ),
        {"id": PLAN_ASSEMBLY_ID},
    )
    await db_session.execute(
        text(
            'INSERT INTO chromosomes (id, assembly_id, name, length, "order") '
            "VALUES (:id, :id, 'Gm01', 100000000, 0)"
        ),
        {"id": PLAN_ASSEMBLY_ID},
    )
    await db_session.execute(
        text(
            "INSERT INTO genes (accession, assembly_id, chromosome_id, name, biotype, "
            'start, "end", strand, description) '
            "SELECT CASE WHEN n <= :matching "
            "THEN :term || lpad(n::text, 2, '0') "
            "ELSE 'Glyma.16G' || lpad(n::text, 6, '0') END, "
            ":assembly_id, :assembly_id, 'Filler annotation row ' || n, "
            "'protein_coding', 1000 + n, 2000 + n, '+', "
            "'Filler annotation row ' || n "
            "FROM generate_series(1, :rows) AS n"
        ),
        {
            "matching": MATCHING_ROWS,
            "term": SEARCH_TERM,
            "assembly_id": PLAN_ASSEMBLY_ID,
            "rows": SEED_ROWS,
        },
    )
    # Build after bulk loading so the fixture measures a populated GIN index,
    # not its unflushed fastupdate pending list (which must be scanned in full
    # and can make a primary-key scan cheaper even with seqscans disabled).
    for name, column in TRIGRAM_INDEX_COLUMNS:
        await db_session.execute(
            text(f"CREATE INDEX IF NOT EXISTS {name} ON genes USING gin ({column} gin_trgm_ops)")
        )
    await db_session.execute(text("ANALYZE genes"))
    await db_session.execute(text("ANALYZE assemblies"))
    return ReleaseContext(release_id=PLAN_RELEASE_ID, assembly_id=PLAN_ASSEMBLY_ID)


async def _explain_on_session(
    db_session: AsyncSession, statement, parameters
) -> str:
    """EXPLAIN a captured statement on the session's own connection.

    The statement is compiled with the engine's own dialect and replayed
    positionally on the raw asyncpg connection: that is the only combination
    that keeps both the ``$n`` binds and the casts asyncpg uses to infer
    argument types -- and the session's own connection is the only one that
    can see the rows and the indexes this transaction created.
    """
    connection = await db_session.connection()
    raw = await connection.get_raw_connection()
    driver = raw.driver_connection
    dialect = connection.dialect
    compiled = statement.compile(
        dialect=dialect, compile_kwargs={"render_postcompile": True}
    )
    values = compiled.construct_params(params=dict(parameters or {}))
    order = list(compiled.positiontup or sorted(values))
    arguments = [values[name] for name in order]

    # Sequential scans are priced out so the assertion is about the *index
    # path* the predicate allows, not about the cost model of a small table.
    await driver.execute("SET enable_seqscan = off")
    try:
        rows = await driver.fetch(
            "EXPLAIN (ANALYZE, BUFFERS) " + str(compiled), *arguments
        )
    finally:
        await driver.execute("RESET enable_seqscan")
    return "\n".join(row[0] for row in rows)


class TestTrigramIndexStaysUsable:
    async def test_the_escaped_search_still_matches_the_right_rows(
        self, db_session: AsyncSession, planner_corpus: ReleaseContext
    ):
        page = await GeneService().list_genes(
            db_session,
            GeneListParams(search=SEARCH_TERM, limit=20),
            release_context=planner_corpus,
        )

        assert len(page.items) == MATCHING_ROWS
        assert all(item.gene_id.startswith(SEARCH_TERM) for item in page.items)

    async def test_the_statement_reaches_the_trigram_indexes(
        self, db_session: AsyncSession, planner_corpus: ReleaseContext
    ):
        """The escaped pattern must not cost the query its index path.

        A ``LIKE`` pattern made only of wildcards carries no trigram, so the
        planner cannot use these indexes for it; the escaped pattern of an
        ordinary search still does, and the ``ESCAPE`` clause does not change
        that -- the operator stays ``ILIKE`` on the indexed column.
        """
        captured: list[tuple] = []

        @event.listens_for(db_session.sync_session, "do_orm_execute")
        def _capture(execute_state) -> None:
            captured.append((execute_state.statement, execute_state.parameters))

        try:
            await GeneService().list_genes(
                db_session,
                GeneListParams(search=SEARCH_TERM, limit=20),
                release_context=planner_corpus,
            )
        finally:
            event.remove(db_session.sync_session, "do_orm_execute", _capture)

        assert len(captured) == 1
        plan = await _explain_on_session(db_session, *captured[0])
        for index in TRIGRAM_INDEXES:
            assert index in plan, plan
