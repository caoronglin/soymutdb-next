"""Static contract checks for the documented development Compose topology."""

import re
from pathlib import Path

import yaml
from yaml.resolver import BaseResolver

from compose_loader import ComposeLoader

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "docker-compose.yml"
DEV = ROOT / "docker-compose.dev.yml"

# The data layer `scripts/start-cloud-dev.sh preview` actually starts. `services:`
# is additive in Compose, so a service outside this set keeps the production
# references it declares -- which is fine, because nothing starts it.
DEV_DATA_LAYER_SERVICES = ("postgres", "clickhouse", "redis", "redis-celery", "minio")


def _load(path: Path) -> dict:
    # One loader for every Compose document in the repository; it knows the
    # Compose-only `!reset` / `!override` tags (scripts/compose_loader.py).
    return yaml.load(path.read_text(encoding="utf-8"), Loader=ComposeLoader)


def _required_variables(value: object) -> set[str]:
    """Every `${NAME:?message}` reference inside an already-parsed value."""
    text = yaml.safe_dump(value, allow_unicode=True)
    return set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*):\?", text))


def _scalar_references(node: yaml.Node) -> set[str]:
    """`${NAME:?message}` references in one scalar.

    Compose first turns `$$` into a literal `$`, which is what keeps the
    `$$HOSTNAME` inside the worker healthchecks from reading as a variable.
    """
    if not isinstance(node, yaml.ScalarNode):
        return set()
    collapsed = node.value.replace("$$", "\0")
    return set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*):\?", collapsed))


def _demanded_variables(
    document: yaml.Node, merged_from: yaml.Node | None = None
) -> set[str]:
    """`${NAME:?message}` references a Compose interpolation pass would resolve.

    Walks the YAML *node tree*, which is the order Compose interpolates in:
    every key node and value node, plus the default branch of a YAML **mapping
    merge** (`<<: *anchor`). That branch is walked even though the local keys
    shadow it, and that is the whole reason this guard exists -- reading the
    parsed mapping instead would show only the winning literal:

        x-app-env:
          <<: *dev-app-env                  # walked, and evaluated
          SOYMUTDB_S3_ACCESS_KEY: literal   # ...in spite of winning

    `merged_from` is the base file's node for the same top-level key when the
    overlay replaced it. Compose appends that mapping as an implicit default of
    the merge, so its references are still demanded; `!reset` is exactly the
    fixture that suppresses this (the tag makes the node "not a mapping merge",
    so there is no default branch to walk).
    """
    demanded: set[str] = set()

    def walk(node: yaml.Node) -> None:
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                demanded.update(_scalar_references(key))
                walk(value)
            return
        if isinstance(node, yaml.SequenceNode):
            for item in node.value:
                walk(item)
            return
        demanded.update(_scalar_references(node))

    walk(document)
    if merged_from is not None:
        walk(merged_from)
    return demanded


def _unresolved_demands(
    base: Path, overlay: Path, services: tuple[str, ...]
) -> set[str]:
    """`${NAME:?message}` references the development stack still resolves to nothing.

    Compose's relevant behaviour, in the order it happens:

    1. **Each file is interpolated on its own, before the merge.** A required
       reference *outside* `services:` can only be satisfied by the file that
       writes it, so it survives unless the overlay takes the key away.
    2. **`services:` entries merge; other top-level keys do not.** An overlay
       service definition is deep-merged into the base service, so replacing a
       base `${…:?…}` in the same slot works — that is why `minio: environment:`
       and the redis `command:` overrides are enough.
    3. **A YAML anchor merge does not remove the reference.** `x-app-env`
       overridden as `{<<: *dev-app-env, …}` keeps the base mapping as the merge
       key's default branch, and Compose expands that branch too, so the abort
       happens before the literal that shadows it is ever chosen. `!reset` is the
       only form that takes the requirement away: it makes the node "not a
       mapping merge", so there is no default branch left to walk.
    4. **`services:` is additive.** Only the services the overlay *declares* are
       merged; every other base service keeps its own `${…:?…}`. `services:` is
       therefore only meaningful together with the set the operator actually
       starts — `scripts/start-cloud-dev.sh` brings up
       `postgres clickhouse redis minio` explicitly, so those are the four this
       test resolves. A stack that started `--profile core` would still need the
       release image references and the monitoring secrets, which is by design.

    Residual set = demands inside the *started* services (after their merge) plus
    every non-`services:` demand of the base file the overlay does not `!reset`.
    Empty means the preview's own compose command succeeds on a shell with no
    `.env` — the property the CNB preview needs.
    """
    base_node = yaml.compose(base.read_text(encoding="utf-8"))
    overlay_node = yaml.compose(overlay.read_text(encoding="utf-8"))
    assert isinstance(base_node, yaml.MappingNode)
    assert isinstance(overlay_node, yaml.MappingNode)

    def entries(node: yaml.MappingNode) -> dict[str, tuple[yaml.Node, yaml.Node]]:
        return {key.value: (key, value) for key, value in node.value}

    def flatten(
        node: yaml.MappingNode,
    ) -> tuple[list[tuple[yaml.Node, yaml.Node]], list[yaml.Node]]:
        """Split a mapping into its merge-key defaults and its own entries.

        Compose (like YAML) resolves a merge key by walking the anchored mapping
        first and letting the local keys win, so the anchored entries have to be
        part of the flattened view -- otherwise an overlay that writes

            minio:
              environment:
                <<: *dev-minio-credentials

        looks empty, and the base service's `${MINIO_ROOT_USER:?…}` appears to
        survive a merge that actually replaces it.
        """
        defaults: list[yaml.Node] = []
        own: list[tuple[yaml.Node, yaml.Node]] = []
        for key, value in node.value:
            if key.tag == "tag:yaml.org,2002:merge":
                defaults.append(value)
                continue
            own.append((key, value))

        def absorb(default: yaml.Node) -> None:
            if isinstance(default, yaml.SequenceNode):
                for item in default.value:
                    absorb(item)
                return
            if not isinstance(default, yaml.MappingNode):
                return
            item_entries, item_defaults = flatten(default)
            names = {key.value for key, _ in own}
            own.extend(
                (key, value) for key, value in item_entries if key.value not in names
            )
            defaults.extend(item_defaults)

        for default in defaults:
            absorb(default)
        # Deduplicate: a value declared locally wins over the same name elsewhere.
        deduplicated: list[tuple[yaml.Node, yaml.Node]] = []
        names: set[str] = set()
        for key, value in own:
            if key.value in names:
                continue
            names.add(key.value)
            deduplicated.append((key, value))
        return deduplicated, defaults

    def merge(
        base_mapping: yaml.MappingNode, overlay_mapping: yaml.MappingNode
    ) -> yaml.MappingNode:
        """Compose's mapping merge: the overlay's entries win, the rest survive."""
        base_entries, _ = flatten(base_mapping)
        overlay_entries, _ = flatten(overlay_mapping)
        overlay_by_name = {key.value: (key, value) for key, value in overlay_entries}
        kept: list[tuple[yaml.Node, yaml.Node]] = []
        for key, value in base_entries:
            name = key.value
            if name in overlay_by_name:
                override_key, override_value = overlay_by_name[name]
                if override_value.tag == "!reset":
                    # `!reset` discards the base mapping for this key.
                    kept.append((override_key, override_value))
                    continue
                # The overlay key carries the tag that matters (e.g. `!reset`).
                key = override_key
                if isinstance(value, yaml.MappingNode) and isinstance(
                    override_value, yaml.MappingNode
                ):
                    value = merge(value, override_value)
                else:
                    value = override_value
            kept.append((key, value))
        for key, value in overlay_entries:
            if key.value not in {entry.value for entry, _ in base_entries}:
                kept.append((key, value))
        return yaml.MappingNode(BaseResolver.DEFAULT_MAPPING_TAG, kept)

    def child(node: yaml.MappingNode, name: str) -> yaml.MappingNode | None:
        value = entries(node).get(name, (None, None))[1]
        return value if isinstance(value, yaml.MappingNode) else None

    merged_services = child(merge(base_node, overlay_node), "services")
    assert merged_services is not None
    merged_by_name = entries(merged_services)

    residual: set[str] = set()
    for name in services:
        assert name in merged_by_name, (
            f"{name} is not a service the development overlay can start; "
            "scripts/start-cloud-dev.sh names it explicitly"
        )
        residual |= _demanded_variables(merged_by_name[name][1])

    # A base service that merged the *production* anchor keeps that merge key
    # when the overlay merges into it, and Compose expands it even though the
    # overlay's own `<<: *dev-app-env` shadows every entry in it.
    base_app_env = child(base_node, "x-app-env")
    if base_app_env is not None and not any(
        key.value == "x-app-env" and value.tag == "!reset"
        for key, value in overlay_node.value
    ):
        residual |= _demanded_variables(base_app_env)

    reset = {
        name
        for name, (_, value) in entries(overlay_node).items()
        if value.tag == "!reset"
    }
    residual |= _demanded_variables(
        yaml.MappingNode(
            BaseResolver.DEFAULT_MAPPING_TAG,
            [
                (key, value)
                for key, value in base_node.value
                if key.value != "services" and key.value not in reset
            ],
        )
    )
    return residual


def test_development_compose_is_an_overlay_for_the_production_topology() -> None:
    base = _load(BASE)
    dev = _load(DEV)

    assert "Development overlay" in DEV.read_text(encoding="utf-8")
    assert "-f docker-compose.yml -f docker-compose.dev.yml" in DEV.read_text(
        encoding="utf-8"
    )
    assert set(dev["services"]) - set(base["services"]) == {"web", "admin"}


def test_development_overlay_replaces_production_image_requirements() -> None:
    dev_services = _load(DEV)["services"]

    for service_name in (
        "api",
        "worker-default",
        "worker-blast",
        "worker-ingest",
        "worker-analyses",
        "beat",
    ):
        service = dev_services[service_name]
        assert service["image"] is None
        assert service["build"]["context"] == "."


def test_development_web_and_admin_are_standalone_node_services() -> None:
    dev_services = _load(DEV)["services"]

    for service_name, port in (("web", "5173:5173"), ("admin", "5174:5174")):
        service = dev_services[service_name]
        assert service["image"] == "node:24.19.0-alpine"
        assert service["working_dir"] == "/app"
        assert service["ports"] == [port]
        assert "pnpm install --frozen-lockfile" in service["command"]
        assert "build" not in service


def test_development_overlay_supplies_the_base_required_credentials() -> None:
    dev_services = _load(DEV)["services"]

    assert dev_services["postgres"]["environment"]["POSTGRES_PASSWORD"]
    assert dev_services["clickhouse"]["environment"]["CLICKHOUSE_PASSWORD"]
    assert dev_services["minio"]["environment"]["MINIO_ROOT_USER"]
    assert dev_services["minio"]["environment"]["MINIO_ROOT_PASSWORD"]
    for service_name in ("redis", "redis-celery"):
        assert "soymutdb_dev_password" in dev_services[service_name]["command"]
        # The base healthcheck interpolates `${REDIS_PASSWORD:?…}`, so the
        # overlay has to replace it -- a service-level `environment:` entry is
        # not visible to interpolation.
        test_command = dev_services[service_name]["healthcheck"]["test"]
        assert "REDIS_PASSWORD" not in " ".join(test_command)
        assert "soymutdb_dev_password" in " ".join(test_command)


def test_development_stack_demands_nothing_from_the_environment() -> None:
    """A `${NAME:?}` reference in the base file must be satisfied by the overlay.

    Regression for the CNB only-preview environment, build `cnb-178-1k29qb0vn`,
    where `scripts/start-cloud-dev.sh` died before creating a single container:

        error while interpolating x-app-env.SOYMUTDB_S3_ACCESS_KEY:
        required variable MINIO_ROOT_USER is missing a value: MINIO_ROOT_USER
        is required

    Compose interpolates `${…}` where it is WRITTEN, so the production base's
    `x-app-env` block turned a development overlay into a hard requirement for
    production S3 credentials. `minio: environment:` did not help, and neither
    did `x-app-env: {<<: *dev-app-env}` — the base mapping stays on the merge's
    default branch and is interpolated before the shadowing literal is chosen.
    `!reset` discards the base mapping outright, which is the only form that
    removes the requirement.

    Three facts are pinned, and all three matter:

    1. the production file alone still fails closed, so nothing was fixed by
       quietly defaulting a production secret;
    2. the development overlay demands NOTHING from the environment, so
       `docker compose -f docker-compose.yml -f docker-compose.dev.yml
       --profile core up -d …` works on a shell with no `.env`;
    3. it stays that way over a fresh checkout, without a `.env` file and
       without the variables on the command line.
    """
    base = _load(BASE)
    dev = _load(DEV)

    # 1. The production topology stays fail-closed.
    assert _required_variables(base), "the production file must require credentials"
    # The base file uses `!reset` only for the local-build override anchors, and
    # those tags sit on an x- key the production stack never merges: every
    # `${…:?…}` requirement is still present and still fires. Assert against the
    # requirements themselves rather than the presence of the tag — the previous
    # form ("no !reset anywhere in the base file") was a proxy that would have
    # failed here without any production behaviour changing.
    assert _required_variables(base) >= {
        "POSTGRES_PASSWORD",
        "CLICKHOUSE_PASSWORD",
        "REDIS_PASSWORD",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
    }
    for local_anchor in (
        "x-service-local-api",
        "x-service-local-worker",
        "x-service-local-mcp",
        "x-service-local-migrate",
        "x-service-local-migrate-clickhouse",
    ):
        assert local_anchor not in DEV.read_text(encoding="utf-8"), (
            "the development overlay must not merge the production local-build "
            "anchors: it replaces `image`/`build` per service instead"
        )

    # 2. The overlay carries no requirement of its own.
    assert not _demanded_variables(yaml.compose(DEV.read_text(encoding="utf-8"))), (
        "docker-compose.dev.yml demands variables of its own; a development "
        "stack must start from a bare shell"
    )

    # 3. After the merge the development stack still demands nothing.
    residual = _unresolved_demands(BASE, DEV, DEV_DATA_LAYER_SERVICES)
    assert not residual, (
        "the development overlay still forces the operator to export "
        f"{sorted(residual)} before `docker compose config` succeeds; "
        "`services:` entries are merged (so `minio:`/`redis:` overrides are "
        "enough) but a top-level key such as `x-app-env` is interpolated from "
        "the base file on its own unless it is tagged `!reset`"
    )

    # 4. The S3 credentials the aborted key resolves to are the dev literals.
    assert dev["x-app-env"]["SOYMUTDB_S3_ACCESS_KEY"] == "soymutdb_dev"
    assert dev["x-app-env"]["SOYMUTDB_S3_SECRET_KEY"] == "soymutdb_dev_password"
    assert "x-app-env: !reset" in DEV.read_text(encoding="utf-8"), (
        "`x-app-env` must keep discarding the base mapping: an anchor merge "
        "leaves the production `${…:?…}` references on the merge default branch"
    )


def test_development_s3_and_minio_credentials_are_one_definition() -> None:
    """The MinIO server and the apps talking to it must share one credential.

    Two independent literals (`minio: MINIO_ROOT_USER` and
    `x-dev-app-env: SOYMUTDB_S3_ACCESS_KEY`) is how a stack comes up healthy and
    then 403s on the first object read: the server and the client disagree. The
    overlay therefore defines the pair once and aliases it everywhere, and this
    test resolves the aliases (instead of grepping) so a re-introduced literal
    is caught.
    """
    dev = _load(DEV)
    minio_env = dev["services"]["minio"]["environment"]
    app_env = dev["x-dev-app-env"]
    override_env = dev["x-app-env"]

    user = minio_env["MINIO_ROOT_USER"]
    password = minio_env["MINIO_ROOT_PASSWORD"]

    assert app_env["SOYMUTDB_S3_ACCESS_KEY"] == user
    assert app_env["SOYMUTDB_S3_SECRET_KEY"] == password
    assert override_env["SOYMUTDB_S3_ACCESS_KEY"] == user
    assert override_env["SOYMUTDB_S3_SECRET_KEY"] == password

    # And the value must not be the image's well-known default, or every stack
    # that ever starts the overlay shares one public credential.
    assert user != "minioadmin"
    assert password != "minioadmin"
    assert "soymutdb_dev_password" == password
