# Release checklist

- [ ] CI green on the exact commit and reviewed PR flow is ready
- [ ] Security/dependency/secret scans reviewed
- [ ] PostgreSQL backup confirmed and migrations upgrade-tested
- [ ] Production environment passes config validation
- [ ] Redis reachable and required semantics enabled
- [ ] Explicit origins and trusted hosts configured
- [ ] Admin token supplied out-of-band; no secrets in frontend
- [ ] Exactly one scheduler worker role configured
- [ ] Provider quotas, timeout, retry, and circuit settings reviewed
- [ ] `/health`, `/ready`, `/livez`, metrics, and deployment smoke checks pass
- [ ] Stage Two–Five synthetic/regression suites pass
- [ ] API and frontend images build as non-root runtime images
- [ ] Rollback/application-forward-fix plan reviewed
- [ ] Public deployment authorization and provider credentials confirmed
