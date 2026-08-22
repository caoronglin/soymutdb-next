#!/bin/sh
set -eu

webhook_file="${ALERTMANAGER_WEBHOOK_URL_FILE:-/run/secrets/alertmanager_webhook_url}"
config_file="${ALERTMANAGER_CONFIG_FILE:-/etc/alertmanager/alertmanager.yml}"
amtool_bin="${AMTOOL_BIN:-/bin/amtool}"
alertmanager_bin="${ALERTMANAGER_BIN:-/bin/alertmanager}"

fail() {
    printf '%s\n' "alertmanager startup validation failed: $*" >&2
    exit 1
}

[ -s "${webhook_file}" ] || fail "receiver URL secret is missing or empty"
[ -f "${config_file}" ] || fail "configuration file is missing"

line_count="$(awk 'NF { count++ } END { print count+0 }' "${webhook_file}")"
[ "${line_count}" -eq 1 ] || fail "receiver URL secret must contain exactly one non-empty line"
webhook_url="$(tr -d '\r\n' < "${webhook_file}")"
case "${webhook_url}" in
    https://*) ;;
    *) fail "receiver URL must use HTTPS" ;;
esac

"${amtool_bin}" check-config "${config_file}" >/dev/null \
    || fail "Alertmanager configuration is invalid"

exec "${alertmanager_bin}" "$@"
