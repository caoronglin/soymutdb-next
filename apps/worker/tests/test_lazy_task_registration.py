"""Registering worker queues must not initialize scientific runtimes."""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_all_worker_tasks_register_without_scientific_imports():
    worker = Path(__file__).resolve().parents[1]
    repository = worker.parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(worker / "src"), str(repository / "packages/jobs-py/src")]
    )
    result = subprocess.run(
        [sys.executable, "-c", """
import importlib.abc
import json
import sys

heavy = {
    "scanpy", "anndata", "numpy", "scipy", "pandas", "numba", "pyarrow",
    "h5py", "matplotlib", "pysam", "cyvcf2", "sklearn",
}

class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in heavy:
            raise RuntimeError("eager scientific import: " + fullname)

sys.meta_path.insert(0, Guard())
from soymutdb_worker.main import celery_app
celery_app.loader.import_default_modules()
print(json.dumps(sorted(name for name in celery_app.tasks
                        if name.startswith("soymutdb_worker."))))
"""],
        cwd=repository, env=environment, capture_output=True, text=True,
        timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    registered = set(json.loads(result.stdout.splitlines()[-1]))
    required = {
        "analyses.run_fastp", "analyses.run_scanpy", "blast.run_blast",
        "cleanup.cleanup_expired_blast_jobs", "cleanup.cleanup_temp_files",
        "email.send_seed_request_email", "export.cleanup_old_exports",
        "export.export_variants", "expression.import_expression_csv",
        "gwas.run_gwas", "homolog.import_homolog_csv", "ingest.import_gff3",
        "ingest.import_mutant_lines", "ingest.import_vcf", "ingest.run_import_adapter",
        "native_retention.cleanup", "notifications.create_notification",
        "page_builder_publish.publish_definition", "release.refresh_release_pointer",
        "static_pages.build_static_pages", "static_publish.build_static_release",
        "stats.compute_chromosome_density", "stats.compute_gene_burden",
        "stats.compute_mutant_line_comparison", "stats.update_release_stats",
    }
    assert {"soymutdb_worker.tasks." + name for name in required} <= registered
