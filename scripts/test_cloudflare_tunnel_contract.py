import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _service(compose: str, service_name: str) -> str:
    """Extract one top-level service block from the Compose document.

    The terminator is another *top-level* key: a sibling service (`  api:`) or
    one of the document sections (`volumes:`, `networks:`, `secrets:`). A
    service's own nested keys are indented four spaces, so they never match.
    """
    match = re.search(
        rf"^  {re.escape(service_name)}:\n.*?(?=^  [a-z0-9-]+:\n|^(?:volumes|networks|secrets):|\Z)",
        compose,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing compose service: {service_name}"
    return match.group(0)


def test_cloudflare_tunnel_is_opt_in_and_uses_a_private_origin() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    origin = _service(compose, "tunnel-origin")
    assert 'profiles:\n      - "cloudflare-tunnel"' in origin
    assert 'image: nginx:1.27-alpine' in origin
    assert 'expose:\n      - "8081"' in origin
    assert "ports:" not in origin
    assert "- default" not in origin
    assert "./infra/nginx/cloudflare-tunnel.conf:/etc/nginx/nginx.conf:ro" in origin
    assert "read_only: true" in origin
    assert "no-new-privileges:true" in origin

    connector = _service(compose, "cloudflared")
    assert 'profiles:\n      - "cloudflare-tunnel"' in connector
    assert "cloudflare/cloudflared:2025.2.1" in connector
    assert "tunnel-origin:" in connector
    assert "condition: service_healthy" in connector
    assert "--no-autoupdate" in connector
    assert "--token-file" in connector
    assert "/run/secrets/cloudflare_tunnel_token" in connector
    assert "cloudflare_tunnel_token" in connector
    assert "ports:" not in connector
    assert 'expose:\n      - "2000"' in connector
    assert "read_only: true" in connector
    assert "cap_drop:" in connector
    assert "no-new-privileges:true" in connector

    # The Tunnel origin must only reach api and minio, and it must reach them
    # on dedicated networks -- the origin has no attachment to `default`, so a
    # service that joins only `tunnel-backend` is unreachable from it.
    #
    # Regression: api used to share `tunnel-backend` with minio, and these
    # assertions pinned that topology (`"- tunnel-backend" in api`). The
    # deployment then split the network in two -- api on `tunnel-api`, minio on
    # `tunnel-backend` -- so a compromised origin component cannot pivot between
    # them, and `infra/nginx/cloudflare-tunnel.conf` was updated to the new
    # aliases. Only the assertions were left behind, so this contract suite
    # failed on a *correct* deployment. Assert the reachability contract the
    # origin actually depends on instead of the network names, so the next
    # topology change cannot silently strand the origin.
    api = _service(compose, "api")
    minio = _service(compose, "minio")

    def _networks(block: str) -> set[str]:
        """Network names a service block attaches to, in either YAML form.

        `- name` (list) and `name:` (mapping with aliases) are both valid
        Compose, and the file uses the mapping form for the two services whose
        alias matters.
        """
        section = re.search(r"^    networks:\n(?P<body>(?:^ {4,}.*\n?)*)", block, re.M)
        assert section is not None, block[:200]
        return set(re.findall(r"^\s+(?:-\s+)?([a-z0-9][a-z0-9-]*):?\s*$", section.group("body"), re.M))

    api_networks = _networks(api)
    minio_networks = _networks(minio)
    origin_networks = _networks(origin)

    # api and minio must NOT share a tunnel network: the split exists so a
    # compromised origin component cannot pivot between them.
    assert "tunnel-api" in api_networks
    assert "tunnel-backend" not in api_networks
    assert "tunnel-backend" in minio_networks
    assert {"tunnel-api", "tunnel-backend"} <= origin_networks
    assert "cloudflare-edge" in origin_networks
    assert "tunnel-api:" in compose
    assert "tunnel-backend:" in compose

    # Each upstream resolves an alias as a Docker network alias, not a container
    # name, so the origin never depends on the Compose service name.
    origin_config = (
        ROOT / "infra/nginx/cloudflare-tunnel.conf"
    ).read_text(encoding="utf-8")
    for alias in ("api-tunnel", "minio-tunnel"):
        assert alias in origin_config, alias
        assert f'"{alias}"' in api or f'"{alias}"' in minio, alias


def test_tunnel_origin_allows_only_public_api_data_and_health_routes() -> None:
    config = (ROOT / "infra/nginx/cloudflare-tunnel.conf").read_text(encoding="utf-8")

    assert "listen 8081;" in config
    # The upstreams target the network aliases the Compose file declares; the
    # bare service names no longer resolve on the split tunnel networks.
    assert "server api-tunnel:8000" in config
    assert "server minio-tunnel:9000" in config
    assert "location = /health" in config
    assert "location = /api/v1/admin" in config
    assert "location ^~ /api/v1/admin/" in config
    assert "location ^~ /api/" in config
    assert "location ^~ /data/" in config
    assert "location ^~ /jbrowse-data/" in config
    assert "location / {" in config
    assert "return 404;" in config
    assert "location ^~ /admin/" not in config
    assert "web_frontend" not in config
    assert "admin_app" not in config
    assert "jbrowse_app" not in config
    public_api_location = re.search(r"^        location \^~ /api/ \{", config, re.MULTILINE)
    assert public_api_location is not None
    assert config.index("location ^~ /api/v1/admin/") < public_api_location.start()
    exact_admin_location = re.search(
        r"location = /api/v1/admin \{(?P<body>.*?)\n        \}",
        config,
        flags=re.DOTALL,
    )
    assert exact_admin_location is not None
    assert "return 404;" in exact_admin_location.group("body")
    admin_location = re.search(
        r"location \^~ /api/v1/admin/ \{(?P<body>.*?)\n        \}",
        config,
        flags=re.DOTALL,
    )
    assert admin_location is not None
    assert "return 404;" in admin_location.group("body")


def test_tunnel_token_is_supplied_by_a_secret_file_not_plaintext_env() -> None:
    env_example = (ROOT / "deploy/.env.example").read_text(encoding="utf-8")

    assert "CLOUDFLARE_TUNNEL_TOKEN_FILE=" in env_example
    assert "CLOUDFLARE_TUNNEL_TOKEN=" not in env_example
    assert ".env" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_tunnel_healthcheck_is_an_explicit_https_end_to_end_probe() -> None:
    script = (ROOT / "deploy/scripts/verify-cloudflare-tunnel.sh").read_text(
        encoding="utf-8"
    )

    assert "CLOUDFLARE_TUNNEL_HEALTH_URL" in script
    assert "CLOUDFLARE_TUNNEL_BASE_URL" in script
    assert "https://" in script
    assert "curl --fail" in script
    assert "Verify forbidden public paths" in script
    assert '"/api/v1/admin"' in script
    assert '"/api/v1/admin/users"' in script
    assert '"/minio/"' in script
    assert '"/metrics"' in script
    assert '"/mcp"' in script
    assert '"/__tunnel-negative-probe__"' in script
    assert "expected HTTP 404" in script
