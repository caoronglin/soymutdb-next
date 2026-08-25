# Windows no-Docker deployment

These PowerShell scripts deploy the FastAPI application directly on Windows. The API defaults to `127.0.0.1:8000`; override with `WEB_API_HOST`/`WEB_API_PORT`. The default ASGI entry is `app.main:app`; override with `WEB_APP_MODULE` only when required.

## Prerequisites

- PowerShell 5.1+ (run as Administrator for service operations), Git, Python, and PostgreSQL client tools (`pg_dump`).
- PostgreSQL may run as a local Windows service, or set `SOYMUTDB_DATABASE_URL` (or the compatibility alias `DATABASE_URL`) to a remote PostgreSQL instance. Keep credentials out of source control (use `.env` or machine environment variables).
- Preferred service wrapper: download WinSW and place `winsw.exe` beside these scripts. NSSM is accepted as a fallback and must be on `PATH`.

## Install and operate

```powershell
Set-Location C:\path\to\web
deploy\windows\install.ps1
# optional: deploy\windows\health.ps1
```

`service.ps1 -Install/-Start/-Stop/-Restart/-Uninstall` manages the service. `health.ps1` checks `/health`; change `-Url` if needed. All operational scripts support `-DryRun` to print intended actions without changing the system.

## Backups, upgrades, rollback

```powershell
deploy\windows\backup.ps1
# review/retain the generated backups\db-*.sql
deploy\windows\upgrade.ps1 -Ref v1.2.3
deploy\windows\rollback.ps1 -Ref v1.2.2
```

Upgrade/rollback stop the service, optionally checkout the Git ref, reinstall the apps/api package, run Alembic migrations, and start the service. Test in staging first. A rollback of schema changes may require a separately planned PostgreSQL restore; `backup.ps1` creates a logical dump but does not automatically restore it.

The scripts intentionally do not install Docker or modify files outside this deployment directory (apart from the virtual environment, service registration, and requested backups under the application root).
