# Evidence

## Metering and idempotency

`tests/test_billing_service.py::test_record_usage_idempotency_duplicate` verifies that a retry returns `201` with the original success message and does not write another event.

## Quota boundaries

`tests/test_billing_service.py::test_record_usage_allows_request_at_quota_boundary` verifies the exact quota boundary is accepted. The over-limit billing-service tests verify a `429` response and release the temporary idempotency key.

## Cost calculations

`tests/test_pricing.py` covers zero, standard, cached-input, reasoning, mixed-volume, and negative-token pricing. `tests/test_phase4.py::test_usage_rollup_aggregation` verifies rollup conversion from microcents to USD.

## Flutterwave webhooks

`tests/test_billing_endpoints.py` verifies valid, missing-signature, and invalid-signature webhook requests. `tests/test_phase3.py::test_webhook_deduplication` verifies event deduplication.

## Latest automated run

```text
32 passed in 3.28s
```

The Compose configuration was validated with `docker compose config --quiet`; Alembic resolves to `0002_add_plans (head)`.

## Live Compose verification

`docker compose up --build --wait` completed with migration exit code `0` and healthy API/worker services. After `docker compose exec -T api python scripts/seed_demo_tenant.py`, a live POST to `/api/v1/usage` returned `201`. Replaying the same idempotency key also returned `201`; the subsequent GET `/api/v1/usage` reported exactly `1` request and `100` tokens, with the Free plan limits included in the response.
