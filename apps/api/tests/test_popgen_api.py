"""Population-genetics three-piece numeric validation (fixture hand-calc).

Exercises the pure numpy-free helpers and the service layer against a fake
ClickHouse client returning a small hand-built fixture, with expected values
computed by hand:

- AlleleFreq: per-variant AF passthrough + region metadata.
- Diversity: π = Σ 2·p·(1−p) / bp; θ = S / a_n; per-window π.
- LD: r² = squared Pearson correlation of dosage vectors.

No docker / no real ClickHouse: the service receives an injected fake CH
client (same seam used by ``VariantService``).
"""

from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import NotFoundError
from app.schemas.popgen import (
    AlleleFreqRequest,
    DiversityRequest,
    GenotypeMatrix,
    LdRequest,
)
from app.services.popgen_service import (
    PopGenService,
    compute_diversity_stats,
    compute_diversity_windows,
    compute_ld_r2,
    harmonic_sum,
    watterson_theta,
)
from app.services.release_context import ReleaseContext

RELEASE_CONTEXT = ReleaseContext(
    release_id=7,
    assembly_id=1,
    assembly="GmWm82.a2.v1",
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

#: Four SNP sites on Gm01, positions 100..400, with allele frequencies.
FIXTURE_ROWS = [
    {
        "variant_id": "var1",
        "assembly_key": "GmWm82.a2.v1",
        "chromosome": "Gm01",
        "position": 100,
        "ref_allele": "A",
        "alt_allele": "G",
        "variant_type": "SNP",
        "allele_frequency": 0.5,
        "gene_id": "Glyma.01G000100",
    },
    {
        "variant_id": "var2",
        "assembly_key": "GmWm82.a2.v1",
        "chromosome": "Gm01",
        "position": 200,
        "ref_allele": "C",
        "alt_allele": "T",
        "variant_type": "SNP",
        "allele_frequency": 0.25,
        "gene_id": "Glyma.01G000100",
    },
    {
        "variant_id": "var3",
        "assembly_key": "GmWm82.a2.v1",
        "chromosome": "Gm01",
        "position": 300,
        "ref_allele": "G",
        "alt_allele": "A",
        "variant_type": "SNP",
        "allele_frequency": 0.0,
        "gene_id": "Glyma.01G000100",
    },
    {
        "variant_id": "var4",
        "assembly_key": "GmWm82.a2.v1",
        "chromosome": "Gm01",
        "position": 400,
        "ref_allele": "T",
        "alt_allele": "C",
        "variant_type": "SNP",
        "allele_frequency": None,
        "gene_id": "Glyma.01G000100",
    },
]


class FakeVariantStore:
    """PostgreSQL variant-store stand-in returning the fixture rows for any region."""

    def __init__(self, rows=None):
        self.rows = rows if rows is not None else FIXTURE_ROWS
        self.calls = 0

    async def query_variants_by_region(self, **kwargs):
        self.calls += 1
        return self.rows


class NullDb:
    """Region-mode requests never touch the DB; this stand-in would raise."""

    async def execute(self, stmt, params=None):
        raise AssertionError("region-mode request must not touch PostgreSQL")


class MissingGeneDb:
    """Capture the gene lookup while returning no row."""

    def __init__(self) -> None:
        self.statements = []

    async def execute(self, stmt, params=None):
        self.statements.append(stmt)

        class Result:
            @staticmethod
            def scalar_one_or_none():
                return None

            @staticmethod
            def scalars():
                class Scalars:
                    @staticmethod
                    def all():
                        return []

                return Scalars()

        return Result()


# ---------------------------------------------------------------------------
# Pure helpers – hand-calculated
# ---------------------------------------------------------------------------


def test_compute_diversity_stats_hand_calc() -> None:
    # Polymorphic sites: af 0.5 -> 2*0.5*0.5 = 0.5; af 0.25 -> 2*0.25*0.75 = 0.375.
    # af 0.0 and None are monomorphic/unknown -> excluded.
    pi_sum, pi_per_site, segregating = compute_diversity_stats([0.5, 0.25, 0.0, None])
    assert pi_sum == pytest.approx(0.5 + 0.375)
    assert pi_per_site == pytest.approx((0.5 + 0.375) / 2)
    assert segregating == 2


def test_harmonic_sum_and_watterson_theta() -> None:
    # a_5 = 1 + 1/2 + 1/3 + 1/4 = 25/12 ≈ 2.08333...
    assert harmonic_sum(5) == pytest.approx(25 / 12)
    # θ = S / a_n, per bp when n_bp given.
    theta = watterson_theta(segregating_sites=10, sample_size=5, n_bp=1000)
    assert theta == pytest.approx(10 / (25 / 12) / 1000)
    with pytest.raises(Exception):
        watterson_theta(1, sample_size=1)


def test_compute_ld_r2_hand_calc() -> None:
    # 4 samples × 3 variants; variants 1 and 2 are perfectly anti-correlated,
    # variant 3 is constant (zero variance -> r2 = 0).
    genotypes = [
        [0, 2, 1],
        [1, 1, 1],
        [2, 0, 1],
        [1, 1, 1],
    ]
    r2 = compute_ld_r2(genotypes)
    assert r2[0][0] == 1.0
    assert r2[1][1] == 1.0
    assert r2[2][2] == 1.0
    # v1 (0,1,2,1) vs v2 (2,1,0,1): perfect negative correlation -> r2 = 1.
    assert r2[0][1] == pytest.approx(1.0)
    assert r2[1][0] == pytest.approx(1.0)
    # v3 constant -> denominator zero -> r2 = 0 by definition.
    assert r2[0][2] == pytest.approx(0.0)
    assert r2[1][2] == pytest.approx(0.0)

    # Second hand-check with distinct correlation: v1=(0,0,1,1), v2=(0,1,0,1).
    r2b = compute_ld_r2([[0, 0], [0, 1], [1, 0], [1, 1]])
    # means 0.5/0.5; cov = ((−.5)(−.5)+(−.5)(.5)+(.5)(−.5)+(.5)(.5))/4 = 0
    assert r2b[0][1] == pytest.approx(0.0)


def test_compute_diversity_windows_hand_calc() -> None:
    variants = [
        {"position": 100, "allele_frequency": 0.5},
        {"position": 200, "allele_frequency": 0.25},
        {"position": 350, "allele_frequency": 0.5},
    ]
    windows = compute_diversity_windows(variants, region_start=1, region_end=400, window_size=200)
    # Window 1: 1..200 -> two polymorphic sites, π = (0.5 + 0.375) / 200.
    assert len(windows) == 2
    w1, w2 = windows
    assert (w1.start, w1.end) == (1, 200)
    assert w1.segregating_sites == 2
    assert w1.pi == pytest.approx(0.875 / 200, abs=1e-9)
    # Window 2: 201..400 -> one polymorphic site, π = 0.5 / 200.
    assert (w2.start, w2.end) == (201, 400)
    assert w2.segregating_sites == 1
    assert w2.pi == pytest.approx(0.5 / 200, abs=1e-9)


# ---------------------------------------------------------------------------
# Service-level checks (injected fake PostgreSQL variant store)
# ---------------------------------------------------------------------------


def _service(variant_service=None) -> PopGenService:
    return PopGenService(variant_service=variant_service or FakeVariantStore())


async def test_allelefreq_region_mode() -> None:
    store = FakeVariantStore()
    service = _service(store)
    request = AlleleFreqRequest(
        assembly="GmWm82.a2.v1", chromosome="Gm01", start=1, end=1000
    )

    response = await service.allele_frequencies(
        NullDb(), request, release_context=RELEASE_CONTEXT
    )

    assert store.calls == 1
    assert response.source == "interval"
    assert response.assembly == "GmWm82.a2.v1"
    assert response.n_variants == 4
    assert response.variants[0].allele_frequency == pytest.approx(0.5)
    assert response.variants[1].allele_frequency == pytest.approx(0.25)
    assert response.variants[2].allele_frequency == pytest.approx(0.0)
    assert response.variants[3].allele_frequency is None
    assert response.variants[0].variant_id == "var1"


async def test_gene_region_lookup_is_bound_to_selected_release() -> None:
    db = MissingGeneDb()
    request = AlleleFreqRequest(gene_id="Glyma.01G000100")

    with pytest.raises(NotFoundError):
        await _service().allele_frequencies(
            db,
            request,
            release_context=RELEASE_CONTEXT,
        )

    statement = db.statements[0]
    sql = str(statement)
    assert "JOIN assemblies" in sql
    assert "assemblies.release_id" in sql
    assert RELEASE_CONTEXT.release_id in statement.compile().params.values()


async def test_diversity_region_mode_hand_calc() -> None:
    service = _service()
    request = DiversityRequest(
        assembly="GmWm82.a2.v1",
        chromosome="Gm01",
        start=1,
        end=1000,
        sample_size=5,
    )

    response = await service.diversity(
        NullDb(), request, release_context=RELEASE_CONTEXT
    )

    assert response.n_bp == 1000
    assert response.n_variants == 4
    # Segregating: af 0.5 and 0.25 only.
    assert response.segregating_sites == 2
    # π per bp = (0.5 + 0.375) / 1000.
    assert response.pi == pytest.approx(0.875 / 1000, abs=1e-10)
    # π per polymorphic site = 0.875 / 2.
    assert response.pi_per_site == pytest.approx(0.875 / 2, abs=1e-10)
    # θ = 2 / a_5 / 1000.
    assert response.theta == pytest.approx(2 / (25 / 12) / 1000, abs=1e-10)


async def test_diversity_without_sample_size_omits_theta() -> None:
    service = _service()
    request = DiversityRequest(
        assembly="GmWm82.a2.v1", chromosome="Gm01", start=1, end=1000
    )

    response = await service.diversity(
        NullDb(), request, release_context=RELEASE_CONTEXT
    )

    assert response.theta is None
    assert response.pi == pytest.approx(0.875 / 1000, abs=1e-10)


async def test_diversity_with_windows() -> None:
    service = _service()
    request = DiversityRequest(
        assembly="GmWm82.a2.v1",
        chromosome="Gm01",
        start=1,
        end=1000,
        window_size=250,
    )

    response = await service.diversity(
        NullDb(), request, release_context=RELEASE_CONTEXT
    )

    # Fixture positions: 100 (af 0.5), 200 (af 0.25), 300 (af 0.0),
    # 400 (af None).
    assert response.windows is not None
    assert len(response.windows) == 2
    w1, w2 = response.windows
    # Window 1: 1..250 -> two polymorphic sites (0.5, 0.25).
    assert (w1.start, w1.end) == (1, 250)
    assert w1.n_variants == 2
    assert w1.segregating_sites == 2
    assert w1.pi == pytest.approx(0.875 / 250, abs=1e-9)
    # Window 2: 251..500 -> positions 300 (af 0.0) and 400 (af None):
    # no polymorphic sites, so π = 0.
    assert (w2.start, w2.end) == (251, 500)
    assert w2.n_variants == 2
    assert w2.segregating_sites == 0
    assert w2.pi == 0.0


async def test_ld_without_genotypes_returns_note_and_coordinates() -> None:
    service = _service()
    request = LdRequest(
        assembly="GmWm82.a2.v1", chromosome="Gm01", start=1, end=1000
    )

    response = await service.ld(
        NullDb(), request, release_context=RELEASE_CONTEXT
    )

    assert response.r_squared is None
    assert response.note is not None and "genotype" in response.note
    assert len(response.variants) == 4
    assert response.variants[0].position == 100


def _identical_across_namespaces(variant_id: str) -> list[dict]:
    """Two rows that share every field except the assembly namespace.

    Only ``assembly_key`` differs: same coordinates, same alleles, same
    ``variant_id``. That is exactly the pair a key built from the number alone
    would merge.
    """
    row = {
        "variant_id": variant_id,
        "chromosome": "Gm01",
        "position": 100,
        "ref_allele": "A",
        "alt_allele": "G",
        "variant_type": "SNP",
        "allele_frequency": 0.5,
        "gene_id": "Glyma.01G000100",
    }
    return [{**row, "assembly_key": "GmWm82.a2.v1"}, {**row, "assembly_key": "GmWm82.a4.v1"}]


async def test_two_namespaces_keep_the_same_variant_id_apart() -> None:
    """The response has to make the two rows distinguishable.

    ``variant_facts`` is keyed by ``(release_id, assembly_id, variant_id)``, so
    the row identity has three parts and the namespace is one of them. A
    response row that carries only the number loses a part of the identity: two
    assemblies' rows would then compare equal on every field the contract
    exposes, and a client keying on the number alone would merge them. This
    endpoint currently answers per assembly, which bounds the blast radius — it
    does not make the extra field unnecessary.
    """
    service = _service(FakeVariantStore(_identical_across_namespaces("77")))
    region = {"chromosome": "Gm01", "start": 1, "end": 1000}

    response = await service.allele_frequencies(
        NullDb(),
        AlleleFreqRequest(assembly="GmWm82.a2.v1", **region),
        release_context=RELEASE_CONTEXT,
    )

    assert [row.variant_id for row in response.variants] == ["77", "77"]
    assert [row.assembly for row in response.variants] == ["GmWm82.a2.v1", "GmWm82.a4.v1"]
    # Everything else in the row is identical, so the namespace is the only
    # field that tells them apart.
    first, second = response.variants
    assert first.model_dump(exclude={"assembly"}) == second.model_dump(exclude={"assembly"})


async def test_every_variant_row_states_its_assembly_namespace() -> None:
    """A row without its namespace cannot be keyed.

    ``variant_facts`` is keyed by ``(release_id, assembly_id, variant_id)``, so
    two assemblies may carry the same ``variant_id``. The popgen responses
    therefore have to echo the namespace per row: a client that only receives
    the number cannot tell the two apart, and a list keyed on the number alone
    would merge them.
    """
    service = _service()
    region = {"assembly": "GmWm82.a2.v1", "chromosome": "Gm01", "start": 1, "end": 1000}

    allele_freq = await service.allele_frequencies(
        NullDb(),
        AlleleFreqRequest(**region),
        release_context=RELEASE_CONTEXT,
    )
    assert [row.assembly for row in allele_freq.variants] == ["GmWm82.a2.v1"] * 4

    ld_response = await service.ld(
        NullDb(),
        LdRequest(**region),
        release_context=RELEASE_CONTEXT,
    )
    assert [row.assembly for row in ld_response.variants] == ["GmWm82.a2.v1"] * 4

    # Coordinates are caller-supplied here, so the namespace is the one the
    # request resolved — still stated per row, never read off the page.
    with_genotypes = await service.ld(
        NullDb(),
        LdRequest(
            **region,
            genotypes=GenotypeMatrix(
                sample_ids=[f"s{i}" for i in range(4)],
                variant_ids=["var1", "var2"],
                values=[[0, 2], [1, 1], [2, 0], [1, 1]],
            ),
        ),
        release_context=RELEASE_CONTEXT,
    )
    assert [row.assembly for row in with_genotypes.variants] == ["GmWm82.a2.v1"] * 2


def test_variant_row_schemas_require_the_namespace() -> None:
    """``assembly`` is required on the wire, not defaulted to an empty string.

    An omitted namespace and "the empty namespace" would render identically in
    a row key, which is the collision this field exists to prevent.
    """
    from app.schemas.popgen import AlleleFreqVariant, LdVariant

    for schema in (AlleleFreqVariant, LdVariant):
        # `assembly` is required (present in `required`, no default) and typed
        # `str`: an omitted namespace must be a validation error, not "".
        assert "assembly" in schema.model_json_schema()["required"], schema.__name__
        assert schema.model_fields["assembly"].annotation is str, schema.__name__


async def test_ld_with_inline_genotypes_computes_r2() -> None:
    service = _service()
    request = LdRequest(
        assembly="GmWm82.a2.v1",
        chromosome="Gm01",
        start=1,
        end=1000,
        genotypes=GenotypeMatrix(
            sample_ids=[f"s{i}" for i in range(4)],
            variant_ids=["var1", "var2"],
            values=[[0, 2], [1, 1], [2, 0], [1, 1]],
        ),
    )

    response = await service.ld(
        NullDb(), request, release_context=RELEASE_CONTEXT
    )

    assert response.r_squared is not None
    assert len(response.r_squared) == 2
    assert response.r_squared[0][1] == pytest.approx(1.0)
    assert response.details is not None
    assert response.details["n_samples"] == 4


async def test_ld_rejects_bad_genotype_shape() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GenotypeMatrix(
            sample_ids=["s1", "s2"],
            variant_ids=["v1", "v2"],
            values=[[0, 0]],  # only one row for two samples
        )
    with pytest.raises(ValidationError):
        GenotypeMatrix(
            sample_ids=["s1", "s2"],
            variant_ids=["v1", "v2"],
            values=[[0, 0], [3, 1]],  # dosage 3 is invalid
        )


def test_region_schema_requires_exactly_one_mode() -> None:
    from pydantic import ValidationError

    from app.schemas.popgen import RegionQuery

    with pytest.raises(ValidationError, match="exactly one"):
        RegionQuery()
    with pytest.raises(ValidationError, match="exactly one"):
        RegionQuery(gene_id="Glyma.01G000100", assembly="GmWm82.a2.v1")
    with pytest.raises(ValidationError, match="missing"):
        RegionQuery(assembly="GmWm82.a2.v1", chromosome="Gm01", start=1)
    with pytest.raises(ValidationError, match="start must be <= end"):
        RegionQuery(
            assembly="GmWm82.a2.v1", chromosome="Gm01", start=500, end=100
        )
    # Valid interval passes.
    RegionQuery(assembly="GmWm82.a2.v1", chromosome="Gm01", start=1, end=1000)


async def test_diversity_empty_region() -> None:
    service = _service(FakeVariantStore(rows=[]))
    request = DiversityRequest(
        assembly="GmWm82.a2.v1", chromosome="Gm01", start=1, end=100
    )

    response = await service.diversity(
        NullDb(), request, release_context=RELEASE_CONTEXT
    )

    assert response.n_variants == 0
    assert response.segregating_sites == 0
    assert response.pi == 0.0
    assert response.pi_per_site is None
    assert response.theta is None


def test_uuid_import_available_for_parity() -> None:
    # Placeholder guard so the module import surface stays exercised.
    assert uuid.uuid4() is not None
