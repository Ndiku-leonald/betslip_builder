# SlipIQ Render Free Staging

This guide prepares the `develop` branch for an internet-accessible staging deployment on Render. It does not create Render resources, select paid plans, change DNS, or deploy to `main`.

## Architecture

The committed [`render.yaml`](../render.yaml) describes four free resources:

- `slipiq-staging-web`: the existing Next.js application, deployed as a Docker Web Service.
- `slipiq-staging-api`: the existing FastAPI application, deployed as a Docker Web Service.
- `slipiq-staging-db`: a Render Free PostgreSQL database.
- `slipiq-staging-redis`: a Render Free Key Value instance using its private connection string.

The API and frontend use one instance each. No Render background worker is defined because a dedicated free worker is not available in Render's free resource list. Scheduled ingestion and scheduled live odds are disabled. This avoids duplicate schedulers and leaves ingestion under controlled admin/CLI operation.

Render's current free-tier documentation is the source of truth for plan availability and limits: [free services](https://render.com/docs/free), [Blueprint specification](https://render.com/docs/blueprint-spec), [Docker environment variables](https://render.com/docs/docker), and [automatic deploys](https://render.com/docs/deploys).

## Create the Blueprint

1. Sign in at [dashboard.render.com](https://dashboard.render.com/).
2. Connect the GitHub account that can read `Ndiku-leonald/betslip_builder`.
3. Choose **New > Blueprint** and select `Ndiku-leonald/betslip_builder`.
4. Select the `develop` branch and confirm that Render found the root `render.yaml`.
5. Review every resource before applying it. Confirm that the API, frontend, Postgres, and Key Value plans all say **Free**. Do not change a plan to paid.
6. Apply the Blueprint. This is the point where Render creates the staging resources; the repository preparation itself does not create them.

The Blueprint uses `autoDeployTrigger: checksPass`, so Render waits for GitHub checks on the linked `develop` commit before automatically deploying. The repository's existing GitHub Actions workflow is the quality gate; no deploy-hook URL or GitHub deploy secret is required.

## Enter environment variables and secrets

Render will prompt for every `sync: false` value during initial Blueprint creation. If a value is missing later, open:

**Render Dashboard -> service -> Environment -> Add Environment Variable**

Add these names to `slipiq-staging-api` only. Enter values in Render; never commit them or paste them into `render.yaml`:

### Required staging secrets

```
ADMIN_TOKEN
API_FOOTBALL_KEY
API_BASKETBALL_KEY
API_SPORTS_KEY
FOOTBALL_DATA_API_KEY
THE_ODDS_API_KEY
```

### Additional provider slots

The six reserved slots are declared in the Blueprint so there is room for approved football, basketball, or all-sports adapters. Leave a slot blank until its official API identity, authentication method, and normalizer have been reviewed. The variable names are:

```
ADDITIONAL_PROVIDER_1_NAME
ADDITIONAL_PROVIDER_1_SPORTS
ADDITIONAL_PROVIDER_1_BASE_URL
ADDITIONAL_PROVIDER_1_API_KEY
ADDITIONAL_PROVIDER_1_AUTH_HEADER
ADDITIONAL_PROVIDER_1_ADAPTER
```

The same six-name pattern exists for slots `2` through `6`. A slot with `ADAPTER=pending` is not queried. Do not add BetPawa scraping or an undocumented provider endpoint.

The database connection is wired with `fromDatabase` to `DATABASE_URL`; the Redis-compatible private connection is wired with `fromService` to `REDIS_URL`. Do not replace either reference with a copied password or URL.

## CORS, hosts, and frontend API URL

The API uses production validation with `APP_ENV=production`, explicit `TRUSTED_HOSTS`, and `ADMIN_TOKEN` protection. Render supplies the API hostname to `TRUSTED_HOSTS` through a self-reference to `RENDER_EXTERNAL_HOSTNAME`.

`ALLOWED_ORIGINS` is intentionally a manual environment value because the frontend hostname is not known until Render creates the service. Set it on `slipiq-staging-api` to the exact frontend origin, for example:

```
https://slipiq-staging-web.onrender.com,http://localhost:3000
```

Replace the example hostname with the actual frontend URL shown by Render. Keep the scheme, omit a trailing slash, and do not use `*`.

The frontend's `NEXT_PUBLIC_API_URL` is a non-secret Blueprint reference to the API service's `RENDER_EXTERNAL_URL`. Render passes Docker service environment variables as build arguments, so the public API URL is baked into the Next.js build without exposing backend secrets. Do not put API keys in any `NEXT_PUBLIC_*` variable.

## Migrations and first data

The API service runs `alembic -c alembic.ini upgrade head` from the image's `/app` working directory as the first part of its Render Docker startup command. Uvicorn starts only when the migration exits successfully; a migration failure stops startup. It never downgrades and does not use `create_all` as a migration substitute.

A new Postgres database is empty. Populate it through a controlled, authenticated operation from the API/CLI workflow documented in the repository. Do not seed synthetic data as real staging data, and do not make providers run on every frontend page load. Keep the existing lineage gates: real data, freshness, quality, champion-model requirements, real odds requirements, and optimizer safety checks.

Because the free staging Blueprint has no worker, run ingestion deliberately using the protected admin workflow or a controlled one-off local command against the staging API/database. Keep `APP_PROCESS_ROLE=web` and the scheduler flags disabled. Do not start multiple schedulers and do not make frontend visitors trigger ingestion.

Verify after deployment:

```
https://<api-host>/health
https://<api-host>/livez
https://<api-host>/ready
```

`/ready` must report the Postgres and required Key Value dependencies accurately. Temporary sports-provider failure should not make the whole API unready. Render's service health check uses `/health`.

## Automatic deployment

Pushes to `develop` trigger the existing GitHub Actions checks. Render is configured with `checksPass`, so it deploys only after the linked commit's checks pass. If a check fails, Render keeps the last successful staging deploy. This is the supported CI gate for this staging setup; no deploy-hook secret is stored in the repository.

For logs, open the relevant Render service and choose **Logs**. Provider keys, Authorization headers, database URLs, Redis URLs, and admin tokens must never appear in logs. If configuration validation fails, fix the missing environment variable in Render and redeploy; do not weaken the production validators.

## Free-tier limitations

Render's current free limits are staging-only constraints:

- Free Web Services spin down after 15 minutes without inbound traffic and can take about a minute to wake up. Do not add fake uptime traffic.
- Free Web Services use an ephemeral filesystem. SQLite, local JSON, local caches, and required model artifacts do not survive restarts or deploys.
- The workspace receives 750 free Web Service instance hours per calendar month; two always-running free services can exhaust that allowance before month end.
- Free Postgres is limited to 1 GB, one active free database per workspace, expires after 30 days, has no backups, and can be restarted for maintenance. After the grace period following expiry, its data is deleted.
- Free Key Value is one instance per workspace, 25 MB, in-memory only, and loses data on restart or maintenance. Its persistence mode is explicitly `off`.
- These services may restart and are not permanent production infrastructure. Before internet production, migrate to durable, backed-up paid infrastructure and add a real worker/scheduler strategy.

## Troubleshooting

- **API build fails:** verify the Docker context is the repository root and the Dockerfile is `apps/api/Dockerfile`.
- **API exits during startup:** check `DATABASE_URL`, `REDIS_URL`, `ALLOWED_ORIGINS`, `TRUSTED_HOSTS`, and `ADMIN_TOKEN`; production validation is intentionally fail-closed.
- **API health passes but readiness fails:** inspect Postgres/Key Value status and Render internal connection references, then check `/ready`.
- **Browser CORS error:** update `ALLOWED_ORIGINS` to the exact frontend `https://` origin and redeploy the API.
- **Frontend calls localhost:** confirm the frontend build contains the Blueprint-provided `NEXT_PUBLIC_API_URL`, then rebuild the frontend after changing the API service URL.
- **No fixtures:** the database starts empty and scheduled ingestion is disabled. Use the controlled ingestion workflow and inspect provider health/quota responses.
- **Slow first request:** the free web service was asleep; wait for wake-up and retry.

## Later production migration

This Blueprint is only for `develop` staging. Do not merge it into `main` as a production approval. A later production design should use a non-expiring backed-up Postgres plan, durable Redis/Key Value, separate credentials, a dedicated single scheduler/worker, provider quotas sized for the workload, monitoring, backups, and an explicit rollback plan.
