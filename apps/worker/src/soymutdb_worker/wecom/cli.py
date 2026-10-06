"""Transport to the official WeCom CLI (`@wecom/cli`).

WeCom now ships an official command-line client that owns the wire format, the
encrypted credential store and the service schema. This module is the single
place that shells out to it, so a change in the CLI's invocation is a one-file
change rather than a scattered one.

Three things this deliberately does *not* do:

- It does not check the CLI's availability or authorization before every call.
  A pre-flight check costs a process per message and races with the call
  anyway; the failure is cheaper to classify after the fact.
- It does not raise. Callers are notification paths whose contract is that an
  external chat service cannot fail an import, a job or an email send.
- It does not log the CLI's own stderr beyond the exit status. The CLI is
  configured with credentials in its own store, and its debug logs can contain
  request payloads.

The CLI's schema is fetched from the server at runtime, so the argument shapes
here are verified with ``--dry-run``, which validates a request locally and
prints it without sending.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass

from soymutdb_worker.config import get_setting

logger = logging.getLogger(__name__)

_DEFAULT_BINARY = "wecom-cli"
_DEFAULT_TIMEOUT = 10.0

#: The CLI's own error codes, per ``docs/cli-reference.md``. Auth failures are
#: the ones worth distinguishing: they mean the deployment is unconfigured,
#: which is an operator problem, not a transient delivery problem.
_AUTH_ERROR_TYPES = frozenset({"AuthError", "UnauthorizedError"})
_USAGE_EXIT_CODE = 2


@dataclass(frozen=True)
class CliResult:
    """What one CLI invocation produced.

    ``ok`` is the only field a caller needs to decide whether the message went
    out. The rest exists so an operator can tell an unconfigured deployment
    from a rejected message without re-running the command by hand.
    """

    ok: bool
    exit_code: int
    payload: dict[str, object] | None = None
    error_type: str | None = None
    error_message: str | None = None

    @property
    def is_auth_failure(self) -> bool:
        """True when the deployment lacks usable credentials."""
        return self.error_type in _AUTH_ERROR_TYPES


class WecomCli:
    """A thin, non-raising wrapper around the official CLI."""

    def __init__(
        self,
        *,
        binary: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        config_dir: str | None = None,
    ) -> None:
        # Through get_setting so the SOYMUTDB_ prefix applies, as everywhere else.
        self._binary = binary or str(get_setting("WECOM_CLI_BIN", "") or "") or _DEFAULT_BINARY
        self._timeout = timeout
        self._config_dir = config_dir

    # -- introspection -------------------------------------------------------------------

    def resolve_binary(self) -> str | None:
        """The absolute path of the CLI, or None when it is not installed.

        Checked with ``shutil.which`` rather than a subprocess so a missing CLI
        costs a stat instead of a fork.
        """
        if os.path.sep in self._binary:
            return self._binary if os.access(self._binary, os.X_OK) else None
        return shutil.which(self._binary)

    def is_installed(self) -> bool:
        return self.resolve_binary() is not None

    def authorized(self) -> bool:
        """Whether the CLI holds usable credentials.

        For diagnostics and startup checks. Do not call this per message: it is
        an extra process, and the answer can be stale the moment it returns.
        """
        result = self.run(["auth", "show", "--status"])
        return result.ok and (result.payload or {}).get("status") != "unauthorized"

    # -- invocation ---------------------------------------------------------------------

    def run(self, args: list[str]) -> CliResult:
        """Run one CLI command. Never raises."""
        binary = self.resolve_binary()
        if binary is None:
            return CliResult(
                ok=False,
                exit_code=127,
                error_type="CliMissing",
                error_message=f"{self._binary} is not installed or not on PATH",
            )

        env = dict(os.environ)
        if self._config_dir:
            env["WECOM_CLI_CONFIG_DIR"] = self._config_dir

        try:
            completed = subprocess.run(  # noqa: S603 - fixed binary, no shell
                [binary, *args],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("wecom.cli: %s timed out", " ".join(args[:2]))
            return CliResult(
                ok=False, exit_code=124, error_type="Timeout", error_message="CLI timed out"
            )
        except OSError as exc:
            logger.warning("wecom.cli: invocation failed (%s)", type(exc).__name__)
            return CliResult(
                ok=False, exit_code=126, error_type="InvocationError", error_message=str(exc)
            )

        return self._interpret(completed.returncode, completed.stdout)

    def _interpret(self, exit_code: int, stdout: str) -> CliResult:
        """Turn an exit code and stdout into a result.

        The CLI writes compact JSON to stdout and all logging to stderr, so
        stdout is the contract. A success may still be a non-JSON payload, and
        a failure may be non-JSON too, so both paths are guarded.
        """
        body = _parse_json(stdout)

        if exit_code == 0:
            return CliResult(ok=True, exit_code=0, payload=body)

        error = (body or {}).get("error")
        if isinstance(error, dict):
            return CliResult(
                ok=False,
                exit_code=exit_code,
                payload=body,
                error_type=_as_str(error.get("type")),
                error_message=_as_str(error.get("message")),
            )

        return CliResult(
            ok=False,
            exit_code=exit_code,
            payload=body,
            error_type="UsageError" if exit_code == _USAGE_EXIT_CODE else "UnknownError",
            error_message=None,
        )

    # -- messaging ----------------------------------------------------------------------

    def send_markdown(self, chat_id: str, content: str) -> CliResult:
        """Send Markdown to a single chat or group as the configured bot."""
        return self.run(
            [
                "message",
                "aibot",
                "send",
                "--chat-id",
                chat_id,
                "--msg-type",
                "markdown",
                "--markdown",
                json.dumps({"content": content}, ensure_ascii=False),
            ]
        )

    def list_sessions(self) -> CliResult:
        """Recent conversations, newest first. Used to discover a chat id."""
        return self.run(["message", "aibot", "sessions", "list"])


def _parse_json(stdout: str) -> dict[str, object] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        return None
    return body if isinstance(body, dict) else None


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


__all__ = ["CliResult", "WecomCli"]
