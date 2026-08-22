#!/usr/bin/env bash
# Sourced by backup/restore scripts; keeps credentials out of mc command argv.

declare -ag MC_ENV_NAMES=()

mc_configure_alias_env() {
    local alias_name="$1" endpoint="$2" access_key="$3" secret_key="$4"
    local variable_name value existing
    [[ "${alias_name}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || return 1
    [[ -n "${endpoint}" && -n "${access_key}" && -n "${secret_key}" ]] || return 1
    variable_name="MC_HOST_${alias_name}"
    value="$(
        MC_ENDPOINT="${endpoint}" MC_ACCESS_KEY="${access_key}" MC_SECRET_KEY="${secret_key}" \
            python3 - <<'PY'
import os
from urllib.parse import quote, urlsplit, urlunsplit

parsed = urlsplit(os.environ["MC_ENDPOINT"])
if parsed.scheme not in {"http", "https"} or not parsed.hostname:
    raise SystemExit("invalid S3 endpoint")
if parsed.username is not None or parsed.password is not None:
    raise SystemExit("S3 endpoint must not embed credentials")
host = parsed.hostname
if ":" in host:
    host = f"[{host}]"
if parsed.port is not None:
    host = f"{host}:{parsed.port}"
credentials = (
    f"{quote(os.environ['MC_ACCESS_KEY'], safe='')}:"
    f"{quote(os.environ['MC_SECRET_KEY'], safe='')}"
)
print(urlunsplit((parsed.scheme, f"{credentials}@{host}", parsed.path, "", "")))
PY
    )" || return 1
    printf -v "${variable_name}" '%s' "${value}"
    export "${variable_name?}"
    for existing in "${MC_ENV_NAMES[@]}"; do
        [[ "${existing}" == "${variable_name}" ]] && return 0
    done
    MC_ENV_NAMES+=("${variable_name}")
}
