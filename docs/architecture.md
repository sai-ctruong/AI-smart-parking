# Current architecture

The frontend is a standalone React application built with Vite. The backend is an installable FastAPI package. Local PostgreSQL 16 is defined in Docker Compose and bound to the loopback interface. The backend uses environment settings, a lazy SQLAlchemy engine, scoped sessions, and Alembic migration history. `/health` checks process liveness; `/health?check_db=true` runs `SELECT 1` for database readiness. The AI directory is a separate installable Python package with no runtime dependencies by default. There is no parking database schema, AI model, inference API, authentication, or parking feature yet.

Development settings can load the ignored root `.env`; production settings read process environment variables only. CORS uses an explicit origin allowlist. The database container and API start independently, and the named PostgreSQL volume is persistent.

Future API authorization must be enforced in the backend. Future AI work must keep dataset ground truth, generated predictions, and human review records separate, and must never use annotations as inference output. Requirements should be checked against an approved SRS before those features are designed.
