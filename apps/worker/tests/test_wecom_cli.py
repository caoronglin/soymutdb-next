"""`WecomCli`: how an exit code and stdout become a result.

The interesting cases are the ones where the CLI is absent, unauthorized, or
speaks something other than the documented JSON. Every one of them has to land
as a `CliResult`, because the callers are notification paths that cannot raise.
"""
from __future__ import annotations

import json
import subprocess

from soymutdb_worker.wecom.cli import CliResult, WecomCli


def _fake_install(monkeypatch) -> None:
    """Pretend the CLI is installed, so run() gets as far as the subprocess."""
    monkeypatch.setattr(
        "soymutdb_worker.wecom.cli.shutil.which", lambda _name: "/usr/bin/wecom-cli"
    )


class _Completed:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _cli(monkeypatch, completed: _Completed | Exception, *, binary: str = "/bin/true") -> WecomCli:
    """A WecomCli whose subprocess.run is replaced, so nothing is executed."""
    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        if isinstance(completed, Exception):
            raise completed
        return completed

    cli = WecomCli(binary=binary)
    monkeypatch.setattr(cli, "run", cli.run)
    monkeypatch.setattr("soymutdb_worker.wecom.cli.subprocess.run", fake_run)
    monkeypatch.setattr("soymutdb_worker.wecom.cli.shutil.which", lambda _n: binary)
    return cli


class TestConfiguration:
    def test_the_default_binary_is_the_documented_name(self, monkeypatch):
        monkeypatch.delenv("WECOM_CLI_BIN", raising=False)
        monkeypatch.delenv("SOYMUTDB_WECOM_CLI_BIN", raising=False)

        assert WecomCli()._binary == "wecom-cli"

    def test_the_prefixed_env_name_is_honoured(self, monkeypatch):
        """Consistency with every other worker setting.

        Reading the environment directly here would make this the one variable
        that ignores the SOYMUTDB_ convention, and the mistake is invisible
        until a deployment quietly keeps the default.
        """
        monkeypatch.setenv("SOYMUTDB_WECOM_CLI_BIN", "/custom/wecom-cli")

        assert WecomCli()._binary == "/custom/wecom-cli"

    def test_an_explicit_argument_wins_over_the_environment(self, monkeypatch):
        monkeypatch.setenv("WECOM_CLI_BIN", "/from/env/wecom-cli")

        assert WecomCli(binary="/explicit/wecom-cli")._binary == "/explicit/wecom-cli"


class TestResolution:
    def test_a_binary_on_path_resolves(self, monkeypatch):
        _fake_install(monkeypatch)
        assert WecomCli().is_installed()

    def test_a_missing_binary_reports_not_installed(self, monkeypatch):
        monkeypatch.setattr("soymutdb_worker.wecom.cli.shutil.which", lambda _n: None)
        assert not WecomCli().is_installed()

    def test_an_explicit_path_is_used_without_a_path_lookup(self, monkeypatch):
        def unexpected(_name):
            raise AssertionError("must not consult PATH for an explicit path")

        monkeypatch.setattr("soymutdb_worker.wecom.cli.shutil.which", unexpected)
        assert WecomCli(binary="/bin/sh").resolve_binary() == "/bin/sh"

    def test_a_non_executable_explicit_path_is_rejected(self):
        """An explicit path is not a promise; it still has to be runnable.

        Otherwise a typo in WECOM_CLI_BIN surfaces as a subprocess error deep
        in a notification, rather than as an obviously-unusable channel.
        """
        assert WecomCli(binary="/etc/hostname").resolve_binary() is None

    def test_an_explicit_non_executable_path_reports_not_installed(self, monkeypatch):
        assert WecomCli(binary="/nonexistent/wecom-cli").resolve_binary() is None


class TestRun:
    def test_a_missing_cli_is_reported_without_forking(self, monkeypatch):
        monkeypatch.setattr("soymutdb_worker.wecom.cli.shutil.which", lambda _n: None)

        def unexpected(*_args, **_kwargs):
            raise AssertionError("must not fork when the CLI is absent")

        monkeypatch.setattr("soymutdb_worker.wecom.cli.subprocess.run", unexpected)

        result = WecomCli().run(["auth", "show"])

        assert result.ok is False
        assert result.error_type == "CliMissing"
        assert result.exit_code == 127

    def test_a_zero_exit_is_a_success(self, monkeypatch):
        cli = _cli(monkeypatch, _Completed(0, json.dumps({"status": "authorized"})))

        result = cli.run(["auth", "show", "--status"])

        assert result.ok is True
        assert result.payload == {"status": "authorized"}

    def test_the_real_unauthorised_envelope_is_recognised(self, monkeypatch):
        """Captured verbatim from `@wecom/cli` 1.3.4 on an unauthorised host.

        The envelope type is the shared fallback and the real cause is only in
        the message, so a `type`-only check classifies a deployment that simply
        needs `wecom-cli auth init` as an opaque backend failure.
        """
        observed = {
            "error": {
                "type": "UnknownError",
                "code": 893999,
                "message": (
                    "AuthError: 该请求需要授权，请先运行 `wecom-cli auth init` "
                    "登录 [code=893201]"
                ),
            }
        }
        cli = _cli(monkeypatch, _Completed(1, json.dumps(observed, ensure_ascii=False)))

        result = cli.run(["message", "aibot", "send"])

        assert result.ok is False
        assert result.error_type == "UnknownError"
        assert result.is_auth_failure is True

    def test_a_genuine_backend_error_is_not_mistaken_for_an_auth_problem(self, monkeypatch):
        cli = _cli(
            monkeypatch,
            _Completed(
                1,
                json.dumps(
                    {"error": {"type": "UnknownError", "code": 893999, "message": "upstream 500"}}
                ),
            ),
        )

        assert cli.run(["message", "aibot", "send"]).is_auth_failure is False

    def test_a_structured_error_is_classified(self, monkeypatch):
        cli = _cli(
            monkeypatch,
            _Completed(
                1,
                json.dumps(
                    {
                        "error": {
                            "type": "AuthError",
                            "code": 893201,
                            "message": "token expired",
                        }
                    }
                ),
            ),
        )

        result = cli.run(["message", "aibot", "send"])

        assert result.ok is False
        assert result.is_auth_failure
        assert result.error_message == "token expired"

    def test_a_usage_error_is_distinguished_from_a_backend_error(self, monkeypatch):
        """Exit 2 means the operator got the invocation wrong.

        That is a deployment bug, not a delivery failure, and the two should
        never be conflated in a log line.
        """
        usage = _cli(monkeypatch, _Completed(2, "not json"))
        assert usage.run(["nope"]).error_type == "UsageError"

        other = _cli(monkeypatch, _Completed(1, "not json"))
        assert other.run(["nope"]).error_type == "UnknownError"

    def test_a_non_json_success_is_still_a_success(self, monkeypatch):
        """Stdout is not guaranteed to be JSON for a success either."""
        cli = _cli(monkeypatch, _Completed(0, "downloaded 3 files"))

        result = cli.run(["disk", "files", "download"])

        assert result.ok is True
        assert result.payload is None

    def test_a_timeout_is_reported_as_a_timeout(self, monkeypatch):
        cli = _cli(monkeypatch, subprocess.TimeoutExpired(cmd="wecom-cli", timeout=10))

        result = cli.run(["message", "aibot", "send"])

        assert result.ok is False
        assert result.error_type == "Timeout"
        assert result.exit_code == 124

    def test_an_os_error_does_not_escape(self, monkeypatch):
        cli = _cli(monkeypatch, OSError("exec format error"))

        result = cli.run(["auth", "show"])

        assert result.ok is False
        assert result.error_type == "InvocationError"


class TestSendMarkdown:
    def _sent(self, monkeypatch) -> list[list[str]]:
        seen: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            seen.append(cmd)
            return _Completed(0, "{}")

        _fake_install(monkeypatch)
        monkeypatch.setattr("soymutdb_worker.wecom.cli.subprocess.run", fake_run)
        WecomCli().send_markdown("chat-1", "hello")
        return seen

    def test_the_message_is_sent_as_markdown_to_the_given_chat(self, monkeypatch):
        cmd = self._sent(monkeypatch)[0]

        assert cmd[1:4] == ["message", "aibot", "send"]
        assert "--chat-id" in cmd and "chat-1" in cmd
        assert "--msg-type" in cmd and "markdown" in cmd

    def test_content_travels_as_json_not_as_shell_text(self, monkeypatch):
        """Passing it as argv keeps quoting out of the picture entirely.

        A body assembled by string concatenation is where Markdown metacharacters
        turn into a shell injection; argv cannot.
        """
        cmd = self._sent(monkeypatch)[0]
        body = json.loads(cmd[cmd.index("--markdown") + 1])

        assert body == {"content": "hello"}

    def test_unicode_content_survives_the_round_trip(self, monkeypatch):
        seen: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            seen.append(cmd)
            return _Completed(0, "{}")

        _fake_install(monkeypatch)
        monkeypatch.setattr("soymutdb_worker.wecom.cli.subprocess.run", fake_run)
        WecomCli().send_markdown("chat-1", "基因数量：3；状态：ready")
        body = json.loads(seen[0][seen[0].index("--markdown") + 1])

        assert body["content"] == "基因数量：3；状态：ready"


class TestAuthorized:
    def test_an_unauthorized_cli_is_reported(self, monkeypatch):
        cli = _cli(monkeypatch, _Completed(0, json.dumps({"status": "unauthorized"})))

        assert cli.authorized() is False

    def test_an_authorized_cli_is_reported(self, monkeypatch):
        cli = _cli(monkeypatch, _Completed(0, json.dumps({"status": "authorized"})))

        assert cli.authorized() is True

    def test_a_broken_cli_is_not_authorized(self, monkeypatch):
        cli = _cli(monkeypatch, _Completed(1, json.dumps({"error": {"type": "IOError"}})))

        assert cli.authorized() is False


def test_result_defaults_are_non_raising():
    result = CliResult(ok=False, exit_code=1)

    assert result.payload is None
    assert result.error_type is None
    assert result.is_auth_failure is False
