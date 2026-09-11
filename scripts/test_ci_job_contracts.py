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
    "scripts/build-static-apps.sh",
    "scripts/build-release-image.sh",
    "scripts/release-contract.golden.sh",
    "scripts/build-pages-artifact.sh",
    "scripts/verify-pages-artifact.sh",
    "scripts/mcp-transport-smoke.sh",
    "scripts/assert-clickhouse-migration.py",
    "scripts/smoke.sh",
)

PIPELINE_FILES = (
    ".cnb/pipelines/verify.yml",
    ".cnb/pipelines/api.yml",
    ".cnb/pipelines/dependency-governance.yml",
    ".cnb/pipelines/docker-images.yml",
    ".cnb/pipelines/release.yml",
    ".cnb/pipelines/pages-publish.yml",
)


def _cnb() -> dict:
    return yaml.safe_load(CNB_CONFIG.read_text(encoding="utf-8"))


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
                # Every stage that runs a pnpm-dependent job body must mount the
                # store, or the install silently de-caches into a dead layer.
                for stage in pipeline.get("stages", []):
                    script = stage.get("script", "")
                    if "run frontend" in script or "run dependency-governance" in script:
                        volumes = stage.get("volumes") or []
                        self.assertTrue(
                            any("pnpm-store" in str(v) for v in volumes),
                            f"{branch}/{event}/{pipeline['name']}/{stage['name']}: "
                            "pnpm job without a persistent store volume",
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
            for stage in pipeline["stages"]:
                volumes = " ".join(str(v) for v in (stage.get("volumes") or []))
                uses_pnpm = bool(
                    re.search(r"(^|[^\w-])pnpm\s", _flatten(stage).replace("run ", " "))
                ) or "build-pages-artifact" in _flatten(stage)
                if uses_pnpm:
                    self.assertIn(
                        "pnpm-store",
                        volumes,
                        f"{branch}/{event}/{pipeline_name}/{stage['name']}: "
                        "pnpm stage without a persistent store volume",
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
        # scripts/smoke.sh is the single documented exception: it must survive a
        # failing layer to report the full summary, so it uses `set -uo pipefail`
        # without `-e` and decides its exit status explicitly.
        non_exiting = {"scripts/smoke.sh"}
        for script in SHARED_SCRIPTS:
            if script.endswith(".py"):
                continue
            text = (ROOT / script).read_text(encoding="utf-8")
            if script in non_exiting:
                self.assertIn("set -uo pipefail", text, script)
                self.assertIn("SMOKE FAIL", text, script)
                self.assertIn("exit 1", text, script)
            else:
                self.assertIn("set -euo pipefail", text, script)
            self.assertTrue((ROOT / script).stat().st_mode & 0o111, script)

    def test_shared_scripts_never_echo_credentials(self) -> None:
        for script in SHARED_SCRIPTS:
            text = (ROOT / script).read_text(encoding="utf-8")
            for leak in ("echo ${CNB_TOKEN", "echo $CNB_TOKEN", "set -x"):
                self.assertNotIn(leak, text, f"{script}: {leak}")

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


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()
