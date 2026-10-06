"""WeCom (企业微信) integration — W5.

## Architecture: governance is ours, transport is the official CLI

WeCom now ships an official command-line client, and it owns everything this
package used to reimplement: the wire format, the encrypted credential store,
the service schema, and token refresh. Reimplementing those was duplicate
ownership, so `token.py` and `smartsheet.py` were retired on 2026-10-05.

What remains is what the CLI does not do and should not do:

* `policy.py` — outbound field whitelist, the separate personal-data approval,
  tenant binding, credential redaction, backoff.
* `outbox.py` — transactional outbox state machine, idempotency keys, version
  guard against out-of-order delivery, dead letters, manual replay, reconciliation.
* `cli.py` — the one place that shells out to `wecom-cli`.

`cli.py` is a boundary, not a wrapper for its own sake. It never raises, because
its callers are notification paths whose contract is that an external chat
service cannot fail an import, a job or an email send.

## What the official CLI provides

Verified on `@wecom/cli` 1.3.4 against the live binary, not from memory:

| Item | Value |
| --- | --- |
| Install | `npm install -g @wecom/cli` |
| Credentials | `wecom-cli auth init` (扫码, or `--manual` for Bot ID + Secret) |
| Credential store | `~/.config/wecom/credentials.enc`, AES-256-GCM, mode 0600 |
| Command shape | `wecom-cli <service> [resource...] <method> [--json '<JSON>']` |
| Services | `message` `mail` `doc` `sheet` `smartsheet` `smartpage` `calendar` `meeting` `todo` `disk` `contact` `chat` `media` |
| Local validation | `--dry-run` prints the request without sending; **no credentials needed** |
| Exit codes | `0` success, `1` runtime error, `2` usage error |
| Error shape | `{"error":{"type","code","message"}}` on stdout; logs go to stderr |
| Env overrides | `WECOM_CLI_CONFIG_DIR`, `WECOM_CLI_ACCESS_TOKEN`, `WECOM_CLI_LOG_LEVEL` |
| Schema | fetched from the server at runtime, so the capability set is not knowable statically |

Because the schema is server-dispatched, this package asserts *invocation shape*
(`--dry-run`), not endpoint semantics. Anything about what a given method accepts
has to be read from `wecom-cli <service> --schema` at the time it is used.

## Not implemented, and must not be reported as integrated

* inbound callback signature verification and decryption;
* document search with per-document ACL evaluation;
* an `OutboxProcessor._deliver` bound to real transport (it still raises).

The plan's acceptance criterion is explicit that without a working deployment
nothing may be described as "接入已完成".

## Deployment prerequisites

- `wecom-cli` installed on the host running the worker;
- `wecom-cli auth init` completed on that host — credentials are per-host, stored
  under `~/.config/wecom`, and are **not** in the worker environment;
- `WECOM_BOT_CHAT_ID` set to the target conversation (a member userid for a
  single chat, a group conversation id for a group). Discover it with
  `wecom-cli message aibot sessions list`.

The worker does not hold WeCom credentials. It holds a chat id. This is the
main operational difference from the retired webhook path: a host with no CLI
and no auth goes silent instead of failing, which preserves the best-effort
contract the three notification call sites depend on.

## Pending confirmation

Each item below blocks a specific capability. None may be guessed.

1. **Target conversation** — the chat id to post to. Blocks every notification.
2. **Inbound callback scheme** — the encryption/signature scheme in the appendix
   (加解密方案说明). The official library download and the exact parameters were
   not retrieved; `CallbackVerifier` is unbound because a placeholder returning
   `True` would make every negative case pass vacuously.
3. **Form intake** — whether the intake surface is a 收集表 (collection form) or
   a Bitable-based form, and which answer fields map to which local model.
4. **Document search** — the CLI exposes `doc` search, but whether its results
   carry the per-document ACL evaluation W5 requires is unverified. Filtering
   after the fact is not equivalent to never seeing a title you may not read.
5. **ACL model** — whether per-document permissions can be evaluated locally or
   must be delegated to the platform on every query. This determines whether
   "no permission, no title or summary either" is enforceable here.
6. **Smartrobot size limit** — whether this tenant is under the ~10-member
   threshold the API historically enforced with `851003 no authority`.

## 凭据脱敏的覆盖边界

`policy.redact` 的匹配项是 `qyapiaccess_token`、`access_token`、`secret`、
`corpsecret`、`api[-_]?key`、`password`，取值要求 8 个字符以上。

自 2026-10-05 起，本包不再自己取 token——凭据由 CLI 在 `credentials.enc` 中
管理，worker 进程里不存在 secret，因此这条边界比之前更窄也更安全。保留
`redact` 是因为 outbox 与 policy 仍会处理上游传入的、来源不明的字段值。

已知不覆盖，写在这里以免误以为它更宽：通用的 `token=`、`refresh_token=`、
`Authorization: Bearer …`。将来若有新的调用方需要它们，必须先扩展 pattern
并补测试，不能依赖现有实现兜底。

脱敏是有代价的：8 字符下限意味着 `password=x` 这样的短值不会被改写。取值
下限是为了让 `key=1` 这类普通日志内容保持可读。
"""
