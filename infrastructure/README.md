# Infrastructure

`compose.yaml` defines local PostgreSQL 16 only. It requires database name, user, and password from the ignored root `.env` file and binds the host port to `127.0.0.1`. The named `postgres_data` volume persists across ordinary container restarts and `docker compose down`. Production deployment configuration is still outside this task.
