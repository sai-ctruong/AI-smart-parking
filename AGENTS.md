# Smart Parking Management System: Agent Rules

1. Inspect existing code, documentation, tests, and configuration before modifying files.
2. This is a solo-developed Software Engineering capstone project named Smart Parking Management System.
3. Default stack: React, Vite, TypeScript, FastAPI, PostgreSQL, SQLAlchemy, Alembic, PyTorch, and OpenCV.
4. Follow the approved SRS if available. Treat `DATT_AI_HANDOFF_2026-10-24.md` as preliminary context, not proof of approval.
5. Implement one task at a time. Preserve existing functionality.
6. Never fabricate model metrics, test results, or project progress.
7. Prevent dataset leakage. Keep ground truth, AI predictions, and human review separate.
8. Never use ground-truth annotations as inference output.
9. Enforce authorization at the backend level.
10. Never commit secrets, datasets, or large model artifacts.
11. Add appropriate tests and update documentation.
12. Run feasible checks after implementing each task.
13. Report modified files, commands run, test results, blockers, and manual verification steps.
14. After each task, run checks equivalent to `.github/workflows/checks.yml`, including relevant cross-platform regression cases. Do not push when any required check fails, when known GitHub Actions failures remain unresolved, or when the CI-equivalent checks cannot be verified; report the blocker and leave the work local. For a CI repair, reproduce the failure and verify the fix on a compatible platform before pushing. After any push, inspect the GitHub Actions result; a red run means the task is unfinished and must be fixed before starting another task. Do not create extra branches unless requested. A task that explicitly forbids commits or pushes takes precedence.
15. Prefer maintainable solutions over unnecessary complexity.

## Frontend design

- When implementing or redesigning frontend UI, use the `design-taste-frontend` skill when available.
- Prioritize visual consistency and responsive layouts.
- Preserve existing application functionality.
- Avoid unnecessary dependencies and follow the existing project architecture.

## Skill usage and verification

- Apply installed skills automatically when relevant; do not invoke irrelevant skills.
- Use `systematic-debugging` for bug fixing.
- Use `test-driven-development` for new features with testable logic.
- Use `verification-before-completion` before declaring work complete.
- Use `web-design-guidelines` for frontend UI review.
- Use `react-best-practices` for React development when the skill is installed.
- Always preserve existing functionality and run relevant tests before reporting completion.

## Dataset and release diagrams

- Use `PKLOT_DATASET_ROOT` for the local PKLot path; keep raw images, annotations, generated crops, audit overlays, and model artifacts out of Git. Never edit original PKLot files.
- Treat PKLot XML occupancy labels and contours as ground truth, not AI inference output. Keep any later predictions and human review records separate.
- At release readiness, use the project-local Archify skill in `.agents/skills/archify/` to inspect the actual repository and create source-backed architecture documentation in `docs/diagrams/`.
- Target a system architecture diagram, an AI/ML pipeline diagram, and an end-to-end workflow diagram. Include only components, connections, and steps verified in source code; omit unimplemented modules instead of implying they exist.
- Deliver standalone HTML diagrams and SVG exports when supported. Embed `docs/diagrams/architecture.svg` in the root README and link the remaining diagrams only after the files exist and their relative GitHub links have been checked.
