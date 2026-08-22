import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _service(compose: str, service_name: str) -> str:
    match = re.search(
        rf"^  {re.escape(service_name)}:\n.*?(?=^  [a-z0-9-]+:\n|^volumes:|\Z)",
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
    assert "- tunnel-backend" in origin
    assert "- cloudflare-edge" in origin
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

    api = _service(compose, "api")
    minio = _service(compose, "minio")
    assert "- tunnel-backend" in api
    assert "- tunnel-backend" in minio
    assert "tunnel-backend:" in compose


def test_tunnel_origin_allows_only_public_api_data_and_health_routes() -> None:
    config = (ROOT / "infra/nginx/cloudflare-tunnel.conf").read_text(encoding="utf-8")

    assert "listen 8081;" in config
    assert "server api:8000" in config
    assert "server minio:9000" in config
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
