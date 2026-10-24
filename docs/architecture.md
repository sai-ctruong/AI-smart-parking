# Current architecture

The frontend is a standalone React application built with Vite. The backend is an installable FastAPI package with a process health endpoint. The AI directory is a separate installable Python package with no runtime dependencies by default. There is no database schema, AI model, inference API, authentication, or parking feature in TASK-01.

Future API authorization must be enforced in the backend. Future AI work must keep dataset ground truth, generated predictions, and human review records separate, and must never use annotations as inference output. Requirements should be checked against an approved SRS before those features are designed.
