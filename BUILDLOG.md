# Build log

## AI assistance

AI assistance was used to inspect the existing code, identify mismatches between tests and the capstone brief, propose changes, and generate drafts for migrations, Docker configuration, tests, and documentation.

## Review and ownership

Changes were reviewed against the project’s FastAPI, SQLAlchemy, Redis, ARQ, Flutterwave, and Alembic structure. The migration bootstrap supports legacy `create_all` databases, and quota semantics are explicit: `429` for exhausted usage limits and `402` for missing/inactive subscriptions.

## Known decisions

- Flutterwave sandbox is used as the regional alternative to Stripe test mode.
- Pricing remains config-driven and uses integer microcents.
- The payment provider’s webhook, not a checkout redirect, is the source of subscription truth.
