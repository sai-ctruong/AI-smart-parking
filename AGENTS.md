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
14. After completing each task, run relevant checks. If they pass, commit and push the task to `https://github.com/sai-ctruong/AI-smart-parking.git`. Do not push when checks fail; report any access or push blocker. Do not create extra branches unless requested.
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
