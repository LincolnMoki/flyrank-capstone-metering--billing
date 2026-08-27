"""Pricing service facade for the canonical config-based calculation."""

from app.core.config import calculate_cost_microcents

calculate_usage_cost = calculate_cost_microcents

__all__ = ["calculate_usage_cost"]
