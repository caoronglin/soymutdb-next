"""Deployment gate verifies authoritative PostgreSQL transfer receipts."""

import pytest
from sqlalchemy import text

from app.models.content import Release
from app.models.genomic import Assembly
from app.models.variant_facts import native_variant_backfills
from app.scripts.verify_native_cutover import verify_native_cutover


async def _seed(db, count=1):
    release = Release(version="native-cutover", name="Native", status="published",
                      variant_count=count)
    db.add(release)
    await db.flush()
    assembly = Assembly(name="native-v4", version="v4", release_id=release.id)
    db.add(assembly)
    await db.flush()
    return release, assembly


async def test_cutover_rejects_known_missing_legacy_facts(db_session):
    release, _assembly = await _seed(db_session)
    assert await verify_native_cutover(db_session) == [{
        "release_id": release.id, "reason": "native fact count differs from verified release count",
    }]


@pytest.mark.parametrize("receipt_count,version,ready", [(1, "native-cutover", True),
                          (2, "native-cutover", False), (1, "different-version", False)])
async def test_cutover_checks_receipt_count_and_version(db_session, receipt_count, version, ready):
    release, assembly = await _seed(db_session)
    await db_session.execute(text(
        "INSERT INTO variant_facts "
        "(release_id,assembly_id,variant_id,assembly_key,chromosome,position,"
        "ref_allele,alt_allele,variant_type) "
        "VALUES (:release,:assembly,1,'v4','Chr01',1,'A','T','SNP')"
    ), {"release": release.id, "assembly": assembly.id})
    if ready:
        assert (await verify_native_cutover(db_session))[0]["reason"] == (
            "legacy release requires a verified backfill receipt"
        )
    await db_session.execute(native_variant_backfills.insert().values(
        release_id=release.id, source_version=version, source_count=receipt_count,
        payload_sha256="a" * 64, assembly_map={"v4": assembly.id},
    ))
    assert (await verify_native_cutover(db_session) == []) is ready
