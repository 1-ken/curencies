# SQL migrations

Migrations run **automatically on backend startup** when PostgreSQL connects.

- Files: `NNN_description.sql` (applied in filename order)
- Tracking table: `schema_migrations`
- Runner: [`app/db/migrations.py`](../../app/db/migrations.py)
- Invoked from: `PostgresService.init_models()` after `create_all`

Add a new migration by creating the next numbered `.sql` file. Use idempotent SQL (`IF NOT EXISTS`, etc.) when possible.
