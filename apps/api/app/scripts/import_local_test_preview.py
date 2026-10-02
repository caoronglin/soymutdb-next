"""Import the 03_soymut sample into the disposable local preview database."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from ..core.config import get_settings
from ..services.local_test_preview_import_service import import_local_test_preview

DEFAULT_DATA_DIR = Path("/home/rlcao/下载/03_soymut")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Import unpublished 03_soymut v6/a6 test data into a disposable "
            "loopback PostgreSQL database."
        )
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"test data directory (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help="explicit async PostgreSQL URL for 127.0.0.1:55432/soymutdb",
    )
    parser.add_argument(
        "--allow-local-test-db",
        action="store_true",
        required=True,
        help="confirm that the target is the disposable local test database",
    )
    return parser


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    # `app_env=dev` is the guard that keeps the preview dataset out of
    # production; `deployment_mode` is not (same relaxation as
    # `core/config.py`), so a local full-stack run may import too.
    if not settings.local_test_preview_enabled or settings.app_env != "dev":
        raise SystemExit(
            "Set SOYMUTDB_APP_ENV=dev and "
            "SOYMUTDB_LOCAL_TEST_PREVIEW_ENABLED=true for this local import."
        )

    annot_dir = args.data_dir / "01_annot"
    gff3_path = annot_dir / "Gmax_880_Wm82.a6.v1.gene.gff3"
    fai_path = annot_dir / "Gmax_880_v6.0.fa.fai"
    sites_tsv_path = args.data_dir / "02_mut-infor" / "mu-infor_Gmax_880_Wm82-test.txt"

    engine = create_async_engine(args.database_url, pool_pre_ping=True)
    try:
        report = await import_local_test_preview(
            engine=engine,
            database_url=args.database_url,
            gff3_path=gff3_path,
            fai_path=fai_path,
            sites_tsv_path=sites_tsv_path,
        )
    finally:
        await engine.dispose()

    gene_action = "imported" if report.imported_genes else "verified existing"
    print(
        f"Local preview ready: {report.gene_count:,} GFF genes ({gene_action}), "
        f"{report.site_count:,} mutation-site records, draft release "
        f"{report.release_version}, assembly {report.assembly_name} "
        f"({report.annotation_sha256[:12]} annotation SHA-256, "
        f"{report.source_sha256[:12]} TSV SHA-256)."
    )


def main() -> None:
    args = _parser().parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
