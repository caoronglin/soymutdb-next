# Public and account-owned BLAST

The two web entry points share the existing BLAST database catalog, transactional outbox, Celery task, parser and object store:

- `/search/blast`: anonymous search with a task-specific, expiring credential.
- `/blast`: account-owned researcher jobs and personal history.

The current worker executes DIAMOND `blastp` against a protein index. Configure and validate that existing worker/index deployment before advertising anonymous searches. This access-mode change does not install NCBI BLAST+ or create indexes.

## API

| Method | Endpoint | Authorization |
|---|---|---|
| GET | `/api/v1/blast/databases` | Published release databases only |
| POST | `/api/v1/blast/public/jobs` | No account session; dedicated peer quota |
| GET | `/api/v1/blast/public/jobs/{job_id}` | `X-Blast-Token` for that job |
| GET | `/api/v1/blast/public/jobs/{job_id}/results?limit=50&offset=0` | Same header; maximum page size 200 |
| POST | `/api/v1/blast/jobs` | Existing researcher capability |
| GET | `/api/v1/blast/jobs` | Existing account history authorization |
| GET | `/api/v1/blast/jobs/{job_id}` and `/results` | Existing owner/administrator policy |

The anonymous POST accepts the same validated `BlastSubmitRequest` payload. It returns `{job, access_token, expires_at}`. The browser keeps the credential in memory; reloading or leaving the page loses access. There is no public history or credential recovery. Never place the credential in URLs, analytics, logs or persistent browser storage. Anonymous credentials cannot authenticate an account or read account-owned jobs. Existing ownerless rows are not implicitly public; new anonymous jobs carry an explicit internal marker which never reaches worker CLI parameters.

Responses use `Cache-Control: private, no-store`. Public responses vary on `X-Blast-Token`, including validation and authorization errors. CORS allows the credential and release headers only from configured origins. Reverse proxies must preserve these headers and must not log credential headers or response bodies.

## Configuration

| Environment variable | Default | Purpose |
|---|---|---|
| `SOYMUTDB_BLAST_PUBLIC_ENABLED` | `true` | Set `false` to disable all anonymous job endpoints with 404 |
| `SOYMUTDB_BLAST_PUBLIC_MAX_LENGTH` | `10000` | Maximum query payload characters, including FASTA headers |
| `SOYMUTDB_BLAST_PUBLIC_TOKEN_TTL_SECONDS` | `86400` | Credential/job lifetime; maximum 24 hours |
| `SOYMUTDB_BLAST_PUBLIC_RATE_LIMIT_MAX` | `5` | Accepted submission attempts per peer/window |
| `SOYMUTDB_BLAST_PUBLIC_RATE_LIMIT_WINDOW` | `3600` | Fixed quota window in seconds |

The dedicated limiter reuses the existing atomic Redis fixed-window implementation. Production and staging fail closed with 503 when Redis cannot verify the budget. Only development uses the existing process-local fallback. The trusted peer resolver ignores forwarding headers from untrusted proxies; configure `SOYMUTDB_ANALYTICS_TRUSTED_PROXY_IPS` to match the actual proxy chain. Networks behind NAT share the peer budget. Keep existing global inbound limits and worker CPU, memory, execution-time and output-size caps enabled.

Searchable databases remain restricted to the resolved published release. Explicit draft-release pins are rejected. Raw-download presign lifetime is capped by the job expiry, credential expiry and one hour. Expired jobs return an expired envelope without hits or a new download link. Previously issued storage URLs remain bearer capabilities until their presigned expiry.

## Deployment and rollback

No schema migration is required: nullable `user_id`, JSON job parameters and expiry already exist. Deploy the API before the web client. Keep the existing DIAMOND worker/index configuration. A rollback can disable public endpoints first; account-owned endpoints and jobs remain usable. Retention and cleanup continue through the existing BLAST job cleanup workflow.

Before production enablement, verify Redis connectivity, trusted proxy configuration, a published protein database, an actual worker/index search, result upload and presigned download reachability. Local API/transport tests prove authorization and dispatch contracts; they are not evidence that a production worker or dataset is ready.
