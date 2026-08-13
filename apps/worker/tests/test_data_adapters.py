import pytest

from soymutdb_worker.tasks.data_adapters import (
    ImportContext,
    get_adapter,
    registered_kinds,
)


@pytest.mark.parametrize(
    "kind", ["fasta", "gff3", "vcf", "blast_db", "seed_data", "expression_csv", "homolog_csv"]
)
def test_all_approved_types_are_registered(kind):
    assert get_adapter(kind).kind == kind


def test_registry_contains_only_approved_types():
    assert registered_kinds() == (
        "blast_db", "expression_csv", "fasta", "gff3", "homolog_csv", "seed_data", "vcf"
    )


def test_fasta_adapter_reports_sequences(tmp_path):
    path = tmp_path / "assembly.fa"
    path.write_text(">chr1\nACGT\n>chr2\nAA\n")

    result = get_adapter("fasta").run(
        ImportContext(1, 2, "r1", str(path), "a1")
    )

    assert result.records == 2
    assert result.inserted == 2
    assert result.evidence["assembly"] == "a1"
