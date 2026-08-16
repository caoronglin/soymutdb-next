import pytest

from soymutdb_worker.tasks.data_adapters import (
    ImportContext,
    get_adapter,
    registered_kinds,
)


@pytest.mark.parametrize(
    "kind", ["fasta", "gff3", "vcf", "blast_db", "seed_data", "expression_csv", "homolog_csv", "module_tsv"]
)
def test_all_approved_types_are_registered(kind):
    assert get_adapter(kind).kind == kind


def test_registry_contains_only_approved_types():
    assert registered_kinds() == (
        "blast_db", "expression_csv", "fasta", "gff3", "homolog_csv", "module_tsv", "seed_data", "vcf"
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


def test_module_tsv_adapter_accepts_csv(tmp_path):
    get_adapter("module_tsv")  # ensure registered
    path = tmp_path / "genes.csv"
    path.write_bytes(b"gene_id,chromosome,start,end\nG1,Chr01,1,9\n")
    ctx = ImportContext(1, 2, "1", str(path), module_key="genes", filename="genes.csv")
    result = get_adapter("module_tsv").validate(ctx)
    assert result["module_key"] == "genes"
    assert result["rows"] == 1


def test_module_tsv_adapter_accepts_txt(tmp_path):
    path = tmp_path / "genes.txt"
    path.write_bytes(b"gene_id\tchromosome\tstart\tend\nG1\tChr01\t1\t9\n")
    ctx = ImportContext(1, 2, "1", str(path), module_key="genes", filename="genes.txt")
    result = get_adapter("module_tsv").validate(ctx)
    assert result["rows"] == 1


def test_module_tsv_adapter_accepts_xlsx(tmp_path):
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        pytest.skip("openpyxl not installed in worker venv")

    from io import BytesIO

    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.append(["gene_id", "chromosome", "start", "end"])
    sheet.append(["G1", "Chr01", 1, 9])
    buf = BytesIO()
    book.save(buf)

    path = tmp_path / "genes.xlsx"
    path.write_bytes(buf.getvalue())
    ctx = ImportContext(1, 2, "1", str(path), module_key="genes", filename="genes.xlsx")
    result = get_adapter("module_tsv").validate(ctx)
    assert result["rows"] == 1


def test_module_tsv_adapter_rejects_unsupported_extension(tmp_path):
    path = tmp_path / "genes.pdf"
    path.write_bytes(b"gene_id\tchromosome\tstart\tend\nG1\tChr01\t1\t9\n")
    ctx = ImportContext(1, 2, "1", str(path), module_key="genes", filename="genes.pdf")
    with pytest.raises(ValueError, match="Unsupported module file format"):
        get_adapter("module_tsv").validate(ctx)
