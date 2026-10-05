"""WeCom (企业微信) integration — W5.

## What is implemented, and what is deliberately not

Implemented, because none of it depends on a tenant we have not been given:

* `policy.py` — outbound field whitelist, the separate personal-data approval,
  tenant binding, credential redaction, backoff.
* `outbox.py` — transactional outbox state machine, idempotency keys, version
  guard against out-of-order delivery, dead letters, manual replay, reconciliation.
* `smartsheet.py` — the Smartsheet wire format, confirmed against the official
  documentation.
* `token.py` — access_token caching with single-flight refresh.

Not implemented, and must not be reported as integrated:

* any outbound call to a WeCom or Tencent Docs endpoint;
* inbound callback signature verification and decryption;
* document search.

`contracts.py` defines the transport protocols for all of these. Calling one
raises `IntegrationUnverified`. The plan's acceptance criterion is explicit that
without credentials nothing may be described as "接入已完成", and this package
is built so that the gap is visible in code rather than only in a document.

## Official contract already confirmed

From https://developer.work.weixin.qq.com/document/path/90664 and the
`wedoc/smartsheet` endpoint pages it links to:

| Item | Value |
| --- | --- |
| Token endpoint | `GET /cgi-bin/gettoken?corpid=ID&corpsecret=SECRET` |
| Smartsheet records | `POST /cgi-bin/wedoc/smartsheet/add_records`, `update_records`, `get_records` |
| Smartsheet webhook | `POST /cgi-bin/wedoc/smartsheet/webhook?...` |
| Failure detection | `errcode` present and non-zero. `errmsg` is **not** a success signal |
| Cell format | field title → list of typed segments, e.g. `[{"type":"text","text":"..."}]` |
| Date format | millisecond epoch **string** |
| Link format | bare record-id array |
| Read-only fields | 创建时间 / 最后编辑时间 / 创建人 / 最后编辑人 |
| Row ceiling | 40000 per sheet |
| Rate limiting | `gettoken` must be cached; repeated calls are throttled |
| Network | trusted IP allowlist required for apps created after 2022-06-20 |
| Transport | HTTPS, JSON, UTF-8 |

## Pending confirmation

Each item below blocks a specific capability. None may be guessed.

1. **Tenant and app identity** — `corpid`, `corpsecret`, and which app is listed
   in the document's "可调用应用" list. Blocks every outbound call.
2. **Trusted IP allowlist** — the egress IPs of the deployment. Required by the
   platform; calls from an unlisted IP fail regardless of credentials.
3. **Visible range size** — the API returns `851003 no authority` when the
   document's visible range exceeds roughly ten members. Whether the target
   tenant is under that limit is unverified.
4. **Inbound callback scheme** — the encryption/signature scheme in the
   appendix (加解密方案说明). The official library download and the exact
   parameters were not retrieved; `CallbackVerifier` is unbound because a
   placeholder returning `True` would make every negative case pass vacuously.
5. **Form intake** — whether the intake surface is a 收集表 (collection form)
   or a Bitable-based form, and which answer fields map to which local model.
6. **Document search** — no official search endpoint was confirmed. The document
   tree exposes management APIs for documents and permissions, but not a search
   API with per-document ACL evaluation, which is what W5 requires.
7. **ACL model** — whether per-document permissions can be evaluated locally or
   must be delegated to the platform on every query. This determines whether
   "no permission, no title or summary either" is enforceable here.
8. **`document/path/101805`** — requested for review; the page renders via
   JavaScript and its content could not be retrieved. Not relied on by any code
   here.

## Operational requirements once bound

Credential storage is environment-only (`SOYMUTDB_WECOM_CORP_ID`,
`SOYMUTDB_WECOM_CORP_SECRET`). Inbound callback keys are injected into the
receiving service only and never share storage with the outbound webhook
credential. External calls stay off the public request path; the worker owns
them. Disabling the integration must leave the application's normal work
continuing, exactly as the existing best-effort group robot does.
