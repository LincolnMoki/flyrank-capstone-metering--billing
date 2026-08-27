# FlyRank Capstone: Usage Metering & Billing

A FastAPI service that records tenant-scoped AI usage exactly once, enforces monthly call and token quotas, calculates integer microcent costs, and upgrades subscriptions through Flutterwave sandbox webhooks.

Flutterwave is used as the payment-provider alternative because Stripe is not available in the deployment region. Payment truth remains with Flutterwave; the local subscription is updated only after a verified webhook.

## Architecture

```text
Client
  │ X-API-Key + idempotency key
  ▼
FastAPI routes ──► BillingService ──► PostgreSQL (tenants, plans, subscriptions, usage events)
  │                    │
  │                    └────────────► Redis (retry/idempotency guard)
  │
  ├──► Flutterwave sandbox Checkout ──► verified webhook ──► subscription upgrade
  └──► ARQ ──► worker ──► asynchronous usage snapshot
```

## Run locally

1. Create your local environment file:

   ```bash
   cp .env.example .env
   ```

2. Set `FLW_CLIENT_ID`, `FLW_CLIENT_SECRET`, and `FLW_SECRET_HASH` when testing Flutterwave sandbox checkout/webhooks.

3. Start the complete system. This creates PostgreSQL and Redis, applies Alembic migrations, then starts the API and ARQ worker:

   ```bash
   docker compose up --build
   ```

4. In another terminal, seed the demo tenant:

   ```bash
   docker compose exec api python scripts/seed_demo_tenant.py
   ```

The API is available at `http://localhost:8000`; interactive documentation is at `/docs`.

## Demo API

The seed command creates this safe local API key:

```text
demo_api_key_000000000001
```

Record usage:

```bash
curl -X POST http://localhost:8000/api/v1/usage \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: demo_api_key_000000000001' \
  -d '{"idempotency_key":"demo-usage-001","standard_input_tokens":100}'
```

Read the current month’s usage and plan limits:

```bash
curl http://localhost:8000/api/v1/usage \
  -H 'X-API-Key: demo_api_key_000000000001'
```

Run tests:

```bash
pytest -q
```

## Behavior guarantees

- A repeated idempotency key returns the original successful result and does not record another event.
- Requests that exceed active-plan usage limits return `429`; no active subscription returns `402`.
- Money is stored and calculated as integer microcents (`100,000,000 microcents = $1`).
- Webhook IDs are unique and duplicate Flutterwave events are ignored.
- Tenant API keys scope all usage reads and writes to one tenant.

## Limitations

- Flutterwave is implemented against sandbox APIs; live credentials and live payments are deliberately out of scope.
- The webhook secret is compared against Flutterwave’s `verif-hash` header. Configure a strong secret in `.env`; do not commit it.
- The worker currently produces usage snapshots/logs rather than invoices, alerts, proration, or reconciliation reports.
- Existing databases created before Alembic are stamped at the initial revision and upgraded during startup. Back up a production database before any schema change.
