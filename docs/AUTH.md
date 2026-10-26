# Authentication and account setup (TASK-09)

The backend provides JSON login at `POST /api/v1/auth/login`, current identity at `GET /api/v1/auth/me`, and Admin-only account creation, listing, role/activation updates, and password resets under `/api/v1/users`. Camera and parking-spot configuration, snapshot prediction/history, and review routes use backend authorization dependencies; see `CONFIGURATION.md`, `SNAPSHOT_INFERENCE.md`, and `OPERATIONS.md` for their contracts.

Passwords use Argon2 via `pwdlib`. Access tokens are HS256 JWTs signed with `AUTH_SECRET_KEY`, expire after `ACCESS_TOKEN_MINUTES` (default 15), and contain a user ID and token version, not a role or password hash. Each protected request reloads the current user and role from the database. Disabling an account denies its existing tokens; resetting a password increments the token version and invalidates existing tokens. The `auth.login`, `user.created`, `user.updated`, `user.password_reset`, and `admin.bootstrapped` actions write actor/target IDs to `audit_logs`; no password or token is stored there.

## One-time local Admin bootstrap

1. Copy `.env.example` to the ignored root `.env` if needed, configure `DATABASE_URL`, and set a **unique** `AUTH_SECRET_KEY` with at least 32 random bytes. In PowerShell, generate a value for your private `.env` using:

   ```powershell
   $bytes = New-Object byte[] 32
   $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
   $rng.GetBytes($bytes)
   $rng.Dispose()
   [BitConverter]::ToString($bytes).Replace('-', '')
   ```

   Copy the printed value into `.env` as `AUTH_SECRET_KEY=...`. Do not commit or share that value. In production, supply both `DATABASE_URL` and `AUTH_SECRET_KEY` as process environment variables; production does not read `.env`.

2. From the repository root, install dependencies and migrate the database:

   ```powershell
   cd backend
   .\.venv\Scripts\python.exe -m pip install -e '.[dev]'
   .\.venv\Scripts\python.exe -m alembic upgrade head
   ```

3. In the same `backend/` directory, create the first account:

   ```powershell
   .\.venv\Scripts\python.exe -m app.bootstrap_admin --username admin
   ```

   Enter and confirm a password of at least 12 characters at the hidden prompt. There is no default username/password pair and no password command-line argument. The command refuses to run once any user exists. Account creation is only through an authenticated Admin after bootstrap.

4. Start the backend and sign in:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
   ```

   Send JSON `{"username":"admin","password":"<entered password>"}` to `POST /api/v1/auth/login`; pass the returned token as `Authorization: Bearer <access_token>` on protected requests. Keep browser tokens in memory, not local storage. Replace the placeholder in the example with the password entered at bootstrap.

Admin account routes are `POST /api/v1/users`, `GET /api/v1/users`, `PATCH /api/v1/users/{id}` (`role` and/or `is_active`), and `POST /api/v1/users/{id}/password`. The response contains only `id`, `username`, `role`, and `is_active`. Admin cannot disable or demote the last active Admin. Operator receives 403 on these routes. Missing, invalid, expired, disabled-account, or reset-account tokens receive 401. Bad login credentials use one generic 401 response so username existence is not disclosed. Auth errors use the API error envelope and a request ID. The existing `/health` response shape is unchanged.

Run authentication tests on fresh disposable SQLite databases from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_auth.py -q
```

Before public deployment, add a login rate limit, secret rotation procedure, HTTPS termination, and secure token handling in the frontend. These deployment controls are not provided by the current development skeleton.
