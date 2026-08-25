import uuid
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name : Mapped[str] =mapped_column(String(255), nullable=False)
    api_key: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    subscription: Mapped["Subscription"] = relationship(
        "Subscription", back_populates="tenant", uselist=False, cascade="all, delete-orphan"
    )
    usage_events: Mapped[list["UsageEvent"]] = relationship(
        "UsageEvent", back_populates="tenant", cascade="all, delete-orphan"
    )

class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    plan_tier: Mapped[str] = mapped_column(
        String(50), default="FREE", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(50), default="active", nullable=False
    )
    api_call_quota: Mapped[int] = mapped_column(
        Integer, default=1000, nullable=False
    )
    api_token_quota: Mapped[int] = mapped_column(
        Integer, default=100000, nullable=False
    )
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="subscription")

class UsageEvent(Base):
    __tablename__ = "usage_events"
    id: Mapped [uuid:UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    usage_type: Mapped[str] = mapped_column(
        String(50), default="ai_tokens", nullable=False
    )
    standard_input_tokens: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    cached_input_tokens: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    reasoning_tokens: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    cost_microcents: Mapped[int] = mapped_column(
        BigInteger, default=0, nullable=False
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="usage_events")
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_tenant_idempotency_key"
        ),
        Index("idx_usage_events_tenant_created", "tenant_id", "created_at"),
    )

class WebhookLog(Base):
    __tablename__ = "webhook_logs"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    stripe_event_id: Mapped[str] =  mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    event_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)