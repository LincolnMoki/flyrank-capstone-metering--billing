"""Add the plans catalog used by subscriptions.

Revision ID: 0002_add_plans
Revises: 0001_initial_schema
Create Date: 2026-08-28
"""
from alembic import op
import sqlalchemy as sa


revision = "0002_add_plans"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("tier", sa.String(length=50), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("api_call_quota", sa.Integer(), nullable=False),
        sa.Column("api_token_quota", sa.Integer(), nullable=False),
    )
    op.bulk_insert(
        sa.table(
            "plans",
            sa.column("tier", sa.String),
            sa.column("name", sa.String),
            sa.column("api_call_quota", sa.Integer),
            sa.column("api_token_quota", sa.Integer),
        ),
        [
            {
                "tier": "FREE",
                "name": "Free",
                "api_call_quota": 1_000,
                "api_token_quota": 100_000,
            },
            {
                "tier": "PRO",
                "name": "Pro",
                "api_call_quota": 10_000,
                "api_token_quota": 10_000_000,
            },
        ],
    )
    op.execute("UPDATE subscriptions SET plan_tier = UPPER(plan_tier)")
    op.create_foreign_key(
        "fk_subscriptions_plan_tier",
        "subscriptions",
        "plans",
        ["plan_tier"],
        ["tier"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_subscriptions_plan_tier", "subscriptions", type_="foreignkey")
    op.drop_table("plans")
