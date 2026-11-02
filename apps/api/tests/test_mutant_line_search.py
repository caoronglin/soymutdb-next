"""Public, release-scoped mutant text search and offset pagination regressions."""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.models.content import Release, ReleaseStatus
from app.models.data_publishing import ActiveRelease
from app.models.variant import MutantLine

PREFIX = "/api/v1/mutants"


@pytest_asyncio.fixture
async def search_lines(db_session):
    release = Release(version="search-public", name="Search", status=ReleaseStatus.PUBLISHED)
    other = Release(version="search-other", name="Other", status=ReleaseStatus.PUBLISHED)
    db_session.add_all([release, other])
    await db_session.flush()
    db_session.add(ActiveRelease(id=1, release_id=release.id))
    rows = [
        MutantLine(public_id="SMSEARCH01", name="Golden leaf", cultivar="Williams82",
                   mutagen="EMS", release_id=release.id),
        MutantLine(public_id="SMSEARCH02", name="Green leaf", cultivar="Jack",
                   mutagen="EMS-long", release_id=release.id),
        MutantLine(public_id="SMSEARCH03", name="Literal %_\\ marker", cultivar="Jack",
                   mutagen="Gamma", release_id=release.id),
        MutantLine(public_id="SMOTHER01", name="Golden hidden", release_id=other.id),
        MutantLine(public_id="SMPRIVATE01", name="Golden private", is_public=False,
                   release_id=release.id),
        MutantLine(public_id="SMDELETED01", name="Golden deleted", is_deleted=True,
                   release_id=release.id),
        MutantLine(public_id=None, name="Golden unpublished", release_id=release.id),
    ]
    db_session.add_all(rows)
    await db_session.commit()
    return release


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected"),
    [("gOLden", ["SMSEARCH01"]), ("wILLIams", ["SMSEARCH01"]),
     ("ems", ["SMSEARCH01", "SMSEARCH02"]), ("%_\\", ["SMSEARCH03"]),
     ("   ", ["SMSEARCH01", "SMSEARCH02", "SMSEARCH03"])],
)
async def test_text_search_is_literal_public_and_release_scoped(
    client, search_lines, query, expected
):
    response = await client.get(PREFIX, params={"q": query})
    assert response.status_code == 200
    assert [row["public_id"] for row in response.json()] == expected
    assert all("id" not in row and "internal_id" not in row for row in response.json())
    for hidden in ("SMOTHER01", "SMPRIVATE01", "SMDELETED01", "unpublished"):
        assert hidden not in response.text


@pytest.mark.asyncio
async def test_the_public_identifier_is_searchable(client, search_lines):
    """The identifier the page displays has to be searchable with the same box.

    The list renders ``public_id`` as the row's identity, so a visitor who
    copies it out of the table and pastes it into the search box must find
    the row again. A search that only covers the names would answer "no
    results" for the identifier the page just showed.
    """
    response = await client.get(PREFIX, params={"q": "smsearch02"})
    assert response.status_code == 200
    assert [row["public_id"] for row in response.json()] == ["SMSEARCH02"]

    # A private or hidden row must not become findable through its identifier.
    for hidden in ("SMPRIVATE01", "SMDELETED01", "SMOTHER01"):
        response = await client.get(PREFIX, params={"q": hidden})
        assert response.status_code == 200
        assert response.json() == []


@pytest.mark.asyncio
async def test_exact_mutagen_filter_composes_with_text_search(client, search_lines):
    response = await client.get(PREFIX, params={"mutagen": "EMS", "q": "leaf"})
    assert response.status_code == 200
    assert [row["public_id"] for row in response.json()] == ["SMSEARCH01"]
    response = await client.get(PREFIX, params={"mutagen": "EM"})
    assert response.json() == []


@pytest.mark.asyncio
async def test_offset_pages_reach_all_public_rows_without_overlap(client, search_lines):
    pages = []
    for offset in range(4):
        response = await client.get(PREFIX, params={"limit": 1, "offset": offset})
        assert response.status_code == 200
        pages.append([row["public_id"] for row in response.json()])
    assert pages == [["SMSEARCH01"], ["SMSEARCH02"], ["SMSEARCH03"], []]


@pytest.mark.asyncio
async def test_more_than_one_hundred_results_are_reachable(client, db_session, search_lines):
    db_session.add_all([
        MutantLine(public_id=f"SMBULK{index:05d}", name=f"Bulk line {index}",
                   release_id=search_lines.id)
        for index in range(123)
    ])
    await db_session.commit()
    public_ids = []
    for offset, expected_size in [(0, 51), (50, 51), (100, 23)]:
        response = await client.get(PREFIX, params={"q": "Bulk", "offset": offset, "limit": 51})
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == expected_size
        public_ids.extend(row["public_id"] for row in rows[:50])
    assert public_ids == [f"SMBULK{index:05d}" for index in range(123)]


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{"offset": -1}, {"limit": 201}, {"q": "x" * 201}])
async def test_invalid_search_parameters_are_rejected(client, search_lines, params):
    response = await client.get(PREFIX, params=params)
    assert response.status_code == 422
