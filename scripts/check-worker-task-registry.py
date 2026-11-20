"""Fail unless the runtime Worker image registers every SoyMutDB task."""

from importlib.metadata import version

import soymutdb_jobs
from soymutdb_worker.main import celery_app

EXPECTED_TASKS = {
    "soymutdb_worker.tasks.analyses.run_fastp",
    "soymutdb_worker.tasks.analyses.run_scanpy",
    "soymutdb_worker.tasks.blast.run_blast",
    "soymutdb_worker.tasks.blast_index.build_index",
    "soymutdb_worker.tasks.blast_index_tasks.build_blast_index",
    "soymutdb_worker.tasks.blast_index_tasks.check_blast_index_health",
    "soymutdb_worker.tasks.cleanup.cleanup_expired_blast_jobs",
    "soymutdb_worker.tasks.cleanup.cleanup_temp_files",
    "soymutdb_worker.tasks.comparative.build_artifact",
    "soymutdb_worker.tasks.email.send_seed_request_email",
    "soymutdb_worker.tasks.export.cleanup_old_exports",
    "soymutdb_worker.tasks.export.export_variants",
    "soymutdb_worker.tasks.expression.import_expression_csv",
    "soymutdb_worker.tasks.gwas.run_gwas",
    "soymutdb_worker.tasks.homolog.import_homolog_csv",
    "soymutdb_worker.tasks.ingest.import_gff3",
    "soymutdb_worker.tasks.ingest.import_mutant_lines",
    "soymutdb_worker.tasks.ingest.import_vcf",
    "soymutdb_worker.tasks.ingest.run_import_adapter",
    "soymutdb_worker.tasks.native_retention.cleanup",
    "soymutdb_worker.tasks.notifications.create_notification",
    "soymutdb_worker.tasks.page_builder_publish.publish_definition",
    "soymutdb_worker.tasks.release.refresh_release_pointer",
    "soymutdb_worker.tasks.static_pages.build_static_pages",
    "soymutdb_worker.tasks.static_publish.build_static_release",
    "soymutdb_worker.tasks.stats.compute_chromosome_density",
    "soymutdb_worker.tasks.stats.compute_gene_burden",
    "soymutdb_worker.tasks.stats.compute_mutant_line_comparison",
    "soymutdb_worker.tasks.stats.update_release_stats",
}


def main() -> None:
    """Import configured task modules and compare the complete business registry."""
    assert version("soymutdb-jobs") == "0.1.0"
    assert soymutdb_jobs.__name__ == "soymutdb_jobs"

    celery_app.loader.import_default_modules()
    registered_tasks = {
        task_name
        for task_name in celery_app.tasks
        if task_name.startswith("soymutdb_worker.tasks.")
    }
    missing = EXPECTED_TASKS - registered_tasks
    unexpected = registered_tasks - EXPECTED_TASKS
    assert not missing, f"missing Worker tasks: {sorted(missing)}"
    assert not unexpected, f"untracked Worker tasks: {sorted(unexpected)}"
    print(f"Worker task registry OK: {len(registered_tasks)} tasks")


if __name__ == "__main__":
    main()
