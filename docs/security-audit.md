# Dependency security audit

Bandit reports no high-severity Python code findings. Gitleaks is configured in CI for secret scanning. `pip-audit` and `npm audit` run in CI; their output must be reviewed before production authorization.

The current approved Next.js 15 dependency line reports an upstream PostCSS high-severity advisory and moderate Vite/esbuild advisories. The published remediation requires a Next.js 16 major upgrade and a Vitest 5 upgrade. A controlled upgrade was attempted locally but the restricted environment could not regenerate the npm lockfile; the repository therefore keeps the tested, internally consistent Next.js 15 lockfile rather than committing a mismatched dependency graph. The CI audit is intentionally non-blocking but visible and must be treated as a release blocker until the major upgrade is reviewed and tested.

The local Python environment audit also reported advisories in globally installed tooling (`cryptography`, `paramiko`, `pytest`, `setuptools`, `soupsieve`, and `tornado`) that are not direct production requirements. CI audits the repository requirements in a clean environment; any direct requirement finding must be patched or explicitly accepted before deployment.
