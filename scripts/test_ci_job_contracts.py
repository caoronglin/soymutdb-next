"""Enforce the CNB-primary / GitHub-mirror delivery architecture.

The delivery pipeline used to exist only as four GitHub Actions workflows with
their build/test/scan logic inlined. The logic now lives in checked-in scripts
that both CI providers call, and `.cnb.yml` is authoritative. These contracts
fail when someone re-inlines logic into a workflow, or when the two providers
stop agreeing on the pins and job list.

Run with: python3 -m unittest scripts.test_ci_job_contracts -v
"""
from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

NODE_VERSION = "24.19.0"
PNPM_VERSION = "11.21.0"
PYTHON_VERSION = "3.14"

CNB_CONFIG = ROOT / ".cnb.yml"
LEGACY_WORKFLOWS = (
    ".github/workflows/ci.yml",
    ".github/workflows/baseline-validation.yml",
    ".github/workflows/pages.yml",
    ".github/workflows/e2e-smoke.yml",
)

SHARED_SCRIPTS = (
    "scripts/ci-job-steps.sh",
    "scripts/setup-workspace.sh",
    "scripts/stage-pages-publication.sh",
    "scripts/verify-frontend-artifacts.sh",
    "scripts/verify-backend-tests.sh",
    "scripts/with-postgres-service.sh",
    "scripts/build-static-apps.sh",
    "scripts/build-release-image.sh",
    "scripts/release-contract.golden.sh",
    "scripts/build-pages-artifact.sh",
    "scripts/verify-pages-artifact.sh",
    "scripts/mcp-transport-smoke.sh",
    "scripts/assert-clickhouse-migration.py",
    "scripts/smoke.sh",
    "scripts/start-cloud-dev.sh",
    "scripts/acceptance.sh",
)

PIPELINE_FILES = (
    ".cnb/pipelines/verify.yml",
    ".cnb/pipelines/api.yml",
    ".cnb/pipelines/dependency-governance.yml",
    ".cnb/pipelines/docker-images.yml",
    ".cnb/pipelines/release.yml",
    ".cnb/pipelines/pages-publish.yml",
    ".cnb/pipelines/acceptance.yml",
)


def _cnb() -> dict:
    return yaml.safe_load(CNB_CONFIG.read_text(encoding="utf-8"))


# CNB data-volume types (docs.cnb.cool/zh/build/grammar.md#pipeline-volumes).
# The declared type defaults to copy-on-write when omitted.
_CNB_VOLUME_TYPES = frozenset(
    {
        "rw",
        "ro",
        "cow",
        "data",
        "read-write",
        "read-only",
        "copy-on-write",
        "copy-on-write-read-only",
    }
)


def _cnb_volume_path(entry: str, location: str) -> str:
    """Return the mount path of a CNB `docker.volumes` entry, or fail the test.

    A CNB volume is `<group>:<path>:<type>`, `<path>:<type>` or `<path>` -- it is
    NOT Docker's `host:container`. Misreading the format is what made the first
    attempt at this fix fail a second time in Prepare:

        volumes:
          - /cache/pnpm-store:/cache/pnpm-store

    CNB splits that into group=/cache/pnpm-store, path=/cache/pnpm-store and no
    type, then rejects the leading segment as an unknown *type*:

        Pipeline prepare error:
          Unsupported volume type. 不支持的数据卷类型: /cache/pnpm-store

    The old version of this test accepted any 2-segment entry whose first part
    started with "/" and silently treated it as a path, so it validated a
    document CNB refuses to prepare. Assert the real grammar instead.
    """
    parts = entry.split(":")
    if len(parts) > 3:
        raise AssertionError(
            f"{location}: volume {entry!r} has {len(parts)} colon-separated "
            "segments; the grammar is <group>:<path>:<type>"
        )
    if len(parts) == 3:
        group, path, volume_type = parts
        if not group:
            raise AssertionError(f"{location}: volume {entry!r} has an empty group")
        if volume_type not in _CNB_VOLUME_TYPES:
            raise AssertionError(
                f"{location}: volume {entry!r}: unknown type {volume_type!r}; "
                f"expected one of {sorted(_CNB_VOLUME_TYPES)}"
            )
    elif len(parts) == 2:
        path, volume_type = parts
        if volume_type not in _CNB_VOLUME_TYPES:
            # e.g. `- /cache/pnpm-store:/cache/pnpm-store`: the second segment is
            # a CONTAINER PATH, not a type, so CNB reads the first as the type
            # and fails Prepare with "Unsupported volume type".
            raise AssertionError(
                f"{location}: volume {entry!r}: {volume_type!r} is not a volume "
                "type -- CNB parses `<path>:<type>`, not Docker's `host:container`; "
                "use a bare `- <path>` to mount the same path on the node"
            )
    else:
        path = parts[0]
    if not path.startswith("/"):
        raise AssertionError(
            f"{location}: volume {entry!r}: path {path!r} must be absolute"
        )
    return path


def _cnb_pipelines(branch: str, event: str) -> list[dict]:
    document = _cnb()
    return document.get(branch, {}).get(event, []) or []


def _pipeline_names(branch: str, event: str) -> set[str]:
    return {pipeline["name"] for pipeline in _cnb_pipelines(branch, event)}


def _cnb_text() -> str:
    return CNB_CONFIG.read_text(encoding="utf-8")


def _iter_script_bodies(node: object, path: str = ""):
    """Yield (location, body) for every `script:` value, at any nesting depth."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "script" and isinstance(value, str):
                yield path, value
            else:
                yield from _iter_script_bodies(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _iter_script_bodies(value, f"{path}[{index}]")


def _iter_pipelines(node: object):
    """Yield every pipeline object, whatever branch/event nests it.

    The CNB config is `branch -> event -> [pipeline]`. Walking it generically
    keeps the assertions from hard-coding a shape that a new event would break.
    """
    if isinstance(node, dict):
        if "stages" in node or "name" in node:
            yield node
            return
        for value in node.values():
            yield from _iter_pipelines(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_pipelines(value)


def _cnb_config_files() -> tuple[Path, ...]:
    return (CNB_CONFIG, *sorted((ROOT / ".cnb").glob("*.yml"))) + tuple(
        ROOT / name for name in PIPELINE_FILES
    )


def _workflow_text(name: str) -> str:
    return (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")


def _flatten(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten(item) for item in value)
    return str(value)


class DeliveryArchitectureTests(unittest.TestCase):
    """The CNB pipeline is authoritative and the GitHub workflows mirror it."""

    def test_cnb_pipeline_exists_and_declares_the_delivery_jobs(self) -> None:
        self.assertTrue(CNB_CONFIG.is_file(), "missing .cnb.yml")
        push = _pipeline_names("main", "push")
        self.assertLessEqual(
            {
                "verify",
                "clickhouse-migration",
                "mcp-e2e",
            },
            push,
        )
        # Release and publication live in the fallback branch: they run on main
        # pushes, tags and manual buttons, never on pull requests.
        self.assertLessEqual({"release", "publish"}, _pipeline_names("$", "push"))
        self.assertLessEqual(
            {
                "verify",
                "clickhouse-migration",
                "mcp-e2e",
                "docker-images (amd64)",
                "docker-images (arm64)",
            },
            _pipeline_names("main", "push"),
        )
        self.assertIn("verify", _pipeline_names("main", "pull_request"))
        self.assertEqual({"release-tagged"}, _pipeline_names("$", "tag_push"))

    def test_every_cnb_pipeline_calls_the_shared_job_entrypoint(self) -> None:
        text = _cnb_text()
        self.assertIn("scripts/ci-job-steps.sh run frontend", text)
        self.assertIn("scripts/ci-job-steps.sh run api-tests", text)
        self.assertIn("scripts/ci-job-steps.sh run dependency-governance", text)
        self.assertIn("scripts/ci-job-steps.sh run image-build", text)
        self.assertIn("scripts/ci-job-steps.sh run release", text)

    def test_cnb_job_catalog_matches_the_scripts_on_disk(self) -> None:
        for script in SHARED_SCRIPTS:
            self.assertTrue((ROOT / script).is_file(), f"missing shared script: {script}")

        catalog = subprocess.run(
            ["bash", "scripts/ci-job-steps.sh", "list"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        jobs = set(catalog.stdout.split())
        self.assertLessEqual(
            {
                "frontend",
                "api-tests",
                "dependency-governance",
                "compose-acceptance",
                "clickhouse-migration",
                "mcp-e2e",
                "image-build",
                "release",
            },
            jobs,
        )

    def test_github_workflows_delegate_instead_of_inlining_gates(self) -> None:
        ci = _workflow_text("ci.yml")
        for delegation in (
            "scripts/verify-frontend-artifacts.sh",
            "scripts/verify-backend-tests.sh",
            "scripts/ci-job-steps.sh run dependency-governance",
            "scripts/ci-job-steps.sh run clickhouse-migration",
            "scripts/ci-job-steps.sh run mcp-e2e",
            "scripts/build-release-image.sh",
            "scripts/release-contract.golden.sh",
            "scripts/build-pages-artifact.sh",
            "scripts/verify-pages-artifact.sh",
        ):
            self.assertIn(delegation, ci, delegation)

        # The inlined per-image build/smoke/scan sequence must be gone: it now
        # lives once, in the script both providers call.
        for inlined in (
            "docker build -f infra/docker/Dockerfile.api",
            "Trivy scan API image (hard gate)",
            "Generate API SPDX SBOM",
        ):
            self.assertNotIn(inlined, ci, inlined)

    def test_every_legacy_workflow_announces_the_authoritative_source(self) -> None:
        for workflow in LEGACY_WORKFLOWS:
            text = _workflow_text(Path(workflow).name)
            self.assertIn(".cnb.yml", text, workflow)

    def test_legacy_workflows_keep_a_working_dispatch_path(self) -> None:
        """The GitHub mirror must stay runnable until it is formally retired."""
        for workflow in LEGACY_WORKFLOWS:
            parsed = yaml.safe_load(_workflow_text(Path(workflow).name))
            self.assertTrue(parsed.get("jobs"), workflow)
            for job in parsed["jobs"].values():
                self.assertTrue(job.get("steps"), workflow)

    def test_pipeline_files_are_valid_yaml_and_consistent_with_the_root_config(self) -> None:
        for pipeline_file in PIPELINE_FILES:
            path = ROOT / pipeline_file
            self.assertTrue(path.is_file(), f"missing pipeline: {pipeline_file}")
            yaml.safe_load(path.read_text(encoding="utf-8"))

        self.assertTrue((ROOT / ".cnb/web_trigger.yml").is_file())
        triggers = yaml.safe_load((ROOT / ".cnb/web_trigger.yml").read_text(encoding="utf-8"))
        declared = {
            button["event"]
            for group in triggers["branch"]
            for button in group["buttons"]
        }
        self.assertLessEqual(
            {
                "web_trigger_verify",
                "web_trigger_acceptance",
                "web_trigger_workspace-preview",
                "web_trigger_docker-images",
                "web_trigger_release",
                "web_trigger_publish",
            },
            declared,
        )

    def test_web_trigger_events_have_matching_pipelines(self) -> None:
        document = _cnb()
        fallback = document.get("$", {})
        for event in (
            "web_trigger_verify",
            "web_trigger_acceptance",
            "web_trigger_workspace-preview",
            "web_trigger_docker-images",
            "web_trigger_release",
            "web_trigger_publish",
        ):
            self.assertIn(event, fallback, event)

    def test_toolchain_pins_agree_across_pipelines_and_manifests(self) -> None:
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(package["packageManager"], f"pnpm@{PNPM_VERSION}")
        self.assertEqual((ROOT / ".nvmrc").read_text(encoding="utf-8").strip(), NODE_VERSION)
        self.assertEqual(
            (ROOT / ".node-version").read_text(encoding="utf-8").strip(), NODE_VERSION
        )

        cnb = _cnb_text()
        self.assertIn(f"node:{NODE_VERSION}", cnb)
        self.assertIn(f"python:{PYTHON_VERSION}", cnb)
        for stale in ("node:20", "node:22", "pnpm@10", "python:3.12"):
            self.assertNotIn(stale, cnb, stale)

        # The pnpm version is no longer inlined into every CNB stage: the
        # workspace bootstrap lives in scripts/setup-workspace.sh, which reads
        # the same pin. Assert it wherever it actually lives, and assert that
        # .cnb.yml cannot silently pick a different one.
        for provider_config in (ROOT / "scripts/setup-workspace.sh",):
            text = provider_config.read_text(encoding="utf-8")
            self.assertIn(f'PNPM_VERSION="${{SOYMUTDB_CI_PNPM_VERSION:-{PNPM_VERSION}}}"', text)
        self.assertNotIn("corepack prepare pnpm@", cnb)

        shared = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")
        self.assertIn(f'NODE_VERSION="${{SOYMUTDB_CI_NODE_VERSION:-{NODE_VERSION}}}"', shared)
        self.assertIn(f'PNPM_VERSION="${{SOYMUTDB_CI_PNPM_VERSION:-{PNPM_VERSION}}}"', shared)
        self.assertIn(f'PYTHON_VERSION="${{SOYMUTDB_CI_PYTHON_VERSION:-{PYTHON_VERSION}}}"', shared)

    def test_pull_request_pipelines_never_hold_release_credentials(self) -> None:
        """PR builds get a restricted token, so no publish step may run there."""
        for branch, event in (("main", "pull_request"), ("$", "pull_request")):
            for pipeline in _cnb_pipelines(branch, event):
                text = _flatten(pipeline)
                for forbidden in ("docker login", "cosign", "docker push"):
                    self.assertNotIn(forbidden, text, f"{branch}/{event}: {forbidden}")

        # Credential-bearing pipelines must be main/tag-triggered only.
        for pipeline in _cnb_pipelines("$", "push"):
            if pipeline["name"] not in {"release", "publish"}:
                continue
            self.assertTrue(pipeline.get("stages"), pipeline["name"])

    def test_no_duplicate_verification_logic_between_providers(self) -> None:
        """Shared logic must be scripted once, not copy-pasted per provider.

        Each gate's identifying string must appear in exactly one executing
        place: either a shared script, or the provider config as a bare
        delegation call.
        """
        ci = _workflow_text("ci.yml")
        shared_scripts = "\n".join(
            (ROOT / script).read_text(encoding="utf-8")
            for script in SHARED_SCRIPTS
            if script.endswith((".sh",))
        )

        for marker in (
            "Smoke test Worker task registry (hard gate)",
            "Assert actual native image architecture (hard gate)",
            "Merge manifests, attest evidence, and write release manifest",
        ):
            self.assertIn(marker, shared_scripts, marker)
            self.assertNotIn(marker, ci, marker)

    def test_image_verification_and_publication_are_separate_pipelines(self) -> None:
        verify_names = {"docker-images (amd64)", "docker-images (arm64)"}
        publish_names = {"release"}
        for pipeline in _cnb_pipelines("$", "push") + _cnb_pipelines("main", "push"):
            text = _flatten(pipeline)
            if pipeline["name"] in verify_names:
                self.assertNotIn("docker push", text)
                self.assertNotIn("cosign", text)
            if pipeline["name"] in publish_names:
                self.assertNotIn("docker build", text)

    def test_arch_specific_image_pipelines_use_native_runners(self) -> None:
        pipelines = {pipeline["name"]: pipeline for pipeline in _cnb_pipelines("main", "push")}
        amd64 = pipelines["docker-images (amd64)"]
        arm64 = pipelines["docker-images (arm64)"]

        self.assertEqual(amd64["env"]["SOYMUTDB_CI_ARCH"], "amd64")
        self.assertEqual(arm64["env"]["SOYMUTDB_CI_ARCH"], "arm64")
        # amd64 is the default runner; arm64 must select an arm64 node so the
        # exported image architecture is natively proven, never emulated.
        self.assertNotIn("tags", amd64.get("runner", {}))
        self.assertEqual(arm64["runner"]["tags"], "cnb:arch:arm64:v8")

    # -------------------------------------------------------------------------
    # Stage shell
    # -------------------------------------------------------------------------
    # Regression guard. A CNB stage body is executed with `sh`; on the platform
    # base images that is dash, which rejects `set -o pipefail`:
    #
    #   sh: 1: set: Illegal option -o pipefail   → exit 2, stage error
    #
    # The very first real CNB build of this pipeline died in "Setup workspace
    # with cache" for exactly that reason. `python3 -m compileall` does not
    # catch it, `yaml.safe_load` does not catch it, and the CNB validator does
    # not catch it: the only place it surfaces is a paid, remote build. These
    # tests make it surface locally instead.

    def test_stage_scripts_never_rely_on_the_platform_shell(self) -> None:
        """Every CNB stage body must pin its interpreter to bash."""
        bashisms = (
            "set -o pipefail",
            "set -euo pipefail",
            "set -uo pipefail",
        )
        offenders = []
        for config in _cnb_config_files():
            document = yaml.safe_load(config.read_text(encoding="utf-8"))
            for location, body in _iter_script_bodies(document):
                # A stage body is a single command line handed to `sh`. Either it
                # is a multiline block (whose first line decides the syntax that
                # `sh` must parse), or a one-liner that must itself start with an
                # explicit interpreter.
                first_line = body.strip().splitlines()[0].strip()
                if any(bashism in body for bashism in bashisms) and not first_line.startswith(
                    ("bash", "./")
                ):
                    offenders.append(f"{config.name}:{location}: {first_line[:80]}")
                # Multiline blocks are parsed by `sh` line by line, so any bashism
                # anywhere in an un-pinned block is fatal regardless of the first
                # line.
                if len(body.strip().splitlines()) > 1 and not first_line.startswith(
                    ("bash", "./")
                ):
                    for line in body.splitlines():
                        stripped = line.strip()
                        for pattern in (
                            "[[ ",
                            "]]",
                            "source ",
                            "set -o ",
                            "pipefail",
                        ):
                            if stripped.startswith(pattern) or pattern in stripped:
                                offenders.append(
                                    f"{config.name}:{location}: {stripped[:80]}"
                                )
                                break
        self.assertEqual(offenders, [], "stage bodies must pin bash:\n" + "\n".join(offenders))

    def test_sh_does_not_catch_the_original_bug_so_we_parse_instead(self) -> None:
        """Document why the guard above is a static check, not `sh -n`.

        `sh -n` (syntax-only) accepts `set -euo pipefail`: the option is only
        rejected at *runtime*, because dash resolves `set -o <name>` when the
        builtin executes. Relying on `sh -n` would therefore have shipped the
        exact failure that took down the first real CNB build. This test pins
        that knowledge so nobody "simplifies" the guard into a no-op.
        """
        body = "set -euo pipefail\ncorepack enable\n"

        syntax_only = subprocess.run(
            ["sh", "-n"], input=body, capture_output=True, text=True
        )
        self.assertEqual(
            syntax_only.returncode,
            0,
            "`sh -n` unexpectedly rejects pipefail; the static guard could be simplified",
        )

        executed = subprocess.run(["sh"], input=body, capture_output=True, text=True)
        self.assertNotEqual(executed.returncode, 0)
        self.assertIn("Illegal option", executed.stderr)

    def test_no_stage_depends_on_another_stages_container_state(self) -> None:
        """CNB gives every stage a fresh container.

        Regression guard for the second failure the first real build produced,
        after the `sh`/pipefail one was fixed:

            Setup workspace with cache   → success (52.5s)
            Frontend verification        → error, exit 127
              scripts/ci-job-steps.sh: line 89: pnpm: command not found

        `corepack enable` had run in the setup stage, but it writes a shim into
        that stage's container, which is destroyed when the stage exits. The
        checkout carries no node_modules either. So:
          * no stage may rely on a "setup" stage having prepared it;
          * every job body that needs the JS toolchain must bootstrap itself;
          * only declared `volumes` cross the container boundary.
        """
        steps = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")

        # The shared bootstrap must exist and be used by the jobs that need it.
        self.assertTrue((ROOT / "scripts/setup-workspace.sh").is_file())
        self.assertIn("ensure_workspace()", steps)
        self.assertIn("setup-workspace.sh", steps)

        # Extract every shell function body, then follow the call chain: a job
        # may delegate its bootstrap to a helper (frontend_run -> frontend_install).
        def function_bodies(text: str) -> dict[str, str]:
            bodies: dict[str, str] = {}
            for match in re.finditer(r"^(\w+)\(\) \{\n", text, re.M):
                start = match.end()
                end = text.index("\n}\n", start)
                bodies[match.group(1)] = text[start:end]
            return bodies

        bodies = function_bodies(steps)

        def reaches_bootstrap(name: str, seen: frozenset[str] = frozenset()) -> bool:
            if name in seen or name not in bodies:
                return False
            body = bodies[name]
            if "setup-workspace.sh" in body:
                return True
            for callee in re.findall(r"^\s*(\w+)\s*$", body, re.M):
                if reaches_bootstrap(callee, seen | {name}):
                    return True
            return False

        # Every job that shells out to pnpm must reach the bootstrap, however the
        # call chain is structured.
        for job in ("frontend", "dependency-governance"):
            entry = f"{job.replace('-', '_')}_run"
            self.assertTrue(
                reaches_bootstrap(entry),
                f"{entry} calls pnpm but never reaches scripts/setup-workspace.sh; "
                "it would fail with `pnpm: command not found` in its own container",
            )

        # A stage named like a setup step must not masquerade as preparation for
        # later stages. If one comes back, it must at least be honest about it.
        document = yaml.safe_load(CNB_CONFIG.read_text(encoding="utf-8"))
        for branch, event in (("main", "pull_request"), ("main", "push"), ("$", "web_trigger_verify")):
            for pipeline in _cnb_pipelines(branch, event):
                stage_names = [stage.get("name", "") for stage in pipeline.get("stages", [])]
                for name in stage_names:
                    self.assertNotIn(
                        "Setup workspace",
                        name,
                        f"{branch}/{event}/{pipeline['name']}: {name!r} implies it "
                        "prepares later stages, which is impossible across containers",
                    )
                # Every stage that runs a pnpm-dependent job body must be able
                # to reach the store, or the install silently de-caches into a
                # dead layer. The store lives in the PIPELINE-level volumes
                # (`docker.volumes`); a stage-level `volumes:` key is not part of
                # the CNB schema, and an entry written as `host:container` is
                # read as an unknown volume TYPE. Either aborts the whole build
                # in Prepare, before any stage runs:
                #
                #   Unsupported volume type. 不支持的数据卷类型: /cache/pnpm-store
                #
                # So assert against `docker.volumes`, and separately assert that
                # no stage declares `volumes:` at all.
                pipeline_volumes = " ".join(
                    str(v) for v in (pipeline.get("docker", {}).get("volumes") or [])
                )
                for stage in pipeline.get("stages", []):
                    self.assertNotIn(
                        "volumes",
                        stage,
                        f"{branch}/{event}/{pipeline['name']}/{stage.get('name')}: "
                        "stage-level `volumes` is not a supported key and fails "
                        "Prepare with `Unsupported volume type`; declare it as "
                        "pipeline `docker.volumes`",
                    )
                    script = stage.get("script", "")
                    if "run frontend" in script or "run dependency-governance" in script:
                        self.assertIn(
                            "pnpm-store",
                            pipeline_volumes,
                            f"{branch}/{event}/{pipeline['name']}/{stage['name']}: "
                            "pnpm job without a persistent store volume",
                        )

    def test_dependency_governance_stage_can_reach_its_python_tooling(self) -> None:
        """The governance gate is Python-backed and needs PyYAML plus uv.

        Regression for a real CNB build, surfaced only once the worker gate in
        front of it stopped failing first:

            ==> Dependency governance
            $ python3 scripts/dependency_governance.py graphs --output ...
            Traceback (most recent call last):
              File "/workspace/scripts/dependency_governance.py", line 23, in <module>
                import yaml
            ModuleNotFoundError: No module named 'yaml'

        The GitHub mirror escapes this because its job explicitly runs
        `python -m pip install --quiet PyYAML==<pin> uv==<pin>` after
        `actions/setup-python`. The CNB stage ran the same job body on
        `node:24.19.0`, which carries no Python at all, and `PyYAML` is not
        declared by any pyproject -- it was only ever present by accident on the
        mirror. Every assertion below is load-bearing; dropping one re-opens the
        failure with the same message.

        Note the gate is `if: always()` on GitHub and a hard CNB stage for the
        same reason: an unavailable analyzer must fail closed, never skip green.
        """
        steps = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")

        def function_bodies(text: str) -> dict[str, str]:
            bodies: dict[str, str] = {}
            for match in re.finditer(r"^(\w+)\(\) \{\n", text, re.M):
                start = match.end()
                end = text.index("\n}\n", start)
                bodies[match.group(1)] = text[start:end]
            return bodies

        bodies = function_bodies(steps)

        # 1. The Python tooling must be provisioned by the job body, so the gate
        #    is self-sufficient on either provider instead of depending on an
        #    image that happens to ship it.
        self.assertIn("ensure_governance_tooling", bodies)

        tooling_body = bodies["ensure_governance_tooling"]
        # The graph generator imports PyYAML; no pyproject declares it, so the
        # job must install it explicitly or the gate cannot run at all.
        self.assertIn("PyYAML", tooling_body)
        # The analyzers shell out to `uv`/`uvx` (deptry, pip-audit, ...), so an
        # interpreter alone is not enough.
        self.assertIn("uv", tooling_body)
        # Both pins must come from the shared version variables, never an
        # inline literal that can drift from the GitHub step and the Dockerfiles.
        self.assertIn("GOVERNANCE_PYYAML_VERSION", tooling_body)
        self.assertIn("UV_VERSION", tooling_body)
        # Pinned through the shared variables (asserted against the GitHub
        # step's literal pins in block 4), never through an inline literal that
        # could drift between the two providers.
        self.assertNotRegex(
            tooling_body,
            r'"(?:PyYAML|uv)==\d',
            "the PyYAML/uv installs must use the shared version variables, "
            "not an inline literal that the GitHub step can drift from",
        )
        # Fail closed rather than silently skipping the gate on a bad image.
        self.assertIn(
            "interpreter_matches_pin",
            tooling_body,
            "the governance gate must reject an interpreter that misses the pin",
        )
        self.assertRegex(
            tooling_body,
            r"(?m)^\s*command -v python3",
            "a missing python3 must be a hard error, not a skipped analyzer",
        )

        # 2. The gate must actually run it, after the pnpm bootstrap, or the
        #    install is dead code.
        step_body = bodies["dependency_governance_step"]
        self.assertIn("ensure_workspace", step_body)
        self.assertIn("ensure_governance_tooling", step_body)
        self.assertLess(
            step_body.index("ensure_workspace"),
            step_body.index("ensure_governance_tooling"),
            "the tooling install must not precede the workspace bootstrap",
        )

        # 3. The stage environment must supply the interpreter. The job body can
        #    install PyYAML/uv, but it cannot conjure a Python 3.14 interpreter,
        #    and `node:24.19.0` -- the image this stage used to pin -- has none.
        for config in _cnb_config_files():
            document = yaml.safe_load(config.read_text(encoding="utf-8"))
            for pipeline in _iter_pipelines(document):
                governance_stages = [
                    stage
                    for stage in pipeline.get("stages", [])
                    if "run dependency-governance" in str(stage.get("script", ""))
                ]
                if not governance_stages:
                    continue

                build = (pipeline.get("docker") or {}).get("build")
                inherited = build if isinstance(build, dict) else {}
                for stage in governance_stages:
                    image = str(stage.get("image", ""))
                    # A stage `image:` overrides the pipeline environment, so it
                    # must itself be a toolchain that carries Python. The image
                    # this regression is about is exactly the one that must never
                    # come back.
                    self.assertNotIn(
                        "node:",
                        image,
                        f"{config.name}/{stage.get('name')}: image={image!r} has "
                        "no Python, but the governance gate runs a Python script",
                    )
                    if not image:
                        self.assertTrue(
                            inherited.get("dockerfile"),
                            f"{config.name}/{stage.get('name')}: the stage drops its "
                            "`image:` without a pipeline-level docker.build to "
                            "inherit a dual-toolchain environment from",
                        )

        # 4. The PyYAML pin must agree with the GitHub step that has always
        #    worked, so the two providers cannot install different versions.
        workflow = _workflow_text("ci.yml")
        self.assertIn("PyYAML==", workflow)
        pyyaml_pin = re.search(r"PyYAML==(\d+\.\d+\.\d+)", workflow)
        self.assertIsNotNone(pyyaml_pin, "the GitHub governance step must pin PyYAML")
        pyyaml_default = re.search(
            r"GOVERNANCE_PYYAML_VERSION=.*?SOYMUTDB_CI_GOVERNANCE_PYYAML_VERSION:-"
            r"(\d+\.\d+\.\d+)",
            steps,
        )
        self.assertIsNotNone(
            pyyaml_default, "the shared PyYAML pin must have a numeric default"
        )
        self.assertEqual(
            pyyaml_default.group(1),
            pyyaml_pin.group(1),
            "the shared PyYAML pin must match the version the GitHub step installs",
        )

        uv_pin = re.search(r"uv==(\d+\.\d+\.\d+)", workflow)
        self.assertIsNotNone(uv_pin, "the GitHub governance step must pin uv")
        self.assertIn(
            f"${{SOYMUTDB_CI_UV_VERSION:-{uv_pin.group(1)}}}",
            steps,
            "the shared uv pin must match the version the GitHub step installs",
        )

    def test_i18n_test_mock_interpolates_like_the_real_library(self) -> None:
        """The shared double must substitute {{name}}, not return it literally.

        Real CNB failure, after the stable-`t` fix removed the render loop:

            src/routes/imports/import-validation-report.test.tsx
            Unable to find an element with the text: /1 validation errors/
              <p>{{errors}} validation errors</p>

        The component interpolates a default and the test asserts the result. Two
        separate gaps produced the literal template: that test did not mock
        `react-i18next` at all (and uninitialised i18next returns `defaultValue`
        verbatim), and the shared double returned it verbatim too. The test now
        uses the shared double, which is why the substitution is asserted here.
        """
        for app in ("apps/admin", "apps/web"):
            mock = (ROOT / app / "src/test/mocks.ts").read_text(encoding="utf-8")
            # Substitution is implemented with a replace() over a `{{name}}`
            # pattern. Assert the mechanism rather than its exact spelling.
            self.assertIn(
                ".replace(",
                mock,
                f"{app}/src/test/mocks.ts must substitute {{{{name}}}} placeholders",
            )
            self.assertIn(
                "{{",
                mock.replace("{{", "{{"),
                f"{app}/src/test/mocks.ts must handle {{{{name}}}} placeholders",
            )
            self.assertIn("(match, name", mock.replace("(match, name", "(match, name"))
            self.assertIn("defaultValue", mock, app)

        # Any test that asserts an interpolated default must mock i18next with the
        # shared double (otherwise nothing substitutes the placeholder).
        import_failures = []
        for test_file in sorted(ROOT.glob("apps/admin/src/**/*.test.ts*")) + sorted(
            ROOT.glob("apps/web/src/**/*.test.ts*")
        ):
            text = test_file.read_text(encoding="utf-8")
            asserts_interpolation = "validation errors" in text and "getByText" in text
            if asserts_interpolation and "test/mocks" not in text:
                import_failures.append(str(test_file.relative_to(ROOT)))
        self.assertEqual(
            import_failures,
            [],
            "these tests assert interpolated output but do not use the shared "
            "i18n double:\n" + "\n".join(import_failures),
        )

    def test_i18n_test_mocks_do_not_return_a_fresh_t_per_render(self) -> None:
        """An inline `useTranslation` mock makes effects loop forever.

        Real CNB failure, after the env leak was fixed:

            src/routes/news/trash.test.tsx > purges only after exact slug
            AssertionError: expected "vi.fn()" to be called 2 times, but got 224 times
            src/routes/news/trash.test.tsx > requires exact slug...
            Error: Unable to perform pointer interaction as the element has
                   `pointer-events: none`

        The page does `useCallback(load, [message, page, pageSize, t])` and
        `useEffect(() => { void load(); }, [load])`. The test mocked
        `useTranslation: () => ({ t: (key) => key })`, which returns a NEW `t`
        every render, so `load` changed every render, so the fetch effect re-ran
        every render. 224 was the click landing while the tree was still
        re-rendering. i18next memoises `t`; the mock must too.
        """
        # A per-render `t` is one whose VALUE is an arrow function declared inside
        # the `useTranslation` return. A reference to a module-scope function is
        # stable and fine; so is the shared double.
        offenders = []
        pattern = re.compile(
            r"useTranslation:\s*\(\)\s*=>\s*\(\{[^}]*?t:\s*(?P<value>\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)",
            re.S,
        )
        for source in sorted(ROOT.glob("apps/*/src/**/*.test.ts*")):
            text = source.read_text(encoding="utf-8")
            if "mockTranslation" in text:
                continue
            for match in pattern.finditer(text):
                offenders.append(str(source.relative_to(ROOT)))
                break
        self.assertEqual(
            offenders,
            [],
            "these test files mock useTranslation with a per-render `t`; import the "
            "shared double from src/test/mocks.ts instead:\n" + "\n".join(offenders),
        )

        # The shared doubles must exist and expose a module-level `t`.
        for app in ("apps/admin", "apps/web"):
            mock = ROOT / app / "src/test/mocks.ts"
            self.assertTrue(mock.is_file(), f"missing shared i18n mock for {app}")
            text = mock.read_text(encoding="utf-8")
            self.assertIn("export const stableT", text)
            self.assertIn("mockTranslation", text)

    def test_js_unit_tests_do_not_inherit_the_build_environment(self) -> None:
        """`turbo run test` must not see the demo build's VITE_* variables.

        On a real CNB build the api-client suite failed with

            AssertionError: expected 'https://api.soymutdb.test/genes/Glyma...'
                                 to be '/api/v1/genes/Glyma.01G000100'

        `apiBaseUrl` resolves from `import.meta.env.VITE_API_BASE_URL` and only
        falls back to the relative base when it is unset — and the suite asserts
        the relative base, because it is testing path construction. CI exports
        VITE_API_BASE_URL for the demo build, and turbo.json lists it under
        `globalEnv`, so the build-time value leaked into the unit tests.

        The fix is to isolate the test run, not to weaken the URL assertions: a
        test whose result depends on an ambient variable is not a test of this
        package. `turbo run test` sets NODE_ENV=test, and vitest resolves
        `import.meta.env` from process.env, so the package config must clear the
        build variables before the config is evaluated.
        """
        config = (ROOT / "packages/api-client/vitest.config.ts").read_text(encoding="utf-8")
        for variable in ("VITE_API_BASE_URL", "VITE_JBROWSE_BASE_URL"):
            self.assertIn(
                f"delete process.env.{variable}",
                config,
                f"packages/api-client/vitest.config.ts must clear {variable} before "
                "vitest resolves import.meta.env",
            )

        # The variable must still be a tracked turbo input for build tasks, or
        # cross-environment builds would share cache entries.
        turbo = json.loads((ROOT / "turbo.json").read_text(encoding="utf-8"))
        self.assertIn("VITE_API_BASE_URL", turbo.get("globalEnv", []))

        # And it must still be exported for the gates that legitimately need it.
        gate = (ROOT / "scripts/verify-frontend-artifacts.sh").read_text(encoding="utf-8")
        self.assertIn("SOYMUTDB_CI_DEMO_API_URL", gate)

    def test_package_script_invocations_do_not_double_up_the_separator(self) -> None:
        """`pnpm run <script> -- --flag` forwards a literal "--" to the script.

        On a real CNB build the frontend gate ran

            pnpm --filter @soymutdb/i18n check:locale-keys -- --self-test

        which executed `node check-locale-keys.mjs -- --self-test` and failed
        with `ENOENT: no such file or directory, open '--'`. The symptom points
        at a missing locale file; the cause is an extra separator. pnpm consumes
        the FIRST `--` as its own end-of-options marker, so the second one is
        passed straight through to the script's argv.
        """
        offenders = []
        for script in SHARED_SCRIPTS:
            if not script.endswith(".sh"):
                continue
            text = "\n".join(
                line
                for line in (ROOT / script).read_text(encoding="utf-8").splitlines()
                if not line.lstrip().startswith("#")
            )
            for line in text.splitlines():
                # Any bare `--` after the script name. Looking only for `-- --`
                # would miss the equally broken one-separator form
                # (`pnpm run check -- --self-test`, where the flag itself is
                # `--self-test` and the separator is the sole `--`).
                if re.search(r"\bpnpm\b.*(^|\s)--(\s|$)", line):
                    offenders.append(f"{script}: {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            "these pnpm invocations forward a literal '--' to the script:\n"
            + "\n".join(offenders),
        )

    def test_frontend_gate_self_test_really_runs_the_self_test(self) -> None:
        """Regression: the locale checker must be invoked as a self-test.

        The bare `--` above meant the parity gate's self-test never executed; the
        checker instead read a file called `--` and failed. Assert the exact
        command shape that pnpm turns into `node check-locale-keys.mjs
        --self-test`, and that the checker treats `--self-test` as a mode flag
        rather than a path.
        """
        gate = (ROOT / "scripts/verify-frontend-artifacts.sh").read_text(encoding="utf-8")
        self.assertIn(
            "pnpm --filter @soymutdb/i18n check:locale-keys --self-test",
            gate,
            "the locale parity gate must run the checker's self-test",
        )

        checker = (ROOT / "packages/i18n/check-locale-keys.mjs").read_text(encoding="utf-8")
        self.assertIn('args[0] === "--self-test"', checker)

        manifest = json.loads(
            (ROOT / "packages/i18n/package.json").read_text(encoding="utf-8")
        )
        self.assertIn("check:locale-keys", manifest.get("scripts", {}))

        # Run the real thing: both the self-test and the fixture check must pass.
        for args in (["--self-test"], []):
            completed = subprocess.run(
                ["node", "check-locale-keys.mjs", *args],
                cwd=ROOT / "packages/i18n",
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"check-locale-keys.mjs {args} failed:\n{completed.stdout}\n{completed.stderr}",
            )

        # The invocation the gate used to make. The checker now filters a stray
        # `--` as defence in depth, so passing is correct — but the flag after it
        # must still select the self-test. A checker that swallowed the flag too
        # would "pass" by running the plain parity check, which is exactly the
        # false green this regression exists to prevent.
        completed = subprocess.run(
            ["node", "check-locale-keys.mjs", "--", "--self-test"],
            cwd=ROOT / "packages/i18n",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            f"the `--` form must degrade to a normal run:\n{completed.stdout}\n{completed.stderr}",
        )
        self.assertIn(
            "self-test passed",
            completed.stdout,
            "a stray `--` must not swallow the following --self-test flag",
        )

    def test_scripts_that_run_pnpm_bootstrap_their_own_container(self) -> None:
        """Generalised form of the container-lifecycle rule.

        The first real build failed at `Frontend verification` with
        `pnpm: command not found` because it inherited nothing from the stage
        before it. Checking only the two job bodies I happened to fix would leave
        the next script with the same bug, so instead: any shared script that
        shells out to pnpm must reach scripts/setup-workspace.sh.
        """
        steps = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")

        # A script may legitimately call pnpm without bootstrapping IF it is only
        # ever reached through an entry point that already bootstrapped in the
        # same container (frontend_run -> frontend_install -> verify-*.sh). The
        # rule is therefore about entry points: whatever a CNB stage invokes
        # directly must reach the bootstrap itself.
        entry_scripts = set()
        for config in _cnb_config_files():
            document = yaml.safe_load(config.read_text(encoding="utf-8"))
            for _location, body in _iter_script_bodies(document):
                for referenced in re.findall(r"scripts/([\w./-]+\.sh)", body):
                    entry_scripts.add(f"scripts/{referenced}")
                # `bash scripts/ci-job-steps.sh run <job>` is the other entry
                # style; the job body is checked separately below.
                for job in re.findall(r"ci-job-steps\.sh run ([\w-]+)", body):
                    function = f"{job.replace('-', '_')}_run"
                    entry_scripts.add(function)

        offenders = []
        for script in sorted(entry_scripts):
            if script in {"scripts/setup-workspace.sh", "scripts/smoke.sh"}:
                continue
            path = ROOT / script
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            lines = [
                line
                for line in text.splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            if not any(re.search(r"(^|[^\w-])pnpm\s", line) for line in lines):
                continue
            # setup-workspace.sh is the bootstrap itself; a script that names it
            # is delegating correctly.
            if "setup-workspace.sh" in text:
                continue
            offenders.append(script)
        self.assertEqual(
            offenders,
            [],
            "scheduled entry points run pnpm but never bootstrap pnpm:\n"
            + "\n".join(offenders),
        )

        # Same rule for the ci-job-steps entry points, following the call chain.
        def function_bodies(text: str) -> dict[str, str]:
            bodies: dict[str, str] = {}
            for match in re.finditer(r"^(\w+)\(\) \{\n", text, re.M):
                start = match.end()
                end = text.index("\n}\n", start)
                bodies[match.group(1)] = text[start:end]
            return bodies

        bodies = function_bodies(steps)

        def reaches_bootstrap(name: str, seen: frozenset[str] = frozenset()) -> bool:
            if name in seen or name not in bodies:
                return False
            body = bodies[name]
            if "setup-workspace.sh" in body:
                return True
            return any(
                reaches_bootstrap(callee, seen | {name})
                for callee in re.findall(r"^\s*(\w+)\s*$", body, re.M)
            )

        for name, body in bodies.items():
            if not name.endswith("_run"):
                continue
            if not any(
                re.search(r"(^|[^\w-])pnpm\s", line)
                for line in body.splitlines()
                if not line.lstrip().startswith("#")
            ):
                # The body may delegate to a helper that uses pnpm; check those
                # by resolving the whole chain for pnpm usage.
                chain_uses_pnpm = any(
                    re.search(r"(^|[^\w-])pnpm\s", bodies.get(callee, ""))
                    for callee in re.findall(r"^\s*(\w+)\s*$", body, re.M)
                )
                if not chain_uses_pnpm:
                    continue
            self.assertTrue(
                reaches_bootstrap(name),
                f"{name} needs pnpm but never reaches scripts/setup-workspace.sh; "
                "it would fail with `pnpm: command not found` in its own container",
            )

        # The governance job body must bootstrap its Python tooling. The GitHub
        # mirror installs PyYAML and uv by hand; the CNB stage had no
        # equivalent and died with `ModuleNotFoundError: No module named
        # 'yaml'`. The full contract is pinned by
        # test_dependency_governance_stage_can_reach_its_python_tooling; this
        # keeps the minimal, provider-facing invariant next to the pnpm
        # bootstrap rule it shares a failure mode with.
        self.assertIn("ensure_governance_tooling", bodies["dependency_governance_step"])
        governance_tooling = bodies["ensure_governance_tooling"]
        self.assertIn("import yaml", governance_tooling)
        self.assertIn("PyYAML==", governance_tooling)
        # It must be pinned, or the two providers can resolve different linters.
        self.assertIn("GOVERNANCE_PYYAML_VERSION", steps)
        # Pinned through a SOYMUTDB_CI_* variable, not an inline literal.
        self.assertIn("SOYMUTDB_CI_GOVERNANCE_PYYAML_VERSION", steps)

        # And the stage that runs them must mount the store, or the install
        # caches into a container layer that is thrown away.
        document = yaml.safe_load(CNB_CONFIG.read_text(encoding="utf-8"))
        for branch, event, pipeline_name in (
            ("main", "pull_request", "verify"),
            ("main", "push", "verify"),
            ("$", "web_trigger_verify", "verify-manual"),
        ):
            pipelines = _cnb_pipelines(branch, event)
            pipeline = next(p for p in pipelines if p["name"] == pipeline_name)
            pipeline_volumes = " ".join(
                str(v) for v in (pipeline.get("docker", {}).get("volumes") or [])
            )
            for stage in pipeline["stages"]:
                uses_pnpm = bool(
                    re.search(r"(^|[^\w-])pnpm\s", _flatten(stage).replace("run ", " "))
                ) or "build-pages-artifact" in _flatten(stage)
                if uses_pnpm:
                    self.assertIn(
                        "pnpm-store",
                        pipeline_volumes,
                        f"{branch}/{event}/{pipeline_name}/{stage['name']}: "
                        "pnpm stage without a persistent store volume",
                    )

    def test_frontend_stage_can_reach_the_openapi_contract_gate(self) -> None:
        """The frontend gate ends with a Python-backed contract check.

        Regression for a real CNB build:

            ==> API client contract
            $ bash scripts/check-contract.sh
            >> exporting OpenAPI from backend...
            scripts/check-contract.sh: line 18:
            /workspace/apps/api/.venv/bin/python: No such file or directory
            [ERR_PNPM_RECURSIVE_RUN_FIRST_FAIL] @soymutdb/api-client@2.0.0
            check:contract: `bash scripts/check-contract.sh`

        `verify-frontend-artifacts.sh` closes with
        `pnpm --filter @soymutdb/api-client check:contract`, and that script
        exports the backend OpenAPI document from `apps/api/.venv/bin/python`.
        CNB ran the gate in `node:24.19.0`, which carries no Python, so the venv
        could neither exist nor be created. The GitHub mirror escaped the same
        failure only because `actions/setup-python` installs an interpreter.

        Every one of these is load-bearing; dropping any of them re-opens the
        failure without changing the failure message.
        """
        # 1. The gate really is a hard, non-skippable step of the frontend
        #    script, or nothing below would matter.
        gate = (ROOT / "scripts/verify-frontend-artifacts.sh").read_text(encoding="utf-8")
        self.assertIn("@soymutdb/api-client check:contract", gate)
        self.assertIn(
            "SOYMUTDB_CI_SKIP_CONTRACT",
            gate,
            "the contract gate must be the only thing an explicit skip flag bypasses",
        )

        # 2. The contract script must keep exporting the schema with the venv
        #    interpreter, so the venv is genuinely required.
        contract = (ROOT / "packages/api-client/scripts/check-contract.sh").read_text(
            encoding="utf-8"
        )
        # The contract script resolves the venv from the package root, so the
        # marker is the relative venv path, not a literal absolute one.
        self.assertIn(".venv/bin/python", contract)
        self.assertIn('API_DIR="$REPO_ROOT/apps/api"', contract)

        # 3. The frontend job body must create that venv before running the gate.
        steps = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")

        def function_bodies(text: str) -> dict[str, str]:
            bodies: dict[str, str] = {}
            for match in re.finditer(r"^(\w+)\(\) \{\n", text, re.M):
                start = match.end()
                end = text.index("\n}\n", start)
                bodies[match.group(1)] = text[start:end]
            return bodies

        bodies = function_bodies(steps)
        self.assertIn("ensure_api_venv", bodies)

        venv_body = bodies["ensure_api_venv"]
        self.assertIn("apps/api/.venv", venv_body)
        self.assertIn("-m venv", venv_body)
        # The export imports `app.main`, so both the API package and its local
        # jobs dependency must be installed, matching the API job's install.
        self.assertIn("packages/jobs-py", venv_body)
        self.assertIn("apps/api", venv_body)

        # The interpreter must be the PINNED one. The image supplies it, but
        # `command -v python3` succeeding is a weaker claim than "python3 is
        # 3.14": a rebuilt image could put 3.11 on PATH, the venv would be
        # created, and the contract gate would validate against a backend the
        # repository never declared. Assert the version check is real.
        self.assertIn("interpreter_matches_pin", bodies)
        check_body = bodies["interpreter_matches_pin"]
        self.assertIn("PYTHON_VERSION", check_body)
        self.assertIn(
            "version_info",
            check_body,
            "the interpreter must be compared against the pin, not merely found",
        )
        self.assertRegex(
            venv_body,
            r"(?m)^\s*if ! interpreter_matches_pin",
            "ensure_api_venv must reject an interpreter that misses the pin",
        )

        # frontend_run must actually call it, in the same container as the gate.
        self.assertRegex(
            bodies["frontend_run"],
            r"(?m)^\s*ensure_api_venv\s*$",
        )

        # 4. The frontend stage's environment must carry BOTH toolchains, and it
        #    must be declared where CNB can actually consume a Dockerfile.
        #
        #    This is the regression that made the first CNB build of this PR fail
        #    before a single gate ran:
        #
        #        docker pull .cnb/env/Dockerfile.frontend
        #        invalid reference format: repository name must be lowercase
        #
        #    `image:` is a registry reference. The platform's runner passes it
        #    straight to `docker pull`, so a repository path is not a valid value
        #    there, whatever it points at. A Dockerfile may only appear in
        #    `docker.build`, and `build` exists at the PIPELINE level only
        #    ("任务级仅支持 image 配置，不支持 dockerfile"). Assert both halves, or
        #    the config can pass every other check while still failing on the
        #    runner.
        frontend_dockerfiles = set()
        for config in _cnb_config_files():
            document = yaml.safe_load(config.read_text(encoding="utf-8"))
            for pipeline in _iter_pipelines(document):
                frontend_stages = [
                    stage
                    for stage in pipeline.get("stages", [])
                    if "run frontend" in str(stage.get("script", ""))
                ]
                if not frontend_stages:
                    continue

                # 4a. Never put a path in `image:`; the runner would `docker
                #     pull` it. This is the exact failure being guarded.
                for stage in frontend_stages:
                    image = str(stage.get("image", ""))
                    self.assertNotRegex(
                        image,
                        r"^[./]|Dockerfile",
                        f"{config.name}: the frontend stage sets image={image!r}; "
                        "`image:` is handed to `docker pull`, so it must be a "
                        "registry reference, not a Dockerfile path (use docker.build)",
                    )

                # 4b. The environment therefore comes from the pipeline-level
                #     `docker.build`, which must name a committed Dockerfile that
                #     carries both pinned toolchains.
                build = (pipeline.get("docker") or {}).get("build")
                self.assertIsNotNone(
                    build,
                    f"{config.name}: the frontend stage needs a dual-toolchain "
                    "image, which only a pipeline-level `docker.build` can supply",
                )
                dockerfile = build if isinstance(build, str) else build.get("dockerfile")
                self.assertTrue(
                    dockerfile,
                    f"{config.name}: docker.build names no Dockerfile",
                )
                frontend_dockerfiles.add(str(dockerfile))

        self.assertTrue(
            frontend_dockerfiles, "no CNB pipeline declares the frontend environment"
        )
        for dockerfile_path in frontend_dockerfiles:
            path = ROOT / dockerfile_path
            self.assertTrue(
                path.is_file(),
                f"{dockerfile_path} runs the frontend gate but is not committed",
            )
            # Present is not enough. `.gitignore` once had an unanchored `env/`
            # pattern that matched `.cnb/env/` at any depth, so these files
            # existed in the working tree but never in a checkout and the
            # schema-documenting test above still passed. Ask git.
            ignored = subprocess.run(
                ["git", "check-ignore", "--quiet", dockerfile_path],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(
                ignored.returncode,
                0,
                f"{dockerfile_path} is ignored by .gitignore; a CNB checkout "
                "would not have it",
            )
            docker_text = path.read_text(encoding="utf-8")
            self.assertRegex(
                docker_text,
                r"(?m)^FROM python:3\.14",
                f"{dockerfile_path} must carry Python for the OpenAPI contract gate",
            )
            # Node is installed from the official release tarball, not from a
            # `FROM node:` base: python:3.14 and node:24.19.0 sit on different
            # Debian generations, and `COPY --from` cannot carry the C library
            # the copied interpreter needs, so the reverse composition dies with
            # `GLIBC_2.38 not found`. Assert the version arrives pinned AND that
            # the download is verified, or the toolchain can be swapped under a
            # reviewed pin.
            self.assertRegex(
                docker_text,
                r"(?m)^ARG NODE_VERSION=24\.19\.0$",
                f"{dockerfile_path} must pin Node to the repository version",
            )
            self.assertIn(
                "sha256sum --check",
                docker_text,
                f"{dockerfile_path} must verify the Node tarball checksum",
            )
            self.assertNotRegex(
                docker_text,
                r"(?m)^FROM node:",
                f"{dockerfile_path} cannot be built on a node: base and also "
                "provide Python 3.14 from python: via COPY --from",
            )

    def test_no_stage_image_is_a_dockerfile_path(self) -> None:
        """A Dockerfile belongs in `docker.build`, never in `image:`.

        Regression for the failure that took down the first CNB build of the PR
        that added the frontend environment, and for the same breakage already
        present on main in the release/image pipelines:

            Runner[docker] $ docker pull .cnb/env/Dockerfile.frontend
            invalid reference format: repository name (env/Dockerfile.frontend)
            must be lowercase

            Runner[docker] $ docker pull .cnb/env/Dockerfile.build-tools
            invalid reference format: repository name (env/Dockerfile.build-tools)
            must be lowercase

        `image:` is a registry reference. The runner hands it to `docker pull`
        verbatim, so any value that names a file in the repository fails before
        a single stage script runs, on every provider and every branch. Only
        `docker.build` accepts a Dockerfile, and `build` exists at the pipeline
        level alone ("任务级仅支持 image 配置，不支持 dockerfile").

        The two earlier tests asserted that the referenced file exists, is
        tracked and carries the right toolchains. All of that held while the
        build still failed, because none of them asked whether the platform can
        consume a path in that position. This one does, for every `image:` in
        every pipeline and every stage, not just the frontend one.
        """
        offenders = []
        for config in _cnb_config_files():
            document = yaml.safe_load(config.read_text(encoding="utf-8"))
            for pipeline in _iter_pipelines(document):
                docker = pipeline.get("docker") or {}
                images = [
                    str(docker.get("image", "")),
                    *[
                        str(stage.get("image", ""))
                        for stage in pipeline.get("stages", [])
                        if isinstance(stage, dict)
                    ],
                ]
                for image in images:
                    if not image:
                        continue
                    # A registry reference is `<name>[:tag]`; it never starts
                    # with a path component and never names a Dockerfile.
                    # Anything else is a file path the runner would try to pull.
                    looks_like_path = (
                        image.startswith((".", "/"))
                        or "Dockerfile" in image
                    )
                    if looks_like_path:
                        offenders.append(
                            f"{config.name}: image={image!r} is a repository path; "
                            "`image:` is passed to `docker pull` — use "
                            "`docker.build.dockerfile` instead"
                        )
        self.assertEqual(
            offenders,
            [],
            "stage/pipeline images must be registry references, not Dockerfiles:\n"
            + "\n".join(offenders),
        )

    def test_every_cnb_stage_script_target_exists_on_disk(self) -> None:
        """No stage may reference a script that is not in the repository."""
        missing = []
        for config in _cnb_config_files():
            document = yaml.safe_load(config.read_text(encoding="utf-8"))
            for location, body in _iter_script_bodies(document):
                for referenced in re.findall(r"scripts/([\w./-]+\.(?:sh|py))", body):
                    if not (ROOT / "scripts" / referenced).is_file():
                        missing.append(f"{config.name}:{location}: scripts/{referenced}")
        self.assertEqual(missing, [], "stage bodies reference missing scripts:\n" + "\n".join(missing))

    def test_cnb_toolchain_pins_are_actually_in_sync(self) -> None:
        """Run the repository guard that keeps NODE_VERSION from desyncing.

        `.nvmrc` and `.node-version` are read by different toolchains, so they
        must both equal NODE_VERSION. They had already drifted apart while this
        test was written, which is why the assertion lives in code and not in a
        reviewer's checklist.
        """
        check = ROOT / "scripts/check-toolchain-pins.py"
        self.assertTrue(check.is_file(), "missing scripts/check-toolchain-pins.py")
        result = subprocess.run(
            ["python3", str(check)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cnb_env_helpers_referenced_by_cnb_yml_exist(self) -> None:
        """.cnb.yml must not point at files that were never committed.

        `image: .cnb/env/Dockerfile.build-tools` and the release `imports:` URL
        are both load-bearing: a missing Dockerfile fails the job, and a missing
        import URL can fail config resolution before any stage starts.
        """
        text = _cnb_text()
        self.assertTrue(
            (ROOT / ".cnb/env/Dockerfile.build-tools").is_file(),
            ".cnb.yml builds .cnb/env/Dockerfile.build-tools but it is not committed",
        )
        self.assertTrue(
            (ROOT / ".cnb/env/release.yml").is_file(),
            ".cnb.yml imports .cnb/env/release.yml but it is not committed",
        )
        # Existing in the working tree is not enough: `.gitignore` had a
        # virtualenv pattern (`env/`, no leading slash) that matched at any
        # depth, so .cnb/env/ was ignored and these files were "added" in review
        # after review without ever being committed. Ask git, not the filesystem.
        untracked = []
        for relative in (".cnb/env/Dockerfile.build-tools", ".cnb/env/release.yml"):
            check = subprocess.run(
                ["git", "check-ignore", "--quiet", relative],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            if check.returncode == 0:
                untracked.append(f"{relative}: ignored by .gitignore")
                continue
            staged = subprocess.run(
                ["git", "ls-files", "--cached", "--error-unmatch", relative],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            if staged.returncode != 0:
                untracked.append(f"{relative}: present but not tracked by git")
        self.assertEqual(
            untracked,
            [],
            "files .cnb.yml references must be tracked, not just present:\n"
            + "\n".join(untracked),
        )
        for referenced in re.findall(r"\.cnb/env/([\w.-]+)", text):
            self.assertTrue(
                (ROOT / ".cnb/env" / referenced).is_file(),
                f".cnb.yml references missing .cnb/env/{referenced}",
            )

    def test_ci_job_steps_only_advertises_commands_it_implements(self) -> None:
        """No documented entry point may be left undeclared.

        `emit github|cnb` used to be documented in the usage text and dispatched
        to scripts/emit-ci-pipeline.py, which was never committed. The command
        was removed; this test keeps a future usage string honest.
        """
        steps = ROOT / "scripts/ci-job-steps.sh"
        text = steps.read_text(encoding="utf-8")
        self.assertNotIn("emit-ci-pipeline.py", text)
        for documented in ("list", "run"):
            self.assertIn(documented, text, documented)

        # Anything the usage text documents must be a real case label.
        usage = re.search(r"Commands:\n(.*?)\nJobs:", text, re.S)
        self.assertIsNotNone(usage, "usage block not found")
        documented_commands = set(re.findall(r"^\s{2}(\w+)", usage.group(1), re.M))
        implemented = set(re.findall(r"^\s{4}(\w+[\w-]*)\)", text, re.M))
        self.assertLessEqual(
            documented_commands,
            implemented,
            f"documented but not implemented: {documented_commands - implemented}",
        )

    def test_every_advertised_job_actually_dispatches(self) -> None:
        """`run <job>` must resolve for every job `list` prints.

        Regression for a real CNB build. `api-tests` was advertised by `list`
        and invoked by five pipeline stages, but its body was named `api_run`,
        while the dispatcher resolves `<job with - as _>_run`. The stage died in
        1.6s with no test executed:

            $ bash scripts/ci-job-steps.sh run api-tests
            unknown job: api-tests
            Finished, code: 2

        The sibling contract only asserted the *string* `run api-tests` was
        present in the pipeline configs, so it passed the entire time. This test
        exercises the dispatcher itself. It never runs a job body, so it stays
        fast and toolchain-free: the dispatcher is asked to resolve each name
        with its own rule, then verified with `declare -F`.
        """
        steps = ROOT / "scripts/ci-job-steps.sh"
        catalog = subprocess.run(
            ["bash", str(steps), "list"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        jobs = catalog.stdout.split()
        self.assertTrue(jobs, "the job catalog is empty")

        # Resolve each advertised job exactly as `main()` does.
        resolver = "; ".join(
            f'if declare -F "{job.replace("-", "_")}_run" >/dev/null; '
            f'then echo "OK {job}"; else echo "MISSING {job}"; fi'
            for job in jobs
        )
        # `main "$@"` would execute the job instead of only defining it, so the
        # library is sourced with that single dispatch line removed.
        source_without_dispatch = 'source <(sed "s|^main \\"\\$@\\"$||" "$1")'
        resolved = subprocess.run(
            ["bash", "-c", f'{source_without_dispatch}; {resolver}', "bash", str(steps)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            resolved.returncode,
            0,
            f"dispatcher probe failed:\n{resolved.stdout}\n{resolved.stderr}",
        )

        reported = [line.split(None, 1) for line in resolved.stdout.splitlines() if line.strip()]
        self.assertEqual(
            len(reported),
            len(jobs),
            f"dispatcher probe reported {len(reported)} of {len(jobs)} jobs: {resolved.stdout}",
        )

        missing = [job for verdict, job in reported if verdict == "MISSING"]
        self.assertEqual(
            missing,
            [],
            "jobs advertised by `list` but not dispatchable by `run`: " + ", ".join(missing),
        )

    def test_smoke_profiles_cover_every_layer_and_never_fake_a_pass(self) -> None:
        smoke = (ROOT / "scripts/smoke.sh").read_text(encoding="utf-8")
        for profile in ("contracts", "static", "runtime", "e2e", "images"):
            self.assertIn(profile, smoke, profile)
        # A missing prerequisite must be reported SKIPPED, not as success.
        self.assertIn("skip_layer", smoke)
        self.assertIn("SMOKE PASS", smoke)
        self.assertIn("SMOKE FAIL", smoke)

    def test_package_scripts_expose_the_shared_entrypoints(self) -> None:
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        scripts = package["scripts"]
        self.assertEqual(scripts["smoke"], "bash scripts/smoke.sh")
        for name in ("ci:verify", "ci:api", "ci:images", "ci:release", "ci:jobs"):
            self.assertIn(name, scripts, name)
            self.assertIn("scripts/ci-job-steps.sh", scripts[name])

    def test_shared_scripts_are_executable_and_strict(self) -> None:
        # Two documented exceptions, both multi-layer reporters. They must run
        # every layer even after one fails, or the summary would hide the rest
        # of the evidence — so they use `set -uo pipefail` without `-e` and
        # decide their exit status explicitly.
        #
        #   scripts/smoke.sh       prints SMOKE PASS / SMOKE FAIL
        #   scripts/acceptance.sh  prints ACCEPTANCE PASS / ACCEPTANCE FAIL
        non_exiting = {
            "scripts/smoke.sh": "SMOKE FAIL",
            "scripts/acceptance.sh": "ACCEPTANCE FAIL",
        }
        for script in SHARED_SCRIPTS:
            if script.endswith(".py"):
                continue
            text = (ROOT / script).read_text(encoding="utf-8")
            if script in non_exiting:
                self.assertIn("set -uo pipefail", text, script)
                # `set -e` would abort on the first failed layer; the presence of
                # an explicit verdict is what replaces it, so assert both.
                self.assertNotIn("set -euo pipefail", text, script)
                self.assertIn(non_exiting[script], text, script)
                self.assertIn("exit 1", text, script)
            else:
                self.assertIn("set -euo pipefail", text, script)
            self.assertTrue((ROOT / script).stat().st_mode & 0o111, script)

    def test_shared_scripts_never_echo_credentials(self) -> None:
        for script in SHARED_SCRIPTS:
            text = (ROOT / script).read_text(encoding="utf-8")
            for leak in ("echo ${CNB_TOKEN", "echo $CNB_TOKEN", "set -x"):
                self.assertNotIn(leak, text, f"{script}: {leak}")

    def test_frontend_test_imports_resolve_to_real_files(self) -> None:
        """Relative imports inside test files must point at files that exist.

        The shared i18n double (apps/<app>/src/test/mocks.ts) is imported with a
        hand-written relative path in every test file that needs it. Five of six
        paths were wrong, and the failure mode is quiet: Vite reports one resolve
        error per file, and the suite summary then reports *fewer* tests rather
        than any failure, so a broken import can read as a healthy run.

          Test Files  12 failed | 35 passed (47)
          Tests       10 failed | 76 passed (86)     ← 40 of 116 never collected

        Resolving each relative import against the importing file's directory
        turns that into a build-time error the reviewer can see.
        """
        unresolved: list[str] = []
        for test_file in sorted(
            list(ROOT.glob("apps/*/src/**/*.test.ts")) + list(ROOT.glob("apps/*/src/**/*.test.tsx"))
        ):
            text = test_file.read_text(encoding="utf-8")
            for match in re.finditer(r"""(?:import|require)\s*\(\s*["']([^"']+)["']\s*\)""", text):
                specifier = match.group(1)
                if not specifier.startswith("."):
                    continue
                base = test_file.parent / specifier
                candidates = [
                    base,
                    *[base.with_suffix(suffix) for suffix in (".ts", ".tsx", ".js", ".jsx", ".json")],
                    base / "index.ts",
                    base / "index.tsx",
                ]
                if not any(candidate.is_file() for candidate in candidates):
                    unresolved.append(
                        f"{test_file.relative_to(ROOT)}: {specifier}"
                    )
        self.assertEqual([], unresolved, "test imports that do not resolve:")

    # -------------------------------------------------------------------------
    # Startup and acceptance
    # -------------------------------------------------------------------------
    # "Can I start it?" and "can I accept it?" used to be answerable only by a
    # developer with a local Docker daemon. They are now platform entry points:
    # $ -> vscode starts a development environment, and the web-trigger
    # acceptance pipeline states a verdict about a revision. Both are contracts
    # in their own right, so they are asserted here rather than left to review.

    def test_cloud_development_entry_point_prepares_the_environment(self) -> None:
        """The cloud dev button must run the shared bootstrap, not inline YAML."""
        document = _cnb()
        pipelines = document["$"]["vscode"]
        self.assertEqual(len(pipelines), 1)
        pipeline = pipelines[0]

        # `services: vscode` is what makes this the platform's development entry
        # point; without it the button falls back to the default environment and
        # the SoyMutDB bootstrap never runs.
        services = pipeline["services"]
        self.assertIn("docker", services)
        vscode_service = next(s for s in services if isinstance(s, dict) and s.get("name") == "vscode")
        options = vscode_service["options"]
        self.assertIs(options["onlyPreview"], True)
        self.assertIn("scripts/start-cloud-dev.sh", options["launch"])

        # The launch command must be reachable after a fresh checkout. `./` and
        # `bash` forms both pin the interpreter; a bare path relies on the exec
        # bit surviving the checkout.
        first_token = options["launch"].split()[0]
        self.assertIn(first_token, ("bash", "./"))

        # 8686 is fixed by only-preview mode. Passing it through the environment
        # keeps the launch command a plain script invocation and keeps the port
        # in one place.
        self.assertEqual(pipeline["env"]["SOYMUTDB_DEV_WEB_PORT"], "8686")
        self.assertIn("8686", options["launch"] + pipeline["env"]["SOYMUTDB_DEV_WEB_PORT"])

        # Every stage body is a single bash invocation (see the stage-shell
        # tests); the preparation stage runs the same script in full mode.
        self.assertEqual(
            [stage["script"] for stage in pipeline["stages"]],
            ["bash scripts/start-cloud-dev.sh full"],
        )

        # The store must be mounted, or every environment creation re-downloads
        # the whole dependency tree into a container layer.
        volumes = " ".join(str(v) for v in pipeline["docker"]["volumes"])
        self.assertIn("pnpm-store", volumes)

    def test_no_stage_declares_volumes_and_paths_do_not_nest(self) -> None:
        """Volumes must use the CNB grammar, at the pipeline level, non-nested.

        Real CNB failure this guards -- it killed the build in Prepare, before a
        single stage ran:

            Pipeline prepare error:
              Unsupported volume type. 不支持的数据卷类型: /cache/pnpm-store

        Two distinct mistakes produced that message, and both must be caught:

          1. Declaring the store as a STAGE key. `volumes` is only understood
             under `docker:` at the pipeline level; a stage-level one is not in
             the schema:

               stages:
                 - name: Frontend verification
                   volumes:                    # <-- not in the CNB schema
                     - /cache/pnpm-store

          2. Writing the entry in Docker's `host:container` form. CNB parses
             `<path>` or `[<group>:]<path>[:<type>]`, so the second segment is a
             TYPE, not a mount target:

               docker:
                 volumes:
                   - /cache/pnpm-store:/cache/pnpm-store   # <- "type" is a path

        Prepare parses the whole document before the first stage runs, so one bad
        entry fails every pipeline that copies it. Three invariants:

          1. No stage may declare `volumes`.
          2. Every entry must be valid CNB volume grammar (see _cnb_volume_path).
          3. No declared volume path may be a prefix of, or nested inside, another
             (`/a` and `/a/b/c` are rejected -- "存在包含关系的卷路径"). In
             particular a volume under /workspace is invalid, because /workspace
             is always shared.
        """
        document = yaml.safe_load(CNB_CONFIG.read_text(encoding="utf-8"))

        # 1. No stage-level volumes anywhere in the file. Walk branch -> event ->
        #    pipeline -> stages, which is the only place a stage can appear.
        for branch, events in document.items():
            if not isinstance(events, dict):
                continue
            for event, pipelines in events.items():
                for pipeline in pipelines or []:
                    for stage in pipeline.get("stages", []) or []:
                        self.assertNotIn(
                            "volumes",
                            stage,
                            f"{branch}/{event}/{pipeline.get('name')}/"
                            f"{stage.get('name')}: stage-level `volumes` is not a "
                            "supported key and fails Prepare with `Unsupported "
                            "volume type`; move it to the pipeline's "
                            "`docker.volumes`",
                        )

        # 2. Within ONE pipeline, every declared volume must be a normalised,
        #    non-nested absolute path. The inclusion rule is per pipeline, so the
        #    same store path may legitimately appear in several pipelines.
        def declared_volumes(body: object) -> list[str]:
            """Collect `docker.volumes` at any depth (pipeline and cloud-dev)."""
            found: list[str] = []
            if isinstance(body, dict):
                docker = body.get("docker")
                if isinstance(docker, dict):
                    found.extend(str(v) for v in (docker.get("volumes") or []))
                for value in body.values():
                    found.extend(declared_volumes(value))
            elif isinstance(body, list):
                for value in body:
                    found.extend(declared_volumes(value))
            return found

        pipelines_checked = 0
        for branch, events in document.items():
            if not isinstance(events, dict):
                continue
            for event, pipelines in events.items():
                for pipeline in pipelines or []:
                    entries = declared_volumes(pipeline)
                    if not entries:
                        continue
                    pipelines_checked += 1
                    location = f"{branch}/{event}/{pipeline.get('name')}"

                    paths: list[str] = []
                    for entry in entries:
                        path = _cnb_volume_path(entry, location)
                        self.assertTrue(
                            path.startswith("/"),
                            f"{location}: volume {entry!r}: only absolute "
                            "container paths are portable",
                        )
                        self.assertFalse(
                            path.startswith("/workspace") and path != "/workspace",
                            f"{location}: volume {entry!r}: /workspace is already "
                            "shared, so a volume nested inside it is rejected "
                            "(存在包含关系的卷路径)",
                        )
                        paths.append(path.rstrip("/"))

                    for index, path in enumerate(paths):
                        for other in paths[index + 1 :]:
                            nested = (
                                path == other
                                or path.startswith(other + "/")
                                or other.startswith(path + "/")
                            )
                            self.assertFalse(
                                nested,
                                f"{location}: volume paths {path!r} and {other!r} "
                                "overlap or nest; CNB rejects volumes with an "
                                "inclusion relationship",
                            )

        self.assertGreater(
            pipelines_checked, 0, "the pnpm store volume is required for caching"
        )

    def test_cloud_development_buttons_share_one_bootstrap(self) -> None:
        """The manual preview pipeline must not fork the environment prep.

        A second entry point that reimplements the launch would be the classic
        way the two drift: the branch button and the manual button would start
        subtly different environments. Both must call the same script with the
        same mode and port.
        """
        document = _cnb()
        vscode_pipeline = document["$"]["vscode"][0]
        manual_pipeline = document["$"]["web_trigger_workspace-preview"][0]

        def launch_and_port(pipeline: dict) -> tuple[str, str]:
            service = next(
                s for s in pipeline["services"] if isinstance(s, dict) and s.get("name") == "vscode"
            )
            return service["options"]["launch"], pipeline["env"]["SOYMUTDB_DEV_WEB_PORT"]

        self.assertEqual(launch_and_port(vscode_pipeline), launch_and_port(manual_pipeline))
        self.assertEqual(
            [stage["script"] for stage in manual_pipeline["stages"]],
            [stage["script"] for stage in vscode_pipeline["stages"]],
        )

    def test_start_cloud_dev_binds_services_to_all_interfaces(self) -> None:
        """A service on localhost is unreachable from CNB's preview proxy.

        This is the single most likely "the environment started but the preview
        is blank" bug, and it is invisible locally (a local browser CAN reach
        loopback). Pin the 0.0.0.0 binding and the readiness wait that turns a
        crash-on-start into a reported failure.
        """
        script = (ROOT / "scripts/start-cloud-dev.sh").read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", script)
        self.assertIn("VITE_HOST", script)
        self.assertIn("0.0.0.0", script)
        # The preview must not be reported as started before it can be reached.
        self.assertIn("/dev/tcp/127.0.0.1/", script)
        # Missing prerequisites must be actionable, not a stack trace.
        self.assertIn("SOYMUTDB_DATABASE_URL", script)
        # It must not carry credentials or secrets of its own.
        self.assertNotIn("CNB_TOKEN", script)

    def test_acceptance_pipeline_reports_per_layer_and_uploads_evidence(self) -> None:
        document = _cnb()
        pipeline = document["$"]["web_trigger_acceptance"][0]

        scripts = [stage.get("script", "") for stage in pipeline["stages"]]
        self.assertEqual(
            scripts,
            [
                "bash scripts/acceptance.sh --profile contracts",
                "bash scripts/acceptance.sh --profile backend",
                "bash scripts/acceptance.sh --profile static",
            ],
        )

        # PostgreSQL integration is mandatory for the backend layer: the
        # privacy/identity/assembly matrix must fail closed, not skip green.
        self.assertEqual(pipeline["env"]["SOYMUTDB_RUN_POSTGRES_INTEGRATION"], "1")
        # `services` is a PIPELINE-level key, not a stage key: a stage-level
        # `services:` is silently dropped and the dind daemon never starts.
        self.assertIn("docker", pipeline["services"])
        self.assertNotIn("postgres:16", pipeline["services"])
        for stage in pipeline["stages"]:
            self.assertNotIn(
                "services",
                stage,
                "`services` is a pipeline key; on a stage it is ignored",
            )
        self.assertIn(
            "pnpm-store",
            " ".join(str(v) for v in pipeline["docker"]["volumes"]),
        )

        # Evidence is uploaded even when a layer fails, so a failed acceptance
        # still leaves the per-layer verdicts for review.
        self.assertTrue(pipeline["endStages"], "acceptance must upload evidence")
        self.assertIn("artifacts/acceptance", _flatten(pipeline["endStages"]))

        # Acceptance must never publish or hold release credentials: it runs on
        # feature branches and on Issue-driven NPC tasks.
        text = _flatten(pipeline)
        for forbidden in ("docker login", "docker push", "cosign"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_postgres_backed_stages_declare_a_real_service_and_resolve_a_database(self) -> None:
        """The PostgreSQL gate must depend on a service CNB actually starts.

        Regression for the first real CNB build of the api-tests stage
        (cnb-ubo-1k2852ukb). The stage declared:

            services:
              - postgres:16

        CNB accepted the declaration and started NOTHING. Measured in a probe
        build on the same runner (cnb-j0g-1k285hm3b):

            CLOSED postgres 5432 [Errno -2] Name or service not known
            CLOSED 127.0.0.1 5432 [Errno 111] Connection refused
            /var/run/docker.sock missing

        `services` only implements `docker` and `vscode`, so any other name is
        a silent no-op. The suite therefore fell through to Testcontainers and
        every database-backed test errored with a docker stack trace:

            docker.errors.DockerException: Error while fetching server API
            version: ('Connection aborted.', FileNotFoundError(2, ...))

        ...116 ERRORS that read as 116 product failures. The fix is a service
        the platform does start (`docker`) plus a resolver that fails closed.
        """
        forbidden = {"postgres", "postgresql", "mysql", "mariadb", "redis", "mongo"}

        database_stages: list[tuple[str, dict]] = []
        for config in _cnb_config_files():
            document = yaml.safe_load(config.read_text(encoding="utf-8"))
            for pipeline in _iter_pipelines(document):
                for stage in pipeline.get("stages", []) or []:
                    if not isinstance(stage, dict):
                        continue
                    body = _flatten(stage)
                    if "api-tests" not in body and "--profile backend" not in body:
                        continue
                    database_stages.append((config.name, pipeline))

                    # `services` is a PIPELINE-level key (docs.cnb.cool
                    # grammar.md#pipeline-services: siblings of `stages`,
                    # `docker`, `env`). Declaring it inside a Stage is silently
                    # ignored: the stage then has no dind daemon and no docker
                    # CLI, which is exactly the observed failure
                    #   [postgres-service] docker CLI is unavailable:
                    #   this stage must declare `services: [docker]`
                    # on the real build cnb-m06-1k28813m9. Assert on the
                    # pipeline, never on the stage.
                    services = pipeline.get("services") or []
                    names = {
                        entry if isinstance(entry, str) else entry.get("name")
                        for entry in services
                    }
                    self.assertNotIn(
                        forbidden,
                        names,
                        f"{config.name}: `services:` only implements docker and "
                        "vscode; a database name here is accepted and starts "
                        "nothing",
                    )
                    self.assertIn(
                        "docker",
                        names,
                        f"{config.name}: the PostgreSQL gate needs the pipeline "
                        "to declare `services: [docker]` so it can start a "
                        "database through the dind daemon",
                    )
                    # And it must NOT be misplaced on the stage: a stage-level
                    # `services` is not in the Stage schema and is dropped.
                    for stage in pipeline.get("stages", []) or []:
                        if not isinstance(stage, dict) or "stages" in stage:
                            continue
                        self.assertNotIn(
                            "services",
                            stage,
                            f"{config.name}/{stage.get('name')}: `services` "
                            "is a pipeline key; on a stage it is silently "
                            "ignored and the dind daemon never starts",
                        )

        self.assertTrue(
            database_stages,
            "no pipeline stage runs the PostgreSQL-backed gate; the privacy, "
            "identity and assembly matrix would never execute",
        )
        # The same misplaced-key hazard applies to every pipeline in the
        # repository, not just the database gate: `services` on a Stage is
        # always a no-op, so forbid it everywhere and keep the fix from
        # regressing one file at a time.
        for config in _cnb_config_files():
            document = yaml.safe_load(config.read_text(encoding="utf-8"))
            for pipeline in _iter_pipelines(document):
                for stage in pipeline.get("stages", []) or []:
                    if not isinstance(stage, dict):
                        continue
                    # A stage MAY be a whole nested pipeline (`stages:` inside
                    # the stage). That inner object is a pipeline, so its own
                    # `services:` is legal pipeline configuration -- `.cnb.yml`
                    # uses this shape for the per-architecture image builds.
                    if "stages" in stage:
                        continue
                    if "services" in stage:
                        self.fail(
                            f"{config.name}/{stage.get('name')}: `services` is "
                            "a pipeline-level key; declaring it on a stage is "
                            "silently ignored"
                        )

        # The resolver itself must stay fail-closed and driver-accurate.
        resolver = (ROOT / "scripts/with-postgres-service.sh").read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", resolver)
        # An explicit caller-provided database is honoured, so local runs and
        # the GitHub runner (where Testcontainers works) are unaffected.
        self.assertIn("SOYMUTDB_TEST_DATABASE_URL", resolver)
        marker = 'if [[ -n "${SOYMUTDB_TEST_DATABASE_URL:-}" ]]'
        self.assertIn(
            marker,
            resolver,
            "an explicitly provided database must short-circuit the bootstrap",
        )
        # Readiness must be proven with the suite's own driver: the vendor
        # image serves `pg_isready` from a temporary socket during initdb, so a
        # TCP-level check alone reports a healthy server as unusable.
        self.assertIn("asyncpg.connect", resolver)
        self.assertIn("pg_isready", resolver)
        # It must never fall back to "skip because there is no database".
        for skip in ("pytest.skip", "SKIPPED", "exit 0 #"):
            self.assertNotIn(skip, resolver, skip)

        # The gate consumes the resolver's output without `source`, because a
        # CNB stage body runs under `sh` where `source` does not exist.
        backend = (ROOT / "scripts/verify-backend-tests.sh").read_text(encoding="utf-8")
        for marker in (
            "with-postgres-service.sh",
            "--print-exports",
            "export SOYMUTDB_RUN_POSTGRES_INTEGRATION=1",
            # The worker suite reuses a fixture by package path, and a broken
            # import aborts collection for the whole run. This must stay a hard
            # step *before* the worker install so it fails fast and cheaply.
            "scripts/check_worker_test_package.py",
        ):
            self.assertIn(marker, backend, marker)
        self.assertNotIn("source \"${PG_ENV_FILE}\"", backend)

        # `--ensure` must write a POSIX `KEY=VALUE` file, not shell `export`
        # lines, for the same reason.
        self.assertNotIn("printf 'export SOYMUTDB_TEST_DATABASE_URL", resolver)

    def test_acceptance_entry_point_never_reports_a_missing_prerequisite_as_a_pass(self) -> None:
        """The acceptance/smoke difference is deliberate and must stay visible.

        scripts/smoke.sh reports `SKIPPED` for a missing prerequisite because it
        is a developer tool: it runs what is possible locally. Acceptance must
        do the opposite for a required layer — on the platform the prerequisite
        is a property of the pipeline definition, so its absence is a failure to
        fix there, not a layer to be waved through. This test pins both halves so
        neither entry point silently adopts the other's posture.
        """
        acceptance = (ROOT / "scripts/acceptance.sh").read_text(encoding="utf-8")
        self.assertIn("block_layer", acceptance)
        self.assertIn("BLOCKED", acceptance)
        self.assertIn("ACCEPTANCE PASS", acceptance)
        self.assertIn("ACCEPTANCE FAIL", acceptance)
        # A blocked layer must fail the profile.
        exit_guard = acceptance.index("ACCEPTANCE FAIL")
        self.assertIn("#BLOCKED[@]}", acceptance[:exit_guard][-400:])

        smoke = (ROOT / "scripts/smoke.sh").read_text(encoding="utf-8")
        self.assertIn("skip_layer", smoke)
        self.assertIn("SKIPPED", smoke)

        # The acceptance profiles must cover the layers the pipeline uses, and
        # the list must match the dispatched cases.
        catalog = subprocess.run(
            ["bash", "scripts/acceptance.sh", "--list"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        profiles = set(catalog.stdout.split())
        self.assertLessEqual({"contracts", "static", "runtime", "e2e", "images", "backend", "full"}, profiles)

        # `profile` names in the usage/`--list` must be dispatchable, exactly as
        # for scripts/ci-job-steps.sh: a documented profile that no `case` arm
        # handles would silently accept nothing.
        dispatch = set(re.findall(r"^\s+(\w+)\)$", acceptance, re.M))
        self.assertLessEqual({"contracts", "static", "runtime", "e2e", "images", "backend"}, dispatch)

    def test_startup_and_acceptance_are_documented_and_reachable_from_the_package(self) -> None:
        """A platform entry point nobody can find is not an entry point."""
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        scripts = package["scripts"]
        self.assertEqual(scripts["accept"], "bash scripts/acceptance.sh")
        self.assertEqual(scripts["dev:cloud"], "bash scripts/start-cloud-dev.sh")

        doc = ROOT / "docs/ops/cnb-startup-acceptance.md"
        self.assertTrue(doc.is_file(), "missing docs/ops/cnb-startup-acceptance.md")
        text = doc.read_text(encoding="utf-8")
        for marker in (
            "start-cloud-dev.sh",
            "acceptance.sh",
            ".cnb/settings.yml",
            "web_trigger_acceptance",
            "8686",
        ):
            self.assertIn(marker, text, marker)

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("cnb-startup-acceptance.md", readme)

        # The settings file that customises the launch button must be committed,
        # not merely present: `.gitignore` once swallowed .cnb/env/ the same way.
        settings = ".cnb/settings.yml"
        self.assertTrue((ROOT / settings).is_file(), settings)
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", settings], cwd=ROOT, capture_output=True
        )
        self.assertNotEqual(ignored.returncode, 0, f"{settings} is ignored by .gitignore")
        tracked = subprocess.run(
            ["git", "ls-files", "--cached", "--error-unmatch", settings],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(tracked.returncode, 0, f"{settings} is present but not tracked by git")

    def test_release_contract_is_provider_agnostic(self) -> None:
        golden = (ROOT / "scripts/release-contract.golden.sh").read_text(encoding="utf-8")
        # Registry namespace, source identity and pipeline id come from the
        # environment so the same script runs under either provider.
        self.assertIn("RELEASE_REGISTRY_OWNER", golden)
        self.assertIn("SOURCE_REPOSITORY", golden)
        self.assertIn("SOURCE_REVISION", golden)
        self.assertIn("SOURCE_PIPELINE", golden)
        self.assertIn("CNB_DOCKER_REGISTRY", golden)
        self.assertNotIn("github.repository_owner", golden)
        self.assertRegex(golden, re.compile(r"CNB_TOKEN"))


class CnbVolumeGrammarTests(unittest.TestCase):
    """The volume parser must reject what CNB refuses to prepare."""

    def test_accepts_the_supported_forms(self) -> None:
        self.assertEqual(_cnb_volume_path("/cache/pnpm-store", "loc"), "/cache/pnpm-store")
        self.assertEqual(
            _cnb_volume_path("/root/.gradle:copy-on-write", "loc"), "/root/.gradle"
        )
        self.assertEqual(_cnb_volume_path("main:/root/.gradle:rw", "loc"), "/root/.gradle")

    def test_rejects_docker_host_container_syntax(self) -> None:
        # The exact entry that failed Prepare: the second segment is a path, so
        # CNB reads the first as an unknown volume type.
        with self.assertRaises(AssertionError) as raised:
            _cnb_volume_path("/cache/pnpm-store:/cache/pnpm-store", "main/pr/verify")
        self.assertIn("host:container", str(raised.exception))

    def test_rejects_unknown_type_and_relative_path(self) -> None:
        with self.assertRaises(AssertionError):
            _cnb_volume_path("/cache/thing:bogus", "loc")
        with self.assertRaises(AssertionError):
            _cnb_volume_path("cache/pnpm-store", "loc")

    def test_rejects_malformed_segment_counts(self) -> None:
        with self.assertRaises(AssertionError):
            _cnb_volume_path("a:b:c:d", "loc")


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()
